"""Test suite for 16-Stage Pre-Push Validation System, Hook Installer & Git Integration.

Covers:
    - PrePushValidationEngine 16 stage execution
    - pre_push_report.md generation
    - install_hooks.py installer CLI flags (--install, --uninstall, --status, --run)
    - Terminal UI dashboard formatting (PASS, FAIL, Bypass)
    - Remote/refspec hook arguments
    - Real Git push integration test (PASS & BLOCK)
"""
from __future__ import annotations

import os
import shutil
import subprocess
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
    """Unit tests for PrePushValidationEngine 16-stage pipeline & terminal UX."""

    _report = None

    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parent.parent
        cls.engine = PrePushValidationEngine(cls.repo_root)
        cls._report = cls.engine.run_full_pipeline()

    def test_full_pipeline_run(self):
        report = self._report
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
        report = self._report
        with tempfile.TemporaryDirectory() as temp_dir:
            out_file = Path(temp_dir) / "pre_push_report.md"
            write_markdown_report(report, out_file)
            self.assertTrue(out_file.exists())
            content = out_file.read_text(encoding="utf-8")
            self.assertIn("# DeveloperOS — Pre-Push Validation System Report", content)
            self.assertIn("16-Stage Pipeline Breakdown", content)

    def test_format_terminal_summary_passing(self):
        report = self._report
        output = format_terminal_summary(report)
        self.assertIn("NEXTERM PRE-PUSH GUARDIAN", output)
        self.assertIn("PUSH AUTHORIZED", output)
        self.assertIn("[01/16]", output)
        self.assertIn("✓ PASS", output)
        self.assertIn("Continuing git push...", output)

    def test_format_terminal_summary_failing(self):
        failing_stages = [
            StageResult(1, "Repository Audit", True, False, 0.1, "Pass"),
            StageResult(4, "Linting Check", False, False, 0.2, "AST syntax error", ["nexterm/bad.py:10 - SyntaxError"], "Fix Python syntax error"),
        ]
        report = PrePushReport("0.1.1", "main", "abc1234", stages=failing_stages)
        output = format_terminal_summary(report, report_path="pre_push_report.md")
        self.assertIn("PUSH BLOCKED", output)
        self.assertIn("Failed Stage:", output)
        self.assertIn("04 — Linting Check", output)
        self.assertIn("Problem:", output)
        self.assertIn("AST syntax error", output)
        self.assertIn("Suggested Remedy:", output)
        self.assertIn("Fix Python syntax error", output)
        self.assertIn("Git push has been cancelled.", output)

    def test_format_terminal_summary_bypass(self):
        report = PrePushReport("0.1.1", "main", "abc1234", bypassed=True)
        output = format_terminal_summary(report)
        self.assertIn("Guardian bypass active", output)
        self.assertIn("Pre-push validation was skipped", output)

    def test_remote_and_refspec_arguments(self):
        report = self.engine.run_full_pipeline(
            remote_name="origin",
            remote_url="https://github.com/user/NexTerm.git",
            ref_specs=["refs/heads/main 111 refs/heads/main 222"],
        )
        self.assertEqual(report.remote_name, "origin")
        self.assertEqual(report.remote_url, "https://github.com/user/NexTerm.git")
        self.assertEqual(report.ref_specs, ["refs/heads/main 111 refs/heads/main 222"])
        output = format_terminal_summary(report)
        self.assertIn("Remote     : origin (https://github.com/user/NexTerm.git)", output)

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


class TestRealGitPushIntegration(unittest.TestCase):
    """Real Git integration testing for pre-push hook (PASS & BLOCK)."""

    def setUp(self):
        self.repo_root = Path(__file__).resolve().parent.parent

    def test_real_git_push_pass_and_block_flow(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bare_remote = temp_path / "remote.git"
            local_repo = temp_path / "local"

            # 1. Initialize bare remote git repository
            subprocess.run(["git", "init", "--bare", str(bare_remote)], check=True, capture_output=True)

            # 2. Initialize local git repository
            subprocess.run(["git", "init", "-b", "main", str(local_repo)], check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=local_repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=local_repo, check=True, capture_output=True)
            subprocess.run(["git", "remote", "add", "origin", str(bare_remote)], cwd=local_repo, check=True, capture_output=True)

            # Copy essential codebase files into local_repo fixture
            for item in ["pyproject.toml", "README.md", "LICENSE", ".github", "nexterm", "scripts", "tests", ".githooks"]:
                src = self.repo_root / item
                dst = local_repo / item
                if src.is_dir():
                    shutil.copytree(src, dst)
                elif src.is_file():
                    shutil.copy2(src, dst)

            # Install NexTerm pre-push hook into local_repo fixture
            self.assertTrue(install_hook(local_repo))

            # 3. Create initial clean commit & test PASSing git push
            subprocess.run(["git", "add", "."], cwd=local_repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial clean commit"], cwd=local_repo, check=True, capture_output=True)

            res_push_pass = subprocess.run(["git", "push", "origin", "main"], cwd=local_repo, capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(res_push_pass.returncode, 0, msg=f"Git push failed: {res_push_pass.stderr}\n{res_push_pass.stdout}")
            self.assertIn("PUSH AUTHORIZED", res_push_pass.stdout + res_push_pass.stderr)

            # 4. Inject syntax error & test BLOCKed git push
            broken_file = local_repo / "nexterm" / "broken_syntax.py"
            broken_file.write_text("def invalid_syntax_error(\n", encoding="utf-8")

            subprocess.run(["git", "add", "."], cwd=local_repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Commit with syntax error"], cwd=local_repo, check=True, capture_output=True)

            res_push_block = subprocess.run(["git", "push", "origin", "main"], cwd=local_repo, capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertNotEqual(res_push_block.returncode, 0, msg="Git push should have been blocked by Guardian gate!")
            output_text = res_push_block.stdout + res_push_block.stderr
            self.assertIn("PUSH BLOCKED", output_text)
            self.assertIn("Linting Check", output_text)


if __name__ == "__main__":
    unittest.main()
