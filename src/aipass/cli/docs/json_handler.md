[← Back to the cli README](../README.md)

# The json handler — a shim, not an implementation

`apps/handlers/json/json_handler.py` binds the one fleet json service published
by `@prax` (DPLAN-0325) — nine names plus `InvalidDocument` and `WriteFailed` —
and is byte-identical in every migrated branch. Anything added to it is drift.

It BINDS (`log_operation = _h.log_operation`) and never wraps. The service names
the calling module from `sys._getframe(2)`, so a `def` wrapper would add exactly
one frame and send every log cli writes into `json_handler_log.json` instead of
the caller's document.

The three-file pattern (config, data, log), atomic writes, validation,
provisioning and rotation all live in the service now, and are pinned once for
the whole fleet by seedgo's cross-branch contract rather than re-tested per
branch. Under pytest the writes are redirected by the `AIPASS_TEST_LOG_DIR` seam
that `conftest.mock_infrastructure` sets; the shim has no attribute to patch, and
that is the point.

The call sites are unchanged:

```python
from aipass.cli.apps.handlers.json import json_handler

json_handler.log_operation("files_created", {"count": 12})
data = json_handler.load_json("cli", "config")
json_handler.save_json("cli", "data", {"key": "value"})
json_handler.ensure_module_jsons("cli")  # Create all 3 if missing
```

Import it as a module, not as loose names — seedgo's AST checker matches that
exact shape.

## Why this is allowed to import prax

`apps/modules/` cannot import `aipass.prax`: prax depends on cli, so the import
is circular, and the ban is bypassed in `.seedgo/bypass.json`.

`handlers/json/json_handler.py` is the exception, and it is not a loophole:
prax's `__init__` is lazy (PEP 562), so `from aipass.prax import json_handler`
resolves the service without importing `cli.display`. The cycle is real —
archiving cli's old handler mid-sweep took `drone` itself down through
`drone → cli.apps.modules.display → cli json_handler` — and laziness is what
breaks it. The two bypasses that read "json_handler cannot import prax
(circular)" were retired once the shim demonstrably did.

---
[← Back to the cli README](../README.md)
