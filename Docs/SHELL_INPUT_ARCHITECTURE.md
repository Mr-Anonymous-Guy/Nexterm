# DeveloperOS — Shell Input & Terminal Line-Editing Architecture

## 1. Current Implementation

The interactive shell in `developeros/cli.py` uses `prompt_toolkit` (v3.0+) `PromptSession` for all interactive input, replacing the original `input()` call. The terminal subsystem lives in `developeros/terminal.py`.

- **Input Reading**: `prompt_toolkit.shortcuts.PromptSession.prompt()` — raw terminal mode with platform-native key event decoding.
- **Command Router**: Parses input with `shlex.split()` and dispatches to Click subcommand handlers or `subprocess.run(line, shell=True)` for native system commands.
- **Directory Navigation**: Custom `_handle_cd()` function mutating `os.chdir()` with support for `cd..`, `cd,,`, `cd~`, `cd-`, `cd/`, `cd\` variants.
- **History**: `prompt_toolkit.history.FileHistory` persisting to `~/.developeros/history`.
- **Completion**: Custom `DeveloperOSCompleter` implementing context-aware Tab completion.
- **Key Bindings**: Custom `KeyBindings` registry normalizing Ctrl+Backspace, Ctrl+Delete, Ctrl+Left/Right, Home/End, Ctrl+A/E/W/U/K/L into semantic editing operations.

---

## 2. Previous Limitations (Now Resolved)

1. ~~**Control Key Interpretation Failure**: Ctrl+Backspace produced `^W`~~ → Fixed via `prompt_toolkit` raw key event handling.
2. ~~**Missing Tab Completion**~~ → Full context-aware completion engine with commands, projects, paths, executables, and native subcommands.
3. ~~**No Cursor Word Movements**: Ctrl+Left/Right ignored~~ → Custom `c-left`/`c-right` bindings with `WORD=True`.
4. ~~**Line Redraw Corruption**~~ → `prompt_toolkit` renderer handles all cursor management.
5. ~~**No History Navigation**~~ → `FileHistory` with Up/Down arrow support across sessions.

---

## 3. Root Cause of `Ctrl+Backspace` Producing `^W`

On Windows console applications operating in line-buffered input mode (standard C runtime `stdin`), `Ctrl+Backspace` generates ASCII 23 (`0x17`, `ETB`), rendered as `^W`.

Standard `input()` reads until newline without intercepting key-down events at the raw terminal layer. The `0x17` byte is placed directly into the stdin buffer as a literal character.

**Resolution**: `prompt_toolkit` operates in raw terminal mode. Its `Win32Input` backend reads `ReadConsoleInputW` key events directly. `Ctrl+Backspace` is decoded as the semantic key `c-w`, which our `KeyBindings` handler maps to `delete_previous_word()` with `WORD=True` boundaries. The control character never reaches the command buffer.

---

## 4. Architecture

```
                     DeveloperOS Interactive Shell
                                  │
                                  ▼
                        PromptSession (prompt_toolkit)
                                  │
                ┌─────────────────┴─────────────────┐
                ▼                                   ▼
         Terminal Input Layer              Key Binding Registry
        (Win32Input / Vt100Input)          (Semantic KeyEvent Map)
                │                                   │
                ▼                                   ▼
         Raw Key Decoder               Line Editor Buffer + Document
                │                      (cursor, text, WORD boundaries)
                └─────────────────┬─────────────────┘
                                  ▼
                         CompletionEngine
                      (DeveloperOSCompleter)
              ┌──────────┬──────────┬──────────┐
              ▼          ▼          ▼          ▼
        DevOS Cmds  Project DB  Native Cmds  PATH/Dir/File
        (25 cmds)   (SQLite)   (git/npm/     (PathCompleter
                                docker)       +DirCompleter)
              └──────────┴──────────┴──────────┘
                                  ▼
                        Formatted Command Buffer
                                  │
                        ┌─────────┴─────────┐
                        ▼                   ▼
                DeveloperOS Engine   OS Native Process
                (Click commands)     (subprocess.run)
```

---

## 5. Input Decoding Strategy

Platform key events are decoded in raw terminal mode:

- **Windows**: `prompt_toolkit.input.win32.Win32Input` using Windows Console API `ReadConsoleInputW` / ConPTY.
- **Unix / macOS**: `prompt_toolkit.input.vt100.Vt100Input` using `termios` raw mode and VT escape sequences.

### Normalized Key Events (Semantic)

| Raw Input | Semantic Event | Line Editor Action |
|:---|:---|:---|
| `Ctrl+Backspace` / `Ctrl+W` | `c-w` | `DELETE_PREVIOUS_WORD` (WORD=True) |
| `Ctrl+Delete` | `c-delete` | `DELETE_NEXT_WORD` (WORD=True) |
| `Ctrl+Left` | `c-left` | `MOVE_WORD_LEFT` (WORD=True) |
| `Ctrl+Right` | `c-right` | `MOVE_WORD_RIGHT` (WORD=True) |
| `Home` / `Ctrl+A` | `home` / `c-a` | `MOVE_HOME` (cursor → 0) |
| `End` / `Ctrl+E` | `end` / `c-e` | `MOVE_END` (cursor → len) |
| `Ctrl+U` | `c-u` | `DISCARD_LINE_BEFORE_CURSOR` |
| `Ctrl+K` | `c-k` | `DISCARD_LINE_AFTER_CURSOR` |
| `Ctrl+L` | `c-l` | `CLEAR_SCREEN` (redraw prompt) |
| `Ctrl+C` | `c-c` | `INTERRUPT` (cancel input or signal child) |
| `Ctrl+H` | `c-h` | `DELETE_PREVIOUS_WORD` (WORD=True, alias) |
| `Up` / `Down` | `up` / `down` | `HISTORY_PREVIOUS` / `HISTORY_NEXT` |
| `Left` / `Right` | `left` / `right` | `CURSOR_LEFT` / `CURSOR_RIGHT` |
| `Backspace` | `backspace` | `DELETE_CHAR_BEFORE_CURSOR` |
| `Delete` | `delete` | `DELETE_CHAR_AFTER_CURSOR` |
| `Tab` | `tab` | `COMPLETE` |

---

## 6. Line-Editor Strategy

### Word Boundary Policy: `WORD=True` (Whitespace-Delimited)

All word-level operations (Ctrl+Backspace, Ctrl+Delete, Ctrl+Left, Ctrl+Right) use `WORD=True` mode:

- Word boundaries are **whitespace only**
- `react-router-dom` is treated as **ONE word**
- `C:\Projects\portfolio` is treated as **ONE word**
- `./src/components` is treated as **ONE word**
- `foo_bar_baz` is treated as **ONE word**

This matches the behavior expected in the directive §9:
```
npm install react-router-dom|
    Ctrl+Backspace →
npm install |
    Ctrl+Backspace →
npm |
    Ctrl+Backspace →
|
```

### Buffer Model

The line editor (via `prompt_toolkit.buffer.Buffer`) maintains:
- Unicode string buffer (`.text`)
- 0-indexed cursor position (`.cursor_position`)
- Document object (`.document`) providing word search methods
- Selection state
- History reference

The buffer is logically independent from terminal rendering.

---

## 7. Completion Strategy (`DeveloperOSCompleter`)

Context-aware completion engine with 7 completion providers:

### 7.1 DeveloperOS Commands (First Word)
Completes top-level subcommands: `scan`, `find`, `open`, `start`, `clone`, `tag`, `doctor`, `nl`, `up`, `down`, `logs`, `stack`, `ship`, `ai`, `ask`, `explain`, `fix`, `repo`, `pref`, `daemon`, `status`, `shell`, `exit`, `quit`, `clear`.

### 7.2 DeveloperOS Subcommands
For compound commands (`stack`, `tag`, `ai`, `repo`, `pref`, `daemon`), completes their subcommands (e.g., `stack start|stop|status`).

### 7.3 Project Completion
When the command is `start`, `open`, `doctor`, `explain`, `fix`, `up`, `down`, `stack`, `ship`, `tag` (or after their subcommands), queries the SQLite `projects` table to offer indexed project names.

### 7.4 Directory Completion (cd)
For `cd`, restricts candidates to directories only (`only_directories=True`).

### 7.5 Native Command Subcommands
For `git`, `docker`, `npm`, `pip`, `python`, `node`, `cargo`, completes their subcommands from a static registry.

### 7.6 Executable Completion (PATH)
For first-word input, scans PATH executables (cached via `@lru_cache` per session) to offer completions like `pyt` → `python`.

### 7.7 Path/File Completion (Fallback)
For general command arguments, completes files and directories.

---

## 8. Rendering Strategy

- ANSI/VT100 screen buffer management via `prompt_toolkit`'s renderer.
- Completion candidates displayed in a dropdown menu below the prompt (6 rows reserved).
- Automatic line wrapping for long commands.
- Terminal resize events (`SIGWINCH` / `WINDOW_BUFFER_SIZE_EVENT`) trigger full redraw.

---

## 9. Windows Strategy

- Win32 API integration via `prompt_toolkit.input.win32.Win32Input`.
- Supports Windows Terminal, PowerShell, CMD, and ConPTY.
- Windows path backslashes (`\`) handled cleanly without shell escape corruption.
- Safe output fallback (`DummyOutput`) prevents `NoConsoleScreenBufferError` when stdio is piped.

---

## 10. Linux / macOS Strategy

- Native `termios` raw mode handling via `prompt_toolkit.input.vt100.Vt100Input`.
- Full VT100/xterm escape sequence support.
- `SIGWINCH` signal handler for terminal resize.

---

## 11. Testing Strategy

### Unit Tests (83 tests total)

- **Word Boundary State Machine** (10 tests): Verify `WORD=True` delete-previous-word behavior with hyphens, paths, underscores, trailing spaces, empty strings, mid-line cursor.
- **Forward Deletion** (3 tests): Ctrl+Delete at start, middle, end of buffer.
- **Word Movement** (6 tests): Ctrl+Left and Ctrl+Right successive movement, boundary behavior.
- **Basic Editing** (8 tests): Backspace, Delete, Home, End, Ctrl+A/E, Ctrl+U, Ctrl+K.
- **Control Character Sanitization** (3 tests): Verify no `^W`, `^H`, `^[` in buffer.
- **DeveloperOS Completion** (10 tests): Command, subcommand, project completion with prefix filtering.
- **Native Command Completion** (6 tests): git, npm, docker, pip, cargo subcommands.
- **Directory Completion** (2 tests): cd directory listing and prefix filtering.
- **History** (2 tests): FileHistory creation and persistence.
- **Key Bindings** (2 tests): Registry structure verification.
- **Executable Completion** (3 tests): PATH cache, python detection, first-word integration.
- **Context Analysis** (3 tests): cd triggers dir mode, explicit path triggers path mode.
- **Session Creation** (3 tests): Factory, completer, key bindings attached.

### Regression Tests
- All 22 original `test_core.py` tests continue passing.

---

## 12. Known Limitations

1. **PATH Executable Cache**: Computed once per session via `@lru_cache`. New executables installed during a session won't appear until restart.
2. **Native Subcommand Registry**: Static list. Dynamic subcommand discovery (e.g., `npm run <TAB>` showing package.json scripts) is not yet implemented.
3. **Reverse History Search**: `Ctrl+R` for incremental reverse search relies on `prompt_toolkit`'s built-in behavior. Not customized.
