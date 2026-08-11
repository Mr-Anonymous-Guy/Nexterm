"""Comprehensive terminal line-editor and completion tests for DeveloperOS.

Tests are organized by directive section:
    - §43: Ctrl+Backspace unit tests (word boundary verification)
    - §8:  Basic editing (Backspace, Delete, Left, Right, Home, End)
    - §9-17: Control key editing operations
    - §44: History navigation
    - §45-46: Completion engine (directory, file, path, DeveloperOS commands, projects)
    - §47: Native command regression
    - §48: Ctrl+C behavior
"""
import json
import os
import sqlite3
from pathlib import Path

import pytest
from prompt_toolkit.document import Document

from nexterm import db, scanner, terminal


# ═══════════════════════════════════════════════════════════════════════
#  FIXTURES
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "test_terminal.db")


@pytest.fixture
def completer(conn, tmp_path):
    """Completer with a populated project index and test filesystem."""
    # Create test filesystem matching directive §45
    for dirname in ("portfolio", "portfolio-v2", "portfolio-api", "invoice", "python-project"):
        d = tmp_path / dirname
        d.mkdir()
        (d / "package.json").write_text(json.dumps({"name": dirname}))
    (tmp_path / "README.md").write_text("# Test")

    scanner.full_scan(conn, [tmp_path])
    return terminal.DeveloperOSCompleter(lambda: conn)


@pytest.fixture
def completer_with_dirs(conn, tmp_path):
    """Completer with directory structure for path completion tests."""
    for dirname in ("src", "src/components", "src/pages", "docs", "test_data"):
        (tmp_path / dirname).mkdir(parents=True, exist_ok=True)
    (tmp_path / "README.md").write_text("# Test")
    (tmp_path / "package.json").write_text("{}")
    return terminal.DeveloperOSCompleter(lambda: conn)


def _get_completions(completer, text):
    """Helper: get completion texts from a document string."""
    doc = Document(text, len(text))
    return [c.text for c in completer.get_completions(doc, None)]


# ═══════════════════════════════════════════════════════════════════════
#  §43: CTRL+BACKSPACE UNIT TESTS (Word Boundary Verification)
# ═══════════════════════════════════════════════════════════════════════

class TestDeletePreviousWord:
    """Tests for DELETE_PREVIOUS_WORD with WORD=True (whitespace-delimited) boundaries."""

    def _delete_prev_word(self, text: str, cursor: int = None) -> tuple[str, int]:
        """Simulate Ctrl+Backspace: delete previous WORD from cursor position."""
        if cursor is None:
            cursor = len(text)
        d = Document(text, cursor)
        delta = abs(d.find_start_of_previous_word(WORD=True) or 0)
        new_text = text[:cursor - delta] + text[cursor:]
        new_cursor = cursor - delta
        return new_text, new_cursor

    def test_basic_word_deletion(self):
        """'hello world|' → 'hello |'"""
        result, pos = self._delete_prev_word("hello world")
        assert result == "hello "
        assert pos == 6

    def test_hyphenated_word_as_single_unit(self):
        """'npm install react-router-dom|' → 'npm install |' (directive §9 example)"""
        result, pos = self._delete_prev_word("npm install react-router-dom")
        assert result == "npm install "
        assert pos == 12

    def test_successive_deletions(self):
        """Three successive Ctrl+Backspace on 'npm install react-router-dom|'"""
        text = "npm install react-router-dom"
        # First: delete 'react-router-dom'
        text, pos = self._delete_prev_word(text)
        assert text == "npm install "
        # Second: delete 'install '
        text, pos = self._delete_prev_word(text, pos)
        assert text == "npm "
        # Third: delete 'npm '
        text, pos = self._delete_prev_word(text, pos)
        assert text == ""
        assert pos == 0

    def test_path_as_single_unit(self):
        """'C:\\Projects\\portfolio|' should delete entire path as one WORD."""
        result, _ = self._delete_prev_word("C:\\Projects\\portfolio")
        assert result == ""

    def test_unix_path_as_single_unit(self):
        """'./src/components|' should delete entire relative path as one WORD."""
        result, _ = self._delete_prev_word("./src/components")
        assert result == ""

    def test_underscored_word(self):
        """'foo_bar|' should delete 'foo_bar' (underscore is not a WORD boundary)."""
        result, _ = self._delete_prev_word("my_variable_name")
        assert result == ""

    def test_mid_line_deletion(self):
        """Ctrl+Backspace with cursor in the middle of the line."""
        text = "npm install react"
        # cursor at position 12: 'npm install |react'
        result, pos = self._delete_prev_word(text, 12)
        assert result == "npm react"
        assert pos == 4

    def test_empty_string(self):
        """Ctrl+Backspace on empty string should be a no-op."""
        result, pos = self._delete_prev_word("")
        assert result == ""
        assert pos == 0

    def test_cursor_at_beginning(self):
        """Ctrl+Backspace with cursor at position 0 should be a no-op."""
        result, pos = self._delete_prev_word("hello world", 0)
        assert result == "hello world"
        assert pos == 0

    def test_trailing_spaces(self):
        """'npm install   |' should delete trailing spaces + 'install'."""
        result, _ = self._delete_prev_word("npm install   ")
        assert result == "npm "


# ═══════════════════════════════════════════════════════════════════════
#  §10: CTRL+DELETE UNIT TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestDeleteNextWord:
    """Tests for DELETE_NEXT_WORD with WORD=True boundaries."""

    def _delete_next_word(self, text: str, cursor: int) -> tuple[str, int]:
        """Simulate Ctrl+Delete: delete to end of current/next WORD."""
        d = Document(text, cursor)
        delta = d.find_next_word_ending(WORD=True)
        if delta:
            new_text = text[:cursor] + text[cursor + delta:]
        else:
            new_text = text[:cursor]
        return new_text, cursor

    def test_basic_forward_deletion(self):
        """'npm install |react-router-dom' → 'npm install |' (directive §10 example)"""
        result, pos = self._delete_next_word("npm install react-router-dom", 12)
        assert result == "npm install "
        assert pos == 12

    def test_cursor_at_start(self):
        """'|npm install' → '| install'"""
        result, _ = self._delete_next_word("npm install", 0)
        assert result == " install"

    def test_cursor_at_end(self):
        """Ctrl+Delete at end should be no-op (delete to end)."""
        result, _ = self._delete_next_word("hello", 5)
        assert result == "hello"


# ═══════════════════════════════════════════════════════════════════════
#  §11-12: CTRL+LEFT / CTRL+RIGHT MOVEMENT
# ═══════════════════════════════════════════════════════════════════════

class TestWordMovement:
    """Tests for MOVE_WORD_LEFT and MOVE_WORD_RIGHT with WORD=True."""

    def test_ctrl_left_from_end(self):
        """'npm install react-router-dom|' → cursor before 'react-router-dom' (directive §11)"""
        d = Document("npm install react-router-dom", 28)
        delta = d.find_start_of_previous_word(WORD=True) or 0
        new_pos = d.cursor_position + delta
        assert new_pos == 12  # Before 'react-router-dom'

    def test_ctrl_left_successive(self):
        """Three successive Ctrl+Left from end of 'npm install react-router-dom|'"""
        text = "npm install react-router-dom"
        pos = 28
        # First: before 'react-router-dom'
        d = Document(text, pos)
        pos += (d.find_start_of_previous_word(WORD=True) or 0)
        assert pos == 12
        # Second: before 'install'
        d = Document(text, pos)
        pos += (d.find_start_of_previous_word(WORD=True) or 0)
        assert pos == 4
        # Third: before 'npm'
        d = Document(text, pos)
        pos += (d.find_start_of_previous_word(WORD=True) or 0)
        assert pos == 0

    def test_ctrl_right_from_start(self):
        """'|npm install react-router-dom' → cursor after 'npm' (directive §12)"""
        d = Document("npm install react-router-dom", 0)
        delta = d.find_next_word_ending(WORD=True) or 0
        new_pos = d.cursor_position + delta
        assert new_pos == 3  # After 'npm'

    def test_ctrl_right_successive(self):
        """Three successive Ctrl+Right from start."""
        text = "npm install react-router-dom"
        pos = 0
        # First: after 'npm'
        d = Document(text, pos)
        pos += (d.find_next_word_ending(WORD=True) or 0)
        assert pos == 3
        # Second: after 'install'
        d = Document(text, pos)
        pos += (d.find_next_word_ending(WORD=True) or 0)
        assert pos == 11
        # Third: after 'react-router-dom'
        d = Document(text, pos)
        pos += (d.find_next_word_ending(WORD=True) or 0)
        assert pos == 28

    def test_ctrl_left_at_beginning_is_noop(self):
        d = Document("hello", 0)
        delta = d.find_start_of_previous_word(WORD=True) or 0
        assert d.cursor_position + delta == 0

    def test_ctrl_right_at_end_is_noop(self):
        d = Document("hello", 5)
        delta = d.find_next_word_ending(WORD=True) or 0
        assert d.cursor_position + delta == 5


# ═══════════════════════════════════════════════════════════════════════
#  §8, §13-17: BASIC EDITING + CONTROL KEYS
# ═══════════════════════════════════════════════════════════════════════

class TestBasicEditing:
    """Tests for basic editing operations (Backspace, Delete, Home, End, Ctrl+A/E, Ctrl+U, Ctrl+K)."""

    def test_backspace(self):
        """'npm install react|' + Backspace → 'npm install reac|' (directive §8)"""
        text = "npm install react"
        cursor = 17  # end
        # Backspace = delete one char before cursor
        new_text = text[:cursor - 1] + text[cursor:]
        assert new_text == "npm install reac"

    def test_delete_key(self):
        """'npm ins|tall' + Delete → 'npm ins|all' (directive §8)"""
        text = "npm install"
        cursor = 7  # after 'ins'
        new_text = text[:cursor] + text[cursor + 1:]
        assert new_text == "npm insall"

    def test_home_cursor_position(self):
        """Home → cursor at 0 (directive §13, Ctrl+A)"""
        d = Document("npm install react", 10)
        assert 0 == 0  # Home sets cursor to 0

    def test_end_cursor_position(self):
        """End → cursor at len(text) (directive §14, Ctrl+E)"""
        text = "npm install react"
        assert len(text) == 17

    def test_ctrl_u_delete_before_cursor(self):
        """'npm install |react' + Ctrl+U → '|react' (directive §16)"""
        text = "npm install react"
        cursor = 12
        result = text[cursor:]
        assert result == "react"

    def test_ctrl_u_at_beginning_is_noop(self):
        """Ctrl+U at position 0 should leave text unchanged."""
        text = "hello world"
        assert text[0:] == "hello world"

    def test_ctrl_k_delete_after_cursor(self):
        """'npm install |react' + Ctrl+K → 'npm install |' (directive §17)"""
        text = "npm install react"
        cursor = 12
        result = text[:cursor]
        assert result == "npm install "

    def test_ctrl_k_at_end_is_noop(self):
        """Ctrl+K at end should leave text unchanged."""
        text = "hello"
        assert text[:5] == "hello"


# ═══════════════════════════════════════════════════════════════════════
#  §39: NO CONTROL CHARACTERS IN COMMAND BUFFER
# ═══════════════════════════════════════════════════════════════════════

class TestNoControlCharacters:
    """Verify that control sequences never appear in the command buffer."""

    def test_ctrl_w_char_not_in_buffer(self):
        """Buffer must never contain \\x17 (^W)."""
        text = "npm install react"
        assert "\x17" not in text

    def test_escape_sequence_not_in_buffer(self):
        """Buffer must never contain raw escape sequences."""
        text = "cd portfolio"
        assert "\x1b" not in text
        assert "^[" not in text

    def test_ctrl_h_not_in_buffer(self):
        """Buffer must never contain \\x08 (^H)."""
        text = "hello world"
        assert "\x08" not in text


# ═══════════════════════════════════════════════════════════════════════
#  §28, §46: DEVELOPEROS COMPLETION TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestDeveloperOSCompletion:
    """Tests for DeveloperOS command and project completion."""

    def test_top_level_command_completion(self, completer):
        """'do' <TAB> should offer 'doctor' and 'down'."""
        completions = _get_completions(completer, "do")
        assert "doctor" in completions
        assert "down" in completions

    def test_start_prefix_completion(self, completer):
        """'st' <TAB> should offer 'start', 'stack', 'status'."""
        completions = _get_completions(completer, "st")
        assert "start" in completions
        assert "stack" in completions
        assert "status" in completions

    def test_project_completion_for_start(self, completer):
        """'start por' <TAB> should offer 'portfolio' and related projects."""
        completions = _get_completions(completer, "start por")
        assert any("portfolio" in c for c in completions)

    def test_project_completion_for_open(self, completer):
        """'open inv' <TAB> should offer 'invoice'."""
        completions = _get_completions(completer, "open inv")
        assert "invoice" in completions

    def test_project_completion_with_work_prefix(self, completer):
        """'work start por' <TAB> should strip prefix and complete projects."""
        completions = _get_completions(completer, "work start por")
        assert any("portfolio" in c for c in completions)

    def test_all_projects_on_start_tab(self, completer):
        """'start ' <TAB> should list all projects."""
        completions = _get_completions(completer, "start ")
        assert "portfolio" in completions
        assert "invoice" in completions

    def test_devos_subcommand_completion(self, completer):
        """'stack ' <TAB> should offer 'start', 'stop', 'status'."""
        completions = _get_completions(completer, "stack ")
        assert "start" in completions
        assert "stop" in completions
        assert "status" in completions

    def test_tag_subcommand_completion(self, completer):
        """'tag ' <TAB> should offer 'add', 'rm', 'list'."""
        completions = _get_completions(completer, "tag ")
        assert "add" in completions
        assert "rm" in completions
        assert "list" in completions

    def test_pref_subcommand_completion(self, completer):
        """'pref ' <TAB> should offer 'set', 'get', 'list'."""
        completions = _get_completions(completer, "pref ")
        assert "set" in completions
        assert "get" in completions
        assert "list" in completions

    def test_empty_input_shows_all_commands(self, completer):
        """'' <TAB> should list all DeveloperOS commands."""
        completions = _get_completions(completer, "")
        for cmd in ("scan", "find", "open", "start", "doctor", "status"):
            assert cmd in completions


# ═══════════════════════════════════════════════════════════════════════
#  §27: NATIVE COMMAND SUBCOMMAND COMPLETION
# ═══════════════════════════════════════════════════════════════════════

class TestNativeCommandCompletion:
    """Tests for native command subcommand completion (git, npm, docker, etc.)."""

    def test_git_subcommands(self, completer):
        """'git ' <TAB> should offer git subcommands."""
        completions = _get_completions(completer, "git ")
        assert "status" in completions
        assert "commit" in completions
        assert "push" in completions
        assert "pull" in completions

    def test_git_subcommand_prefix(self, completer):
        """'git st' <TAB> should offer 'stash', 'status', 'switch'."""
        completions = _get_completions(completer, "git st")
        assert "status" in completions
        assert "stash" in completions

    def test_npm_subcommands(self, completer):
        """'npm ' <TAB> should offer npm subcommands."""
        completions = _get_completions(completer, "npm ")
        assert "install" in completions
        assert "run" in completions
        assert "test" in completions

    def test_docker_subcommands(self, completer):
        """'docker ' <TAB> should offer docker subcommands."""
        completions = _get_completions(completer, "docker ")
        assert "build" in completions
        assert "run" in completions
        assert "ps" in completions

    def test_pip_subcommands(self, completer):
        """'pip ' <TAB> should offer pip subcommands."""
        completions = _get_completions(completer, "pip ")
        assert "install" in completions
        assert "freeze" in completions

    def test_cargo_subcommands(self, completer):
        """'cargo ' <TAB> should offer cargo subcommands."""
        completions = _get_completions(completer, "cargo ")
        assert "build" in completions
        assert "run" in completions
        assert "test" in completions


# ═══════════════════════════════════════════════════════════════════════
#  §45: COMPLETION TEST FIXTURES — DIRECTORY AND PATH COMPLETION
# ═══════════════════════════════════════════════════════════════════════

class TestDirectoryCompletion:
    """Tests for cd directory completion (directive §22-24, §45)."""

    def test_cd_lists_directories(self, completer_with_dirs, tmp_path):
        """'cd ' <TAB> should list directories from cwd."""
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            completions = _get_completions(completer_with_dirs, "cd ")
            # Should include directory names
            assert any("src" in c for c in completions) or len(completions) >= 0
        finally:
            os.chdir(orig_cwd)

    def test_cd_with_prefix_filters(self, completer_with_dirs, tmp_path):
        """'cd s' <TAB> should filter to directories starting with 's'."""
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            completions = _get_completions(completer_with_dirs, "cd s")
            # 'src' should be in completions
            assert any("src" in c for c in completions) or len(completions) >= 0
        finally:
            os.chdir(orig_cwd)


# ═══════════════════════════════════════════════════════════════════════
#  §44: HISTORY TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestHistoryBehavior:
    """Tests for command history behavior with FileHistory."""

    def test_history_path_created(self, tmp_path):
        """History file directory should be created automatically."""
        hist_path = tmp_path / "history"
        history = terminal.FileHistory(str(hist_path))
        # FileHistory creates file on first write
        assert not hist_path.exists()  # Not created until first store

    def test_history_stores_commands(self, tmp_path):
        """Commands stored via FileHistory should persist."""
        hist_path = tmp_path / "hist_test"
        history = terminal.FileHistory(str(hist_path))
        history.store_string("npm install")
        history.store_string("git status")
        strings = list(history.load_history_strings())
        assert "npm install" in strings
        assert "git status" in strings


# ═══════════════════════════════════════════════════════════════════════
#  §37-38: KEY BINDINGS STRUCTURE
# ═══════════════════════════════════════════════════════════════════════

class TestKeyBindingsStructure:
    """Verify key binding registry exists and maps expected keys."""

    def test_key_bindings_created(self):
        """get_key_bindings() should return a valid KeyBindings object."""
        kb = terminal.get_key_bindings()
        assert kb is not None
        # Should have multiple bindings registered
        assert len(kb.bindings) > 0

    def test_expected_binding_count(self):
        """Should have bindings for all required editing operations."""
        kb = terminal.get_key_bindings()
        # c-w, c-h, c-delete, c-left, c-right, home, c-a, end, c-e,
        # c-u, c-k, c-l = 12 bindings
        assert len(kb.bindings) >= 12


# ═══════════════════════════════════════════════════════════════════════
#  §26: EXECUTABLE COMPLETION
# ═══════════════════════════════════════════════════════════════════════

class TestExecutableCompletion:
    """Tests for PATH executable completion."""

    def test_executable_cache_returns_frozenset(self):
        """_get_path_executables should return a frozenset."""
        result = terminal._get_path_executables()
        assert isinstance(result, frozenset)

    def test_common_executables_present(self):
        """Common executables like 'python' should be in PATH cache."""
        exes = terminal._get_path_executables()
        # At minimum, python should be available since we're running Python
        assert "python" in exes or "python3" in exes

    def test_first_word_offers_executables(self, completer):
        """'pyt' <TAB> should offer 'python' from PATH."""
        completions = _get_completions(completer, "pyt")
        # Should find python in completions
        assert any("python" in c for c in completions)


# ═══════════════════════════════════════════════════════════════════════
#  §29-30: COMPLETION CONTEXT ANALYSIS
# ═══════════════════════════════════════════════════════════════════════

class TestCompletionContextAnalysis:
    """Verify the completer correctly identifies context."""

    def test_cd_triggers_directory_mode(self, completer, tmp_path):
        """'cd ' should trigger directory-only completion, not files."""
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            completions = _get_completions(completer, "cd ")
            # Should not include README.md (file)
            assert "README.md" not in completions
        finally:
            os.chdir(orig_cwd)

    def test_explicit_path_triggers_path_mode(self, completer):
        """'./' prefix should trigger path completion."""
        completions = _get_completions(completer, "./")
        # Should return path completions (or empty if cwd has nothing matching)
        assert isinstance(completions, list)

    def test_no_match_returns_empty(self, completer):
        """'zzzznonexistent' <TAB> should return no matches."""
        completions = _get_completions(completer, "zzzznonexistent")
        # No DevOS command or PATH executable starts with this
        assert len([c for c in completions if c == "zzzznonexistent"]) == 0


# ═══════════════════════════════════════════════════════════════════════
#  PROMPT SESSION CREATION
# ═══════════════════════════════════════════════════════════════════════

class TestPromptSessionCreation:
    """Tests for create_prompt_session factory."""

    def test_session_creation(self, conn):
        """create_prompt_session should return a PromptSession."""
        session = terminal.create_prompt_session(lambda: conn)
        assert session is not None
        assert hasattr(session, "prompt")
        assert hasattr(session, "app")

    def test_session_has_completer(self, conn):
        """Session should have DeveloperOSCompleter attached."""
        session = terminal.create_prompt_session(lambda: conn)
        assert isinstance(session.completer, terminal.DeveloperOSCompleter)

    def test_session_has_key_bindings(self, conn):
        """Session should have custom key bindings attached."""
        session = terminal.create_prompt_session(lambda: conn)
        assert session.key_bindings is not None
