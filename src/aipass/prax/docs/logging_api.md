[<- Back to the README](../README.md)

# logger — the logging API

Both import patterns, log levels, the mocking contract every branch's tests rely on.

---

## Pattern A — Canonical (use this)

```python
from aipass.prax import logger

logger.info("Processing started")
```

This works from any branch. Prax detects the caller via stack introspection and routes to the correct log file. There is no fallback logger: if the logger chain cannot import, `from aipass.prax import logger` raises exactly as `from aipass.prax.apps.modules.logger import system_logger` does, and so does `get_direct_logger`. Pinned in a subprocess by `test_logger_module.py::TestBrokenChainRaises`.

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
config.load.get_system_logs_dir() -> /tmp/<redirect>/system         <- redirected
```

Four modules build paths that way — `handlers/config/load.py`,
`handlers/config/ignore_patterns.py`, `handlers/registry/load.py` and
`handlers/registry/save.py` — and any write that goes through a *path* rather
than a module name (the module registry is the live one) lands in the real tree
under any suite unless the test redirects that constant itself.

## Pattern B — Direct Logger (for prax internals)

```python
from aipass.prax.apps.handlers.logging.direct import get_direct_logger

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
unrecognised value warns once, on load's trail (`prax/logs/load.jsonl`), and
uses `INFO`.

The default line format is the pipe form, `%(asctime)s | %(name)s | %(levelname)s | %(message)s`;
`prax_logger_config.json` is git-ignored, so a fresh clone logs what a configured seat logs.

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

The cause is the consumer's own from-import: `from aipass.prax import logger`
copies the object into the consumer's globals at import time. The package door
caches nothing (`__getattr__` reads the home on every access), but anything
patched at or above `aipass.prax` is still upstream of the copy the consumer
already took. **The last
dot must be resolved at call time**, which only the consumer-module patch does.

**The technique, one line per consuming module:**

```python
patch("aipass.<branch>.apps.handlers.<module>.logger")
```

A branch that forgets a module gets silence, not an error, so a per-module patch
list is fragile; the consumer-module patch is still the only one that reaches.

## The logging path fires no events

`SystemLogger` checks no watcher and calls no `trigger.fire`, and nothing on the
path from `from aipass.prax import logger` to a written line imports
`aipass.trigger`. That graph costs most of a first log line, so the hot path stays
clear of it: a fresh interpreter that imports the logger and logs one line has
**no `aipass.trigger` module at all**, not even a package shell. Pinned in
`test_logger_module.py::TestLoggingPathIsTriggerFree`. The `startup` event still
exists for whoever fires it deliberately (`drone @trigger fire startup`); error
catch-up on start belongs to trigger's own `log_watcher_service`.

## Door two — the trail, and prax's own diagnostics

```python
from aipass.prax import trail

log = trail(Path(__file__).parents[2] / "logs" / "jobs.jsonl")  # must be <dir>/logs/<name>.jsonl
log.warning("job failed", job="sweep", error=str(exc))
```

A trail line is `{"ts", "level", "msg", **fields}` in a `.jsonl` file the log
watcher never reads, so a loop on the watched path can log without feeding
itself. A failed write raises; there is no drop counter.

Prax's own files log their diagnostics the same way, through
`handlers/logging/trail.py`'s `PraxTrail("<module>")`, onto
`prax/logs/<module>.jsonl` (`$AIPASS_TEST_LOG_DIR/prax/logs/` under a test).
Only the files that build door one hold stdlib `logging`, and prax publishes
that list.

## What prax publishes

`aipass.prax.apps.modules.logger` exports two facts for other branches:

| name | what |
|---|---|
| `log_backup_count()` | backups the `.log` tiers keep, the deeper of `system_logs` and `local_logs`, read from the config at call time; a reader of rotated `.log.N` files walks this many |
| `LOGGING_ALLOWED` | `(path under src/aipass, reason)` pairs: the only prax files allowed to import stdlib `logging` — `setup.py` and `direct.py`, which build door one on stdlib `Logger` and handlers |
| `LOGGER_DOORS` | `(path under src/aipass, reason)` pairs: the only files whose classes are logging doors — `SystemLogger` (`logger.py`), `DirectLogger` (`direct.py`), `TrailLogger` and `PraxTrail` (`trail.py`); sentry's one_logger reads it for its level-shaped-class key |

`test_logger_module.py::TestPublishedLoggingFacts` pins `LOGGING_ALLOWED` to the
files that actually import `logging`, and `LOGGER_DOORS` to the files that define a class with two or
more level methods, so neither list can drift.
