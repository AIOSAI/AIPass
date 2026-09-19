[<- Back to the README](../README.md)

# Cross-branch clients — the in-process Python API

**Branch** api · **Code** `apps/modules/openrouter_client.py`, `google_client.py`, `secrets.py`, `bridge.py`

---

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

Private drivers in `apps/integrations/{project}/driver.py` (gitignored) register named contracts via `bridge.register()`. Callers resolve by name — never referencing private projects directly. `registry.py` handles auto-discovery via importlib.

---

---

[← api README](../README.md)
