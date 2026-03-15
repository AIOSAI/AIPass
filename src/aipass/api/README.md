# API

**Purpose:** Centralized external API gateway — authenticated service clients for all external APIs (OpenRouter, Google, future providers).
**Module:** `aipass.api`
**Last Updated:** 2026-03-14

---

## Overview

### What I Do
- Provide authenticated service clients for external APIs (Google Drive, OpenRouter, etc.)
- Manage OAuth2 flows, credential storage, and token refresh
- Offer thread-safe service factories for concurrent consumers
- Handle API key management and validation across providers
- Provide SSL retry and connection resilience utilities

### What I Don't Do
- Host business logic — consumers own what they do with the service
- Set default models or configs — consumers provide their own
- Manage application workflows, polling loops, or orchestration

### How I Work
- **Entry Point:** `apps/api.py` -- auto-discovers and routes to modules
- **Pattern:** Standard AIPass 3-tier architecture (entry point / modules / handlers)
- **Design principle:** If it's not auth, credentials, or service factory — it doesn't belong here

---

## Commands / Usage

```bash
drone @api get-key           # Retrieve API key for provider
drone @api validate          # Validate API credentials and connection
drone @api validate google   # Validate Google OAuth2 credentials
drone @api reauth google     # Re-authenticate Google OAuth2
drone @api test              # Test OpenRouter connection status
drone @api models            # List available models from provider
drone @api track             # Track API usage metrics
drone @api stats             # Display API usage statistics
drone @api --help            # Full help output
drone @api --version         # Show version
```

Running `drone @api` with no arguments displays module introspection (discovered modules and status).

---

## Cross-Branch API

```python
# LLM access (OpenRouter)
from aipass.api.apps.modules.openrouter_client import get_response
response = get_response(prompt="...", model="anthropic/claude-3.5-sonnet", caller="flow")

# Google Drive (or any Google API)
from aipass.api.apps.modules.google_client import get_drive_service
service = get_drive_service()                   # Single-threaded
service = get_drive_service(thread_safe=True)   # For concurrent workers

# Any Google service
from aipass.api.apps.modules.google_client import get_google_service
service = get_google_service("calendar", "v3")

# Retry utility for raw API calls
from aipass.api.apps.modules.google_client import api_call_with_retry
```

---

## Architecture

```
api/
├── __init__.py                    # Public API exports
├── apps/
│   ├── api.py                     # Entry point (module discovery, command routing)
│   ├── modules/
│   │   ├── api_key.py             # Key retrieval and validation logic
│   │   ├── openrouter_client.py   # OpenRouter API client
│   │   ├── google_client.py       # Google API services (Drive, Calendar, etc.)
│   │   └── usage_tracker.py       # Usage metrics tracking
│   └── handlers/
│       ├── auth/
│       │   ├── env.py             # Environment variable credential loading
│       │   └── keys.py            # API key storage and retrieval
│       ├── config/
│       │   └── provider.py        # Provider configuration management
│       ├── google/
│       │   ├── auth.py            # OAuth2 lifecycle, credential I/O
│       │   ├── service_factory.py # Service object factory (single + thread-safe)
│       │   └── retry.py           # SSL retry with exponential backoff
│       ├── json/
│       │   └── json_handler.py    # JSON operation logging
│       ├── openrouter/
│       │   ├── caller.py          # HTTP request execution
│       │   ├── client.py          # OpenRouter client implementation
│       │   ├── models.py          # Model discovery and listing
│       │   └── provision.py       # Provider provisioning
│       └── usage/
│           ├── aggregation.py     # Usage data aggregation
│           ├── cleanup.py         # Usage data cleanup
│           └── tracking.py        # Usage event tracking
└── README.md
```

---

## Integration Points

### Depends On
- `aipass.prax` -- structured logging via `system_logger`
- `aipass.cli` -- Rich console output formatting

### Provides To
- All branches -- authenticated external API clients
- `@backup` -- Google Drive service (migration from self-contained auth)
- `@skills` -- future external API integrations (Telegram, Google services)
- System-wide API key management and credential validation

### Credentials
- `~/.secrets/aipass/.env` -- API keys (OpenRouter, etc.)
- `~/.secrets/aipass/google_creds.json` -- Google OAuth2 tokens
- `~/.secrets/aipass/google_client_secret.json` -- Google OAuth app config

---

*Last Updated: 2026-03-14*
