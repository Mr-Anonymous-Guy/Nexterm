"""Tag CRUD (SDD section 11)."""
from __future__ import annotations

import sqlite3


def add_tag(conn: sqlite3.Connection, project_id: int, tag_name: str) -> None:
    conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag_name,))
    tag_id = conn.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()["id"]
    conn.execute(
        "INSERT OR IGNORE INTO project_tags (project_id, tag_id) VALUES (?, ?)",
        (project_id, tag_id),
    )
    conn.commit()


def remove_tag(conn: sqlite3.Connection, project_id: int, tag_name: str) -> None:
    row = conn.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()
    if row:
        conn.execute(
            "DELETE FROM project_tags WHERE project_id = ? AND tag_id = ?",
            (project_id, row["id"]),
        )
        conn.commit()


def list_tags(conn: sqlite3.Connection, project_id: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT t.name FROM tags t
        JOIN project_tags pt ON pt.tag_id = t.id
        WHERE pt.project_id = ?
        """,
        (project_id,),
    ).fetchall()
    return [r["name"] for r in rows]
