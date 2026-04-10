# API Branch — Local Context

## Identity

API is the **centralized external API gateway** for AIPass. Provides authenticated service clients for external APIs. Consumers import ready-to-use clients — API owns the plumbing, consumers own the business logic.

## Key Breadcrumbs

- **Credentials live at** `~/.secrets/aipass/` — `google_creds.json`, `google_client_secret.json`, `.env`
- **Design rule:** If it's not auth, credentials, or service factory — it doesn't belong here. See DPLAN-0036 for the full rationale and old Telegram anti-pattern.
- **Provider pattern:** One module per provider (`openrouter_client.py`, `google_client.py`), one handler directory per provider (`openrouter/`, `google/`). Module orchestrates, handlers implement.
- **No default models/configs** — consumers provide their own. API provides the connection.
- **Thread-safe mode:** `get_drive_service(thread_safe=True)` loads fresh creds from disk per call for concurrent workers.
- **Google libs are optional deps** — guarded by `GOOGLE_AUTH_AVAILABLE` flag, commands fail explicitly with install instructions.
- **After building:** Run `drone @seedgo audit aipass @api` before reporting complete.

## Commands

| Command | Description |
|---|---|
| `get-key [provider]` | Retrieve API key (default: openrouter) |
| `validate [provider]` | Validate API key (default: openrouter) |
| `validate google` | Validate Google OAuth2 credentials |
| `reauth google` | Re-authenticate Google OAuth2 |
| `test` | Test OpenRouter connection |
| `models [--all]` | List available models |
| `status` | OpenRouter client status |
| `call "prompt" --model MODEL` | Make API call |
| `list-providers` | List available providers |
| `init` | Create .env template |
| `track <gen_id> [caller]` | Track generation usage |
| `stats` | Usage statistics |
| `session` | Session usage summary |
| `caller-usage <caller>` | Usage by caller |
| `cleanup [days]` | Clean old usage data (default: 30) |

## Architecture

```
api.py (entry, routing)
  → modules/ (orchestration, CLI)
    → handlers/ (business logic)
```

**Modules:** `api_key`, `openrouter_client`, `usage_tracker`, `google_client`
**Handlers:** `auth/`, `config/`, `openrouter/`, `usage/`, `json/`, `google/`
