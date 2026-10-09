"""The seed config passes, and known-bad changes fail. Run: python3 -m unittest discover -s tests"""
import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import qqcfg  # noqa: E402


class SeedConfig(unittest.TestCase):
    def test_seed_config_passes(self):
        errors, _ = qqcfg.validate(ROOT)
        self.assertEqual(errors, [])


class BadChangesFail(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for d in ("config", "schema", "generated", "templates"):
            shutil.copytree(ROOT / d, self.tmp / d)
        (self.tmp / ".github/workflows").mkdir(parents=True)
        for f in (ROOT / ".github/workflows").glob("qq-required-*"):
            shutil.copy(f, self.tmp / ".github/workflows")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def edit(self, rel, old, new):
        path = self.tmp / rel
        text = path.read_text()
        self.assertIn(old, text, f"test fixture drifted: {old!r} not in {rel}")
        path.write_text(text.replace(old, new, 1))

    def assertFails(self, needle):
        errors, _ = qqcfg.validate(self.tmp)
        self.assertTrue(any(needle in e for e in errors), f"expected {needle!r} in {errors}")

    def test_result_sink_must_be_pinned_by_commit(self):
        pinned = qqcfg.load(self.tmp)["pipelines"]["defaults"]["results"]["sink"]
        self.edit("config/pipelines.toml", pinned, pinned.split("@")[0] + "@main")
        self.assertFails("does not match")

    def test_other_qq_workflows_may_not_list_a_file_twice(self):
        repos = self.tmp / "config/repos.toml"  # the last [[repo]] is innernet, which lists qq-roll-land.yml
        repos.write_text(repos.read_text() + '[[repo.other_qq_workflows]]\nfile = "qq-roll-land.yml"\n'
                         'from = "quirq-ai/rollers"\nsha256 = "' + "0" * 64 + '"\n')
        self.assertFails("other_qq_workflows lists a file twice")

    def test_mistagged_todo_rejected(self):
        self.edit("config/org.toml", "TODO(suraj, v0)", "TODO(suraj, V0)")
        self.assertFails("--todos never lists it")

    def test_result_globs_stay_inside_the_workspace(self):
        for bad in ("/tmp/*.xml", "../x/*.xml", "results/../../x.xml", " results/*.xml"):
            with self.subTest(bad=bad):
                self.edit("config/kinds.toml", 'test_reports = ["results/junit.xml"]', f"test_reports = [{bad!r}]")
                self.assertFails("does not match")
                self.setUp()

    def test_test_reports_need_a_test_command(self):
        self.edit("config/kinds.toml", 'name = "node-app"', 'name = "node-app"\ntest_reports = ["out.xml"]')
        self.edit("config/kinds.toml", 'test = "pnpm typecheck"', '#')
        self.assertFails("test_reports without an interim test command")

    def test_one_queue_builder_per_repo(self):
        self.edit("config/pipelines.toml", 'pipeline = "postsubmit"', 'pipeline = "presubmit"')
        self.edit("config/pipelines.toml", 'triggers = ["land"]', 'triggers = ["queue"]')
        self.assertFails("several generated queue builders")

    def test_agent_cannot_promote_to_stable(self):
        self.edit("config/channels.toml", 'approval = "policy-owner"   # suraj', 'approval = "none"')
        self.assertFails("promotion to stable needs the policy-owner")

    def test_dev_needs_a_human_owner(self):
        self.edit("config/channels.toml", 'approval = "human-owner" # settled', 'approval = "owner" # settled')
        self.assertFails("a human owner approves promotion")

    def test_auto_revert_cap_cannot_exceed_ten(self):
        self.edit("config/auto_revert.toml", "daily_cap = 10", "daily_cap = 12")
        self.assertFails("daily_cap may not exceed 10")

    def test_test_failure_reverts_never_auto_submit(self):
        self.edit("config/auto_revert.toml", "submit_daily_limit = 0", "submit_daily_limit = 2")
        self.assertFails("test_failure submit_daily_limit")

    def test_auto_land_repos_must_be_known_repos(self):
        self.edit("config/auto_revert.toml", "auto_land_repos = []", 'auto_land_repos = ["nope"]')
        self.assertFails("auto_land_repos names unknown repo 'nope'")

    def test_auto_land_repos_accepts_a_known_repo(self):
        self.edit("config/auto_revert.toml", "auto_land_repos = []", 'auto_land_repos = ["xo-space"]')
        errors, _ = qqcfg.validate(self.tmp)
        self.assertEqual(errors, [])

    def test_required_workflow_must_match_its_builder(self):
        path = self.tmp / ".github/workflows/qq-required-innernet-presubmit.yml"
        path.write_text(path.read_text().replace("pnpm typecheck", "true"))
        self.assertFails(".github/workflows/qq-required-innernet-presubmit.yml: out of date")
        path.unlink()
        self.assertFails(".github/workflows/qq-required-innernet-presubmit.yml: missing")

    def test_stale_required_workflow_fails(self):
        (self.tmp / ".github/workflows/qq-required-gone-presubmit.yml").write_text("name: x\n")
        self.assertFails("qq-required-gone-presubmit.yml: stale")

    def test_toolchain_action_must_be_pinned_by_commit(self):
        self.edit("config/kinds.toml", "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020", "actions/setup-node@v7")
        self.assertFails("does not match")

    def test_unknown_kind_rejected(self):
        self.edit("config/repos.toml", 'kinds = ["node-app"]', 'kinds = ["rust-app"]')
        self.assertFails("unknown kind 'rust-app'")

    def test_containers_come_later(self):
        self.edit("config/repos.toml", 'kinds = ["node-app"]', 'kinds = ["node-app", "container-image"]')
        self.assertFails("not available yet")

    def test_untrusted_pool_holds_no_secrets(self):
        self.edit("config/org.toml", "secrets = []", 'secrets = ["deploy"]')
        self.assertFails("untrusted pool holds no secrets")

    def test_unknown_backend_rejected(self):
        self.edit("config/pipelines.toml", 'backend = "github"', 'backend = "jenkins"')
        self.assertFails("unknown backend 'jenkins'")

    def test_typo_is_a_schema_error(self):
        self.edit("config/gate.toml", "max_minutes = 40", "max_minutes = 40\nmax_minuets = 40")
        self.assertFails("max_minuets")

    def test_required_copy_over_gate_ruleset_cap_rejected(self):
        # Even a non-blocking presubmit gets an org-required copy, and gate's rulesets refuse jobs over max_minutes.
        self.edit("config/pipelines.toml", "blocking = true\ntimeout_minutes = 20\ngenerate = true\n\n[[builder]]\nname = \"innernet-postsubmit\"",
                  "blocking = false\ntimeout_minutes = 41\ngenerate = true\n\n[[builder]]\nname = \"innernet-postsubmit\"")
        self.assertFails("org-required copy may not run longer than gate admission max_minutes (40)")

    def test_other_qq_workflow_may_not_shadow_a_stub(self):
        self.edit("config/repos.toml", 'file = "qq-roll-land.yml"\nfrom = "quirq-ai/rollers"   # V0-ROL-02; xo-space',
                  'file = "qq-xo-space-presubmit.yml"\nfrom = "quirq-ai/rollers"   # V0-ROL-02; xo-space')
        self.assertFails("is a generated builder's stub")

    def test_other_qq_workflow_may_not_shadow_a_required_copy(self):
        self.edit("config/repos.toml", 'file = "qq-roll-land.yml"\nfrom = "quirq-ai/rollers"   # V0-ROL-02; xo-space',
                  'file = "qq-required-xo-space-presubmit.yml"\nfrom = "quirq-ai/rollers"   # V0-ROL-02; xo-space')
        self.assertFails("is a generated builder's stub")

    def test_hand_edited_generated_file_rejected(self):
        self.edit("generated/github/xo-space/qq-xo-space-presubmit.yml", "timeout-minutes: 20", "timeout-minutes: 90")
        self.assertFails("out of date")

    def test_missing_area_rejected(self):
        (self.tmp / "config/perf.toml").unlink()
        self.assertFails("config/perf.toml: required area is missing")

    def test_missing_required_field_rejected(self):
        self.edit("config/repos.toml", 'visibility = "public"\n', "")
        self.assertFails("'visibility' is a required property")

    def test_unknown_repo_reference_rejected(self):
        self.edit("config/pipelines.toml", 'repo = "innernet"', 'repo = "innernet-typo"')
        self.assertFails("unknown repo 'innernet-typo'")

    def test_release_builder_cannot_skip_human_approval(self):
        # A builder that deploys to stable on every landing would bypass suraj's promotion.
        self.edit("config/pipelines.toml", "# --- innernet", "\n".join([
            "[[builder]]", 'name = "xo-space-stable-deploy"', 'repo = "xo-space"', 'pipeline = "release"',
            'triggers = ["land"]', 'channel = "stable"', 'kinds = ["python-service"]',
            'capabilities = ["deploy"]', 'pool = "trusted"', "", "# --- innernet"]))
        self.assertFails("release builder 'xo-space-stable-deploy' would deploy to 'stable'")

    def test_auto_revert_window_cannot_shrink(self):
        # 10 per rolling hour would be 240 a day.
        self.edit("config/auto_revert.toml", "window_hours = 24", "window_hours = 1")
        self.assertFails("window_hours may not be under 24")

    def test_auto_revert_lands_only_clean_reverts(self):
        self.edit("config/auto_revert.toml", "only_clean_reverts = true", "only_clean_reverts = false")
        self.assertFails("only clean reverts")

    def test_pr_code_never_runs_with_secrets(self):
        # A non-presubmit builder triggered by a change still runs PR code.
        self.edit("config/pipelines.toml", 'pipeline = "postsubmit"\ntriggers = ["land"]',
                  'pipeline = "postsubmit"\ntriggers = ["land", "change"]')
        self.assertFails("runs PR code")

    def test_all_thirteen_infra_repos_listed(self):
        self.edit("config/org.toml", '[[infra_repo]]\nname = "perf"', '[[infra_repo]]\nname = "perf-typo"')
        self.assertFails("infra repo 'perf' is missing")

    def test_infra_repos_are_public(self):
        self.edit("config/org.toml", 'visibility = "public"', 'visibility = "private"')
        self.assertFails("infra_repo/0/visibility")

    def test_infra_repo_source_matches_name(self):
        self.edit("config/org.toml", 'source = "github.com/quirq-ai/sync"', 'source = "github.com/quirq-ai/gclient"')
        self.assertFails("infra repo 'sync' source must be")

    def test_sources_match_quirq_ai_exactly(self):
        for rel, old, new in (("config/org.toml", 'source = "github.com/quirq-ai/qq"', 'source = "github.com/Quirq-AI/qq"'),
                              ("config/repos.toml", 'source = "github.com/quirq-ai/xo-space"',
                               'source = "github.com/QUIRQ-AI/xo-space"')):
            with self.subTest(new=new):
                self.edit(rel, old, new)
                self.assertFails("source")
                self.assertTrue(qqcfg.validate(self.tmp)[0])
                self.edit(rel, new, old)

    def test_infra_repo_is_not_a_product_repo(self):
        self.edit("config/repos.toml", 'name = "innernet"', 'name = "perf"')
        self.edit("config/pipelines.toml", 'repo = "innernet"', 'repo = "perf"')
        self.assertFails("'perf' is both an infra repo and a product repo")

    def test_v0_signals_are_ci_only(self):
        self.edit("config/health.toml", 'phase = "v1"\nsource = "posthog"', 'phase = "v0"\nsource = "posthog"')
        self.assertFails("v0 uses CI signals only")

    def test_every_canary_repo_has_a_probe(self):
        self.edit("config/health.toml", 'repo = "innernet"\npath = "/"', 'repo = "xo-space"\npath = "/"')
        self.assertFails("repo 'innernet' ships on 'canary' but has no probe")

    def test_missing_probe_data_never_passes(self):
        self.edit("config/health.toml", 'missing_data = "hold"', 'missing_data = "pass"')
        self.assertFails("canary/missing_data")

    def test_postmortem_template_must_exist(self):
        (self.tmp / "templates/postmortem.md").unlink()
        self.assertFails("template 'templates/postmortem.md' does not exist")

    def test_canary_smoke_covers_property_tests(self):
        self.edit("config/fuzz.toml", "canary_minutes = 15", "canary_minutes = 30")
        self.assertFails("canary_smoke duration_minutes must cover")

    def test_every_tested_toolchain_has_a_property_test_library(self):
        self.edit("config/fuzz.toml", 'node = "fast-check"      # MIT\n', "")
        self.assertFails("names no library for toolchain 'node'")

    def test_property_tests_for_unknown_toolchain_rejected(self):
        self.edit("config/fuzz.toml", 'node = "fast-check"', 'rust = "proptest"')
        self.assertFails("property_tests library for unknown toolchain 'rust'")

    def test_dependabot_roller_needs_an_ecosystem(self):
        self.edit("config/rollers.toml", 'ecosystem = "pip"               # Dependabot package-ecosystem\n', "")
        self.assertFails("'ecosystem' is a required property")



class Readers(unittest.TestCase):
    def setUp(self):
        self.cfg = qqcfg.load(ROOT)

    def test_get_reads_a_dotted_key(self):
        self.assertIsInstance(qqcfg.get(self.cfg, "org", "budget.monthly_ci_usd"), (int, float))

    def test_get_finds_array_items_by_name(self):
        self.assertEqual(qqcfg.get(self.cfg, "channels", "channel.canary.audience"), ["agents"])

    def test_get_reports_a_missing_key(self):
        with self.assertRaisesRegex(qqcfg.ConfigError, "org.budget.nope: not found"):
            qqcfg.get(self.cfg, "org", "budget.nope")

    def test_unowned_lists_rotations(self):
        self.assertIn("rotations", qqcfg.unowned(self.cfg))

    def test_v0_todos_are_marked(self):
        self.assertTrue(any("TODO(suraj, v0)" in t for t in qqcfg.todos(ROOT)))


class Delivery(unittest.TestCase):
    """V0-CFG-02: generated stubs land in a product repo, and a hand edit there fails its presubmit."""

    def setUp(self):
        self.cfg = qqcfg.load(ROOT)
        self.dest = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dest)

    def drift_check(self):
        return subprocess.run(["bash", "-c", qqcfg.DRIFT_CHECK], cwd=self.dest, capture_output=True, text=True)

    def test_every_v0_repo_gets_presubmit_and_postsubmit(self):
        for repo in ("xo-space", "innernet"):
            names = {Path(k).name for k in qqcfg.render(self.cfg) if k.startswith(f"github/{repo}/")}
            self.assertEqual(names, {f"qq-{repo}-presubmit.yml", f"qq-{repo}-postsubmit.yml"})

    def test_delivered_stubs_pass_the_drift_check(self):
        qqcfg.deliver(self.cfg, "innernet", self.dest)
        self.assertEqual(self.drift_check().returncode, 0)

    def test_hand_edit_in_product_repo_fails_the_drift_check(self):
        qqcfg.deliver(self.cfg, "xo-space", self.dest)
        stub = self.dest / ".github/workflows/qq-xo-space-presubmit.yml"
        stub.write_text(stub.read_text().replace("timeout-minutes: 20", "timeout-minutes: 90"))
        result = self.drift_check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("was edited by hand", result.stdout)

    def _with_roll_land(self, text):
        # A config whose xo-space other_qq_workflows entry records the digest of `text`.
        import copy, hashlib
        cfg = copy.deepcopy(self.cfg)
        entry = next(o for o in qqcfg.by_name(cfg["repos"]["repo"])["xo-space"]["other_qq_workflows"]
                     if o["file"] == "qq-roll-land.yml")
        entry["sha256"] = hashlib.sha256(text.encode()).hexdigest()
        roll = self.dest / ".github/workflows/qq-roll-land.yml"
        roll.parent.mkdir(parents=True, exist_ok=True)
        roll.write_text(text)
        return cfg, roll

    def test_other_tools_qq_workflows_are_left_alone(self):
        # rollers delivers qq-roll-land.yml (V0-ROL-02); deliver must not delete it, nor qq-drift flag it.
        body = "name: qq roll land\non: pull_request\njobs:\n  land:\n    runs-on: ubuntu-24.04\n    steps: []\n"
        cfg, roll = self._with_roll_land(body)
        self.assertNotIn("removed .github/workflows/qq-roll-land.yml", qqcfg.deliver(cfg, "xo-space", self.dest))
        self.assertTrue(roll.exists())
        self.assertEqual(qqcfg.check_delivered(cfg, "xo-space", self.dest), [])
        # Absent is fine (not delivered yet).
        roll.unlink()
        self.assertEqual(qqcfg.check_delivered(cfg, "xo-space", self.dest), [])

    def test_other_qq_workflow_must_match_its_digest(self):
        # Audit F1: a reviewed product PR may not weaken another tool's workflow unnoticed.
        body = "name: qq roll land\non: pull_request\njobs:\n  land:\n    runs-on: ubuntu-24.04\n    steps: []\n"
        cfg, roll = self._with_roll_land(body)
        qqcfg.deliver(cfg, "xo-space", self.dest)
        roll.write_text(body.replace("steps: []", "steps: [{run: 'true'}]"))
        self.assertTrue(any("qq-roll-land.yml: differs from the digest" in e
                            for e in qqcfg.check_delivered(cfg, "xo-space", self.dest)))

    def test_other_qq_workflow_still_may_not_take_a_check_name(self):
        body = "name: x\non: pull_request\njobs:\n  xo-space-presubmit:\n    runs-on: ubuntu-24.04\n    steps: []\n"
        cfg, _ = self._with_roll_land(body)  # even with a matching digest
        qqcfg.deliver(cfg, "xo-space", self.dest)
        self.assertTrue(any("only its generated stub may define" in e
                            for e in qqcfg.check_delivered(cfg, "xo-space", self.dest)))

    def test_symlinked_workflows_are_refused(self):
        # Audit F3: never read or write through a symlink.
        import os
        qqcfg.deliver(self.cfg, "xo-space", self.dest)
        wf = self.dest / ".github/workflows"
        outside = self.dest / "elsewhere.yml"
        outside.write_text("name: x\non: push\njobs: {}\n")
        os.symlink(outside, wf / "extra.yml")
        self.assertTrue(any("extra.yml: is a symlink" in e
                            for e in qqcfg.check_delivered(self.cfg, "xo-space", self.dest)))
        os.symlink(outside, wf / "qq-old.yml")
        with self.assertRaises(qqcfg.ConfigError):
            qqcfg.deliver(self.cfg, "xo-space", self.dest)

    def test_symlinked_workflow_directories_are_refused(self):
        # Audit F3/R3: a .github or workflows directory that is a symlink is neither read nor written.
        import os
        real = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, real)
        qqcfg.deliver(self.cfg, "xo-space", real)  # exact bytes, so only the link itself can fail
        for linked in (".github", ".github/workflows"):
            with self.subTest(linked=linked):
                shutil.rmtree(self.dest)
                (self.dest / linked).parent.mkdir(parents=True, exist_ok=True)
                os.symlink(real / linked, self.dest / linked)
                self.assertTrue(any("is or sits under a symlink" in e
                                    for e in qqcfg.check_delivered(self.cfg, "xo-space", self.dest)))
                with self.assertRaises(qqcfg.ConfigError):
                    qqcfg.deliver(self.cfg, "xo-space", self.dest)

    def test_listing_is_exact_and_never_covers_a_qqcfg_stub(self):
        qqcfg.deliver(self.cfg, "xo-space", self.dest)
        wf = self.dest / ".github/workflows"
        body = "name: x\non: push\njobs:\n  land:\n    runs-on: ubuntu-24.04\n    steps: []\n"
        for name, text in [("QQ-Roll-Land.yml", body), ("qq-roll-land.yaml", body),
                           ("qq-roll-land.yml", "# GENERATED by qqcfg\n" + body)]:
            (wf / name).write_text(text)
            errors = qqcfg.check_delivered(self.cfg, "xo-space", self.dest)
            self.assertTrue(any(name in e and "not generated" in e for e in errors), (name, errors))
            (wf / name).unlink()

    def test_unlisted_qq_workflow_still_fails_drift(self):
        other = self.dest / ".github/workflows/qq-something-else.yml"
        other.parent.mkdir(parents=True)
        other.write_text("name: x\non: push\njobs: {}\n")
        qqcfg.deliver(self.cfg, "xo-space", self.dest)
        self.assertFalse(other.exists())  # deliver drops unlisted qq-* files as stale stubs
        qqcfg.deliver(self.cfg, "xo-space", self.dest)
        other.write_text("name: x\non: push\njobs: {}\n")
        self.assertTrue(any("qq-something-else.yml: not generated" in e
                            for e in qqcfg.check_delivered(self.cfg, "xo-space", self.dest)))

    def test_deliver_removes_stale_stubs_and_is_idempotent(self):
        stale = self.dest / ".github/workflows/qq-old-builder.yml"
        stale.parent.mkdir(parents=True)
        stale.write_text("old")
        self.assertIn("removed .github/workflows/qq-old-builder.yml", qqcfg.deliver(self.cfg, "innernet", self.dest))
        self.assertEqual(qqcfg.deliver(self.cfg, "innernet", self.dest), [])

    def test_checks_run_the_step_as_generated(self):
        # Parse the YAML so a quoting or indent regression in render() is caught, not just DRIFT_CHECK.
        import yaml
        for path, text in qqcfg.render(self.cfg).items():
            doc = yaml.safe_load(text)
            steps = next(iter(doc["jobs"].values()))["steps"]
            drift = [s["run"] for s in steps if "drift" in s.get("name", "")]
            self.assertEqual(drift, [qqcfg.DRIFT_CHECK + "\n"], path)

    def test_test_builders_end_with_the_result_sink(self):
        # V0-TST-01: results are stored even when a test step fails, so the sink runs if: always()
        # (post-submit: unless a backfill was refused before testing anything).
        import yaml
        sink = self.cfg["pipelines"]["defaults"]["results"]["sink"]
        for b in self.cfg["pipelines"]["builder"]:
            if not b.get("generate"):
                continue
            doc = yaml.safe_load(qqcfg.render(self.cfg)[f"github/{b['repo']}/qq-{b['name']}.yml"])
            last = next(iter(doc["jobs"].values()))["steps"][-1]
            if "test" in b["capabilities"]:
                want_if = ("always() && (github.event_name != 'workflow_dispatch' || steps.qq-backfill.outcome == 'success')"
                           if b["pipeline"] == "postsubmit" else "always()")
                self.assertEqual((last.get("uses"), last.get("if")), (sink, want_if), b["name"])
                kinds = qqcfg.by_name(self.cfg["kinds"]["kind"])
                want = [g for k in b["kinds"] if "test" in kinds[k].get("interim", {})
                        for g in kinds[k].get("test_reports", [f"results/qq/{k}.xml"])]
                self.assertEqual(last["with"]["junit"].split(), want, b["name"])
            else:
                self.assertNotEqual(last.get("uses"), sink, b["name"])

    def test_test_without_junit_gets_a_one_case_report(self):
        # Audit S5: a typecheck writes no JUnit, so its outcome becomes the report, not "no results".
        import yaml
        doc = yaml.safe_load(qqcfg.render(self.cfg)["github/innernet/qq-innernet-presubmit.yml"])
        steps = doc["jobs"]["innernet-presubmit"]["steps"]
        test = next(s for s in steps if s.get("name") == "test (node-app)")
        report = next(s for s in steps if s.get("name") == "qq test report (node-app)")
        self.assertEqual(test["id"], "qq-test-node-app")
        self.assertIn("steps.qq-test-node-app.outcome == 'success'", report["if"])
        self.assertNotIn("cancelled", report["if"])  # a superseded run is not a test failure
        self.assertEqual(report["env"]["OUTCOME"], "${{ steps.qq-test-node-app.outcome }}")
        for outcome, failed in (("success", False), ("failure", True)):
            out = self.dest / "results/qq/node-app.xml"
            subprocess.run(["bash", "-c", report["run"]], cwd=self.dest, env={"OUTCOME": outcome, "PATH": "/usr/bin:/bin"},
                           check=True)
            self.assertEqual("<failure" in out.read_text(), failed, outcome)

    def test_postsubmit_has_no_concurrency_group(self):
        # A group keeps one pending run, so bursty landings (or a repeated backfill) would drop verdicts.
        import yaml
        doc = yaml.safe_load(qqcfg.render(self.cfg)["github/xo-space/qq-xo-space-postsubmit.yml"])
        self.assertNotIn("concurrency", doc)

    def test_postsubmit_can_be_dispatched_for_a_commit(self):
        # V0-GAR-01: the gardener backfills main commits a batched push skipped.
        import yaml
        for repo in ("xo-space", "innernet"):
            doc = yaml.safe_load(qqcfg.render(self.cfg)[f"github/{repo}/qq-{repo}-postsubmit.yml"])
            on = doc[True]  # YAML 1.1 reads the key `on` as true
            self.assertTrue(on["workflow_dispatch"]["inputs"]["commit"]["required"])
            self.assertEqual(doc["run-name"], f"{repo}-postsubmit ${{{{ inputs.commit || github.sha }}}}")
            steps = doc["jobs"][f"{repo}-postsubmit"]["steps"]
            self.assertEqual((steps[0]["name"], steps[0]["id"]), ("qq backfill commit check", "qq-backfill"))
            self.assertEqual(steps[1]["with"]["ref"], "${{ inputs.commit || github.sha }}")
            sink = next(st for st in steps if st.get("name") == "qq result sink")
            # A refused backfill tested nothing, so it must not write to the write-once store (audit S1).
            self.assertEqual((sink["if"], sink["with"]["commit"], sink["with"]["kind"]),
                             ("always() && (github.event_name != 'workflow_dispatch' || steps.qq-backfill.outcome == 'success')",
                              "${{ inputs.commit || github.sha }}", "postsubmit"))

    def test_backfill_check_rejects_a_dispatch_from_another_ref(self):
        script = qqcfg.BACKFILL_CHECK.format(branch="main")
        for ref in ("refs/heads/feature", "refs/heads/main-x", ""):
            r = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                               env={"COMMIT": "a" * 40, "GITHUB_REF": ref, "PATH": "/usr/bin:/bin"})
            self.assertEqual(r.returncode, 1, ref)
            self.assertIn("dispatch backfills from main", r.stdout, ref)

    def test_backfill_check_rejects_a_short_or_odd_commit(self):
        script = qqcfg.BACKFILL_CHECK.format(branch="main")
        for bad in ("abc123", "main", "$(id)", "A" * 40):
            r = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                               env={"COMMIT": bad, "GITHUB_REF": "refs/heads/main", "PATH": "/usr/bin:/bin"})
            self.assertEqual(r.returncode, 1, bad)
            self.assertIn("full 40-character SHA", r.stdout, bad)

    def test_required_copies_run_the_presubmit_in_its_repo_only(self):
        # Rollers audit R-2: an org ruleset pins these by commit, so a product PR can't edit its tests away.
        import yaml
        req = qqcfg.render(self.cfg, required=True)
        stubs = qqcfg.render(self.cfg)
        d = self.cfg["pipelines"]["defaults"]
        pre = [b for b in self.cfg["pipelines"]["builder"] if b.get("generate") and b["pipeline"] == "presubmit"]
        self.assertEqual(sorted(req), sorted(f".github/workflows/qq-required-{b['name']}.yml" for b in pre))
        for b in pre:
            doc = yaml.safe_load(req[f".github/workflows/qq-required-{b['name']}.yml"])
            stub = yaml.safe_load(stubs[f"github/{b['repo']}/qq-{b['name']}.yml"])
            job = doc["jobs"][f"{b['name']}-pinned"]
            self.assertEqual(job["if"], f"github.repository == 'quirq-ai/{b['repo']}'")
            self.assertEqual(doc[True], stub[True])
            self.assertNotIn("concurrency", doc)  # a ruleset workflow must not be cancelled in progress
            self.assertNotIn("cancel-in-progress", req[f".github/workflows/qq-required-{b['name']}.yml"])
            self.assertLessEqual(job["timeout-minutes"], self.cfg["gate"]["admission"]["max_minutes"])  # gate's ruleset cap
            self.assertEqual(doc["permissions"], {"contents": "read"})
            # Same commands; timing and result storage stay with the stub so nothing is stored twice.
            runs = [st.get("run") for st in job["steps"]]
            extra = {d["timing"], d["results"]["sink"]}
            stub_runs = [st.get("run") for st in next(iter(stub["jobs"].values()))["steps"]
                         if st.get("uses") not in extra and not st.get("name", "").startswith("qq test report")]
            self.assertEqual(runs, stub_runs, b["name"])
            self.assertFalse(any("sink" in str(st.get("uses")) or "timing" in str(st.get("uses")) for st in job["steps"]))

    def test_this_repos_workflows_pin_actions_and_qq_drift_pins_its_config(self):
        # Audit F2: qq-drift runs qqcfg from the commit its ruleset pins, not from main at run time.
        import re
        for p in (ROOT / ".github/workflows").glob("*.yml"):
            for ref in re.findall(r"uses: (\S+)", p.read_text()):
                self.assertRegex(ref, r"@[0-9a-f]{40}$", p.name)
        drift = (ROOT / ".github/workflows/qq-drift.yml").read_text()
        self.assertIn("ref: ${{ github.workflow_sha }}", drift)
        self.assertNotIn("ref: main", drift)

    def test_generated_actions_are_pinned_by_commit(self):
        import re
        for path, text in {**qqcfg.render(self.cfg), **qqcfg.render(self.cfg, required=True)}.items():
            for ref in re.findall(r"uses: (\S+)", text):
                self.assertRegex(ref, r"@[0-9a-f]{40}$", path)

    def test_only_queue_builders_get_the_gate_timing_step(self):
        import yaml
        timing = self.cfg["pipelines"]["defaults"]["timing"]
        for b in self.cfg["pipelines"]["builder"]:
            if not b.get("generate"):
                continue
            doc = yaml.safe_load(qqcfg.render(self.cfg)[f"github/{b['repo']}/qq-{b['name']}.yml"])
            steps = next(iter(doc["jobs"].values()))["steps"]
            got = [st for st in steps if st.get("uses") == timing]
            if "queue" in b["triggers"]:
                self.assertEqual([(st["if"], st["timeout-minutes"], st["continue-on-error"]) for st in got],
                                 [("always() && github.event_name == 'merge_group'", 3, True)], b["name"])
                self.assertEqual(doc["permissions"], {"contents": "read", "pull-requests": "read"})
            else:
                self.assertEqual(got, [], b["name"])
                self.assertEqual(doc["permissions"], {"contents": "read"})

    def test_check_delivered_passes_a_fresh_delivery(self):
        for repo in ("xo-space", "innernet"):
            qqcfg.deliver(self.cfg, repo, self.dest)
            self.assertEqual(qqcfg.check_delivered(self.cfg, repo, self.dest), [])
            shutil.rmtree(self.dest / ".github")

    def test_check_delivered_catches_an_edit_that_also_drops_the_drift_step(self):
        qqcfg.deliver(self.cfg, "xo-space", self.dest)
        stub = self.dest / ".github/workflows/qq-xo-space-presubmit.yml"
        stub.write_text(stub.read_text().replace("qq drift check", "renamed step"))
        self.assertTrue(any("differs from infra-config" in e for e in qqcfg.check_delivered(self.cfg, "xo-space", self.dest)))

    def test_check_delivered_catches_a_renamed_stub(self):
        qqcfg.deliver(self.cfg, "innernet", self.dest)
        wf = self.dest / ".github/workflows"
        (wf / "qq-innernet-presubmit.yml").rename(wf / "innernet-ci.yaml")
        errors = qqcfg.check_delivered(self.cfg, "innernet", self.dest)
        self.assertTrue(any("qq-innernet-presubmit.yml: missing" in e for e in errors), errors)
        self.assertTrue(any("innernet-ci.yaml: not generated" in e for e in errors), errors)

    def test_check_delivered_catches_a_second_check_with_a_generated_name(self):
        # Audit S2: any YAML spelling of the job, or another job id carrying the name, is a second check.
        spoofs = {
            "plain": "jobs:\n  innernet-presubmit:\n    runs-on: x\n",
            "quoted": 'jobs:\n  "innernet-presubmit":\n    runs-on: x\n',
            "comment": "jobs:\n  innernet-presubmit:   # mine\n    runs-on: x\n",
            "flow": "jobs: {innernet-presubmit: {runs-on: x}}\n",
            "renamed": "jobs:\n  other:\n    name: innernet-presubmit\n    runs-on: x\n",
            "null name": "jobs:\n  innernet-presubmit:\n    name: ~\n    runs-on: x\n",
            "case": "jobs:\n  other:\n    name: ' Innernet-Presubmit'\n",
        }
        qqcfg.deliver(self.cfg, "innernet", self.dest)
        for label, text in spoofs.items():
            with self.subTest(label):
                for f in (self.dest / ".github/workflows").glob("fake*"):
                    f.unlink()
                (self.dest / f".github/workflows/fake.{'YML' if label == 'case' else 'yaml'}").write_text(text)
                self.assertTrue(any("defines check" in e
                                    for e in qqcfg.check_delivered(self.cfg, "innernet", self.dest)), label)

    def test_check_delivered_rejects_expression_names_and_bad_yaml(self):
        qqcfg.deliver(self.cfg, "innernet", self.dest)
        fake = self.dest / ".github/workflows/fake.yml"
        fake.write_text("jobs:\n  a:\n    name: ${{ format('{0}-presubmit', 'innernet') }}\n")
        self.assertTrue(any("is an expression" in e for e in qqcfg.check_delivered(self.cfg, "innernet", self.dest)))
        fake.write_text("jobs: [unclosed\n")
        self.assertTrue(any("not valid YAML" in e for e in qqcfg.check_delivered(self.cfg, "innernet", self.dest)))

    def test_check_delivered_accepts_an_older_generation_with_a_warning(self):
        # Audit S3: stubs from an earlier main pass within the grace window, so open PRs stay green.
        qqcfg.deliver(self.cfg, "innernet", self.dest)
        wf = self.dest / ".github/workflows"
        old = {p.name: p.read_text().replace("timeout-minutes: 20", "timeout-minutes: 19") for p in wf.glob("qq-*")}
        for name, text in old.items():
            (wf / name).write_text(text)
        self.assertTrue(qqcfg.check_delivered(self.cfg, "innernet", self.dest))  # not main's, no history
        warnings = []
        self.assertEqual(qqcfg.check_delivered(self.cfg, "innernet", self.dest, [old], warnings.append), [])
        self.assertTrue(any("redeliver" in w for w in warnings))
        (wf / "qq-innernet-presubmit.yml").write_text("hand edit")  # a mix of neither still fails
        self.assertTrue(qqcfg.check_delivered(self.cfg, "innernet", self.dest, [old]))

    def test_check_delivered_compares_bytes(self):
        qqcfg.deliver(self.cfg, "innernet", self.dest)
        stub = self.dest / ".github/workflows/qq-innernet-presubmit.yml"
        stub.write_bytes(stub.read_bytes().replace(b"\n", b"\r\n"))
        self.assertTrue(any("differs" in e for e in qqcfg.check_delivered(self.cfg, "innernet", self.dest)))

    def test_pr_changes_stubs_reads_the_merge_commit(self):
        # Review of audit S3: the grace window is only for PRs that leave the stubs alone.
        repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, repo)
        wf = repo / ".github/workflows"
        wf.mkdir(parents=True)
        git = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                        check=True, capture_output=True)
        git("init", "-q")
        (wf / "qq-innernet-presubmit.yml").write_text("old")
        git("add", "-A"); git("commit", "-qm", "base")
        self.assertTrue(qqcfg.pr_changes_stubs(repo))  # no parent: fail closed
        (wf / "tests.yml").write_text("mine")
        git("add", "-A"); git("commit", "-qm", "other workflow")
        self.assertFalse(qqcfg.pr_changes_stubs(repo))
        (wf / "qq-innernet-presubmit.yml").unlink()
        git("add", "-A"); git("commit", "-qm", "drop a stub")
        self.assertTrue(qqcfg.pr_changes_stubs(repo))
        git("reset", "-q", "--hard", "HEAD~1")
        (wf / "qq-innernet-presubmit.yml").rename(wf / "other.yml")  # a rename still counts
        git("add", "-A"); git("commit", "-qm", "rename a stub")
        self.assertTrue(qqcfg.pr_changes_stubs(repo))
        base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD~2"], capture_output=True, text=True).stdout.strip()
        (wf / "README").write_text("x")
        git("add", "-A"); git("commit", "-qm", "later commit")  # HEAD^1 alone would miss the rename
        self.assertFalse(qqcfg.pr_changes_stubs(repo))
        self.assertTrue(qqcfg.pr_changes_stubs(repo, base))

    def test_generations_reads_stubs_that_were_current_in_the_window(self):
        repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, repo)
        gen = repo / "generated/github/innernet"
        gen.mkdir(parents=True)
        git = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                        check=True, capture_output=True)
        git("init", "-q")
        for text in ("one", "two"):
            (gen / "qq-innernet-presubmit.yml").write_text(text)
            git("add", "-A")
            git("commit", "-qm", text)
        self.assertEqual(qqcfg.generations(repo, "innernet", 7), [{"qq-innernet-presubmit.yml": "one"}])
        self.assertEqual(qqcfg.generations(repo, "xo-space", 7), [])

    def test_check_delivered_cli_passes_other_base_branches(self):
        # Audit S4: stubs live on the default branch only, so a PR into development has none to check.
        self.assertEqual(qqcfg.main(["check-delivered", "xo-space", str(self.dest), "--base", "development"]), 0)
        self.assertEqual(qqcfg.main(["check-delivered", "xo-space", str(self.dest), "--base", "refs/heads/main"]), 1)

    def test_check_delivered_ignores_repos_with_nothing_delivered(self):
        self.assertEqual(qqcfg.check_delivered(self.cfg, "infra-config", self.dest), [])

    def test_deliver_leaves_hand_written_workflows_alone(self):
        own = self.dest / ".github/workflows/tests.yml"
        own.parent.mkdir(parents=True)
        own.write_text("mine")
        qqcfg.deliver(self.cfg, "xo-space", self.dest)
        self.assertEqual(own.read_text(), "mine")


class UserOrg(unittest.TestCase):
    """One-command setup: a user's org keeps only data (config/, generated/) in <org>/qq-config, and
    qqcfg from this checkout validates and generates it with --root. quirq-ai's output never changes."""

    QQ_CONFIG = ('[[infra_repo]]\nname = "qq-config"\nsource = "github.com/acme/qq-config"\n'
                 'visibility = "public"\nwave = 1\nowns = "acme\'s qq config."\nchromium = "infra/config"\n'
                 'owners = []\n\n')

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(ROOT / "config", self.tmp / "config")  # data only: no schema/, tools/ or templates/
        org = self.tmp / "config/org.toml"
        text = org.read_text().replace('code_host = "github.com/quirq-ai"', 'code_host = "github.com/acme"', 1)
        first, last = text.index("[[infra_repo]]"), text.rindex("[[infra_repo]]")
        rest = text[last:]
        rest = rest[re.search(r"\n\n(?=[#\[])", rest).end():]  # what follows the last infra repo
        org.write_text(text[:first] + self.QQ_CONFIG + rest)
        repos = self.tmp / "config/repos.toml"
        repos.write_text(repos.read_text().replace('source = "github.com/quirq-ai/', 'source = "github.com/acme/'))
        self.generate()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def generate(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(qqcfg.main(["generate", "--root", str(self.tmp)]), 0)

    def edit(self, rel, old, new):
        path = self.tmp / rel
        text = path.read_text()
        self.assertIn(old, text, f"test fixture drifted: {old!r} not in {rel}")
        path.write_text(text.replace(old, new, 1))

    def assertFails(self, needle):
        errors, _ = qqcfg.validate(self.tmp)
        self.assertTrue(any(needle in e for e in errors), f"expected {needle!r} in {errors}")

    def test_data_only_user_org_validates_and_generates(self):
        errors, _ = qqcfg.validate(self.tmp)
        self.assertEqual(errors, [])
        self.assertFalse((self.tmp / ".github").exists(), "a user org gets no qq-required-* org copies")
        stubs = sorted((self.tmp / "generated").rglob("*.yml"))
        self.assertTrue(stubs)
        cfg = qqcfg.load(self.tmp)
        for path in stubs:
            text = path.read_text()
            self.assertTrue(text.startswith("# GENERATED by qqcfg (tools/qqcfg.py generate) from acme/qq-config."))
            self.assertIn("Change acme/qq-config and redeliver it.", text)
            self.assertNotIn("quirq-ai/infra-config", text)
        presubmit = (self.tmp / "generated/github/xo-space/qq-xo-space-presubmit.yml").read_text()
        for pin in (cfg["pipelines"]["defaults"]["results"]["sink"], cfg["pipelines"]["defaults"]["timing"]):
            self.assertTrue(pin.startswith("quirq-ai/"), pin)  # tool pins never follow code_host
            self.assertIn(f"uses: {pin}", presubmit)

    def test_user_stubs_pass_their_own_drift_check(self):
        dest = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, dest)
        qqcfg.deliver(qqcfg.load(self.tmp), "xo-space", dest)
        ok = subprocess.run(["bash", "-c", qqcfg.drift_check("acme/qq-config")], cwd=dest,
                            capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertEqual(qqcfg.check_delivered(qqcfg.load(self.tmp), "xo-space", dest), [])

    def test_product_source_must_name_this_org(self):
        self.edit("config/repos.toml", 'source = "github.com/acme/xo-space"', 'source = "github.com/other/xo-space"')
        self.assertFails("xo-space: source must be github.com/acme/xo-space")

    def test_infra_source_must_name_this_org(self):
        self.edit("config/org.toml", 'source = "github.com/acme/qq-config"', 'source = "github.com/quirq-ai/qq-config"')
        self.assertFails("infra repo 'qq-config' source must be github.com/acme/qq-config")

    def test_zero_infra_repos_rejected(self):
        self.edit("config/org.toml", self.QQ_CONFIG, "")
        self.assertFails("'infra_repo' is a required property")

    def test_only_qq_config_may_be_an_infra_repo(self):
        for bad in (self.QQ_CONFIG.replace("qq-config", "gate"),
                    self.QQ_CONFIG + self.QQ_CONFIG.replace("qq-config", "qq")):
            with self.subTest(bad=bad):
                self.edit("config/org.toml", self.QQ_CONFIG, bad)
                self.assertFails("lists exactly one infra repo, 'qq-config'")
                self.edit("config/org.toml", bad, self.QQ_CONFIG)

    def test_quirq_ai_may_not_drop_to_qq_config(self):
        self.edit("config/org.toml", 'code_host = "github.com/acme"', 'code_host = "github.com/quirq-ai"')
        self.assertFails("infra repo 'qq' is missing")

    def test_code_host_is_one_host_and_org(self):
        for bad in ("github.com/acme/x", "github.com/acme/", "github.com/ac me", "acme", "www.github.com/acme",
                    "gitlab.com/acme"):
            with self.subTest(bad=bad):
                self.edit("config/org.toml", 'code_host = "github.com/acme"', f"code_host = {bad!r}")
                self.assertFails("org/code_host")
                self.edit("config/org.toml", f"code_host = {bad!r}", 'code_host = "github.com/acme"')

    def test_user_org_gets_no_required_copies_and_names_qq_config(self):
        cfg = qqcfg.load(self.tmp)
        self.assertEqual(qqcfg.render(cfg, required=True), {})
        self.assertEqual(qqcfg.config_repo(cfg), "acme/qq-config")
        self.assertEqual(qqcfg.config_repo(qqcfg.load(ROOT)), "quirq-ai/infra-config")

    def test_code_host_may_not_end_in_a_newline(self):
        self.edit("config/org.toml", 'code_host = "github.com/acme"', 'code_host = "github.com/acme\\n"')
        self.assertFails("must be exactly github.com/<org>")
        with self.assertRaises(qqcfg.ConfigError):
            qqcfg.render(qqcfg.load(self.tmp))

    def test_sources_compare_exactly(self):
        self.edit("config/repos.toml", 'source = "github.com/acme/xo-space"', 'source = "github.com/ACME/xo-space"')
        self.assertFails("repo/0/source")  # the schema wants a lower-case owner
        self.edit("config/repos.toml", 'source = "github.com/ACME/xo-space"', 'source = "github.com/acme/XO-space"')
        self.assertFails("xo-space: source must be github.com/acme/xo-space")  # qqcfg compares exactly

    def test_quirq_ai_in_any_casing_is_quirq_ai(self):
        self.edit("config/org.toml", 'code_host = "github.com/acme"', 'code_host = "github.com/Quirq-AI"')
        self.assertFails("org/code_host")  # the schema wants a lower-case owner
        cfg = qqcfg.load(self.tmp)
        self.assertTrue(qqcfg.is_quirq(cfg))  # and if it ever got past, the thirteen would still apply
        errors = []
        qqcfg.check_refs(self.tmp, cfg, errors.append)
        self.assertTrue(any("write code_host as 'github.com/quirq-ai'" in e for e in errors), errors)
        self.assertTrue(any("infra repo 'qq' is missing" in e for e in errors), errors)

    def test_bad_code_host_is_a_clean_error_in_every_command(self):
        self.edit("config/org.toml", 'code_host = "github.com/acme"', 'code_host = "github.com/acme\\n"')
        dest = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, dest)
        for argv in (["generate"], ["check-delivered", "xo-space", str(dest)], ["deliver", "xo-space", str(dest)]):
            with self.subTest(argv=argv):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    self.assertEqual(qqcfg.main([*argv, "--root", str(self.tmp)]), 1)
                self.assertIn("github.com/<org>", out.getvalue() + err.getvalue())

    def test_tool_pins_cannot_leave_quirq_ai_by_path(self):
        pin = qqcfg.load(self.tmp)["pipelines"]["defaults"]["results"]["sink"]
        sha = pin.split("@")[1]
        for bad in (f"quirq-ai/test-pipelines/../../../evil/sink@{sha}", f"quirq-ai/../x@{sha}",
                    f"quirq-ai/.@{sha}", f"quirq-ai/..@{sha}", f"quirq-ai/test.pipelines/sink@{sha}",
                    f"quirq-ai/\uff47ate@{sha}", f"quirq-ai/test-pipelines/sink@{sha}\n"):
            with self.subTest(bad=bad):
                self.edit("config/pipelines.toml", f'sink = "{pin}"', f"sink = {json.dumps(bad)}")
                errors, _ = qqcfg.validate(self.tmp)
                self.assertTrue(errors)
                cfg = qqcfg.load(self.tmp)
                refs = []
                qqcfg.check_refs(self.tmp, cfg, refs.append)  # the fullmatch holds even past the schema
                self.assertTrue(any("must be a quirq-ai tool pinned by commit" in e for e in refs), refs)
                self.edit("config/pipelines.toml", f"sink = {json.dumps(bad)}", f'sink = "{pin}"')

    def test_tool_pins_stay_quirq_ai(self):
        for key in ("sink", "timing"):
            with self.subTest(key=key):
                pin = qqcfg.load(self.tmp)["pipelines"]["defaults"]["results" if key == "sink" else "timing"]
                pin = pin["sink"] if key == "sink" else pin
                self.edit("config/pipelines.toml", pin, pin.replace("quirq-ai/", "acme/", 1))
                self.assertFails("does not match")
                self.edit("config/pipelines.toml", pin.replace("quirq-ai/", "acme/", 1), pin)

    def test_quirq_checkout_cannot_switch_to_user_org_mode(self):
        # Config alone never turns off the thirteen-repo rule: the default --root must be quirq-ai.
        with mock.patch.object(qqcfg, "ROOT", self.tmp.resolve()):
            self.assertFails("this checkout is quirq's own config")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(qqcfg.main(["generate", "--root", str(self.tmp)]), 1)


class Golden(unittest.TestCase):
    """render() is pinned: quirq-ai's config at tests/golden/config (infra-config 41a8cb0) must render
    exactly the files infra-config 41a8cb0 generated. Each stub's qq-digest covers every byte, header
    included, so a change here flags every delivered stub as hand-edited. A PR that means to change
    the output updates tests/golden/ (a policy path) in the same diff, where review sees it."""

    GOLDEN = ROOT / "tests/golden"

    def test_render_matches_the_golden_output(self):
        cfg = qqcfg.load(self.GOLDEN)
        made = {f"generated/{k}": v for k, v in qqcfg.render(cfg).items()}
        made.update(qqcfg.render(cfg, required=True))
        have = {p.relative_to(self.GOLDEN).as_posix(): p.read_text()
                for p in [*(self.GOLDEN / "generated").rglob("*"), *(self.GOLDEN / ".github/workflows").glob("*")]
                if p.is_file()}
        self.assertEqual(sorted(made), sorted(have))
        for path in have:
            self.assertEqual(made[path], have[path], path)

    def test_golden_config_is_quirq_ai(self):
        self.assertEqual(qqcfg.load(self.GOLDEN)["org"]["org"]["code_host"], qqcfg.QUIRQ_HOST)


class DriftWorkflow(unittest.TestCase):
    """qq-drift.yml's own guards (audit F2, R1-R3): each test fails if its guard is removed or weakened."""

    WF = ROOT / ".github/workflows/qq-drift.yml"
    SHA = "0123456789abcdef0123456789abcdef01234567"
    REF = "quirq-ai/infra-config/.github/workflows/qq-drift.yml@refs/heads/main"

    def setUp(self):
        import yaml
        self.job = yaml.safe_load(self.WF.read_text())["jobs"]["qq-drift"]
        self.steps = self.job["steps"]

    def step(self, prefix):
        return next(st for st in self.steps if st.get("name", "").startswith(prefix))

    def run_step(self, prefix, env, cwd=None):
        # As GitHub runs a `run:` step: bash -eo pipefail, the step's env only.
        st = self.step(prefix)
        return subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", st["run"]],
                              env={"PATH": "/usr/bin:/bin", **env}, cwd=cwd, capture_output=True, text=True)

    def test_guard_accepts_only_this_file_from_infra_config(self):
        ok = [self.REF, f"quirq-ai/infra-config/.github/workflows/qq-drift.yml@{self.SHA}"]
        bad = ["", "quirq-ai/xo-space/.github/workflows/qq-drift.yml@refs/pull/218/merge",
               "quirq-ai/xo-space/.github/workflows/qq-drift.yml@refs/heads/gh-readonly-queue/main/pr-1-abc",
               "evil/infra-config/.github/workflows/qq-drift.yml@refs/heads/main",
               "quirq-ai/infra-config/.github/workflows/qq-drift.yml.bak@refs/heads/main",
               "quirq-ai/infra-config/.github/workflows/validate.yml@refs/heads/main",
               "Quirq-AI/infra-config/.github/workflows/qq-drift.yml@refs/heads/main"]
        for ref in ok + bad:
            with self.subTest(ref=ref):
                r = self.run_step("refuse a run that is not", {"WORKFLOW_REF": ref, "WORKFLOW_SHA": self.SHA})
                self.assertEqual(r.returncode, 0 if ref in ok else 1, r.stdout + r.stderr)

    def test_guard_requires_a_full_workflow_sha(self):
        # Audit R1 case C: an empty SHA would check out main at run time.
        for sha in ["", self.SHA[:7], self.SHA.upper(), self.SHA + "0", f"{self.SHA}\n", "refs/heads/main"]:
            with self.subTest(sha=sha):
                r = self.run_step("refuse a run that is not", {"WORKFLOW_REF": self.REF, "WORKFLOW_SHA": sha})
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_commit_check_requires_the_pin_on_infra_config_main(self):
        # Audit R1 case D: the checked-out commit must be the pin and on main, not a fork's commit.
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        repo = tmp / "infra-config"
        env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t",
               "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

        def git(*a):
            return subprocess.run(["git", "-C", str(repo), *a], env={"PATH": "/usr/bin:/bin", **env},
                                  check=True, capture_output=True, text=True).stdout.strip()

        repo.mkdir()
        git("init", "-q", "-b", "main")
        git("commit", "-q", "--allow-empty", "-m", "a")
        older = git("rev-parse", "HEAD")
        git("commit", "-q", "--allow-empty", "-m", "b")
        on_main = git("rev-parse", "HEAD")
        git("update-ref", "refs/remotes/origin/main", on_main)
        git("commit", "-q", "--allow-empty", "-m", "fork")
        off_main = git("rev-parse", "HEAD")
        # A tag named origin/main would win over the branch for a short ref; the check must not take it.
        git("tag", "origin/main", off_main)

        def check(head, sha):
            git("checkout", "-q", "--detach", head)
            return self.run_step("refuse an infra-config commit", {"WORKFLOW_SHA": sha, **env}, cwd=tmp)

        self.assertEqual(check(on_main, on_main).returncode, 0)
        self.assertEqual(check(on_main, off_main).returncode, 1)  # not what was asked for
        self.assertEqual(check(on_main, older).returncode, 1)  # not what was asked for, though on main
        self.assertEqual(check(off_main, off_main).returncode, 1)  # not on main
        self.assertEqual(check(on_main, "").returncode, 1)
        # With no main branch, a tag named like the remote ref must not stand in for it.
        git("update-ref", "-d", "refs/remotes/origin/main")
        git("tag", "refs/remotes/origin/main", on_main)
        self.assertEqual(check(on_main, on_main).returncode, 1)

    def test_guards_run_first_and_cannot_be_skipped(self):
        names = [st.get("name", st.get("uses", st.get("run", ""))) for st in self.steps]
        self.assertTrue(names[0].startswith("refuse a run that is not"), names)
        checkout = next(i for i, st in enumerate(self.steps)
                        if st.get("with", {}).get("repository") == "quirq-ai/infra-config")
        commit = names.index(self.step("refuse an infra-config commit")["name"])
        python = next(i for i, st in enumerate(self.steps) if "python" in str(st.get("run", "")))
        self.assertLess(checkout, commit)
        self.assertLess(commit, python)
        self.assertEqual(self.job["if"], "github.repository != 'quirq-ai/infra-config'")
        self.assertNotIn("continue-on-error", self.job)
        for st in self.steps:
            self.assertNotIn("continue-on-error", st, st)
            self.assertNotIn("if", st, st)
        for prefix in ("refuse a run that is not", "refuse an infra-config commit"):
            self.assertEqual(self.step(prefix)["env"]["WORKFLOW_SHA"], "${{ github.workflow_sha }}")
        self.assertEqual(self.step("refuse a run that is not")["env"]["WORKFLOW_REF"], "${{ github.workflow_ref }}")
        self.assertEqual(self.steps[checkout]["with"]["ref"], "${{ github.workflow_sha }}")
        self.assertEqual(self.steps[checkout]["with"]["fetch-depth"], 0)

    def test_installs_only_hashed_pyyaml(self):
        # Audit R2: nothing unpinned or unhashed runs inside the required check.
        installs = [st["run"] for st in self.steps if "pip" in str(st.get("run", ""))]
        self.assertEqual(len(installs), 1, installs)
        # Whole arguments, so "-r infra-config/requirements-drift.txt.bak" or a second -r does not pass.
        args = installs[0].split()
        self.assertEqual(args[:4], ["python", "-m", "pip", "install"], args)
        self.assertEqual(sorted(args[4:]), sorted(["--quiet", "--require-hashes", "--no-deps",
                                                   "--only-binary", ":all:", "-r", "infra-config/requirements-drift.txt"]), args)
        self.assertEqual(args[args.index("--only-binary") + 1], ":all:")
        self.assertEqual(args[args.index("-r") + 1], "infra-config/requirements-drift.txt")
        lines = [l.strip() for l in (ROOT / "requirements-drift.txt").read_text().splitlines()
                 if l.strip() and not l.lstrip().startswith("#")]
        self.assertEqual(lines[0], "pyyaml==6.0.3 \\")
        self.assertTrue(all(re.fullmatch(r"--hash=sha256:[0-9a-f]{64}( \\)?", l) for l in lines[1:]), lines)

    def test_validate_installs_only_a_hashed_lock(self):
        # Audit follow-up: infra-config's own CI installs nothing unpinned either.
        doc = __import__("yaml").safe_load((ROOT / ".github/workflows/validate.yml").read_text())
        installs = [st["run"] for st in doc["jobs"]["validate"]["steps"] if "pip" in str(st.get("run", ""))]
        self.assertEqual(len(installs), 1, installs)
        # Whole arguments, so "-r requirements.txt.bak" or a second -r does not pass.
        args = installs[0].split()
        self.assertEqual(args[:4], ["python", "-m", "pip", "install"], args)
        self.assertEqual(sorted(args[4:]), sorted(["--quiet", "--require-hashes", "--no-deps",
                                                   "--only-binary", ":all:", "-r", "requirements.txt"]), args)
        self.assertEqual(args[args.index("--only-binary") + 1], ":all:")
        self.assertEqual(args[args.index("-r") + 1], "requirements.txt")
        reqs = re.split(r"\n(?=\S)", "\n".join(l for l in (ROOT / "requirements.txt").read_text().splitlines()
                                              if l.strip() and not l.startswith("#")))
        self.assertTrue(reqs)
        for req in reqs:
            self.assertRegex(req, r"^\S+==\S+", req)
            self.assertIn("--hash=sha256:", req)

    def test_check_delivered_needs_nothing_but_pyyaml(self):
        dest = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, dest)
        qqcfg.deliver(qqcfg.load(ROOT), "innernet", dest)
        env = {"PATH": "/usr/bin:/bin", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "base"],
                     ["add", "-A"], ["commit", "-q", "-m", "deliver"]):
            subprocess.run(["git", "-C", str(dest), *args], env=env, check=True, capture_output=True)
        # The workflow's own arguments, --history included, with jsonschema unimportable.
        argv = ["check-delivered", "innernet", str(dest), "--base", "main", "--base-sha", "", "--history"]
        code = ("import sys; sys.modules.update(jsonschema=None, referencing=None); "
                f"sys.path.insert(0, {str(ROOT / 'tools')!r}); import qqcfg; sys.exit(qqcfg.main({argv!r}))")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
