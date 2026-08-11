import json
import sqlite3
from pathlib import Path

import pytest

from nexterm import db, detectors, scanner, search, tags, nlp


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "test.db")


# ─── Existing Tests (preserved) ──────────────────────────────────────
def test_detect_node(tmp_path):
    proj = tmp_path / "app"
    proj.mkdir()
    (proj / "package.json").write_text(json.dumps({
        "name": "app",
        "dependencies": {"react": "19.0.0", "next": "14.0.0"},
        "scripts": {"dev": "next dev"},
    }))
    facts = detectors.detect_all(proj)
    assert facts["language"] == "javascript/typescript"
    assert facts["framework"] == "Next.js"
    assert facts["run_cmd"] == "npm run dev"


def test_detect_python_poetry(tmp_path):
    proj = tmp_path / "svc"
    proj.mkdir()
    (proj / "pyproject.toml").write_text("[tool.poetry]\nname='svc'\n[tool.poetry.dependencies]\nfastapi='^0.1'\n")
    facts = detectors.detect_all(proj)
    assert facts["language"] == "python"
    assert facts["framework"] == "FastAPI"
    assert facts["package_manager"] == "poetry"


def test_scan_and_find(conn, tmp_path):
    proj = tmp_path / "workspace" / "webapp"
    proj.mkdir(parents=True)
    (proj / "package.json").write_text(json.dumps({"name": "webapp", "dependencies": {"react": "19.1.0"}}))
    scanner.full_scan(conn, [tmp_path / "workspace"])
    rows = search.find(conn, dependency="react", dep_version_prefix="19")
    assert len(rows) == 1
    assert rows[0]["name"] == "webapp"


def test_tags(conn, tmp_path):
    proj = tmp_path / "p1"
    proj.mkdir()
    (proj / "go.mod").write_text("module example.com/p1\n")
    scanner.full_scan(conn, [tmp_path])
    project_id = conn.execute("SELECT id FROM projects").fetchone()["id"]
    tags.add_tag(conn, project_id, "backend")
    assert "backend" in tags.list_tags(conn, project_id)
    tags.remove_tag(conn, project_id, "backend")
    assert tags.list_tags(conn, project_id) == []


def test_nlp_rules():
    assert nlp.parse_intent("start portfolio") == {"action": "start", "args": ("portfolio",)}
    assert nlp.parse_intent("open backend") == {"action": "open", "args": ("backend",)}
    assert nlp.parse_intent("explain portfolio") == {"action": "explain", "args": ("portfolio",)}
    assert nlp.parse_intent("fix invoice") == {"action": "fix", "args": ("invoice",)}
    intent = nlp.parse_intent("find projects using react 19")
    assert intent["action"] == "find_dep_version"
    assert intent["args"] == ("react", "19")


def test_process_manager(conn, tmp_path):
    from nexterm import process
    proj = tmp_path / "proc_app"
    proj.mkdir()
    (proj / "package.json").write_text(json.dumps({"name": "proc_app"}))
    scanner.full_scan(conn, [tmp_path])
    pid_row = conn.execute("SELECT id FROM projects").fetchone()

    res = process.start_process(conn, pid_row["id"], "dummy_task", "python -c \"print('hello')\"", proj)
    assert res["name"] == "dummy_task"
    procs = process.list_processes(conn, pid_row["id"])
    assert len(procs) >= 1


def test_ship_runner(conn, tmp_path):
    from nexterm import ship
    proj = tmp_path / "ship_app"
    proj.mkdir()
    (proj / "package.json").write_text(json.dumps({"name": "ship_app"}))
    scanner.full_scan(conn, [tmp_path])
    pid_row = conn.execute("SELECT id FROM projects").fetchone()

    res = ship.ship_project(conn, pid_row["id"], skip_tests=True)
    assert res["success"] is True
    assert len(res["phases"]) >= 3


def test_ai_features(conn, tmp_path):
    from nexterm import ai
    proj = tmp_path / "ai_app"
    proj.mkdir()
    (proj / "package.json").write_text(json.dumps({"name": "ai_app", "dependencies": {"react": "18.0.0"}}))
    scanner.full_scan(conn, [tmp_path])
    pid_row = conn.execute("SELECT id FROM projects").fetchone()

    exp = ai.explain_project(conn, "ai_app")
    assert exp["name"] == "ai_app"

    ans = ai.ask_ai(conn, "Why isn't backend starting?", pid_row["id"])
    assert "Backend" in ans or "worksapce" in ans

    fix_res = ai.fix_project(conn, "ai_app")
    assert fix_res["project"] == "ai_app"


# ─── New Tests: Bug Fix Verification ─────────────────────────────────

def test_doctor_fix_install_prefix(conn, tmp_path):
    """BUG-2: doctor apply_fix must handle 'install:' prefix findings."""
    from nexterm import doctor

    proj = tmp_path / "missing_deps"
    proj.mkdir()
    (proj / "package.json").write_text(json.dumps({"name": "missing_deps"}))
    scanner.full_scan(conn, [tmp_path])
    pid_row = conn.execute("SELECT id FROM projects").fetchone()

    finding = {
        "check_name": "install:missing_deps",
        "project_id": pid_row["id"],
        "severity": "warn",
        "message": "missing_deps: dependencies not installed",
        "repairable": True,
    }
    result = doctor.apply_fix(conn, finding)
    # Should attempt install, not return "No automated repair available"
    assert "No automated repair" not in result


def test_doctor_fix_env_prefix(conn, tmp_path):
    """BUG-2: doctor apply_fix env: prefix still works after refactor."""
    from nexterm import doctor

    proj = tmp_path / "env_app"
    proj.mkdir()
    (proj / "package.json").write_text(json.dumps({"name": "env_app"}))
    (proj / ".env.example").write_text("DB_URL=postgres://localhost\nSECRET=abc\n")
    scanner.full_scan(conn, [tmp_path])
    pid_row = conn.execute("SELECT id FROM projects").fetchone()

    finding = {
        "check_name": "env:env_app",
        "project_id": pid_row["id"],
        "severity": "error",
        "message": "env_app: .env missing",
        "repairable": True,
    }
    result = doctor.apply_fix(conn, finding)
    assert "Created" in result
    assert (proj / ".env").exists()
    assert (proj / ".env").read_text() == "DB_URL=postgres://localhost\nSECRET=abc\n"


def test_tag_list(conn, tmp_path):
    """BUG-5: tag list should return correct tags."""
    proj = tmp_path / "tagged_proj"
    proj.mkdir()
    (proj / "package.json").write_text(json.dumps({"name": "tagged_proj"}))
    scanner.full_scan(conn, [tmp_path])
    pid_row = conn.execute("SELECT id FROM projects").fetchone()

    tags.add_tag(conn, pid_row["id"], "frontend")
    tags.add_tag(conn, pid_row["id"], "production")
    result = tags.list_tags(conn, pid_row["id"])
    assert "frontend" in result
    assert "production" in result
    assert len(result) == 2


def test_scanner_windows_path_dedup(tmp_path):
    """BUG-3: Scanner should not index subdirectories of detected projects."""
    proj = tmp_path / "myproject"
    proj.mkdir()
    (proj / "package.json").write_text(json.dumps({"name": "myproject"}))
    # Create a subdirectory with its own package.json (nested project)
    sub = proj / "packages" / "sub"
    sub.mkdir(parents=True)
    (sub / "package.json").write_text(json.dumps({"name": "sub"}))

    conn = db.connect(tmp_path / "dedup.db")
    result = scanner.full_scan(conn, [tmp_path], max_depth=4)
    # The parent project is detected first, so subdirs should be skipped
    assert result["updated"] == 1  # Only the top-level project


def test_preferences(conn):
    """GAP-4: Preference get/set/list."""
    assert db.get_preference(conn, "editor") is None
    assert db.get_preference(conn, "editor", "code") == "code"

    db.set_preference(conn, "editor", "vim")
    assert db.get_preference(conn, "editor") == "vim"

    db.set_preference(conn, "package_manager", "pnpm")
    prefs = db.list_preferences(conn)
    assert len(prefs) == 2
    keys = [p["key"] for p in prefs]
    assert "editor" in keys
    assert "package_manager" in keys

    # Update existing
    db.set_preference(conn, "editor", "code")
    assert db.get_preference(conn, "editor") == "code"


def test_ai_model_list_remove(conn):
    """GAP-7: AI model list and remove."""
    from nexterm import ai

    ai.register_ai_model(conn, "test-model", "ollama", "test-path")
    models = ai.list_ai_models(conn)
    assert len(models) >= 1
    assert any(m["name"] == "test-model" for m in models)

    removed = ai.remove_ai_model(conn, "test-model")
    assert removed is True
    models_after = ai.list_ai_models(conn)
    assert not any(m["name"] == "test-model" for m in models_after)

    # Remove non-existent
    assert ai.remove_ai_model(conn, "nonexistent") is False


def test_repo_status(conn, tmp_path):
    """GAP-5: repo_status returns git info for indexed repos."""
    from nexterm import repo
    # Create a project without git — should not appear
    proj = tmp_path / "nongit_proj"
    proj.mkdir()
    (proj / "package.json").write_text(json.dumps({"name": "nongit_proj"}))
    scanner.full_scan(conn, [tmp_path])

    results = repo.repo_status(conn)
    # Non-git projects should not appear in repo status
    assert all(r["name"] != "nongit_proj" for r in results)


def test_find_all_projects(conn, tmp_path):
    """UX-2: find with no args should return all projects."""
    p1 = tmp_path / "alpha"
    p1.mkdir()
    (p1 / "package.json").write_text(json.dumps({"name": "alpha"}))
    p2 = tmp_path / "beta"
    p2.mkdir()
    (p2 / "go.mod").write_text("module example.com/beta\n")
    scanner.full_scan(conn, [tmp_path])

    rows = search.find(conn)
    assert len(rows) >= 2


def test_detect_rust(tmp_path):
    """Additional detector test for Rust projects."""
    proj = tmp_path / "mylib"
    proj.mkdir()
    (proj / "Cargo.toml").write_text('[package]\nname = "mylib"\nversion = "0.1.0"\n\n[dependencies]\nserde = "1.0"\ntokio = "1"\n')
    facts = detectors.detect_all(proj)
    assert facts["language"] == "rust"
    assert facts["package_manager"] == "cargo"
    assert facts["run_cmd"] == "cargo run"
    dep_names = [d["name"] for d in facts["dependencies"]]
    assert "serde" in dep_names
    assert "tokio" in dep_names


def test_detect_go(tmp_path):
    """Additional detector test for Go projects."""
    proj = tmp_path / "goapp"
    proj.mkdir()
    (proj / "go.mod").write_text("module github.com/user/goapp\n\ngo 1.21\n")
    facts = detectors.detect_all(proj)
    assert facts["language"] == "go"
    assert facts["name"] == "goapp"
    assert facts["package_manager"] == "go"


def test_detect_java_gradle(tmp_path):
    """Additional detector test for Java/Gradle projects."""
    proj = tmp_path / "javaapp"
    proj.mkdir()
    (proj / "build.gradle").write_text("plugins { id 'org.springframework.boot' version '3.0.0' }\ndependencies { implementation 'org.spring-boot:spring-boot-starter' }")
    facts = detectors.detect_all(proj)
    assert facts["language"] == "java"
    assert facts["package_manager"] == "gradle"


def test_detect_docker_compose(tmp_path):
    """Additional detector test for Docker Compose projects."""
    proj = tmp_path / "dockerapp"
    proj.mkdir()
    (proj / "docker-compose.yml").write_text("version: '3'\nservices:\n  web:\n    image: nginx\n")
    facts = detectors.detect_all(proj)
    assert facts["language"] == "docker"
    assert facts["framework"] == "Docker Compose"
    assert facts["run_cmd"] == "docker compose up -d"


def test_shell_cd_and_prompt(conn, tmp_path):
    """Test cd navigation, cd.. / cd,, variants, and prompt formatting."""
    from nexterm import cli
    orig_cwd = Path.cwd()

    target_dir = tmp_path / "sub_dir"
    target_dir.mkdir()
    scanner.full_scan(conn, [tmp_path])

    try:
        cli._handle_cd(str(target_dir))
        assert Path.cwd().resolve() == target_dir.resolve()

        prompt = cli._get_prompt(conn)
        assert "worksapce" in prompt
        assert str(target_dir) in prompt

        # Test cd.. and cd,, normalization
        cli._handle_cd("..")
        assert Path.cwd().resolve() == tmp_path.resolve()
    finally:
        cli._handle_cd(str(orig_cwd))


def test_terminal_completer(conn, tmp_path):
    """Test DeveloperOSCompleter completion engine."""
    from prompt_toolkit.document import Document
    from nexterm import terminal

    proj = tmp_path / "completer_app"
    proj.mkdir()
    (proj / "package.json").write_text(json.dumps({"name": "completer_app"}))
    scanner.full_scan(conn, [tmp_path])

    completer = terminal.DeveloperOSCompleter(lambda: conn)

    # 1. Top-level command completion
    doc1 = Document("do", 2)
    completions1 = [c.text for c in completer.get_completions(doc1, None)]
    assert "doctor" in completions1

    # 2. Project name completion
    doc2 = Document("start comp", 10)
    completions2 = [c.text for c in completer.get_completions(doc2, None)]
    assert "completer_app" in completions2

    # 3. Work subcommand project completion
    doc3 = Document("work open comp", 14)
    completions3 = [c.text for c in completer.get_completions(doc3, None)]
    assert "completer_app" in completions3



