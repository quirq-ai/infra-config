#!/usr/bin/env python3
"""qqcfg: validate and generate quirq infra (qq) config. The small counterpart of Chromium's lucicfg.

    python3 tools/qqcfg.py validate [--todos]   schema, cross-references, policy invariants,
                                                and generated files in sync. Exit 1 on any error.
    python3 tools/qqcfg.py generate             rewrite generated/<backend>/ from config/.
    python3 tools/qqcfg.py get AREA [KEY.PATH]  print an area, or one value in it, as JSON, for readers
                                                outside Python (the scorecard reads org budget this way).
    python3 tools/qqcfg.py deliver REPO DIR     copy REPO's generated workflows into the checkout at DIR.
    python3 tools/qqcfg.py check-delivered REPO DIR   fail if DIR's workflows drift from what REPO gets.

Config is TOML: parsed, never executed. Needs Python 3.11+ (tomllib) and jsonschema (requirements.txt).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Every area must exist. Adding an area means adding config/<area>.toml and schema/<area>.schema.json.
REQUIRED_AREAS = ("org", "kinds", "repos", "pipelines", "gate", "flakes", "auto_revert",
                  "rollers", "channels", "fuzz", "postmortem", "health", "perf")

# The thirteen quirq infra repos (plan §5.5; D3 builds them all). org.toml [[infra_repo]] must list
# exactly these. Renaming, adding or dropping one is a plan change, so it is a change to this line.
QQ_REPOS = ("depot", "sync", "recipes", "infra-config", "test-pipelines", "gate", "toolchains",
            "remote-build", "gardener", "rollers", "release", "installer", "perf")

# Settled policy that config alone cannot loosen. Changing these lines is itself a policy change,
# and this file is a policy path (CODEOWNERS), so it needs the policy-owner.
AUTO_REVERT_DAILY_CAP = 10  # suraj's number (D5); counting reverts created is a default he can change
LUCI_CAPS = {  # failure type: (max reverts created per day, max auto-submitted per day); luci-bisection.cfg
    "build_failure": (10, 4),
    "test_failure": (10, 0),
}
MAX_CULPRIT_AGE_HOURS = 6
AGENT_ALONE_CLASSES = {"clean-revert", "dependency-roll", "docs"}
HUMAN_APPROVALS = {"human-owner", "policy-owner"}
UNLANDED_TRIGGERS = {"change", "queue"}  # run code from an open change, before it lands

# A TODO names who decides (suraj or expert) and, optionally, the version that needs it: "suraj, v0".
TODO_RE = re.compile(r"TODO\((suraj|expert)(?:,\s*(v\d+))?\):\s*(.+)")


class ConfigError(Exception):
    pass


# --- loading ---------------------------------------------------------------------------------

def load(root: Path) -> dict:
    cfg = {}
    for path in sorted((root / "config").glob("*.toml")):
        try:
            cfg[path.stem] = tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"config/{path.name}: {e}") from None
    return cfg


def by_name(items: list[dict]) -> dict[str, dict]:
    return {i["name"]: i for i in items}


# --- checks ----------------------------------------------------------------------------------

def check_schema(root: Path, cfg: dict, err) -> None:
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    schemas = {p.name.removesuffix(".schema.json"): json.loads(p.read_text())
               for p in (root / "schema").glob("*.schema.json")}
    registry = Registry().with_resources(
        (s["$id"], Resource.from_contents(s)) for s in schemas.values())
    for area in REQUIRED_AREAS:
        if area not in cfg:
            err(f"config/{area}.toml: required area is missing")
    for area in sorted((set(schemas) - {"area"}) | set(cfg)):
        if area not in schemas:
            err(f"config/{area}.toml: no schema/{area}.schema.json")
            continue
        if area not in cfg:
            if area not in REQUIRED_AREAS:
                err(f"schema/{area}.schema.json: no config/{area}.toml")
            continue
        validator = Draft202012Validator(schemas[area], registry=registry)
        for e in sorted(validator.iter_errors(cfg[area]), key=lambda e: list(map(str, e.absolute_path))):
            where = "/".join(str(p) for p in e.absolute_path) or "(top level)"
            err(f"config/{area}.toml: {where}: {e.message}")
        if cfg[area].get("area", {}).get("name") != area:
            err(f"config/{area}.toml: [area] name must be {area!r}")


def check_refs(root: Path, cfg: dict, err) -> None:
    backends = by_name(cfg["org"]["backend"])
    toolchains = by_name(cfg["kinds"]["toolchain"])
    kinds = by_name(cfg["kinds"]["kind"])
    repos = by_name(cfg["repos"]["repo"])
    pools = by_name(cfg["org"]["pool"])
    scopes = by_name(cfg["org"]["secret_scope"])
    chans = cfg["channels"]["channel"]
    signals = by_name(cfg["health"]["signal"])
    builders = cfg["pipelines"]["builder"]
    defaults = cfg["pipelines"]["defaults"]
    events = {t["event"] for t in cfg["postmortem"]["trigger"]}

    for label, items in [("backends", cfg["org"]["backend"]), ("toolchains", cfg["kinds"]["toolchain"]),
                         ("kinds", cfg["kinds"]["kind"]), ("repos", cfg["repos"]["repo"]),
                         ("org pools", cfg["org"]["pool"]), ("pipelines builders", builders),
                         ("channels", chans), ("health signals", cfg["health"]["signal"]),
                         ("fuzz schedules", cfg["fuzz"]["schedule"]), ("rollers", cfg["rollers"]["roller"]),
                         ("perf benchmarks", cfg["perf"]["benchmark"]),
                         ("org infra repos", cfg["org"]["infra_repo"]),
                         ("health probes", cfg["health"]["probe"])]:
        names = [i["name"] for i in items]
        for dup in sorted({n for n in names if names.count(n) > 1}):
            err(f"{label}: duplicate name {dup!r}")

    for where, b in [("org default_backend", cfg["org"]["org"]["default_backend"]),
                     ("pipelines defaults backend", defaults["backend"]),
                     ("gate merge_queue backend", cfg["gate"]["merge_queue"]["backend"]),
                     *((f"pipelines: builder {x['name']!r} backend", x["backend"]) for x in builders if "backend" in x)]:
        if b not in backends:
            err(f"{where}: unknown backend {b!r} (see org.toml [[backend]])")
    infra = by_name(cfg["org"]["infra_repo"])
    for name in QQ_REPOS:
        if name not in infra:
            err(f"org: infra repo {name!r} is missing (plan §5.5 lists thirteen)")
    for name, r in infra.items():
        if name not in QQ_REPOS:
            err(f"org: infra repo {name!r} is not one of the plan's thirteen")
        if r["source"] != f"{cfg['org']['org']['code_host']}/{name}":
            err(f"org: infra repo {name!r} source must be {cfg['org']['org']['code_host']}/{name}")
        if name in repos:
            err(f"org: {name!r} is both an infra repo and a product repo (repos.toml)")
    for k in kinds.values():
        if "toolchain" in k and k["toolchain"] not in toolchains:
            err(f"kinds: {k['name']}: unknown toolchain {k['toolchain']!r}")
    for t in cfg["fuzz"]["engine"]:
        if t not in toolchains:
            err(f"fuzz: engine for unknown toolchain {t!r}")

    for pool in pools.values():
        for s in pool["secrets"]:
            if s not in scopes:
                err(f"org: pool {pool['name']!r} names unknown secret scope {s!r}")
    if cfg["health"]["posthog"]["secret_scope"] not in scopes:
        err("health: posthog secret_scope is not an org.toml secret_scope")

    chan_names = [c["name"] for c in chans]
    for k in kinds.values():
        if "test_reports" in k and "test" not in k.get("interim", {}):
            err(f"kinds: {k['name']}: test_reports without an interim test command that writes them")
    for r in repos.values():
        for k in r["kinds"]:
            if k not in kinds:
                err(f"repos: {r['name']}: unknown kind {k!r} (see kinds.toml)")
            elif kinds[k]["phase"] != "year-one":
                err(f"repos: {r['name']}: kind {k!r} is phase {kinds[k]['phase']!r}, not available yet")
        for c in r["channels"]:
            if c not in chan_names:
                err(f"repos: {r['name']}: unknown channel {c!r}")

    max_minutes = cfg["gate"]["admission"]["max_minutes"]
    for b in builders:
        where = f"pipelines: builder {b['name']!r}"
        repo = repos.get(b["repo"])
        if repo is None:
            err(f"{where}: unknown repo {b['repo']!r}")
            continue
        for k in b["kinds"]:
            if k not in repo["kinds"]:
                err(f"{where}: kind {k!r} is not one of repo {repo['name']!r}'s kinds")
        offered = set().union(*(kinds[k]["capabilities"] for k in b["kinds"] if k in kinds))
        for cap in b["capabilities"]:
            if cap not in offered:
                err(f"{where}: no kind in {b['kinds']} offers capability {cap!r}")
        if b["pool"] not in pools:
            err(f"{where}: unknown pool {b['pool']!r}")
        if "channel" in b and b["channel"] not in chan_names:
            err(f"{where}: unknown channel {b['channel']!r}")
        if b.get("blocking") and b.get("timeout_minutes", defaults["timeout_minutes"]) > max_minutes:
            err(f"{where}: a blocking builder may not run longer than gate admission max_minutes ({max_minutes})")

    for r in repos:
        mine = [b for b in builders if b["repo"] == r]
        if not any(b["pipeline"] == "presubmit" and b.get("blocking")
                   and {"change", "queue"} <= set(b["triggers"]) for b in mine):
            err(f"repos: {r}: needs a blocking presubmit builder triggered on change and queue")
        if cfg["gate"]["admission"]["needs_postsubmit_mirror"] and not any(b["pipeline"] == "postsubmit" for b in mine):
            err(f"repos: {r}: needs a postsubmit builder (gate admission needs a post-submit mirror)")
        if chan_names[0] in repos[r]["channels"] and not any(
                b["pipeline"] == "release" and b.get("channel") == chan_names[0] for b in mine):
            err(f"repos: {r}: ships on {chan_names[0]!r} but has no release builder for it")

    if chans[0]["from"] != cfg["channels"]["source"]["ref"]:
        err(f"channels: {chans[0]['name']!r} must come from source ref {cfg['channels']['source']['ref']!r}")
    for prev, ch in zip(chans, chans[1:]):
        if ch["from"] != prev["name"]:
            err(f"channels: {ch['name']!r} must come from {prev['name']!r}, the channel before it")
    for ch in chans:
        for s in ch["promotion"]["health_signals"]:
            if s not in signals:
                err(f"channels: {ch['name']!r} names unknown health signal {s!r}")

    for label, items, key in [("health signal", cfg["health"]["signal"], "repos"),
                              ("roller", cfg["rollers"]["roller"], "repos"),
                              ("fuzz schedule", cfg["fuzz"]["schedule"], "repo"),
                              ("perf benchmark", cfg["perf"]["benchmark"], "repo")]:
        for item in items:
            for r in item[key] if isinstance(item[key], list) else [item[key]]:
                if r not in repos:
                    err(f"{label} {item['name']!r}: unknown repo {r!r}")
    for p in cfg["health"]["probe"]:
        if p["repo"] not in repos:
            err(f"health probe {p['name']!r}: unknown repo {p['repo']!r}")
    for r in repos.values():
        if chan_names[0] in r["channels"] and not any(p["repo"] == r["name"] for p in cfg["health"]["probe"]):
            err(f"health: repo {r['name']!r} ships on {chan_names[0]!r} but has no probe (a missing signal holds it)")
    for s in cfg["health"]["signal"]:
        if s["phase"] == "v0" and s["source"] != "ci":
            err(f"health signal {s['name']!r}: v0 uses CI signals only; {s['source']!r} signals are phase v1")
    pt = cfg["fuzz"]["property_tests"]
    for tc in (k for k, v in pt.items() if isinstance(v, str)):
        if tc not in toolchains:
            err(f"fuzz: property_tests library for unknown toolchain {tc!r}")
    tested = {kinds[k]["toolchain"] for r in repos.values() for k in r["kinds"]
              if k in kinds and "test" in kinds[k]["capabilities"] and "toolchain" in kinds[k]}
    for tc in sorted(tested - set(pt)):
        err(f"fuzz: property_tests names no library for toolchain {tc!r}, which a repo tests with")
    if pt["gate_minutes"] > pt["canary_minutes"]:
        err("fuzz: property_tests gate_minutes may not exceed canary_minutes")
    if cfg["fuzz"]["canary_smoke"]["duration_minutes"] < pt["canary_minutes"]:
        err("fuzz: canary_smoke duration_minutes must cover property_tests canary_minutes")
    template = cfg["postmortem"]["policy"]["template"]
    if not (root / template).is_file():
        err(f"postmortem: template {template!r} does not exist in this repo")
    trig = [e["event"] for e in cfg["postmortem"]["trigger"]]
    for dup in sorted({e for e in trig if trig.count(e) > 1}):
        err(f"postmortem: duplicate trigger event {dup!r}")
    for s in cfg["fuzz"]["schedule"]:
        if s["pool"] not in pools:
            err(f"fuzz schedule {s['name']!r}: unknown pool {s['pool']!r}")
    for e in cfg["gate"]["tree_status"]["closes_on"]:
        if e not in events:
            err(f"gate: tree_status closes_on {e!r} is not a postmortem.toml trigger event")


def check_policy(cfg: dict, err) -> int:
    """Settled policy. Returns the number of invariants checked."""
    pools = by_name(cfg["org"]["pool"])
    chans = by_name(cfg["channels"]["channel"])
    classes = by_name(cfg["gate"]["change_class"])
    ar = cfg["auto_revert"]
    checks = 0

    def inv(ok: bool, msg: str) -> None:
        nonlocal checks
        checks += 1
        if not ok:
            err(f"policy: {msg}")

    inv(bool(cfg["org"]["roles"]["policy-owner"]), "org.toml [roles] policy-owner must name someone")
    stable = chans.get("stable", {}).get("promotion", {})
    inv(stable.get("approval") == "policy-owner", "promotion to stable needs the policy-owner (suraj)")
    inv(chans.get("canary", {}).get("audience") == ["agents"], "canary is for agents only")
    inv(chans.get("canary", {}).get("unattended") is True, "the daily canary deploy runs unattended")
    inv(sorted(chans.get("dev", {}).get("audience", [])) == ["agents", "humans"], "dev is for humans plus agents")
    for ch in chans.values():
        if ch["audience"] != ["agents"]:
            inv(ch["promotion"]["approval"] in HUMAN_APPROVALS,
                f"channel {ch['name']!r} reaches people, so a human owner approves promotion into it")
    inv(all(r["visibility"] == "public" for r in cfg["repos"]["repo"]), "public repos only for now")
    alone = {c["name"] for c in classes.values() if c["approval"] == "none"}
    inv(alone <= AGENT_ALONE_CLASSES,
        f"agents may land alone only {sorted(AGENT_ALONE_CLASSES)}; got {sorted(alone - AGENT_ALONE_CLASSES)}")
    inv(classes.get("policy", {}).get("approval") == "policy-owner", "policy changes need the policy-owner (suraj)")
    inv(cfg["gate"]["verification_surface"]["author_may_approve"] is False,
        "an author may not approve their own verification-surface change")
    cap = ar["policy"]["daily_cap"]
    inv(cap <= AUTO_REVERT_DAILY_CAP, f"auto_revert daily_cap may not exceed {AUTO_REVERT_DAILY_CAP}")
    inv(ar["policy"]["window_hours"] >= 24,
        "auto_revert window_hours may not be under 24, or daily_cap would allow more than "
        f"{AUTO_REVERT_DAILY_CAP} reverts a day")
    inv(ar["policy"]["only_clean_reverts"] is True,
        "auto_revert may land only clean reverts; a revert that needs edits is a normal change")
    for ftype, (create, submit) in LUCI_CAPS.items():
        caps = ar[ftype]
        inv(caps["create_daily_limit"] <= min(create, cap),
            f"auto_revert {ftype} create_daily_limit may not exceed {create} or daily_cap")
        inv(caps["submit_daily_limit"] <= min(submit, caps["create_daily_limit"]),
            f"auto_revert {ftype} submit_daily_limit may not exceed {submit} or the create limit")
        inv(caps["max_culprit_age_hours"] <= MAX_CULPRIT_AGE_HOURS,
            f"auto_revert {ftype} max_culprit_age_hours may not exceed {MAX_CULPRIT_AGE_HOURS}")
    inv(not pools.get("untrusted", {"secrets": ["missing"]})["secrets"], "the untrusted pool holds no secrets")
    for b in cfg["pipelines"]["builder"]:
        if b["pipeline"] == "presubmit" or UNLANDED_TRIGGERS & set(b["triggers"]):
            inv(not pools.get(b["pool"], {}).get("secrets", ["?"]),
                f"builder {b['name']!r} runs PR code (presubmit or a change/queue trigger), "
                "so its pool may hold no secrets")
        if b["pipeline"] == "release":
            # Every builder trigger fires without a person, so a release builder may feed only a
            # channel that promotes without one. Builds reach dev and stable by approved promotion.
            target = chans.get(b.get("channel"), {}).get("promotion", {}).get("approval")
            inv(target == "none",
                f"release builder {b['name']!r} would deploy to {b.get('channel')!r} on a trigger, "
                "but promotion into that channel needs approval (channels.toml)")
        if b["pipeline"] == "postsubmit":
            inv(b.get("cancel_in_progress") is not True, f"postsubmit builder {b['name']!r} is never cancelled")
    for s in cfg["fuzz"]["schedule"]:
        if s["mode"] == "code-change":
            inv(not pools.get(s["pool"], {}).get("secrets", ["?"]),
                f"fuzz schedule {s['name']!r} runs PR code, so its pool may hold no secrets")
    return checks


# --- generation (one backend: github; one example: builders with generate = true) -------------
# Everything GitHub-specific in this repo's tooling lives in this section.

CHECKOUT = "actions/checkout@v7"  # TODO(expert): pin actions by commit SHA (plan P5).
GITHUB_EVENTS = {"change": "pull_request", "queue": "merge_group", "land": "push"}
GENERATABLE = {"presubmit", "postsubmit"}  # release builders wait for the release executor (V0-REL-03)
WORKFLOWS = ".github/workflows"            # where deliver puts them in a product repo
DIGEST = "# qq-digest: sha256:"

# A step that fails when any delivered qq-*.yml no longer matches its digest line: a fast local signal.
# A PR can edit this step away in its own stub, so the binding check is check_delivered, run from
# this repo by .github/workflows/qq-drift.yml as an org-required workflow the PR cannot edit.
DRIFT_CHECK = r"""python3 - <<'PY'
import hashlib, pathlib, sys
bad = []
for p in sorted(pathlib.Path(".github/workflows").glob("qq-*.yml")):
    lines = p.read_text().splitlines(keepends=True)
    want = [l[len("# qq-digest: sha256:"):].strip() for l in lines if l.startswith("# qq-digest: sha256:")]
    body = "".join(l for l in lines if not l.startswith("# qq-digest: "))
    if want != [hashlib.sha256(body.encode()).hexdigest()]:
        bad.append(str(p))
for p in bad:
    print(f"::error file={p}::{p} was edited by hand. Change quirq-ai/infra-config and redeliver it.")
sys.exit(1 if bad else 0)
PY"""


# Writes a one-testcase JUnit report from a step's outcome ($OUTCOME). {path} and {case} come from
# config names (schema-restricted to [a-z0-9-]), so they need no XML or shell escaping.
ONE_CASE_REPORT = """mkdir -p "$(dirname "{path}")"
if [ "$OUTCOME" = success ]; then
  body=''
else
  body="<failure message=\\"step outcome: $OUTCOME\\"/>"
fi
printf '<?xml version="1.0" encoding="UTF-8"?>\\n<testsuite name="qq" tests="1"><testcase classname="qq" name="{case}">%s</testcase></testsuite>\\n' "$body" > "{path}"
"""


def with_digest(text: str) -> str:
    """Put the body's sha256 on line 3, after the two header comments. The drift check strips it again."""
    lines = text.splitlines(keepends=True)
    return "".join(lines[:2]) + DIGEST + hashlib.sha256(text.encode()).hexdigest() + "\n" + "".join(lines[2:])


def q(s: str) -> str:
    return json.dumps(s)  # a JSON string is a valid YAML double-quoted scalar


def render(cfg: dict) -> dict[str, str]:
    kinds = by_name(cfg["kinds"]["kind"])
    repos = by_name(cfg["repos"]["repo"])
    defaults = cfg["pipelines"]["defaults"]
    out = {}
    for b in cfg["pipelines"]["builder"]:
        if not b.get("generate"):
            continue
        where = f"builder {b['name']!r}"
        if b.get("backend", defaults["backend"]) != "github" or b["pipeline"] not in GENERATABLE:
            raise ConfigError(f"{where}: only {sorted(GENERATABLE)} builders on the github backend can be generated today")
        repo = repos[b["repo"]]
        names = {kinds[k].get("toolchain") for k in b["kinds"]} - {None}
        if len(names) != 1:
            raise ConfigError(f"{where}: a generated job needs exactly one toolchain, got {sorted(names)}")
        tc = by_name(cfg["kinds"]["toolchain"])[names.pop()]
        if "github" not in tc:
            raise ConfigError(f"{where}: toolchain {tc['name']!r} has no [toolchain.github] provisioning")
        steps = []
        for cap in b["capabilities"]:
            ran = False
            for k in b["kinds"]:
                if cap in kinds[k]["capabilities"] and cap in kinds[k].get("interim", {}):
                    steps.append((cap, k, kinds[k]["interim"][cap]))
                    ran = True
            if not ran:
                raise ConfigError(f"{where}: no interim command for {cap!r} in kinds {b['kinds']}")
        on = []
        for t in b["triggers"]:
            if t not in GITHUB_EVENTS:
                raise ConfigError(f"{where}: trigger {t!r} has no github mapping yet")
            on.append(f"  {GITHUB_EVENTS[t]}:")
            if t in ("change", "land"):
                on.append(f"    branches: [{q(repo['default_branch'])}]")
        lines = [
            "# GENERATED by qqcfg (tools/qqcfg.py generate) from quirq-ai/infra-config. Do not edit by hand.",
            f"# Source: config/pipelines.toml builder {q(b['name'])}. The job name is the required check.",
            f"name: {q('qq ' + b['name'])}",
            "on:", *on,
            "permissions:",
            "  contents: read",
            # A concurrency group keeps only one pending run even without cancelling, so builders that
            # must give every commit a verdict (post-submit) get no group at all.
            *(["concurrency:", f"  group: {q('qq-' + b['name'] + '-${{ github.ref }}')}", "  cancel-in-progress: true"]
              if b.get("cancel_in_progress", b["pipeline"] != "postsubmit") else []),
            "jobs:",
            f"  {b['name']}:",
            f"    runs-on: {q(by_name(cfg['org']['pool'])[b['pool']]['github']['runs_on'])}",
            f"    timeout-minutes: {b.get('timeout_minutes', defaults['timeout_minutes'])}",
            "    steps:",
            f"      - uses: {CHECKOUT}",
            f"      - uses: {tc['github']['uses']}",
            "        with:",
            f"          {tc['github']['version_input']}: {q(tc['pin'])}",
        ]
        if b["pipeline"] in GENERATABLE:
            lines += ['      - name: "qq drift check (generated workflows not hand-edited)"', "        run: |",
                      *("          " + line for line in DRIFT_CHECK.splitlines())]
        reports = []
        for cap, k, cmd in steps:
            lines.append(f"      - name: {q(f'{cap} ({k})')}")
            if cap == "test" and "test_reports" not in kinds[k]:
                lines.append(f"        id: {q(f'qq-test-{k}')}")
            lines.append(f"        run: {q(cmd)}")
        for cap, k, _ in steps:
            if cap != "test":
                continue
            if "test_reports" in kinds[k]:
                reports += kinds[k]["test_reports"]
                continue
            # A test command with no JUnit output (a typecheck, say) gets a one-case report from its
            # own outcome, so the run is stored as pass or fail, not as "no results" (audit S5). A
            # cancelled or skipped test step writes nothing, so it is not counted as a test failure.
            path = f"results/qq/{k}.xml"
            reports.append(path)
            lines += [f"      - name: {q(f'qq test report ({k})')}",
                      f"        if: always() && (steps.qq-test-{k}.outcome == 'success' || steps.qq-test-{k}.outcome == 'failure')",
                      "        env:", f"          OUTCOME: ${{{{ steps.qq-test-{k}.outcome }}}}",
                      "        run: |", *("          " + line for line in ONE_CASE_REPORT.format(
                          path=path, case=f"test ({k})").splitlines())]
        if reports:
            # V0-TST-01: store this run's test results even when a test step failed.
            lines += ['      - name: "qq result sink"', "        if: always()",
                      f"        uses: {defaults['results']['sink']}",
                      "        with:", "          junit: |", *(f"            {g}" for g in dict.fromkeys(reports))]
        out[f"github/{b['repo']}/qq-{b['name']}.yml"] = with_digest("\n".join(lines) + "\n")
    return out


def generations(root: Path, repo: str, days: int) -> list[dict[str, str]]:
    """Earlier sets of repo's stubs that were current on this checkout's branch within the last days.

    A set counts while it was current, so it is the parent tree of each commit in the window that
    changed generated/github/<repo>/. Needs a git checkout with that history (fetch-depth: 0).
    """
    import subprocess

    def git(*a: str) -> str:
        return subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True, text=True).stdout

    gen = f"generated/github/{repo}"
    out = []
    for c in git("log", "--format=%H", f"--since={days} days ago", "--", gen).split():
        try:
            names = git("ls-tree", "--name-only", f"{c}^", f"{gen}/").split()
        except subprocess.CalledProcessError:
            continue  # the first commit has no parent
        out.append({Path(n).name: git("show", f"{c}^:{n}") for n in names})
    return out


def workflow_checks(text: str) -> list[str]:
    """Check names a workflow file defines: each job's `name:`, or its id when it has none (as gate reads them)."""
    import yaml
    doc = yaml.safe_load(text) or {}
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    if not isinstance(jobs, dict):
        return []
    return [str(j.get("name", jid)) if isinstance(j, dict) else str(jid) for jid, j in jobs.items()]


def check_delivered(cfg: dict, repo: str, dest: Path, older: list[dict[str, str]] = (), warn=None) -> list[str]:
    """Compare a product repo's workflows with what infra-config generates for it (V0-CFG-02).

    The stubs must be byte-identical to what main generates, or to an older set in `older` (a grace
    window, so a generator change does not turn every open product PR red; `warn` hears about it).
    No other workflow may be a qqcfg stub, or define a check with a generated builder's name, under
    any job id, quoting or YAML style (renaming a stub does not escape the check). Returns errors.
    """
    if repo not in by_name(cfg["repos"]["repo"]):
        return []  # nothing is delivered to repos outside repos.toml, infra-config included
    prefix = f"github/{repo}/"
    want = {k[len(prefix):]: v for k, v in render(cfg).items() if k.startswith(prefix)}
    wf = dest / WORKFLOWS
    have = {p.name: p.read_text(errors="replace") for p in sorted(wf.glob("*")) if p.is_file()} if wf.is_dir() else {}
    errors = []
    checks = {re.sub(r"^qq-|\.yml$", "", n) for g in (want, *older) for n in g}
    stale = next((g for g in older if g and all(have.get(n) == t for n, t in g.items())), None)
    if stale is not None and any(have.get(n) != t for n, t in want.items()):
        if warn:
            warn(f"{repo}'s stubs come from an earlier infra-config main; redeliver with qqcfg deliver {repo}")
        want = stale
    for name, text in sorted(want.items()):
        if name not in have:
            errors.append(f"{WORKFLOWS}/{name}: missing; deliver it with qqcfg deliver {repo}")
        elif have[name] != text:
            errors.append(f"{WORKFLOWS}/{name}: differs from infra-config; change config there and redeliver")
    for name, text in have.items():
        if name in want:
            continue
        if name.startswith("qq-") or "GENERATED by qqcfg" in text:
            errors.append(f"{WORKFLOWS}/{name}: not generated for {repo}; remove it or redeliver")
        if not name.endswith((".yml", ".yaml")):
            continue
        try:
            found = workflow_checks(text)
        except Exception as e:  # yaml.YAMLError; GitHub would not run it, but say so rather than guess
            errors.append(f"{WORKFLOWS}/{name}: not valid YAML ({e.__class__.__name__}); fix it so qq-drift can read it")
            continue
        for c in found:
            if c in checks:
                errors.append(f"{WORKFLOWS}/{name}: defines check {c!r}, which only its generated stub may define")
            elif "${{" in c:
                errors.append(f"{WORKFLOWS}/{name}: job name {c!r} is an expression; use a literal so qq-drift can check it")
    return errors


def deliver(cfg: dict, repo: str, dest: Path) -> list[str]:
    """Write repo's generated workflows into a checkout and drop stale qq-*.yml. Returns what changed."""
    if repo not in by_name(cfg["repos"]["repo"]):
        raise ConfigError(f"no repo {repo!r} in repos.toml")
    prefix = f"github/{repo}/"
    want = {k[len(prefix):]: v for k, v in render(cfg).items() if k.startswith(prefix)}
    wf = dest / WORKFLOWS
    wf.mkdir(parents=True, exist_ok=True)
    changed = []
    for p in sorted(wf.glob("qq-*.yml")):
        if p.name not in want:
            p.unlink()
            changed.append(f"removed {WORKFLOWS}/{p.name}")
    for name, text in sorted(want.items()):
        p = wf / name
        if not p.exists() or p.read_text() != text:
            p.write_text(text)
            changed.append(f"wrote {WORKFLOWS}/{name}")
    return changed


def check_generated(root: Path, cfg: dict, err) -> int:
    want = render(cfg)
    gen = root / "generated"
    have = {p.relative_to(gen).as_posix(): p.read_text() for p in gen.rglob("*") if p.is_file()} if gen.exists() else {}
    for path in sorted(set(want) | set(have)):
        if path not in have:
            err(f"generated/{path}: missing; run python3 tools/qqcfg.py generate")
        elif path not in want:
            err(f"generated/{path}: no builder produces it; run python3 tools/qqcfg.py generate")
        elif have[path] != want[path]:
            err(f"generated/{path}: out of date; run python3 tools/qqcfg.py generate")
    return len(want)


# --- commands --------------------------------------------------------------------------------

def todos(root: Path) -> list[str]:
    found = []
    for path in sorted([*(root / "config").glob("*.toml"), *(root / "tools").glob("*.py")]):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            m = TODO_RE.search(line)
            if m:
                who = m.group(1) + (f", {m.group(2)}" if m.group(2) else "")
                found.append(f"{path.relative_to(root)}:{n}: TODO({who}): {m.group(3).strip()}")
    return found


def unowned(cfg: dict) -> dict[str, list[str]]:
    """Every owners list and rotation suraj has yet to fill (V0-ORG-02). Empty lists mean done."""
    return {
        "areas": sorted(a for a, c in cfg.items() if not c["area"]["owners"]),
        "product repos": [r["name"] for r in cfg["repos"]["repo"] if not r["owners"]],
        "infra repos": [r["name"] for r in cfg["org"]["infra_repo"] if not r["owners"]],
        "rotations": [r["name"] for r in cfg["org"]["rotation"] if not r["members"]],
    }


def get(cfg: dict, area: str, key: str | None = None):
    """One area, or one dotted key in it. Arrays of tables are addressed by their `name`."""
    if area not in cfg:
        raise ConfigError(f"no area {area!r}; areas: {', '.join(sorted(cfg))}")
    value, path = cfg[area], area
    for part in key.split(".") if key else []:
        path += "." + part
        if isinstance(value, list):
            value = next((i for i in value if isinstance(i, dict) and i.get("name") == part), None)
        elif isinstance(value, dict):
            value = value.get(part)
        else:
            value = None
        if value is None:
            raise ConfigError(f"{path}: not found")
    return value


def validate(root: Path) -> tuple[list[str], list[str]]:
    """Returns (errors, report lines). No errors means the config may land."""
    errors: list[str] = []
    report: list[str] = []
    try:
        cfg = load(root)
    except ConfigError as e:
        return [str(e)], report
    report.append(f"ok    parse      {len(cfg)} files in config/")
    n = len(errors)
    check_schema(root, cfg, errors.append)
    if len(errors) > n:
        return errors, report  # cross-reference checks assume a schema-valid config
    report.append(f"ok    schema     {len(cfg)} areas against schema/")
    check_refs(root, cfg, errors.append)
    refs_ok = len(errors) == n
    if refs_ok:
        report.append("ok    refs       repos, infra repos, kinds, pools, builders, channels, signals, probes, triggers")
    n = len(errors)
    checks = check_policy(cfg, errors.append)
    if len(errors) == n:
        report.append(f"ok    policy     {checks} invariants")
    n = len(errors)
    if refs_ok:  # generation assumes every reference resolves
        try:
            files = check_generated(root, cfg, errors.append)
            if len(errors) == n:
                report.append(f"ok    generated  {files} file(s) in sync")
        except ConfigError as e:
            errors.append(f"generate: {e}")
    stubs = sorted(a for a, c in cfg.items() if c["area"]["status"] == "stub")
    report.append(f"note  status     {len(cfg) - len(stubs)} seed, {len(stubs)} stub: {', '.join(stubs)}")
    empty = {k: v for k, v in unowned(cfg).items() if v}
    if empty:
        report.append("note  owners     empty, for suraj to fill (V0-ORG-02): "
                      + "; ".join(f"{len(v)} {k} ({', '.join(v)})" for k, v in empty.items()))
    else:
        report.append("ok    owners     every area, repo and rotation has owners")
    budget = cfg["org"]["budget"]["monthly_ci_usd"]
    report.append(f"note  budget     monthly CI ceiling {'not set (V0-ORG-04)' if not budget else f'${budget:g}'}")
    found = todos(root)
    v0 = sum(TODO_RE.search(t).group(2) == "v0" for t in found)
    for path in sorted((root / "config").glob("*.toml")):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"TODO\([^)]*\):", line) and not TODO_RE.search(line):
                errors.append(f"config/{path.name}:{n}: write TODO(suraj|expert[, vN]): text, or --todos never lists it")
    report.append(f"note  todos      {len(found)} open, {v0} needed for v0 (python3 tools/qqcfg.py validate --todos)")
    return errors, report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="qqcfg", description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["validate", "generate", "get", "deliver", "check-delivered"])
    ap.add_argument("target", nargs="?", help="get: the area, e.g. org; deliver, check-delivered: the product repo")
    ap.add_argument("detail", nargs="?", help="get: a dotted key, e.g. budget.monthly_ci_usd; deliver, check-delivered: path to that repo's checkout")
    ap.add_argument("--root", type=Path, default=ROOT, help="repo root (default: this checkout)")
    ap.add_argument("--todos", action="store_true", help="validate: also list open TODOs")
    ap.add_argument("--base", help="check-delivered: the PR's base branch; other branches than the default pass")
    ap.add_argument("--history", action="store_true",
                    help="check-delivered: also accept stubs main generated within drift_grace_days (needs git history)")
    args = ap.parse_args(argv)

    if args.command == "get":
        if not args.target:
            ap.error("get needs an AREA")
        try:
            print(json.dumps(get(load(args.root), args.target, args.detail), indent=2, sort_keys=True))
        except ConfigError as e:
            print(f"qqcfg get: {e}", file=sys.stderr)
            return 1
        return 0

    if args.command == "check-delivered":
        if not (args.target and args.detail):
            ap.error("check-delivered needs REPO and DIR")
        cfg = load(args.root)
        repo = by_name(cfg["repos"]["repo"]).get(args.target)
        if repo is None:
            print(f"PASS: nothing is delivered to {args.target}")
            return 0
        base = (args.base or "").removeprefix("refs/heads/")
        if base and base != repo["default_branch"]:
            print(f"PASS: stubs are delivered to {repo['default_branch']}, not {base}")
            return 0
        older = generations(args.root, args.target, cfg["pipelines"]["defaults"]["drift_grace_days"]) if args.history else []
        errors = check_delivered(cfg, args.target, Path(args.detail), older, warn=lambda w: print(f"::warning::{w}"))
        for e in errors:
            print(f"::error::{e}")
        print(f"FAIL ({len(errors)})" if errors else f"PASS: {args.target}'s generated workflows match infra-config")
        return 1 if errors else 0

    if args.command == "deliver":
        if not (args.target and args.detail):
            ap.error("deliver needs REPO and DIR")
        try:
            changed = deliver(load(args.root), args.target, Path(args.detail))
        except ConfigError as e:
            print(f"qqcfg deliver: {e}", file=sys.stderr)
            return 1
        print("\n".join(changed) or "already up to date")
        return 0

    if args.command == "generate":
        cfg = load(args.root)
        gen = args.root / "generated"
        want = render(cfg)
        for p in sorted(gen.rglob("*"), reverse=True) if gen.exists() else []:
            if p.is_file() and p.relative_to(gen).as_posix() not in want:
                p.unlink()
            elif p.is_dir() and not any(p.iterdir()):
                p.rmdir()
        for rel, text in want.items():
            (gen / rel).parent.mkdir(parents=True, exist_ok=True)
            (gen / rel).write_text(text)
            print(f"wrote generated/{rel}")
        return 0

    errors, report = validate(args.root)
    print("qqcfg validate")
    for line in report:
        print("  " + line)
    if args.todos:
        print("open TODOs:")
        for t in todos(args.root):
            print("  " + t)
    if errors:
        for e in errors:
            print("  ERROR " + e)
        print(f"FAIL ({len(errors)} error{'s' if len(errors) != 1 else ''})")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
