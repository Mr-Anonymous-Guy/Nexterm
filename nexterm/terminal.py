"""Terminal line editor, keyboard bindings, and context-aware completion subsystem for DeveloperOS.

Architecture:
    DeveloperOS Interactive Shell
        │
        ├── TerminalBackend (prompt_toolkit PromptSession)
        │       ├── Win32Input (Windows) / Vt100Input (Unix/macOS)
        │       └── ANSI/VT100 Output + Resize handling
        │
        ├── Key Decoder & Keymap (get_key_bindings)
        │       ├── Ctrl+Backspace / Ctrl+W → DELETE_PREVIOUS_WORD
        │       ├── Ctrl+Delete           → DELETE_NEXT_WORD
        │       ├── Ctrl+Left             → MOVE_WORD_LEFT
        │       ├── Ctrl+Right            → MOVE_WORD_RIGHT
        │       ├── Home / Ctrl+A         → MOVE_HOME
        │       ├── End / Ctrl+E          → MOVE_END
        │       ├── Ctrl+U               → DISCARD_LINE_BEFORE_CURSOR
        │       ├── Ctrl+K               → DISCARD_LINE_AFTER_CURSOR
        │       └── Ctrl+L               → CLEAR_SCREEN
        │
        ├── LineEditor (prompt_toolkit Buffer + Document)
        │       ├── Unicode text buffer with cursor position
        │       ├── Word boundary policy: WORD=True (whitespace-delimited)
        │       └── Independent of terminal rendering
        │
        ├── HistoryManager (FileHistory → ~/.developeros/history)
        │
        ├── CompletionEngine (DeveloperOSCompleter)
        │       ├── CommandContextAnalyzer (token parsing)
        │       ├── DirectoryCompleter (cd → dirs only)
        │       ├── FileCompleter / PathCompleter (general args)
        │       ├── ExecutableCompleter (PATH scan, cached)
        │       ├── NativeCommandCompleter (git/npm/docker subcommands)
        │       ├── DeveloperOSCommandCompleter (top-level commands)
        │       └── ProjectCompleter (SQLite project index)
        │
        └── PromptRenderer (prompt_toolkit default renderer)
                ├── Completion dropdown menu
                ├── Line wrapping support
                └── Terminal resize handling (SIGWINCH / WINDOW_BUFFER_SIZE_EVENT)

Word Boundary Policy:
    All Ctrl+Backspace, Ctrl+Delete, Ctrl+Left, Ctrl+Right operations use
    WORD=True (whitespace-delimited) boundaries. This means:
        "npm install react-router-dom|" + Ctrl+Backspace → "npm install |"
        "C:\\Projects\\portfolio|" + Ctrl+Backspace → "|"
    This matches standard terminal behavior where Ctrl+W deletes back to
    the previous whitespace.

Key Event Normalization:
    Platform-specific raw input (Win32 Console API, VT100 escape sequences)
    is normalized by prompt_toolkit into semantic key events. Our custom
    KeyBindings layer maps these to editing operations, ensuring no raw
    control characters (^W, ^H, ^[, etc.) leak into the command buffer.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Callable, Optional

from prompt_toolkit.completion import Completer, Completion, PathCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.shortcuts import PromptSession
from prompt_toolkit.styles import Style
from prompt_toolkit.output import DummyOutput, create_output

from . import db

DEFAULT_HISTORY_PATH = db.DEFAULT_DB_DIR / "history"

# ── DeveloperOS command registry ─────────────────────────────────────
DEVOS_TOP_COMMANDS = [
    "scan", "find", "open", "start", "clone", "tag", "doctor", "nl",
    "up", "down", "logs", "stack", "ship", "ai", "ask", "explain",
    "fix", "repo", "pref", "daemon", "status", "errors", "release", "guardian", "check", "shell", "exit", "quit", "clear",
]

PROJECT_COMMANDS = {
    "start", "open", "doctor", "explain", "fix", "up", "down",
    "stack", "ship", "tag",
}

# ── Native command subcommand definitions (extensible) ───────────────
NATIVE_SUBCOMMANDS: dict[str, list[str]] = {
    "git": [
        "add", "bisect", "branch", "checkout", "clone", "commit", "config",
        "diff", "fetch", "grep", "init", "log", "merge", "mv", "pull",
        "push", "rebase", "remote", "reset", "restore", "rm", "show",
        "stash", "status", "switch", "tag", "worktree",
    ],
    "docker": [
        "build", "compose", "container", "create", "exec", "image",
        "images", "inspect", "kill", "logs", "network", "ps", "pull",
        "push", "rm", "rmi", "run", "start", "stop", "system", "tag",
        "volume",
    ],
    "npm": [
        "access", "audit", "cache", "ci", "config", "create", "dedupe",
        "diff", "dist-tag", "docs", "exec", "explain", "explore",
        "fund", "init", "install", "link", "list", "login", "logout",
        "outdated", "pack", "ping", "pkg", "prefix", "prune", "publish",
        "rebuild", "repo", "restart", "root", "run", "search", "set",
        "start", "stop", "test", "token", "uninstall", "unpublish",
        "update", "version", "view",
    ],
    "pip": [
        "install", "uninstall", "freeze", "list", "show", "check",
        "download", "wheel", "hash", "search", "config", "debug",
        "cache", "index", "inspect",
    ],
    "python": ["-c", "-m", "--version", "--help"],
    "node": ["-e", "-p", "--version", "--help"],
    "cargo": [
        "add", "bench", "build", "check", "clean", "clippy", "doc",
        "fetch", "fix", "fmt", "init", "install", "new", "publish",
        "remove", "run", "search", "test", "tree", "update",
    ],
}

# DeveloperOS subcommand argument types
DEVOS_SUBCOMMANDS: dict[str, list[str]] = {
    "stack": ["start", "stop", "status"],
    "tag": ["add", "rm", "list"],
    "ai": ["install", "list", "remove"],
    "repo": ["status"],
    "pref": ["set", "get", "list"],
    "daemon": ["start", "stop", "status"],
    "release": ["check", "build", "verify"],
    "guardian": ["check", "run", "install-hook", "remove-hook", "status"],
}


# ── Executable PATH cache ────────────────────────────────────────────
@lru_cache(maxsize=1)
def _get_path_executables() -> frozenset[str]:
    """Cache the set of executable basenames from PATH (computed once per session)."""
    executables: set[str] = set()
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    extensions = {".exe", ".cmd", ".bat", ".com", ".ps1"} if os.name == "nt" else {""}

    for d in path_dirs:
        try:
            for entry in os.scandir(d):
                if entry.is_file():
                    name = entry.name
                    if os.name == "nt":
                        stem, ext = os.path.splitext(name)
                        if ext.lower() in extensions:
                            executables.add(stem.lower())
                    else:
                        if os.access(entry.path, os.X_OK):
                            executables.add(name)
        except (PermissionError, FileNotFoundError, OSError):
            continue

    return frozenset(executables)


# ═══════════════════════════════════════════════════════════════════════
#  COMPLETION ENGINE
# ═══════════════════════════════════════════════════════════════════════

class DeveloperOSCompleter(Completer):
    """Context-aware completion engine for DeveloperOS interactive shell.

    Completion context analysis:
        1. Empty or first token → DeveloperOS commands + PATH executables
        2. "cd <TAB>" → directory-only completion
        3. "start <TAB>" / "open <TAB>" etc. → project name completion
        4. "git <TAB>" / "npm <TAB>" etc. → native subcommand completion
        5. Explicit paths (./, ../, C:\\, /) → path/file completion
        6. General arguments → path/file fallback completion

    The completer never triggers expensive operations on every keystroke.
    PATH scanning is cached. Project queries hit a local SQLite index.
    """

    def __init__(self, conn_factory: Callable[[], sqlite3.Connection]):
        self.conn_factory = conn_factory
        self._path_completer = PathCompleter(expanduser=True)
        self._dir_completer = PathCompleter(only_directories=True, expanduser=True)

    def _get_project_names(self) -> list[str]:
        """Query indexed project names from SQLite (fast local lookup)."""
        try:
            conn = self.conn_factory()
            rows = conn.execute("SELECT name FROM projects WHERE is_active = 1").fetchall()
            return [r["name"] for r in rows]
        except Exception:
            return []

    def _complete_path(
        self,
        sub_text: str,
        word_before_cursor: str,
        completer: PathCompleter,
        complete_event,
    ) -> Iterable[Completion]:
        """Delegate path completion to prompt_toolkit's PathCompleter with correct sub-document."""
        sub_doc = Document(sub_text, cursor_position=len(sub_text))
        for c in completer.get_completions(sub_doc, complete_event):
            yield Completion(c.text, start_position=-len(word_before_cursor), display=c.display)

    def _complete_static_list(
        self,
        candidates: list[str],
        prefix: str,
    ) -> Iterable[Completion]:
        """Complete from a static list of candidates filtered by prefix."""
        for item in candidates:
            if item.lower().startswith(prefix.lower()):
                yield Completion(item, start_position=-len(prefix))

    def get_completions(self, document: Document, complete_event) -> Iterable[Completion]:
        text_before_cursor = document.text_before_cursor
        # Use WORD boundary for the word fragment (captures hyphens, dots, slashes)
        word_before_cursor = document.get_word_before_cursor(WORD=True)

        # Strip leading prompt prefixes if user typed "worksapce start" etc.
        cleaned_text = text_before_cursor.lstrip()
        for prefix in ("nexterm ", "worksapce ", "workspace ", "work ", "developeros "):
            if cleaned_text.lower().startswith(prefix):
                cleaned_text = cleaned_text[len(prefix):].lstrip()
                break

        tokens = cleaned_text.split()
        ends_with_space = text_before_cursor.endswith(" ")
        is_first_word = len(tokens) == 0 or (len(tokens) == 1 and not ends_with_space)

        # ── 1. Directory-only completion for `cd` ────────────────────
        if cleaned_text.lower().startswith("cd ") or cleaned_text.lower() == "cd":
            sub_text = cleaned_text[3:] if cleaned_text.lower().startswith("cd ") else ""
            yield from self._complete_path(sub_text, word_before_cursor, self._dir_completer, complete_event)
            return

        # ── 2. Explicit path completion (./, ../, C:\, /, ~) ─────────
        if word_before_cursor and any(
            word_before_cursor.startswith(p) for p in ("./", ".\\", "../", "..\\", "/", "~", "C:\\", "D:\\", "E:\\")
        ):
            yield from self._complete_path(word_before_cursor, word_before_cursor, self._path_completer, complete_event)
            return

        # ── 3. First word: DeveloperOS commands + PATH executables ───
        if is_first_word:
            prefix = word_before_cursor
            # DeveloperOS commands
            yield from self._complete_static_list(DEVOS_TOP_COMMANDS, prefix)
            # PATH executables (cached)
            if prefix:
                try:
                    for exe in sorted(_get_path_executables()):
                        if exe.startswith(prefix.lower()) and exe not in DEVOS_TOP_COMMANDS:
                            yield Completion(exe, start_position=-len(prefix))
                except Exception:
                    pass
            return

        first_token = tokens[0].lower()

        # ── 4. DeveloperOS subcommand completion (stack start, tag add, etc.) ─
        if first_token in DEVOS_SUBCOMMANDS and len(tokens) == 1 and ends_with_space:
            yield from self._complete_static_list(DEVOS_SUBCOMMANDS[first_token], "")
            return
        if first_token in DEVOS_SUBCOMMANDS and len(tokens) == 2 and not ends_with_space:
            yield from self._complete_static_list(DEVOS_SUBCOMMANDS[first_token], tokens[1])
            return

        # ── 5. Project name completion for project-aware commands ────
        if first_token in PROJECT_COMMANDS:
            projects = self._get_project_names()
            prefix = word_before_cursor if not ends_with_space else ""
            yield from self._complete_static_list(projects, prefix)
            return

        # After subcommand of stack/tag, complete with project names
        if first_token in ("stack", "tag") and len(tokens) >= 2:
            projects = self._get_project_names()
            prefix = word_before_cursor if not ends_with_space else ""
            yield from self._complete_static_list(projects, prefix)
            return

        # ── 6. Native command subcommand completion ──────────────────
        if first_token in NATIVE_SUBCOMMANDS:
            if len(tokens) == 1 and ends_with_space:
                yield from self._complete_static_list(NATIVE_SUBCOMMANDS[first_token], "")
                return
            if len(tokens) == 2 and not ends_with_space:
                yield from self._complete_static_list(NATIVE_SUBCOMMANDS[first_token], tokens[1])
                return

        # ── 7. Default fallback: Path/file completion for arguments ──
        sub_text = word_before_cursor if word_before_cursor else ""
        yield from self._complete_path(sub_text, word_before_cursor, self._path_completer, complete_event)


# ═══════════════════════════════════════════════════════════════════════
#  KEYMAP — Semantic key event to line-editor action bindings
# ═══════════════════════════════════════════════════════════════════════

def get_key_bindings() -> KeyBindings:
    """Build normalized key bindings for professional terminal line editing.

    Key Event Model (semantic, platform-independent):
        Ctrl+Backspace / Ctrl+W  → DELETE_PREVIOUS_WORD
        Ctrl+Delete              → DELETE_NEXT_WORD
        Ctrl+Left                → MOVE_WORD_LEFT
        Ctrl+Right               → MOVE_WORD_RIGHT
        Home / Ctrl+A            → MOVE_HOME
        End / Ctrl+E             → MOVE_END
        Ctrl+U                   → DISCARD_LINE_BEFORE_CURSOR
        Ctrl+K                   → DISCARD_LINE_AFTER_CURSOR
        Ctrl+L                   → CLEAR_SCREEN

    Word Boundary Policy:
        WORD=True — boundaries are whitespace only.
        "react-router-dom" is ONE word.
        "C:\\Projects\\portfolio" is ONE word.
        Matches standard Ctrl+W terminal behavior.

    The raw control character (0x17 for Ctrl+W, 0x08 for Ctrl+H) is consumed
    by the key binding handler and NEVER inserted into the command buffer.
    """
    kb = KeyBindings()

    # ── DELETE_PREVIOUS_WORD: Ctrl+Backspace / Ctrl+W / Ctrl+H ───────
    @kb.add("c-w")
    @kb.add("c-h")
    def _delete_previous_word(event):
        """Delete from cursor back to previous whitespace boundary."""
        buf = event.current_buffer
        delta = abs(buf.document.find_start_of_previous_word(count=event.arg, WORD=True) or 0)
        if delta > 0:
            buf.delete_before_cursor(count=delta)

    # ── DELETE_NEXT_WORD: Ctrl+Delete ────────────────────────────────
    @kb.add("c-delete")
    def _delete_next_word(event):
        """Delete from cursor forward to end of current/next word."""
        buf = event.current_buffer
        delta = buf.document.find_next_word_ending(count=event.arg, WORD=True)
        if delta:
            buf.delete(count=delta)

    # ── MOVE_WORD_LEFT: Ctrl+Left ────────────────────────────────────
    @kb.add("c-left")
    def _move_word_left(event):
        """Move cursor to the start of the previous whitespace-delimited word."""
        buf = event.current_buffer
        delta = buf.document.find_start_of_previous_word(count=event.arg, WORD=True) or 0
        buf.cursor_position += delta

    # ── MOVE_WORD_RIGHT: Ctrl+Right ──────────────────────────────────
    @kb.add("c-right")
    def _move_word_right(event):
        """Move cursor to the end of the current/next whitespace-delimited word."""
        buf = event.current_buffer
        delta = buf.document.find_next_word_ending(count=event.arg, WORD=True) or 0
        buf.cursor_position += delta

    # ── MOVE_HOME: Home / Ctrl+A ─────────────────────────────────────
    @kb.add("home")
    @kb.add("c-a")
    def _move_home(event):
        """Move cursor to position 0 (beginning of line)."""
        event.current_buffer.cursor_position = 0

    # ── MOVE_END: End / Ctrl+E ───────────────────────────────────────
    @kb.add("end")
    @kb.add("c-e")
    def _move_end(event):
        """Move cursor to end of buffer text."""
        event.current_buffer.cursor_position = len(event.current_buffer.text)

    # ── DISCARD_LINE_BEFORE_CURSOR: Ctrl+U ───────────────────────────
    @kb.add("c-u")
    def _discard_before(event):
        """Delete everything before cursor, keep text after cursor."""
        buf = event.current_buffer
        pos = buf.cursor_position
        buf.text = buf.text[pos:]
        buf.cursor_position = 0

    # ── DISCARD_LINE_AFTER_CURSOR: Ctrl+K ────────────────────────────
    @kb.add("c-k")
    def _discard_after(event):
        """Delete everything after cursor, keep text before cursor."""
        buf = event.current_buffer
        buf.text = buf.text[:buf.cursor_position]

    # ── CLEAR_SCREEN: Ctrl+L ─────────────────────────────────────────
    @kb.add("c-l")
    def _clear_screen(event):
        """Clear terminal screen and redraw prompt (preserves buffer/history/cwd)."""
        event.app.renderer.clear()

    return kb


# ═══════════════════════════════════════════════════════════════════════
#  PROMPT SESSION FACTORY
# ═══════════════════════════════════════════════════════════════════════

def create_prompt_session(conn_factory: Callable[[], sqlite3.Connection]) -> PromptSession:
    """Create a configured prompt_toolkit PromptSession.

    Integrates:
        - FileHistory for persistent command recall (Up/Down arrows)
        - DeveloperOSCompleter for context-aware Tab completion
        - Custom KeyBindings for professional line editing
        - Safe output fallback for non-console environments

    Terminal resize events are handled automatically by prompt_toolkit's
    renderer, which responds to SIGWINCH (Unix) / WINDOW_BUFFER_SIZE_EVENT
    (Windows) and redraws the prompt, buffer, and completion menu correctly.
    """
    db.DEFAULT_DB_DIR.mkdir(parents=True, exist_ok=True)
    history = FileHistory(str(DEFAULT_HISTORY_PATH))
    completer = DeveloperOSCompleter(conn_factory)
    bindings = get_key_bindings()

    # Safe output creation: prevents NoConsoleScreenBufferError when
    # stdio is piped or running in non-console contexts (CI, subprocess).
    try:
        if sys.stdout.isatty():
            output = create_output()
        else:
            output = DummyOutput()
    except Exception:
        output = DummyOutput()

    return PromptSession(
        completer=completer,
        complete_while_typing=False,  # Require TAB for completion (standard shell UX)
        history=history,
        key_bindings=bindings,
        output=output,
        reserve_space_for_menu=6,  # Room for completion dropdown
    )
