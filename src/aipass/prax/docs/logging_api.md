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

**Ruling 2026-08-30 — the object form stays recommended.** @seedgo widened the
`imports` standard to accept three spellings and asked prax, as the owner of the
logging contract, which one to recommend. The answer is this one, and the reason
is that the import form was never the thing doing damage.

The question arrived attached to a real measurement: one `@daemon` test performed
23 atomic writes into prax's live `prax_json/`, and the diagnosis was that
`from aipass.prax import logger` binds the logger *object*, so a conftest that
swaps `sys.modules["aipass.prax"]` cannot reach it. Measured here with an audit
hook before ruling, and the diagnosis does not survive:

| | import | 1st call | 2nd call |
|---|---|---|---|
| `from aipass.prax import logger` | 0 | **26** | 0 |
| `from aipass import prax` → `prax.logger` | 0 | **26** | 0 |
| `from ...modules.logger import system_logger as logger` | 0 | **26** | 0 |

**Importing prax writes nothing. The first `logger.info()` writes 26 times, and
the second writes nothing.** All three spellings are identical because the writes
come from the *call*, not the binding — the first call is what starts the file
watcher and auto-creates the per-module JSON. (It also fired
`trigger.fire("startup")` when this was measured; that fire was removed in
DPLAN-0339 step 3, see below.)
Changing the recommended import would have moved a number that does not depend
on it.

The rebindability claim also does not hold against the mechanism it names. With
the swap landing *after* the caller's import — the shape an autouse fixture
produces — every form returns the real logger, the module form included:

| swap timing | form 1 | form 2 (object) | form 3 (module) |
|---|---|---|---|
| `sys.modules` swap **after** import | REAL | REAL | **REAL** |
| `monkeypatch.setattr(prax, "logger", …)` | REAL | REAL | MOCK |
| `sys.modules` swap **before** import | **ModuleNotFoundError** | MOCK | MOCK |

Ordering decides this, not binding style. Two things follow that are worth more
than the ruling itself. First, a `sys.modules` swap that lands after import fixes
nothing in *any* spelling, so branches carrying that fixture are not protected
today and would not have been protected by migrating. Second, the form the
standard labels canonical — importing through `apps.modules.logger` — is the only
one that **crashes** against a mocked `aipass.prax`, because the mock package has
no `apps` submodule. A branch that follows the top recommendation and mocks prax
gets `ModuleNotFoundError`, not a mock.

Import cost was not load-bearing either: 131.0ms vs 130.7ms median over 5 samples
for the object and module forms — indistinguishable, because `prax/__init__.py`
eagerly imported `apps.modules.logger` at the time, so every spelling paid the
same package init. **That reason expired on 2026-09-03**: the init is lazy now
(PEP 562, see [json_service.md](json_service.md)), so importing `aipass.prax` no longer
pays for the logger graph and only a spelling that actually *touches* `logger`
does. The ruling itself is unaffected — it never rested on the cost — and
consistency remains the tiebreak: one spelling across the fleet is worth more
than a rebindability property that does not work.

**The defect that section named is fixed for module documents, and survives for
path-based writes.** The json service resolves its directory per call from
`AIPASS_TEST_LOG_DIR`, so everything written *by module name* is redirected.
Measured 2026-09-05, one `logger.info()` in a fresh interpreter with the
variable set:

```
files written into the real src/aipass/prax/prax_json/ : 0
files written under AIPASS_TEST_LOG_DIR                : 18
```

What is **not** redirected is the handful of module-level path constants built
from `__file__`. Measured the same night, with `AIPASS_TEST_LOG_DIR` set:

```
config.load.PRAX_JSON_DIR         -> src/aipass/prax/prax_json     <- real tree
registry.save.REGISTRY_FILE       -> …/prax_json/prax_registry.json <- real tree
logging.operations.LOG_FILE       -> …/prax_json/prax_logger_log.json <- real tree
config.load.get_system_logs_dir() -> /tmp/<redirect>/system         <- redirected
```

Four modules still build paths that way — `handlers/config/load.py`,
`handlers/config/ignore_patterns.py`, `handlers/registry/load.py` and
`handlers/registry/save.py` — and any write that goes through a *path* rather
than a module name (the module registry is the live one) lands in the real tree
under any suite. It is the same shape as before, one layer down. Reported
2026-09-05, unfixed here because this pass is documentation only.

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

@seedgo corrected their own dispatch within ten minutes of sending it, and the
corrected question is the better one: prax never published a mocking technique,
so five branches invented five, and all five miss. Measured by object identity
against a real consumer:

| technique | reaches |
|---|---|
| `patch("aipass.prax.logger")` | REAL |
| `patch("…apps.modules.logger.system_logger")` | REAL |
| `setitem(sys.modules, "…apps.modules.logger")` | REAL |
| `setitem(sys.modules, "aipass.prax")` | REAL |
| `patch("<the consuming module>.logger")` | **MOCK** |

The cause is in this package's own `__init__.py`, and the lazy rewrite did not
change it: `__getattr__` resolves `logger` once and caches the object in
`globals()`, so the object is still copied at the package boundary and copied
again into each consumer's globals. Anything patched at or above `aipass.prax`
is upstream of a copy already taken. **The last dot must be resolved at call
time**, which only the consumer-module patch does. prax's own conftest was one of
the four that miss — this is prax's gap before it is anyone else's.

**Interim technique, correct today, one line per consuming module:**

```python
patch("aipass.<branch>.apps.handlers.<module>.logger")
```

**But do not build patch lists on it.** That is not the contract prax wants to
leave standing, because it asks 18 branches to maintain a per-module list for a
problem prax should solve once — and a branch that forgets a module gets silence,
not an error.

**Ruling on the test seam: extend the mechanism that already exists, do not add a
new one.** prax already auto-detects pytest and redirects — no env var, no fixture,
no cooperation from the caller. It simply covers the wrong half. Measured with
`PYTEST_CURRENT_TEST` set, one `logger.info()`:

```
 4 writes -> /tmp/aipass_test_logs/   (log files — already redirected)
24 writes -> real src/aipass/prax/prax_json/   (JSON state — not redirected)
```

So the seam is built, proven and automatic for 4 of 28 writes. Extending it to
`PRAX_JSON_DIR` closes the remaining 24 and every branch's number at once, with
no patches, no import changes and nothing for a caller to remember. A new
`silence()` API would need adoption across 385 call sites; a new env var would
need a fixture nobody sets — @daemon offered exactly that mitigation to @memory
in good faith and it fixed 0%, because the thing it targeted was never the cause.
The explicit override for the other half already exists as `AIPASS_TEST_LOG_DIR`,
so the escape-hatch pattern is settled too.

Callers need do nothing and should change nothing. Reported shares — @drone 7650,
@memory 1552, @daemon 1096, @backup 778 — are prax's to fix, not theirs.

## The first log line no longer fires a startup event

**DPLAN-0339 step 3, 2026-09-12.** `SystemLogger._ensure_watcher` used to end
with `trigger.fire("startup")`, so every process in the fleet fired a startup
event on its first log line. That fire *was* the first log line: **0.339 s of its
0.361 s, 94%**, nearly all of it importing the `aipass.trigger` graph so that one
event could reach one handler.

What it bought was an error catch-up scan in trigger's `handle_startup`. At 5.1
fires a minute, **100 of 100** of those runs found 0 errors — and because every
process shared one throttle, a hook or a drone command routinely consumed the
recovery window seconds before the scan that actually needed it. Recovery now has
a real owner: trigger's `log_watcher_service` calls `run_error_catchup()` itself
at service start, and `last_scan_timestamp` advances only after a scan that
covered every file (FPLAN-0551, live since 00:28). Medic's digest lane never rode
the fire — it calls `run_startup_catchup()` directly, deliberately.

Measured here, 12 throwaway processes each side, `AIPASS_TEST_LOG_DIR` redirect,
live tree untouched:

| | median | range |
|---|---|---|
| first `.info()` before | 0.420 s | 0.336-0.826 |
| first `.info()` after | **0.016 s** | 0.012-0.021 |
| steady state before | 0.390 ms/line | 0.240-0.488 |
| steady state after | 0.402 ms/line | 0.384-0.574 |

**The first log line got ~26x cheaper; the steady state did not move.** The event
still exists and still has exactly one listener, and `drone @trigger fire startup`
still works — nothing fires it per-process any more, by design. Proof that the
per-process fire is gone: trigger's `startup_log.json` ring gained **40 records
from a batch of 40 short processes before the change and 0 after** (counted by
timestamp, because the ring is capped at 100 rows and a raw count is saturated).

## The lifecycle doors fire, the log line does not

**FPLAN-0555, 2026-09-12.** Removing the hot-path `startup` fire in step 3 left
`logger.py` with no `trigger.fire` anywhere, and seedgo's Trigger standard reads
that file-level: its Pattern 9 checks `initialize_*_system` / `shutdown_*_system`
only when the file contains no fire at all, so the two doors had been passing on
a technicality the whole time. Once the technicality went, the audit dropped to
99% and the CI gate went red (Linux run 34682737344).

The cure is the one the standard actually asks for. `initialize_logging_system()`
fires `logging_system_initialized` (carrying `modules_count`) after
`run_initialize` returns; `shutdown_logging_system()` fires
`logging_system_shutdown` after `run_shutdown`, last, so the event says the
system *is* down rather than that it is going down. seedgo's event table names no
system-lifecycle event, so those two names are prax's, following the convention
it does state: lowercase, underscore-separated, past tense.

**Both imports are inside their function, and that is the design, not a style
choice.** `from aipass.prax import logger` and every log line the fleet writes
must stay clear of the `aipass.trigger` import graph — that graph was 0.339 s of
a 0.361 s first log line before step 3. A door called deliberately, once, can
afford what a hot path cannot. Each fire is guarded `(ImportError, OSError)`
exactly as the removed one was: these doors must still work on a host where
trigger cannot import or inotify is exhausted, so a failed fire is a warning and
never a failed initialize. Nothing listens to either event today, by design — the
point of the standard is that a handler can plug in later without prax changing.

Measured on a fresh interpreter that imports the logger and logs one line:
**no `aipass.trigger` module at all**, not even a package shell, and the first
`.info()` costs about 0.010 s. Pinned in
`test_logger_module.py::TestLoggingPathIsTriggerFree`.

