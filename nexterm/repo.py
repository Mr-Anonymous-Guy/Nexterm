"""Repository management and fresh-clone bootstrap workflow for DeveloperOS (SDD section 9)."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
import sqlite3

from . import db, scanner, detectors


def clone_repository(conn: sqlite3.Connection, repo_url: str, dest_dir: Path | None = None) -> dict:
    """Clones a Git repository and performs full automated workspace bootstrap."""
    if dest_dir is None:
        repo_name = repo_url.rstrip("/").split("/")[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]
        dest_dir = Path.cwd() / repo_name

    dest_dir = dest_dir.resolve()
    if dest_dir.exists() and any(dest_dir.iterdir()):
        raise FileExistsError(f"Target directory '{dest_dir}' already exists and is not empty.")

    # 1. Git Clone
    cmd = ["git", "clone", repo_url, str(dest_dir)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Git clone failed: {res.stderr}")

    # 2. Index project
    scan_res = scanner.full_scan(conn, [dest_dir], max_depth=2)
    project_row = conn.execute("SELECT * FROM projects WHERE path = ?", (str(dest_dir),)).fetchone()

    actions_taken = ["cloned repository", "indexed workspace"]

    # 3. Auto-install dependencies if present
    if project_row:
        facts = detectors.detect_all(dest_dir)
        pkg_mgr = facts.get("package_manager")
        if pkg_mgr == "npm" and (dest_dir / "package.json").exists():
            subprocess.run(["npm", "install"], cwd=dest_dir, capture_output=True)
            actions_taken.append("installed npm dependencies")
        elif pkg_mgr == "pip" and (dest_dir / "requirements.txt").exists():
            subprocess.run(["pip", "install", "-r", "requirements.txt"], cwd=dest_dir, capture_output=True)
            actions_taken.append("installed pip dependencies")
        elif pkg_mgr == "poetry" and (dest_dir / "pyproject.toml").exists():
            subprocess.run(["poetry", "install"], cwd=dest_dir, capture_output=True)
            actions_taken.append("installed poetry dependencies")
        elif pkg_mgr == "cargo" and (dest_dir / "Cargo.toml").exists():
            subprocess.run(["cargo", "check"], cwd=dest_dir, capture_output=True)
            actions_taken.append("checked cargo dependencies")

        # 4. Generate .env file if missing
        env_file = dest_dir / ".env"
        if not env_file.exists():
            for sample in [".env.example", ".env.template", ".env.sample"]:
                sample_path = dest_dir / sample
                if sample_path.exists():
                    shutil.copy(sample_path, env_file)
                    actions_taken.append(f"created .env from {sample}")
                    break

        # 5. Check and run migrations if database/orm detected
        if (dest_dir / "prisma" / "schema.prisma").exists() and shutil.which("npx"):
            subprocess.run(["npx", "prisma", "generate"], cwd=dest_dir, capture_output=True)
            actions_taken.append("generated Prisma client")

        db.record_workflow(conn, "clone", project_row["id"], True)

    return {
        "path": str(dest_dir),
        "name": dest_dir.name,
        "actions": actions_taken,
    }


def repo_status(conn: sqlite3.Connection, name_filter: str | None = None) -> list[dict]:
    """Returns git status across indexed repositories."""
    query = "SELECT * FROM projects WHERE is_active = 1"
    args = []
    if name_filter:
        query += " AND name LIKE ?"
        args.append(f"%{name_filter}%")

    rows = conn.execute(query, args).fetchall()
    results = []
    for r in rows:
        p = Path(r["path"])
        if (p / ".git").exists():
            res = subprocess.run(["git", "status", "--porcelain", "-b"], cwd=p, capture_output=True, text=True)
            lines = [line for line in res.stdout.splitlines() if line.strip()]
            branch = lines[0] if lines else "unknown"
            modified_count = len(lines) - 1 if len(lines) > 1 else 0
            results.append({
                "name": r["name"],
                "path": r["path"],
                "branch": branch,
                "changes": modified_count,
            })
    return results
