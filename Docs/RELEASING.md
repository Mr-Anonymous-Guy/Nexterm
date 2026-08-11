# Nexterm — Releasing Guide

This document describes how to package, validate, tag, and publish Nexterm (`nexterm`) to PyPI and GitHub Releases.

The release system uses **PyPI Trusted Publishing (OIDC)**. No PyPI API tokens or passwords are required or stored in the repository, secrets, or CLI.

---

## 1. One-Time PyPI Trusted Publisher Setup

Before the first release, the package owner (`Tutun Mahapatra`) must configure PyPI Trusted Publishing once on [PyPI.org](https://pypi.org):

1. Log in to [PyPI.org](https://pypi.org).
2. Go to **Account Settings** -> **Publishers** (or navigate to your project settings if the package `nexterm` is already registered).
3. Add a new **GitHub Publisher**:
   - **PyPI Project Name**: `nexterm`
   - **Owner / Organization**: `Mr-Anonymous-Guy`
   - **Repository Name**: `Nexterm`
   - **Workflow Name**: `release.yml`
   - **Environment Name**: `pypi`
4. Save the Trusted Publisher configuration.

> [!IMPORTANT]
> Do NOT create or add a PyPI API token to GitHub repository secrets. The GitHub Actions release workflow authenticates automatically via short-lived OpenID Connect (OIDC) tokens.

---

## 2. Standard Developer Release Workflow

### Step 1: Run Local Release Validation

Before creating a release, run the local validation engine:

```bash
workspace release check
```

or using python:

```bash
python scripts/release_check.py
```

This automatically runs:
- Git working tree cleanliness check
- Code & `pyproject.toml` version alignment check
- Pytest suite execution
- Package build (`python -m build`)
- Metadata check (`twine check`)
- Artifact content secret scan (scans wheel & sdist zip/tar for `.env`, `*.db`, secrets, private keys)
- Clean virtual environment installation smoke test (`pip install wheel` into temporary venv, testing `workspace --version` and `workspace --help`)

All checks must pass `[OK]`.

### Step 2: Update Version & Changelog

1. Update `__version__ = "X.Y.Z"` in `developeros/__init__.py`.
2. Update `version = "X.Y.Z"` in `pyproject.toml`.
3. Add release notes in `CHANGELOG.md`.

Commit the changes:

```bash
git commit -am "chore: release v0.1.0"
```

### Step 3: Create and Push Git Tag

Create the version tag matching `vX.Y.Z`:

```bash
git tag v0.1.0
git push origin main
git push origin v0.1.0
```

### Step 4: Automated CI/CD Execution

Once the tag `v0.1.0` is pushed:

1. **GitHub Actions** triggers `.github/workflows/release.yml`.
2. **Job 1 (validate-and-build)**: Runs tests, validates tag matches package version, builds wheel & sdist, scans secrets, generates `SHA256SUMS.txt`.
3. **Job 2 (publish-pypi)**: Authenticates to PyPI via OIDC Trusted Publishing and publishes `nexterm` to PyPI.
4. **Job 3 (github-release)**: Creates official GitHub Release for `v0.1.0`, attaches `.whl`, `.tar.gz`, and `SHA256SUMS.txt`.

---

## 3. Local Inspection & Verification Commands

To manually inspect build artifacts locally:

```bash
# Build wheel and sdist
workspace release build

# Verify build metadata, secrets, and clean venv installation
workspace release verify
```

To test wheel installation in an isolated clean environment manually:

```bash
python -m venv .test-venv
.test-venv/Scripts/python -m pip install dist/*.whl   # Windows
.test-venv/Scripts/workspace --version
.test-venv/Scripts/workspace --help
```

---

## 4. Failure Recovery & Version Immutability

PyPI versions are **immutable**. Once `0.1.0` is published to PyPI, it cannot be overwritten or re-uploaded.

- If a release validation step fails before PyPI publication, fix the issue, update commit, and push the tag.
- If PyPI publication succeeds but a bug is found post-release, increment the patch version (e.g. `0.1.1`), tag `v0.1.1`, and push.

---

## 5. Security Architecture Summary

- **Zero Stored Credentials**: No API keys, PyPI tokens, or SSH keys stored anywhere.
- **Minimal Permissions**: The GitHub Release workflow requests only `id-token: write` for OIDC and `contents: read`/`contents: write` for releases.
- **Secret Scanning**: Wheels & sdists are scanned for forbidden file extensions (`.env`, `.key`, `.db`, `.log`) and secret content patterns before publication.
- **Isolated Testing**: Installation is verified in a isolated clean virtual environment detached from the source code directory.
