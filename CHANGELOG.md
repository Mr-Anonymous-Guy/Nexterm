# Changelog

All notable changes to DeveloperOS (`Work_SpaceX`) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-08-08

### Added
- **PyPI Package Identity & Metadata Completion**:
  - Root `LICENSE` file containing official MIT License for Tutun Mahapatra.
  - Refined technical package summary, author identity (`Tutun Mahapatra`), and `license-files = ["LICENSE"]` in `pyproject.toml`.
  - Expanded PEP 621 keywords and verified project URLs (`Homepage`, `Repository`, `Issues`, `Documentation`, `Changelog`).
  - Created `Docs/PYPI_METADATA.md` architecture specification.
  - Version alignment to `0.1.1` across codebase and entrypoints.

## [0.1.0] - 2026-08-08

### Added
- **Production Pre-Push Guardian System**:
  - Pre-push Git hook defense (`workspace guardian check`, `workspace guardian install-hook`, `workspace guardian remove-hook`, `workspace guardian status`).
  - Secret scanning for API keys, tokens, and private keys in diffs and changed files.
  - Repository git hygiene validation (`.gitignore` enforcement and untracked secret checking).
  - Outgoing commit changed files analysis.
  - Package build, twine metadata check, artifact secret content scanning, and clean venv smoke testing.
  - GitHub Actions Guardian CI workflow (`.github/workflows/guardian_ci.yml`) for remote branch protection status checks.
  - Emergency bypass logging via `SKIP_GUARDIAN=1` or `--no-verify`.
- **PyPI Packaging & Trusted Publishing (OIDC)**: PEP 517/518 build setup (`pyproject.toml` hatchling), version alignment, artifact secret scanning, clean venv testing, and zero-token GitHub Actions publishing.
- **Interactive Shell Subsystem**: Real CWD terminal shell supporting standard commands (`cd`, `pwd`, `ls`, `git`, `npm`, `python`, `docker`), signal handling, and line editing.
- **Terminal Line Editor & Completion Engine**: Full support for whitespace word deletion (`Ctrl+Backspace`, `Ctrl+Delete`), word movement (`Ctrl+Left`, `Ctrl+Right`), history persistence, and 7 completion providers (DeveloperOS commands, project index, PATH executables, native subcommands, directories, files).
- **Professional Error Handling & Terminal UX**: Structured error presentation (`CommandError`, `ProcessResult`, `ErrorCategory`, `ErrorSource`) for OS, npm, Python, Git, Docker, and Node failures. Preserves raw output, provides actionable suggestions, redacts secrets (`SecretRedactor`), and supports `normal`, `verbose`, `debug`, and `json` formatting.
- **Workspace Indexer & SQLite Persistence**: Scans workspace roots, detects multi-language project facts (frameworks, dependencies, scripts), and maintains an indexed SQLite database (`~/.developeros/devos.db`).
- **Doctor Diagnostic Engine**: Automated toolchain, port conflict, and missing `.env` diagnostics with interactive repair (`workspace doctor --fix`).
- **Infrastructure Stack Orchestrator**: Dependency graph service starter for PostgreSQL, Redis, Docker, and background processes (`work up`, `work down`, `work logs`).
- **Autonomous AI Assistant & Fix Agent**: Local hardware profiling, model registry, knowledge engine, and autonomous fix agent (`work fix <project>`).
- **PyPI Packaging & Release Automation**: PEP 517/518 packaging (`hatchling`), single source of truth versioning, local release validation suite (`workspace release check`), SHA256 checksums, and GitHub Actions OIDC PyPI Trusted Publishing (zero PyPI tokens).
