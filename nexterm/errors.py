"""Professional Error Handling & Terminal Error UX for DeveloperOS.

Architecture:

    User Command
         ↓
    Process Executor (run_command)
         ↓
    ProcessResult
         │
         ├── stdout, stderr, exit_code, signal, duration, cwd, command
         │
    exit_code == 0? ──YES──→ Pass through (success stays quiet)
         │
        NO
         ↓
    ErrorClassifier Chain
         │
         ├── SystemErrorClassifier    (COMMAND_NOT_FOUND, PERMISSION_DENIED, FILE_NOT_FOUND)
         ├── NpmErrorClassifier       (PACKAGE_MANAGER_ERROR, DEPENDENCY_MISSING)
         ├── PythonErrorClassifier    (PYTHON_ERROR, traceback extraction)
         ├── GitErrorClassifier       (GIT_ERROR, branch/merge patterns)
         ├── DockerErrorClassifier    (DOCKER_ERROR, daemon/port issues)
         ├── PortConflictClassifier   (PORT_IN_USE, EADDRINUSE)
         └── GenericClassifier        (UNKNOWN fallback)
         ↓
    CommandError
         ↓
    SecretRedactor
         ↓
    ErrorFormatter
         │
         ├── format_normal()   → compact summary
         ├── format_verbose()  → summary + raw stderr/stdout
         ├── format_debug()    → all diagnostics + traceback + classifier meta
         └── format_json()     → machine-readable JSON
         ↓
    Terminal Output

Principles:
    - Preserve the truth: raw stderr/stdout NEVER discarded
    - Reduce the noise: structured, compact output
    - Explain the failure: clean_message, reason
    - Give the next useful action: suggestions
    - Success stays quiet: no wrapper on exit 0
    - Never crash the shell: safe fallback formatting
    - Never expose secrets: redaction before display
    - Never fabricate explanations: UNKNOWN > wrong diagnosis
"""
from __future__ import annotations

import difflib
import enum
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence


# ═══════════════════════════════════════════════════════════════════════
#  ENUMS
# ═══════════════════════════════════════════════════════════════════════

class ErrorCategory(enum.Enum):
    """Classification categories for command failures."""
    COMMAND_NOT_FOUND = "COMMAND_NOT_FOUND"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    DIRECTORY_NOT_FOUND = "DIRECTORY_NOT_FOUND"
    PORT_IN_USE = "PORT_IN_USE"
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    ENVIRONMENT_MISSING = "ENVIRONMENT_MISSING"
    RUNTIME_VERSION = "RUNTIME_VERSION"
    PROCESS_FAILED = "PROCESS_FAILED"
    PROCESS_CRASHED = "PROCESS_CRASHED"
    PROCESS_TIMEOUT = "PROCESS_TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    GIT_ERROR = "GIT_ERROR"
    DOCKER_ERROR = "DOCKER_ERROR"
    PACKAGE_MANAGER_ERROR = "PACKAGE_MANAGER_ERROR"
    PYTHON_ERROR = "PYTHON_ERROR"
    NODE_ERROR = "NODE_ERROR"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    INTERRUPTED = "INTERRUPTED"
    UNKNOWN = "UNKNOWN"


class ErrorSource(enum.Enum):
    """Origin of the error."""
    SYSTEM = "System"
    NODE = "Node"
    NPM = "npm"
    PNPM = "pnpm"
    YARN = "yarn"
    PYTHON = "Python"
    PIP = "pip"
    GIT = "Git"
    DOCKER = "Docker"
    CARGO = "Cargo"
    DEVELOPEROS = "DeveloperOS"
    AI = "AI"
    FILESYSTEM = "Filesystem"
    UNKNOWN = "Unknown"


# ═══════════════════════════════════════════════════════════════════════
#  DATA MODELS
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class ProcessResult:
    """Structured result from every executed command.

    Every external process execution produces a ProcessResult with enough
    structured information to diagnose failures. Successful commands use
    this too, but the error pipeline only activates on non-zero exit.
    """
    command: str
    args: list[str] = field(default_factory=list)
    cwd: str = ""
    exit_code: int | None = None
    signal_name: str | None = None
    stdout: str = ""
    stderr: str = ""
    duration: float = 0.0
    started_at: str = ""
    finished_at: str = ""
    timed_out: bool = False
    executable: str = ""

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    @property
    def was_interrupted(self) -> bool:
        return self.signal_name in ("SIGINT", "SIGTERM", "KeyboardInterrupt")


@dataclass
class CommandError:
    """Structured internal error model.

    Produced by the ErrorClassifier from a ProcessResult. Contains both
    the clean human-readable explanation AND the raw original output.
    """
    category: ErrorCategory = ErrorCategory.UNKNOWN
    title: str = "Command failed"
    command: str = ""
    cwd: str = ""
    exit_code: int | None = None
    signal_name: str | None = None
    raw_message: str = ""
    clean_message: str = ""
    reason: str = ""
    suggestions: list[str] = field(default_factory=list)
    source: ErrorSource = ErrorSource.UNKNOWN
    stdout: str = ""
    stderr: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Machine-readable representation (JSON mode)."""
        return {
            "success": False,
            "category": self.category.value,
            "source": self.source.value,
            "title": self.title,
            "command": self.command,
            "cwd": self.cwd,
            "exit_code": self.exit_code,
            "signal": self.signal_name,
            "message": self.clean_message,
            "reason": self.reason,
            "details": self.raw_message,
            "suggestions": self.suggestions,
            "raw_stderr": self.stderr,
            "raw_stdout": self.stdout,
        }


# ═══════════════════════════════════════════════════════════════════════
#  SECRET REDACTOR
# ═══════════════════════════════════════════════════════════════════════

# Patterns that identify secret variable names (case-insensitive)
_SECRET_NAME_PATTERNS = re.compile(
    r"(API[_-]?KEY|SECRET[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY|"
    r"AUTH[_-]?TOKEN|ACCESS[_-]?TOKEN|REFRESH[_-]?TOKEN|BEARER[_-]?TOKEN|TOKEN|"
    r"PASSWORD|PASSWD|DB[_-]?PASS|"
    r"SECRET|CLIENT[_-]?SECRET|APP[_-]?SECRET|"
    r"CREDENTIAL|AWS[_-]?SECRET|"
    r"STRIPE[_-]?KEY|SENDGRID[_-]?KEY|TWILIO[_-]?AUTH|"
    r"GITHUB[_-]?TOKEN|GITLAB[_-]?TOKEN|NPM[_-]?TOKEN|"
    r"DATABASE[_-]?URL|REDIS[_-]?URL|MONGO[_-]?URI|"
    r"ENCRYPTION[_-]?KEY|SIGNING[_-]?KEY|JWT[_-]?SECRET)",
    re.IGNORECASE,
)

# Pattern matching KEY=value in text
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(" + _SECRET_NAME_PATTERNS.pattern + r")\s*[=:]\s*(\S+)",
    re.IGNORECASE,
)


class SecretRedactor:
    """Redacts secrets from text before display.

    Applied to all user-facing error output. Never exposes API keys,
    passwords, tokens, or credentials in error messages, logs, or
    debug output.
    """

    REDACTED = "[REDACTED]"

    @classmethod
    def redact(cls, text: str) -> str:
        """Redact secret values from text."""
        if not text:
            return text

        # Redact KEY=value assignments
        def _replace_assignment(match):
            key_name = match.group(1)
            return f"{key_name}={cls.REDACTED}"

        result = _SECRET_ASSIGNMENT_PATTERN.sub(_replace_assignment, text)
        return result

    @classmethod
    def redact_error(cls, error: CommandError) -> CommandError:
        """Return a new CommandError with secrets redacted from all text fields."""
        return CommandError(
            category=error.category,
            title=error.title,
            command=error.command,
            cwd=error.cwd,
            exit_code=error.exit_code,
            signal_name=error.signal_name,
            raw_message=cls.redact(error.raw_message),
            clean_message=cls.redact(error.clean_message),
            reason=cls.redact(error.reason),
            suggestions=error.suggestions,  # suggestions are our own text, no secrets
            source=error.source,
            stdout=cls.redact(error.stdout),
            stderr=cls.redact(error.stderr),
            metadata=error.metadata,
        )


# ═══════════════════════════════════════════════════════════════════════
#  ERROR CLASSIFIERS
# ═══════════════════════════════════════════════════════════════════════

class ErrorClassifier:
    """Base class for error classifiers.

    Each classifier inspects a ProcessResult and either returns a
    CommandError (if it can classify the failure) or None (pass to next).

    Classification priority (§49):
        1. Structured OS error (errno, exit code patterns)
        2. Executable-specific patterns (npm, git, docker, python)
        3. Exit code interpretation
        4. Known stderr patterns
        5. UNKNOWN (fallback)
    """

    def classify(self, result: ProcessResult) -> CommandError | None:
        raise NotImplementedError


class SystemErrorClassifier(ErrorClassifier):
    """Classifies OS-level errors: command not found, permission denied, file not found."""

    # Windows error patterns
    _WIN_NOT_FOUND = re.compile(
        r"is not recognized as an internal or external command|"
        r"The system cannot find the file specified|"
        r"not recognized|"
        r"'(\S+)' is not recognized",
        re.IGNORECASE,
    )
    _WIN_PERMISSION = re.compile(
        r"Access is denied|"
        r"requires elevation|"
        r"Administrator privileges",
        re.IGNORECASE,
    )
    _WIN_FILE_NOT_FOUND = re.compile(
        r"The system cannot find the (file|path) specified|"
        r"No such file or directory",
        re.IGNORECASE,
    )

    # Unix error patterns
    _UNIX_NOT_FOUND = re.compile(
        r"command not found|"
        r"not found|"
        r"No such file or directory.*exec",
        re.IGNORECASE,
    )
    _UNIX_PERMISSION = re.compile(
        r"Permission denied|"
        r"EACCES|"
        r"Operation not permitted",
        re.IGNORECASE,
    )

    def classify(self, result: ProcessResult) -> CommandError | None:
        combined = (result.stderr + " " + result.stdout).strip()
        executable = result.command.split()[0] if result.command else ""

        # COMMAND_NOT_FOUND: exit code 9009 (Windows) or 127 (Unix)
        if result.exit_code in (9009, 127) or self._WIN_NOT_FOUND.search(combined) or \
                (result.exit_code == 1 and self._UNIX_NOT_FOUND.search(combined) and "command not found" in combined.lower()):
            return CommandError(
                category=ErrorCategory.COMMAND_NOT_FOUND,
                title="Command not found",
                command=result.command,
                cwd=result.cwd,
                exit_code=result.exit_code,
                clean_message=f"`{executable}` is not available in PATH.",
                reason=f"The executable `{executable}` was not found on this system.",
                source=ErrorSource.SYSTEM,
                stderr=result.stderr,
                stdout=result.stdout,
                raw_message=combined[:500],
            )

        # PERMISSION_DENIED
        if self._WIN_PERMISSION.search(combined) or self._UNIX_PERMISSION.search(combined):
            return CommandError(
                category=ErrorCategory.PERMISSION_DENIED,
                title="Permission denied",
                command=result.command,
                cwd=result.cwd,
                exit_code=result.exit_code,
                clean_message=f"Insufficient permissions to execute `{executable}`.",
                reason="The command requires elevated privileges or the file is not accessible.",
                suggestions=["Run with administrator/sudo privileges.", "Check file permissions."],
                source=ErrorSource.SYSTEM,
                stderr=result.stderr,
                stdout=result.stdout,
                raw_message=combined[:500],
            )

        # FILE_NOT_FOUND (generic, not command-not-found)
        if result.exit_code in (2,) and self._WIN_FILE_NOT_FOUND.search(combined):
            return CommandError(
                category=ErrorCategory.FILE_NOT_FOUND,
                title="File not found",
                command=result.command,
                cwd=result.cwd,
                exit_code=result.exit_code,
                clean_message="The specified file or path does not exist.",
                source=ErrorSource.FILESYSTEM,
                stderr=result.stderr,
                stdout=result.stdout,
                raw_message=combined[:500],
            )

        return None


class NpmErrorClassifier(ErrorClassifier):
    """Classifies npm/pnpm/yarn errors."""

    _NPM_ENOENT = re.compile(r"npm ERR!.*ENOENT|Could not read package\.json|enoent", re.IGNORECASE)
    _NPM_ERESOLVE = re.compile(r"npm ERR!.*ERESOLVE|Could not resolve dependency|peer dep", re.IGNORECASE)
    _NPM_MISSING_SCRIPT = re.compile(r"Missing script|npm ERR!.*missing script", re.IGNORECASE)
    _NPM_NETWORK = re.compile(r"npm ERR!.*ENETUNREACH|npm ERR!.*ETIMEDOUT|npm ERR!.*EAI_AGAIN|network", re.IGNORECASE)
    _PNPM_MARKER = re.compile(r"ERR_PNPM", re.IGNORECASE)
    _YARN_MARKER = re.compile(r"error.*yarn|YN\d{4}", re.IGNORECASE)

    def _detect_source(self, result: ProcessResult) -> ErrorSource:
        executable = result.command.split()[0].lower() if result.command else ""
        if "pnpm" in executable or self._PNPM_MARKER.search(result.stderr):
            return ErrorSource.PNPM
        if "yarn" in executable or self._YARN_MARKER.search(result.stderr):
            return ErrorSource.YARN
        return ErrorSource.NPM

    def classify(self, result: ProcessResult) -> CommandError | None:
        executable = result.command.split()[0].lower() if result.command else ""
        if executable not in ("npm", "npx", "pnpm", "yarn"):
            return None

        combined = (result.stderr + " " + result.stdout).strip()
        source = self._detect_source(result)

        # Missing package.json
        if self._NPM_ENOENT.search(combined):
            return CommandError(
                category=ErrorCategory.FILE_NOT_FOUND,
                title=f"{source.value} install failed",
                command=result.command,
                cwd=result.cwd,
                exit_code=result.exit_code,
                clean_message="package.json was not found.",
                reason="The current directory does not contain a package.json file.",
                suggestions=[
                    "Navigate to the Node project directory.",
                    "Create package.json with `npm init`.",
                ],
                source=source,
                stderr=result.stderr,
                stdout=result.stdout,
                raw_message=self._extract_npm_message(combined),
            )

        # Dependency resolution failure
        if self._NPM_ERESOLVE.search(combined):
            return CommandError(
                category=ErrorCategory.DEPENDENCY_MISSING,
                title=f"{source.value} dependency resolution failed",
                command=result.command,
                cwd=result.cwd,
                exit_code=result.exit_code,
                clean_message="Could not resolve dependency tree.",
                reason="Conflicting peer dependencies or version constraints.",
                suggestions=[
                    "Run with `--legacy-peer-deps` to bypass peer dependency checks.",
                    "Run with `--force` to force installation.",
                    "Check package.json for version conflicts.",
                ],
                source=source,
                stderr=result.stderr,
                stdout=result.stdout,
                raw_message=self._extract_npm_message(combined),
            )

        # Missing script
        if self._NPM_MISSING_SCRIPT.search(combined):
            script_name = ""
            m = re.search(r'missing script[:\s]*["\']?(\w[\w-]*)', combined, re.IGNORECASE)
            if m:
                script_name = m.group(1)
            return CommandError(
                category=ErrorCategory.CONFIGURATION_ERROR,
                title=f"{source.value} script not found",
                command=result.command,
                cwd=result.cwd,
                exit_code=result.exit_code,
                clean_message=f"Script `{script_name}` is not defined in package.json." if script_name else "The requested script is not defined in package.json.",
                suggestions=[
                    "Run `npm run` to list available scripts.",
                    "Check the `scripts` section in package.json.",
                ],
                source=source,
                stderr=result.stderr,
                stdout=result.stdout,
                raw_message=self._extract_npm_message(combined),
            )

        # Network error
        if self._NPM_NETWORK.search(combined):
            return CommandError(
                category=ErrorCategory.NETWORK_ERROR,
                title=f"{source.value} network error",
                command=result.command,
                cwd=result.cwd,
                exit_code=result.exit_code,
                clean_message="Network request failed during package operation.",
                suggestions=[
                    "Check your internet connection.",
                    "Check proxy/firewall settings.",
                    "Try again later.",
                ],
                source=source,
                stderr=result.stderr,
                stdout=result.stdout,
                raw_message=self._extract_npm_message(combined),
            )

        # Generic npm failure
        if result.exit_code and result.exit_code != 0:
            return CommandError(
                category=ErrorCategory.PACKAGE_MANAGER_ERROR,
                title=f"{source.value} command failed",
                command=result.command,
                cwd=result.cwd,
                exit_code=result.exit_code,
                clean_message=self._extract_npm_message(combined) or f"{source.value} exited with an error.",
                source=source,
                stderr=result.stderr,
                stdout=result.stdout,
                raw_message=combined[:1000],
            )

        return None

    @staticmethod
    def _extract_npm_message(text: str) -> str:
        """Extract the most meaningful npm error line from output."""
        lines = text.splitlines()
        meaningful = []
        for line in lines:
            cleaned = re.sub(r"^npm ERR!\s*", "", line).strip()
            if cleaned and cleaned not in ("", "code", "errno", "syscall", "path") and \
                    not cleaned.startswith("A complete log") and \
                    not cleaned.startswith("npm notice"):
                meaningful.append(cleaned)
        return "\n".join(meaningful[:5]) if meaningful else ""


class PythonErrorClassifier(ErrorClassifier):
    """Classifies Python runtime errors."""

    _TRACEBACK = re.compile(r"Traceback \(most recent call last\)")
    _MODULE_NOT_FOUND = re.compile(r"ModuleNotFoundError:\s*No module named\s+['\"]?(\S+)")
    _SYNTAX_ERROR = re.compile(r"SyntaxError:")
    _FILE_NOT_FOUND = re.compile(r"can't open file.*No such file or directory|FileNotFoundError|python:.*can't open file", re.IGNORECASE)

    def classify(self, result: ProcessResult) -> CommandError | None:
        executable = result.command.split()[0].lower() if result.command else ""
        if executable not in ("python", "python3", "py"):
            return None

        combined = (result.stderr + " " + result.stdout).strip()

        # Python script file not found
        if result.exit_code == 2 and self._FILE_NOT_FOUND.search(combined):
            script = ""
            parts = result.command.split()
            if len(parts) > 1:
                script = parts[1]
            return CommandError(
                category=ErrorCategory.FILE_NOT_FOUND,
                title="Python script not found",
                command=result.command,
                cwd=result.cwd,
                exit_code=result.exit_code,
                clean_message=f"Python could not find the file `{script}`." if script else "Python could not find the specified file.",
                suggestions=[
                    f"Check that `{script}` exists in the current directory." if script else "Check the file path.",
                    "Run `ls` or `dir` to inspect the directory.",
                ],
                source=ErrorSource.PYTHON,
                stderr=result.stderr,
                stdout=result.stdout,
                raw_message=combined[:500],
            )

        # ModuleNotFoundError
        m = self._MODULE_NOT_FOUND.search(combined)
        if m:
            module_name = m.group(1).strip("'\"")
            return CommandError(
                category=ErrorCategory.DEPENDENCY_MISSING,
                title="Python module not found",
                command=result.command,
                cwd=result.cwd,
                exit_code=result.exit_code,
                clean_message=f"Python could not import `{module_name}`.",
                reason=f"The module `{module_name}` is not installed.",
                suggestions=[
                    f"Install it: `pip install {module_name}`",
                    "Or install project dependencies: `pip install -r requirements.txt`",
                ],
                source=ErrorSource.PYTHON,
                stderr=result.stderr,
                stdout=result.stdout,
                raw_message=self._extract_traceback(combined),
            )

        # Generic Python traceback
        if self._TRACEBACK.search(combined):
            last_error = self._extract_last_error_line(combined)
            location = self._extract_traceback_location(combined)
            suggestions = []
            if location:
                suggestions.append(f"Inspect the error location: {location}")
            return CommandError(
                category=ErrorCategory.PYTHON_ERROR,
                title="Python process failed",
                command=result.command,
                cwd=result.cwd,
                exit_code=result.exit_code,
                clean_message=last_error or "Python raised an exception.",
                reason="",
                suggestions=suggestions or ["Inspect the traceback above for details."],
                source=ErrorSource.PYTHON,
                stderr=result.stderr,
                stdout=result.stdout,
                raw_message=self._extract_traceback(combined),
            )

        # Generic Python failure
        if result.exit_code and result.exit_code != 0:
            return CommandError(
                category=ErrorCategory.PYTHON_ERROR,
                title="Python process failed",
                command=result.command,
                cwd=result.cwd,
                exit_code=result.exit_code,
                clean_message="Python process exited with an error.",
                source=ErrorSource.PYTHON,
                stderr=result.stderr,
                stdout=result.stdout,
                raw_message=combined[:500],
            )

        return None

    @staticmethod
    def _extract_traceback(text: str) -> str:
        """Extract the Python traceback block."""
        lines = text.splitlines()
        tb_start = None
        for i, line in enumerate(lines):
            if "Traceback (most recent call last)" in line:
                tb_start = i
        if tb_start is not None:
            return "\n".join(lines[tb_start:])
        return text[:500]

    @staticmethod
    def _extract_last_error_line(text: str) -> str:
        """Extract the final exception line from a traceback."""
        lines = text.strip().splitlines()
        for line in reversed(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith("File ") and not stripped.startswith("^"):
                return stripped
        return ""

    @staticmethod
    def _extract_traceback_location(text: str) -> str:
        """Extract the last File "..." line from a traceback."""
        matches = re.findall(r'File "([^"]+)", line (\d+)', text)
        if matches:
            filepath, lineno = matches[-1]
            filename = Path(filepath).name
            return f"{filename}:{lineno}"
        return ""


class GitErrorClassifier(ErrorClassifier):
    """Classifies Git command errors."""

    _NOT_A_REPO = re.compile(r"not a git repository|fatal: not a git repo", re.IGNORECASE)
    _BRANCH_NOT_FOUND = re.compile(r"did not match any|pathspec.*did not match|error: pathspec|invalid reference", re.IGNORECASE)
    _MERGE_CONFLICT = re.compile(r"CONFLICT|Merge conflict|merge failed|Automatic merge failed", re.IGNORECASE)
    _PUSH_REJECTED = re.compile(r"rejected.*non-fast-forward|Updates were rejected|failed to push", re.IGNORECASE)
    _AUTH_FAILED = re.compile(r"Authentication failed|Permission denied|fatal: could not read", re.IGNORECASE)

    def classify(self, result: ProcessResult) -> CommandError | None:
        executable = result.command.split()[0].lower() if result.command else ""
        if executable != "git":
            return None

        combined = (result.stderr + " " + result.stdout).strip()

        # Not a git repository
        if self._NOT_A_REPO.search(combined):
            return CommandError(
                category=ErrorCategory.GIT_ERROR,
                title="Not a Git repository",
                command=result.command,
                cwd=result.cwd,
                exit_code=result.exit_code,
                clean_message="The current directory is not a Git repository.",
                suggestions=["Run `git init` to initialize a new repository.", "Navigate to a directory containing a Git repository."],
                source=ErrorSource.GIT,
                stderr=result.stderr,
                stdout=result.stdout,
                raw_message=combined[:500],
            )

        # Branch/ref not found
        if self._BRANCH_NOT_FOUND.search(combined):
            return CommandError(
                category=ErrorCategory.GIT_ERROR,
                title="Git reference not found",
                command=result.command,
                cwd=result.cwd,
                exit_code=result.exit_code,
                clean_message="The requested branch, tag, or path does not exist.",
                suggestions=["Run `git branch` to view available branches.", "Run `git tag` to view available tags."],
                source=ErrorSource.GIT,
                stderr=result.stderr,
                stdout=result.stdout,
                raw_message=combined[:500],
            )

        # Merge conflict
        if self._MERGE_CONFLICT.search(combined):
            return CommandError(
                category=ErrorCategory.GIT_ERROR,
                title="Git merge conflict",
                command=result.command,
                cwd=result.cwd,
                exit_code=result.exit_code,
                clean_message="Merge conflicts need to be resolved manually.",
                suggestions=["Run `git status` to see conflicting files.", "Resolve conflicts, then `git add` and `git commit`."],
                source=ErrorSource.GIT,
                stderr=result.stderr,
                stdout=result.stdout,
                raw_message=combined[:500],
            )

        # Push rejected
        if self._PUSH_REJECTED.search(combined):
            return CommandError(
                category=ErrorCategory.GIT_ERROR,
                title="Git push rejected",
                command=result.command,
                cwd=result.cwd,
                exit_code=result.exit_code,
                clean_message="Remote rejected the push (non-fast-forward).",
                suggestions=["Run `git pull --rebase` to sync with remote.", "Run `git push --force` if you intend to overwrite (caution)."],
                source=ErrorSource.GIT,
                stderr=result.stderr,
                stdout=result.stdout,
                raw_message=combined[:500],
            )

        # Generic Git failure
        if result.exit_code and result.exit_code != 0:
            git_message = self._extract_git_message(combined)
            return CommandError(
                category=ErrorCategory.GIT_ERROR,
                title="Git command failed",
                command=result.command,
                cwd=result.cwd,
                exit_code=result.exit_code,
                clean_message=git_message or "Git exited with an error.",
                source=ErrorSource.GIT,
                stderr=result.stderr,
                stdout=result.stdout,
                raw_message=combined[:500],
            )

        return None

    @staticmethod
    def _extract_git_message(text: str) -> str:
        """Extract the most meaningful Git error line."""
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("fatal:") or stripped.startswith("error:"):
                return stripped
        return ""


class DockerErrorClassifier(ErrorClassifier):
    """Classifies Docker/Docker Compose errors."""

    _DAEMON_NOT_RUNNING = re.compile(
        r"Cannot connect to the Docker daemon|"
        r"Is the docker daemon running|"
        r"docker daemon is not running|"
        r"error during connect",
        re.IGNORECASE,
    )
    _IMAGE_NOT_FOUND = re.compile(r"No such image|manifest unknown|pull access denied|repository does not exist", re.IGNORECASE)
    _PORT_CONFLICT = re.compile(r"port is already allocated|address already in use|Bind for.*failed", re.IGNORECASE)

    def classify(self, result: ProcessResult) -> CommandError | None:
        executable = result.command.split()[0].lower() if result.command else ""
        if executable not in ("docker", "docker-compose"):
            return None

        combined = (result.stderr + " " + result.stdout).strip()

        # Docker daemon not running
        if self._DAEMON_NOT_RUNNING.search(combined):
            return CommandError(
                category=ErrorCategory.DOCKER_ERROR,
                title="Docker daemon unavailable",
                command=result.command,
                cwd=result.cwd,
                exit_code=result.exit_code,
                clean_message="Could not connect to the Docker daemon.",
                reason="Docker Desktop or the Docker service is not running.",
                suggestions=["Start Docker Desktop or the Docker service.", "Run `docker info` to check Docker status."],
                source=ErrorSource.DOCKER,
                stderr=result.stderr,
                stdout=result.stdout,
                raw_message=combined[:500],
            )

        # Image not found
        if self._IMAGE_NOT_FOUND.search(combined):
            return CommandError(
                category=ErrorCategory.DOCKER_ERROR,
                title="Docker image not found",
                command=result.command,
                cwd=result.cwd,
                exit_code=result.exit_code,
                clean_message="The requested Docker image was not found.",
                suggestions=["Check the image name and tag.", "Run `docker pull <image>` to download it."],
                source=ErrorSource.DOCKER,
                stderr=result.stderr,
                stdout=result.stdout,
                raw_message=combined[:500],
            )

        # Port conflict
        if self._PORT_CONFLICT.search(combined):
            port = ""
            m = re.search(r"(?:port|Bind for)\s*[\w.:]*?:?(\d{2,5})", combined)
            if m:
                port = m.group(1)
            return CommandError(
                category=ErrorCategory.PORT_IN_USE,
                title="Docker port conflict",
                command=result.command,
                cwd=result.cwd,
                exit_code=result.exit_code,
                clean_message=f"Port {port} is already in use." if port else "A required port is already in use.",
                suggestions=[
                    f"Stop the process using port {port}." if port else "Free the conflicting port.",
                    "Or configure the container to use a different port.",
                ],
                source=ErrorSource.DOCKER,
                stderr=result.stderr,
                stdout=result.stdout,
                raw_message=combined[:500],
            )

        # Generic Docker failure
        if result.exit_code and result.exit_code != 0:
            return CommandError(
                category=ErrorCategory.DOCKER_ERROR,
                title="Docker command failed",
                command=result.command,
                cwd=result.cwd,
                exit_code=result.exit_code,
                clean_message="Docker exited with an error.",
                source=ErrorSource.DOCKER,
                stderr=result.stderr,
                stdout=result.stdout,
                raw_message=combined[:500],
            )

        return None


class PortConflictClassifier(ErrorClassifier):
    """Detects port-in-use errors across any tool."""

    _PORT_PATTERNS = re.compile(
        r"EADDRINUSE|"
        r"address already in use|"
        r"port is already allocated|"
        r"listen tcp.*bind.*address already in use|"
        r"port \d+ is already in use",
        re.IGNORECASE,
    )

    def classify(self, result: ProcessResult) -> CommandError | None:
        combined = (result.stderr + " " + result.stdout).strip()

        if not self._PORT_PATTERNS.search(combined):
            return None

        port = ""
        m = re.search(r":(\d{2,5})", combined)
        if m:
            port = m.group(1)

        return CommandError(
            category=ErrorCategory.PORT_IN_USE,
            title="Port already in use",
            command=result.command,
            cwd=result.cwd,
            exit_code=result.exit_code,
            clean_message=f"Port {port} is already in use." if port else "A required port is already in use.",
            suggestions=[
                f"Stop the process using port {port} or configure another port." if port else "Free the conflicting port or use an alternative.",
            ],
            source=ErrorSource.UNKNOWN,
            stderr=result.stderr,
            stdout=result.stdout,
            raw_message=combined[:500],
        )


class NodeErrorClassifier(ErrorClassifier):
    """Classifies Node.js runtime errors (not npm package manager)."""

    _MODULE_NOT_FOUND = re.compile(r"Error: Cannot find module|MODULE_NOT_FOUND", re.IGNORECASE)
    _SYNTAX_ERROR = re.compile(r"SyntaxError:", re.IGNORECASE)

    def classify(self, result: ProcessResult) -> CommandError | None:
        executable = result.command.split()[0].lower() if result.command else ""
        if executable not in ("node", "nodejs"):
            return None

        combined = (result.stderr + " " + result.stdout).strip()

        if self._MODULE_NOT_FOUND.search(combined):
            module_match = re.search(r"Cannot find module\s+['\"]([^'\"]+)", combined)
            module_name = module_match.group(1) if module_match else "unknown"
            return CommandError(
                category=ErrorCategory.DEPENDENCY_MISSING,
                title="Node module not found",
                command=result.command,
                cwd=result.cwd,
                exit_code=result.exit_code,
                clean_message=f"Node could not find module `{module_name}`.",
                suggestions=["Run `npm install` to install project dependencies."],
                source=ErrorSource.NODE,
                stderr=result.stderr,
                stdout=result.stdout,
                raw_message=combined[:500],
            )

        # Generic Node failure
        if result.exit_code and result.exit_code != 0:
            return CommandError(
                category=ErrorCategory.NODE_ERROR,
                title="Node process failed",
                command=result.command,
                cwd=result.cwd,
                exit_code=result.exit_code,
                clean_message="Node.js process exited with an error.",
                source=ErrorSource.NODE,
                stderr=result.stderr,
                stdout=result.stdout,
                raw_message=combined[:500],
            )

        return None


# ═══════════════════════════════════════════════════════════════════════
#  CLASSIFIER CHAIN
# ═══════════════════════════════════════════════════════════════════════

# Ordered by classification priority (§49)
DEFAULT_CLASSIFIERS: list[ErrorClassifier] = [
    SystemErrorClassifier(),
    NpmErrorClassifier(),
    PythonErrorClassifier(),
    GitErrorClassifier(),
    DockerErrorClassifier(),
    NodeErrorClassifier(),
    PortConflictClassifier(),
]


def classify_error(result: ProcessResult, classifiers: list[ErrorClassifier] | None = None) -> CommandError:
    """Run ProcessResult through the classifier chain.

    Returns the first successful classification, or a generic UNKNOWN error.
    Never returns None — always produces a structured CommandError.
    """
    classifiers = classifiers or DEFAULT_CLASSIFIERS

    for classifier in classifiers:
        try:
            error = classifier.classify(result)
            if error is not None:
                return error
        except Exception:
            # A classifier must NEVER crash the pipeline
            continue

    # Fallback: generic error (§16, §42, §55)
    combined = (result.stderr + " " + result.stdout).strip()
    return CommandError(
        category=ErrorCategory.UNKNOWN,
        title="Command failed",
        command=result.command,
        cwd=result.cwd,
        exit_code=result.exit_code,
        signal_name=result.signal_name,
        clean_message=f"The process exited with code {result.exit_code}.",
        source=ErrorSource.UNKNOWN,
        stderr=result.stderr,
        stdout=result.stdout,
        raw_message=combined[:500],
    )


# ═══════════════════════════════════════════════════════════════════════
#  ERROR FORMATTER
# ═══════════════════════════════════════════════════════════════════════

def _supports_color() -> bool:
    """Detect whether the terminal supports ANSI color."""
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(sys.stderr, "isatty") or not sys.stderr.isatty():
        return False
    if os.name == "nt":
        return os.environ.get("TERM") or os.environ.get("WT_SESSION") or True
    return True


class ErrorFormatter:
    """Renders CommandError to terminal with semantic styling.

    Modes:
        normal:  compact summary (default)
        verbose: summary + raw stderr/stdout
        debug:   all diagnostics + internal traceback + classifier metadata
        json:    machine-readable structured output

    Respects NO_COLOR and non-TTY environments.
    """

    # Semantic ANSI styles
    _STYLES = {
        "error":   "\033[1;31m",   # Bold red
        "warning": "\033[1;33m",   # Bold yellow
        "label":   "\033[1;37m",   # Bold white
        "value":   "\033[0;37m",   # Normal white
        "command": "\033[1;36m",   # Bold cyan
        "path":    "\033[0;36m",   # Cyan
        "dim":     "\033[2m",      # Dim
        "reset":   "\033[0m",
        "cross":   "\033[1;31m✗\033[0m",
    }

    def __init__(self, use_color: bool | None = None):
        if use_color is None:
            self._color = _supports_color()
        else:
            self._color = use_color

    def _s(self, style: str, text: str) -> str:
        """Apply semantic style if color is enabled."""
        if not self._color:
            return text
        return f"{self._STYLES.get(style, '')}{text}{self._STYLES['reset']}"

    def _cross(self) -> str:
        if self._color:
            return self._STYLES["cross"]
        return "X"

    def format_normal(self, error: CommandError) -> str:
        """Compact user-facing error summary."""
        lines = []
        lines.append(f"\n  {self._cross()} {self._s('error', error.title)}\n")

        if error.command:
            lines.append(f"    {self._s('label', 'Command')}    {self._s('command', error.command)}")
        if error.cwd:
            lines.append(f"    {self._s('label', 'Location')}   {self._s('path', error.cwd)}")
        if error.exit_code is not None:
            lines.append(f"    {self._s('label', 'Exit code')}  {error.exit_code}")
        if error.source != ErrorSource.UNKNOWN:
            lines.append(f"    {self._s('label', 'Source')}     {error.source.value}")

        lines.append("")

        if error.clean_message:
            lines.append(f"    {self._s('label', 'Error')}")
            for msg_line in error.clean_message.splitlines():
                lines.append(f"    {msg_line}")

        if error.reason:
            lines.append(f"\n    {self._s('label', 'Reason')}")
            for reason_line in error.reason.splitlines():
                lines.append(f"    {reason_line}")

        if error.raw_message and error.raw_message != error.clean_message:
            # Show condensed details (max 5 lines in normal mode)
            detail_lines = error.raw_message.strip().splitlines()[:5]
            if detail_lines:
                lines.append(f"\n    {self._s('label', 'Details')}")
                for dl in detail_lines:
                    lines.append(f"    {self._s('dim', dl)}")

        if error.suggestions:
            lines.append(f"\n    {self._s('label', 'Suggested action')}")
            for suggestion in error.suggestions:
                lines.append(f"    {suggestion}")

        lines.append("")
        return "\n".join(lines)

    def format_verbose(self, error: CommandError) -> str:
        """Normal summary plus raw stderr/stdout."""
        parts = [self.format_normal(error)]

        if error.stderr and error.stderr.strip():
            parts.append(f"    {self._s('label', 'Raw stderr')}")
            for line in error.stderr.strip().splitlines():
                parts.append(f"    {self._s('dim', line)}")
            parts.append("")

        if error.stdout and error.stdout.strip():
            parts.append(f"    {self._s('label', 'Raw stdout')}")
            for line in error.stdout.strip().splitlines():
                parts.append(f"    {self._s('dim', line)}")
            parts.append("")

        return "\n".join(parts)

    def format_debug(self, error: CommandError, internal_traceback: str = "") -> str:
        """Full diagnostic information."""
        parts = [self.format_verbose(error)]

        parts.append(f"    {self._s('label', 'Classifier')}")
        parts.append(f"    Category:  {error.category.value}")
        parts.append(f"    Source:    {error.source.value}")
        if error.metadata:
            for k, v in error.metadata.items():
                parts.append(f"    {k}: {v}")
        parts.append("")

        if internal_traceback:
            parts.append(f"    {self._s('label', 'Internal traceback')}")
            for line in internal_traceback.strip().splitlines():
                parts.append(f"    {self._s('dim', line)}")
            parts.append("")

        return "\n".join(parts)

    def format_json(self, error: CommandError) -> str:
        """Machine-readable JSON output (no ANSI escape sequences)."""
        return json.dumps(error.to_dict(), indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════
#  COMMAND EXECUTION WRAPPER
# ═══════════════════════════════════════════════════════════════════════

def run_command(
    command: str,
    cwd: str | Path | None = None,
    capture: bool = True,
    timeout: float | None = None,
) -> ProcessResult:
    """Execute a command and produce a structured ProcessResult.

    For interactive/streaming commands (npm run dev), set capture=False
    to let stdout/stderr flow to the terminal in real-time.

    Args:
        command: The command string to execute.
        cwd: Working directory (defaults to os.getcwd()).
        capture: If True, capture stdout/stderr. If False, stream to terminal.
        timeout: Maximum seconds to wait (None = no timeout).

    Returns:
        ProcessResult with all execution metadata.
    """
    cwd = str(cwd or os.getcwd())
    executable = command.split()[0] if command else ""

    result = ProcessResult(
        command=command,
        args=command.split()[1:] if command else [],
        cwd=cwd,
        executable=executable,
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    start_time = time.monotonic()

    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=capture,
            text=True if capture else None,
            timeout=timeout,
        )

        result.exit_code = proc.returncode
        result.finished_at = datetime.now(timezone.utc).isoformat()
        result.duration = time.monotonic() - start_time

        if capture:
            result.stdout = proc.stdout or ""
            result.stderr = proc.stderr or ""

        # Detect signal termination on Unix
        if proc.returncode and proc.returncode < 0:
            try:
                import signal
                result.signal_name = signal.Signals(-proc.returncode).name
            except (ValueError, AttributeError):
                result.signal_name = f"signal({-proc.returncode})"

    except subprocess.TimeoutExpired as e:
        result.timed_out = True
        result.exit_code = -1
        result.finished_at = datetime.now(timezone.utc).isoformat()
        result.duration = time.monotonic() - start_time
        if capture:
            result.stdout = (e.stdout or b"").decode("utf-8", errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            result.stderr = (e.stderr or b"").decode("utf-8", errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")

    except KeyboardInterrupt:
        result.signal_name = "KeyboardInterrupt"
        result.exit_code = 130  # Standard Ctrl+C exit code
        result.finished_at = datetime.now(timezone.utc).isoformat()
        result.duration = time.monotonic() - start_time

    except Exception as e:
        result.exit_code = -1
        result.stderr = str(e)
        result.finished_at = datetime.now(timezone.utc).isoformat()
        result.duration = time.monotonic() - start_time

    return result


# ═══════════════════════════════════════════════════════════════════════
#  TYPO CORRECTION
# ═══════════════════════════════════════════════════════════════════════

def suggest_similar_command(
    command: str,
    known_commands: Sequence[str] | None = None,
    max_distance: int = 2,
    max_suggestions: int = 3,
) -> list[str]:
    """Deterministic typo correction using Levenshtein distance.

    Returns similar commands sorted by edit distance. Only suggests
    matches within max_distance edits. Never auto-executes.
    """
    if not command:
        return []

    # Build candidate pool
    candidates: list[str] = list(known_commands or [])

    # Also check PATH executables
    try:
        from . import terminal as terminal_mod
        candidates.extend(terminal_mod._get_path_executables())
    except Exception:
        pass

    if not candidates:
        return []

    command_lower = command.lower()
    matches = difflib.get_close_matches(command_lower, [c.lower() for c in candidates], n=max_suggestions, cutoff=0.6)

    # Map back to original casing
    result = []
    lower_to_original = {c.lower(): c for c in candidates}
    for m in matches:
        original = lower_to_original.get(m, m)
        if original.lower() != command_lower:
            result.append(original)

    return result[:max_suggestions]


# ═══════════════════════════════════════════════════════════════════════
#  PIPELINE — classify_and_format
# ═══════════════════════════════════════════════════════════════════════

def classify_and_format(
    result: ProcessResult,
    mode: str = "normal",
    formatter: ErrorFormatter | None = None,
    classifiers: list[ErrorClassifier] | None = None,
    internal_traceback: str = "",
) -> str:
    """Full error pipeline: classify → redact → format.

    Args:
        result: The ProcessResult from command execution.
        mode: "normal", "verbose", "debug", or "json".
        formatter: ErrorFormatter instance (auto-created if None).
        classifiers: Custom classifier chain (defaults to DEFAULT_CLASSIFIERS).
        internal_traceback: Internal Python traceback (debug mode only).

    Returns:
        Formatted error string ready for terminal display.
    """
    # Classify
    error = classify_error(result, classifiers)

    # Add typo suggestions for COMMAND_NOT_FOUND
    if error.category == ErrorCategory.COMMAND_NOT_FOUND:
        executable = result.command.split()[0] if result.command else ""
        suggestions = suggest_similar_command(executable)
        if suggestions:
            error.suggestions = [f"Did you mean: {s}" for s in suggestions] + error.suggestions

    # Redact secrets
    error = SecretRedactor.redact_error(error)

    # Format
    if formatter is None:
        formatter = ErrorFormatter()

    if mode == "json":
        return formatter.format_json(error)
    elif mode == "debug":
        return formatter.format_debug(error, internal_traceback=internal_traceback)
    elif mode == "verbose":
        return formatter.format_verbose(error)
    else:
        return formatter.format_normal(error)


# ═══════════════════════════════════════════════════════════════════════
#  DIRECTORY ERROR HELPER
# ═══════════════════════════════════════════════════════════════════════

def format_directory_error(
    path: str,
    cwd: str = "",
    similar_dirs: list[str] | None = None,
    use_color: bool | None = None,
) -> str:
    """Format a structured DIRECTORY_NOT_FOUND error for cd failures."""
    error = CommandError(
        category=ErrorCategory.DIRECTORY_NOT_FOUND,
        title="Directory not found",
        command=f"cd {path}",
        cwd=cwd or os.getcwd(),
        clean_message="The directory does not exist.",
        source=ErrorSource.FILESYSTEM,
    )

    if similar_dirs:
        error.suggestions = ["Available matches:"] + [f"  {d}" for d in similar_dirs[:5]]
    else:
        error.suggestions = ["Run `ls` to inspect the current directory."]

    formatter = ErrorFormatter(use_color=use_color)
    return formatter.format_normal(error)


# ═══════════════════════════════════════════════════════════════════════
#  DEVOS INTERNAL ERROR HELPER
# ═══════════════════════════════════════════════════════════════════════

def format_devos_error(
    title: str,
    message: str,
    suggestions: list[str] | None = None,
    command: str = "",
    use_color: bool | None = None,
) -> str:
    """Format a structured DeveloperOS internal error."""
    error = CommandError(
        category=ErrorCategory.CONFIGURATION_ERROR,
        title=title,
        command=command,
        cwd=os.getcwd(),
        clean_message=message,
        source=ErrorSource.DEVELOPEROS,
        suggestions=suggestions or [],
    )
    formatter = ErrorFormatter(use_color=use_color)
    return formatter.format_normal(error)
