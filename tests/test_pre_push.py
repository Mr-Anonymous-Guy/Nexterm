"""Test suite for 16-Stage Pre-Push Validation System & Hook Installer.

Covers:
    - PrePushValidationEngine 16 stage execution
    - pre_push_report.md generation
    - install_hooks.py installer CLI flags (--install, --uninstall, --status, --run)
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.pre_push import (
    PrePushValidationEngine,
    PrePushReport,
    StageResult,
    write_markdown_report,
    format_terminal_summary,
)
from scripts.install_hooks import install_hook, uninstall_hook, check_status


class TestPrePushEngine(unittest.TestCase):
    """Unit tests for PrePushValidationEngine 16-stage pipeline."""

    def setUp(self):
        self.repo_root = Path(__file__).resolve().parent.parent
        self.engine = PrePushValidationEngine(self.repo_root)

    def test_full_pipeline_run(self):
        report = self.engine.run_full_pipeline()
        self.assertIsInstance(report, PrePushReport)
        self.assertTrue(len(report.stages) == 16)
        self.assertTrue(report.all_passed)

        # Check individual stage names
        stage_names = [s.name for s in report.stages]
        self.assertIn("Repository Audit", stage_names)
        self.assertIn("Dependency Verification", stage_names)
        self.assertIn("Formatting Check", stage_names)
        self.assertIn("Linting Check", stage_names)
        self.assertIn("Type Check & Static Analysis", stage_names)
        self.assertIn("Production Build", stage_names)
        self.assertIn("Test Suite", stage_names)
        self.assertIn("GitHub Actions Parsing", stage_names)
        self.assertIn("Workflow Simulation", stage_names)
        self.assertIn("Matrix Validation", stage_names)
        self.assertIn("Failure Investigation", stage_names)
        self.assertIn("Auto-Repair Engine", stage_names)
        self.assertIn("Security & Secret Scan", stage_names)
        self.assertIn("Artifact Inspection", stage_names)
        self.assertIn("Git Conflict & Hygiene", stage_names)
        self.assertIn("Final Decision & Report", stage_names)

    def test_write_markdown_report(self):
        report = self.engine.run_full_pipeline()
        with tempfile.TemporaryDirectory() as temp_dir:
            out_file = Path(temp_dir) / "pre_push_report.md"
            write_markdown_report(report, out_file)
            self.assertTrue(out_file.exists())
            content = out_file.read_text(encoding="utf-8")
            self.assertIn("# DeveloperOS — Pre-Push Validation System Report", content)
            self.assertIn("16-Stage Pipeline Breakdown", content)

    def test_format_terminal_summary(self):
        report = self.engine.run_full_pipeline()
        output = format_terminal_summary(report)
        self.assertIn("Pre-Push Gate", output)
        self.assertIn("Repository Audit", output)

    def test_hook_installer_lifecycle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            (temp_path / ".git" / "hooks").mkdir(parents=True, exist_ok=True)
            (temp_path / ".githooks").mkdir(parents=True, exist_ok=True)
            (temp_path / ".githooks" / "pre-push").write_text("#!/bin/sh\necho test", encoding="utf-8")

            # Check status before install
            self.assertFalse(check_status(temp_path))

            # Install hook
            self.assertTrue(install_hook(temp_path))
            self.assertTrue(check_status(temp_path))

            # Uninstall hook
            self.assertTrue(uninstall_hook(temp_path))
            self.assertFalse(check_status(temp_path))


if __name__ == "__main__":
    unittest.main()
