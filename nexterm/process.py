"""Multi-Terminal & Background Process Manager for DeveloperOS (SDD section 13)."""
from __future__ import annotations

import os
import signal
import subprocess
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from . import db

LOGS_DIR = db.DEFAULT_DB_DIR / "logs"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def start_process(
    conn: sqlite3.Connection,
    project_id: int,
    name: str,
    command: str,
    cwd: Path | str,
) -> dict:
    """Spawns a named background process, redirects output to a log file, and records PID."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    cwd = Path(cwd)
    log_file = LOGS_DIR / f"{project_id}_{name}.log"

    with open(log_file, "a", encoding="utf-8") as out:
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            stdout=out,
            stderr=out,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )

    conn.execute(
        """
        INSERT INTO processes (project_id, name, pid, command, status, started_at, log_file)
        VALUES (?, ?, ?, ?, 'running', ?, ?)
        """,
        (project_id, name, proc.pid, command, _now_iso(), str(log_file)),
    )
    conn.commit()

    return {
        "name": name,
        "pid": proc.pid,
        "command": command,
        "log_file": str(log_file),
    }


def list_processes(conn: sqlite3.Connection, project_id: int | None = None) -> list[dict]:
    """Returns processes and updates status by probing PIDs."""
    query = "SELECT p.*, pr.name as project_name FROM processes p LEFT JOIN projects pr ON p.project_id = pr.id"
    args = []
    if project_id:
        query += " WHERE p.project_id = ?"
        args.append(project_id)

    rows = conn.execute(query, args).fetchall()
    results = []

    for r in rows:
        pid = r["pid"]
        is_running = False
        if pid:
            if os.name == "nt":
                res = subprocess.run(f"tasklist /FI \"PID eq {pid}\"", capture_output=True, text=True, shell=True)
                is_running = str(pid) in res.stdout
            else:
                try:
                    os.kill(pid, 0)
                    is_running = True
                except OSError:
                    is_running = False

        status = "running" if is_running else "stopped"
        if status != r["status"]:
            conn.execute("UPDATE processes SET status = ? WHERE id = ?", (status, r["id"]))
            conn.commit()

        results.append({
            "id": r["id"],
            "project_name": r["project_name"] or "global",
            "name": r["name"],
            "pid": pid,
            "command": r["command"],
            "status": status,
            "started_at": r["started_at"],
            "log_file": r["log_file"],
        })

    return results


def stop_process(conn: sqlite3.Connection, pid_or_name: int | str) -> bool:
    """Stops a background process by PID or name."""
    if str(pid_or_name).isdigit():
        row = conn.execute("SELECT * FROM processes WHERE pid = ?", (int(pid_or_name),)).fetchone()
    else:
        row = conn.execute("SELECT * FROM processes WHERE name = ?", (str(pid_or_name),)).fetchone()

    if not row:
        return False

    pid = row["pid"]
    if pid:
        if os.name == "nt":
            subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
        else:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

    conn.execute("UPDATE processes SET status = 'stopped' WHERE id = ?", (row["id"],))
    conn.commit()
    return True


def get_logs(conn: sqlite3.Connection, name_or_pid: str | int, tail_lines: int = 50) -> str:
    """Reads recent lines from process log file."""
    if str(name_or_pid).isdigit():
        row = conn.execute("SELECT * FROM processes WHERE pid = ?", (int(name_or_pid),)).fetchone()
    else:
        row = conn.execute("SELECT * FROM processes WHERE name = ?", (str(name_or_pid),)).fetchone()

    if not row or not row["log_file"]:
        return f"No process logs found for '{name_or_pid}'."

    log_path = Path(row["log_file"])
    if not log_path.exists():
        return f"Log file '{log_path}' does not exist."

    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
        return "".join(lines[-tail_lines:])
