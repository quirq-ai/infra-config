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
to take it over. Nothing reads this config yet except its own tool, `qqcfg`. Each file's header
says whether it is a `seed` (its values are decided) or a `stub` (only the shape is there, and the
values are placeholders).

The plan behind this repo is in [docs/plan.md](docs/plan.md), and the 51 v0 work items for all
thirteen quirq infra repos are in [docs/v0.md](docs/v0.md). Both are reference copies of suraj's
originals, and changing them needs his approval.

## Quick start

```sh
python3 -m pip install -r requirements.txt     # jsonschema; Python 3.11+ for tomllib
python3 tools/qqcfg.py validate                # the CI check; exit 1 on any error
python3 tools/qqcfg.py validate --todos        # also list every open decision
python3 tools/qqcfg.py generate                # rewrite generated/ after editing config/
python3 tools/qqcfg.py get org budget           # one area or value as JSON, for non-Python readers
python3 -m unittest discover -s tests          # seed passes; known-bad changes fail
```

`validate` checks five things: the TOML parses, every area matches its JSON Schema, every
reference resolves, the policy invariants hold, and `generated/` matches what `generate` would
write. `.github/workflows/validate.yml` runs it with the tests on every PR and in the merge queue.

## Layout

```text
infra-config/
├── config/                 the source of truth: one TOML file per area, parsed and never executed
│   ├── org.toml            system name, backends, roles, pools, secret scopes, budget, rotations,
│   │                       and the thirteen quirq infra repos
│   ├── kinds.toml          toolchains and target kinds (year one: latest Python, latest Next.js)
│   ├── repos.toml          registry of onboarded repos: xo-space, innernet
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
`schema` version (`v0`), `owners` (left empty; suraj fills it in, and nothing here assigns owners),
`read_by` (the systems that will read the file) and `chromium` (the counterpart an expert should
read first).

## Areas and what each expert owns next

| Area | Status | What the expert owns next |
|---|---|---|
| `org` | seed | Isolated runners for trusted work; OIDC trust for each deploy target; mapping Launchpad onto the backend seam. |
| `kinds` | seed | Recipes adapters for `python-service`, `pytest`, `node-app` and `static-docs` that replace the `interim` commands; github provisioning for node. |
| `repos` | seed | Each repo's own `infra/repo.toml` (with `sync`); moving xo-space from Python 3.12 to the org pin; confirming innernet's deploy target. |
| `pipelines` | seed | Generating every builder, not just the one example; getting generated workflows into product repos. |
| `gate` | seed | Making the change classes machine-checkable; the gate check app; tree closers. suraj applies the GitHub settings (merge queue, required checks). |
| `flakes` | seed | Exoneration thresholds and enforcing quarantine expiry (v1). test-pipelines reads `[verdict]` in v0. |
| `auto_revert` | seed | A gardener that stays within the caps; whether deploy failures get their own budget. |
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
- **GitHub Actions as the only generator target, with one example** (`xo-space-presubmit`). Its
  steps are interim commands in `kinds.toml` until the recipes adapters exist. The generated
  workflow has not been run on GitHub yet; its commands pass locally against xo-space (`c3cea98`,
  Python 3.14.8). It checks less than xo-space's own `tests.yml`, which stays a required check
  until the repo's manifest targets cover the rest.
- **Squash merges**, because xo-space already uses them. **Dependabot** for ecosystem rolls (the
  plan lists it as an option). **GitHub Issues** for postmortem and fuzz tracking. **Atheris**
  (Python) and **Jazzer.js** (JS/TS) as fuzz engines, because neither needs containers. Cron
  schedules are in UTC.

## Open decisions

`python3 tools/qqcfg.py validate --todos` lists all of them; those v0 needs are marked
`TODO(suraj, v0)`. `validate` also lists every empty `owners` list and rotation, and whether the
compute ceiling is set. The ones for suraj:

- **v0:** the hour of the daily canary deploy (`channels.toml`)
- **v0:** whether the cap of 10 keeps counting reverts created, the default, or counts only auto-landed
  ones (`auto_revert.toml`)
- whether an agent may roll stable back on its own when a health signal breaches (`channels.toml`)
- the stable target of every two weeks, each promotion still his to approve (`channels.toml`)
- **v0:** the monthly CI compute ceiling (`org.toml`)
- **v0:** squash merges for every repo (`gate.toml`)
- the PostHog host and projects (`health.toml`)
- **v0:** the owners of every area and repo, and the members of every rotation

## How this fits with the other repos

`gate` reads `repos`, `pipelines` and `gate` to decide which checks are required. `gardener`
reads `auto_revert` and `flakes`. `release` and `installer` read `channels` and `health`.
`rollers` reads `rollers` and moves the pins in `kinds`. Per the plan, `sync` will own the single
parser library. Until it exists, every reader goes through `qqcfg.load` and writes no parser of
its own.
