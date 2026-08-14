[← Back to AIPass](../../../README.md)

# API

> Centralized external API gateway — authenticated service clients for all external APIs

**Module:** `aipass.api` | **Role:** `api_gateway`
**Seedgo:** 100% (44/44 at 100%; 99% with all bypasses disabled) | **Tests:** 532 pass | **Functions:** 84 public (84 tested)
**Last Updated:** 2026-08-13

---

## Invoke

```bash
drone @api <command> [args]
```

---

## Quick Start

```bash
# Validate your API key
drone @api validate

# Test the connection
drone @api test

# List available models
drone @api models

# Make an API call
drone @api call "Hello, world" --model anthropic/claude-3.5-sonnet

# Check usage stats
drone @api stats
```

---

## Commands

| Command | Description |
|---|---|
| `get-key [provider]` | Retrieve API key (default: openrouter) |
| `validate [provider]` | Validate API key (default: openrouter) |
| `validate google` | Validate Google OAuth2 credentials |
| `reauth google` | Re-authenticate Google OAuth2 |
| `get-secret <provider/slug> [--out FILE] [--json] [--list]` | Secret access (masked summary; --out writes to file) |
| `list-providers` | List available API providers |
| `init` | Initialize .env template at ~/.secrets/aipass/ |
| `test` | Test OpenRouter connection status |
| `models [--all]` | List available models (default: top 10) |
| `status` | Check OpenRouter client status (key, SDK, cache) |
| `call "prompt" --model MODEL` | Make API call to model |
| `track <gen_id> [caller]` | Track API usage for a generation |
| `stats` | Display overall usage statistics |
| `session` | Show current session usage |
| `caller-usage <caller>` | Show usage by caller module |
| `cleanup [days]` | Clean up data older than N days (default: 30) |
| `integrations list` | List registered contracts |
| `integrations call <contract> [args...]` | Call a registered contract |

---

## Architecture

```
api/
├── apps/
│   ├── api.py                         # Entry point — module discovery, command routing
│   ├── modules/                       # Orchestration layer (8 modules)
│   │   ├── api_key.py                 # Key retrieval, validation, provider listing
│   │   ├── secrets.py                 # Cross-branch secrets door (in-process API)
│   │   ├── openrouter_client.py       # OpenRouter client — calls, models, status
│   │   ├── google_client.py           # Google API services (Drive, Calendar, etc.)
│   │   ├── usage_tracker.py           # Usage metrics — track, stats, cleanup
│   │   ├── bridge.py                  # Generic contract registry (register/resolve)
│   │   ├── integrations_manager.py    # Contract dispatch — integrations list/call
│   │   └── registry.py               # Driver auto-discovery (load_drivers)
│   ├── handlers/                      # Business logic (8 packages, 17 files)
│   │   ├── auth/env.py, keys.py, secrets.py
│   │   ├── config/provider.py
│   │   ├── google/auth.py, service_factory.py, retry.py
│   │   ├── integrations/list.py, call.py
│   │   ├── json/json_handler.py
│   │   ├── openrouter/caller.py, client.py, models.py, provision.py
│   │   └── usage/aggregation.py, cleanup.py, tracking.py
│   └── integrations/                  # Private driver space (gitignored)
│       └── {project}/driver.py
└── tests/                             # 532 tests across 31 files
```

Three-tier: entry point routes to modules (orchestration), modules delegate to handlers (business logic). Modules auto-discovered from `apps/modules/*.py` via `handle_command()`.

---

## Cross-Branch API

```python
from aipass.api.apps.modules.openrouter_client import get_response
response = get_response(prompt="...", model="anthropic/claude-3.5-sonnet", caller="flow")

from aipass.api.apps.modules.google_client import get_drive_service
service = get_drive_service()                   # Single-threaded
service = get_drive_service(thread_safe=True)   # For concurrent workers

from aipass.api.apps.modules.google_client import get_google_service
service = get_google_service("calendar", "v3")

from aipass.api.apps.modules.secrets import get_secret, set_secret, list_secrets
token = get_secret("telegram", "bot")               # Returns bot_token string
config = get_secret("telegram", "bot", as_json=True) # Returns full dict
set_secret("telegram", "newbot", cfg, as_json=True)  # Writes ~/.secrets/aipass/telegram/newbot.json
slugs = list_secrets("telegram")                     # Returns ["bot", "newbot", ...]
# Values never reach stdout — use the Python API above for programmatic access
```

---

## Integration Points

**Depends On:**
- `aipass.prax` — structured logging via `system_logger`
- `aipass.cli` — Rich console output formatting

**Provides To:**
- All branches — authenticated API clients (`get_response()`, `get_drive_service()`, `get_google_service()`)
- System-wide API key management and credential validation

**Credentials** (`~/.secrets/aipass/`, 0o700 dir, 0o600 files):
- `.env` — API keys (OpenRouter, etc.)
- `google_creds.json` — Google OAuth2 tokens
- `google_client_secret.json` — Google OAuth app config

---

## Integration Contract System (DPLAN-0133)

Private drivers in `apps/integrations/{project}/driver.py` (gitignored) register named contracts via `bridge.register()`. Callers resolve by name — never referencing private projects directly. `registry.py` handles auto-discovery via importlib.

---

## Known Issues

- Error paths exit `0` — a failed command (missing arg, no key, no data) reports success to the shell, so `drone @api validate && ...` proceeds on failure. Unknown commands correctly exit `1`. See APLAN-0013.
- Google auth libraries are optional deps — commands fail with install instructions if missing
- Backup branch credential migration pending (`~/.aipass/` → `~/.secrets/aipass/`; legacy dir still present)
- No rate limiting on OpenRouter calls (S117 finding)

**Troubleshooting:** `openai`/Google auth `ModuleNotFoundError` despite a working venv → the `[llm]`/`[drive]` extras were added after the venv was last built; re-run `setup.sh` (installs `.[dev,memory,llm,drive]`) to resync, no code fix needed. Both import cleanly as of 2026-08-13.

---

*Last Updated: 2026-08-13*

[← Back to AIPass](../../../README.md)
