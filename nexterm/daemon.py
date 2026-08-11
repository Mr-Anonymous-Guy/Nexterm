"""Background Workspace Watcher & Real-Time Indexing Daemon for DeveloperOS (SDD section 22 & 38)."""
from __future__ import annotations

import os
import sys
import time
import subprocess
import sqlite3
from pathlib import Path

from . import db, scanner

PID_FILE = db.DEFAULT_DB_DIR / "daemon.pid"
LOG_FILE = db.DEFAULT_DB_DIR / "daemon.log"


def is_daemon_running() -> int | None:
    """Checks if background daemon process is currently active."""
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
        if os.name == "nt":
            res = subprocess.run(f"tasklist /FI \"PID eq {pid}\"", capture_output=True, text=True, shell=True)
            return pid if str(pid) in res.stdout else None
        else:
            os.kill(pid, 0)
            return pid
    except (ValueError, OSError):
        return None


def run_daemon_loop(db_path: Path | None = None, roots: list[Path] | None = None, interval_seconds: int = 15):
    """Execution loop for background indexing daemon."""
    conn = db.connect(db_path)
    roots = roots or [Path.home() / "code", Path("C:/Mr-Anonymous-Guy")]
    valid_roots = [r for r in roots if r.exists()]

    with open(LOG_FILE, "a", encoding="utf-8") as log:
        log.write(f"[{db.now_iso()}] worksapce daemon started watching: {[str(r) for r in valid_roots]}\n")
        log.flush()

        while True:
            try:
                if valid_roots:
                    res = scanner.full_scan(conn, valid_roots, max_depth=3)
                    log.write(f"[{db.now_iso()}] Indexed {res['scanned']} folders, updated {res['updated']} projects.\n")
                    log.flush()
                time.sleep(interval_seconds)
            except Exception as e:
                log.write(f"[{db.now_iso()}] Daemon error: {e}\n")
                log.flush()
                time.sleep(interval_seconds)


def start_daemon(roots: list[Path] | None = None) -> dict:
    """Launches the background daemon process."""
    running_pid = is_daemon_running()
    if running_pid:
        return {"status": "already running", "pid": running_pid}

    db.DEFAULT_DB_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "nexterm.daemon"]
    
    with open(LOG_FILE, "a", encoding="utf-8") as out:
        proc = subprocess.Popen(
            cmd,
            stdout=out,
            stderr=out,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )

    PID_FILE.write_text(str(proc.pid))
    return {"status": "started", "pid": proc.pid, "log_file": str(LOG_FILE)}


def stop_daemon() -> dict:
    """Stops the running background daemon."""
    pid = is_daemon_running()
    if not pid:
        if PID_FILE.exists():
            PID_FILE.unlink()
        return {"status": "not running"}

    if os.name == "nt":
        subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            pass

    if PID_FILE.exists():
        PID_FILE.unlink()

    return {"status": "stopped", "pid": pid}
