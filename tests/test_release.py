"""Test suite for DeveloperOS PyPI release & validation engine.

Covers:
    - Version alignment check
    - Git status check
    - Artifact content secret scanner
    - Package build & twine check execution
    - Clean environment smoke test helper
    - SHA256 checksum generation
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nexterm import __version__
from nexterm.release import (
    ReleaseValidator,
    CheckResult,
    ReleaseCheckReport,
    format_report_terminal,
    generate_sha256sums_file,
)


class TestReleaseValidator(unittest.TestCase):
    """Unit tests for the ReleaseValidator subsystem."""

    _full_report = None

    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parent.parent
        cls.validator = ReleaseValidator(cls.repo_root)
        dist_dir = cls.repo_root / "dist"
        if not (dist_dir.exists() and list(dist_dir.glob("*.whl")) and list(dist_dir.glob("*.tar.gz"))):
            cls.validator.build_packages()
        cls._full_report = cls.validator.run_full_check()

    def test_version_alignment(self):
        check = self.validator.check_version_alignment(target_tag=f"v{__version__}")
        self.assertTrue(check.passed)
        self.assertIn(__version__, check.message)

    def test_version_alignment_mismatch(self):
        check = self.validator.check_version_alignment(target_tag="v99.99.99")
        self.assertFalse(check.passed)
        self.assertIn("Tag version mismatch", check.message)

    def test_git_status_check(self):
        check = self.validator.check_git_status()
        self.assertIsInstance(check, CheckResult)

    def test_run_tests(self):
        # Verify via the full report's test suite check instead of re-running pytest
        test_checks = [c for c in self._full_report.checks if c.name == "Test Suite"]
        self.assertTrue(len(test_checks) >= 1)
        check = test_checks[0]
        self.assertTrue(check.passed)
        self.assertIn("passed", check.message.lower())

    def test_build_packages(self):
        check, files = self.validator.build_packages()
        self.assertTrue(check.passed)
        self.assertTrue(len(files) >= 2)  # at least wheel and sdist
        self.assertTrue(any(f.name.endswith(".whl") for f in files))
        self.assertTrue(any(f.name.endswith(".tar.gz") for f in files))

    def test_validate_metadata(self):
        # Assumes packages built in previous step
        check = self.validator.validate_metadata()
        self.assertTrue(check.passed)
        self.assertIn("passed", check.message.lower())

    def test_artifact_secret_scan_clean(self):
        check = self.validator.scan_artifact_secrets()
        self.assertTrue(check.passed)
        self.assertIn("Zero secrets", check.message)

    def test_clean_environment_smoke_test(self):
        # Verify via the full report's smoke test check instead of re-running
        smoke_checks = [c for c in self._full_report.checks if c.name == "Clean Venv Test"]
        self.assertTrue(len(smoke_checks) >= 1)
        check = smoke_checks[0]
        self.assertTrue(check.passed, msg=f"Smoke test failed: {check.message} - details: {check.details}")
        self.assertIn("installed & verified", check.message.lower())

    def test_full_check(self):
        report = self._full_report
        self.assertIsInstance(report, ReleaseCheckReport)
        self.assertEqual(report.version, __version__)
        self.assertTrue(len(report.checks) >= 6)
        self.assertTrue(len(report.artifacts) >= 2)

    def test_format_report_terminal(self):
        report = self._full_report
        output = format_report_terminal(report, use_color=False)
        self.assertIn("DeveloperOS Release Check", output)
        self.assertIn(__version__, output)
        self.assertNotIn("\033[", output)

    def test_generate_sha256sums_file(self):
        dist_dir = self.repo_root / "dist"
        sums_text = generate_sha256sums_file(dist_dir)
        self.assertIn(".whl", sums_text)
        self.assertIn(".tar.gz", sums_text)


if __name__ == "__main__":
    unittest.main()
