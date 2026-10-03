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
        for d in ("config", "schema", "generated"):
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


if __name__ == "__main__":
    unittest.main()
