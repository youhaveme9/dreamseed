import os
import tempfile
import unittest
from pathlib import Path

from dreamseed_mcp.doctor import run_checks


ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(os.environ.get("DREAMSEED_BINARY", str(ROOT / "build" / "dreamseed")))


class DoctorTests(unittest.TestCase):
    def test_release_environment_is_ready(self):
        with tempfile.TemporaryDirectory() as state_dir:
            report = run_checks(BINARY, Path(state_dir))
        self.assertTrue(report["ok"], report)
        self.assertTrue(all(check["ok"] for check in report["checks"]))

    def test_missing_binary_is_reported(self):
        with tempfile.TemporaryDirectory() as state_dir:
            report = run_checks(Path(state_dir) / "missing", Path(state_dir) / "jobs")
        self.assertFalse(report["ok"])
        native = next(check for check in report["checks"] if check["name"] == "native_engine")
        self.assertFalse(native["ok"])


if __name__ == "__main__":
    unittest.main()
