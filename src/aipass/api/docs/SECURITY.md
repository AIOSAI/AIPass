# API Branch — Key Management & Security

## Architecture

All secrets live **outside** the repository at `~/.secrets/aipass/`:

```
~/.secrets/aipass/
├── .env                      # API keys (OpenRouter, OpenAI, etc.)
├── google_creds.json          # Google OAuth2 tokens
└── google_client_secret.json  # Google OAuth app config
```

Code never stores, logs, or exposes raw keys. The `api` branch provides authenticated service clients — consumers never touch credentials directly.

## Credential Flow

```
~/.secrets/aipass/.env  →  keys.py (read + validate)  →  client.py (use)
                                                              ↓
                                                        service object (returned to consumer)
```

- `get_api_key()` reads from config JSON first, falls back to `~/.secrets/aipass/.env`
- `validate_key()` checks prefix and minimum length per provider
- Keys are never returned to CLI output unmasked
- `get_cache_stats()` returns count only, never cache keys
- Credential files are created with `0o600` (owner-only read/write)
- Secret directories use `0o700` permissions

## Provider Key Formats

| Provider   | Prefix      | Min Length |
|------------|-------------|------------|
| OpenRouter | `sk-or-v1-` | 40         |
| OpenAI     | `sk-`       | 40         |
| Anthropic  | `sk-ant-`   | 40         |
| Google     | `AIza`      | 39         |
| Generic    | (none)      | 10         |

## Defense Layers

### 1. `.gitignore`
- `.env` — blocks all dotenv files
- `src/aipass/api/` — API branch excluded from public repo (contains key handling code)
- `~/.secrets/` is outside the repo entirely

### 2. Pre-commit Hook (`.git/hooks/pre-commit`)
- Blocks `sk-or-v1-` + 20 alphanumeric chars
- Blocks API key assignments in code
- Blocks `.env` and credential files from staging
- Allows `FAKE-` and `NOTREAL` prefixed test keys

### 3. Gitleaks (`.gitleaks.toml` + `.pre-commit-config.yaml`)
- Automated secret scanning via `pre-commit` framework
- Custom rules for OpenRouter, OpenAI, Anthropic, Google key formats
- Allowlist for test key prefixes (`FAKE-`, `NOTREAL`)
- Install: `pip install pre-commit && pre-commit install`

### 4. GitHub Push Protection
- Enabled by default on public repos
- Catches known secret patterns server-side before push completes

## Test Key Conventions

Tests must **never** use strings that could be confused with real keys.

### For mocked keys (validation bypassed):
```python
# Short, obviously fake — used when the key value doesn't matter
mock_keys.get_api_key.return_value = "FAKE-sk-or-testkey"
```

### For keys that must pass validation:
```python
# Correct prefix + NOTREAL marker — passes format validation but clearly fake
key = "sk-or-v1-NOTREAL-test-000000000000000000000000000000000000"
```

### Never do this:
```python
# WRONG — looks like a real key, will trigger pre-commit hook
key = "sk-or-v1-FAKE-do-not-use-real-hex-here"

# WRONG — hex strings that resemble real keys
key = "sk-or-v1-FAKE-no-hex-patterns"
```

### Rules:
1. **FAKE-** prefix: for any key that doesn't go through validation
2. **NOTREAL** in the key body: for keys that must have the correct provider prefix
3. Use zeros or repeating patterns, never hex-like random strings
4. Keep test keys as short as possible when length doesn't matter

## If a Key Leaks

1. **Rotate immediately** — bots scan public repos within seconds
2. Revoke the old key at the provider dashboard
3. Generate a new key and update `~/.secrets/aipass/.env`
4. Check git history: `git log --all -p -- '*.env' '*.json'`
5. If the key entered git history, consider `git filter-branch` or BFG Repo-Cleaner
