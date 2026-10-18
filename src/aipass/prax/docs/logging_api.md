[<- Back to the README](../README.md)

# logger — the logging API

Both import patterns, log levels, the mocking contract every branch's tests rely on, and the lifecycle events.

---

## Pattern A — Canonical (use this)

```python
from aipass.prax import logger

logger.info("Processing started")
```

This works from any branch. Prax detects the caller via stack introspection and routes to the correct log file. If prax fails to import, a NullLogger fallback prevents crashes.

Four levels are available — `debug()`, `info()`, `warning()`, `error()`.

**The object form is the recommended spelling.** Three spellings reach the same
logger — `from aipass.prax import logger`, `from aipass import prax` then
`prax.logger`, and `from ...modules.logger import system_logger as logger` — and
they behave identically: importing prax writes nothing, and any writes come from
the *call*, not the binding. Importing `aipass.prax` is lazy (PEP 562, see
[json_service.md](json_service.md)), so only a spelling that touches `logger`
pays for the logger graph. One spelling across the fleet is the tiebreak.

Whether a test's mock reaches the logger depends on ordering, not binding style:

| swap timing | form 1 | form 2 (object) | form 3 (module) |
|---|---|---|---|
| `sys.modules` swap **after** import | REAL | REAL | **REAL** |
| `monkeypatch.setattr(prax, "logger", …)` | REAL | REAL | MOCK |
| `sys.modules` swap **before** import | **ModuleNotFoundError** | MOCK | MOCK |

A `sys.modules` swap that lands after import reaches nothing in *any* spelling.
The module form is the only one that **crashes** against a mocked `aipass.prax`,
because the mock package has no `apps` submodule.

**What the test-log seam redirects.** Under pytest, log files go to a temp
directory automatically. The json service resolves its directory per call from
`AIPASS_TEST_LOG_DIR`, so everything written *by module name* is redirected when
that variable is set. What is **not** redirected is the handful of module-level
path constants built from `__file__`:

```
config.load.PRAX_JSON_DIR         -> src/aipass/prax/prax_json     <- real tree
registry.save.REGISTRY_FILE       -> …/prax_json/prax_registry.json <- real tree
logging.operations.LOG_FILE       -> …/prax_json/prax_logger_log.json <- real tree
config.load.get_system_logs_dir() -> /tmp/<redirect>/system         <- redirected
```

Four modules build paths that way — `handlers/config/load.py`,
`handlers/config/ignore_patterns.py`, `handlers/registry/load.py` and
`handlers/registry/save.py` — and any write that goes through a *path* rather
than a module name (the module registry is the live one) lands in the real tree
under any suite unless the test redirects that constant itself.

## Pattern B — Direct Logger (for prax internals)

```python
from aipass.prax.apps.modules.logger import get_direct_logger

logger = get_direct_logger()
logger.info("Direct log entry")
```

Use this in prax handler files that run in watchdog threads or sit in the import chain. Resolves module/branch at creation time, bypassing the runtime event pipeline.

## Log levels

`debug()` is silent by default. Nothing it logs reaches a file until the level is
lowered, which is the point: use it for the verbose trail you want available on
demand but absent from normal operation.

```bash
AIPASS_LOG_LEVEL=DEBUG drone @yourbranch yourcommand   # verbose run
```

The level can also be set per tier in `prax_json/prax_logger_config.json`, so a
branch can keep a verbose local log while the central aggregation stays quiet:

```json
{"config": {"system_logs": {"log_level": "INFO"}, "local_logs": {"log_level": "DEBUG"}}}
```

Precedence is `AIPASS_LOG_LEVEL` → the tier's `log_level` → `INFO`. An
unrecognised value warns once and falls back to `INFO` rather than silently
picking a level nobody asked for.

**Levels bind when a logger is created, not per call.** A long-running process
(Mission Control, a daemon, a bot) picks up a level change on restart — setting
the env var mid-flight does nothing for loggers that already exist.

## Mocking the logger — the contract

Measured by object identity against a real consumer:

| technique | reaches |
|---|---|
| `patch("aipass.prax.logger")` | REAL |
| `patch("…apps.modules.logger.system_logger")` | REAL |
| `setitem(sys.modules, "…apps.modules.logger")` | REAL |
| `setitem(sys.modules, "aipass.prax")` | REAL |
| `patch("<the consuming module>.logger")` | **MOCK** |

The cause is in this package's own `__init__.py`: `__getattr__` resolves
`logger` once and caches the object in `globals()`, so the object is copied at
the package boundary and copied again into each consumer's globals. Anything
patched at or above `aipass.prax` is upstream of a copy already taken. **The last
dot must be resolved at call time**, which only the consumer-module patch does.

**The technique, one line per consuming module:**

```python
patch("aipass.<branch>.apps.handlers.<module>.logger")
```

A branch that forgets a module gets silence, not an error, so a per-module patch
list is fragile; the consumer-module patch is still the only one that reaches.

## The logging path fires no events

`SystemLogger._ensure_watcher` does not call `trigger.fire`, and nothing on the
path from `from aipass.prax import logger` to a written line imports
`aipass.trigger`. That graph costs most of a first log line, so the hot path stays
clear of it: a fresh interpreter that imports the logger and logs one line has
**no `aipass.trigger` module at all**, not even a package shell. Pinned in
`test_logger_module.py::TestLoggingPathIsTriggerFree`. The `startup` event still
exists for whoever fires it deliberately (`drone @trigger fire startup`); error
catch-up on start belongs to trigger's own `log_watcher_service`.

## The lifecycle doors fire, the log line does not

`initialize_logging_system()` fires `logging_system_initialized` (carrying
`modules_count`) after `run_initialize` returns; `shutdown_logging_system()` fires
`logging_system_shutdown` after `run_shutdown`, last, so the event says the
system *is* down rather than that it is going down. seedgo's event table names no
system-lifecycle event, so those two names are prax's, following the convention
it does state: lowercase, underscore-separated, past tense.

**Both imports are inside their function, and that is the design, not a style
choice.** Every log line the fleet writes must stay clear of the `aipass.trigger`
import graph; a door called deliberately, once, can afford what a hot path cannot.
Each fire is guarded `(ImportError, OSError)`: these doors must work on a host
where trigger cannot import or inotify is exhausted, so a failed fire is a warning
and never a failed initialize. Nothing listens to either event, by design — the
point of the standard is that a handler can plug in later without prax changing.
