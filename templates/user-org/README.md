# User-org config templates

`qqcfg init --root DIR --owner OWNER` writes a user org's `DIR/config/` from these files, for the
one-command setup (README, "A user's own org"). Each is one area with every org-specific list empty;
`qqcfg add-repo` then adds repos and their builders. `kinds.toml` has no template: init copies this
checkout's `config/kinds.toml`, so toolchain pins move with quirq's rolls. The timing and sink pins
in `pipelines.toml` are filled from this checkout's `config/pipelines.toml` for the same reason.

Tokens: `@OWNER@` is the org (lower case), `@POLICY_OWNER@` the policy-owner's handle, and
`@TIMING@` and `@SINK@` the pins. The policy values must equal quirq's own config:
`tests/test_qqcfg.py` (`Init`) checks it, so a policy change to quirq's config updates these too.
