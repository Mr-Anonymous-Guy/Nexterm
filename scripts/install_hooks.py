#!/usr/bin/env python3
"""Git Hook Registration Engine & Installer CLI for DeveloperOS.

Supports:
    python scripts/install_hooks.py --install
    python scripts/install_hooks.py --uninstall
    python scripts/install_hooks.py --status
    python scripts/install_hooks.py --run
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from scripts.pre_push import PrePushValidationEngine, format_terminal_summary, write_markdown_report


def install_hook(root: Path) -> bool:
    git_hooks_dir = root / ".git" / "hooks"
    if not git_hooks_dir.parent.exists():
        print(f"Error: {root} is not a git repository.")
        return False

    git_hooks_dir.mkdir(parents=True, exist_ok=True)
    target_hook = git_hooks_dir / "pre-push"
    source_hook = root / ".githooks" / "pre-push"

    if not source_hook.exists():
        # Fallback inline hook script
        script = f"""#!/bin/sh
if [ "$SKIP_GUARDIAN" = "1" ]; then
    exit 0
fi
"{sys.executable}" "{root / 'scripts' / 'pre_push.py'}" "$@"
"""
        target_hook.write_text(script, encoding="utf-8")
    else:
        target_hook.write_text(source_hook.read_text(encoding="utf-8"), encoding="utf-8")

    if os.name != "nt":
        target_hook.chmod(0o755)

    import subprocess
    subprocess.run(["git", "config", "core.hooksPath", ".githooks"], cwd=root, capture_output=True)

    install_cli(root)

    print(f"[OK] Pre-push hook successfully installed at {target_hook}")
    return True


def install_cli(root: Path) -> bool:
    import subprocess
    print("[INFO] Registering NexTerm CLI entry points (nexterm, workspace, workspcae)...")
    res = subprocess.run([sys.executable, "-m", "pip", "install", "-e", str(root)], capture_output=True, text=True)
    if res.returncode == 0:
        print("[OK] NexTerm CLI entry points registered successfully.")
        return True
    else:
        print(f"[ERR] Failed to register CLI entry points: {res.stderr}")
        return False


def uninstall_hook(root: Path) -> bool:
    target_hook = root / ".git" / "hooks" / "pre-push"
    if target_hook.exists():
        target_hook.unlink()
        print("[OK] Pre-push hook successfully uninstalled.")
        return True
    print("[NOTICE] No pre-push hook was installed.")
    return True


def check_status(root: Path) -> bool:
    target_hook = root / ".git" / "hooks" / "pre-push"
    if target_hook.exists():
        print(f"Pre-Push Hook Status: [INSTALLED] at {target_hook}")
        return True
    else:
        print("Pre-Push Hook Status: [NOT INSTALLED]")
        return False


def main():
    parser = argparse.ArgumentParser(description="DeveloperOS Git Hook Registration Engine")
    parser.add_argument("--install", action="store_true", help="Install pre-push hook into .git/hooks/")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall pre-push hook")
    parser.add_argument("--status", action="store_true", help="Check hook installation status")
    parser.add_argument("--run", action="store_true", help="Run 16-stage validation pipeline manually")

    args = parser.parse_args()

    if args.install:
        success = install_hook(repo_root)
        sys.exit(0 if success else 1)
    elif args.uninstall:
        success = uninstall_hook(repo_root)
        sys.exit(0 if success else 1)
    elif args.status:
        check_status(repo_root)
        sys.exit(0)
    elif args.run:
        engine = PrePushValidationEngine(repo_root)
        report = engine.run_full_pipeline()
        print(format_terminal_summary(report))
        write_markdown_report(report, repo_root / "pre_push_report.md")
        sys.exit(0 if report.all_passed else 1)
    else:
        # Default behavior: install hook
        install_hook(repo_root)


if __name__ == "__main__":
    main()
