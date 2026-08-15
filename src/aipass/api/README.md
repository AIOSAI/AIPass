[← Back to AIPass](../../../README.md)

# API

> Centralized external API gateway — authenticated service clients for all external APIs

**Module:** `aipass.api` | **Role:** `api_gateway`
**Seedgo:** 100% (44/44 at 100%; 99% with all bypasses disabled) | **Tests:** 719 pass | **Functions:** 118 public (118 tested)
**Last Updated:** 2026-08-14

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
| `host-api serve [--host IP] [--port N]` | Run the host API (loopback only in Phase 1) |
| `host-api issue-token <label> --out FILE` | Mint a bearer token (raw value never printed) |
| `host-api list-tokens` | List tokens — values are never shown |
| `host-api revoke-token <id>` | Revoke server-side, effective next request |
| `host-api config` / `set-config` | Show / set the bind address (validated first) |

---

## Architecture

```
api/
├── apps/
│   ├── api.py                         # Entry point — module discovery, command routing
│   ├── modules/                       # Orchestration layer (9 modules)
│   │   ├── api_key.py                 # Key retrieval, validation, provider listing
│   │   ├── secrets.py                 # Cross-branch secrets door (in-process API)
│   │   ├── openrouter_client.py       # OpenRouter client — calls, models, status
│   │   ├── google_client.py           # Google API services (Drive, Calendar, etc.)
│   │   ├── host_api.py                # Host API — server lifecycle, token admin
│   │   ├── usage_tracker.py           # Usage metrics — track, stats, cleanup
│   │   ├── bridge.py                  # Generic contract registry (register/resolve)
│   │   ├── integrations_manager.py    # Contract dispatch — integrations list/call
│   │   └── registry.py               # Driver auto-discovery (load_drivers)
│   ├── handlers/                      # Business logic (9 packages, 23 files)
│   │   ├── auth/env.py, keys.py, secrets.py
│   │   ├── config/provider.py
│   │   ├── google/auth.py, service_factory.py, retry.py
│   │   ├── host/config.py, tokens.py, server.py, feed.py, reads.py, fleet.py
│   │   ├── integrations/list.py, call.py
│   │   ├── json/json_handler.py
│   │   ├── openrouter/caller.py, client.py, models.py, provision.py
│   │   └── usage/aggregation.py, cleanup.py, tracking.py
│   └── integrations/                  # Private driver space (gitignored)
│       └── {project}/driver.py
└── tests/                             # 719 tests across 34 files
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

## Host API — Stage 0 (FPLAN-0411)

The server the BAUD phone face talks to. **Phases 1–2: config, bind validation,
bearer auth and the read lane — loopback-bound.** This is the first
network-listening service in AIPass, so a wider bind is gated on a security review.

```bash
drone @api host-api issue-token pixel-8 --scope read --out ~/pixel.token
drone @api host-api serve            # 127.0.0.1:8787 by default
drone @api host-api revoke-token <id>  # effective next request, no restart
```

**Two auth layers** (neither trusted alone): a private network boundary, plus a
bearer token stored as a sha256 hash under `~/.secrets/aipass/host_api/`.
Revocation is a server-side file edit — a phone that keeps its token forever is
inert once the host stops honouring it.

**The bind rule:** the server binds the address it was configured for or refuses
to start. No fallback. Wildcards (`0.0.0.0`, `::`), hostnames, and addresses this
machine does not hold are all refused.

**Endpoints live today:**

| Endpoint | Scope | Notes |
|---|---|---|
| `GET /v1/ping` | none | 204, no body — separates "tunnel down" from "token bad" |
| `GET /v1/whoami` | read | Enrollment check; returns only what the caller already holds |
| `GET /v1/feed?since=&limit=` | read | Cursor is a **timestamp**, clamped both ends, `gap` flagged |
| `GET /v1/files?branch=&file=` | read | Branch by NAME, file relative to it; 512KB cap **refuses**, never trims |
| `GET /v1/diff?branch=&staged=` | read | Routed through `drone @git`, never raw git; truncation is reported |
| `GET /v1/fleet?project=` | read | @baud's snapshot envelope, unchanged. `project` is case-sensitive |
| `GET /v1/rooms?project=` | read | A filter over that same snapshot — never a room judgment of its own |

**Why the feed cursor is a timestamp:** `notifications.jsonl` is trimmed 400→200
lines and the trim replaces the file, so a line or byte offset goes stale under
any reader — the same shape as the 10-hour Telegram outage. The cursor clamps at
both ends and re-delivers the boundary event: a duplicate alert is a nuisance, a
dropped one defeats the app.

**Names, not paths:** `/v1/files` has no path parameter. The client names a branch
and the server resolves it through the citizen registry, which removes the
traversal class rather than mitigating it. Containment is still checked underneath,
because a "name" can lie and a symlink can point out of the tree.

**Fleet is a pipe, not a model.** `/v1/fleet` shells `baud --snapshot` and returns
@baud's envelope with no adapter — this server never computes what an agent's
state means, because a second answer to "is this agent alive" would eventually
disagree with the desktop and neither would be trusted. `has_room` is filtered on,
never derived, and `live_agent_sessions` is served raw rather than joined to the
branch list. BAUD's binary is resolved to the same built release path the desktop
launcher execs. `fleet.SNAPSHOT_READY` remains as a kill switch: switched off
means **503 with a reason**, never a synthesised fleet.

**Aliveness is `live_agent_sessions`, and only that.** The three fleet fields
answer three different questions: `has_room` means a BAUD-named session *exists*
(an empty room is `has_room: true`), `outside_room` names a session BAUD did not
create, and `live_agent_sessions` is the process-table read. Rendering "alive"
from `has_room` puts a green circle over an empty room. This server never
synthesises an aliveness signal, so the only field a client can read it from is
the one that means it — pinned by test at @baud's request.

The verb lane and push are reserved, not built. See FPLAN-0411.

Requires the optional `[host]` extra (`fastapi`, `uvicorn`); commands fail with
install instructions if it is absent.

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
