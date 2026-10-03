#!/usr/bin/env python3
"""qqcfg: validate and generate quirq infra (qq) config. The small counterpart of Chromium's lucicfg.

    python3 tools/qqcfg.py validate [--todos]   schema, cross-references, policy invariants,
                                                and generated files in sync. Exit 1 on any error.
    python3 tools/qqcfg.py generate             rewrite generated/<backend>/ from config/.

Config is TOML: parsed, never executed. Needs Python 3.11+ (tomllib) and jsonschema (requirements.txt).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Every area must exist. Adding an area means adding config/<area>.toml and schema/<area>.schema.json.
REQUIRED_AREAS = ("org", "kinds", "repos", "pipelines", "gate", "flakes", "auto_revert",
                  "rollers", "channels", "fuzz", "postmortem", "health", "perf")

# Settled policy that config alone cannot loosen. Changing these lines is itself a policy change,
# and this file is a policy path (CODEOWNERS), so it needs the policy-owner.
AUTO_REVERT_DAILY_CAP = 10  # settled by suraj
LUCI_CAPS = {  # failure type: (max reverts created per day, max auto-submitted per day); luci-bisection.cfg
    "build_failure": (10, 4),
    "test_failure": (10, 0),
}
MAX_CULPRIT_AGE_HOURS = 6
AGENT_ALONE_CLASSES = {"clean-revert", "dependency-roll", "docs"}
HUMAN_APPROVALS = {"human-owner", "policy-owner"}

TODO_RE = re.compile(r"TODO\((suraj|expert)\):\s*(.+)")


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


def check_refs(cfg: dict, err) -> None:
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
                         ("perf benchmarks", cfg["perf"]["benchmark"])]:
        names = [i["name"] for i in items]
        for dup in sorted({n for n in names if names.count(n) > 1}):
            err(f"{label}: duplicate name {dup!r}")

    for where, b in [("org default_backend", cfg["org"]["org"]["default_backend"]),
                     ("pipelines defaults backend", defaults["backend"]),
                     ("gate merge_queue backend", cfg["gate"]["merge_queue"]["backend"]),
                     *((f"pipelines: builder {x['name']!r} backend", x["backend"]) for x in builders if "backend" in x)]:
        if b not in backends:
            err(f"{where}: unknown backend {b!r} (see org.toml [[backend]])")
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
        if b["pipeline"] == "presubmit":
            inv(not pools.get(b["pool"], {}).get("secrets", ["?"]),
                f"presubmit builder {b['name']!r} runs PR code, so its pool may hold no secrets")
        if b["pipeline"] == "postsubmit":
            inv(b.get("cancel_in_progress") is not True, f"postsubmit builder {b['name']!r} is never cancelled")
    for s in cfg["fuzz"]["schedule"]:
        if s["mode"] == "code-change":
            inv(not pools.get(s["pool"], {}).get("secrets", ["?"]),
                f"fuzz schedule {s['name']!r} runs PR code, so its pool may hold no secrets")
    return checks


# --- generation (one backend: github; one example: builders with generate = true) -------------
# Everything GitHub-specific in this repo's tooling lives in this section.

CHECKOUT = "actions/checkout@v6"  # TODO(expert): pin actions by commit SHA (plan P5).
GITHUB_EVENTS = {"change": "pull_request", "queue": "merge_group", "land": "push"}


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
        if b.get("backend", defaults["backend"]) != "github" or b["pipeline"] != "presubmit":
            raise ConfigError(f"{where}: only presubmit builders on the github backend can be generated today")
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
                    steps.append((f"{cap} ({k})", kinds[k]["interim"][cap]))
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
            "concurrency:",
            f"  group: {q('qq-' + b['name'] + '-${{ github.ref }}')}",
            f"  cancel-in-progress: {'true' if b.get('cancel_in_progress', True) else 'false'}",
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
        for name, cmd in steps:
            lines += [f"      - name: {q(name)}", f"        run: {q(cmd)}"]
        out[f"github/{b['repo']}/qq-{b['name']}.yml"] = "\n".join(lines) + "\n"
    return out


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
                found.append(f"{path.relative_to(root)}:{n}: TODO({m.group(1)}): {m.group(2).strip()}")
    return found


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
    check_refs(cfg, errors.append)
    refs_ok = len(errors) == n
    if refs_ok:
        report.append("ok    refs       repos, kinds, pools, builders, channels, signals, triggers")
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
    unowned = [a for a, c in cfg.items() if not c["area"]["owners"]]
    unowned_repos = [r["name"] for r in cfg["repos"]["repo"] if not r["owners"]]
    report.append(f"note  owners     empty in {len(unowned)} areas and {len(unowned_repos)} repos (suraj assigns)")
    report.append(f"note  todos      {len(todos(root))} open (python3 tools/qqcfg.py validate --todos)")
    return errors, report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="qqcfg", description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["validate", "generate"])
    ap.add_argument("--root", type=Path, default=ROOT, help="repo root (default: this checkout)")
    ap.add_argument("--todos", action="store_true", help="validate: also list open TODOs")
    args = ap.parse_args(argv)

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
