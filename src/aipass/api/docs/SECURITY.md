[<- Back to the README](../README.md)

# API Branch — Key Management & Security

Where the API branch keeps keys and OAuth secrets, who reads them, and what keeps them out of the repository.

## Architecture

Every secret value rests in the owner's login keyring, reached through the python `keyring` package:

| OS      | Backend                                              |
|---------|------------------------------------------------------|
| Linux   | SecretService (GNOME Keyring, KWallet) over D-Bus    |
| macOS   | the login Keychain                                   |
| Windows | the Credential Locker                                |

- One entry per secret: service `aipass`, username `<provider>/<slug>`, the value as the password. A value written with `as_json` is stored as a JSON document.
- `aipass` / `<provider>/` is the provider's index entry, a JSON list of its slugs, kept by `set_secret` so `list_secrets` needs no file on disk.
- Examples: `openrouter/api_key`, `google/creds`, `google/client_secret`, `host_api/tokens`, `host_api/pairings`, `host_api/config`, `telegram/<bot>`.
- The owner inspects the keyring with `secret-tool search service aipass` (package `libsecret-tools`) or Seahorse. No seat runs either.

A backend that cannot hold a secret raises `SecretsUnavailable`, naming the backend class and the reason, never a value and never a path: keyring's `fail` and `null` backends, any `keyrings.alt` plaintext backend, a chainer with no member or a plaintext member, and a locked or absent keyring. There is no fall back to a file or to `None`. A missing entry is `None`.

Code never stores, logs, or exposes raw values. The `api` branch provides authenticated service clients; consumers never touch credentials directly.

## Credential Flow

```
login keyring  →  handlers/auth/secrets.py (get_secret)  →  keys.py / google/auth.py / host/*  →  client (use)
                                                                                                  ↓
                                                                            service object (returned to consumer)
```

- `get_api_key()` reads the entry `<provider>/api_key` and checks its prefix and minimum length.
- Google: `google/creds` feeds `Credentials.from_authorized_user_info`, `google/client_secret` feeds `InstalledAppFlow.from_client_config`, and a refresh or a consent writes `google/creds` back through `set_secret`.
- Host API: token rows (`host_api/tokens`), pairing rows (`host_api/pairings`) and the server config (`host_api/config`) are JSON entries.
- `drone @api get-secret <provider/slug>` prints a masked summary (`set (N chars)`) and `--list` prints slugs. It writes no value to stdout and none to a file.
- The operations log records the provider and slug of a read or write, never a value and never a path.
- `get_cache_stats()` returns count only, never cache keys.

## Importing a Value

Files are the import source only. The owner writes a new value into `~/.secrets/aipass/` by hand, then runs:

```
drone @api secrets migrate --dry-run   # the backend class and what would move; changes nothing
drone @api secrets migrate             # imports, then shreds each imported file
```

| File in the store                     | Entry                       |
|---------------------------------------|-----------------------------|
| `<provider>/<slug>.json`              | `<provider>/<slug>` (JSON)  |
| `<provider>/<slug>` (no suffix)       | `<provider>/<slug>`         |
| `.env` line `<PROVIDER>_API_KEY=<v>`  | `<provider>/api_key`        |
| `google_client_secret.json`           | `google/client_secret`      |
| `google_creds.json`                   | `google/creds`              |

Each import writes the entry, reads it back, then overwrites the file with zeros, fsyncs and unlinks it, and logs one `secret_migrated` row (provider, slug). A write that fails leaves the file whole and names it. `.env` is shredded once every key in it is in; a `.env` that also holds other settings (`BLUESKY_HANDLE`, ...) has its keys imported and stays. A second run says nothing is left to move. `drone @api init` still writes the `.env` template the owner fills before `secrets migrate`. The verb is the owner's run; a seat never runs it unasked.

The integration drivers read named entries. A `.env` line they need that `secrets migrate` does not import from the `.env` is written by hand as the store file in the right column, then imported; after that the `.env` line is the owner's to delete.

| Driver  | `.env` line name        | Store file (raw, no suffix) → entry |
|---------|-------------------------|-------------------------------------|
| devto   | `DEVTO_API_KEY`         | imported from the `.env` → `devto/api_key` |
| bluesky | `BLUESKY_HANDLE`        | `bluesky/handle`                    |
| bluesky | `BLUESKY_APP_PASSWORD`  | `bluesky/app_password` (not imported from the `.env`: it does not end in `_API_KEY`) |

A driver whose entry is absent or empty raises naming the entry and `secrets migrate`; neither driver reads the `.env`.

## What Stays on Disk

`~/.secrets/aipass/` (directory `0o700`) keeps what is not a store shape, named as left by `secrets migrate`:

- `host_api/tokens.lock`, the host API's write lock, and `host_api/<label>.token`, the pairing receipts. A receipt is the one value written to disk on purpose, for the owner to carry to the phone, and is the owner's to delete.
- Telethon `.session` files: SQLite owned by the library, `0o600`.
- Anything else the owner keeps there by hand (`twitter_cookies.json`, `PyPI.md`, recovery codes): the owner's to move.

## Known Limits

- The keyring protects the disk, the backups and a copied laptop. It does not protect against a process running as the owner while the session is unlocked; that case is held by the hooks rule that refuses any seat's command naming the store, and by the seedgo standard that refuses an import of the secrets modules outside `src/aipass/api/`.
- After a reboot the login keyring is locked until the owner logs in. The 05:45 Drive backup then fails with exit 2 and the daemon mails the failure until then. There is no autologin and no stored keyring password: either would hand the disk the key again.

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
- `src/aipass/*/apps/integrations/**` — private integration drivers stay out of the repo; only the scaffold `README.md` is tracked
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
