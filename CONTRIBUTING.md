# Contributing to Nexterm

First off, thank you for considering contributing to **Nexterm** (`nexterm`)! It's people like you that make Nexterm such a powerful tool for developers.

Below are guidelines and steps to help you get started contributing to this repository.

---

## 📋 Table of Contents

1. [Code of Conduct](#-code-of-conduct)
2. [Getting Started](#-getting-started)
   - [Prerequisites](#prerequisites)
   - [Setting Up Your Local Development Environment](#setting-up-your-local-development-environment)
3. [Development Workflow](#-development-workflow)
   - [Running Tests](#running-tests)
   - [Running Pre-Push Guardian Validation](#running-pre-push-guardian-validation)
   - [Code Formatting & Linting](#code-formatting--linting)
4. [Submitting a Pull Request](#-submitting-a-pull-request)
5. [Commit Message Guidelines](#-commit-message-guidelines)
6. [Reporting Bugs & Requesting Features](#-reporting-bugs--requesting-features)

---

## 📜 Code of Conduct

This project adheres to the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior to [tutunmahapatra@gmail.com](mailto:tutunmahapatra@gmail.com).

---

## 🚀 Getting Started

### Prerequisites

- **Python**: `3.9` or higher (`3.9`, `3.10`, `3.11`, `3.12`, `3.13`)
- **Git**: Installed and configured
- **pip**: Up to date (`python -m pip install --upgrade pip`)

### Setting Up Your Local Development Environment

1. **Fork & Clone the Repository**:
   ```bash
   git clone https://github.com/Mr-Anonymous-Guy/Nexterm.git
   cd Nexterm
   ```

2. **Create a Virtual Environment**:
   ```bash
   # On Windows
   python -m venv .venv
   .venv\Scripts\activate

   # On macOS/Linux
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install Dependencies in Editable Mode**:
   ```bash
   pip install -e .[dev]
   ```

4. **Install the Pre-Push Guardian Git Hook**:
   ```bash
   python scripts/install_hooks.py
   # Or run via CLI: workspace guardian install-hook
   ```

---

## ⚡ Development Workflow

### Running Tests

We use `pytest` for unit testing across all modules:

```bash
# Run the complete test suite
python -m pytest

# Run tests with verbose output
python -m pytest -v

# Run specific test modules
python -m pytest tests/test_cli.py
python -m pytest tests/test_guardian.py
```

### Running Pre-Push Guardian Validation

Before pushing any commit, run the mandatory 16-stage local guardian engine:

```bash
python scripts/pre_push.py
```

This performs repository audit, dependency verification, formatting, linting, type checks, build generation, test execution, security secret scanning, and git hygiene checks.

### Code Formatting & Linting

We maintain strict code style standards:
- **Style guide**: PEP 8
- **Format check**: `black --check nexterm tests scripts` (or `flake8`)
- **Type safety**: Clean imports and explicit type annotations where possible.

---

## 🔀 Submitting a Pull Request

1. **Create a Feature Branch**:
   ```bash
   git checkout -b feat/my-amazing-feature
   ```
2. **Make your changes** and add unit tests covering new functionality.
3. **Run local validation**:
   ```bash
   python scripts/pre_push.py
   ```
4. **Commit your changes**:
   ```bash
   git commit -m "feat(module): description of feature"
   ```
5. **Push to your fork and open a Pull Request** against the `main` branch.

---

## 💬 Commit Message Guidelines

We follow Conventional Commits standard:

- `feat(scope)`: A new feature
- `fix(scope)`: A bug fix
- `docs(scope)`: Documentation updates
- `style(scope)`: Formatting, missing semi-colons, etc.
- `refactor(scope)`: Code changes that neither fix a bug nor add a feature
- `test(scope)`: Adding missing tests or correcting existing tests
- `chore(scope)`: Maintenance tasks, dependency updates, CI workflows

Example:
```text
feat(guardian): add secret scanning rule for API tokens
```

---

## 🐛 Reporting Bugs & Requesting Features

- **Bugs**: Open an issue on GitHub describing the bug, step-by-step reproduction, expected vs actual behavior, and environment (`python --version`, OS).
- **Feature Requests**: Open an issue explaining the feature, use case, and proposed interface or CLI command syntax.

Thank you for helping make NexTerm awesome! 🎉
