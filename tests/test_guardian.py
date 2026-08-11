"""Test suite for DeveloperOS Pre-Push Guardian subsystem.

Covers:
    - Git hygiene checks
    - Changed files diff analysis
    - Secret scanning in diff and file content
    - Dependency validation
    - Git pre-push hook installation, status, and removal lifecycle
    - Guardian report formatting
    - Full guardian check pipeline
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nexterm import __version__
from nexterm.guardian import (
    GuardianEngine,
    GuardianReport,
    CheckResult,
    format_guardian_report_terminal,
)


class TestGuardianEngine(unittest.TestCase):
    """Unit tests for GuardianEngine subsystem."""

    def setUp(self):
        self.repo_root = Path(__file__).resolve().parent.parent
        self.engine = GuardianEngine(self.repo_root)

    def test_check_git_hygiene(self):
        check = self.engine.check_git_hygiene()
        self.assertTrue(check.passed)
        self.assertIn("hygiene valid", check.message)

    def test_analyze_changed_files(self):
        check, files = self.engine.analyze_changed_files()
        self.assertTrue(check.passed)
        self.assertIsInstance(files, list)

    def test_scan_secrets_clean(self):
        check = self.engine.scan_secrets(changed_files=["README.md", "pyproject.toml"])
        self.assertTrue(check.passed)
        self.assertIn("Zero secrets", check.message)

    def test_scan_secrets_detects_api_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_file = temp_path / "config.py"
            fake_file.write_text("API_KEY = 'sk-1234567890abcdef1234567890'\n", encoding="utf-8")
            
            temp_engine = GuardianEngine(temp_path)
            check = temp_engine.scan_secrets(["config.py"])
            self.assertFalse(check.passed)
            self.assertIn("Secret scan detected", check.message)

    def test_validate_dependencies(self):
        check = self.engine.validate_dependencies()
        self.assertTrue(check.passed)

    def test_git_hook_lifecycle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            (temp_path / ".git" / "hooks").mkdir(parents=True, exist_ok=True)

            temp_engine = GuardianEngine(temp_path)
            
            # 1. Check status before install
            self.assertFalse(temp_engine.check_hook_status())

            # 2. Install hook
            inst_check = temp_engine.install_git_hook()
            self.assertTrue(inst_check.passed)
            self.assertTrue(temp_engine.check_hook_status())

            # 3. Remove hook
            rm_check = temp_engine.remove_git_hook()
            self.assertTrue(rm_check.passed)
            self.assertFalse(temp_engine.check_hook_status())

    def test_full_guardian_check(self):
        report = self.engine.run_full_guardian_check()
        self.assertIsInstance(report, GuardianReport)
        self.assertEqual(report.version, __version__)
        self.assertTrue(len(report.checks) >= 4)

    def test_format_guardian_report_terminal(self):
        report = self.engine.run_full_guardian_check()
        output = format_guardian_report_terminal(report, use_color=False)
        self.assertIn("Pre-Push Guardian System", output)
        self.assertIn(__version__, output)
        self.assertNotIn("\033[", output)


if __name__ == "__main__":
    unittest.main()
