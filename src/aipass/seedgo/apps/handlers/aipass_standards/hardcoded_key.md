# Hardcoded Key Standard
**Status:** Draft v1
**Date:** 2026-03-22

---

## What This Standard Is

API keys and secrets must never appear as string literals in source code. A single committed key can compromise an entire service, and once pushed to a repository, the key must be considered leaked -- even after removal. Use environment variables or configuration files instead.

---

## Why It Matters

- **Security:** Hardcoded keys in source code are the #1 cause of credential leaks. Bots scrape public repositories for key prefixes within seconds of a push.
- **Rotation difficulty:** Keys embedded in code require code changes to rotate. Environment variables can be rotated without touching code.
- **Compliance:** Most security frameworks (SOC2, ISO27001) explicitly prohibit hardcoded credentials.
- **Blast radius:** A leaked key can grant access to billing accounts, user data, and infrastructure. The damage compounds fast.

---

## What the Checker Scans For

The checker scans every `.py` file for known API key prefixes inside quote characters (`"`, `'`, `` ` ``).

### Detected Providers

| Provider | Prefix Pattern | Minimum Length |
|----------|---------------|----------------|
| OpenRouter | `sk-or-v1-` | 8+ chars after prefix |
| OpenAI | `sk-proj-` | 8+ chars after prefix |
| Anthropic | `sk-ant-` | 8+ chars after prefix |
| Google | `AIza` | 20+ chars after prefix |
| AWS | `AKIA` | 12+ chars after prefix |
| GitHub | `ghp_` / `gho_` / `ghs_` | 8+ chars after prefix |
| Slack | `xoxb-` / `xoxp-` | 8+ chars after prefix |
| Generic | `key-` | 16+ chars after prefix |

### Smart Filtering

The checker avoids false positives through multiple filters:

**Not flagged:**

- **Comment lines** -- lines starting with `#`
- **Docstrings** -- the first-statement string of a module, class or function, every line; a triple-quoted literal in code is scanned like any other string
- **Placeholder values** -- strings containing: `your_key`, `xxx`, `example`, `placeholder`, `abc123`, `test`, `fake`, `dummy`, `sample`, `...`, `changeme`, `<`, `>`
- **Placeholder suffixes** -- strings ending with: `-here`, `-example`, `-test`, `-xxx`, `-placeholder`, `-demo`, `-key`, `-secret`, `-value`
- **Example context** -- lines containing words like `example`, `template`, `placeholder`, `sample`, `demo`
- **Regex contexts** -- lines containing `re.compile`, raw strings (`r"`), or regex metacharacters

---

## Code Examples

### Violation

```python
# These will be flagged:
API_KEY = "sk-or-v1-abc123real456key789def012"
client = Anthropic(api_key="sk-ant-realkey123456789abcdef")
GOOGLE_KEY = "AIzaSyC_REAL_KEY_THAT_IS_LONG_ENOUGH"
```

### Fix -- Environment Variables

```python
import os

API_KEY = os.environ["OPENROUTER_API_KEY"]
client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
GOOGLE_KEY = os.environ["GOOGLE_API_KEY"]
```

### Fix -- Configuration File

```python
import json
from pathlib import Path

config = json.loads(
    Path("config.json").read_text(encoding="utf-8")
)
API_KEY = config["api_key"]
```

### Not Flagged -- Placeholders

```python
# These are recognized as placeholders and not flagged:
DEFAULT_KEY = "sk-or-v1-your_key_here"
EXAMPLE_KEY = "sk-proj-xxxxxxxxxxxxxxxx"
DEMO = "sk-ant-placeholder-abc123"
```

---

## Scoring

- **Check:** One check per file -- "Hardcoded API keys"
- **Pass:** Zero hardcoded keys detected (after filtering and bypass)
- **Fail:** Any hardcoded keys found. The violation message reports the count and first three line numbers (e.g., `Found 2 hardcoded key(s) on lines 15, 42`)
- **Score:** 100 if passed, 0 if failed
- **Threshold:** Score >= 75 to pass overall
- **Line-level bypass:** Individual lines can be bypassed and are filtered out before counting violations

---

## Bypass

Add an entry to `.seedgo/bypass.json`:

```json
{
    "standard": "hardcoded_key",
    "file": "path/to/file.py"
}
```

Or bypass specific lines:

```json
{
    "standard": "hardcoded_key",
    "file": "path/to/file.py",
    "lines": [15]
}
```

---

## Audit Scope

`AUDIT_SCOPE = "all_files"` -- runs against every `.py` file in the branch. Skips `__init__.py`.

---

## If You Find a Real Key

1. **Rotate immediately.** The key is compromised the moment it appears in source.
2. Remove the key from source code.
3. Move it to an environment variable or secure config.
4. Check git history -- if the key was ever committed, it persists in history even after removal.
5. Consider using `git filter-branch` or BFG Repo Cleaner to purge it from history.

---

## Reference

- Checker: `hardcoded_key_check.py`
- Standards pack: seedgo standards (hardcoded_key)
