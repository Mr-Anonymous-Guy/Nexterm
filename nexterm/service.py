"""Service Manager: smart start with topological dependency ordering (SDD 11-12)."""
from __future__ import annotations

import subprocess
import sqlite3


def topo_sort(services: list[sqlite3.Row]) -> list[sqlite3.Row]:
    by_name = {s["name"]: s for s in services}
    visited: set[str] = set()
    order: list[sqlite3.Row] = []

    def visit(svc: sqlite3.Row, stack: set[str]):
        if svc["name"] in visited:
            return
        if svc["name"] in stack:
            return  # cycle guard
        stack = stack | {svc["name"]}
        deps = (svc["depends_on"] or "").split(",")
        for dep_name in deps:
            dep_name = dep_name.strip()
            if dep_name and dep_name in by_name:
                visit(by_name[dep_name], stack)
        visited.add(svc["name"])
        order.append(svc)

    for svc in services:
        visit(svc, set())
    return order


def smart_start(conn: sqlite3.Connection, project_id: int) -> list[dict]:
    services = conn.execute(
        "SELECT * FROM services WHERE project_id = ?", (project_id,)
    ).fetchall()
    ordered = topo_sort(services)
    results = []
    for svc in ordered:
        status = "skipped (no start_cmd)"
        if svc["start_cmd"]:
            try:
                subprocess.Popen(
                    svc["start_cmd"], shell=True, cwd=None,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                status = "started"
                conn.execute("UPDATE services SET state = 'running' WHERE id = ?", (svc["id"],))
                conn.commit()
            except Exception as exc:
                status = f"failed: {exc}"
        results.append({"service": svc["name"], "status": status})
    return results
