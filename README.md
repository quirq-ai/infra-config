# infra-config

Configuration as code for **quirq infra** (qq), the CI/CD system for every quirq-ai repo. This
repo declares the whole system as data: which repos are onboarded, what builds them, how a change
lands, how releases move through channels, and the limits on what agents may do alone. A change
here is a pull request that goes through the same gate as code, and you revert it like code.

Chromium counterpart: `chromium/src/infra/config` plus `lucicfg`. Chromium writes its fleet in
Starlark, generates the service configs, and a presubmit check fails if the generated files are
stale. This repo keeps that model (source, then generated output, then an in-sync check) with
smaller parts.

**Status: v0 skeleton, built width-first.** Every area is declared in enough detail for an expert
to take it over. Each file's header says whether it is a `seed` (its values are decided) or a
`stub` (only the shape is there, and the values are placeholders), and its `[area] read_by` names
the readers it is meant for.

Who reads it today (checked in each repo's main on 2026-10-07):

| Reader | Reads |
| --- | --- |
| `qqcfg` here (validate, generate, deliver) | every area; `pipelines`, `kinds`, `repos` and `org` pools shape the generated workflows |
| quirq-ai/gate | `gate`, `kinds`, `org`, `pipelines`, `repos` |
| quirq-ai/rollers | `rollers`, `kinds`, `org`, `repos` |
| quirq-ai/recipes (`qqrecipes check-kinds`) | `kinds` |
| quirq-ai/sync | `kinds` |
| quirq-ai/test-pipelines (`qqresults`, when given `--infra-config`) | `flakes` |
| quirq-ai/gardener (`qqgarden`, V0-GAR-03, V0-GAR-04) | `auto_revert`, `postmortem`, `pipelines`, `repos`, `org` |
| quirq-ai/release (`qqrelease`, V0-REL-01..03) | `channels`, `health` (canary probes), `pipelines`, `repos` |
| quirq-ai/monitoring (raw files, not `qqcfg`) | `channels`, `repos` |

No reader yet: `fuzz` and `perf`. release's fuzz smoke keeps its bounds in code until V1-REL-02
(a `TODO(expert)` in its `canary.py`), and perf reads its benchmark parameters from its own
`tools/bench_commit.sh`, so V0-CFG-03's "their readers use them" is not met for those two.

The plan behind this repo is in [docs/plan.md](docs/plan.md), and the 51 v0 work items for all
thirteen quirq infra repos are in [docs/v0.md](docs/v0.md). Both are reference copies of suraj's
originals, and changing them needs his approval.

## v0 status

| Item | PRs | State |
| --- | --- | --- |
| V0-CFG-01 schema, validator, CI | skeleton (7228ab2) | merged; `validate` is the required check in this repo's merge queue (gate's repo rulesets, applied at gate 6610664) |
| V0-ORG-01 the 13 repos | #1 | merged |
| V0-CFG-03 fill the stubs | #2 | merged; readers listed above; `fuzz` and `perf` have none yet |
| V0-CFG-02 builders and drift check | #3, #7 (S5 test reports), #8, #24 to #27 (drift fixes); xo-space #211, innernet #37, website #1 | merged and delivered to all three product repos. The `qq-drift` org ruleset is off: quirq-ai is on GitHub Free, which has no org rulesets (gate `docs/apply-settings.md`), so nothing requires `qq-drift.yml` yet |
| website onboarding | #31, #32 | merged; gate's settings for website (gate #28) are merged but not applied yet |
| V0-CFG-04 suraj's v0 decisions | #4 | suraj decided the 3 `TODO(suraj, v0)` values on 2026-10-06 (canary hour, revert-cap counting, compute ceiling); they are not written into config yet |
| V0-ORG-02 owners and rotations | #4, #30 | suraj owns `org` and the thirteen infra repos (#30); `validate` lists the 12 areas, 3 product repos and 3 rotations still empty |
| V0-ORG-04 budget readable | #4 | `qqcfg get org budget`; suraj decided the ceiling on 2026-10-06, but it is not written into config yet |
| V0-TST-01 result sink in test builders (asked by test-pipelines) | #5 | merged |
| V0-PRF-01 `bench` in python-service and node-app (asked by perf) | #6 | merged |
| V0-CFG-05 one source for policy | partial | gardener's caps and `auto_land_repos` come from `auto_revert` (gardener `tests/test_policy.py`); release reads `channels`, `health`, `pipelines` and `repos`; release's fuzz smoke bounds are still in its code |

## Quick start

```sh
python3 -m pip install -r requirements.txt     # hashed lock of requirements.in (jsonschema, PyYAML); Python 3.11+
python3 tools/qqcfg.py validate                # the CI check; exit 1 on any error
python3 tools/qqcfg.py validate --todos        # also list every open decision
python3 tools/qqcfg.py generate                # rewrite generated/ after editing config/
python3 tools/qqcfg.py get org budget           # one area or value as JSON, for non-Python readers
python3 tools/qqcfg.py deliver xo-space ../xo-space   # copy its generated workflows into a checkout
python3 tools/qqcfg.py check-delivered xo-space ../xo-space   # the qq-drift check
python3 -m unittest discover -s tests          # seed passes; known-bad changes fail
```

`validate` checks five things: the TOML parses, every area matches its JSON Schema, every
reference resolves, the policy invariants hold, and `generated/` matches what `generate` would
write. `.github/workflows/validate.yml` runs it with the tests on every PR and in the merge queue.
`render()` itself is pinned by a golden test (`tests/golden/`): quirq-ai's config there must render
byte for byte what it rendered before, because each delivered stub's `qq-digest` covers its header.
A change that means to alter generated output updates `tests/golden/` in the same PR.

### A user's own org (one-command setup)

`--root DIR` names the data to check or generate: `DIR/config/` and `DIR/generated/`. Code,
schema and the postmortem template always come from this checkout, so a user's `<org>/qq-config`
holds data only (all 13 areas, `generated/`, and the pinned infra-config commit):

```sh
python3 tools/qqcfg.py validate --root ../qq-config
python3 tools/qqcfg.py generate --root ../qq-config
```

Every repo's `source` must be exactly `<code_host>/<name>`, with `code_host` a `github.com/<org>`
and the owner in lower case (a `Quirq-AI` spelling would still count as quirq-ai). When `code_host` is `github.com/quirq-ai`, the thirteen infra
repos are required as before, and this checkout's own config (the default `--root`) must be
quirq-ai's. Any other org lists exactly one infra repo, `qq-config`. A user org gets no `qq-required-*` org copies, and its stubs name `<org>/qq-config` as
their source. Tool pins are never derived from `code_host`: the schema requires gate's timing step,
test-pipelines' sink and `other_qq_workflows` `from` to name quirq-ai, so every org runs quirq's
tools at pinned commits.

## Layout

```text
infra-config/
├── config/                 the source of truth: one TOML file per area, parsed and never executed
│   ├── org.toml            system name, backends, roles, pools, secret scopes, budget, rotations,
│   │                       and the thirteen quirq infra repos
│   ├── kinds.toml          toolchains and target kinds (year one: latest Python, latest Next.js, Gatsby)
│   ├── repos.toml          registry of onboarded repos: xo-space, innernet, website
│   ├── pipelines.toml      builders: presubmit, postsubmit, release
│   ├── gate.toml           landing gate, verification surface, who may land what
│   ├── flakes.toml         retries, exoneration, quarantine with expiry
│   ├── auto_revert.toml    gardener revert caps
│   ├── rollers.toml        machine-written dependency updates
│   ├── channels.toml       canary → dev → stable, promotion and rollback rules
│   ├── fuzz.toml           fuzz engines and schedules
│   ├── postmortem.toml     postmortem policy and failure tracking
│   ├── health.toml         health signals (PostHog and CI) that gate promotion
│   └── perf.toml           benchmarks and alert thresholds
├── schema/                 JSON Schema (draft 2020-12): area.schema.json plus one per area
├── templates/              files config points at (postmortem.md)
├── tools/qqcfg.py          validate + generate (the lucicfg counterpart)
├── generated/github/       generated output for the github backend; never edit by hand
├── tests/test_qqcfg.py     the validator's own tests
├── .github/                CODEOWNERS and this repo's own validate workflow
├── docs/                   reference copies of the plan (plan.md) and the v0 work items (v0.md)
└── AGENTS.md               how agents change this repo safely
```

Every config file begins with the same `[area]` header: `name`, `status` (`seed` or `stub`),
`schema` version (`v0`), `owners` (empty in most areas until suraj fills it in; `org` names suraj),
`read_by` (the systems that will read the file) and `chromium` (the counterpart an expert should
read first).

## Areas and what each expert owns next

| Area | Status | What the expert owns next |
|---|---|---|
| `org` | seed | Isolated runners for trusted work; OIDC trust for each deploy target; mapping Launchpad onto the backend seam. |
| `kinds` | seed | Recipes adapters for `python-service`, `pytest`, `node-app`, `gatsby-site` and `static-docs` that replace the `interim` commands; github provisioning for node. |
| `repos` | seed | Each repo's own `infra/repo.toml` (with `sync`); moving xo-space from Python 3.12 to the org pin; confirming innernet's deploy target. |
| `pipelines` | seed | Switching steps from `interim` commands to recipes adapters; a gate-side check that delivered stubs match this repo. |
| `gate` | seed | Making the change classes machine-checkable; the gate check app; tree closers. suraj applies the GitHub settings (merge queue, required checks). |
| `flakes` | seed | Exoneration thresholds and enforcing quarantine expiry (v1). test-pipelines reads `[verdict]` in v0. |
| `auto_revert` | seed | A gardener that stays within the caps and lands reverts only in `auto_land_repos` (empty in v0, so it proposes); whether deploy failures get their own budget. |
| `rollers` | seed | A Python lockfile for xo-space. rollers generates Dependabot config from the `dependabot` rollers and runs the toolchain roller. |
| `channels` | seed | Who advances `lkgr`; what a channel and a rollout percentage mean for each deploy target; rollback. |
| `fuzz` | seed | v0 runs time-boxed property tests in the gate and the canary's fuzz smoke. Fuzz harnesses, orchestration and corpus storage are v1 (schedules marked `phase = "v1"`). |
| `postmortem` | seed | Grouping failures into recurring classes (v1). The template is `templates/postmortem.md`, and postmortems live in their tracker issue. |
| `health` | seed | v0 uses CI signals and canary probes only. Wiring PostHog into each repo, event names and xo-space telemetry consent are v1 (signals marked `phase = "v1"`). |
| `perf` | stub | Benchmark hardware, noise control, and routing alerts to bisection. |

Not declared yet, because their phase has not started: hermetic toolchain images (`toolchains`,
P3), the remote cache and executor (`remote-build`, P3/P6) and channel-following installers
(`installer`, P5). Each gets a `config/<area>.toml` and a schema when it starts.

## Rules the validator enforces

Config alone cannot loosen these. They live in `tools/qqcfg.py`, which is a policy path, so
changing one needs the policy-owner (suraj).

- Promotion to stable needs the policy-owner. Any channel that reaches people (dev, stable) needs
  a human owner's approval. Only canary, which is agents-only, promotes without one. Builder
  triggers fire without a person, so a release builder may feed only canary; builds reach dev and
  stable only through an approved promotion.
- canary is agents-only and runs unattended every day. It is the fully autonomous loop and serves
  as a research and test environment. dev is for humans plus agents.
- Agents may land only clean reverts, dependency rolls and docs alone. Policy changes need the
  policy-owner, and authors cannot approve their own changes to the verification surface.
- Auto-revert: at most 10 reverts created per rolling 24 h (the window may not be shorter), and
  only clean reverts. The 10 is suraj's; counting reverts created is a default he can change.
  Beneath that cap sit LUCI Bisection's limits: 10 created per failure type, 4 auto-submitted for
  build failures, none auto-submitted for test failures, and only culprits up to 6 h old.
  Submission also needs the repo in `auto_land_repos`, which may name only repos in `repos.toml`;
  it is empty in v0, so every revert is proposed and the policy-owner merges it.
- Untrusted pools hold no secrets. Any builder that runs code from an open change (presubmit, or a
  `change` or `queue` trigger) and PR fuzzing run only in pools without secrets.
- Post-submit builders are never cancelled. Repos are public only.

The validator also checks the files against each other. Every repo needs a blocking presubmit
builder on `change` and `queue` and a post-submit mirror. A blocking builder must fit within the
gate's `max_minutes`. Repos may use only kinds whose phase is `year-one`, so containers wait.
Every name used in one file must be defined in another.

## Backends: GitHub now, Launchpad later

v0 runs on GitHub. Execution later moves to Launchpad, quirq's own cloud, so the config stays
backend-neutral:

- Triggers have neutral names: `change`, `queue`, `land` and `schedule`. The github generator maps
  them to `pull_request`, `merge_group` and `push`.
- Anything specific to one backend sits in a sub-table named after that backend (`[pool.github]`,
  `[toolchain.github]`) or is chosen by a `backend` field (`pipelines.defaults`,
  `gate.merge_queue`). `org.toml` lists the backends.
- All GitHub-specific tooling sits in one section of `tools/qqcfg.py`, and its output goes to
  `generated/github/`.

## Choices made where the plan does not decide

Where the plan left a choice open, I picked the simplest well-known option:

- **TOML for config.** The plan already uses TOML for repo manifests ("parsed and never executed,
  like DEPS"), and Python reads it with the standard-library `tomllib`. Starlark would need an
  interpreter and would make config executable.
- **JSON Schema 2020-12, checked with `jsonschema`.** It is independent of any language, so other
  tools and editors can use the same schemas.
- **GitHub Actions as the only generator target.** Every presubmit and post-submit builder for
  xo-space, innernet and website is generated into `generated/github/<repo>/` and copied into the repo with
  `python3 tools/qqcfg.py deliver <repo> <checkout>` (V0-CFG-02). The binding drift check is
  `.github/workflows/qq-drift.yml` here, meant to run as an organization-required workflow in every
  product repo (gate's `qq-drift` org ruleset, which is off: quirq-ai is on GitHub Free, so no repo
  requires it yet): it fails a PR whose `qq-*.yml` stubs differ from infra-config `main`, are renamed or missing,
  or whose own workflows define a check with a generated builder's name (YAML is parsed, so quoting,
  flow style or a `name:` on another job id don't escape it). While a PR leaves its `qq-*` files
  alone, stubs `main` generated within `drift_grace_days` (pipelines.toml) pass with a warning, so a
  generator change doesn't turn open product PRs red before redelivery; a PR that edits them must
  match `main` exactly. A repo's `other_qq_workflows` (repos.toml), such as rollers' `qq-roll-land.yml`, belong to another quirq tool: `deliver` leaves them in place and the drift check does not count them as stale stubs, though each, when present, must match the sha256 recorded there (its owner bumps it on redelivery) and may not define a generated builder's check. qq-drift runs qqcfg from the infra-config commit its ruleset pins, not from `main` at run time, so a change here reaches product PRs only when gate moves that pin: merge here, have gate repin, then redeliver. Before running anything it refuses a run that is not this file from quirq-ai/infra-config, a pin that is not a full commit SHA, and a checked-out commit that is not that pin or not on infra-config `main`; it installs only PyYAML, hash-checked with no dependencies (`requirements-drift.txt`, bumped with its Python version), and tests run each of these guards. It refuses symlinked workflows. PRs into other branches than the default pass. A PR cannot edit
  it, because it lives here. Each stub
  also carries a `# qq-digest:` line and a fast in-repo drift step. Post-submit builders also run on `workflow_dispatch` with a `commit` input, so the gardener can backfill main commits a batched push skipped (V0-GAR-01). A backfill must be dispatched from the default branch, and a refused one stores no results. Such a run's check shows on the branch tip, so find it by its run name (`<builder> <commit>`), not by the tip's checks. Each repo's merge-queue builder ends with gate's timing step (V0-GAT-04), capped at 3 minutes and unable to fail the check. Every action in a generated workflow is pinned by full commit SHA. `generate` also writes `.github/workflows/qq-required-<builder>.yml` here, one per presubmit builder: the same commands as the delivered stub (no timing step or result sink), guarded to run only in its own repo, with no concurrency group (GitHub says a ruleset workflow must not be cancelled in progress) and no job over gate's admission `max_minutes` (validate checks it; gate #13's rulesets refuse longer ones). Gate's org rulesets would require it in each product repo, pinned by commit, so a product PR cannot edit its own tests away (rollers audit R-2); they are all off on GitHub Free, so today xo-space and innernet require their delivered stub instead (website's rulesets are not applied yet). Changing a copy takes effect only when a gate PR moves that pin. Canary builders are `generate = false`: the canary runs in quirq-ai/release (`canary.yml`, V0-REL-03), not in the product repos. Steps are interim commands in
  `kinds.toml` until the recipes adapters exist (V0-REC-02, V0-REC-03); they pass locally against
  xo-space `c3cea98` (Python 3.14.8) and innernet `da9b84c` (pnpm install, typecheck, build). xo-space's
  hand-written `tests.yml` is gone (xo-space #217); gate requires only `xo-space-presubmit` there.
- **Squash merges** for every repo (suraj, 2026-10-04). **Dependabot** for ecosystem rolls (the
  plan lists it as an option). **GitHub Issues** for postmortem and fuzz tracking. **Atheris**
  (Python) and **Jazzer.js** (JS/TS) as fuzz engines, because neither needs containers. Cron
  schedules are in UTC.

## Open decisions

`python3 tools/qqcfg.py validate --todos` lists all of them; the config values v0 needs are
marked `TODO(suraj, v0)`. `validate` also lists every empty `owners` list and rotation, and whether the
compute ceiling is set. The ones for suraj:

- whether an agent may roll stable back on its own when a health signal breaches (`channels.toml`)
- the PostHog host and projects (`health.toml`)
- **v0:** the owners of every area and repo, and the members of every rotation

Decided by suraj on 2026-10-06 but not written into config yet, so `validate --todos` still lists
them: the daily canary deploy at 06:17 UTC (`channels.toml`; release's `canary.yml` repeats it, and
a release test checks they match), a revert cap of 10 a day
(`auto_revert.toml`), stable every two weeks with each promotion his to approve (`channels.toml`),
and no new compute spend as the monthly CI ceiling (`org.toml`).

## How this fits with the other repos

`gate` reads `gate`, `kinds`, `org`, `pipelines` and `repos` to decide which checks are required. `gardener`
reads `auto_revert`, `postmortem`, `pipelines`, `repos` and `org` (and later `flakes`). `release` reads
`channels`, `health`, `pipelines` and `repos`;
`installer` follows release's published `channels.json`, not this repo.
`rollers` reads `rollers`, `kinds`, `org` and `repos` and moves the toolchain pins in each product repo's `infra/repo.toml`. Per the plan, `sync` will own the single
parser library. sync exists but parses only manifests, so every Python reader goes through
`qqcfg.load` and writes no parser of its own. monitoring, a read-only TypeScript dashboard, parses
`channels.toml` and `repos.toml` itself.

## Licence

Apache-2.0; see [LICENSE](LICENSE).
