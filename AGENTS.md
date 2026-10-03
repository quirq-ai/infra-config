# Agent guide

How an agent changes this repo safely. Read `README.md` first. This repo configures the system
that verifies everyone's work, including yours, so it is held to a stricter standard than product
code.

## The rule

**Config changes go through the same gate as code.** Every change is a pull request. It lands
only when the required `validate` check (`qqcfg validate` plus the unit tests) is green on the
exact merge result in the merge queue, and the right person has approved it. Never push to `main`
directly, and never ask anyone to bypass the gate. An agent's word that a change works counts for
nothing; the gate's verdict counts.

## Who approves what here

Almost everything in this repo is a **policy path** (`.github/CODEOWNERS`), and a policy path
needs the policy-owner (suraj):

| You changed | Class | Approval |
|---|---|---|
| `config/`, `schema/`, `tools/`, `generated/`, `tests/`, `.github/`, `AGENTS.md` | policy | policy-owner (suraj) |
| `README.md` only | docs | none; an agent may land it alone once the gate is green |
| `requirements.txt` pin bump only | dependency-roll | none, if opened by the roller rotation |
| a clean `git revert` of a landed PR | clean-revert | none |

You can never approve your own change. If one PR mixes classes, the strictest class applies. To
land docs quickly, keep them in their own PR.

## How to change config

1. Edit the TOML in `config/`. If you add a field, add it to that area's schema in `schema/` in
   the same PR. The schemas reject unknown keys on purpose.
2. Run `python3 tools/qqcfg.py generate` if anything that feeds `generated/` changed.
3. Run `python3 tools/qqcfg.py validate` and `python3 -m unittest discover -s tests`. Both must pass.
4. Open a PR that states which area changed, why, what reads it, and how to roll it back (normally
   by reverting the PR).

## Never

- Edit `generated/` by hand. Change `config/` and regenerate.
- Fill in `owners` or rotation `members`. suraj assigns people; leave the lists as they are.
- Loosen a policy invariant in `tools/qqcfg.py`, or remove a check, to make your change pass. If
  an invariant blocks you, say so in the PR; the policy-owner decides.
- Change a `stub` area to `seed` unless its values were actually decided. Say who decided in the PR.
- Put backend-specific settings at the top level of an area. They go in a sub-table named after
  the backend (`[pool.github]`) or behind a `backend` field, so a later move to Launchpad does not
  rewrite every area.
- Write a second parser for these files. Read them through `qqcfg.load` (and, later, the `sync`
  library).
- Commit secrets, tokens or personal data. This repo is public.

## Adding things

- **A repo:** add a `[[repo]]` block to `config/repos.toml` (public repos only, year-one kinds
  only). Give it a blocking presubmit builder, a post-submit builder and a canary release builder
  in `config/pipelines.toml`. Leave `owners = []`.
- **An area:** add `config/<area>.toml` with the `[area]` header and `schema/<area>.schema.json`,
  add the area to `REQUIRED_AREAS` in `tools/qqcfg.py`, and add a row to the README table.
- **A decision you cannot make:** leave a one-line `# TODO(suraj): ...` or `# TODO(expert): ...`
  that names the decision. `validate --todos` lists them. Do not start a long design in a comment.

## Before you open the PR

- [ ] `python3 tools/qqcfg.py validate` prints `PASS`.
- [ ] `python3 -m unittest discover -s tests` passes.
- [ ] `generated/` was regenerated, not hand-edited.
- [ ] No owners or members were filled in, and no invariant was loosened.
- [ ] Stubs are still marked `stub`, and any new TODO names its decision.
- [ ] The PR says what changed, why, and how to roll it back.
