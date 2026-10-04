"""The seed config passes, and known-bad changes fail. Run: python3 -m unittest discover -s tests"""
import shutil
import sys
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
