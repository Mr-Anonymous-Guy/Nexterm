"""Test suite for the `nexterm check` manual pre-push Guardian command.

Covers:
    - Command registration and existence
    - Shell autocomplete registration
    - Help text availability
    - StageResult and PrePushReport model behavior for failure output
    - Pipeline definition consistency with pre-push engine
    - Report generation

NOTE: Full pipeline integration tests are NOT included in this file because
the pre-push Guardian's Stage 7 (Test Suite) runs pytest, which would discover
this test file and create infinite recursion. The full pipeline is verified
manually via `nexterm check` or `python -m nexterm.cli check`.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from click.testing import CliRunner
from nexterm.cli import main, check_cmd


class TestCheckCommandRegistration(unittest.TestCase):
    """Verify the check command is registered in the CLI."""

    def test_check_command_exists(self):
        """check must be a registered Click command."""
        self.assertIn("check", main.commands)

    def test_check_command_is_callable(self):
        """The check command function must be callable."""
        self.assertTrue(callable(check_cmd))

    def test_check_in_terminal_completions(self):
        """check must appear in DEVOS_TOP_COMMANDS for shell autocomplete."""
        from nexterm.terminal import DEVOS_TOP_COMMANDS
        self.assertIn("check", DEVOS_TOP_COMMANDS)

    def test_check_help_text(self):
        """check --help must show usage information."""
        runner = CliRunner()
        result = runner.invoke(main, ["check", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("pre-push", result.output.lower())
        self.assertIn("--verbose", result.output)

    def test_check_not_in_guardian_subcommands(self):
        """check must be a top-level command, not nested under guardian."""
        cmd = main.commands.get("check")
        self.assertIsNotNone(cmd, "check must be a top-level Click command")
        # Also verify guardian group still exists independently
        self.assertIn("guardian", main.commands)


class TestCheckCommandStageModels(unittest.TestCase):
    """Verify StageResult and PrePushReport models support the check command output logic."""

    def test_stage_result_fields_accessible(self):
        """StageResult must expose all fields needed for failure reporting."""
        from scripts.pre_push import StageResult

        failing = StageResult(
            stage_num=7,
            name="Test Suite",
            passed=False,
            skipped=False,
            duration=5.23,
            message="Test suite failed.",
            details=["FAILED tests/test_commands.py::TestFoo::test_bar"],
            remedy="Fix failing unit tests before pushing",
        )

        self.assertFalse(failing.passed)
        self.assertFalse(failing.skipped)
        self.assertEqual(failing.name, "Test Suite")
        self.assertEqual(failing.stage_num, 7)
        self.assertAlmostEqual(failing.duration, 5.23)
        self.assertIn("FAILED", failing.details[0])
        self.assertEqual(failing.remedy, "Fix failing unit tests before pushing")

    def test_skipped_stage_result(self):
        """Skipped stages must have correct flags."""
        from scripts.pre_push import StageResult

        skipped = StageResult(
            stage_num=8,
            name="GitHub Actions Parsing",
            passed=False,
            skipped=True,
            duration=0.0,
            message="Skipped due to earlier critical failure.",
        )

        self.assertFalse(skipped.passed)
        self.assertTrue(skipped.skipped)

    def test_pre_push_report_all_passed_with_passing_stages(self):
        """PrePushReport.all_passed must be True when all stages pass."""
        from scripts.pre_push import StageResult, PrePushReport

        stages = [
            StageResult(1, "A", True, False, 0.1, "ok"),
            StageResult(2, "B", True, False, 0.1, "ok"),
        ]
        report = PrePushReport("0.1.5", "main", "abc", stages=stages)
        self.assertTrue(report.all_passed)

    def test_pre_push_report_all_passed_with_failure(self):
        """PrePushReport.all_passed must be False when any stage fails."""
        from scripts.pre_push import StageResult, PrePushReport

        stages = [
            StageResult(1, "A", True, False, 0.1, "ok"),
            StageResult(2, "B", False, False, 0.1, "fail"),
        ]
        report = PrePushReport("0.1.5", "main", "abc", stages=stages)
        self.assertFalse(report.all_passed)

    def test_pre_push_report_all_passed_with_skips(self):
        """PrePushReport.all_passed must be True when non-passing stages are skipped."""
        from scripts.pre_push import StageResult, PrePushReport

        stages = [
            StageResult(1, "A", True, False, 0.1, "ok"),
            StageResult(2, "B", False, True, 0.0, "skip"),
        ]
        report = PrePushReport("0.1.5", "main", "abc", stages=stages)
        self.assertTrue(report.all_passed)


class TestCheckCommandPipelineDefinition(unittest.TestCase):
    """Verify the check command uses the same stage definitions as the pre-push engine."""

    def test_check_references_all_stage_methods(self):
        """The check command must reference all 15 stage methods from the engine."""
        import inspect
        source = inspect.getsource(check_cmd.callback)
        expected_stages = [
            "_stage1_repo_audit",
            "_stage2_dep_verification",
            "_stage3_formatting_check",
            "_stage4_linting_check",
            "_stage5_type_check",
            "_stage6_production_build",
            "_stage7_test_suite",
            "_stage8_workflow_parsing",
            "_stage9_workflow_simulation",
            "_stage10_matrix_validation",
            "_stage11_failure_investigation",
            "_stage12_auto_repair",
            "_stage13_security_secret_scan",
            "_stage14_artifact_inspection",
            "_stage15_git_validation",
        ]
        for stage_method in expected_stages:
            self.assertIn(stage_method, source, f"check command missing reference to {stage_method}")

    def test_check_defines_critical_stages(self):
        """The check command must define critical_stages containing the correct stage numbers."""
        import inspect
        source = inspect.getsource(check_cmd.callback)
        self.assertIn("critical_stages", source)
        # Verify all required critical stage numbers appear
        for stage_num in [1, 2, 4, 6, 7, 13]:
            self.assertIn(str(stage_num), source,
                          f"Critical stage {stage_num} not found in check command source")

    def test_check_imports_pre_push_engine(self):
        """The check command must import from scripts.pre_push."""
        import inspect
        source = inspect.getsource(check_cmd.callback)
        self.assertIn("PrePushValidationEngine", source)
        self.assertIn("StageResult", source)
        self.assertIn("PrePushReport", source)
        self.assertIn("write_markdown_report", source)

    def test_check_calls_stage16_final_decision(self):
        """The check command must call _stage16_final_decision."""
        import inspect
        source = inspect.getsource(check_cmd.callback)
        self.assertIn("_stage16_final_decision", source)

    def test_check_generates_report(self):
        """The check command must call write_markdown_report."""
        import inspect
        source = inspect.getsource(check_cmd.callback)
        self.assertIn("write_markdown_report", source)
        self.assertIn("pre_push_report.md", source)


class TestCheckCommandWriteReport(unittest.TestCase):
    """Verify the check command's report generation logic."""

    def test_write_markdown_report_creates_file(self):
        """write_markdown_report must create a valid markdown report."""
        from scripts.pre_push import StageResult, PrePushReport, write_markdown_report

        stages = [
            StageResult(1, "Repository Audit", True, False, 0.05, "ok"),
            StageResult(2, "Dep Verification", True, False, 1.0, "ok"),
            StageResult(16, "Final Decision & Report", True, False, 0.01, "All passed"),
        ]
        report = PrePushReport("0.1.5", "main", "abc1234", stages=stages)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "pre_push_report.md"
            write_markdown_report(report, out)
            self.assertTrue(out.exists())
            content = out.read_text(encoding="utf-8")
            self.assertIn("Pre-Push Validation System Report", content)
            self.assertIn("Repository Audit", content)
            self.assertIn("PASS", content)


if __name__ == "__main__":
    unittest.main()
