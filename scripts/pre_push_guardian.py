#!/usr/bin/env python3
"""Standalone Pre-Push Guardian Script for DeveloperOS.

Executed automatically by `.git/hooks/pre-push` before any git push reaches the remote.
Runs full repository defense checks: hygiene, diff secret scan, tests, build, metadata,
artifact content scan, and clean venv smoke test.
"""
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from nexterm.guardian import GuardianEngine, format_guardian_report_terminal


def main():
    if os.environ.get("SKIP_GUARDIAN") == "1":
        print("[GUARDIAN NOTICE] SKIP_GUARDIAN=1 detected. Bypassing pre-push checks.")
        sys.exit(0)

    engine = GuardianEngine(repo_root)
    report = engine.run_full_guardian_check()

    print(format_guardian_report_terminal(report))

    if report.all_passed:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
