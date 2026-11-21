# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 2.8.x   | Yes       |
| < 2.8   | No        |

## Reporting a Vulnerability

If you discover a security vulnerability in AIPass, please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, use one of these methods:

1. **GitHub Security Advisories** (preferred): [Report a vulnerability](https://github.com/AIOSAI/AIPass/security/advisories/new)
2. **Email**: aipass.system@gmail.com

### What to include

- Description of the vulnerability
- Steps to reproduce
- Affected version(s)
- Any potential impact

### What to expect

- Acknowledgment within 48 hours
- Status update within 7 days
- Fix timeline communicated once the issue is confirmed

## Scope

### In scope

- AIPass Python package (`src/aipass/`)
- CLI entry points (`drone`, `aipass`)
- Hook handlers (`src/aipass/hooks/apps/handlers/`)
- GitHub Actions workflows (`.github/workflows/`)

### Out of scope

- Third-party dependencies (report upstream)
- Issues requiring physical access to the machine
- Social engineering

## Security Design

AIPass runs locally. No data leaves your machine unless you explicitly configure external services.

- **Secrets** are stored outside the repo at `~/.secrets/aipass/` and never committed
- **API keys** are handled by the `api` branch and never logged or exposed in output
- **Git operations** are sandboxed through `drone @git` with permission deny lists
- **Hook handlers** are native Python handlers routed through the hook engine
