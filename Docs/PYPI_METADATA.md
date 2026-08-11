# Nexterm — PyPI Package Identity & Metadata Architecture

## 1. Executive Package Specification

| Property | Value | Description |
| :--- | :--- | :--- |
| **PyPI Distribution Name** | `nexterm` | `pip install nexterm` |
| **Python Import Name** | `nexterm` | `import nexterm` |
| **Primary CLI Executable** | `nexterm` | Executed directly from terminal after installation |
| **CLI Aliases** | `workspace`, `worksapce`, `developeros`, `work` | Registered console entry points |
| **Author / Maintainer** | `Tutun Mahapatra` | Authoritative package owner identity |
| **License** | `MIT` | Open source license specified in `LICENSE` file |
| **Authoritative Version** | `0.1.1` | Single source of truth in `nexterm/__init__.py` & `pyproject.toml` |
| **Build Backend** | `hatchling` | PEP 517/518 compliant build system |
| **Python Compatibility** | `>=3.9` | Tested across Python 3.9, 3.10, 3.11, 3.12, 3.13 |

---

## 2. Package Summary & Description

- **PyPI Summary**:
  > *"A local developer workspace CLI for managing projects, environments, repositories, and development workflows from an interactive terminal."*

- **Long Description**:
  Powered by `README.md` (`readme = "README.md"` in `pyproject.toml`). Exposes full installation, quick start, interactive line editor shortcuts, 7 context-aware completion providers, structured error UX, pre-push guardian defense gate, doctor diagnostics, local AI agent integration, and command reference.

---

## 3. Keywords & PEP 621 Classifiers

- **Keywords**:
  `["cli", "terminal", "developer-tools", "workspace", "project-management", "git", "automation", "python", "shell"]`

- **Classifiers**:
  - `Development Status :: 4 - Beta`
  - `Environment :: Console`
  - `Intended Audience :: Developers`
  - `License :: OSI Approved :: MIT License`
  - `Operating System :: OS Independent`
  - `Programming Language :: Python :: 3`
  - `Programming Language :: Python :: 3.9`
  - `Programming Language :: Python :: 3.10`
  - `Programming Language :: Python :: 3.11`
  - `Programming Language :: Python :: 3.12`
  - `Programming Language :: Python :: 3.13`
  - `Topic :: Software Development :: Build Tools`

---

## 4. Dependencies & Extras

- **Runtime Dependencies (`dependencies`)**:
  - `click>=8.1`
  - `tomli>=2.0; python_version < '3.11'`
  - `pyyaml>=6.0`
  - `psutil>=5.9`
  - `prompt-toolkit>=3.0.0`

- **Optional Development Extras (`[project.optional-dependencies]`)**:
  - `dev`: `pytest`, `pytest-cov`, `build`, `twine`
  - `ai`: `requests`

---

## 5. Console Entry Points

```toml
[project.scripts]
nexterm = "nexterm.cli:main"
workspace = "nexterm.cli:main"
worksapce = "nexterm.cli:main"
developeros = "nexterm.cli:main"
work = "nexterm.cli:main"
```

---

## 6. Official Project URLs

- **Homepage**: [https://github.com/Mr-Anonymous-Guy/Nexterm](https://github.com/Mr-Anonymous-Guy/Nexterm)
- **Repository**: [https://github.com/Mr-Anonymous-Guy/Nexterm.git](https://github.com/Mr-Anonymous-Guy/Nexterm.git)
- **Issues**: [https://github.com/Mr-Anonymous-Guy/Nexterm/issues](https://github.com/Mr-Anonymous-Guy/Nexterm/issues)
- **Documentation**: [https://github.com/Mr-Anonymous-Guy/Nexterm/blob/main/README.md](https://github.com/Mr-Anonymous-Guy/Nexterm/blob/main/README.md)
- **Changelog**: [https://github.com/Mr-Anonymous-Guy/Nexterm/blob/main/CHANGELOG.md](https://github.com/Mr-Anonymous-Guy/Nexterm/blob/main/CHANGELOG.md)

---

## 7. Zero-Token OIDC Release Architecture

Releases are published to PyPI automatically when a Git tag matching `v*` (e.g. `v0.1.1`) is pushed:
```text
Git Tag (v0.1.1) ➔ GitHub Actions (release.yml) ➔ python -m build ➔ twine check ➔ OIDC Token ➔ PyPI Trusted Publishing
```
No long-lived API tokens, passwords, or secrets are required or stored.
