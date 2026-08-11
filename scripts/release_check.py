#!/usr/bin/env python3
"""Standalone Release Validation Script for NexTerm.

Runs full release validation suite: git status, version alignment, test suite,
python -m build, twine check, artifact secret scan, clean venv installation test,
and SHA256 checksum generation.

Zero PyPI tokens required. Publication uses PyPI Trusted Publishing OIDC.
"""
import sys
from pathlib import Path

# Ensure project root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from nexterm.release import ReleaseValidator, format_report_terminal, generate_sha256sums_file


def main():
    target_tag = sys.argv[1] if len(sys.argv) > 1 else None
    validator = ReleaseValidator(repo_root)
    report = validator.run_full_check(target_tag=target_tag)
    
    print(format_report_terminal(report))

    if report.all_passed:
        # Write SHA256SUMS.txt in dist/
        dist_dir = repo_root / "dist"
        if dist_dir.exists():
            sums_file = dist_dir / "SHA256SUMS.txt"
            sums_file.write_text(generate_sha256sums_file(dist_dir), encoding="utf-8")
            print(f"Generated {sums_file}")
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
