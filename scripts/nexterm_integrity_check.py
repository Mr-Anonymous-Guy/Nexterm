#!/usr/bin/env python3
"""
NexTerm Repository Integrity & Rename Audit

Purpose
-------
Perform a complete pre-push integrity audit after the project was renamed
from WorkSpaceX/workspace to NexTerm.

This script is intentionally read-only.

It checks:

1. Repository structure
2. Stale WorkSpaceX/workspace references
3. Python package naming
4. pyproject.toml
5. CLI entry points
6. Git hooks
7. GitHub Actions workflows
8. PyPI release configuration
9. Documentation
10. Tests
11. Scripts
12. Configuration files
13. Generated artifacts
14. Git status
15. Package build metadata
16. Release workflow consistency
17. Hook installation
18. Required NexTerm files
19. Accidental old directories/files
20. General repository hygiene

Exit code:
    0 = PASS
    1 = FAIL

This script MUST be safe to run repeatedly.
It MUST NOT modify project files.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable


# ============================================================
# CONFIGURATION
# ============================================================

PROJECT_NAME = "NexTerm"

# Names that MUST NOT remain in the new project unless explicitly
# documented as historical references.
STALE_NAMES = [
    "WorkSpaceX",
    "WorkspaceX",
    "workspaceX",
    "Work_SpaceX",
    "work_spacex",
    "work-space-x",
]

# "workspace" alone is intentionally treated separately because it
# can legitimately occur as a generic English word.
GENERIC_STALE_NAMES = [
    "workspace",
]

EXPECTED_PACKAGE_NAMES = [
    "nexterm",
]

EXPECTED_CLI_NAMES = [
    "nexterm",
]

REQUIRED_FILES = [
    "pyproject.toml",
    "README.md",
    "LICENSE",
]

EXPECTED_DIRECTORIES = [
    "tests",
    "scripts",
    ".github",
]

ROOT = Path(__file__).resolve().parents[1]

WORKFLOW_DIRECTORY = ROOT / ".github" / "workflows"

HOOK_DIRECTORIES = [
    ROOT / ".githooks",
    ROOT / ".git" / "hooks",
]

TEXT_EXTENSIONS = {
    ".py",
    ".pyw",
    ".md",
    ".txt",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".ini",
    ".cfg",
    ".conf",
    ".sh",
    ".ps1",
    ".bat",
    ".cmd",
    ".xml",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".css",
    ".html",
    ".rst",
    ".env",
}

IGNORED_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    "node_modules",
    ".idea",
    ".vscode",
    ".eggs",
    "site-packages",
}

IGNORED_FILES = {
    ".DS_Store",
}

# Generated/build directories that should generally not be committed.
GENERATED_DIRECTORIES = {
    "dist",
    "build",
    "*.egg-info",
}

# Files that may legitimately contain historical names.
# Keep this list extremely small.
ALLOWED_STALE_REFERENCE_FILES = {
    "CHANGELOG.md",
}


# ============================================================
# RESULT SYSTEM
# ============================================================

class Audit:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.failures: list[str] = []
        self.warnings_list: list[str] = []

    def ok(self, message: str) -> None:
        self.passed += 1
        print(f"  [PASS] {message}")

    def fail(self, message: str) -> None:
        self.failed += 1
        self.failures.append(message)
        print(f"  [FAIL] {message}")

    def warn(self, message: str) -> None:
        self.warnings += 1
        self.warnings_list.append(message)
        print(f"  [WARN] {message}")

    def section(self, title: str) -> None:
        print()
        print("=" * 72)
        print(title)
        print("=" * 72)


audit = Audit()


# ============================================================
# BASIC HELPERS
# ============================================================

ROOT = Path(__file__).resolve().parents[1]


def run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    timeout: int = 30,
) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        return (
            result.returncode,
            result.stdout.strip(),
            result.stderr.strip(),
        )
    except FileNotFoundError:
        return 127, "", f"Command not found: {command[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", "Command timed out"


def is_ignored(path: Path) -> bool:
    parts = set(path.parts)

    if parts.intersection(IGNORED_DIRECTORIES):
        return True

    if path.name in IGNORED_FILES:
        return True

    return False


def is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS


def iter_repository_files() -> Iterable[Path]:
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue

        if is_ignored(path):
            continue

        yield path


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


# ============================================================
# 1. REPOSITORY ROOT
# ============================================================

def check_repository() -> None:
    audit.section("1. REPOSITORY")

    code, out, err = run(["git", "rev-parse", "--show-toplevel"])

    if code != 0:
        audit.fail("Current directory is not a Git repository.")
        return

    repo_root = Path(out).resolve()

    if repo_root != ROOT.resolve():
        audit.fail(
            f"Repository root mismatch: expected {ROOT}, got {repo_root}"
        )
    else:
        audit.ok("Git repository root is correct.")

    code, branch, _ = run(["git", "branch", "--show-current"])

    if code == 0 and branch:
        audit.ok(f"Current branch: {branch}")
    else:
        audit.warn("Could not determine current Git branch.")


# ============================================================
# 2. REQUIRED FILES
# ============================================================

def check_required_files() -> None:
    audit.section("2. REQUIRED PROJECT FILES")

    for relative in REQUIRED_FILES:
        path = ROOT / relative

        if path.exists():
            audit.ok(relative)
        else:
            audit.fail(f"Missing required file: {relative}")


# ============================================================
# 3. REQUIRED DIRECTORIES
# ============================================================

def check_required_directories() -> None:
    audit.section("3. REQUIRED DIRECTORIES")

    for relative in EXPECTED_DIRECTORIES:
        path = ROOT / relative

        if path.exists() and path.is_dir():
            audit.ok(relative)
        else:
            audit.warn(f"Expected directory missing: {relative}")


# ============================================================
# 4. STALE NAME SCAN
# ============================================================

def check_stale_names() -> None:
    audit.section("4. STALE PROJECT NAME SCAN")

    found = []

    for path in iter_repository_files():
        if not is_text_file(path):
            continue

        text = read_text(path)

        for stale in STALE_NAMES:
            if stale.lower() in text.lower():
                relative = path.relative_to(ROOT)

                if relative.name == "nexterm_integrity_check.py":
                    continue

                if relative.name in ALLOWED_STALE_REFERENCE_FILES:
                    audit.warn(
                        f"Historical stale name found in allowed file: "
                        f"{relative} -> {stale}"
                    )
                    continue

                found.append((relative, stale))

    if not found:
        audit.ok("No stale WorkSpaceX/work_spacex references found.")
    else:
        for path, stale in found:
            audit.fail(
                f"Stale project name '{stale}' found in {path}"
            )


# ============================================================
# 5. GENERIC WORKSPACE REFERENCES
# ============================================================

def check_generic_workspace_references() -> None:
    audit.section("5. GENERIC WORKSPACE REFERENCE REVIEW")

    found = []

    for path in iter_repository_files():
        if not is_text_file(path):
            continue

        text = read_text(path)

        # Detect identifiers, package names, imports, commands, etc.
        patterns = [
            r"\bworkspace\b",
            r"\bworkspace_[A-Za-z0-9_]+\b",
            r"\bworkspace-[A-Za-z0-9-]+\b",
        ]

        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                found.append(path)
                break

    unique = sorted(set(found))

    if not unique:
        audit.ok("No suspicious generic workspace references found.")
    else:
        for path in unique:
            relative = path.relative_to(ROOT)

            # Generic English usage is not necessarily an error.
            audit.warn(
                f"Review generic workspace reference manually: {relative}"
            )


# ============================================================
# 6. PACKAGE DIRECTORY
# ============================================================

def check_package_directory() -> None:
    audit.section("6. PYTHON PACKAGE")

    nexterm = ROOT / "nexterm"

    if nexterm.exists() and nexterm.is_dir():
        audit.ok("nexterm package directory exists.")
    else:
        audit.fail("Missing nexterm/ package directory.")

    stale_dirs = [
        ROOT / "workspace",
        ROOT / "work_spacex",
        ROOT / "workspace_x",
        ROOT / "WorkSpaceX",
    ]

    for directory in stale_dirs:
        if directory.exists():
            audit.fail(
                f"Old package/project directory still exists: "
                f"{directory.relative_to(ROOT)}"
            )


# ============================================================
# 7. PYPROJECT
# ============================================================

def check_pyproject() -> None:
    audit.section("7. PYPROJECT.TOML")

    path = ROOT / "pyproject.toml"

    if not path.exists():
        audit.fail("pyproject.toml does not exist.")
        return

    text = read_text(path)

    # Package name
    match = re.search(
        r'(?m)^\s*name\s*=\s*["\']([^"\']+)["\']',
        text,
    )

    if not match:
        audit.fail("Could not find [project].name in pyproject.toml.")
    else:
        package_name = match.group(1)

        if package_name.lower() in EXPECTED_PACKAGE_NAMES:
            audit.ok(f"PyPI package name: {package_name}")
        else:
            audit.fail(
                f"Unexpected package name: {package_name}. "
                f"Expected NexTerm package name."
            )

    # CLI entry point
    if re.search(r"\bnexterm\s*=", text):
        audit.ok("NexTerm CLI entry point detected.")
    else:
        audit.fail("NexTerm CLI entry point not found.")

    # Stale entry point names
    for stale in [
        "workspacex",
        "work_spacex",
    ]:
        if re.search(rf"\b{re.escape(stale)}\s*=", text, re.IGNORECASE):
            audit.fail(
                f"Old CLI/package entry point still exists: {stale}"
            )


# ============================================================
# 8. WORKFLOW CHECK
# ============================================================

def check_workflows() -> None:
    audit.section("8. GITHUB ACTIONS WORKFLOWS")

    if not WORKFLOW_DIRECTORY.exists():
        audit.fail(".github/workflows directory is missing.")
        return

    workflows = list(WORKFLOW_DIRECTORY.glob("*.yml"))
    workflows += list(WORKFLOW_DIRECTORY.glob("*.yaml"))

    if not workflows:
        audit.fail("No GitHub Actions workflows found.")
        return

    for workflow in workflows:
        audit.ok(
            f"Workflow found: {workflow.relative_to(ROOT)}"
        )

        text = read_text(workflow)

        # Old names
        for stale in STALE_NAMES:
            if stale.lower() in text.lower():
                audit.fail(
                    f"Stale name '{stale}' found in workflow "
                    f"{workflow.relative_to(ROOT)}"
                )

        # NexTerm references
        if "nexterm" in text.lower():
            audit.ok(
                f"NexTerm reference present: "
                f"{workflow.relative_to(ROOT)}"
            )

    release = (
        WORKFLOW_DIRECTORY / "release.yml"
    )

    if release.exists():
        audit.ok("release.yml exists.")
    else:
        audit.warn("release.yml not found.")

    ci = (
        WORKFLOW_DIRECTORY / "ci.yml"
    )

    if ci.exists():
        audit.ok("ci.yml exists.")
    else:
        audit.warn("ci.yml not found.")


# ============================================================
# 9. RELEASE WORKFLOW
# ============================================================

def check_release_workflow() -> None:
    audit.section("9. RELEASE WORKFLOW")

    release = WORKFLOW_DIRECTORY / "release.yml"

    if not release.exists():
        audit.warn("No release.yml found.")
        return

    text = read_text(release)

    required_patterns = {
        "PyPI publish action": "gh-action-pypi-publish",
        "OIDC permission": "id-token: write",
        "PyPI environment": "pypi",
    }

    for name, pattern in required_patterns.items():
        if pattern.lower() in text.lower():
            audit.ok(name)
        else:
            audit.fail(
                f"Release workflow missing {name}: {pattern}"
            )

    if "work_spacex" in text.lower():
        audit.fail(
            "release.yml still contains old package name work_spacex."
        )

    if "workspace" in text.lower():
        audit.warn(
            "release.yml contains generic 'workspace'; review manually."
        )


# ============================================================
# 10. PYPI METADATA
# ============================================================

def check_pypi_metadata() -> None:
    audit.section("10. PYPI / PACKAGE METADATA")

    path = ROOT / "pyproject.toml"

    if not path.exists():
        return

    text = read_text(path)

    checks = {
        "README metadata": "readme",
        "license metadata": "license",
        "author metadata": "authors",
        "project URLs": "urls",
    }

    for name, pattern in checks.items():
        if pattern.lower() in text.lower():
            audit.ok(name)
        else:
            audit.warn(f"{name} may be missing.")


# ============================================================
# 11. HOOK CHECK
# ============================================================

def check_hooks() -> None:
    audit.section("11. GIT HOOKS")

    githooks = ROOT / ".githooks"

    if not githooks.exists():
        audit.warn(".githooks directory does not exist.")
        return

    hooks = list(githooks.iterdir())

    if not hooks:
        audit.warn(".githooks directory is empty.")
        return

    for hook in hooks:
        if not hook.is_file():
            continue

        audit.ok(
            f"Hook source exists: {hook.relative_to(ROOT)}"
        )

        text = read_text(hook)

        if "workspace" in text.lower():
            audit.warn(
                f"Generic workspace reference in hook: "
                f"{hook.relative_to(ROOT)}"
            )

        for stale in STALE_NAMES:
            if stale.lower() in text.lower():
                audit.fail(
                    f"Old name '{stale}' found in hook: "
                    f"{hook.relative_to(ROOT)}"
                )

    # pre-push hook should exist somewhere in hook architecture
    pre_push_candidates = [
        githooks / "pre-push",
        githooks / "pre-push.py",
        githooks / "pre_push.py",
        githooks / "pre-push.ps1",
        githooks / "pre_push.ps1",
    ]

    if any(path.exists() for path in pre_push_candidates):
        audit.ok("Pre-push hook implementation found.")
    else:
        audit.warn(
            "No recognizable pre-push hook found in .githooks."
        )


# ============================================================
# 12. GIT CONFIGURATION
# ============================================================

def check_git_hooks_config() -> None:
    audit.section("12. GIT HOOK CONFIGURATION")

    code, out, err = run(
        ["git", "config", "--get", "core.hooksPath"]
    )

    if code != 0 or not out:
        audit.warn(
            "core.hooksPath is not configured."
        )
        return

    hooks_path = out.strip()

    audit.ok(
        f"Git hooks path configured: {hooks_path}"
    )

    if "githooks" not in hooks_path.lower():
        audit.warn(
            f"core.hooksPath does not appear to point to .githooks: "
            f"{hooks_path}"
        )


# ============================================================
# 13. HOOK INSTALLATION SCRIPTS
# ============================================================

def check_hook_installers() -> None:
    audit.section("13. HOOK INSTALLATION")

    candidates = [
        ROOT / "scripts" / "install_hooks.py",
        ROOT / "scripts" / "install_hooks.ps1",
        ROOT / "scripts" / "install-hooks.py",
        ROOT / "scripts" / "install-hooks.ps1",
    ]

    found = False

    for path in candidates:
        if path.exists():
            found = True
            audit.ok(
                f"Hook installer found: {path.relative_to(ROOT)}"
            )

            text = read_text(path)

            if "core.hookspath" in text.lower():
                audit.ok(
                    "Hook installer configures core.hooksPath."
                )

    if not found:
        audit.warn(
            "No dedicated hook installation script detected."
        )


# ============================================================
# 14. TEST SUITE
# ============================================================

def check_tests() -> None:
    audit.section("14. TEST SUITE")

    tests = ROOT / "tests"

    if not tests.exists():
        audit.fail("tests/ directory does not exist.")
        return

    test_files = list(tests.rglob("test_*.py"))

    if not test_files:
        audit.fail("No Python test files found.")
    else:
        audit.ok(
            f"{len(test_files)} Python test files found."
        )

    command_test = tests / "test_commands.py"

    if command_test.exists():
        audit.ok("Command verification test exists.")
    else:
        audit.warn("tests/test_commands.py not found.")

    pre_push_test = tests / "test_pre_push.py"

    if pre_push_test.exists():
        audit.ok("Pre-push test exists.")
    else:
        audit.warn("tests/test_pre_push.py not found.")


# ============================================================
# 15. COMMAND DOCUMENTATION
# ============================================================

def check_command_docs() -> None:
    audit.section("15. COMMAND DOCUMENTATION")

    candidates = [
        ROOT / "Commands.md",
        ROOT / "COMMANDS.md",
        ROOT / "Docs" / "COMMANDS.md",
        ROOT / "docs" / "COMMANDS.md",
    ]

    found = False

    for path in candidates:
        if path.exists():
            found = True
            audit.ok(
                f"Command specification found: "
                f"{path.relative_to(ROOT)}"
            )

            text = read_text(path)

            if "nexterm" not in text.lower():
                audit.fail(
                    f"Command specification does not contain NexTerm: "
                    f"{path.relative_to(ROOT)}"
                )

            for stale in STALE_NAMES:
                if stale.lower() in text.lower():
                    audit.fail(
                        f"Stale name '{stale}' found in command specification."
                    )

    if not found:
        audit.warn(
            "No Commands.md/COMMANDS.md specification found."
        )


# ============================================================
# 16. README
# ============================================================

def check_readme() -> None:
    audit.section("16. README")

    readme = ROOT / "README.md"

    if not readme.exists():
        audit.fail("README.md missing.")
        return

    text = read_text(readme)

    if "nexterm" in text.lower():
        audit.ok("README references NexTerm.")
    else:
        audit.fail(
            "README does not appear to reference NexTerm."
        )

    for stale in STALE_NAMES:
        if stale.lower() in text.lower():
            audit.fail(
                f"README contains stale name: {stale}"
            )


# ============================================================
# 17. SCRIPTS
# ============================================================

def check_scripts() -> None:
    audit.section("17. SCRIPTS")

    scripts = ROOT / "scripts"

    if not scripts.exists():
        audit.warn("scripts directory does not exist.")
        return

    for path in scripts.rglob("*"):
        if not path.is_file():
            continue

        if not is_text_file(path):
            continue

        if path.name == "nexterm_integrity_check.py":
            continue

        text = read_text(path)

        for stale in STALE_NAMES:
            if stale.lower() in text.lower():
                audit.fail(
                    f"Stale name '{stale}' found in "
                    f"{path.relative_to(ROOT)}"
                )


# ============================================================
# 18. TEST FILE STALE REFERENCES
# ============================================================

def check_test_references() -> None:
    audit.section("18. TEST REFERENCES")

    tests = ROOT / "tests"

    if not tests.exists():
        return

    for path in tests.rglob("*"):
        if not path.is_file() or not is_text_file(path):
            continue

        text = read_text(path)

        for stale in STALE_NAMES:
            if stale.lower() in text.lower():
                audit.fail(
                    f"Stale name '{stale}' found in test: "
                    f"{path.relative_to(ROOT)}"
                )


# ============================================================
# 19. GENERATED ARTIFACTS
# ============================================================

def check_generated_artifacts() -> None:
    audit.section("19. GENERATED ARTIFACTS")

    dist = ROOT / "dist"

    if not dist.exists():
        audit.ok("dist/ does not exist yet.")
        return

    artifacts = list(dist.iterdir())

    if not artifacts:
        audit.ok("dist/ is empty.")
        return

    for artifact in artifacts:
        name = artifact.name.lower()

        if "workspace" in name or "work_spacex" in name:
            audit.fail(
                f"Stale distribution artifact detected: {artifact.name}"
            )
        elif "nexterm" in name:
            audit.ok(
                f"NexTerm artifact detected: {artifact.name}"
            )
        else:
            audit.warn(
                f"Unrecognized distribution artifact: {artifact.name}"
            )


# ============================================================
# 20. GIT STATUS
# ============================================================

def check_git_status() -> None:
    audit.section("20. GIT STATUS")

    code, out, err = run(
        ["git", "status", "--short"]
    )

    if code != 0:
        audit.fail("Unable to determine Git status.")
        return

    if not out:
        audit.ok("Working tree is clean.")
        return

    audit.warn(
        "Working tree contains changes that will be included/excluded "
        "according to Git staging state."
    )

    print()
    print(out)


# ============================================================
# 21. STAGED FILE AUDIT
# ============================================================

def check_staged_files() -> None:
    audit.section("21. STAGED FILE AUDIT")

    code, out, err = run(
        [
            "git",
            "diff",
            "--cached",
            "--name-only",
        ]
    )

    if code != 0:
        audit.warn("Unable to inspect staged files.")
        return

    if not out:
        audit.warn("No staged files detected.")
        return

    staged = out.splitlines()

    for filename in staged:
        lower = filename.lower()

        if any(
            stale.lower() in lower
            for stale in STALE_NAMES
        ):
            audit.fail(
                f"Staged file contains stale project name: {filename}"
            )

    audit.ok(
        f"Audited {len(staged)} staged file(s)."
    )


# ============================================================
# 22. SECRET FILE CHECK
# ============================================================

def check_sensitive_files() -> None:
    audit.section("22. SENSITIVE FILE CHECK")

    suspicious = {
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        "credentials.json",
        "service-account.json",
    }

    code, out, err = run(
        [
            "git",
            "ls-files",
        ]
    )

    if code != 0:
        audit.warn("Unable to inspect tracked files.")
        return

    tracked = out.splitlines()

    for filename in tracked:
        name = Path(filename).name.lower()

        if name in suspicious:
            audit.fail(
                f"Potential sensitive file tracked by Git: {filename}"
            )

    audit.ok("Sensitive-file tracking audit completed.")


# ============================================================
# 23. PACKAGE BUILD VALIDATION
# ============================================================

def check_package_build() -> None:
    audit.section("23. PACKAGE BUILD VALIDATION")

    pyproject = ROOT / "pyproject.toml"

    if not pyproject.exists():
        audit.fail("Cannot validate package build without pyproject.toml.")
        return

    # Only run build if build module is installed.
    code, out, err = run(
        [
            sys.executable,
            "-m",
            "build",
            "--sdist",
            "--wheel",
        ],
        timeout=180,
    )

    if code == 0:
        audit.ok("Python package build succeeded.")
    elif code == 127:
        audit.warn(
            "Python build module is not installed; "
            "package build could not be tested."
        )
    else:
        audit.fail(
            "Python package build failed."
        )

        if err:
            print(err)


# ============================================================
# 24. IMPORT VALIDATION
# ============================================================

def check_import() -> None:
    audit.section("24. PACKAGE IMPORT")

    code, out, err = run(
        [
            sys.executable,
            "-c",
            "import nexterm; print(getattr(nexterm, '__version__', 'unknown'))",
        ],
    )

    if code == 0:
        audit.ok(
            f"nexterm Python package imports successfully: {out}"
        )
    else:
        audit.fail(
            "Unable to import nexterm package."
        )

        if err:
            print(err)


# ============================================================
# 25. CLI VALIDATION
# ============================================================

def check_cli() -> None:
    audit.section("25. NEXTERM CLI")

    code, out, err = run(
        [
            sys.executable,
            "-m",
            "nexterm",
            "--version",
        ],
    )

    if code == 0:
        audit.ok(
            f"NexTerm CLI --version works: {out}"
        )
    else:
        audit.fail(
            "NexTerm CLI --version failed."
        )

        if err:
            print(err)


# ============================================================
# 26. PYPROJECT OLD REFERENCES
# ============================================================

def check_pyproject_stale_refs() -> None:
    audit.section("26. PYPROJECT STALE REFERENCES")

    path = ROOT / "pyproject.toml"

    if not path.exists():
        return

    text = read_text(path)

    for stale in STALE_NAMES:
        if stale.lower() in text.lower():
            audit.fail(
                f"Old project name '{stale}' remains in pyproject.toml."
            )

    audit.ok("pyproject.toml stale-name scan completed.")


# ============================================================
# 27. GLOBAL STALE FILE NAMES
# ============================================================

def check_stale_filenames() -> None:
    audit.section("27. STALE FILE/DIRECTORY NAMES")

    found = []

    for path in ROOT.rglob("*"):
        if is_ignored(path):
            continue

        relative = path.relative_to(ROOT)

        for stale in STALE_NAMES:
            if stale.lower() in str(relative).lower():
                found.append(relative)
                break

    if not found:
        audit.ok("No stale filenames/directories detected.")
    else:
        for path in sorted(set(found)):
            audit.fail(
                f"Stale filename/directory: {path}"
            )


# ============================================================
# 28. GITHUB ACTIONS SYNTAX / REFERENCE AUDIT
# ============================================================

def check_actions_reference_integrity() -> None:
    audit.section("28. GITHUB ACTIONS REFERENCE INTEGRITY")

    if not WORKFLOW_DIRECTORY.exists():
        return

    workflows = list(WORKFLOW_DIRECTORY.glob("*.yml"))
    workflows += list(WORKFLOW_DIRECTORY.glob("*.yaml"))

    for workflow in workflows:
        text = read_text(workflow)

        # Detect references to files that clearly do not exist.
        for match in re.findall(
            r"(?:python|bash|pwsh|powershell|sh)\s+([A-Za-z0-9_./\\-]+\.(?:py|sh|ps1))",
            text,
            re.IGNORECASE,
        ):
            referenced = ROOT / match.replace("\\", "/")

            if not referenced.exists():
                audit.fail(
                    f"{workflow.relative_to(ROOT)} references missing script: "
                    f"{match}"
                )

    audit.ok("GitHub Actions script-reference audit completed.")


# ============================================================
# 29. COMMAND SPECIFICATION CONSISTENCY
# ============================================================

def check_command_spec_consistency() -> None:
    audit.section("29. COMMAND SPECIFICATION CONSISTENCY")

    candidates = [
        ROOT / "Commands.md",
        ROOT / "COMMANDS.md",
        ROOT / "Docs" / "COMMANDS.md",
        ROOT / "docs" / "COMMANDS.md",
    ]

    command_doc = None

    for path in candidates:
        if path.exists():
            command_doc = path
            break

    if command_doc is None:
        audit.warn("No command specification available.")
        return

    text = read_text(command_doc).lower()

    required_commands = [
        "nexterm",
        "pwd",
        "ls",
        "cd",
        "npm",
        "python",
        "git",
        "docker",
        "projects",
        "find",
        "search",
        "open",
        "start",
        "status",
        "doctor",
        "tag",
        "register",
        "unregister",
        "rescan",
        "index",
        "stack",
        "ai",
        "ask",
        "explain",
        "fix",
        "guardian",
        "release",
    ]

    for command in required_commands:
        if command in text:
            audit.ok(
                f"Command documented: {command}"
            )
        else:
            audit.warn(
                f"Command not found in specification: {command}"
            )


# ============================================================
# 30. PYPI RELEASE CONSISTENCY
# ============================================================

def check_release_consistency() -> None:
    audit.section("30. RELEASE CONSISTENCY")

    pyproject = ROOT / "pyproject.toml"
    release = WORKFLOW_DIRECTORY / "release.yml"

    if not pyproject.exists() or not release.exists():
        audit.warn(
            "Cannot perform complete release consistency check."
        )
        return

    pyproject_text = read_text(pyproject)
    release_text = read_text(release)

    if "nexterm" in pyproject_text.lower():
        audit.ok("pyproject.toml uses NexTerm naming.")
    else:
        audit.fail(
            "pyproject.toml does not appear to use NexTerm naming."
        )

    if "nexterm" in release_text.lower():
        audit.ok("release.yml references NexTerm.")
    else:
        audit.warn(
            "release.yml does not explicitly reference NexTerm."
        )

    if "work_spacex" in release_text.lower():
        audit.fail(
            "release.yml still contains work_spacex."
        )

    if "workspacex" in release_text.lower():
        audit.fail(
            "release.yml still contains WorkSpaceX."
        )


# ============================================================
# 31. FINAL REPORT
# ============================================================

def print_report() -> int:
    print()
    print()
    print("=" * 72)
    print("NEXTERM REPOSITORY INTEGRITY AUDIT")
    print("=" * 72)

    print()
    print(f"Repository: {ROOT}")
    print(f"Project:    {PROJECT_NAME}")

    print()
    print("RESULTS")
    print("-" * 72)
    print(f"PASS:     {audit.passed}")
    print(f"FAIL:     {audit.failed}")
    print(f"WARNINGS: {audit.warnings}")

    total = audit.passed + audit.failed

    if total:
        readiness = (audit.passed / total) * 100
    else:
        readiness = 0

    print(f"READINESS: {readiness:.1f}%")

    if audit.failures:
        print()
        print("=" * 72)
        print("CRITICAL FAILURES")
        print("=" * 72)

        for failure in audit.failures:
            print(f"[FAIL] {failure}")

    if audit.warnings_list:
        print()
        print("=" * 72)
        print("WARNINGS")
        print("=" * 72)

        for warning in audit.warnings_list:
            print(f"[WARN] {warning}")

    print()
    print("=" * 72)

    if audit.failed:
        print("PRE-PUSH DECISION: BLOCK")
        print("=" * 72)
        print()
        print(
            "NexTerm contains repository integrity failures."
        )
        print(
            "Fix the failures before pushing to GitHub."
        )
        return 1

    print("PRE-PUSH DECISION: PASS")
    print("=" * 72)
    print()
    print(
        "No critical repository integrity failures detected."
    )

    return 0


# ============================================================
# MAIN
# ============================================================

def main() -> int:
    print("=" * 72)
    print("NEXTERM — PRE-PUSH REPOSITORY INTEGRITY CHECK")
    print("=" * 72)

    print()
    print(
        "This audit is READ-ONLY."
    )

    print(
        "No project files will be modified."
    )

    check_repository()
    check_required_files()
    check_required_directories()
    check_stale_names()
    check_generic_workspace_references()
    check_package_directory()
    check_pyproject()
    check_pyproject_stale_refs()
    check_workflows()
    check_release_workflow()
    check_pypi_metadata()
    check_hooks()
    check_git_hooks_config()
    check_hook_installers()
    check_tests()
    check_command_docs()
    check_readme()
    check_scripts()
    check_test_references()
    check_generated_artifacts()
    check_git_status()
    check_staged_files()
    check_sensitive_files()
    check_package_build()
    check_import()
    check_cli()
    check_stale_filenames()
    check_actions_reference_integrity()
    check_command_spec_consistency()
    check_release_consistency()

    return print_report()


if __name__ == "__main__":
    raise SystemExit(main())