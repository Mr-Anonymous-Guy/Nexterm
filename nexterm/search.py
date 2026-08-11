"""Search: fuzzy name matching + structured filters (SDD section 11)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher


def fuzzy_find(conn: sqlite3.Connection, query: str, limit: int = 5) -> list[sqlite3.Row]:
    rows = conn.execute("SELECT * FROM projects WHERE is_active = 1").fetchall()
    scored = sorted(
        rows,
        key=lambda r: SequenceMatcher(None, query.lower(), r["name"].lower()).ratio(),
        reverse=True,
    )
    return [r for r in scored if SequenceMatcher(None, query.lower(), r["name"].lower()).ratio() > 0.3][:limit]


def find(
    conn: sqlite3.Connection,
    query: str | None = None,
    framework: str | None = None,
    language: str | None = None,
    dependency: str | None = None,
    dep_version_prefix: str | None = None,
    tag: str | None = None,
    inactive_days: int | None = None,
) -> list[sqlite3.Row]:
    sql = "SELECT DISTINCT p.* FROM projects p"
    joins = []
    where = ["p.is_active = 1"]
    params: dict = {}

    if dependency:
        joins.append("JOIN dependencies d ON d.project_id = p.id")
        where.append("d.name = :dep")
        params["dep"] = dependency
        if dep_version_prefix:
            where.append("d.version LIKE :dep_ver")
            params["dep_ver"] = f"{dep_version_prefix}%"
    if tag:
        joins.append("JOIN project_tags pt ON pt.project_id = p.id")
        joins.append("JOIN tags t ON t.id = pt.tag_id")
        where.append("t.name = :tag")
        params["tag"] = tag
    if framework:
        where.append("p.framework = :framework")
        params["framework"] = framework
    if language:
        where.append("p.language = :language")
        params["language"] = language
    if inactive_days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=inactive_days)).isoformat()
        where.append("(p.last_opened IS NULL OR p.last_opened < :cutoff)")
        params["cutoff"] = cutoff

    sql += " " + " ".join(joins)
    if where:
        sql += " WHERE " + " AND ".join(where)
    rows = conn.execute(sql, params).fetchall()

    if query:
        rows = sorted(
            rows,
            key=lambda r: SequenceMatcher(None, query.lower(), r["name"].lower()).ratio(),
            reverse=True,
        )
    return rows
