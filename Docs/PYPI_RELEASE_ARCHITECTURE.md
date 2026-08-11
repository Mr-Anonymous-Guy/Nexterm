# PyPI Release & Packaging Architecture — Nexterm

## 1. Audit of Current Project State

### Repository Metadata & Language
- **Project Language**: Python 3.9+ (tested through 3.13)
- **Primary Package Name (PyPI distribution name)**: `nexterm`
- **Import Package Name**: `nexterm`
- **CLI Executable Names**: `nexterm`, `workspace`, `worksapce`, `developeros`, `work`
- **Current Version**: `0.1.1` (defined in `nexterm/__init__.py` and `pyproject.toml`)
- **Build Backend**: `hatchling` (`hatchling.build`)
- **Package Layout**: Flat src layout (`nexterm/` package directory)
- **Dependencies**: `click>=8.1`, `tomli>=2.0` (Python <3.11), `pyyaml>=6.0`, `psutil>=5.9`, `prompt-toolkit>=3.0.0`
- **Test Suite**: `pytest` (183 tests across `tests/test_core.py`, `tests/test_terminal.py`, `tests/test_errors.py`)
- **Existing CI/CD**: None present (`.github/` directory missing)
- **Existing Build Artifacts**: `dist/` directory exists from manual builds

---

## 2. Target Packaging & Trusted Publishing Architecture

### OIDC Trusted Publishing Flow (Zero Tokens)
```
  Developer
      │
  git commit & test
      │
  git tag v0.1.0
      │
  git push origin v0.1.0
      │
  GitHub Actions Workflow (.github/workflows/release.yml)
      │
  ├── Job 1: Test & Validate
  │     ├── Checkout repository
  │     ├── Setup Python (3.9 - 3.13)
  │     ├── Run test suite (pytest)
  │     ├── Validate version (tag 'v0.1.0' == '0.1.0')
  │     ├── Build wheel + sdist (python -m build)
  │     ├── Validate metadata (twine check)
  │     ├── Scan artifact contents for secrets
  │     └── Generate SHA256 checksums
  │
  ├── Job 2: Publish to PyPI (Environment: pypi)
  │     ├── Request GitHub OIDC identity token (permissions: id-token: write)
  │     ├── Exchange OIDC token with PyPI for short-lived upload session
  │     └── Upload wheel & sdist using pypa/gh-action-pypi-publish@release/v1
  │
  └── Job 3: GitHub Release
        ├── Create GitHub Release for tag v0.1.0
        ├── Attach .whl, .tar.gz, SHA256SUMS.txt
        └── Publish clean release notes
```

### Security & Token Policy
- **ZERO stored PyPI API tokens**: No `PYPI_TOKEN`, `TWINE_PASSWORD`, or API credentials in repository, `.env`, secrets, or CLI.
- **GitHub Actions OIDC**: Short-lived, cryptographic identity token exchanged directly with PyPI.
- **Environment protection**: Production releases execute within the protected `pypi` GitHub Actions environment.
- **Pull Request protection**: Pull requests and normal branch pushes CANNOT publish to PyPI.

---

## 3. Name & Entrypoint Architecture

| Entity | Identifier | Purpose |
|--------|------------|---------|
| **PyPI Distribution Name** | `nexterm` | PyPI package name (`pip install nexterm`) |
| **Python Import Name** | `nexterm` | Internal Python package (`import nexterm`) |
| **Primary Executable** | `nexterm` | Standard CLI entrypoint (`nexterm --help`) |
| **Alias Executables** | `workspace`, `worksapce`, `developeros`, `work` | Convenience CLI aliases |

---

## 4. Single Source of Truth for Versioning

- **Authoritative Version**: Defined in `developeros/__init__.__version__` (`0.1.0`) and mirrored in `pyproject.toml`.
- **Git Tag Rule**: Release tag must follow `vX.Y.Z` (e.g. `v0.1.0`).
- **Validation Rule**: `release_check` and CI/CD enforce strict equality: `tag.strip('v') == __version__ == pyproject.toml version`. Mismatches halt publication immediately.

---

## 5. Artifact Security & Secret Scanning

The release pipeline executes an automated artifact content scan before publication:
- **Included**: Python files (`.py`), package data, license, README.
- **Strictly Excluded**: `.env`, `.git`, `*.db`, `*.key`, `*.pem`, `*.log`, `__pycache__`, `.pytest_cache`, test artifacts, local databases.
