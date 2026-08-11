# Security Policy for Nexterm

Nexterm (`nexterm`) takes the security of our software, dependencies, and users seriously.

---

## 🛡️ Supported Versions

We provide security updates and patches for the following active release series:

| Version | Supported | Notes |
| :---: | :---: | :--- |
| `0.1.x` |  Yes | Active production release series |
| `< 0.1.0` | ❌ No | Early pre-alpha releases |

---

## 🔒 Reporting a Vulnerability

If you discover a security vulnerability within Nexterm, please follow responsible disclosure principles and report it directly to the maintainer rather than creating a public issue.

### Contact Method:
- **Email**: Send vulnerability reports to [tutunmahapatra@gmail.com](mailto:tutunmahapatra@gmail.com)
- **Subject Line**: `[SECURITY VULNERABILITY] Nexterm - <Brief Description>`

### What to Include in Your Report:
1. **Description**: Clear description of the vulnerability and its potential impact.
2. **Reproduction Steps**: Step-by-step instructions or proof-of-concept (PoC) script.
3. **Affected Components**: CLI commands, package modules, or environment scripts involved.
4. **Environment**: Operating System, Python version, and `nexterm` version.

---

## ⏱️ Response Timelines

When you report a security issue responsibly:

- **Initial Acknowledgment**: Within 24–48 hours of report submission.
- **Triage & Assessment**: Within 5 business days.
- **Fix & Patch Release**: High-severity vulnerabilities will be prioritized and released in a patch update (e.g. `0.1.2`, `0.1.3`) within 7-14 days.

---

## 🛡️ Repository Security Safeguards

NexTerm includes built-in security features designed to protect development environments:

1. **Pre-Push Guardian Engine**: Scans staged commits for hardcoded API keys, private credentials, tokens, AWS keys, and RSA keys prior to git push.
2. **Isolated Build Verification**: Validates PyPI wheel build artifacts in clean virtual environment sandboxes.
3. **OIDC PyPI Trusted Publishing**: Production packages are published directly from GitHub Actions via OpenID Connect (OIDC) without static PyPI API tokens or stored passwords.
4. **Dependency Audit**: Automated CI checks for known vulnerabilities in third-party Python packages.

Thank you for helping keep NexTerm secure for everyone!
