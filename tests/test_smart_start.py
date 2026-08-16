"""Tests for the Interactive Smart Start feature.

Verifies that `nexterm start <project>`:
    - Detects project and package manager correctly
    - Installs dependencies only when node_modules is missing
    - Aborts if installation fails
    - Runs the app interactively (foreground subprocess.run, not background Popen)
    - Checks for port conflicts before starting
    - Uses the correct run command (dev preferred over start)
    - Works with npm, pnpm, and yarn
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

# Ensure project root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from nexterm import db, scanner, search, cli, detectors, stack


# ═══════════════════════════════════════════════════════════════════════
#  FIXTURES
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture
def tmp_conn(tmp_path):
    """In-memory-style DB connection using a temp file."""
    return db.connect(tmp_path / "test_start.db")


@pytest.fixture
def npm_project(tmp_path):
    """Creates a minimal npm project with a dev script."""
    proj = tmp_path / "test-app"
    proj.mkdir()
    (proj / "package.json").write_text(json.dumps({
        "name": "test-app",
        "version": "1.0.0",
        "scripts": {
            "dev": "vite",
            "start": "node server.js",
            "build": "vite build",
        },
        "dependencies": {
            "vite": "^5.0.0",
        },
    }))
    return proj


@pytest.fixture
def npm_project_start_only(tmp_path):
    """Creates an npm project with only a start script (no dev)."""
    proj = tmp_path / "start-only-app"
    proj.mkdir()
    (proj / "package.json").write_text(json.dumps({
        "name": "start-only-app",
        "version": "1.0.0",
        "scripts": {
            "start": "node index.js",
        },
        "dependencies": {},
    }))
    return proj


@pytest.fixture
def pnpm_project(tmp_path):
    """Creates a pnpm project (has pnpm-lock.yaml)."""
    proj = tmp_path / "pnpm-app"
    proj.mkdir()
    (proj / "package.json").write_text(json.dumps({
        "name": "pnpm-app",
        "version": "1.0.0",
        "scripts": {"dev": "vite"},
        "dependencies": {},
    }))
    (proj / "pnpm-lock.yaml").write_text("lockfileVersion: 5.4\n")
    return proj


@pytest.fixture
def yarn_project(tmp_path):
    """Creates a yarn project (has yarn.lock)."""
    proj = tmp_path / "yarn-app"
    proj.mkdir()
    (proj / "package.json").write_text(json.dumps({
        "name": "yarn-app",
        "version": "1.0.0",
        "scripts": {"dev": "vite"},
        "dependencies": {},
    }))
    (proj / "yarn.lock").write_text("# yarn lockfile\n")
    return proj


def _index_project(conn, proj_path):
    """Scan and index a project so `search.fuzzy_find` can find it."""
    scanner.full_scan(conn, [proj_path])


# ═══════════════════════════════════════════════════════════════════════
#  TESTS: DEPENDENCY DETECTION
# ═══════════════════════════════════════════════════════════════════════

class TestDepsAlreadyInstalled:
    """When node_modules exists, npm install must NOT be called."""

    def test_start_skips_install_when_node_modules_exists(self, tmp_conn, npm_project):
        # Create node_modules so install is skipped
        (npm_project / "node_modules").mkdir()
        _index_project(tmp_conn, npm_project)

        runner = CliRunner()
        with mock.patch("subprocess.run") as mock_run, \
             mock.patch("nexterm.stack.is_port_open", return_value=False), \
             mock.patch("nexterm.stack.detect_stack", return_value=[]), \
             mock.patch("nexterm.cli._conn", return_value=tmp_conn):
            mock_run.return_value = mock.Mock(returncode=0)
            result = runner.invoke(cli.start, ["test-app", "--no-browser"])

        # subprocess.run should have been called for the run command, NOT install
        for call in mock_run.call_args_list:
            cmd_arg = call.args[0] if call.args else call.kwargs.get("args", "")
            assert "install" not in str(cmd_arg), \
                f"npm install should NOT have been called. Command: {cmd_arg}"
        assert "Dependencies already installed" in result.output


class TestDepsMissing:
    """When node_modules is missing, npm install must be called before start."""

    def test_start_runs_install_when_node_modules_missing(self, tmp_conn, npm_project):
        # No node_modules directory
        _index_project(tmp_conn, npm_project)

        runner = CliRunner()
        with mock.patch("subprocess.run") as mock_run, \
             mock.patch("nexterm.stack.is_port_open", return_value=False), \
             mock.patch("nexterm.stack.detect_stack", return_value=[]), \
             mock.patch("nexterm.cli._conn", return_value=tmp_conn):
            mock_run.return_value = mock.Mock(returncode=0)
            result = runner.invoke(cli.start, ["test-app", "--no-browser"])

        # First subprocess.run call should be install, second should be the run command
        assert mock_run.call_count >= 2, \
            f"Expected at least 2 subprocess.run calls (install + run). Got {mock_run.call_count}"
        install_call = mock_run.call_args_list[0]
        assert "install" in str(install_call), \
            f"First call should be install. Got: {install_call}"
        assert "Dependencies missing" in result.output


# ═══════════════════════════════════════════════════════════════════════
#  TESTS: START SCRIPT DETECTION
# ═══════════════════════════════════════════════════════════════════════

class TestScriptDetection:
    """Verify that 'dev' is preferred over 'start', and fallback works."""

    def test_dev_script_preferred(self, npm_project):
        facts = detectors.detect_all(npm_project)
        assert facts["run_cmd"] == "npm run dev"

    def test_start_script_fallback(self, npm_project_start_only):
        facts = detectors.detect_all(npm_project_start_only)
        assert facts["run_cmd"] == "npm run start"


# ═══════════════════════════════════════════════════════════════════════
#  TESTS: PACKAGE MANAGER DETECTION
# ═══════════════════════════════════════════════════════════════════════

class TestPackageManagerDetection:
    """Verify correct package manager detection for npm, pnpm, yarn."""

    def test_npm_detected(self, npm_project):
        facts = detectors.detect_all(npm_project)
        assert facts["package_manager"] == "npm"
        assert facts["install_cmd"] == "npm install"

    def test_pnpm_detected(self, pnpm_project):
        facts = detectors.detect_all(pnpm_project)
        assert facts["package_manager"] == "pnpm"
        assert facts["install_cmd"] == "pnpm install"

    def test_yarn_detected(self, yarn_project):
        facts = detectors.detect_all(yarn_project)
        assert facts["package_manager"] == "yarn"
        assert facts["install_cmd"] == "yarn install"


# ═══════════════════════════════════════════════════════════════════════
#  TESTS: INSTALL FAILURE
# ═══════════════════════════════════════════════════════════════════════

class TestInstallFailure:
    """If installation fails, the application must NOT start."""

    def test_install_failure_aborts_start(self, tmp_conn, npm_project):
        # No node_modules → install will run
        _index_project(tmp_conn, npm_project)

        runner = CliRunner()
        with mock.patch("subprocess.run") as mock_run, \
             mock.patch("nexterm.stack.is_port_open", return_value=False), \
             mock.patch("nexterm.stack.detect_stack", return_value=[]), \
             mock.patch("nexterm.cli._conn", return_value=tmp_conn):
            # First call (install) fails, subsequent calls should not happen
            mock_run.return_value = mock.Mock(returncode=1)
            result = runner.invoke(cli.start, ["test-app", "--no-browser"])

        assert "installation failed" in result.output.lower()
        # Only 1 subprocess.run call (the failed install), no run command
        assert mock_run.call_count == 1, \
            f"Expected exactly 1 call (failed install). Got {mock_run.call_count}"


# ═══════════════════════════════════════════════════════════════════════
#  TESTS: FOREGROUND EXECUTION
# ═══════════════════════════════════════════════════════════════════════

class TestForegroundExecution:
    """Verify that the app runs via subprocess.run (foreground), not Popen (background)."""

    def test_start_uses_subprocess_run_not_popen(self, tmp_conn, npm_project):
        (npm_project / "node_modules").mkdir()
        _index_project(tmp_conn, npm_project)

        runner = CliRunner()
        with mock.patch("subprocess.run") as mock_run, \
             mock.patch("subprocess.Popen") as mock_popen, \
             mock.patch("nexterm.stack.is_port_open", return_value=False), \
             mock.patch("nexterm.stack.detect_stack", return_value=[]), \
             mock.patch("nexterm.cli._conn", return_value=tmp_conn):
            mock_run.return_value = mock.Mock(returncode=0)
            result = runner.invoke(cli.start, ["test-app", "--no-browser"])

        # subprocess.run should have been called (foreground)
        assert mock_run.called, "subprocess.run was not called (app should run in foreground)"
        # subprocess.Popen should NOT have been called for the app
        assert not mock_popen.called, "subprocess.Popen was called (app should NOT run in background)"


# ═══════════════════════════════════════════════════════════════════════
#  TESTS: PORT CONFLICT
# ═══════════════════════════════════════════════════════════════════════

class TestPortConflict:
    """If the detected port is already in use, start should abort."""

    def test_port_in_use_aborts(self, tmp_conn, npm_project):
        (npm_project / "node_modules").mkdir()
        _index_project(tmp_conn, npm_project)

        runner = CliRunner()
        with mock.patch("subprocess.run") as mock_run, \
             mock.patch("nexterm.stack.is_port_open", return_value=True), \
             mock.patch("nexterm.stack.detect_stack", return_value=[]), \
             mock.patch("nexterm.cli._conn", return_value=tmp_conn):
            mock_run.return_value = mock.Mock(returncode=0)
            result = runner.invoke(cli.start, ["test-app", "--no-browser"])

        assert "already in use" in result.output.lower()


# ═══════════════════════════════════════════════════════════════════════
#  TESTS: CWD-BASED START (no project name, no prior scan)
# ═══════════════════════════════════════════════════════════════════════

class TestStartFromCWD:
    """When no project name is given, `start` should detect from current directory."""

    def test_start_from_cwd_detects_npm_project(self, tmp_conn, npm_project):
        """cd into an npm project dir and type `start` — should detect and run."""
        (npm_project / "node_modules").mkdir()
        # NO _index_project call — project is NOT in the database

        runner = CliRunner()
        with mock.patch("subprocess.run") as mock_run, \
             mock.patch("nexterm.stack.is_port_open", return_value=False), \
             mock.patch("nexterm.stack.detect_stack", return_value=[]), \
             mock.patch("nexterm.cli._conn", return_value=tmp_conn), \
             mock.patch("pathlib.Path.cwd", return_value=npm_project):
            mock_run.return_value = mock.Mock(returncode=0)
            # No argument — CWD mode
            result = runner.invoke(cli.start, ["--no-browser"])

        assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}. Output: {result.output}"
        assert "Detecting project" in result.output
        assert "test-app" in result.output
        # The run command should have been called
        assert mock_run.called

    def test_start_from_cwd_no_prior_scan_needed(self, tmp_conn, npm_project):
        """Project has never been scanned — `start` from CWD should still work."""
        (npm_project / "node_modules").mkdir()
        # Explicitly verify project is NOT in the database
        rows = tmp_conn.execute("SELECT * FROM projects").fetchall()
        project_names = [r["name"] for r in rows]
        assert "test-app" not in project_names

        runner = CliRunner()
        with mock.patch("subprocess.run") as mock_run, \
             mock.patch("nexterm.stack.is_port_open", return_value=False), \
             mock.patch("nexterm.stack.detect_stack", return_value=[]), \
             mock.patch("nexterm.cli._conn", return_value=tmp_conn), \
             mock.patch("pathlib.Path.cwd", return_value=npm_project):
            mock_run.return_value = mock.Mock(returncode=0)
            result = runner.invoke(cli.start, ["--no-browser"])

        assert result.exit_code == 0
        assert "npm run dev" in result.output

    def test_start_from_cwd_installs_when_missing(self, tmp_conn, npm_project):
        """CWD mode: missing node_modules triggers install before start."""
        # No node_modules
        runner = CliRunner()
        with mock.patch("subprocess.run") as mock_run, \
             mock.patch("nexterm.stack.is_port_open", return_value=False), \
             mock.patch("nexterm.stack.detect_stack", return_value=[]), \
             mock.patch("nexterm.cli._conn", return_value=tmp_conn), \
             mock.patch("pathlib.Path.cwd", return_value=npm_project):
            mock_run.return_value = mock.Mock(returncode=0)
            result = runner.invoke(cli.start, ["--no-browser"])

        assert "Dependencies missing" in result.output
        # First call should be install
        first_cmd = mock_run.call_args_list[0].args[0]
        assert "install" in str(first_cmd)

    def test_start_from_cwd_skips_install_when_present(self, tmp_conn, npm_project):
        """CWD mode: existing node_modules skips install."""
        (npm_project / "node_modules").mkdir()

        runner = CliRunner()
        with mock.patch("subprocess.run") as mock_run, \
             mock.patch("nexterm.stack.is_port_open", return_value=False), \
             mock.patch("nexterm.stack.detect_stack", return_value=[]), \
             mock.patch("nexterm.cli._conn", return_value=tmp_conn), \
             mock.patch("pathlib.Path.cwd", return_value=npm_project):
            mock_run.return_value = mock.Mock(returncode=0)
            result = runner.invoke(cli.start, ["--no-browser"])

        assert "Dependencies already installed" in result.output


class TestStartFromInvalidDirectory:
    """When no project name is given and CWD is not a project, show clear error."""

    def test_no_project_detected_error(self, tmp_conn, tmp_path):
        """CWD with no package.json/pyproject.toml/etc should give a clear error."""
        empty_dir = tmp_path / "empty-folder"
        empty_dir.mkdir()

        runner = CliRunner()
        with mock.patch("nexterm.cli._conn", return_value=tmp_conn), \
             mock.patch("pathlib.Path.cwd", return_value=empty_dir):
            result = runner.invoke(cli.start, ["--no-browser"])

        assert "No supported project detected" in result.output
        assert result.exit_code != 0


class TestProjectNameModeRegression:
    """Existing `start <project-name>` must continue working unchanged."""

    def test_start_with_name_still_works(self, tmp_conn, npm_project):
        """start <name> uses DB lookup, same as before."""
        (npm_project / "node_modules").mkdir()
        _index_project(tmp_conn, npm_project)

        runner = CliRunner()
        with mock.patch("subprocess.run") as mock_run, \
             mock.patch("nexterm.stack.is_port_open", return_value=False), \
             mock.patch("nexterm.stack.detect_stack", return_value=[]), \
             mock.patch("nexterm.cli._conn", return_value=tmp_conn):
            mock_run.return_value = mock.Mock(returncode=0)
            result = runner.invoke(cli.start, ["test-app", "--no-browser"])

        assert result.exit_code == 0
        assert "Starting 'test-app'" in result.output
        assert mock_run.called
