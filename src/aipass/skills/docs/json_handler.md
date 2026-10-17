[← Back to the skills README](../README.md)

# The JSON Handler

Why `apps/handlers/json/json_handler.py` is a shim and not an implementation.

`apps/handlers/json/json_handler.py` is **not an implementation**. It is the
fleet's canonical shim (decision record: DPLAN-0325): 1724 bytes,
byte-identical in all eighteen branches, sha256
`3456b7660698fa9d2a1f9352523f3a0aa75c3d862bcf6222ce4be280513cf0b7`. seedgo
checks it by hash, so nothing branch-specific may be added to it.

It **binds** the one json service — `aipass.prax.json_handler`, owned by @prax —
and adds nothing. Binding rather than wrapping is load-bearing: the service
names the calling module from frame 2, so a wrapper would attribute every entry
this branch logs to the wrapper's own file.

```python
from aipass.skills.apps.handlers.json import json_handler

json_handler.log_operation("skill_executed", {"name": name})
```

Consequences worth knowing before you touch it:

- **There is no `SKILLS_JSON_DIR` and no `atomic_write_json`.** Code that needs this branch's json directory asks the
  service — `json_handler.get_json_path(module, json_type).parent` — which
  recomputes it per call rather than capturing it at import.
- **Tests redirect with `AIPASS_TEST_LOG_DIR`, never by patching an attribute.**
  The shim has no attributes to patch, and that is the point. All three
  conftests (`tests/`, `lib/telegram/tests/`, `lib/screen_lock/tests/`) set the
  seam; in `tests/` the autouse `mock_infrastructure` fixture scopes it per test.
- Nothing imports out of `apps/handlers/json/.archive/`.

---

*Owned by the skills branch. The face is [../README.md](../README.md).*
