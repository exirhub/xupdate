"""Exercise the package bootstrap without running host APT or systemd."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]


class DependencyTests(unittest.TestCase):
    def run_bootstrap(self, failure):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apt = root / "apt-get"
            apt.write_text('''#!/usr/bin/env python3
import json
import os
import sys
with open(os.environ["XUPDATE_TEST_APT_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
failure = os.environ["XUPDATE_TEST_APT_FAILURE"]
if "update" in sys.argv and failure == "dns":
    print("Temporary failure resolving 'security.ubuntu.com'", file=sys.stderr)
    # APT can return success on a transient update failure without this option.
    sys.exit(100 if "--error-on=any" in sys.argv else 0)
if "install" in sys.argv and failure == "download":
    sys.exit(100)
''')
            apt.chmod(0o755)
            log = root / "calls.jsonl"
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ["PATH"],
                       XUPDATE_TEST_APT_LOG=str(log), XUPDATE_TEST_APT_FAILURE=failure)
            result = subprocess.run(
                ["bash", "-c", 'set -euo pipefail; source "$1"; xupdate_install_dependencies; '
                 'echo DEPENDENCIES_READY', "test", str(PROJECT / "scripts/install-dependencies.sh")],
                env=env, capture_output=True, text=True, timeout=10)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            return result, calls

    def test_dns_failure_stops_before_install_or_continuation(self):
        result, calls = self.run_bootstrap("dns")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("DEPENDENCIES_READY", result.stdout)
        self.assertIn("x-ui cleanup have not started", result.stderr)
        self.assertIn("fix the server's DNS", result.stderr)

    def test_success_allows_continuation_after_package_install(self):
        result, calls = self.run_bootstrap("")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 2)
        self.assertIn("update", calls[0])
        self.assertIn("install", calls[1])
        self.assertIn("nginx", calls[1])
        self.assertIn("DEPENDENCIES_READY", result.stdout)

    def test_package_download_failure_stops_continuation(self):
        result, calls = self.run_bootstrap("download")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 2)
        self.assertNotIn("DEPENDENCIES_READY", result.stdout)
        self.assertIn("has not started x-ui cleanup", result.stderr)


if __name__ == "__main__":
    unittest.main()
