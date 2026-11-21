[<- Back to the README](../README.md)

# Cross-branch clients — the in-process Python API

**Branch** api · **Code** `apps/modules/openrouter_client.py`, `google_client.py`, `secrets.py`, `bridge.py`

---

```python
from aipass.api import get_drive_service
service = get_drive_service()                   # Single-threaded
service = get_drive_service(thread_safe=True)   # For concurrent workers
```

`get_drive_service` is the client the package door carries. The door does not carry the OpenRouter client, `get_google_service` or the secret functions (`get_secret`, `set_secret`, `list_secrets`). Secret values never reach stdout.

Private drivers in `apps/integrations/{project}/driver.py` (gitignored) register named contracts via `bridge.register()`. Callers resolve by name — never referencing private projects directly. `registry.py` handles auto-discovery via importlib.

---

---

[← api README](../README.md)
