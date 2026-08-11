# Nexterm

> **The Local Developer Operating System CLI.**  
> Address your software projects **by name** across workspaces, automate environment setup, defend repositories with pre-push hooks, edit commands with terminal line controls, and release packages securely.

[![Python Version](https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://pypi.org/project/nexterm/)
[![PyPI Package](https://img.shields.io/pypi/v/nexterm.svg)](https://pypi.org/project/nexterm/)
[![Build Status](https://img.shields.io/github/actions/workflow/status/Mr-Anonymous-Guy/Nexterm/guardian_ci.yml?branch=main&label=guardian%20ci)](https://github.com/Mr-Anonymous-Guy/Nexterm/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 🚀 Installation

Install the package directly from [PyPI](https://pypi.org/project/nexterm/):

```bash
pip install nexterm
```

This installs the primary CLI executable **`nexterm`**, along with aliases (**`workspace`**, **`worksapce`**, **`developeros`**, **`work`**).

### Verify Installation

```bash
nexterm --version
nexterm --help
```

---

## ⚡ Quick Start

```bash
# 1. Launch the interactive DeveloperOS shell
workspace

# 2. Index your workspace directories
workspace scan ~/code

# 3. Search projects by name, language, or framework
workspace find react
workspace find --language python

# 4. Launch your editor and track usage
workspace open portfolio

# 5. Auto-bootstrap project dependencies, environment, stack & browser
workspace start portfolio

# 6. Diagnose toolchains, missing .env files, and port conflicts
workspace doctor --fix

# 7. Install pre-push Git hook repository defense
workspace guardian install-hook

# 8. Run pre-release validation & artifact secret scan
workspace release check
```

---

## 🔥 Key Subsystems & Features

### 1. Interactive Terminal Shell & Line Editor Subsystem
Launch `workspace` to enter an interactive CWD prompt supporting native OS commands (`ls`, `cd`, `git`, `npm`, `python`, `docker`) alongside DeveloperOS commands.

#### Line Editing Keyboard Shortcuts
| Shortcut | Action | Description |
| :--- | :--- | :--- |
| `Ctrl+Backspace` / `Ctrl+Delete` | `DELETE_PREVIOUS_WORD` | Deletes whole whitespace/delimiter-delimited words |
| `Alt+Backspace` | `DELETE_PREVIOUS_WORD` | Alt-based word deletion |
| `Ctrl+Left` / `Ctrl+Right` | `MOVE_CURSOR_WORD` | Moves cursor backward/forward by whole words |
| `Home` / `Ctrl+A` | `MOVE_CURSOR_START` | Moves cursor to the start of the line |
| `End` / `Ctrl+E` | `MOVE_CURSOR_END` | Moves cursor to the end of the line |
| `Ctrl+U` | `DELETE_TO_START` | Deletes text from cursor position to line start |
| `Ctrl+K` | `DELETE_TO_END` | Deletes text from cursor position to line end |

---

### 2. Context-Aware Tab Completion Engine
DeveloperOS features 7 intelligent completion providers triggered by `<Tab>`:

1. **Top-Level Commands**: `start`, `open`, `doctor`, `find`, `scan`, `guardian`, `release`, etc.
2. **Project Names**: Auto-completes indexed project names when typing `start`, `open`, `doctor`, `fix`.
3. **PATH Executables**: Completes binary executables available on your system `PATH`.
4. **Native Tool Subcommands**: Rich subcommands for `git`, `docker`, `npm`, `pip`, `python`, `node`, `cargo`.
5. **Subcommand Options**: Options for `guardian` (`check`, `install-hook`, `remove-hook`, `status`), `release` (`check`, `build`, `verify`), `stack`, `tag`, `pref`, `daemon`.
6. **Directory-Only Completion**: Smart filtering for `cd <dir>`.
7. **Filesystem Completion**: Path completion for file arguments.

---

### 3. Pre-Push Guardian Subsystem (`workspace guardian`)
Blocks broken, insecure, unformatted, or incomplete code from reaching remote branches before `git push` executes.

```bash
# Install the Git pre-push hook into .git/hooks/pre-push
workspace guardian install-hook

# Check hook installation status
workspace guardian status

# Run full local pre-push validation engine manually
workspace guardian check

# Remove Git pre-push hook
workspace guardian remove-hook
```

#### Pre-Push Verification Pipeline:
- **Git Hygiene**: Validates `.gitignore` presence and checks for untracked secret files (`.env`, `*.db`, `*.key`, `*.pem`, `*.log`, `id_rsa`).
- **Diff Secret Scanner**: Scans diff additions and changed files for API keys, private keys (`id_rsa`, `-----BEGIN PRIVATE KEY-----`), GitHub tokens (`ghp_`), PyPI tokens (`pypi-`), and Slack bot tokens (`xoxb`).
- **Dependency & Version Validation**: Checks `pyproject.toml` syntax and verifies code-to-package version alignment.
- **Automated Test Suite**: Executes `pytest` unit test suite.
- **Build & Metadata Gate**: Executes `python -m build` and `twine check dist/*`.
- **Artifact Secret Content Scanner**: Scans built `.whl` and `.tar.gz` for secrets or forbidden files.
- **Clean Venv Smoke Test**: Installs built wheel into an isolated temporary virtual environment and verifies `workspace --version` / `workspace --help`.
- **Emergency Bypass**: Pass `SKIP_GUARDIAN=1 git push` or `git push --no-verify` to bypass with automated logging.

---

### 4. PyPI Release Subsystem (`workspace release`)
Professional release automation complying with PEP 517/518 and GitHub Actions PyPI Trusted Publishing (OIDC).

```bash
# Run 7-stage pre-release check locally
workspace release check

# Build wheel and sdist packages into dist/
workspace release build

# Validate metadata, scan artifact content secrets, and test clean venv installation
workspace release verify
```

#### Security Guarantee:
- **ZERO PyPI Tokens Required**: Uses GitHub Actions OpenID Connect (`id-token: write`) via `pypa/gh-action-pypi-publish@release/v1`. Zero passwords or long-lived secrets in source code, `.env`, configs, or GitHub secrets.

---

### 5. Structured Error UX Subsystem (`workspace errors`)
Replaces cluttered error tracebacks with human-readable diagnostic cards answering:
- **WHAT** failed?
- **WHERE** did it fail?
- **WHY** did it fail?
- **WHAT** was the exit code?
- **WHAT** actionable steps can the user take next?

Includes automatic **secret redaction** (`SecretRedactor`) and SQLite history logging viewable via `workspace errors`.

---

### 6. Doctor Diagnostics & Repair Subsystem (`workspace doctor`)
Diagnoses toolchain issues, port conflicts, missing `.env` files, and database corruption, offering automated repair via `workspace doctor --fix`.

---

### 7. Autonomous Local AI & Fix Agent (`workspace ai` / `workspace fix`)
Local hardware profiler detecting CPU, RAM, GPU, and disk specs to recommend and download GGUF/Ollama model configurations for local offline AI assistance:

```bash
workspace ai install
workspace ask "How do I set up a PostgreSQL connection pool in Python?"
workspace explain portfolio
workspace fix portfolio
```

---

## 🛠️ CLI Command Reference

| Command | Subcommands / Flags | Description |
| :--- | :--- | :--- |
| `workspace` | *(none)* | Launches the interactive DeveloperOS shell |
| `workspace scan` | `[PATHS...]` | Scans directories and indexes projects in SQLite DB |
| `workspace find` | `[QUERY] [--language] [--framework]` | Searches projects by name, language, or framework |
| `workspace open` | `<project>` | Opens project in default IDE and records usage stats |
| `workspace start` | `<project> [--no-browser]` | Auto-bootstraps project dependencies, env, stack, and browser |
| `workspace clone` | `<repo_url>` | Clones repository, detects stack, and registers in index |
| `workspace doctor` | `[--fix]` | Runs diagnostic checks and optionally applies safe repairs |
| `workspace guardian` | `check` \| `install-hook` \| `remove-hook` \| `status` | Manages Pre-Push Guardian repository defense gate |
| `workspace release` | `check` \| `build` \| `verify` | Validates, builds, and tests PyPI packages for release |
| `workspace errors` | `[--limit]` | View structured error history log |
| `workspace stack` | `start` \| `stop` \| `status` | Orchestrates multi-service dependency-graph stacks |
| `workspace daemon` | `start` \| `stop` \| `status` | Controls background process and health monitor |
| `workspace tag` | `add` \| `rm` \| `list` | Manages custom tags on indexed projects |
| `workspace pref` | `set` \| `get` \| `list` | Sets developer preferences (editor, package manager) |
| `workspace ai` | `install` \| `list` \| `remove` | Manages local GGUF/Ollama AI models |
| `workspace ask` | `<prompt>` | Queries local AI assistant with project context |
| `workspace explain` | `<project>` | Explains project architecture and file structure |
| `workspace fix` | `<project>` | Autonomous AI fix agent for project errors |

---

## 💻 Development & Contributing

### Setup Development Environment

```bash
# Clone the repository
git clone https://github.com/Mr-Anonymous-Guy/Nexterm.git
cd Nexterm

# Install in editable mode with development dependencies
pip install -e .[dev]
```

### Running Test Suite

```bash
# Run full unit test suite (200+ tests)
pytest -v

# Run specific test modules
pytest tests/test_guardian.py -v
pytest tests/test_release.py -v
pytest tests/test_terminal.py -v
pytest tests/test_errors.py -v
pytest tests/test_core.py -v
```

### Running Pre-Push Guardian & Pre-Release Checks

```bash
python scripts/pre_push_guardian.py
python scripts/release_check.py
```

For full release architecture documentation, see [Docs/PYPI_RELEASE_ARCHITECTURE.md](Docs/PYPI_RELEASE_ARCHITECTURE.md) and [Docs/GIT_GUARDIAN_ARCHITECTURE.md](Docs/GIT_GUARDIAN_ARCHITECTURE.md).

---

## 📄 License

Distributed under the **MIT License**. See `LICENSE` for details.
