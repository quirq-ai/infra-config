<!-- quirq infra postmortem template (config/postmortem.toml [policy] template).
     An agent drafts from captured evidence; an owner of the affected repo or area reviews.
     Blameless: describe systems and decisions, not people. Delete these comments when filing. -->

# Postmortem: <one line naming what failed>

**Trigger:** <postmortem.toml event, e.g. canary-deploy-failed>
**Repo or area:** <repo or config area>
**Status:** draft | in review | final
**Failure record:** <link to the tracked record>

## Summary

<Two or three sentences: what broke, who or what noticed, how long it lasted, what users saw.>

## Timeline (UTC)

| Time | Event | Evidence |
|---|---|---|
| | first bad commit landed | <commit link> |
| | first red run | <run link> |
| | detected | <run, alert or probe link> |
| | mitigated (revert, rollback or hold) | <PR or operation key> |
| | resolved | <commit or run link> |

## Impact

<What was held, rolled back or reverted; channels and users affected; time main was red.>

## Root cause

<The mechanism, with links. Inferred claims are marked as inferred.>

## Record needs

A failure record closes only when all three are linked (postmortem.toml `record_needs`).

- [ ] Culprit: <commit>
- [ ] Fix: <PR>
- [ ] Covering test: <test, fuzz target, corpus entry, gate or health signal that now catches this>

## Action items

Each action item links an issue (postmortem.toml `action_items_need_issue`).

- [ ] <action> (<issue link>)
