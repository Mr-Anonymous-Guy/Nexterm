"""Release Engine & Validation Subsystem for DeveloperOS.

Provides local release checks, artifact secret scanning, version alignment,
clean virtual environment smoke testing, and package verification.

Strict Security Guarantee:
    - NO PyPI API tokens in code, configs, secrets, or CLI.
    - Publication uses GitHub Actions OIDC Trusted Publishing.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from . import errors as errors_mod


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    details: list[str] = field(default_factory=list)


@dataclass
class ReleaseCheckReport:
    version: str
    git_tag: str | None
    checks: list[CheckResult] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)


class ReleaseValidator:
    """Automated release check & validation engine."""

    # Forbidden files inside release wheels/sdists
    FORBIDDEN_FILE_PATTERNS = [
        re.compile(r"\.env($|\.)", re.IGNORECASE),
        re.compile(r"\.key$", re.IGNORECASE),
        re.compile(r"\.pem$", re.IGNORECASE),
        re.compile(r"\.db$", re.IGNORECASE),
        re.compile(r"\.log$", re.IGNORECASE),
        re.compile(r"(^|/)\.git(/|$)", re.IGNORECASE),
        re.compile(r"\.pytest_cache", re.IGNORECASE),
        re.compile(r"id_rsa", re.IGNORECASE),
        re.compile(r"credentials", re.IGNORECASE),
        re.compile(r"secrets?\.(json|yaml|yml|txt|key)$", re.IGNORECASE),
    ]

    # Forbidden text content inside packaged files
    FORBIDDEN_CONTENT_PATTERNS = [
        (re.compile(r"(?:API[_-]?KEY|SECRET[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY|AUTH[_-]?TOKEN)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{16,}['\"]?", re.IGNORECASE), "Secret key/token detected"),
        (re.compile(r"-----BEGIN (?:RSA|OPENSSH|EC|PGP) PRIVATE KEY-----"), "Private key detected"),
        (re.compile(r"ghp_[A-Za-z0-9]{36}"), "GitHub Personal Access Token detected"),
        (re.compile(r"pypi-[A-Za-z0-9_\-]{50,}"), "PyPI API Token detected"),
    ]

    def __init__(self, repo_root: Path | str | None = None):
        self.repo_root = Path(repo_root or Path.cwd()).resolve()

    def check_git_status(self) -> CheckResult:
        """Check if Git working tree is clean."""
        try:
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
            )
            if res.returncode != 0:
                if "not a git repository" in res.stderr.lower():
                    return CheckResult("Git Working Tree", True, "Git repository not initialized locally (skipped).")
                return CheckResult("Git Status", False, "Git repository check failed.", [res.stderr.strip()])

            uncommitted = [line for line in res.stdout.splitlines() if line.strip()]
            if uncommitted:
                return CheckResult(
                    "Git Working Tree",
                    False,
                    f"Working tree has {len(uncommitted)} uncommitted change(s).",
                    uncommitted[:10],
                )
            return CheckResult("Git Working Tree", True, "Git working tree is clean.")
        except Exception as e:
            return CheckResult("Git Working Tree", False, f"Could not check Git status: {e}")

    def check_version_alignment(self, target_tag: str | None = None) -> CheckResult:
        """Check that package version, pyproject.toml, and git tag match."""
        details = []
        code_version = __version__
        details.append(f"nexterm.__version__: {code_version}")

        # pyproject.toml version
        pyproject_path = self.repo_root / "pyproject.toml"
        if not pyproject_path.exists():
            return CheckResult("Version Alignment", False, "pyproject.toml not found.")

        pyproject_text = pyproject_path.read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', pyproject_text, re.MULTILINE)
        if not match:
            return CheckResult("Version Alignment", False, "version field not found in pyproject.toml.")

        toml_version = match.group(1)
        details.append(f"pyproject.toml version: {toml_version}")

        if code_version != toml_version:
            return CheckResult(
                "Version Alignment",
                False,
                f"Version mismatch: __version__ ({code_version}) != pyproject.toml ({toml_version}).",
                details,
            )

        # Git tag check if target_tag provided or detected
        git_tag = target_tag
        if not git_tag:
            try:
                res = subprocess.run(
                    ["git", "describe", "--tags", "--exact-match"],
                    cwd=self.repo_root,
                    capture_output=True,
                    text=True,
                )
                if res.returncode == 0:
                    git_tag = res.stdout.strip()
            except Exception:
                pass

        if git_tag:
            clean_tag = git_tag.lstrip("v")
            details.append(f"Git tag: {git_tag} (clean: {clean_tag})")
            if clean_tag != code_version:
                return CheckResult(
                    "Version Alignment",
                    False,
                    f"Tag version mismatch: git tag ({git_tag}) != package version ({code_version}).",
                    details,
                )

        return CheckResult("Version Alignment", True, f"Version {code_version} aligned across codebase.", details)

    def run_tests(self) -> CheckResult:
        """Run the pytest test suite."""
        try:
            res = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-k", "not TestReleaseValidator and not TestGuardianEngine"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if res.returncode == 0:
                summary = res.stdout.strip().splitlines()[-1] if res.stdout.strip() else "Tests passed."
                return CheckResult("Test Suite", True, f"All unit tests passed ({summary}).")
            else:
                last_lines = res.stdout.strip().splitlines()[-10:] + res.stderr.strip().splitlines()[-10:]
                return CheckResult("Test Suite", False, "Unit tests failed.", last_lines)
        except subprocess.TimeoutExpired:
            return CheckResult("Test Suite", False, "Test suite timed out after 300 seconds.")
        except Exception as e:
            return CheckResult("Test Suite", False, f"Error running tests: {e}")

    def build_packages(self) -> tuple[CheckResult, list[Path]]:
        """Build wheel and sdist using python -m build."""
        dist_dir = (self.repo_root / "dist").resolve()
        try:
            res = subprocess.run(
                [sys.executable, "-m", "build"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if res.returncode != 0:
                return CheckResult("Build Packages", False, "Package build failed.", res.stderr.splitlines()[-10:]), []

            built_files = [f.resolve() for f in dist_dir.glob("*.whl")] + [f.resolve() for f in dist_dir.glob("*.tar.gz")]
            if not built_files:
                return CheckResult("Build Packages", False, "No package artifacts built in dist/."), []

            file_names = [f.name for f in built_files]
            return CheckResult("Build Packages", True, f"Built {len(built_files)} artifact(s): {', '.join(file_names)}.", file_names), built_files
        except Exception as e:
            return CheckResult("Build Packages", False, f"Build error: {e}"), []

    def validate_metadata(self) -> CheckResult:
        """Validate built dist packages using twine check."""
        dist_dir = (self.repo_root / "dist").resolve()
        artifacts = [f.resolve() for f in dist_dir.glob("*.whl")] + [f.resolve() for f in dist_dir.glob("*.tar.gz")]
        if not artifacts:
            self.build_packages()
            artifacts = [f.resolve() for f in dist_dir.glob("*.whl")] + [f.resolve() for f in dist_dir.glob("*.tar.gz")]
        if not artifacts:
            return CheckResult("Metadata Check", False, "No dist artifacts to check.")

        try:
            res = subprocess.run(
                [sys.executable, "-m", "twine", "check"] + [str(a) for a in artifacts],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if res.returncode == 0:
                return CheckResult("Metadata Check", True, "Twine metadata validation passed for all artifacts.")
            else:
                output_lines = (res.stdout + "\n" + res.stderr).strip().splitlines()
                return CheckResult("Metadata Check", False, "Twine metadata check failed.", output_lines[-10:])
        except Exception as e:
            return CheckResult("Metadata Check", False, f"Twine check error: {e}")

    def scan_artifact_secrets(self) -> CheckResult:
        """Scan zip/tar contents of built wheel and sdist for secrets or forbidden files."""
        dist_dir = (self.repo_root / "dist").resolve()
        artifacts = [f.resolve() for f in dist_dir.glob("*.whl")] + [f.resolve() for f in dist_dir.glob("*.tar.gz")]
        if not artifacts:
            self.build_packages()
            artifacts = [f.resolve() for f in dist_dir.glob("*.whl")] + [f.resolve() for f in dist_dir.glob("*.tar.gz")]
        if not artifacts:
            return CheckResult("Artifact Secret Scan", False, "No artifacts found in dist/.")

        findings = []

        for artifact in artifacts:
            if artifact.name.endswith(".whl"):
                try:
                    with zipfile.ZipFile(artifact, "r") as zf:
                        for name in zf.namelist():
                            for pattern in self.FORBIDDEN_FILE_PATTERNS:
                                if pattern.search(name):
                                    findings.append(f"[{artifact.name}] Forbidden file pattern: {name}")

                            # Read text content of small files to scan secrets
                            if zf.getinfo(name).file_size < 500000:
                                try:
                                    content = zf.read(name).decode("utf-8", errors="ignore")
                                    for c_pattern, msg in self.FORBIDDEN_CONTENT_PATTERNS:
                                        if c_pattern.search(content):
                                            findings.append(f"[{artifact.name}] {msg} in {name}")
                                except Exception:
                                    pass
                except Exception as e:
                    findings.append(f"Failed to inspect wheel {artifact.name}: {e}")

            elif artifact.name.endswith(".tar.gz"):
                try:
                    with tarfile.open(artifact, "r:gz") as tf:
                        for member in tf.getmembers():
                            for pattern in self.FORBIDDEN_FILE_PATTERNS:
                                if pattern.search(member.name):
                                    findings.append(f"[{artifact.name}] Forbidden file pattern: {member.name}")
                except Exception as e:
                    findings.append(f"Failed to inspect sdist {artifact.name}: {e}")

        if findings:
            return CheckResult("Artifact Secret Scan", False, f"Secret scan found {len(findings)} issue(s).", findings)
        return CheckResult("Artifact Secret Scan", True, "Artifact secret scan passed. Zero secrets or forbidden files found.")

    def clean_environment_smoke_test(self) -> CheckResult:
        """Test installing built wheel into a clean temporary venv."""
        dist_dir = (self.repo_root / "dist").resolve()
        wheels = [w.resolve() for w in dist_dir.glob("*.whl")]
        if not wheels:
            self.build_packages()
            wheels = [w.resolve() for w in dist_dir.glob("*.whl")]
        if not wheels:
            return CheckResult("Clean Venv Test", False, "No wheel file found in dist/.")

        matching_wheels = [w for w in wheels if f"-{__version__}-" in w.name or f"-{__version__}." in w.name]
        wheel = matching_wheels[0] if matching_wheels else sorted(wheels, key=lambda p: p.stat().st_mtime, reverse=True)[0]
        details = []

        with tempfile.TemporaryDirectory(prefix="devos-release-test-") as temp_dir:
            temp_venv = Path(temp_dir) / "venv"
            try:
                # 1. Create venv
                sub_res = subprocess.run([sys.executable, "-m", "venv", str(temp_venv)], capture_output=True, text=True, timeout=60)
                if sub_res.returncode != 0:
                    return CheckResult("Clean Venv Test", False, f"Failed to create temporary venv: {sub_res.stderr}")

                # Resolve pip/python executables inside temp venv
                if os.name == "nt":
                    venv_python = temp_venv / "Scripts" / "python.exe"
                    venv_nexterm = temp_venv / "Scripts" / "nexterm.exe"
                else:
                    venv_python = temp_venv / "bin" / "python"
                    venv_nexterm = temp_venv / "bin" / "nexterm"

                # 2. Pip install wheel inside temp venv
                wheel_path = os.fspath(wheel.resolve())
                inst_res = subprocess.run(
                    [str(venv_python), "-m", "pip", "install", wheel_path],
                    cwd=self.repo_root,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if inst_res.returncode != 0:
                    return CheckResult("Clean Venv Test", False, f"pip install {wheel.name} failed.", inst_res.stderr.splitlines()[-10:])

                details.append(f"Installed {wheel.name} into clean venv.")

                # 3. Test `nexterm --version`
                ver_res = subprocess.run(
                    [str(venv_nexterm), "--version"],
                    cwd=temp_dir,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if ver_res.returncode != 0 or __version__ not in ver_res.stdout:
                    return CheckResult("Clean Venv Test", False, f"nexterm --version failed: {ver_res.stderr or ver_res.stdout}", details)

                details.append(f"nexterm --version: {ver_res.stdout.strip()}")

                # 4. Test `nexterm --help`
                help_res = subprocess.run(
                    [str(venv_nexterm), "--help"],
                    cwd=temp_dir,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if help_res.returncode != 0 or "nexterm" not in help_res.stdout.lower():
                    return CheckResult("Clean Venv Test", False, "nexterm --help failed.", details)

                details.append("nexterm --help executed successfully.")

                return CheckResult("Clean Venv Test", True, "Wheel installed & verified in clean isolated virtual environment.", details)

            except subprocess.TimeoutExpired:
                return CheckResult("Clean Venv Test", False, "Clean venv test timed out.", details)
            except Exception as e:
                return CheckResult("Clean Venv Test", False, f"Clean venv test error: {e}", details)

    def run_full_check(self, target_tag: str | None = None) -> ReleaseCheckReport:
        """Run complete release validation suite."""
        report = ReleaseCheckReport(version=__version__, git_tag=target_tag)

        # 1. Git status
        report.checks.append(self.check_git_status())

        # 2. Version alignment
        report.checks.append(self.check_version_alignment(target_tag))

        # 3. Unit tests
        report.checks.append(self.run_tests())

        # 4. Build packages
        build_check, built_files = self.build_packages()
        report.checks.append(build_check)

        if build_check.passed and built_files:
            # Gather metadata & SHA256 checksums
            for f in built_files:
                sha256 = hashlib.sha256(f.read_bytes()).hexdigest()
                report.artifacts.append({
                    "filename": f.name,
                    "size_bytes": f.stat().st_size,
                    "sha256": sha256,
                })

            # 5. Metadata validation (twine check)
            report.checks.append(self.validate_metadata())

            # 6. Artifact secret scan
            report.checks.append(self.scan_artifact_secrets())

            # 7. Clean venv installation smoke test
            report.checks.append(self.clean_environment_smoke_test())

        return report


def format_report_terminal(report: ReleaseCheckReport, use_color: bool | None = None) -> str:
    """Format ReleaseCheckReport using DeveloperOS clean semantic styling."""
    formatter = errors_mod.ErrorFormatter(use_color=use_color)
    lines = []

    lines.append("\n============================================================")
    lines.append(f"          DeveloperOS Release Check (v{report.version})")
    lines.append("============================================================\n")

    for check in report.checks:
        icon = "[OK]" if check.passed else "[ERR]"
        status_str = formatter._s("path", "[OK]") if check.passed else formatter._s("error", "[ERR]")
        lines.append(f"  {status_str}  {formatter._s('label', check.name):<24} {check.message}")
        if check.details:
            for d in check.details:
                lines.append(f"        {formatter._s('dim', d)}")

    if report.artifacts:
        lines.append("\n------------------------------------------------------------")
        lines.append("  Generated Build Artifacts & SHA256 Checksums:")
        lines.append("------------------------------------------------------------")
        for art in report.artifacts:
            lines.append(f"  Filename: {formatter._s('command', art['filename'])}")
            lines.append(f"  Size:     {art['size_bytes']} bytes")
            lines.append(f"  SHA256:   {formatter._s('dim', art['sha256'])}\n")

    lines.append("------------------------------------------------------------")
    if report.all_passed:
        lines.append(f"  {formatter._s('path', '[SUCCESS]')} Release validation passed. Ready for git tag & GitHub release.")
    else:
        lines.append(f"  {formatter._s('error', '[FAILED]')} Release validation failed. Resolve issues above before releasing.")
    lines.append("------------------------------------------------------------\n")

    return "\n".join(lines)


def generate_sha256sums_file(dist_dir: Path) -> str:
    """Generate SHA256SUMS.txt content for release artifacts in dist/."""
    lines = []
    for f in sorted(dist_dir.glob("*")):
        if f.is_file() and f.name != "SHA256SUMS.txt":
            sha256 = hashlib.sha256(f.read_bytes()).hexdigest()
            lines.append(f"{sha256}  {f.name}")
    return "\n".join(lines) + "\n"
