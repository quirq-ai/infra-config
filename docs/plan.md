# quirq infra: a Chromium-grade CI/CD system for any repo

> **Reference copy.** suraj's master plan for quirq infra as of 2026-10-03, copied here so that v0 sessions can read it. suraj keeps the original; if the two differ, the original wins. Two edits were made: links to the v0 plan point at [v0.md](v0.md), and one local file path became a description. The v1 and v2 plans, `ci-cd-vision.md` and `writings-notes.md` are not copied, so links to them do not resolve here.

Status: draft plan for suraj. Date: 2026-10-03. Revised the same day with suraj's decisions (§10.1), release
channels, the daily canary, fuzzing, failure tracking and PostHog (§5.6–§5.11), and the v0, v1 and v2 version
plans in [quirq-infra/](v0.md) (§7.1).
Replaces the scope of [ci-cd-vision.md](ci-cd-vision.md). That file was about hardening one repo's GitHub
Actions. Its baseline facts and Phase 1 still hold and become this plan's first migration (Phase 1 below).
Companion: [writings-notes.md](writings-notes.md), which covers what each of suraj's writings contributed.

How claims are marked, following the claim-ledger convention in suraj's writings:
**[cr]** read by me in a primary source (Chromium, LUCI, or a tool's or vendor's own docs and repo), cited in §12.
**[w]** taken from suraj's Chromium teardowns in `writings/chromium/`, which cite `chromium/src@f288fed6`. I did not re-check these unless they are also marked [cr].
**[inf]** my own inference or design.
**[verify]** not checked yet.

---

## 0. The two-minute version

**What it is.** One CI/CD system for every quirq-ai repo, whatever its language or build tool. It
checks every change before it lands, keeps `main` green after it lands, and ships through
release channels: canary, built and shipped daily by agents alone; dev, promoted by humans and agents
together; then stable, promoted by suraj. The bar is how Chromium does each of those things. Like Chromium's, the system is split into
repos with one job each: devtools, dependency sync, build adapters (recipes), shared config, toolchains, remote build (the goma slot), test
pipelines, the gate, gardening, rollers, release, the installer, and perf.

**Who runs it.** Claude agents do most of the work. They open changes, triage red builds, bisect and
propose reverts, roll dependencies and cut releases. suraj sets policy, owns the admin settings, assigns the human and AI
owners, and promotes to stable. The rule comes from suraj's own Space Walk judge: **the model proposes; deterministic
machinery disposes.** Nothing lands because an agent said it works. It lands because the gate verified
the exact merge result. That makes the CI system quirq's first production *verifier*: a merged change is a
unit of work, and the gate's verdict is evidence captured from the environment, not something the agent
reported about itself.

**What makes it work for any repo.** This is the xo-space invariant applied to builds: *no core
file names a language.* Each repo keeps a declarative manifest in its own tree. The manifest lists pinned
dependencies, pinned toolchains and typed targets. Per-kind adapters (python-service, node-app,
container-image, …) implement capabilities (build, test, package, run, deploy) behind one loader. Every
step is a content-addressed **action** (command + input digest → output digest), which is the Bazel
Remote Execution API's model. Actions can be cached, reused and run anywhere: on a laptop, a CI runner or a
remote executor.

**What lets the canary run unattended.** The canary goes only to quirq's research and test environments, never
to users, and humans still use and regulate them (D4). Each day it builds the last-known-good commit, runs the
full tests and a fuzz smoke, deploys, probes and soaks. Any failure holds or rolls it back on its own, within
daily caps, and opens a failure record linked to the culprit and its fix. Agents draft blameless postmortems,
and a failure class that recurs must end in a new test, fuzz target or gate (§5.7–§5.10). PostHog, which today
runs only on the docs site, becomes a soak-time health signal and the feature-flag tool, never the gate (§5.11).
Infra as code is a core pillar: everything from onboarded repos to rollback rules is declared in `infra-config` (§5.6).

**Build, buy or adopt.** Adopt the commodity parts and build only the glue that is specific to quirq.
- Adopt now: GitHub merge queue and Actions as the first gate and scheduler, kept behind an
  interface; JUnit XML as the test-result input; OCI images pinned by digest as the toolchain transport.
- Adopt later: a REAPI cache, and then remote execution (Buildbarn, Apache-2.0).
- Adopt for fuzzing: Hypothesis and fast-check per change; Atheris through ClusterFuzzLite, Jazzer.js and
  Schemathesis continuously and in the canary (§5.9).
- Do not adopt LUCI wholesale (see §6), but copy its designs.
- Build: the manifest and its single parser, the adapters, the results store and flake handling, the
  gardener agent, and the release, channel and installer tooling, plus the canary pipeline, fuzz
  orchestration and failure records.

**Roadmap.** Eight phases (P0–P7), each with a pass/fail exit test. It starts by putting xo-space and innernet
behind a gate generated from their manifests. It ends with agents running the gardener, roller and release
rotations, and humans touching only policy and stable promotions. The work is grouped into three versions, each
a list of delegable work items per repo: **v0** gives all thirteen repos a base version and runs the toolchain end
to end on GitHub, including an agent-run daily canary; **v1** makes the canary unattended (soak, rollback,
fuzzing, failure records, postmortems, PostHog signals) and opens dev; **v2** adds Launchpad, remote execution,
perf bisection, fuzzing depth and, at low priority, stable and the installer ([v0](v0.md),
[v1](quirq-infra/v1.md), [v2](quirq-infra/v2.md); §7.1).

**Decided, and still open** (§10). suraj settled the main questions on 2026-10-03 (§10.1). Year one starts with
latest Python and latest Next.js, containers later. Only public repos, so GitHub's merge queue needs no Enterprise
Cloud **[cr]**. All thirteen repos are built, as delegated work items. Agents land clean reverts, rolls and docs on
their own; policy changes and stable promotion need suraj, and GitHub repos always keep human owners. Auto-revert
is capped at 10 reverts created a day (counting created reverts is my default, which suraj can change). The architecture is cloud agnostic so it can move to Launchpad, quirq's own cloud, and v0
runs on GitHub. Release work beyond canary and dev is low priority. Still open (§10.3): the compute ceiling's
amount, whether to keep the revert cap's default count, who uses the canary, and PostHog's plan and scope.

---

## 1. What was asked, and how I read it

> "no not really I want to make a plan for a complete ci cd syste. like chromium that it agnostic of repo
> tech and can compile build run and deploy anything."

Follow-ups: "so idea would be like we need to make repos like for testing pipleines, sync installer
devtools etc", then "gp,a".

I read this as follows:
- The deliverable is a **system**, not one repo's workflows. xo-space, innernet and wiki are its first users,
  and the design must not depend on them.
- It should be **structured like Chromium's infra**, as separate repos per concern. §5.5 gives the list.
- "gp,a" is most likely **"goma"**, Chromium's old distributed compiler. On a QWERTY keyboard, "p,"
  sit next to "om", and suraj has written a post on goma. **This is an inference [inf].** If it is right, the plan
  needs a remote-build component. That is `remote-build` in §5.5.

---

## 2. What the writings say, and what the plan takes from them

Details by file are in [writings-notes.md](writings-notes.md). Five ideas shaped the plan:

1. **The fleet is a diff.** Chromium's 1,211 builders, its CQ and its release-branch fleets are generated
   from Starlark inside the repo they build. A fleet change is a CL that is reviewed and reverted like code. "The
   fleet is legible because it is a diff, and slow for the same reason." (`chromium/ci-cd-and-releases` §02, §12)
   → CI config is code in git and goes through the same gate as the code. (Decided 2026-10-03, D15: each repo
   keeps only its manifest in its tree; builder and pipeline definitions live centrally in `infra-config`.)
2. **Interfaces outlive mechanisms.** DEPS is parsed by so many tools that Chromium's submodule
   migration stalled at stage one for three years. "Every parser of DEPS is a dependency on DEPS."
   (`chromium/deps-and-goma` §09, §12) → one manifest format, one parser library, a versioned schema, and
   other tools are not allowed to write their own parsers.
3. **No core file names a backend.** xo-space resolves agents through one loader, declares them as
   data, and treats a missing capability as a normal state. "The plugin architecture isn't the point. It's the
   instrument." (`xo-space` §04–06, §18, §21) → this is how the system stays agnostic of repo technology (§5.1).
4. **Verify from captured state, never from self-report.** "A quirq is never claimed, it is minted."
   (`whitepaper`); the environment measures, not the agent (`what-is-quirq` §1.2; `markov-processes` §13)
   → an agent's "done" means nothing until the gate verifies the merge result. Tests and CI config
   are the verification surface, so agents may not change them without an owner's review.
5. **The product owns intent, the runtime owns the attempt.** Keep the work item, the attempt and the
   worker separate. Accept work and push the result later. Record an operation key before any external
   effect (`codex-session` §15–18; `claude-code-session` §13–14) → this gives the run data model, the
   job interface agents use, and idempotent deploys.

Two smaller rules: "The model proposes; Go disposes" (`research/spacewalk-architecture`), and licence plus
governance is checked for every adopted tool (`where-the-json-lives` §05).

---

## 3. What "Chromium-grade" means, checked against sources

Each pillar below is something Chromium does that I confirmed, with the quirq target beside it.

| # | Pillar | What Chromium does | quirq target |
|---|---|---|---|
| P1 | **Config as code, in the tree** | LUCI config is Starlark run by lucicfg into generated files, and "A presubmit check enforces that the generated files are kept in sync" **[cr]** (infra/config/README.md). Config changes reach the services by polling, with no deploy step **[w]**. | Each repo's `infra/` holds only its manifest; builders are defined centrally in `infra-config` (D15, §5.6). Generated CI files are checked in and diff-checked by a required check. |
| P2 | **Hermetic, pinned inputs** | gclient supports git, GCS and CIPD dependency types **[cr]**. Chromium does not "allow direct dependencies on non-Google-hosted repositories, so that we can still build if an external repository goes down" **[cr]** (docs/dependencies.md). Clang is pinned in text, and GN refuses to build if the pin and the tarball disagree **[w]**. | Every dependency and toolchain is pinned by digest. External sources are mirrored. The build checks its pins. |
| P3 | **Remote execution and content-addressed caching** | Nearly all workloads run as Swarming tasks; test inputs move from builders to test bots through CAS **[cr]** (builder_types.md, glossary.md). Siso is "a drop-in replacement for Ninja" that runs actions over REAPI **[cr]**. Chromium documents using *any* REAPI-compatible backend, not only Google's **[cr]** (linux/build_instructions.md). | Actions are REAPI-shaped. Cache first, remote execution second. No silent fallback from remote to local. |
| P4 | **Pre-submit gate on the change** | The CQ has dry-run, full-run and Mega-CQ modes. A full run submits only if there are no new regressions **[cr]**. A CQ builder must have a gardened CI mirror and a "Median cycle time ... under 40 minutes", with p90 "around an hour" **[cr]** (cq.md). 32 builders block every CL whatever files it touches, and path-filtered builders add more **[cr]** (generated cq-usage/default.cfg). Tryjob results are reused across trivial rebases **[w]**. | Required checks run on the exact merge result through a merge queue. Admission bar: p50 under 15 min to start, under 40 min ever. Results are reused when inputs are unchanged. |
| P5 | **Results are data; flakes are handled** | "nearly all pass-fail decisions on the builders are based on" ResultDB, not test JSON **[cr]** (resultdb.md). Failed shards are retried, then failing suites are re-run *without* the patch; only failures that pass without the patch fail the CL **[cr]**. The CQ has "roughly ~20,000 unique flaky tests" **[cr]** (cq.md). LUCI Analysis exonerates known flakes using thresholds kept in config **[cr]** (luci-analysis.cfg). New tests are checked for flakiness **[cr]**. | One results store; the CI verdict is computed from it. Retry, then compare against base. Flakes are tracked; quarantine needs an issue and an expiry date. |
| P6 | **Post-submit, gardening and auto-revert** | Gardeners' priorities are "The tree is open", then no new failures, then repair old ones. They may revert, disable tests and override OWNERS **[cr]** (gardener.md). LUCI Bisection finds culprits. Its config creates at most 10 reverts per rolling 24 h for compile failures and a separate 10 for test failures, auto-submits at most 4, only for culprits merged under 21,600 s (6 h) earlier (the age limit gates submission, not creation), and never auto-submits reverts for test failures **[cr]** (luci-bisection.cfg; luci-go `bisection/` config proto and revert code). Sheriff-o-Matic "tries to group failures ... that have the same regression range" **[cr]**. | A gardener agent with the same authority and budgets. Main is tested on every commit, and a red main is reverted fast. |
| P7 | **Performance regression detection** | The chrome.perf waterfall builds every commit and tests ranges on real hardware. Policy: "If you make a change that regresses measured performance, you will be required to fix it or revert" **[cr]** (perf_waterfall.md). The dashboard raises alerts, and Pinpoint bisects them **[cr]**. Binary-size gates run in the CQ **[cr]** (cq.md `Binary-Size:` footer). | Benchmarks on main with alert thresholds, plus size and latency budgets as required checks. |
| P8 | **Release channels and staged rollout** | Chrome ships a milestone to stable every two weeks, after three weeks of stabilization on a branch. Beta lasts two weeks. Early stable goes to a small percentage. Rollout is staged, using "two separate builds which are identical, except for the build number". Stable gets weekly refreshes **[cr]** (release_cycle.md). Release branches run the same config with `is_main` false **[w]**. | canary (agents alone), dev (humans and agents) and stable (suraj), promoted from a last-known-good ref, with no beta (§5.7). Staged rollout and one-command rollback, using the same machinery as CI. |
| P9 | **Machine-written dependency updates** | AutoRoll and similar rollers write about 20% of main's commits **[w]**. | Rollers move pinned dependencies and toolchains through the gate with no human involved. |
| P10 | **Infra ships like product** | LUCI's own services promote by a reviewed CL (`promote.py --canary --stable`), and rollback means reverting that CL **[cr]** (luci-go analysis/ and bisection/ READMEs). | quirq infra is itself a set of repos behind the same gate and channels. |
| P12 | **Fuzzing, per change and continuous** | Fuzz targets "run continuously at scale on ClusterFuzz"; new targets use FuzzTest, which runs for one second whenever its unit tests run **[cr]** (testing/libfuzzer/README.md, getting_started.md). ClusterFuzz files, triages and closes bugs automatically and re-tests open crashes daily **[cr]** (google/clusterfuzz). | Property tests per change, coverage-guided fuzzers nightly and in the canary, findings filed and closed automatically (§5.9). |
| P13 | **Failure clusters become bugs** | LUCI Analysis files a bug at a set priority when a failure cluster crosses a threshold in config, for example P0 when 10 or more developer CLs are blocked in one day **[cr]** (luci-analysis.cfg). | Every canary failure gets a record; a recurring class must end in a new test, fuzz target or gate (§5.10). |
| P11 | **Clear authority** | OWNERS approval is required for each directory a change touches; a clean revert can use the Rubber Stamper bot instead of a human reviewer **[cr]** (code_reviews.md, gardener.md). Pools are "a security boundary" **[cr]** (glossary.md). | CODEOWNERS for policy paths. Clean reverts and rolls can be approved by an agent. Untrusted and trusted work run in separate pools. |

Things I am *not* claiming: anything about how Chromium's internal `chrome` project runs (not public),
GardenerAI or TurboCI (neither is publicly documented; GardenerAI's only public trace is one line in a mail template, per **[w]**), and the current status of
Sheriff-o-Matic beyond the page quoted.

---

## 4. Who drives it

| Seat | Today in Chromium | In quirq infra |
|---|---|---|
| Author | Engineers upload CLs | Claude agents (and suraj) open PRs through `qq upload` |
| Reviewer and owner | OWNERS + committers | CODEOWNERS. Agents can review; owner approval is required for policy paths (tests, quarantine, `infra/`, release config) |
| Gate | LUCI CV + CQ builders | Deterministic: merge queue + generated required checks. No agent can override it |
| Gardener | 12 human rotations + LUCI Bisection | `gardener` agent: watches main, groups failures, bisects, opens reverts within budget |
| Roller | AutoRoll service accounts | `rollers` agent and service |
| Release manager | Humans + release service accounts | `release` agent builds and ships canary alone; a human owner approves each dev promotion the agent prepares; **suraj promotes to stable** until the scorecard earns more autonomy |
| Policy | Infra team | suraj: budgets, admin settings, autonomy levels |

**Owners.** suraj assigns the human and AI owners (decided 2026-10-03, D11). The system does not pick owners. It
reads them from each repo's CODEOWNERS and from the `owners` fields and rotations in `infra-config` (§5.6). GitHub
repos always keep human owners before anything is released (D4).

Rules that come from the writings:
- **Agents propose, machinery disposes.** An agent can open any PR, but only a green gate run on the
  merge result lands it.
- **The verification surface is protected.** A PR that edits tests, skips or quarantines tests, or changes `infra/`
  needs owner approval, and the PR's author, human or agent, cannot approve it. This blocks the whitepaper's
  attack A3, editing the test instead of fixing the code.
- **Acknowledge, then push.** `qq try` and `qq land` return a run ID at once, and the verdict is pushed to the
  agent session later. Agents never hold a tool call open while a build runs.
- **Observers never act.** The results store, scorecard and failure detector only read. Anything that
  changes the world (reverts, releases, deploys) is an executor acting with a recorded operation key.

The autonomy metric is the one from `what-is-quirq`: **intervention rate**, meaning human touches per landed
agent change, read next to quality (reverts per landed change).

---

## 5. Architecture

### 5.1 The rule that keeps it agnostic

**No core file names a language, build tool or deploy target.** Core means `qq`, `sync`, `gate`,
`test-pipelines`, `gardener` and `release`. Anything language-specific lives in an adapter under `recipes/`,
found through one loader, the way xo-space finds agents. A required check (an AST and grep guard)
enforces the rule from the first day. xo-space left its guard uncommitted, and suraj's teardown of it (`xo-space` §18) says a
control plane for verified work "should eventually not tolerate" that.

### 5.2 Three contracts

1. **Repo manifest** (`infra/repo.toml`, parsed and never executed, like DEPS). It lists pinned
   dependencies, pinned toolchains and **targets**. A target has a `kind` and declared inputs and
   outputs. Sketch for xo-space **[inf]**:

   ```toml
   schema = "quirq-repo/1"
   toolchains = { python = "oci://ghcr.io/quirq-ai/toolchains/python@sha256:…" }   # latest stable Python (D1; 3.14 on 2026-10-03), pinned by digest

   targets = [
     { name = "server",  kind = "python-service",  srcs = ["server.py", "services/**", "routers/**"] },
     { name = "tests",   kind = "pytest",          deps = ["server"], shards = "auto" },
     { name = "image",   kind = "container-image", deps = ["server"], platforms = ["linux/amd64", "linux/arm64"] },
     { name = "release", kind = "channel-release", deps = ["image", "tests"] },
   ]
   ```

2. **Adapter (recipe) contract.** A `kind` resolves to `recipes/<kind>/`. An adapter implements a subset of
   these capabilities: `fetch`, `build`, `test`, `package`, `run`, `deploy`, `bench`. A missing capability is a
   declared state, so a docs-only repo simply has no `package`. Each capability turns a target into
   **actions**. Adapters are versioned packages, pinned per repo.

3. **Action contract** (the universal unit). An action is a command, an input-root digest, platform
   properties and an environment, and it produces output digests, an exit code and test results. Apart from the test results, which REAPI carries only as
   output files, this is the REAPI `Action` and `ActionResult` **[cr]** (remote-apis `remote_execution.proto`). It is also the rule from `sea-of-nodes-paper` §14:
   "Operation plus inputs, hashed ... your dedup key, your cache key, and your incremental-rebuild key all
   at once." Tools that are not hermetic are marked `cacheable = false`, so they still run but are never reused.
   Test adapters emit JUnit XML, which pytest, vitest, jest (through jest-junit) and go (through gotestsum) can all produce. The
   result sink converts it into the results store's schema, as ResultSink does for ResultDB.

Repos that already use Bazel, Buck2 or Pants can keep them. Those tools speak REAPI natively **[cr]** and
share the same cache. Nobody is forced to migrate, which is the point of being agnostic.

### 5.3 How a change flows

```
agent/human ─ qq upload ─▶ PR ─▶ presubmit (manifest valid, generated files in sync, agnosticism guard,
                                     verification-surface rule)
                               ─▶ gate: merge queue builds exact merge result
                                     scheduler ─▶ executor adapter: local | Actions runner | REAPI remote
                                     results ─▶ test-pipelines: retry → compare with base → exonerate known flakes
                               ─▶ lands on main (linear history)
main ─▶ post-submit on every commit (never cancelled) ─▶ gardener: group, bisect, revert within budget
     ─▶ lkgr ref advanced by a builder ─▶ release: canary daily (agents) → dev (human approval) → stable (suraj, staged) ─▶ installer / deploy
fuzzers ─▶ per change in the gate, smoke in each canary, nightly batch ─▶ failure records (§5.9, §5.10)
rollers ─▶ edit pins through the sync library ─▶ PR ─▶ same gate
```

The scheduler is separate from the action graph, as the sea-of-nodes recipe advises ("Name the
scheduler"). GitHub Actions is the first executor and is replaceable.

### 5.4 Data model (adapted from `codex-session` §17)

`Change` (a PR, the unit of intent) → `Run` (one gate or post-submit attempt: config revision,
adapter versions, executor, lease) → `Result` (one test or action outcome, write-once, raw plus
normalized) → `Verdict` (computed mechanically from Results) → `Artifact` (digest, provenance) →
`Operation` (an external effect such as a deploy or publish, keyed before it happens, so a retry after a
crash can see "already done"). A lost worker leaves the run *uncertain*, and it is reconciled before any retry. A `Failure` record (§5.10)
links a red run, held canary or rollback to its culprit `Change`, the `Operation` that held or rolled it back,
and the fix `Change`.

### 5.5 The repos

suraj asked for separate repos for test pipelines, sync, installer and devtools, plus goma by inference. Below is
the full target set, each mapped to its Chromium counterpart. Each product repo also keeps its own `infra/`
directory, as `chromium/src/infra/config` does, but unlike Chromium it holds only the manifest: builder and
pipeline definitions live centrally in `infra-config` (D15).

| Repo | Owns | Chromium counterpart | Approach | Starts |
|---|---|---|---|---|
| `qq` (devtools, was `depot`) | The `qq` CLI: bootstrap, `fetch`, `sync`, `build`, `test`, `try`, `upload`, `land`, `roll`, `status`. Self-updating, with a pinned version per repo | depot_tools (`fetch`, `gclient`, `git cl`, `roll-dep`) **[w]** | Build (thin, wraps `gh` and git) | P1 |
| `sync` | The manifest schema, **the only parser and editor library**, the resolver, mirroring policy | gclient + DEPS + gclient_eval **[w]**; "three dependency types" **[cr]** | Build | P1 |
| `recipes` | Adapters per kind: python-service, pytest, node-app (pnpm/Next.js), container-image, static-docs, then go and rust | chromium/tools/build recipes + recipes-py **[cr]** | Build. Dagger is a candidate runtime inside adapters | P1 |
| `infra-config` | Shared config library and org-wide policy: pools, secret scopes, rotations, budgets, autonomy levels; since D15 also builder and pipeline definitions, channels, caps, fuzz schedules, postmortem policy and health signals (§5.6) | infra/chromium `@chromium-luci` lib + infradata/config **[w]** | Build | P1 |
| `test-pipelines` | Result schema and sinks, results store, flake detection, quarantine with expiry, retry and exoneration logic, autosharding | ResultDB/ResultSink + LUCI Analysis + test_executable_api + autosharder **[cr]**/**[w]** | Build on JUnit XML + a small store | P2 |
| `gate` | Required-check computation from config, merge-queue integration, reuse keys, quotas, tree status | LUCI CV + commit-queue.cfg **[cr]** | Adopt GitHub merge queue; build a thin check app | P2 (until then, gate config lives in `infra-config`) |
| `toolchains` | Hermetic toolchain images and packages built by CI, staging → promote, pinned by digest | CIPD + 3pp + clang upload/promote **[w]** | Adopt OCI registry; build recipes | P3 |
| `remote-build` (goma slot) | REAPI cache, then remote execution, worker images, client config, typed fallback counters | goma → reclient → Siso + RBE **[w]**; any REAPI backend **[cr]** | Adopt (bazel-remote cache, then Buildbarn) | P3 / P6 |
| `gardener` | Failure grouping by regression range, bisection, revert with budgets, tree status, rotation | Gardeners + Sheriff-o-Matic + LUCI Bisection + tree closers **[cr]** | Build (agent + small service) | P4 |
| `rollers` | Automatic pin updates for deps, toolchains and adapters, through `sync` | Skia AutoRoll **[w]** | Build on the `sync` lib. Ecosystem lockfiles via Dependabot (GitHub service; dependabot-core is MIT) or Renovate (AGPL-3.0-only) **[cr]** | P4 |
| `release` | Versioning, lkgr ref, branch cuts, channels, promotion, notes, deploy operations, rollback | V8's release scripts and lkgr finder + chrome-official-brancher **[w]**; LUCI `promote.py` **[cr]** | Build | P5 |
| `installer` | Client installers and updaters that follow a channel (xo-space's install.sh and in-app updater today follow `main` tip) | Windows installer packaging in chrome/tools/build/win **[w]** + chrome/updater, "a drop-in replacement for Google Update/Omaha/Keystone" that third-party embedders can customise for non-Google software on Windows, macOS and Linux **[cr]** | Build. Evaluate the Chromium updater for desktop apps; fit with quirq's apps not yet checked **[inf]** | P5 |
| `perf` | Benchmarks, dashboard, alert thresholds, bisect | chrome.perf + perf dashboard + Pinpoint **[cr]** | Build small; adopt later | P6 |

How they fit together: `qq` and `rollers` use `sync` to read and write manifests. `recipes` emits actions
and JUnit results that `test-pipelines` ingests. `gate` reads `infra-config` and each repo's `infra/` to decide
which checks are required. `gardener` reads `test-pipelines` results and writes revert PRs through `qq`.
`release` reads the lkgr ref that `gate`'s post-submit runs advance. `installer` reads `release`'s channels.
`remote-build` and `toolchains` sit under `recipes`.

**Recommendation:** create only `depot`, `sync`, `recipes`, `infra-config` and `test-pipelines` now, and create each
other repo when its phase starts. Chromium's infra took years to split this way **[inf]**. Splitting before there
are users would leave a three-product org maintaining thirteen repos.

**Superseded on 2026-10-03 (D3).** suraj chose to build all thirteen repos now, each as a base version with its
own delegable work items ([v0](v0.md), which also gives the dependency order). The "Starts" column now
reads as the phase in which each repo's work deepens.

### 5.6 Infra as code: what `infra-config` declares

Decided 2026-10-03 (D12): infra as code is a core pillar. Everything that decides how a change is built,
landed, shipped or rolled back is data in git. It is parsed and never executed, changed only by a reviewed
PR through the gate, and owner-approved because it is a policy path (§4). The v0 skeleton of `infra-config`
already exists with one TOML file per area ([v0](v0.md) records it as the baseline):

| Declared in code | File in `infra-config/config/` | Read by |
|---|---|---|
| System name, backends (`github` now, `launchpad` later, D7), pools, secret scopes, compute budget (D9), owners and rotations (D11) | `org.toml` | everything |
| Kinds and toolchains (year one: latest Python and latest Next.js, D1) | `kinds.toml` | recipes, toolchains |
| Repos onboarded (each repo keeps only its `infra/repo.toml` manifest) | `repos.toml` | gate, generator |
| Pipelines and builders: presubmit, post-submit, release (D15) | `pipelines.toml` | generator, gate, gardener |
| Gates: required checks, the verification surface, who may land what (D4) | `gate.toml` | gate |
| Flake retries, exoneration, quarantine expiry | `flakes.toml` | test-pipelines |
| Auto-revert caps (D5) | `auto_revert.toml` | gardener |
| Rollers | `rollers.toml` | rollers |
| Channels and promotion rules (§5.7) | `channels.toml` | release, installer |
| Fuzz engines and schedules (§5.9) | `fuzz.toml` | recipes, release |
| Postmortem policy and failure tracking (§5.10) | `postmortem.toml` | gardener, test-pipelines |
| Health signals and thresholds, PostHog included (§5.8, §5.11) | `health.toml` | release |
| Benchmarks and alert thresholds | `perf.toml` | perf |

Three rules. One schema per area and one validator (`qqcfg validate`), run as a required check. Generated
output, such as the GitHub workflow stubs, is checked in, and a required check fails if it drifts, as
Chromium's lucicfg presubmit does **[cr]**. Anything backend-specific sits under a `backend` field or a
sub-table named after the backend, so moving work to Launchpad changes config, not core code [inf].

### 5.7 Release channels: canary, dev, stable

**What Chromium does.**
- Chrome builds know four channels, listed "from most fun to most stable": canary, dev, beta, stable **[cr]**
  (`base/version_info/channel.h`).
- Canary builds "contain changes as soon as we make them, and are released twice daily with only automated
  testing", and "may still crash frequently". Dev "gets updated once or twice weekly" and "does get tested".
  New features spend "about a month in Beta before being promoted to Stable" **[cr]** (chromium.org, Chrome
  Release Channels). That page's cadences disagree with the tree's: `release_cycle.md` speaks of "the daily
  canary" and a two-week stable cycle **[cr]**, so I take cadence from the tree and only the roles from the page.
- A milestone branch is "the branch generated by the daily canary created at branch point" **[cr]**
  (`release_cycle.md`). Before a fix is merged to a release branch, its author confirms it, "preferably by
  testing on and monitoring the canary channel for 24 hours post-release" **[cr]** (`docs/process/merge_request.md`).
- Which build a user runs (channel) is kept apart from which features are on inside it (field trials) [inf].
  CI tests the active field-trial configurations through `fieldtrial_testing_config.json` **[cr]**
  (`testing/variations/README.md`).

**quirq's channels** (decided D4 and D8; mechanics are proposals):

| Channel | What it is | Who promotes | Gate to enter | A bad build |
|---|---|---|---|---|
| canary | The daily build of `lkgr`, deployed only to quirq's research and test environments | Agents alone, on a schedule. No approval | Green post-submit, then the canary pipeline (§5.8) | Held before deploy, or rolled back automatically after it. Failure record and postmortem draft (§5.10). The pipeline pauses itself after 2 failed canaries in a row |
| dev | A canary that soaked 24 h with no open failure record (Chrome's 24-hour canary check as the model), promoted about weekly. xo-space's existing `development` staging branch (`RELEASING.md`) is its natural home [inf] | An agent prepares the evidence, a human owner approves | 24 h clean soak, no new fuzz crash, health within thresholds | A human or agent holds promotion, the pointer moves back to the previous dev, a record is opened |
| stable | A dev build suraj promotes, targeting every two weeks (target pending his confirmation, §10.3 O8), with staged rollout where the product supports it. **Priority P4, low (D8)** | suraj only | Dev soak, release notes, a passed rollback drill | One-command rollback to the previous stable. Postmortem required |

**Where quirq deliberately differs.**
- **No beta.** In Chrome a milestone "spends two weeks total in the beta channel while undergoing stabilization"
  **[cr]** (`release_cycle.md`). That takes a population of beta users, which quirq does not have yet, so dev plus a
  human approval does the job [inf].
- **No release branches in year one.** Channels are pointers to commits on `main`, so fixes roll forward
  through `main` instead of being merged back [inf].
- **Canary never reaches users.** It runs in research and test environments that humans also use and regulate (D4).

**Mechanism** (proposal). A channel is a pointer, not a build: `channels/<name>` names a commit and an
artifact digest and is moved only by the `release` executor with an operation key (§5.4). Rollback moves the
pointer back; nothing is rebuilt. Container images get matching `canary` and `dev` tags when containers
arrive (v1). xo-space's installer can already track a ref other than `main` through `QUIRQ_SOURCE_REF`
(`INSTALLATION.md`), so test installs can follow `channels/canary` [inf]. GitHub environments carry the
human approvals: up to six required reviewers, one approval needed, optional self-review prevention, and on
Free, Pro and Team plans only in public repositories **[cr]**. GitHub's custom deployment protection rules can
gate on outside signals but are in public preview **[cr]**, so health gating stays in quirq's own pipeline [inf].
PostHog feature flags toggle features inside a build, as field trials do in Chrome. They are not channels (§5.11).

### 5.8 The daily canary pipeline

It runs once a day with nobody watching. Thresholds live in `health.toml` and `channels.toml` (§5.6).

**Scheduling.** v0 uses GitHub's `schedule` trigger. GitHub warns that scheduled runs can be delayed under
high load, that "some queued jobs may be dropped", that they run only on the default branch, and that in a
public repository they are disabled after 60 days without repository activity **[cr]**. So the canary runs off
the hour, and the gardener's watchdog starts it by hand (`workflow_dispatch`) if no canary exists by a set time
[proposal].

**Stages, in order.** Each stage writes Results to `test-pipelines`. A failure stops the pipeline, and the
previous canary stays in place.
1. **Select** the newest `lkgr` commit. If `lkgr` has not moved since the last canary, record a no-op and stop.
2. **Build** every target through its adapter, with digests and provenance.
3. **Verify**: the full test suites, not only the gate's subset, plus a smoke run of each artifact.
4. **Fuzz smoke**: replay every stored crash reproducer, then fuzz the changed areas for a fixed time (§5.9).
5. **Deploy**: the `release` executor moves `channels/canary`, recording the operation key first.
6. **Probe**: scripted checks against the deployed canary, starting with health endpoints (xo-space already has
   `/health`, which its Dockerfile `HEALTHCHECK` calls).
7. **Soak** for a set window (proposal: 2 h): probe results, error rates, and PostHog error-tracking issues and
   spikes tagged with the canary release (§5.11).
8. **Declare** the canary good. It becomes eligible for dev after 24 h with no open failure record.

**What stops or rolls back a canary automatically.**
- Stages 1–4 fail: nothing is deployed, a failure record opens, and the gardener bisects the day's commits.
- Stages 6–7 fail (probe failure, crash loop, error rate above threshold against the previous canary, or a new
  PostHog issue on the canary release above threshold): the pointer moves back, then a failure record and a
  postmortem draft open.
- A missing signal is not a healthy one. If probes or PostHog return no data, the canary is held, never promoted.
- Circuit breaker: 2 failed canaries in a row, or the revert cap reached (D5), pauses the pipeline.

**What reaches a human.** Only these: a paused pipeline, a rollback that failed, a P0 or P1 failure record (data
loss, a security-looking fuzz crash, a recurring class), a dev promotion waiting for approval, and postmortem
drafts waiting for review. Everything else goes into one daily canary report [proposal].

### 5.9 Fuzzing

**What Chromium does.** Fuzz targets "run continuously at scale on ClusterFuzz". New targets use FuzzTest, and
libFuzzer is marked deprecated for Chromium's own use **[cr]** (`testing/libfuzzer/README.md`). A FuzzTest sits
beside the unit tests and runs for one second when they run, and ClusterFuzz "typically begins running your new
fuzzer within two days" **[cr]** (`testing/libfuzzer/getting_started.md`): a short per-change pass, then
continuous depth. ClusterFuzz deduplicates crashes, minimises testcases, finds regression ranges by bisection
and does "Fully automatic bug filing, triage and closing" **[cr]** (README). Once a day it re-runs open testcases
against the latest build and records a "Fixed Revision Range" **[cr]** (`fixing-a-bug.md`).

**Why quirq does not run those directly.** ClusterFuzz depends on Google Cloud for many features **[cr]**
(prerequisites), which conflicts with a cloud-agnostic design (D7) [inf]. OSS-Fuzz accepts projects with "a
significant user base and/or be critical to the global IT infrastructure" **[cr]**, which quirq's repos are not
yet [inf]. libFuzzer's original authors have moved to Centipede, and it now gets bug fixes only **[cr]**
(LLVM `LibFuzzer.md`). ClusterFuzzLite runs inside CI, GitHub Actions included, and has code-change mode (10
minutes by default, stops at the first crash), scheduled batch mode, corpus pruning and coverage. It supports
C, C++, JVM languages, Go, Python, Rust and Swift, **not JavaScript** **[cr]** (ClusterFuzzLite README and docs).
ClusterFuzz, OSS-Fuzz and ClusterFuzzLite are all Apache-2.0 **[cr]**.

**Tools per kind** (proposal; `fuzz` is an adapter capability, so no core file names a fuzzer, §5.1):

| Kind | Per change, in the gate | Continuous and in the canary |
|---|---|---|
| `python-service` | Hypothesis property tests in pytest (MPL-2.0) **[cr]** | Atheris targets on parsers and input handlers, run by ClusterFuzzLite. Atheris is a coverage-guided Python fuzzer based on libFuzzer, Apache-2.0, Python 3.11–3.14 **[cr]**; Python 3.15.0 is due 2026-10-09 (PEP 790) **[cr]**, so Atheris targets may need a 3.14 toolchain until Atheris supports 3.15 [inf]. Schemathesis against the deployed canary's OpenAPI schema (MIT) **[cr]** |
| `node-app` (Next.js) | fast-check property tests in vitest or jest (MIT) **[cr]** | Jazzer.js targets, wrapped by the adapter. Jazzer.js is a coverage-guided Node.js fuzzer based on libFuzzer, Apache-2.0, and what OSS-Fuzz uses for JavaScript **[cr]**. Schemathesis on API routes with a schema |
| `container-image` (v1) | none of its own | Schemathesis against the booted container in the canary [inf] |
| `static-docs` (v1) | not fuzzed: build and link check | none |

**Where they run.** Property tests run as ordinary tests in every gate run, time-boxed. The canary runs a fuzz
smoke (§5.8, stage 4). Coverage-guided fuzzers run nightly in batch, with corpora stored outside the product
repos and pruned daily, as ClusterFuzzLite recommends **[cr]**.

**How a finding becomes a tracked bug** (proposal, ClusterFuzz's workflow rebuilt small). The runner groups
crashes by stack signature, minimises the input, and opens one issue per new signature with the reproducer,
build digest and regression range. The gardener bisects. The fix PR must add the reproducer to the regression
corpus, and the issue closes only when the daily replay passes. A daily filing cap lives in `fuzz.toml`.
Because the repos are public, crashes that look like security bugs stay out of public issues until fixed [inf].

### 5.10 Failure records and postmortems

**Every failure gets a record.** Every held canary, canary rollback, auto-revert and fuzz finding opens a
write-once `Failure` record in `test-pipelines`, mirrored to a labelled GitHub issue [proposal]. It holds the
channel and build digest, last good and first bad, the stage and signal that fired, the culprit change from
bisection, the action taken with its operation key, the fix change, the test or fuzz case that now covers it,
a failure class, and the postmortem link. A record closes only when culprit, fix and covering test are all linked.

**When a postmortem is required.** Google's SRE book lists triggers that include "On-call engineer intervention
(release rollback, rerouting of traffic, etc.)" and "A monitoring failure (which usually implies manual incident
discovery)" **[cr]**. quirq's triggers (proposal, in `postmortem.toml`): every canary rollback, every failure that
reached dev, and every failure a human found before the machinery did.

**Blameless, and agents draft them.** A blameless postmortem identifies "contributing causes of the incident
without indicting any individual or team" **[cr]** (SRE book). For quirq the same holds for agents: the postmortem
names the missing test, gate or signal, never "the agent was wrong" [inf]. The gardener agent drafts it from the
record, under the sealed-judge rule (§2): every claim cites a run, result, operation or commit. The sections follow
Google's example: summary, impact, root causes and trigger, timeline, lessons learned, and action items, each with
an owner and a tracking bug **[cr]** (SRE workbook). The workbook also says to "monitor the closure of action
items" **[cr]**, so action-item closure is on the scorecard (§8). Humans review drafts for P0 and P1 records.

**Recurring classes feed back into the system.** LUCI Analysis clusters failures and, through policies in config,
files a bug at a set priority when a cluster crosses an activation threshold and closes it below a deactivation
threshold. For example, it files a P0 when a cluster blocks 10 or more developer CLs in one day **[cr]**
(`luci-analysis.cfg`). quirq does the same for failure classes (proposal): a class seen twice in 14 days opens a
"close the class" work item, and that item is done only when one of three things lands and runs: a new test, a
new fuzz target or corpus entry, or a new gate or health signal.

### 5.11 PostHog

**How it is wired today** (read 2026-10-03; xo-space `c3cea98`, innernet `da9b84c`, docs `23215ff`).
- **xo-space: no PostHog.** It has an OpenTelemetry GenAI exporter for agent sessions
  (`services/cowork_agent/opentelemetry_exporter.py`, `routers/cowork_agent/opentelemetry.py`) and a `/health`
  endpoint. Its README promises that nothing leaves the machine by default: a self-hosted install "sends no usage data".
- **innernet: no PostHog.** Its only mention is in the generated index `data/demo/index.json`, which lists the docs
  repo's dependencies. Its public demo keeps its own visit history and never stores "an IP address, a user agent,
  cookies or any other header" (README).
- **quirq-ai/docs is where PostHog runs.** `posthog-js` ^1.392.0, a provider in
  `src/components/posthog/provider.tsx` (reverse proxy at `/ingest`, autocapture, session recording with every input
  masked, heatmaps, page-leave), manual `$pageview` capture in `pageview.tsx`, mounted in `src/app/layout.tsx`, rewrites
  to `us.i.posthog.com` in `next.config.mjs`, and off when `NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN` is unset. Its code sets up no
  error tracking, flags or server-side capture. Four gaps against PostHog's Next.js proxy guide: the guide says "The static and
  array rewrites must come before the catch-all", but docs puts `/ingest/static` after it and has no `/ingest/array` rewrite;
  the guide's required `skipTrailingSlashRedirect` is not set; and the SDK init has no `ui_host`, which the guide sets to
  `https://us.posthog.com` so the toolbar links correctly **[cr]**. Fixing them is v1 work item V1-PH-01.

So "integrated" today means web analytics and session replay on the docs site. Nothing in the CI or deploy path uses it yet.

**Where it fits** (proposal; each capability confirmed in PostHog's docs **[cr]**):
- **Canary health, from error tracking.** Python apps link exceptions to a release through `POSTHOG_RELEASE_ID`, and
  Next.js releases are created by source-map upload. Alerts go to a webhook when an issue is created or reopened, and
  spike detection compares each issue against a rolling baseline. The canary pipeline turns those webhooks into
  failure records. Use it on quirq's own canary instances and hosted sites only.
- **Staged rollout inside a build, with feature flags.** PostHog flags roll a change out to a percentage of users and
  turn it off "no redeploy, no hotfix", with server-side local evaluation in the Python and Node SDKs. PostHog's own
  canary-release guide widens release conditions step by step. As with Chrome's field-trial config, the canary tests
  the flag configuration it ships with [inf].
- **Soak-window metrics, from insight alerts.** Threshold and anomaly alerts on trends, funnels and SQL insights,
  sent to webhooks, Slack or email, for signals such as a key event dropping after a canary deploy.
- **Context, from error-tracking integrations.** PostHog can create GitHub issues from errors and link stack frames
  to commits; the failure record links the PostHog issue.

**What PostHog should not be used for.**
- **Not the gate, and not the source of truth.** Verdicts come only from the results store (§3 P5). PostHog's
  `/query` endpoint "is not a supported export mechanism", and it warns that "Pipelines built on `/query` may break at
  any time" **[cr]**.
- **Not the fast rollback trigger on its own.** Real-time alert checks (about every two minutes) need a Scale or
  Enterprise plan, 15-minute checks need Boost or higher, and otherwise checks run hourly or less often. The free tier
  allows 5 alerts in total. Spike detection works hourly over 5-minute buckets **[cr]**. Probes are the fast signal;
  PostHog is a soak signal, and missing PostHog data means hold.
- **Not inside self-hosted xo-space or local innernet** without an explicit opt-in, because both promise not to send
  such data. On hosted sites, PostHog can discard client IPs at organization and project level and can track without
  cookies **[cr]**. Adding it to the innernet demo would also mean changing that README's promise, which is suraj's call [inf].
- **Not a channel mechanism.** Flags switch features inside a build. Channels choose builds.
- **Not storage for CI results or fuzz crashes.** Reproducers can be security-sensitive [inf].

---

## 6. Build vs buy vs adopt

| Candidate | What it is (source) | Licence | Verdict |
|---|---|---|---|
| **LUCI** (Buildbucket, Swarming, CV, ResultDB, Analysis, Bisection) | Chromium's CI services **[cr]** | Apache-2.0 **[cr]** | **Copy the designs, don't run it.** Its services sit on Google Cloud (READMEs reference Spanner, App Engine and Cloud Run) **[cr]**, and CV is built around Gerrit changes **[cr]**. Running it for a GitHub org would mean porting it **[inf]**. |
| **GitHub merge queue + Actions** | The queue groups PRs with the base branch and merges once required checks pass; workflows must listen for `merge_group` **[cr]** | SaaS | **Adopt now** as the gate and first executor, behind an interface. Availability: public org repos, or private repos with Enterprise Cloud **[cr]**. Needs admin. |
| **Bazel / Buck2 / Pants** | Multi-language hermetic build systems that speak REAPI **[cr]** | Bazel Apache-2.0; Buck2 MIT or Apache-2.0 **[cr]** | **Allow, don't require.** Requiring one would make the system language-specific and force migrations. Chromium uses GN and Siso, not Bazel, yet still uses REAPI **[cr]**. |
| **REAPI servers** | Buildbarn (Apache-2.0), bazel-remote (cache only, Apache-2.0), BuildBuddy (Commercial & MIT), NativeLink (Commercial & FSL-1.1-ALv2) **[cr]** | as listed | **Adopt bazel-remote for cache (P3), Buildbarn for remote execution (P6).** NativeLink's FSL is not OSI-approved, so it fails the test in `where-the-json-lives` §05 **[inf]**. |
| **Nix** | "reliable and reproducible" package manager **[cr]** | LGPL-2.1 **[cr]** | **Optional** inside toolchain images. Not the contract, because it has a steep learning curve for agents and humans **[inf]**. |
| **Dagger** | "build, test and ship any codebase", runs locally or in CI; the only host dependency is a container runtime **[cr]** | Apache-2.0 **[cr]** | **Evaluate in P2** as the runtime inside adapters, which gives local and CI parity. Keep it behind the adapter seam: it is governed by one company, and that governance could change **[inf]**. |
| **Tekton** | Kubernetes-native pipeline resources **[cr]** | Apache-2.0 **[cr]** | **Not now.** It assumes Kubernetes, which quirq does not run **[inf]**. |
| **Buildkite** | Hosted control plane. The agent polls buildkite.com and runs jobs on your machines **[cr]** | Agent MIT; control plane SaaS | **Fallback executor** if Actions limits start to hurt. |
| **Zuul** | A project-gating system ("Project Gating" docs) | Apache-2.0 **[cr]** (zuul 14.3.0 sdist LICENSE) | **Skip.** Heavy to operate for our size **[inf]**. |
| **ClusterFuzz / OSS-Fuzz / ClusterFuzzLite** | Chromium's fuzzing backend; Google's free service for qualifying open source; a CI-run version **[cr]** | Apache-2.0 **[cr]** | **Adopt ClusterFuzzLite for Python; copy ClusterFuzz's workflow (dedup, automatic filing, daily fix re-test) and don't run ClusterFuzz itself**, which leans on Google Cloud **[cr]** (§5.9). |
| **PostHog** (already used on the docs site) | Product analytics, error tracking, feature flags, alerts **[cr]** | SaaS (PostHog Cloud, US region per the docs repo's config); the code is MIT outside `ee/` **[cr]** | **Use as a soak-time health signal and the flag tool, never as the gate** (§5.11). |

Net: we build about a third of the system, and it is the third that encodes quirq's rules: the manifest, the
adapters, flake policy, the gardener and release. We adopt the commodity parts: queue, runners, cache,
executors, registry.

---

## 7. Roadmap

Each phase ends with a test that either passes or fails. "Agents" means Claude sessions working through PRs.
"suraj" marks admin-only or policy steps.

| Phase | Goal | Exit criterion |
|---|---|---|
| **P0 Baseline** (1–2 wks) | Fill the unknowns in ci-cd-vision.md, decide §10, create the first five repos as skeletons (since D3: all thirteen as base versions, [v0](v0.md)), publish scorecard v0 | Every baseline item is a fact or an explicit "none". The scorecard is computed by a script from GitHub data, not typed by hand. §10 decisions are recorded |
| **P1 Gate the first users** | xo-space and innernet get `infra/repo.toml`. Adapters `python-service`, `pytest`, `node-app`, `container-image` (moved to v1 by D1). Generated `tests` check. Merge queue on (suraj). `merge_group` trigger. CODEOWNERS for policy paths. Agnosticism guard required | A deliberately red PR is refused in both repos. Both repos' CI is generated from their manifests by shared adapters, with no hand-written YAML beyond a generated stub. Onboarding `wiki` (a docs-only kind) takes only a manifest and adds no core code |
| **P2 Results and flakes** | `test-pipelines`: JUnit ingestion, results store, retry → compare with base → exonerate. Quarantine with expiry. `qq try` runs the same actions locally. Dagger evaluated. Property tests (Hypothesis, fast-check) run in the gate (§5.9) | 100% of test results stored. Flake rate reported weekly. A planted flaky test is detected and quarantined by an agent with an issue and an expiry date, and CI fails once the date passes. Local and CI verdicts match for the same inputs. A planted input-handling bug is caught by a property test |
| **P3 Hermetic and cached** | Toolchains pinned by digest via `toolchains`. External deps mirrored. REAPI cache (bazel-remote). Reuse of unchanged results | Re-running CI on an unchanged commit gets at least 90% cache hits. A fresh machine reproduces the same output digests for targets marked deterministic. 100% of deps are pinned and mirrored |
| **P4 Gardening and rollers** | Post-submit on every main commit (never cancelled). Tree status. `gardener` agent with LUCI-style budgets. `rollers` for pins and lockfiles. Every auto-revert opens a failure record and a postmortem stub (§5.10) | A planted build-breaking commit is reverted automatically within 30 min. A planted test break gets a revert PR (proposed, not submitted). Rollers land weekly updates through the gate with no human. Main-red time under 60 min/week for 4 weeks in a row. Every auto-revert has a failure record linked to culprit and fix |
| **P5 Release, deploy, installer** | lkgr ref. Unattended daily canary by agents (§5.8) with fuzz smoke, soak, automatic rollback, failure records and postmortem drafts. Dev weekly with human approval. PostHog health signals and flags (§5.11). Deploys keyed by operation. **Priority P4, low (D8):** stable promotion, staged rollout, `installer` follows channels | 14 green canaries in a row with no human touch. A planted bad canary is rolled back automatically within its soak and gets a failure record and a cited postmortem draft. A planted fuzz crash becomes one issue and closes only after its fix's replay passes. Dev promoted 4 times by human approval. *Low priority, may trail:* one stable promotion with accurate notes; a rollback drill restores the previous stable in under 10 min; xo-space's installer and updater follow a channel, not `main` |
| **P6 Speed, fleet, perf** | Buildbarn remote execution for heavy targets. Autoscaled workers and sandboxes. `perf` benchmarks with alerts and bisect | Gate p50 under 10 min and p90 under 20 min for 4 weeks. A planted 10% perf regression is alerted and bisected to its culprit |
| **P7 Autonomy** | Agents hold the gardener, roller and release rotations. Humans own policy and stable promotion | 8 weeks with intervention rate under target (see §10), revert rate not worse than P4, and no policy-path change landed without owner approval |

The order follows `codex-session` §18: prove correctness and recovery (P1–P2) before speed and scale (P3, P6), and
prove those before handing over autonomy (P7).

### 7.1 Version plans: v0, v1, v2

Decided 2026-10-03 (D13): the phases are delivered as three versions, so the team starts with a base version of
every repo and adds depth later. Each version file lists, per repo, discrete work items with a one-line scope, a
done-when test and dependencies, and leaves the owner blank for suraj to assign (D11).

| Version | Delivers | Phases | Work items |
|---|---|---|---|
| [v0](v0.md) | A base version of all thirteen repos. xo-space and innernet gated from manifests on GitHub. An agent-run daily canary with hold and rollback. Auto-revert within the cap of 10. Property tests. The `infra-config` skeleton as baseline | P0, P1 (except its `wiki` criterion, which needs the v1 docs-only kind), and a thin slice of P2, P4 and P5 | 51 |
| [v1](quirq-infra/v1.md) | Unattended canary (soak, automatic rollback, circuit breaker), the dev channel, fuzzing per kind, failure classes and postmortem drafts, PostHog signals and flags, flake handling, hermetic builds and a shared cache, container and docs kinds | The rest of P2, P3 and P4, and P5's canary and dev parts | 44 |
| [v2](quirq-infra/v2.md) | Launchpad backend, remote execution, perf bisection, fuzzing depth, agents on every rotation. Stable and the installer at priority P4 | P5's stable and installer parts, P6, P7 | 25 |

---

## 8. Scorecard

The scorecard is computed by a script from GitHub and the results store, never typed by hand. Targets are proposals.

| Metric | Measured as | Target |
|---|---|---|
| Repos behind the gate | repos with manifest + merge queue + required checks / product repos | 100% by end of P1 for existing repos |
| Landed on a green merge result | merged PRs whose required checks passed on the merge-group SHA | 100% (enforced) |
| Gate time-to-green | queue entry → verdict, p50 / p90 | P1: under 15 / 30 min; P6: under 10 / 20 min. Chromium's admission bar is under 40 min median **[cr]** |
| Main-red time | first red post-submit run → next green, per week | under 60 min/week |
| Time to revert a culprit | first red → revert landed | mean under 30 min (P4+) |
| Flake rate | runs that pass on retry with the same inputs / all runs | under 1% |
| Expired quarantines | quarantined tests past their expiry date | 0 |
| Cache hit rate | reused actions / all actions on unchanged inputs | at least 90% (P3+) |
| Reproducibility | deterministic targets with matching digests across machines | 100% of those declared deterministic |
| Pinned and mirrored deps | from `sync` | 100% |
| Release cadence | releases per channel | canary daily (v0 on), dev weekly (v1 on), stable every two weeks as a target, each promotion approved by suraj (target pending his confirmation; priority P4) |
| Rollback time | drill, previous stable restored | under 10 min |
| Unattended canary days | canary days with zero human touches / days on which lkgr moved | 14 in a row by the P5 exit, then above 90% |
| Canary hold or rollback time | health signal fired → previous canary restored | under 15 min (proposal) |
| Failures fully recorded | records linking culprit, operation, fix and covering test / all held or rolled-back canaries, auto-reverts and fuzz findings | 100% |
| Postmortem action items closed | items closed within 30 days / items due | at least 90% |
| Open recurring failure classes | classes seen twice in 14 days with no new test, fuzz target or gate yet | 0 |
| Fuzz finding turnaround | new crash signature → issue filed; fixed findings whose reproducer is replayed daily | under 24 h; 100% |
| Intervention rate | human commits or approvals per landed agent PR (excluding policy-path approvals, which are required) | falling every month; P7 target set by suraj |
| Revert precision | agent reverts later confirmed as the culprit / all agent reverts | at least 90% |
| CI cost per landed change | all-in compute + hosted minutes / landed PRs | measured; it is quirq's cost side for this unit type |

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| **Over-building.** Thirteen repos for three products | Create repos only when their phase starts (§5.5); superseded by D3, so all thirteen start as thin v0 base versions (§7.1). Each phase must earn the next |
| **The abstraction leaks.** Docker builds and package installs are often not hermetic | `cacheable = false` is allowed and visible. Reproducibility is measured, not assumed |
| **The manifest gets stuck**, as DEPS did | Versioned schema from day one. A single parser library. A presubmit that rejects new parsers |
| **Agents game verification** (edit tests, quarantine away failures) | Verification-surface rule (§4). Quarantine needs an issue and an expiry. Owner approval on policy paths |
| **Auto-revert harm** | LUCI Bisection's budgets as defaults: at most 10 created (per failure type) and 4 submitted per day, auto-submit only for culprits under 6 h old, test reverts proposed not submitted **[cr]** |
| **GitHub dependency and limits** | Merge queue availability depends on plan and visibility **[cr]**. The executor sits behind an interface, and Buildkite is the fallback |
| **Supply chain and secrets.** Agents near deploy credentials | Separate pools for untrusted PR runs and trusted post-submit and release runs (Chromium's "pool as security boundary" **[cr]**). Short-lived OIDC credentials. Operation keys on every deploy |
| **Licence or governance change in an adopted tool** | Prefer OSI licences under foundation governance. Adopted tools sit behind seams |
| **One-person bus factor** | Everything is config in the tree, runbooks are in repos, and agents can run every rotation |
| **Compute cost of retries and post-submit** | A budget in `infra-config`. CI cost per landed change is on the scorecard |
| **The unattended canary does harm** | It deploys only to research and test environments (D4). Automatic hold and rollback, a circuit breaker after 2 failed canaries, and the cap of 10 reverts a day (§5.8) |
| **Health signals arrive late or not at all** | Missing data means hold, never healthy. Probes are the fast signal. PostHog alerts are checked every few minutes to hours depending on the plan **[cr]**, so they serve the soak window only (§5.11) |
| **Telemetry breaks a privacy promise** | No PostHog in self-hosted xo-space or local innernet without explicit opt-in; client IPs discarded on hosted sites (§5.11) |
| **Fuzz findings disclosed in public repos** | Security-looking crashes stay out of public issues until fixed **[inf]** |
| **GitHub drops a scheduled run** | Off-the-hour schedule plus a watchdog that starts a missed canary (§5.8) **[cr]** |

---

## 10. Decisions

### 10.1 Decided on 2026-10-03

suraj answered in two rounds on the same day. Where the second round changed the first, the later answer
wins and the row says so. Quotes are verbatim.

| # | Question (§10.2 row) | Decision | Notes |
|---|---|---|---|
| D1 | Year-one scope of "anything" (1) | First round: Python services, Node and Next.js apps, container images, docs. Second round: "lets just start with latest version of next js and python, we have containers but can later add supprot for more." **Year one starts with latest Python and latest Next.js; containers and docs-only repos follow in v1.** | The second answer narrows the first. That docs-only repos also wait is my reading [inf] |
| D2 | Repo visibility (2) | Infra repos are public. "we will only work on public repos for starters", so onboarded product repos are public too. | GitHub's merge queue then needs no Enterprise Cloud **[cr]** |
| D3 | How many repos at the start (3) | First round: create five first (`depot`, `sync`, `recipes`, `infra-config`, `test-pipelines`). Second round: "lets build all of them because they are all important, so we make different different work-items and delegate them". **All thirteen get a v0 base version, as delegated work items.** | Supersedes the first round and the §5.5 recommendation. [v0](v0.md) gives the dependency order |
| D4 | Agent autonomy (4) | Agents may land clean reverts, dependency rolls and docs on their own. Policy changes and stable promotion need suraj. "github will always have human owners before releases". The fully autonomous loop (the agent-run canary [inf]) is a research and test environment that humans also use and regulate. | Rolls and docs go beyond Chromium's Rubber Stamper, which covers clean reverts, clean cherry-picks and translation files **[cr]** |
| D5 | Auto-revert (5) | Auto-revert within LUCI Bisection-style daily caps. "yess lets implement the auto-revert, based on 10 sounds good." **quirq's rule: at most 10 reverts created per rolling 24 h across all repos and failure types.** LUCI's finer limits sit beneath it as defaults: for build failures, at most 4 auto-submitted and only culprits under 6 h old; test-failure reverts are proposed, not submitted **[cr]** (§3 P6). | One cap across failure types is the `infra-config` skeleton's reading of "based on 10" [inf]; LUCI itself caps compile and test failures separately **[cr]**. That the 10 counts reverts created is a default I picked, not suraj's words; he can change it (§10.3 O2) |
| D6 | Toolchain transport (6) | "not sure, if low priority then we will document it as that one." **Recorded as low priority.** OCI images pinned by digest stay the default until revisited (v2). | Mapping this answer to row 6, and reading his conditional "if low priority" as a yes, are my inferences [inf] |
| D7 | First executor and cloud (7) | "we will execute all of this on our custom cloud and priduct called launchpad ... design the architecture cloud agnostic and we start the first v0 version with github". **Cloud agnostic; v0 on GitHub (merge queue and Actions) behind the executor interface; Launchpad, quirq's own cloud, later.** | `infra-config` carries this as a `backend` field: `github` now, `launchpad` planned |
| D8 | Channels and cadence (8) | "already mentioned ahdyes": canary built and shipped by agents, dev by humans and agents, then stable. No beta. Release work beyond canary and dev (stable promotion, installer and updater) is **priority P4, low**, and stays late in the roadmap. | "P4" is suraj's priority label here, not phase P4 |
| D9 | Monthly compute budget (9) | "yes": set a ceiling now. | The amount is still open (§10.3) |
| D10 | Names (10) | "yes quirq infra and qq sounds really good." The system is "quirq infra", the CLI and prefix `qq`. | Repo names in §5.5 kept |
| D11 | Owners | suraj assigns human and AI owners. The system reads them from CODEOWNERS and `infra-config`; it never assigns them (§4). | |
| D12 | Infra as code | A core pillar: everything in §5.6 is declared in code. | |
| D13 | Version plans | Plan the work as v0, v1, v2, "this way the team starts with base version of all repos ... and then slowly add more complex things" (§7.1). | |
| D14 | Plan depth | Future planning goes breadth first and high level, just enough for experts to take over. Guidance for future work: existing sections were not trimmed for it. | |
| D15 | Where builders live | Builder and pipeline definitions live centrally in `infra-config`; each repo keeps only its manifest. | Differs from Chromium, which keeps them in `src/infra/config` **[cr]**. Reconciled with the `infra-config` skeleton |

### 10.2 The questions as first asked

Kept for the record. Where §10.1 differs, §10.1 wins.

| # | Decision | Recommendation |
|---|---|---|
| 1 | **What "anything" covers in year one** | python-service, node and Next.js apps, container images, static docs. Then go and rust. Mobile and desktop only when a product needs them |
| 2 | **Repo visibility and GitHub plan** | Merge queue works on public org repos, or private ones on Enterprise Cloud **[cr]**. Recommend: infra repos public. Product repos as you prefer; if private and no Enterprise Cloud, the `gate` app has to implement the queue itself (bors-style), which adds about a phase of work **[inf]** |
| 3 | **How many repos at the start** | Five (`depot`, `sync`, `recipes`, `infra-config`, `test-pipelines`), the rest by phase. Alternative: one `infra` monorepo split later. Cheaper, but not what you asked for |
| 4 | **Agent autonomy boundary** | Agents may land anything that passes the gate and has owner approval. An agent may approve clean reverts, roller PRs and docs. Chromium's Rubber Stamper covers only clean reverts, clean cherry-picks and translation files, and Chromium requires human review for docs **[cr]** (code_reviews.md), so roller PRs and docs go beyond that precedent **[inf]**. Policy paths and stable promotion need suraj |
| 5 | **Auto-revert policy** | Start with LUCI Bisection's numbers (10 created and 4 submitted per day; auto-submit only build-break culprits under 6 h old); revisit after 4 weeks |
| 6 | **Toolchain transport** | OCI images pinned by digest (ghcr), built by `toolchains`. Nix optional inside images |
| 7 | **First executor** | GitHub Actions (hosted, then self-hosted runners) behind the executor interface. Buildkite as the fallback |
| 8 | **Channels and cadence** | canary (daily from lkgr), beta (weekly), stable (every 2 weeks, Chromium's current cadence **[cr]**) |
| 9 | **Monthly CI compute budget** | Set a ceiling now. The scorecard reports cost per landed change against it |
| 10 | **Names** | Working names: "quirq infra" for the system and `qq` for the CLI. The repo names in §5.5 are placeholders |

### 10.3 Still open

| # | Decision | Recommendation |
|---|---|---|
| O1 | The compute ceiling's amount (D9) | Set it from 4 weeks of measured v0 spend plus headroom. The scorecard already reports cost per landed change |
| O2 | What the cap of 10 counts (D5): reverts created or reverts auto-landed | Reverts created, as LUCI's create limits do **[cr]**. It is the stricter reading and bounds what humans have to look at. This is the default in `infra-config` now, and suraj can change it |
| O3 | Who uses the canary | Only quirq's research and test environments, plus team members who opt in. No outside users before stable exists |
| O4 | PostHog plan, project and scope | A separate PostHog project for canary signals, so product analytics stay clean, with client IPs discarded. Confirm the plan tier, because alert frequency depends on it **[cr]** |
| O5 | Telemetry from self-hosted xo-space | None by default, as its README promises. xo-space's canary health comes from quirq's own test instances |
| O6 | Canary hour and soak window | Off the hour, as GitHub advises for scheduled runs **[cr]**, early in suraj's working day so a paused pipeline is seen the same day. Soak 2 h to start |
| O7 | May an agent roll stable back alone on a health breach? | Yes, but only to the previous build suraj already approved. Promotion stays with suraj. The `infra-config` skeleton also lists this as a TODO in `channels.toml` |
| O8 | Stable cadence | A target of every two weeks, Chromium's stable cycle **[cr]**, with suraj approving each promotion. Pending his confirmation; the `infra-config` skeleton lists it as a TODO in `channels.toml` |

---

## 11. What this plan is not sure of

- That "gp,a" means goma ([inf], §1).
- The 20% roller share, the 1,211 builders, tryjob reuse, and Chromium's linear numbering come from suraj's
  teardowns ([w]). I re-checked the CQ docs, the release cycle, ResultDB, gardening, LUCI Bisection limits,
  the CQ submit pacing (`max_burst: 2`) and the 32 blocking CQ builders myself ([cr]). The generated
  `commit-queue.cfg` now holds 607 builder entries, where the teardown counted 604, so the tree has moved
  since f288fed6.
- I read Chromium sources through the official GitHub mirror (`github.com/chromium/chromium`,
  `github.com/luci/luci-go`) on 2026-10-03, because this session's proxy blocks `chromium.googlesource.com`.
  The URLs in §12 point at the canonical hosts.
- Whether running LUCI outside Google is practical. My "don't run it" verdict is an inference from
  the dependencies named in its READMEs.
- Whether the Chromium updater fits quirq's desktop apps (**[inf]**, §5.5). Zuul's licence (Apache-2.0) and Renovate's (AGPL-3.0-only) are now checked **[cr]**.
- Every time and percentage target in §7 and §8 is a proposal, not a measurement.
- Chrome's channel cadence. chromium.org's Chrome Release Channels page says canary ships "twice daily" and stable
  majors "every four weeks"; an older chromium.org page (updated Oct 2016) says "Canary is updated every day (at
  ~4am PST)"; `release_cycle.md` in today's tree speaks of "the daily canary" and a two-week stable cycle. I take
  cadence from the tree and only each channel's role from the channels page (§5.7).
- Which PostHog plan quirq is on. Alert frequency and the number of alerts depend on it **[cr]**; §5.11 assumes no
  real-time alerts.
- That each Python service serves an OpenAPI schema Schemathesis can use. xo-space does: it is a FastAPI app that keeps
  FastAPI's default `/openapi.json` (OpenAPI 3.1.0), and Schemathesis supports OpenAPI 2.0 to 3.2 **[cr]**. Other services
  **[verify]** when onboarded.
- PostHog annotations, for marking canary deploys, can be created through the REST API: PostHog registers a full
  create/read/update viewset at `/api/projects/:project_id/annotations/` **[cr]** (PostHog/posthog
  `products/annotations/backend/routes.py`).
- My mapping of suraj's second-round answers onto the ten questions in order, especially the sixth (toolchain
  transport, D6) and the eighth ("already mentioned ahdyes", D8) **[inf]**.
- I read chromium.org and the Google SRE pages through a fetch tool, and the other new sources from their GitHub
  repos (PostHog/posthog.com, github/docs, google/clusterfuzz, google/clusterfuzzlite, google/oss-fuzz,
  llvm/llvm-project and the fuzzers' own repos), all on 2026-10-03.

---

## 12. Sources

**suraj's writings** (`github.com/sharmasuraj0123/writings`, read 2026-10-03): `chromium/ci-cd-and-releases/`,
`chromium/deps-and-goma/`, `chromium/sea-of-nodes-paper/` §14, `xo-space/`, `xo-space-architecture/`,
`whitepaper/`, `what-is-quirq/`, `codex-session/`, `claude-code-session/`, `research/spacewalk-architecture/`,
`markov-processes/` §13, `game-timers/` §09, `where-the-json-lives/` §05, `liveblocks-for-xo-space/`,
`page-registries/` §06, `personal-memory-engine/`. Per-file notes are in [writings-notes.md](writings-notes.md).

**Chromium** (canonical `https://chromium.googlesource.com/chromium/src/+/main/<path>`, read via the GitHub mirror):
- `docs/infra/cq.md`: CQ modes, structure, 40-min bar, ~20,000 flaky tests, footers
- `docs/infra/glossary.md`: LUCI, Buildbucket, CV, CIPD, Milo, recipes, Swarming pools and dimensions, CAS
- `docs/infra/builder_types.md`: "nearly 100% of all workloads ... run as Swarming tasks" (Q2 2025)
- `docs/testing/resultdb.md`: ResultDB as the source of pass/fail decisions
- `docs/gardener.md` and `docs/code_reviews.md`: gardener duties and authority; OWNERS; Rubber Stamper
- `docs/process/release_cycle.md`: two-week stable, beta, early stable, staged rollout, extended stable
- `docs/speed/perf_waterfall.md` and `docs/speed/addressing_performance_regressions.md`: perf waterfall, dashboard, Pinpoint
- `docs/dependencies.md`: three dependency types; no direct non-Google-hosted dependencies
- `docs/linux/build_instructions.md`: Siso, REAPI, non-Google REAPI backends
- `infra/config/README.md`, `infra/config/luci-bisection.cfg`, `infra/config/generated/luci/commit-queue.cfg`,
  `infra/config/generated/cq-usage/default.cfg`, `infra/config/generated/luci/luci-analysis.cfg`
- `chrome/updater/README.md`: the open-source updater
- Siso: `https://chromium.googlesource.com/build/+/refs/heads/main/siso/README.md`
- Sheriff-o-Matic: `https://www.chromium.org/developers/tree-sheriffs/sheriff-o-matic/`

**LUCI** (`https://chromium.googlesource.com/infra/luci/luci-go/`, read via `github.com/luci/luci-go`):
`README.md`, `LICENSE` (Apache-2.0), `cv/README.md`, `bisection/README.md`, `analysis/README.md`,
`resultdb/README.md`. Recipes: `github.com/luci/recipes-py` `README.md`.

**Other:** `github.com/bazelbuild/remote-apis` README (clients, servers, licences); GitHub Docs "Managing a merge queue"
and the merge-queue availability snippet (`github/docs` repo); READMEs and licences of `bazelbuild/bazel`,
`facebook/buck2`, `NixOS/nix`, `dagger/dagger`, `tektoncd/pipeline`, `buildkite/agent`, `renovatebot/renovate`, `dependabot/dependabot-core`
and the `zuul` 14.3.0 sdist; `bazelbuild/remote-apis` `remote_execution.proto`; luci-go `bisection/proto/config/project_config.proto`
and `bisection/culpritaction/revertculprit/`; Chromium `infra/config/generators/cq-usage.star`; Zuul "Project Gating"
docs page title (`https://zuul-ci.org/docs/zuul/latest/gating.html`, not read in full).

**Added in the 2026-10-03 revision** (§5.6–§5.11, §10.1):
- Chromium (via the GitHub mirror): `base/version_info/channel.h` (four channels), `docs/process/release_cycle.md`
  (daily canary, beta stabilisation), `docs/process/merge_request.md` (24 h canary monitoring before a merge),
  `testing/variations/README.md` (field-trial testing config), `testing/libfuzzer/README.md` and
  `testing/libfuzzer/getting_started.md` (ClusterFuzz, FuzzTest preferred, libFuzzer deprecated in Chromium),
  `infra/config/generated/luci/luci-analysis.cfg` (bug-management policies).
- chromium.org: "Chrome Release Channels" (`https://www.chromium.org/getting-involved/chrome-release-channels/`)
  and "When will a fix ship in Chrome (stable or canary)?" (`https://www.chromium.org/blink/when-will-a-fix-ship-in-chrome-stable-or-canary/`).
- Fuzzing: `google/clusterfuzz` README, `docs/index.md`, `docs/getting-started/prerequisites.md`,
  `docs/using-clusterfuzz/workflows/fixing-a-bug.md`, LICENSE; `google/clusterfuzzlite` README,
  `docs/running_clusterfuzzlite.md`, `docs/running-clusterfuzzlite/github_actions.md`,
  `docs/build-integration/python_lang.md`, LICENSE; `google/oss-fuzz` `docs/getting-started/accepting_new_projects.md`,
  `new_project_guide.md`, `new-project-guide/javascript_lang.md`, LICENSE; LLVM `llvm/docs/LibFuzzer.md` (status);
  READMEs and licences of `google/atheris`, `CodeIntelligenceTesting/jazzer.js`, `HypothesisWorks/hypothesis`,
  `dubzzz/fast-check` (`packages/fast-check/README.md`) and `schemathesis/schemathesis`.
- PostHog docs (`github.com/PostHog/posthog.com`, `contents/docs/`, commit 4c27ff7): `feature-flags/index.mdx`,
  `feature-flags/canary-release.md`, `feature-flags/creating-feature-flags.mdx`, `feature-flags/local-evaluation/index.mdx`,
  `error-tracking/releases.mdx`, `error-tracking/link-releases/index.mdx`, `error-tracking/alerts.mdx`,
  `error-tracking/spikes.mdx`, `error-tracking/integrations.mdx`, `alerts/index.mdx`, `data/annotations.mdx`,
  `api/queries.mdx`, `privacy/data-collection.mdx`, `advanced/proxy/nextjs.mdx`.
- GitHub Docs (`github/docs`): `content/actions/reference/workflows-and-actions/deployments-and-environments.md`,
  `content/actions/concepts/workflows-and-actions/deployment-environments.md`,
  `content/actions/reference/workflows-and-actions/events-that-trigger-workflows.md` (`schedule`),
  `data/reusables/actions/schedule-delay.md`, `about-custom-deployment-protection-rules.md`,
  `custom-deployment-protection-rules-beta-note.md`.
- Postmortems: Google SRE book, "Postmortem Culture: Learning from Failure" (`https://sre.google/sre-book/postmortem-culture/`),
  and SRE workbook, "Postmortem Culture" (`https://sre.google/workbook/postmortem-culture/`).
- quirq-ai repos, cloned read-only: `xo-space` at c3cea98 (README, RELEASING.md, INSTALLATION.md, Dockerfile,
  `.github/workflows/`, OpenTelemetry exporter), `innernet` at da9b84c (README, package.json, data/demo/index.json),
  `docs` at 23215ff (`src/components/posthog/`, `src/app/layout.tsx`, `next.config.mjs`, package.json, .example.env).
- The `infra-config` v0 skeleton (this repo, first shared as a zip; earlier draft `infra-config-v1/`): README and `config/*.toml`.
- Versions on 2026-10-03: PEP 790 and PEP 745 (`python/peps`) and CPython's git tags (3.14.8 latest stable, 3.15.0rc3);
  the npm registry's `next` dist-tags (`latest` 16.3.8). PostHog/posthog `products/annotations/backend/routes.py` and
  `LICENSE`; FastAPI 0.142.2 `fastapi/applications.py` (default `openapi_url`).
