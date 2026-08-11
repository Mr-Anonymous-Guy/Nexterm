"""Infrastructure & Service Stack Orchestrator for DeveloperOS (SDD section 12 & 36)."""
from __future__ import annotations

import socket
import subprocess
import sqlite3
from pathlib import Path

from . import db, service, process, detectors


def is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    """Probes whether a port is currently listening."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def detect_stack(project_dir: Path) -> list[dict]:
    """Detects service dependencies for a project."""
    services = []
    has_docker = (project_dir / "docker-compose.yml").exists() or (project_dir / "docker-compose.yaml").exists()

    if has_docker:
        services.append({
            "name": "docker-compose",
            "kind": "docker",
            "start_cmd": "docker compose up -d",
            "stop_cmd": "docker compose down",
            "port": None,
            "depends_on": [],
        })

    facts = detectors.detect_all(project_dir)
    deps = [d["name"].lower() for d in facts.get("dependencies", [])]

    if "pg" in deps or "psycopg2" in deps or "asyncpg" in deps or "prisma" in deps:
        services.append({
            "name": "postgresql",
            "kind": "database",
            "start_cmd": None,
            "port": 5432,
            "depends_on": ["docker-compose"] if has_docker else [],
        })

    if "redis" in deps or "ioredis" in deps:
        services.append({
            "name": "redis",
            "kind": "cache",
            "start_cmd": None,
            "port": 6379,
            "depends_on": ["docker-compose"] if has_docker else [],
        })

    if facts.get("run_cmd"):
        services.append({
            "name": f"{project_dir.name}-app",
            "kind": "app",
            "start_cmd": facts["run_cmd"],
            "port": 3000 if "Next.js" in (facts.get("framework") or "") else 8000,
            "depends_on": [s["name"] for s in services if s["kind"] in ("database", "cache", "docker")],
        })

    return services


def start_stack(conn: sqlite3.Connection, project_id: int) -> list[dict]:
    """Starts the stack in dependency order."""
    p_row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not p_row:
        return []

    project_dir = Path(p_row["path"])
    services = detect_stack(project_dir)
    results = []

    for svc in services:
        name = svc["name"]
        cmd = svc.get("start_cmd")
        port = svc.get("port")

        if port and is_port_open(port):
            results.append({"service": name, "status": "running (port in use)", "port": port})
            continue

        if cmd:
            res = process.start_process(conn, project_id, name, cmd, project_dir)
            results.append({"service": name, "status": "started", "pid": res["pid"], "port": port})
        else:
            results.append({"service": name, "status": "no start command configured", "port": port})

    return results


def stack_status(conn: sqlite3.Connection, project_id: int) -> list[dict]:
    """Probes status of stack services."""
    p_row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not p_row:
        return []

    services = detect_stack(Path(p_row["path"]))
    status_list = []

    for svc in services:
        port = svc.get("port")
        running = is_port_open(port) if port else False
        status_list.append({
            "name": svc["name"],
            "kind": svc["kind"],
            "port": port,
            "status": "running" if running else "stopped",
        })

    return status_list
