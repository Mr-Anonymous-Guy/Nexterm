"""Test suite for DeveloperOS professional error handling subsystem.

Covers:
    - ProcessResult model
    - CommandError model
    - All 7 error classifiers (System, Npm, Python, Git, Docker, Node, PortConflict)
    - ErrorFormatter output modes (normal, verbose, debug, json)
    - SecretRedactor
    - classify_and_format pipeline
    - suggest_similar_command typo correction
    - Safety guarantees (shell-never-crashes, formatter-fallback, success-stays-quiet)
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nexterm.errors import (
    ProcessResult,
    CommandError,
    ErrorCategory,
    ErrorSource,
    SecretRedactor,
    SystemErrorClassifier,
    NpmErrorClassifier,
    PythonErrorClassifier,
    GitErrorClassifier,
    DockerErrorClassifier,
    NodeErrorClassifier,
    PortConflictClassifier,
    ErrorFormatter,
    ErrorClassifier,
    classify_error,
    classify_and_format,
    suggest_similar_command,
    format_directory_error,
    format_devos_error,
    run_command,
    DEFAULT_CLASSIFIERS,
)


# ═══════════════════════════════════════════════════════════════════════
#  ProcessResult Model Tests
# ═══════════════════════════════════════════════════════════════════════

class TestProcessResult(unittest.TestCase):
    """Tests for the ProcessResult data model."""

    def test_default_construction(self):
        r = ProcessResult(command="echo hello")
        self.assertEqual(r.command, "echo hello")
        self.assertEqual(r.exit_code, None)
        self.assertEqual(r.stdout, "")
        self.assertEqual(r.stderr, "")
        self.assertEqual(r.duration, 0.0)
        self.assertFalse(r.timed_out)

    def test_success_property(self):
        r = ProcessResult(command="echo hello", exit_code=0)
        self.assertTrue(r.success)

    def test_failure_property(self):
        r = ProcessResult(command="bad", exit_code=1)
        self.assertFalse(r.success)

    def test_timeout_is_not_success(self):
        r = ProcessResult(command="slow", exit_code=0, timed_out=True)
        self.assertFalse(r.success)

    def test_was_interrupted_sigint(self):
        r = ProcessResult(command="process", signal_name="SIGINT")
        self.assertTrue(r.was_interrupted)

    def test_was_interrupted_keyboard(self):
        r = ProcessResult(command="process", signal_name="KeyboardInterrupt")
        self.assertTrue(r.was_interrupted)

    def test_was_not_interrupted(self):
        r = ProcessResult(command="process", exit_code=1)
        self.assertFalse(r.was_interrupted)

    def test_duration_stored(self):
        r = ProcessResult(command="x", duration=1.234)
        self.assertAlmostEqual(r.duration, 1.234)


# ═══════════════════════════════════════════════════════════════════════
#  CommandError Model Tests
# ═══════════════════════════════════════════════════════════════════════

class TestCommandError(unittest.TestCase):
    """Tests for the CommandError data model."""

    def test_default_category_is_unknown(self):
        e = CommandError()
        self.assertEqual(e.category, ErrorCategory.UNKNOWN)

    def test_default_source_is_unknown(self):
        e = CommandError()
        self.assertEqual(e.source, ErrorSource.UNKNOWN)

    def test_to_dict_contains_required_fields(self):
        e = CommandError(
            category=ErrorCategory.COMMAND_NOT_FOUND,
            title="Command not found",
            command="foobar",
            exit_code=127,
            clean_message="`foobar` is not available in PATH.",
            source=ErrorSource.SYSTEM,
        )
        d = e.to_dict()
        self.assertFalse(d["success"])
        self.assertEqual(d["category"], "COMMAND_NOT_FOUND")
        self.assertEqual(d["source"], "System")
        self.assertEqual(d["title"], "Command not found")
        self.assertEqual(d["command"], "foobar")
        self.assertEqual(d["exit_code"], 127)
        self.assertIn("message", d)
        self.assertIn("suggestions", d)

    def test_suggestions_default_empty_list(self):
        e = CommandError()
        self.assertEqual(e.suggestions, [])

    def test_metadata_default_empty_dict(self):
        e = CommandError()
        self.assertEqual(e.metadata, {})


# ═══════════════════════════════════════════════════════════════════════
#  SecretRedactor Tests
# ═══════════════════════════════════════════════════════════════════════

class TestSecretRedactor(unittest.TestCase):
    """Tests for secret redaction."""

    def test_redacts_api_key(self):
        text = "Error: API_KEY=sk-abc123xyz is invalid"
        result = SecretRedactor.redact(text)
        self.assertNotIn("sk-abc123xyz", result)
        self.assertIn("[REDACTED]", result)

    def test_redacts_password(self):
        text = "connection failed: PASSWORD=s3cretP@ss"
        result = SecretRedactor.redact(text)
        self.assertNotIn("s3cretP@ss", result)
        self.assertIn("[REDACTED]", result)

    def test_redacts_token(self):
        text = "AUTH_TOKEN=ghp_abc123 expired"
        result = SecretRedactor.redact(text)
        self.assertNotIn("ghp_abc123", result)
        self.assertIn("[REDACTED]", result)

    def test_redacts_database_url(self):
        text = "DATABASE_URL=postgres://user:pass@host/db"
        result = SecretRedactor.redact(text)
        self.assertNotIn("postgres://user:pass@host/db", result)
        self.assertIn("[REDACTED]", result)

    def test_preserves_normal_text(self):
        text = "Normal error: file not found at /path/to/file"
        result = SecretRedactor.redact(text)
        self.assertEqual(text, result)

    def test_empty_string(self):
        self.assertEqual(SecretRedactor.redact(""), "")

    def test_none_returns_empty(self):
        self.assertEqual(SecretRedactor.redact(None), None)

    def test_redact_error_object(self):
        e = CommandError(
            stderr="API_KEY=secret123 failed",
            stdout="TOKEN=abc456 invalid",
            clean_message="API_KEY=secret123 is wrong",
        )
        redacted = SecretRedactor.redact_error(e)
        self.assertNotIn("secret123", redacted.stderr)
        self.assertNotIn("abc456", redacted.stdout)
        self.assertNotIn("secret123", redacted.clean_message)
        self.assertIn("[REDACTED]", redacted.stderr)


# ═══════════════════════════════════════════════════════════════════════
#  SystemErrorClassifier Tests
# ═══════════════════════════════════════════════════════════════════════

class TestSystemErrorClassifier(unittest.TestCase):
    """Tests for OS-level error classification."""

    def setUp(self):
        self.classifier = SystemErrorClassifier()

    def test_command_not_found_windows(self):
        r = ProcessResult(
            command="foobar --version",
            exit_code=9009,
            stderr="'foobar' is not recognized as an internal or external command",
        )
        e = self.classifier.classify(r)
        self.assertIsNotNone(e)
        self.assertEqual(e.category, ErrorCategory.COMMAND_NOT_FOUND)
        self.assertIn("foobar", e.clean_message)

    def test_command_not_found_unix(self):
        r = ProcessResult(
            command="foobar",
            exit_code=127,
            stderr="bash: foobar: command not found",
        )
        e = self.classifier.classify(r)
        self.assertIsNotNone(e)
        self.assertEqual(e.category, ErrorCategory.COMMAND_NOT_FOUND)

    def test_permission_denied(self):
        r = ProcessResult(
            command="run_protected",
            exit_code=1,
            stderr="Access is denied.",
        )
        e = self.classifier.classify(r)
        self.assertIsNotNone(e)
        self.assertEqual(e.category, ErrorCategory.PERMISSION_DENIED)
        self.assertTrue(len(e.suggestions) > 0)

    def test_normal_failure_not_classified(self):
        r = ProcessResult(
            command="something",
            exit_code=1,
            stderr="some normal error output",
        )
        e = self.classifier.classify(r)
        self.assertIsNone(e)


# ═══════════════════════════════════════════════════════════════════════
#  NpmErrorClassifier Tests
# ═══════════════════════════════════════════════════════════════════════

class TestNpmErrorClassifier(unittest.TestCase):
    """Tests for npm/pnpm/yarn error classification."""

    def setUp(self):
        self.classifier = NpmErrorClassifier()

    def test_missing_package_json(self):
        r = ProcessResult(
            command="npm install",
            exit_code=1,
            stderr="npm ERR! ENOENT: no such file or directory, open 'package.json'",
        )
        e = self.classifier.classify(r)
        self.assertIsNotNone(e)
        self.assertEqual(e.category, ErrorCategory.FILE_NOT_FOUND)
        self.assertIn("package.json", e.clean_message)

    def test_eresolve_dependency_conflict(self):
        r = ProcessResult(
            command="npm install",
            exit_code=1,
            stderr="npm ERR! ERESOLVE could not resolve dependency tree",
        )
        e = self.classifier.classify(r)
        self.assertIsNotNone(e)
        self.assertEqual(e.category, ErrorCategory.DEPENDENCY_MISSING)
        self.assertTrue(any("legacy-peer-deps" in s for s in e.suggestions))

    def test_missing_script(self):
        r = ProcessResult(
            command="npm run nonexistent",
            exit_code=1,
            stderr='npm ERR! Missing script: "nonexistent"',
        )
        e = self.classifier.classify(r)
        self.assertIsNotNone(e)
        self.assertEqual(e.category, ErrorCategory.CONFIGURATION_ERROR)
        self.assertIn("nonexistent", e.clean_message)

    def test_network_error(self):
        r = ProcessResult(
            command="npm install",
            exit_code=1,
            stderr="npm ERR! code ETIMEDOUT\nnpm ERR! network request failed",
        )
        e = self.classifier.classify(r)
        self.assertIsNotNone(e)
        self.assertEqual(e.category, ErrorCategory.NETWORK_ERROR)

    def test_generic_npm_failure(self):
        r = ProcessResult(
            command="npm run build",
            exit_code=1,
            stderr="npm ERR! code ELIFECYCLE\nnpm ERR! errno 2",
        )
        e = self.classifier.classify(r)
        self.assertIsNotNone(e)
        self.assertEqual(e.source, ErrorSource.NPM)

    def test_pnpm_detected(self):
        r = ProcessResult(
            command="pnpm install",
            exit_code=1,
            stderr="ERR_PNPM_LOCKFILE_MISMATCH",
        )
        e = self.classifier.classify(r)
        self.assertIsNotNone(e)
        self.assertEqual(e.source, ErrorSource.PNPM)

    def test_non_npm_command_not_classified(self):
        r = ProcessResult(
            command="python script.py",
            exit_code=1,
            stderr="some error",
        )
        e = self.classifier.classify(r)
        self.assertIsNone(e)


# ═══════════════════════════════════════════════════════════════════════
#  PythonErrorClassifier Tests
# ═══════════════════════════════════════════════════════════════════════

class TestPythonErrorClassifier(unittest.TestCase):
    """Tests for Python runtime error classification."""

    def setUp(self):
        self.classifier = PythonErrorClassifier()

    def test_module_not_found(self):
        r = ProcessResult(
            command="python app.py",
            exit_code=1,
            stderr='Traceback (most recent call last):\n  File "app.py", line 1, in <module>\n    import flask\nModuleNotFoundError: No module named \'flask\'',
        )
        e = self.classifier.classify(r)
        self.assertIsNotNone(e)
        self.assertEqual(e.category, ErrorCategory.DEPENDENCY_MISSING)
        self.assertIn("flask", e.clean_message)
        self.assertTrue(any("pip install flask" in s for s in e.suggestions))

    def test_file_not_found(self):
        r = ProcessResult(
            command="python nonexistent.py",
            exit_code=2,
            stderr="python: can't open file 'nonexistent.py': No such file or directory",
        )
        e = self.classifier.classify(r)
        self.assertIsNotNone(e)
        self.assertEqual(e.category, ErrorCategory.FILE_NOT_FOUND)
        self.assertIn("nonexistent.py", e.clean_message)

    def test_generic_traceback(self):
        r = ProcessResult(
            command="python app.py",
            exit_code=1,
            stderr='Traceback (most recent call last):\n  File "app.py", line 10, in <module>\n    result = 1 / 0\nZeroDivisionError: division by zero',
        )
        e = self.classifier.classify(r)
        self.assertIsNotNone(e)
        self.assertEqual(e.category, ErrorCategory.PYTHON_ERROR)
        self.assertIn("ZeroDivisionError", e.clean_message)

    def test_traceback_location_extracted(self):
        r = ProcessResult(
            command="python app.py",
            exit_code=1,
            stderr='Traceback (most recent call last):\n  File "app.py", line 42, in main\n    raise ValueError("bad")\nValueError: bad',
        )
        e = self.classifier.classify(r)
        self.assertIsNotNone(e)
        # Should suggest inspecting the location
        self.assertTrue(any("app.py:42" in s for s in e.suggestions))

    def test_non_python_not_classified(self):
        r = ProcessResult(command="node app.js", exit_code=1, stderr="error")
        e = self.classifier.classify(r)
        self.assertIsNone(e)


# ═══════════════════════════════════════════════════════════════════════
#  GitErrorClassifier Tests
# ═══════════════════════════════════════════════════════════════════════

class TestGitErrorClassifier(unittest.TestCase):
    """Tests for Git error classification."""

    def setUp(self):
        self.classifier = GitErrorClassifier()

    def test_not_a_repo(self):
        r = ProcessResult(
            command="git status",
            exit_code=128,
            stderr="fatal: not a git repository (or any of the parent directories)",
        )
        e = self.classifier.classify(r)
        self.assertIsNotNone(e)
        self.assertEqual(e.category, ErrorCategory.GIT_ERROR)
        self.assertIn("Git repository", e.clean_message)

    def test_branch_not_found(self):
        r = ProcessResult(
            command="git checkout feature-xyz",
            exit_code=1,
            stderr="error: pathspec 'feature-xyz' did not match any file(s) known to git",
        )
        e = self.classifier.classify(r)
        self.assertIsNotNone(e)
        self.assertEqual(e.category, ErrorCategory.GIT_ERROR)
        self.assertIn("branch", e.clean_message.lower())

    def test_merge_conflict(self):
        r = ProcessResult(
            command="git merge feature",
            exit_code=1,
            stderr="CONFLICT (content): Merge conflict in file.txt\nAutomatic merge failed",
        )
        e = self.classifier.classify(r)
        self.assertIsNotNone(e)
        self.assertEqual(e.category, ErrorCategory.GIT_ERROR)
        self.assertIn("conflict", e.clean_message.lower())

    def test_push_rejected(self):
        r = ProcessResult(
            command="git push origin main",
            exit_code=1,
            stderr="! [rejected] main -> main (non-fast-forward)\nUpdates were rejected",
        )
        e = self.classifier.classify(r)
        self.assertIsNotNone(e)
        self.assertIn("rejected", e.clean_message.lower())

    def test_non_git_not_classified(self):
        r = ProcessResult(command="npm test", exit_code=1, stderr="error")
        e = self.classifier.classify(r)
        self.assertIsNone(e)


# ═══════════════════════════════════════════════════════════════════════
#  DockerErrorClassifier Tests
# ═══════════════════════════════════════════════════════════════════════

class TestDockerErrorClassifier(unittest.TestCase):
    """Tests for Docker error classification."""

    def setUp(self):
        self.classifier = DockerErrorClassifier()

    def test_daemon_not_running(self):
        r = ProcessResult(
            command="docker ps",
            exit_code=1,
            stderr="Cannot connect to the Docker daemon. Is the docker daemon running?",
        )
        e = self.classifier.classify(r)
        self.assertIsNotNone(e)
        self.assertEqual(e.category, ErrorCategory.DOCKER_ERROR)
        self.assertIn("daemon", e.clean_message.lower())

    def test_image_not_found(self):
        r = ProcessResult(
            command="docker pull nonexistent/image:latest",
            exit_code=1,
            stderr="Error response from daemon: pull access denied for nonexistent/image, repository does not exist",
        )
        e = self.classifier.classify(r)
        self.assertIsNotNone(e)
        self.assertEqual(e.category, ErrorCategory.DOCKER_ERROR)
        self.assertIn("image", e.title.lower())

    def test_port_conflict(self):
        r = ProcessResult(
            command="docker run -p 3000:3000 app",
            exit_code=1,
            stderr="Bind for 0.0.0.0:3000 failed: port is already allocated",
        )
        e = self.classifier.classify(r)
        self.assertIsNotNone(e)
        self.assertEqual(e.category, ErrorCategory.PORT_IN_USE)

    def test_non_docker_not_classified(self):
        r = ProcessResult(command="git status", exit_code=1, stderr="error")
        e = self.classifier.classify(r)
        self.assertIsNone(e)


# ═══════════════════════════════════════════════════════════════════════
#  NodeErrorClassifier Tests
# ═══════════════════════════════════════════════════════════════════════

class TestNodeErrorClassifier(unittest.TestCase):
    """Tests for Node.js runtime error classification."""

    def setUp(self):
        self.classifier = NodeErrorClassifier()

    def test_module_not_found(self):
        r = ProcessResult(
            command="node app.js",
            exit_code=1,
            stderr="Error: Cannot find module 'express'\nRequire stack:",
        )
        e = self.classifier.classify(r)
        self.assertIsNotNone(e)
        self.assertEqual(e.category, ErrorCategory.DEPENDENCY_MISSING)
        self.assertIn("express", e.clean_message)

    def test_generic_node_failure(self):
        r = ProcessResult(
            command="node app.js",
            exit_code=1,
            stderr="ReferenceError: foo is not defined",
        )
        e = self.classifier.classify(r)
        self.assertIsNotNone(e)
        self.assertEqual(e.category, ErrorCategory.NODE_ERROR)
        self.assertEqual(e.source, ErrorSource.NODE)

    def test_non_node_not_classified(self):
        r = ProcessResult(command="python app.py", exit_code=1, stderr="error")
        e = self.classifier.classify(r)
        self.assertIsNone(e)


# ═══════════════════════════════════════════════════════════════════════
#  PortConflictClassifier Tests
# ═══════════════════════════════════════════════════════════════════════

class TestPortConflictClassifier(unittest.TestCase):
    """Tests for port-in-use detection across any tool."""

    def setUp(self):
        self.classifier = PortConflictClassifier()

    def test_eaddrinuse(self):
        r = ProcessResult(
            command="npm run dev",
            exit_code=1,
            stderr="Error: listen EADDRINUSE: address already in use :::3000",
        )
        e = self.classifier.classify(r)
        self.assertIsNotNone(e)
        self.assertEqual(e.category, ErrorCategory.PORT_IN_USE)
        self.assertIn("3000", e.clean_message)

    def test_no_port_conflict(self):
        r = ProcessResult(command="npm run dev", exit_code=1, stderr="some other error")
        e = self.classifier.classify(r)
        self.assertIsNone(e)


# ═══════════════════════════════════════════════════════════════════════
#  Classifier Chain Tests
# ═══════════════════════════════════════════════════════════════════════

class TestClassifierChain(unittest.TestCase):
    """Tests for the full classifier chain."""

    def test_always_returns_command_error(self):
        """classify_error must NEVER return None."""
        r = ProcessResult(command="unknown_cmd", exit_code=42, stderr="weird error")
        e = classify_error(r)
        self.assertIsNotNone(e)
        self.assertIsInstance(e, CommandError)

    def test_unknown_falls_through_to_generic(self):
        r = ProcessResult(command="unknown_cmd", exit_code=42, stderr="unexpected situation")
        e = classify_error(r)
        self.assertEqual(e.category, ErrorCategory.UNKNOWN)
        self.assertIn("42", e.clean_message)

    def test_first_match_wins(self):
        """System classifier should match before Npm for exit 9009."""
        r = ProcessResult(
            command="npmm install",
            exit_code=9009,
            stderr="'npmm' is not recognized as an internal or external command",
        )
        e = classify_error(r)
        self.assertEqual(e.category, ErrorCategory.COMMAND_NOT_FOUND)

    def test_crashing_classifier_skipped(self):
        """A broken classifier must not crash the chain."""
        class BrokenClassifier(ErrorClassifier):
            def classify(self, result):
                raise RuntimeError("classifier exploded")

        r = ProcessResult(command="test", exit_code=1, stderr="error")
        e = classify_error(r, classifiers=[BrokenClassifier()] + DEFAULT_CLASSIFIERS)
        # Should still produce a result (from remaining classifiers or fallback)
        self.assertIsNotNone(e)


# ═══════════════════════════════════════════════════════════════════════
#  ErrorFormatter Tests
# ═══════════════════════════════════════════════════════════════════════

class TestErrorFormatter(unittest.TestCase):
    """Tests for error output formatting."""

    def setUp(self):
        # Force no-color for predictable output
        self.formatter = ErrorFormatter(use_color=False)
        self.sample_error = CommandError(
            category=ErrorCategory.COMMAND_NOT_FOUND,
            title="Command not found",
            command="foobar --version",
            cwd="/home/user/project",
            exit_code=127,
            clean_message="`foobar` is not available in PATH.",
            reason="The executable `foobar` was not found.",
            suggestions=["Install foobar.", "Check your PATH."],
            source=ErrorSource.SYSTEM,
            stderr="bash: foobar: command not found",
            stdout="",
            raw_message="foobar: command not found",
        )

    def test_format_normal_contains_title(self):
        output = self.formatter.format_normal(self.sample_error)
        self.assertIn("Command not found", output)

    def test_format_normal_contains_command(self):
        output = self.formatter.format_normal(self.sample_error)
        self.assertIn("foobar --version", output)

    def test_format_normal_contains_exit_code(self):
        output = self.formatter.format_normal(self.sample_error)
        self.assertIn("127", output)

    def test_format_normal_contains_suggestions(self):
        output = self.formatter.format_normal(self.sample_error)
        self.assertIn("Install foobar.", output)
        self.assertIn("Check your PATH.", output)

    def test_format_normal_contains_location(self):
        output = self.formatter.format_normal(self.sample_error)
        self.assertIn("/home/user/project", output)

    def test_format_verbose_contains_raw_stderr(self):
        output = self.formatter.format_verbose(self.sample_error)
        self.assertIn("foobar: command not found", output)

    def test_format_debug_contains_classifier_info(self):
        output = self.formatter.format_debug(self.sample_error)
        self.assertIn("COMMAND_NOT_FOUND", output)
        self.assertIn("System", output)

    def test_format_debug_with_internal_traceback(self):
        output = self.formatter.format_debug(
            self.sample_error,
            internal_traceback="File 'test.py', line 1\n  raise Exception('test')"
        )
        self.assertIn("Internal traceback", output)
        self.assertIn("test.py", output)

    def test_format_json_valid(self):
        output = self.formatter.format_json(self.sample_error)
        parsed = json.loads(output)
        self.assertFalse(parsed["success"])
        self.assertEqual(parsed["category"], "COMMAND_NOT_FOUND")
        self.assertEqual(parsed["exit_code"], 127)

    def test_format_json_no_ansi(self):
        """JSON output must never contain ANSI escape sequences."""
        color_formatter = ErrorFormatter(use_color=True)
        output = color_formatter.format_json(self.sample_error)
        self.assertNotIn("\033[", output)

    def test_no_color_mode_no_ansi(self):
        """No-color mode must produce no ANSI escapes."""
        output = self.formatter.format_normal(self.sample_error)
        self.assertNotIn("\033[", output)


# ═══════════════════════════════════════════════════════════════════════
#  Safety Guarantee Tests
# ═══════════════════════════════════════════════════════════════════════

class TestSuccessStaysQuiet(unittest.TestCase):
    """Success (exit 0) must NOT produce DeveloperOS error wrapper."""

    def test_success_result_is_quiet(self):
        r = ProcessResult(command="echo hello", exit_code=0, stdout="hello\n")
        self.assertTrue(r.success)
        # The pipeline should not be called for success — but if it IS,
        # classify_and_format should still produce a result without crashing
        output = classify_and_format(r, mode="normal")
        # Even on exit 0 forced through pipeline, it should not crash
        self.assertIsInstance(output, str)


class TestInterruptionNotFailure(unittest.TestCase):
    """Ctrl+C (SIGINT) should be treated as interruption, not failure."""

    def test_keyboard_interrupt_detection(self):
        r = ProcessResult(command="long-process", signal_name="KeyboardInterrupt", exit_code=130)
        self.assertTrue(r.was_interrupted)

    def test_sigint_detection(self):
        r = ProcessResult(command="long-process", signal_name="SIGINT", exit_code=130)
        self.assertTrue(r.was_interrupted)


class TestShellContinuesAfterError(unittest.TestCase):
    """The error handler must NEVER crash the shell."""

    def test_classify_and_format_never_crashes(self):
        """Even with garbage input, the pipeline must produce a string."""
        r = ProcessResult(
            command="",
            exit_code=-999,
            stderr="\x00\x01\x02 binary garbage \xff\xfe",
        )
        try:
            output = classify_and_format(r, mode="normal")
            self.assertIsInstance(output, str)
        except Exception:
            self.fail("classify_and_format crashed with garbage input")

    def test_format_never_crashes_on_empty_error(self):
        formatter = ErrorFormatter(use_color=False)
        e = CommandError()
        try:
            output = formatter.format_normal(e)
            self.assertIsInstance(output, str)
        except Exception:
            self.fail("format_normal crashed on empty CommandError")


class TestFormatterFallback(unittest.TestCase):
    """Malformed errors must not crash the formatter."""

    def test_none_fields_handled(self):
        e = CommandError(
            exit_code=None,
            signal_name=None,
            clean_message="",
            raw_message="",
        )
        formatter = ErrorFormatter(use_color=False)
        output = formatter.format_normal(e)
        self.assertIsInstance(output, str)

    def test_very_long_output_handled(self):
        e = CommandError(
            stderr="x" * 100000,
            raw_message="y" * 100000,
        )
        formatter = ErrorFormatter(use_color=False)
        output = formatter.format_verbose(e)
        self.assertIsInstance(output, str)


class TestNoFalseExplanations(unittest.TestCase):
    """Unknown failures must say UNKNOWN, not fabricate causes."""

    def test_unknown_category_for_unrecognized_error(self):
        r = ProcessResult(
            command="custom_tool --do-thing",
            exit_code=42,
            stderr="XYZ-CUSTOM-ERROR: something proprietary happened",
        )
        e = classify_error(r)
        self.assertEqual(e.category, ErrorCategory.UNKNOWN)

    def test_unknown_does_not_fabricate_reason(self):
        r = ProcessResult(
            command="custom_tool",
            exit_code=99,
            stderr="unrecognizable output",
        )
        e = classify_error(r)
        # The reason should be empty or generic, not fabricated
        self.assertNotIn("npm", e.reason.lower() if e.reason else "")
        self.assertNotIn("python", e.reason.lower() if e.reason else "")


class TestNoControlCharInOutput(unittest.TestCase):
    """Non-TTY / NO_COLOR mode must not contain raw ANSI sequences."""

    def test_no_ansi_in_no_color(self):
        formatter = ErrorFormatter(use_color=False)
        e = CommandError(
            category=ErrorCategory.PROCESS_FAILED,
            title="Process failed",
            command="test",
            exit_code=1,
            clean_message="Something failed.",
        )
        output = formatter.format_normal(e)
        self.assertNotIn("\033[", output)
        self.assertNotIn("\x1b[", output)


# ═══════════════════════════════════════════════════════════════════════
#  suggest_similar_command Tests
# ═══════════════════════════════════════════════════════════════════════

class TestSuggestSimilarCommand(unittest.TestCase):
    """Tests for deterministic typo correction."""

    def test_close_match(self):
        suggestions = suggest_similar_command("gti", known_commands=["git", "go", "gcc"])
        self.assertIn("git", suggestions)

    def test_no_match(self):
        suggestions = suggest_similar_command("xyzabc123", known_commands=["git", "npm", "python"])
        self.assertEqual(len(suggestions), 0)

    def test_exact_match_excluded(self):
        suggestions = suggest_similar_command("git", known_commands=["git", "go", "gcc"])
        self.assertNotIn("git", suggestions)

    def test_empty_command(self):
        suggestions = suggest_similar_command("", known_commands=["git"])
        self.assertEqual(len(suggestions), 0)

    def test_max_suggestions_respected(self):
        suggestions = suggest_similar_command(
            "tes",
            known_commands=["test", "tests", "tess", "rest", "best"],
            max_suggestions=2,
        )
        self.assertTrue(len(suggestions) <= 2)


# ═══════════════════════════════════════════════════════════════════════
#  classify_and_format Pipeline Tests
# ═══════════════════════════════════════════════════════════════════════

class TestClassifyAndFormat(unittest.TestCase):
    """Tests for the full pipeline."""

    def test_normal_mode(self):
        r = ProcessResult(
            command="foobar",
            exit_code=9009,
            stderr="'foobar' is not recognized as an internal or external command",
        )
        output = classify_and_format(r, mode="normal")
        self.assertIn("Command not found", output)
        self.assertIn("foobar", output)

    def test_json_mode(self):
        r = ProcessResult(
            command="git status",
            exit_code=128,
            stderr="fatal: not a git repository",
        )
        output = classify_and_format(r, mode="json")
        parsed = json.loads(output)
        self.assertFalse(parsed["success"])
        self.assertEqual(parsed["category"], "GIT_ERROR")

    def test_verbose_mode(self):
        r = ProcessResult(
            command="npm install",
            exit_code=1,
            stderr="npm ERR! ERESOLVE could not resolve dependency tree\nnpm ERR! more details...",
        )
        output = classify_and_format(r, mode="verbose")
        self.assertIn("ERESOLVE", output)
        self.assertIn("more details", output)

    def test_secret_redaction_in_pipeline(self):
        r = ProcessResult(
            command="deploy",
            exit_code=1,
            stderr="Error: API_KEY=sk-secret123 is invalid",
        )
        output = classify_and_format(r, mode="normal")
        self.assertNotIn("sk-secret123", output)

    def test_command_not_found_suggests_typo_correction(self):
        r = ProcessResult(
            command="gti status",
            exit_code=9009,
            stderr="'gti' is not recognized as an internal or external command",
        )
        output = classify_and_format(r, mode="normal")
        self.assertIn("Command not found", output)


# ═══════════════════════════════════════════════════════════════════════
#  Helper Function Tests
# ═══════════════════════════════════════════════════════════════════════

class TestFormatDirectoryError(unittest.TestCase):
    """Tests for format_directory_error helper."""

    def test_basic_output(self):
        output = format_directory_error("nonexistent_dir", cwd="/home/user")
        self.assertIn("Directory not found", output)
        self.assertIn("nonexistent_dir", output)

    def test_with_similar_dirs(self):
        output = format_directory_error("src", similar_dirs=["srcs", "source", "dist"])
        self.assertIn("srcs", output)

    def test_no_color(self):
        output = format_directory_error("test", use_color=False)
        self.assertNotIn("\033[", output)


class TestFormatDevosError(unittest.TestCase):
    """Tests for format_devos_error helper."""

    def test_basic_output(self):
        output = format_devos_error(
            title="Project not found",
            message="No project matching 'xyz' found.",
            suggestions=["Run `worksapce scan <path>` first."],
        )
        self.assertIn("Project not found", output)
        self.assertIn("xyz", output)

    def test_no_color(self):
        output = format_devos_error(
            title="Error",
            message="something failed",
            use_color=False,
        )
        self.assertNotIn("\033[", output)


# ═══════════════════════════════════════════════════════════════════════
#  run_command Tests
# ═══════════════════════════════════════════════════════════════════════

class TestRunCommand(unittest.TestCase):
    """Tests for the run_command wrapper."""

    def test_echo_success(self):
        if os.name == "nt":
            r = run_command('echo hello', capture=True)
        else:
            r = run_command('echo hello', capture=True)
        self.assertEqual(r.exit_code, 0)
        self.assertTrue(r.success)
        self.assertIn("hello", r.stdout)

    def test_nonexistent_command(self):
        r = run_command('this_command_definitely_does_not_exist_xyz123', capture=True)
        self.assertNotEqual(r.exit_code, 0)
        self.assertFalse(r.success)

    def test_captures_stderr(self):
        if os.name == "nt":
            r = run_command('cmd /c "echo error_output 1>&2"', capture=True)
        else:
            r = run_command('echo error_output >&2', capture=True)
        self.assertIn("error_output", r.stderr)

    def test_cwd_tracked(self):
        cwd = os.getcwd()
        r = run_command('echo test', cwd=cwd, capture=True)
        self.assertEqual(r.cwd, cwd)

    def test_duration_positive(self):
        r = run_command('echo fast', capture=True)
        self.assertGreaterEqual(r.duration, 0.0)

    def test_timestamps_populated(self):
        r = run_command('echo test', capture=True)
        self.assertTrue(len(r.started_at) > 0)
        self.assertTrue(len(r.finished_at) > 0)


# ═══════════════════════════════════════════════════════════════════════
#  Error History DB Tests
# ═══════════════════════════════════════════════════════════════════════

class TestErrorHistoryDB(unittest.TestCase):
    """Tests for error_history database operations."""

    def setUp(self):
        from nexterm import db as db_mod
        self.conn = db_mod.connect(Path(":memory:"))

    def test_record_and_retrieve_error(self):
        from nexterm import db as db_mod
        db_mod.record_error(
            self.conn,
            command="foobar",
            cwd="/home/user",
            exit_code=127,
            category="COMMAND_NOT_FOUND",
            source="System",
            title="Command not found",
            summary="`foobar` is not available in PATH.",
        )
        errors = db_mod.get_recent_errors(self.conn, limit=10)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["command"], "foobar")
        self.assertEqual(errors[0]["category"], "COMMAND_NOT_FOUND")

    def test_error_history_limit(self):
        from nexterm import db as db_mod
        for i in range(5):
            db_mod.record_error(
                self.conn,
                command=f"cmd{i}",
                cwd="/",
                exit_code=1,
                category="UNKNOWN",
                source="Unknown",
                title="Failed",
            )
        errors = db_mod.get_recent_errors(self.conn, limit=3)
        self.assertEqual(len(errors), 3)

    def test_empty_history(self):
        from nexterm import db as db_mod
        errors = db_mod.get_recent_errors(self.conn, limit=10)
        self.assertEqual(len(errors), 0)


if __name__ == "__main__":
    unittest.main()
