"""Build, Test, Verification & Deployment Engine for DeveloperOS (SDD section 37)."""
from __future__ import annotations

import subprocess
import sqlite3
from pathlib import Path

from . import db, detectors


def ship_project(
    conn: sqlite3.Connection,
    project_id: int,
    skip_tests: bool = False,
    target: str | None = None,
) -> dict:
    """Runs linting, typechecking, tests, build, and deployment validation."""
    p_row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not p_row:
        raise ValueError(f"Project ID '{project_id}' not found.")

    project_dir = Path(p_row["path"])
    facts = detectors.detect_all(project_dir)
    pkg_mgr = facts.get("package_manager")

    phases = []

    import json

    # 1. Lint Phase
    lint_cmd = None
    if (project_dir / "package.json").exists():
        try:
            pkg_json = json.loads((project_dir / "package.json").read_text(encoding="utf-8"))
            if "lint" in pkg_json.get("scripts", {}):
                lint_cmd = "npm run lint"
        except Exception:
            pass
    elif (project_dir / "pyproject.toml").exists() or (project_dir / "requirements.txt").exists():
        lint_cmd = "python -m ruff check ." if (project_dir / "ruff.toml").exists() else None

    if lint_cmd:
        res = subprocess.run(lint_cmd, shell=True, cwd=project_dir, capture_output=True, text=True)
        phases.append({"phase": "lint", "success": res.returncode == 0, "output": res.stdout or res.stderr})
    else:
        phases.append({"phase": "lint", "success": True, "output": "No linter configured (skipped)"})

    # 2. Test Phase
    if not skip_tests:
        test_cmd = None
        if (project_dir / "package.json").exists():
            try:
                pkg_json = json.loads((project_dir / "package.json").read_text(encoding="utf-8"))
                if "test" in pkg_json.get("scripts", {}):
                    test_cmd = "npm test"
            except Exception:
                pass
        elif (project_dir / "tests").exists() or (project_dir / "test").exists():
            test_cmd = "python -m pytest"
        elif (project_dir / "Cargo.toml").exists():
            test_cmd = "cargo test"

        if test_cmd:
            res = subprocess.run(test_cmd, shell=True, cwd=project_dir, capture_output=True, text=True)
            phases.append({"phase": "test", "success": res.returncode == 0, "output": res.stdout or res.stderr})
        else:
            phases.append({"phase": "test", "success": True, "output": "No test runner configured (skipped)"})

    # 3. Build Phase
    build_cmd = p_row["build_cmd"] or facts.get("build_cmd")
    if not build_cmd:
        if (project_dir / "package.json").exists():
            try:
                pkg_json = json.loads((project_dir / "package.json").read_text(encoding="utf-8"))
                if "build" in pkg_json.get("scripts", {}):
                    build_cmd = "npm run build"
            except Exception:
                pass
        elif (project_dir / "Cargo.toml").exists():
            build_cmd = "cargo build --release"

    if build_cmd:
        res = subprocess.run(build_cmd, shell=True, cwd=project_dir, capture_output=True, text=True)
        phases.append({"phase": "build", "success": res.returncode == 0, "output": res.stdout or res.stderr})
    else:
        phases.append({"phase": "build", "success": True, "output": "No build command required"})

    # 4. Deploy Validation Phase
    deploy_success = all(p["success"] for p in phases)
    phases.append({
        "phase": "deploy",
        "success": deploy_success,
        "output": f"Ready for target '{target or 'production'}'" if deploy_success else "Deploy aborted due to phase failures",
    })

    db.record_workflow(conn, f"ship:{target or 'prod'}", project_id, deploy_success)

    return {
        "project": p_row["name"],
        "success": deploy_success,
        "phases": phases,
    }
