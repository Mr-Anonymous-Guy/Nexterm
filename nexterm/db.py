"""SQLite persistence layer for DeveloperOS (SDD section 7)."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DEFAULT_DB_DIR = Path.home() / ".nexterm"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "nexterm.db"

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS projects (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    path            TEXT NOT NULL UNIQUE,
    framework       TEXT,
    language        TEXT,
    package_manager TEXT,
    install_cmd     TEXT,
    run_cmd         TEXT,
    build_cmd       TEXT,
    git_remote      TEXT,
    git_branch      TEXT,
    last_opened     TEXT,
    last_indexed    TEXT NOT NULL,
    is_active       INTEGER DEFAULT 1,
    metadata_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_projects_name ON projects(name);
CREATE INDEX IF NOT EXISTS idx_projects_language ON projects(language);
CREATE INDEX IF NOT EXISTS idx_projects_framework ON projects(framework);

CREATE TABLE IF NOT EXISTS dependencies (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    version     TEXT,
    is_dev      INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_deps_name_version ON dependencies(name, version);
CREATE INDEX IF NOT EXISTS idx_deps_project ON dependencies(project_id);

CREATE TABLE IF NOT EXISTS services (
    id           INTEGER PRIMARY KEY,
    project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,
    name         TEXT NOT NULL,
    start_cmd    TEXT,
    stop_cmd     TEXT,
    health_check TEXT,
    port         INTEGER,
    depends_on   TEXT,
    state        TEXT DEFAULT 'stopped'
);
CREATE INDEX IF NOT EXISTS idx_services_project ON services(project_id);

CREATE TABLE IF NOT EXISTS tags (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS project_tags (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    tag_id     INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (project_id, tag_id)
);

CREATE TABLE IF NOT EXISTS doctor_findings (
    id          INTEGER PRIMARY KEY,
    scope       TEXT NOT NULL,
    project_id  INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    check_name  TEXT NOT NULL,
    severity    TEXT NOT NULL,
    message     TEXT,
    repairable  INTEGER DEFAULT 0,
    found_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS preferences (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_history (
    id          INTEGER PRIMARY KEY,
    command     TEXT NOT NULL,
    project_id  INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    ran_at      TEXT NOT NULL,
    success     INTEGER
);

CREATE TABLE IF NOT EXISTS processes (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    pid         INTEGER,
    command     TEXT NOT NULL,
    status      TEXT DEFAULT 'running',
    started_at  TEXT NOT NULL,
    log_file    TEXT
);

CREATE TABLE IF NOT EXISTS ai_models (
    id                INTEGER PRIMARY KEY,
    name              TEXT NOT NULL UNIQUE,
    provider          TEXT NOT NULL,
    model_path_or_id  TEXT NOT NULL,
    is_default        INTEGER DEFAULT 0,
    registered_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_conversations (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    prompt      TEXT NOT NULL,
    response    TEXT NOT NULL,
    timestamp   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS error_history (
    id          INTEGER PRIMARY KEY,
    command     TEXT NOT NULL,
    cwd         TEXT NOT NULL,
    exit_code   INTEGER,
    category    TEXT NOT NULL,
    source      TEXT,
    title       TEXT NOT NULL,
    summary     TEXT,
    occurred_at TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    db_path = db_path or DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def upsert_project(conn: sqlite3.Connection, facts: dict) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO projects
            (name, path, framework, language, package_manager,
             install_cmd, run_cmd, build_cmd, git_remote, git_branch,
             last_indexed, metadata_json)
        VALUES (:name, :path, :framework, :language, :package_manager,
                :install_cmd, :run_cmd, :build_cmd, :git_remote, :git_branch,
                :last_indexed, :metadata_json)
        ON CONFLICT(path) DO UPDATE SET
            name=excluded.name, framework=excluded.framework, language=excluded.language,
            package_manager=excluded.package_manager, install_cmd=excluded.install_cmd,
            run_cmd=excluded.run_cmd, build_cmd=excluded.build_cmd,
            git_remote=excluded.git_remote, git_branch=excluded.git_branch,
            last_indexed=excluded.last_indexed, metadata_json=excluded.metadata_json
        """,
        facts,
    )
    conn.commit()
    row = cur.execute("SELECT id FROM projects WHERE path = ?", (facts["path"],)).fetchone()
    project_id = row["id"]

    cur.execute("DELETE FROM dependencies WHERE project_id = ?", (project_id,))
    for dep in facts.get("dependencies", []):
        cur.execute(
            "INSERT INTO dependencies (project_id, name, version, is_dev) VALUES (?, ?, ?, ?)",
            (project_id, dep["name"], dep.get("version"), int(dep.get("is_dev", False))),
        )
    conn.commit()
    return project_id


def touch_last_opened(conn: sqlite3.Connection, project_id: int) -> None:
    conn.execute("UPDATE projects SET last_opened = ? WHERE id = ?", (now_iso(), project_id))
    conn.commit()


def record_workflow(conn: sqlite3.Connection, command: str, project_id: int | None, success: bool) -> None:
    conn.execute(
        "INSERT INTO workflow_history (command, project_id, ran_at, success) VALUES (?, ?, ?, ?)",
        (command, project_id, now_iso(), int(success)),
    )
    conn.commit()


def get_preference(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    """Get a stored user preference by key."""
    row = conn.execute("SELECT value FROM preferences WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_preference(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Set a user preference (insert or update)."""
    conn.execute(
        "INSERT INTO preferences (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, value, now_iso()),
    )
    conn.commit()


def list_preferences(conn: sqlite3.Connection) -> list[dict]:
    """List all user preferences."""
    rows = conn.execute("SELECT key, value, updated_at FROM preferences ORDER BY key").fetchall()
    return [{"key": r["key"], "value": r["value"], "updated_at": r["updated_at"]} for r in rows]


def record_error(
    conn: sqlite3.Connection,
    command: str,
    cwd: str,
    exit_code: int | None,
    category: str,
    source: str,
    title: str,
    summary: str = "",
) -> None:
    """Store a recent command error in error_history."""
    conn.execute(
        "INSERT INTO error_history (command, cwd, exit_code, category, source, title, summary, occurred_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (command, cwd, exit_code, category, source, title, summary, now_iso()),
    )
    conn.commit()
    # Keep only the last 100 errors
    conn.execute(
        "DELETE FROM error_history WHERE id NOT IN (SELECT id FROM error_history ORDER BY id DESC LIMIT 100)"
    )
    conn.commit()


def get_recent_errors(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """Retrieve recent command errors."""
    rows = conn.execute(
        "SELECT * FROM error_history ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [
        {
            "id": r["id"],
            "command": r["command"],
            "cwd": r["cwd"],
            "exit_code": r["exit_code"],
            "category": r["category"],
            "source": r["source"],
            "title": r["title"],
            "summary": r["summary"],
            "occurred_at": r["occurred_at"],
        }
        for r in rows
    ]


def unregister_project(conn: sqlite3.Connection, project_id: int) -> bool:
    """Mark a project as inactive (unregistered)."""
    cur = conn.execute("UPDATE projects SET is_active = 0 WHERE id = ?", (project_id,))
    conn.commit()
    return cur.rowcount > 0


def get_all_roots(conn: sqlite3.Connection) -> list[Path]:
    """Get all unique root paths containing active projects."""
    rows = conn.execute("SELECT DISTINCT path FROM projects WHERE is_active = 1").fetchall()
    roots = set()
    for r in rows:
        p = Path(r["path"])
        roots.add(p.parent)
    return list(roots)


def get_project_info(conn: sqlite3.Connection, project_id: int) -> dict | None:
    """Get full details and metadata for a single project."""
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchall()
    if not row:
        return None
    r = dict(row[0])
    tags_rows = conn.execute("SELECT tag FROM project_tags WHERE project_id = ?", (project_id,)).fetchall()
    r["tags"] = [t["tag"] for t in tags_rows]
    return r

