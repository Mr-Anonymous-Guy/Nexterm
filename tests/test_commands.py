"""Comprehensive Command-by-Command Verification Suite for NexTerm.

Validates every command specified in Commands.md across Layer 1 (Native Shell)
and Layer 2 (NexTerm Commands).
"""
import os
import sys
import json
import shutil
import subprocess
import unittest
from pathlib import Path

# Ensure project root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from nexterm import (
    db,
    scanner,
    search,
    tags,
    doctor,
    process,
    stack,
    ai,
    guardian,
    release,
    cli,
    terminal,
    errors,
    __version__,
)


class TestLayer1NativeShellCommands(unittest.TestCase):
    """Verifies OS shell passthrough commands (pwd, echo, whoami, directory ops, toolchains)."""

    def test_pwd_execution(self):
        res = errors.run_command("pwd" if os.name != "nt" else "cd", cwd=os.getcwd(), capture=True)
        self.assertEqual(res.exit_code, 0)
        self.assertTrue(len(res.stdout.strip()) > 0)

    def test_echo_execution(self):
        res = errors.run_command("echo hello_nexterm", cwd=os.getcwd(), capture=True)
        self.assertEqual(res.exit_code, 0)
        self.assertIn("hello_nexterm", res.stdout)

    def test_whoami_execution(self):
        res = errors.run_command("whoami", cwd=os.getcwd(), capture=True)
        self.assertIn(res.exit_code, (0, 1))  # 0 on standard env, 1 if restricted container

    def test_python_executable_passthrough(self):
        res = errors.run_command(f'"{sys.executable}" --version', cwd=os.getcwd(), capture=True)
        self.assertEqual(res.exit_code, 0)
        self.assertIn("Python 3.", res.stdout + res.stderr)

    def test_git_executable_passthrough(self):
        if shutil.which("git"):
            res = errors.run_command("git --version", cwd=os.getcwd(), capture=True)
            self.assertEqual(res.exit_code, 0)
            self.assertIn("git version", res.stdout)

    def test_node_toolchain_detection(self):
        node_avail = shutil.which("node") is not None
        if node_avail:
            res = errors.run_command("node --version", cwd=os.getcwd(), capture=True)
            self.assertEqual(res.exit_code, 0)

    def test_docker_toolchain_detection(self):
        docker_avail = shutil.which("docker") is not None
        if docker_avail:
            res = errors.run_command("docker --version", cwd=os.getcwd(), capture=True)
            self.assertIn(res.exit_code, (0, 1))


class TestLayer2NexTermCommands(unittest.TestCase):
    """Verifies NexTerm native CLI commands."""

    def setUp(self):
        self.conn = db.connect(Path(":memory:"))

    def test_version_command(self):
        import tomllib
        with open(Path(__file__).resolve().parent.parent / "pyproject.toml", "rb") as f:
            pyproject_version = tomllib.load(f)["project"]["version"]
        self.assertEqual(__version__, pyproject_version)

    def test_scan_and_projects_list(self):
        tmp_dir = Path(__file__).resolve().parent / "tmp_fixture_proj"
        tmp_dir.mkdir(exist_ok=True)
        (tmp_dir / "package.json").write_text(json.dumps({"name": "tmp_fixture_proj"}))
        try:
            res = scanner.full_scan(self.conn, [tmp_dir])
            self.assertGreaterEqual(res["updated"], 1)

            rows = search.find(self.conn)
            self.assertTrue(any(r["name"] == "tmp_fixture_proj" for r in rows))

            p = rows[0]
            info = db.get_project_info(self.conn, p["id"])
            self.assertIsNotNone(info)
            self.assertEqual(info["name"], "tmp_fixture_proj")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_unregister_and_rescan(self):
        tmp_dir = Path(__file__).resolve().parent / "tmp_unreg_proj"
        tmp_dir.mkdir(exist_ok=True)
        (tmp_dir / "pyproject.toml").write_text('[project]\nname="tmp_unreg_proj"\nversion="0.1.0"')
        try:
            scanner.full_scan(self.conn, [tmp_dir])
            rows = search.find(self.conn)
            self.assertTrue(len(rows) >= 1)
            pid = rows[0]["id"]

            unreg_ok = db.unregister_project(self.conn, pid)
            self.assertTrue(unreg_ok)
            rows_after = search.find(self.conn)
            self.assertFalse(any(r["id"] == pid for r in rows_after))

            roots = db.get_all_roots(self.conn)
            self.assertIsInstance(roots, list)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_tag_system_commands(self):
        tmp_dir = Path(__file__).resolve().parent / "tmp_tag_proj"
        tmp_dir.mkdir(exist_ok=True)
        (tmp_dir / "package.json").write_text(json.dumps({"name": "tmp_tag_proj"}))
        try:
            scanner.full_scan(self.conn, [tmp_dir])
            p = search.find(self.conn)[0]
            tags.add_tag(self.conn, p["id"], "frontend")
            tags.add_tag(self.conn, p["id"], "react")

            listed = tags.list_tags(self.conn, p["id"])
            self.assertIn("frontend", listed)
            self.assertIn("react", listed)

            tags.remove_tag(self.conn, p["id"], "frontend")
            listed_after = tags.list_tags(self.conn, p["id"])
            self.assertNotIn("frontend", listed_after)
            self.assertIn("react", listed_after)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_doctor_diagnostics(self):
        findings = doctor.run_all(self.conn)
        self.assertIsInstance(findings, list)
        self.assertTrue(all("severity" in f and "message" in f for f in findings))

    def test_stack_orchestration(self):
        tmp_dir = Path(__file__).resolve().parent / "tmp_stack_proj"
        tmp_dir.mkdir(exist_ok=True)
        (tmp_dir / "docker-compose.yml").write_text("version: '3'\nservices:\n  web:\n    image: nginx\n")
        try:
            scanner.full_scan(self.conn, [tmp_dir])
            p = search.find(self.conn)[0]
            status_res = stack.stack_status(self.conn, p["id"])
            self.assertIsInstance(status_res, list)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_ai_subsystem(self):
        prof = ai.profile_hardware()
        self.assertIn("ram_gb", prof)
        self.assertIn("recommended_model", prof)

        reg = ai.register_ai_model(self.conn, "test-model-1", "ollama", "test-path")
        self.assertEqual(reg["name"], "test-model-1")

        models = ai.list_ai_models(self.conn)
        self.assertTrue(any(m["name"] == "test-model-1" for m in models))

        ans = ai.ask_ai(self.conn, "Explain NexTerm")
        self.assertIsInstance(ans, str)

    def test_guardian_subsystem(self):
        engine = guardian.GuardianEngine(repo_root)
        report = engine.run_full_guardian_check()
        self.assertIsNotNone(report)
        self.assertIsInstance(report.all_passed, bool)

    def test_release_subsystem(self):
        validator = release.ReleaseValidator(repo_root)
        check_res = validator.check_version_alignment(target_tag=f"v{__version__}")
        self.assertTrue(check_res.passed)

    def test_preferences_memory(self):
        db.set_preference(self.conn, "editor", "code")
        self.assertEqual(db.get_preference(self.conn, "editor"), "code")

        prefs = db.list_preferences(self.conn)
        self.assertTrue(any(p["key"] == "editor" and p["value"] == "code" for p in prefs))


if __name__ == "__main__":
    unittest.main()
