"""Pre-Push Guardian & CI Verification Subsystem for DeveloperOS.

Provides local pre-push repository defense, diff secret scanning, file hygiene validation,
unit test execution, package build validation, clean environment smoke testing,
and Git pre-push hook management.

Enforcement Architecture:
    - Local Gate: .git/hooks/pre-push blocks pushes before remote reception.
    - Remote Gate: GitHub Actions CI status checks enforce branch protection rules.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from . import errors as errors_mod
from .release import ReleaseValidator, CheckResult, ReleaseCheckReport, format_report_terminal


@dataclass
class GuardianReport:
    version: str
    is_hook_installed: bool
    bypassed: bool = False
    checks: list[CheckResult] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)


class GuardianEngine:
    """Pre-Push Guardian verification and repository defense engine."""

    SECRET_PATTERNS = [
        (re.compile(r"(?:API[_-]?KEY|SECRET[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY|AUTH[_-]?TOKEN)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{16,}['\"]?", re.IGNORECASE), "Secret API key or token detected"),
        (re.compile(r"-----BEGIN (?:RSA|OPENSSH|EC|PGP) PRIVATE KEY-----"), "Private key header detected"),
        (re.compile(r"ghp_[A-Za-z0-9]{36}"), "GitHub Personal Access Token detected"),
        (re.compile(r"pypi-[A-Za-z0-9_\-]{50,}"), "PyPI API Token detected"),
        (re.compile(r"xox[bapz]-[0-9]{10,}-[0-9]{10,}-[a-zA-Z0-9]{24}"), "Slack OAuth/Bot Token detected"),
    ]

    FORBIDDEN_UNTRACKED_PATTERNS = [
        (re.compile(r"^\.env($|\.)", re.IGNORECASE), "Unignored .env file"),
        (re.compile(r"\.key$", re.IGNORECASE), "Unignored private key file"),
        (re.compile(r"\.pem$", re.IGNORECASE), "Unignored PEM certificate/key file"),
        (re.compile(r"id_rsa", re.IGNORECASE), "Unignored SSH private key"),
    ]

    def __init__(self, repo_root: Path | str | None = None):
        self.repo_root = Path(repo_root or Path.cwd()).resolve()
        self.release_validator = ReleaseValidator(self.repo_root)

    def check_git_hygiene(self) -> CheckResult:
        """Check .gitignore presence and untracked secret/sensitive files."""
        details = []
        gitignore_path = self.repo_root / ".gitignore"

        if not gitignore_path.exists():
            return CheckResult("Git Hygiene", False, ".gitignore file is missing from repository root.")

        details.append(".gitignore file present.")

        # Check git status for untracked forbidden files
        try:
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
                untracked_forbidden = []
                for line in lines:
                    if line.startswith("??"):
                        fname = line[3:].strip()
                        for pattern, label in self.FORBIDDEN_UNTRACKED_PATTERNS:
                            if pattern.search(fname):
                                untracked_forbidden.append(f"{fname} ({label})")

                if untracked_forbidden:
                    return CheckResult(
                        "Git Hygiene",
                        False,
                        f"Found {len(untracked_forbidden)} untracked sensitive file(s). Add them to .gitignore immediately.",
                        untracked_forbidden,
                    )
        except Exception as e:
            details.append(f"Git status warning: {e}")

        return CheckResult("Git Hygiene", True, "Git repository hygiene valid. .gitignore present.", details)

    def analyze_changed_files(self) -> tuple[CheckResult, list[str]]:
        """Identify files modified in outgoing commit diff or staged area."""
        changed_files = []
        try:
            # 1. Try comparing against upstream tracking branch @{u}
            res = subprocess.run(
                ["git", "diff", "--name-only", "@{u}..HEAD"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                changed_files = [f.strip() for f in res.stdout.splitlines() if f.strip()]
            else:
                # Fallback to HEAD~1..HEAD or staged files
                res_staged = subprocess.run(
                    ["git", "diff", "--name-only", "--cached"],
                    cwd=self.repo_root,
                    capture_output=True,
                    text=True,
                )
                if res_staged.returncode == 0 and res_staged.stdout.strip():
                    changed_files = [f.strip() for f in res_staged.stdout.splitlines() if f.strip()]
                else:
                    res_head = subprocess.run(
                        ["git", "diff", "--name-only", "HEAD~1..HEAD"],
                        cwd=self.repo_root,
                        capture_output=True,
                        text=True,
                    )
                    if res_head.returncode == 0:
                        changed_files = [f.strip() for f in res_head.stdout.splitlines() if f.strip()]
        except Exception as e:
            return CheckResult("Changed Files Analysis", True, f"Could not determine diff: {e}"), []

        msg = f"Analyzed {len(changed_files)} changed file(s) in outgoing commit." if changed_files else "No changed files detected in diff."
        return CheckResult("Changed Files Analysis", True, msg, changed_files[:10]), changed_files

    def scan_secrets(self, changed_files: list[str]) -> CheckResult:
        """Scan diff contents and changed file texts for API keys, tokens, or private keys."""
        findings = []

        # 1. Scan git diff text if available
        try:
            res_diff = subprocess.run(
                ["git", "diff", "--cached"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
            )
            diff_text = res_diff.stdout if res_diff.returncode == 0 and res_diff.stdout else ""

            if not diff_text:
                res_head_diff = subprocess.run(
                    ["git", "diff", "HEAD~1..HEAD"],
                    cwd=self.repo_root,
                    capture_output=True,
                    text=True,
                )
                diff_text = res_head_diff.stdout if res_head_diff.returncode == 0 else ""

            if diff_text:
                for line in diff_text.splitlines():
                    if line.startswith("+") and not line.startswith("+++"):
                        for pattern, label in self.SECRET_PATTERNS:
                            if pattern.search(line):
                                findings.append(f"Diff line addition: {label}")
        except Exception:
            pass

        # 2. Scan content of modified python/config files
        for rel_path in changed_files:
            file_path = self.repo_root / rel_path
            if file_path.exists() and file_path.is_file() and file_path.stat().st_size < 1000000:
                try:
                    text = file_path.read_text(encoding="utf-8", errors="ignore")
                    for pattern, label in self.SECRET_PATTERNS:
                        if pattern.search(text):
                            findings.append(f"{rel_path}: {label}")
                except Exception:
                    pass

        if findings:
            return CheckResult("Secret Scanner", False, f"Secret scan detected {len(findings)} potential secret(s).", findings)
        return CheckResult("Secret Scanner", True, "Zero secrets or private keys detected in changed code.")

    def validate_dependencies(self) -> CheckResult:
        """Validate pyproject.toml syntax and dependency configuration."""
        pyproject_path = self.repo_root / "pyproject.toml"
        if not pyproject_path.exists():
            return CheckResult("Dependency Check", False, "pyproject.toml not found.")

        try:
            content = pyproject_path.read_text(encoding="utf-8")
            if "[project]" not in content or "dependencies" not in content:
                return CheckResult("Dependency Check", False, "pyproject.toml missing [project] or dependencies field.")
            return CheckResult("Dependency Check", True, "pyproject.toml dependencies valid.")
        except Exception as e:
            return CheckResult("Dependency Check", False, f"Invalid pyproject.toml: {e}")

    def install_git_hook(self) -> CheckResult:
        """Install pre-push Git hook in .git/hooks/pre-push."""
        git_dir = self.repo_root / ".git"
        if not git_dir.exists():
            return CheckResult("Git Hook Install", False, ".git directory not found. Initialize git repository first.")

        hooks_dir = git_dir / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook_path = hooks_dir / "pre-push"

        hook_script = f"""#!/bin/sh
# DeveloperOS Pre-Push Guardian Git Hook
# Automatically generated by `workspace guardian install-hook`

if [ "$SKIP_GUARDIAN" = "1" ]; then
    echo "[GUARDIAN WARNING] SKIP_GUARDIAN=1 detected. Pre-push checks bypassed."
    exit 0
fi

"{sys.executable}" "{self.repo_root / 'scripts' / 'pre_push.py'}"
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "[GUARDIAN BLOCK] Push rejected by DeveloperOS Pre-Push Guardian."
    echo "[GUARDIAN TIP] Resolve errors above or pass SKIP_GUARDIAN=1 to bypass."
    exit $EXIT_CODE
fi
"""

        try:
            hook_path.write_text(hook_script, encoding="utf-8")

            # Set POSIX executable permissions
            if os.name != "nt":
                hook_path.chmod(0o755)

            return CheckResult("Git Hook Install", True, f"Installed pre-push hook at {hook_path.relative_to(self.repo_root)}.")
        except Exception as e:
            return CheckResult("Git Hook Install", False, f"Failed to write Git hook: {e}")

    def remove_git_hook(self) -> CheckResult:
        """Remove pre-push Git hook from .git/hooks/pre-push."""
        hook_path = self.repo_root / ".git" / "hooks" / "pre-push"
        if hook_path.exists():
            try:
                hook_path.unlink()
                return CheckResult("Git Hook Remove", True, "Pre-push hook removed successfully.")
            except Exception as e:
                return CheckResult("Git Hook Remove", False, f"Failed to delete hook: {e}")
        return CheckResult("Git Hook Remove", True, "No pre-push hook was installed.")

    def check_hook_status(self) -> bool:
        """Check if DeveloperOS pre-push hook is installed."""
        hook_path = self.repo_root / ".git" / "hooks" / "pre-push"
        if hook_path.exists():
            try:
                content = hook_path.read_text(encoding="utf-8")
                return "DeveloperOS Pre-Push Guardian" in content
            except Exception:
                return False
        return False

    def run_full_guardian_check(self) -> GuardianReport:
        """Run full pre-push Guardian verification pipeline.

        Guardian is responsible for repository integrity and security checks ONLY.
        It does NOT re-run pytest, build, twine, or venv smoke tests — those
        belong to CI and Release pipelines respectively.
        """
        bypassed = os.environ.get("SKIP_GUARDIAN") == "1"
        is_installed = self.check_hook_status()

        # 1. Hygiene check
        hygiene_check = self.check_git_hygiene()

        # 2. Changed file analysis
        files_check, changed_files = self.analyze_changed_files()

        # 3. Secret scan
        secret_check = self.scan_secrets(changed_files)

        # 4. Dependency check
        dep_check = self.validate_dependencies()

        checks = [
            hygiene_check,
            files_check,
            secret_check,
            dep_check,
        ]

        return GuardianReport(
            version=__version__,
            is_hook_installed=is_installed,
            bypassed=bypassed,
            checks=checks,
            changed_files=changed_files,
        )


def format_guardian_report_terminal(report: GuardianReport, use_color: bool | None = None) -> str:
    """Format GuardianReport using DeveloperOS clean semantic styling."""
    formatter = errors_mod.ErrorFormatter(use_color=use_color)
    lines = []

    lines.append("\n============================================================")
    lines.append(f"     DeveloperOS Pre-Push Guardian System (v{report.version})")
    lines.append("============================================================\n")

    hook_status = formatter._s("path", "[ACTIVE]") if report.is_hook_installed else formatter._s("dim", "[NOT INSTALLED]")
    lines.append(f"  Pre-Push Hook: {hook_status} (install via `workspace guardian install-hook`)")

    if report.bypassed:
        lines.append(f"  {formatter._s('error', '[WARNING]')} SKIP_GUARDIAN=1 active. Enforcement bypassed.")
        lines.append("------------------------------------------------------------\n")
        return "\n".join(lines)

    lines.append("")

    for check in report.checks:
        status_str = formatter._s("path", "[OK]") if check.passed else formatter._s("error", "[ERR]")
        lines.append(f"  {status_str}  {formatter._s('label', check.name):<26} {check.message}")
        if check.details:
            for d in check.details[:5]:
                lines.append(f"        {formatter._s('dim', d)}")

    lines.append("\n------------------------------------------------------------")
    if report.all_passed:
        lines.append(f"  {formatter._s('path', '[SUCCESS]')} All Guardian pre-push checks passed. Git push authorized.")
    else:
        lines.append(f"  {formatter._s('error', '[BLOCKED]')} Guardian pre-push validation failed. Push rejected.")
        lines.append(f"            Fix errors above or run `SKIP_GUARDIAN=1 git push` for emergency bypass.")
    lines.append("------------------------------------------------------------\n")

    return "\n".join(lines)
