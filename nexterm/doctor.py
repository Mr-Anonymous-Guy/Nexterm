"""Doctor: diagnostics + repair suggestions (SDD section 16)."""
from __future__ import annotations

import shutil
import socket
import subprocess
import sqlite3
from pathlib import Path

TOOLS = ["git", "node", "npm", "pnpm", "python3", "java", "docker"]


def _tool_version(tool: str) -> str | None:
    path = shutil.which(tool)
    if not path:
        return None
    try:
        out = subprocess.run([tool, "--version"], capture_output=True, text=True, timeout=3)
        return out.stdout.strip().splitlines()[0] if out.stdout else "installed"
    except Exception:
        return "installed"


def check_toolchain() -> list[dict]:
    findings = []
    for tool in TOOLS:
        version = _tool_version(tool)
        findings.append({
            "check_name": f"toolchain:{tool}",
            "severity": "ok" if version else "warn",
            "message": version or f"{tool} not found on PATH",
            "repairable": False,
        })
    return findings


def check_port_conflicts(conn: sqlite3.Connection) -> list[dict]:
    findings = []
    rows = conn.execute("SELECT id, name, port FROM services WHERE port IS NOT NULL").fetchall()
    for row in rows:
        in_use = _port_in_use(row["port"])
        findings.append({
            "check_name": f"port:{row['port']}",
            "severity": "warn" if in_use else "ok",
            "message": f"Port {row['port']} ({row['name']}) is {'in use' if in_use else 'free'}",
            "repairable": False,
        })
    return findings


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def check_project_env(conn: sqlite3.Connection) -> list[dict]:
    findings = []
    for row in conn.execute("SELECT id, name, path, package_manager FROM projects WHERE is_active = 1"):
        path = Path(row["path"])
        example = path / ".env.example"
        actual = path / ".env"
        if example.exists() and not actual.exists():
            findings.append({
                "check_name": f"env:{row['name']}",
                "severity": "error",
                "message": f"{row['name']}: .env.example present but .env is missing",
                "repairable": True,
                "project_id": row["id"],
            })
        node_modules_missing = (
            row["package_manager"] in ("npm", "pnpm", "yarn")
            and (path / "package.json").exists()
            and not (path / "node_modules").exists()
        )
        if node_modules_missing:
            findings.append({
                "check_name": f"install:{row['name']}",
                "severity": "warn",
                "message": f"{row['name']}: dependencies not installed (node_modules missing)",
                "repairable": True,
                "project_id": row["id"],
            })
    return findings


def run_all(conn: sqlite3.Connection) -> list[dict]:
    return check_toolchain() + check_port_conflicts(conn) + check_project_env(conn)


def apply_fix(conn: sqlite3.Connection, finding: dict) -> str:
    """Apply auto-repair: create .env from .env.example or install missing dependencies."""
    check = finding.get("check_name", "")

    if check.startswith("env:"):
        row = conn.execute("SELECT path FROM projects WHERE id = ?", (finding["project_id"],)).fetchone()
        path = Path(row["path"])
        source = path / ".env.example"
        target = path / ".env"
        if source.exists():
            target.write_text(source.read_text())
            return f"Created {target}"
        return "No .env.example found to copy."

    if check.startswith("install:"):
        row = conn.execute("SELECT path, package_manager FROM projects WHERE id = ?", (finding["project_id"],)).fetchone()
        path = Path(row["path"])
        pm = row["package_manager"] or "npm"
        install_cmds = {
            "npm": ["npm", "install"],
            "pnpm": ["pnpm", "install"],
            "yarn": ["yarn", "install"],
            "pip": ["pip", "install", "-r", "requirements.txt"],
            "poetry": ["poetry", "install"],
            "cargo": ["cargo", "check"],
        }
        cmd = install_cmds.get(pm, ["npm", "install"])
        try:
            res = subprocess.run(cmd, cwd=path, capture_output=True, text=True, timeout=120)
            if res.returncode == 0:
                return f"Installed dependencies via `{' '.join(cmd)}` in {path.name}"
            return f"Install failed (exit {res.returncode}): {res.stderr[:200]}"
        except Exception as e:
            return f"Install error: {e}"

    return "No automated repair available for this finding."
