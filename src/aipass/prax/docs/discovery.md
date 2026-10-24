[<- Back to the README](../README.md)

# discovery — the module registry and its watcher

The scheduled scan that builds the registry, and the watcher's own lifecycle events.

---

## Discovery is a scheduled scan

`drone @prax discover run` walks the ecosystem once and writes `prax_registry.json`
as a **snapshot**: modules added, modules whose file is gone removed,
`discovered_time` carried over for anything already on record. A second run over
an unchanged tree reports 0 added and 0 removed, which is what makes it safe to
schedule. It runs daily as `module-scan-daily` in `.daemon/schedule.json` (04:30,
`timeout_seconds` 60, `notify: false`). Bare `drone @prax discover` shows
introspection and scans nothing — the fleet's module standard, and the right
default for a verb that rewrites a registry.

A log line starts no watcher and no thread. Discovery is not a per-process watch:
a whole-tree inotify watch per process costs one watch per directory and contends
with the caller for the GIL, and a watch registers only what is created while it
is alive.

**Logging does not depend on discovery.** A module gets its log file when it logs,
not when it is registered; nothing outside prax reads the registry, and nothing
anywhere reads `discovered_time`. What the registry feeds is prax's own dedupe
and the module count in `drone @prax status`.

**What starts a watcher.** Only a process that calls `start_file_watcher()`
itself; nothing in production does. A process that opens it can lose its watchdog
dispatcher, which is why the liveness check, the `died` record and the
`file_watcher_died` fire exist.

## The watcher's own events

The watcher fires `module_discovered` and `file_watcher_died` on the trigger bus.
`_get_trigger()` in `handlers/discovery/watcher.py` imports trigger at the fire
site, not at module level: a module-level import cannot succeed, because trigger's
`core.py` imports prax's logger, which imports this watcher while it is still
initialising. By the time a fire site runs, this module is fully imported and the
cycle is gone.

The import is guarded `(ImportError, OSError)` to a warning and returns `None`
when the host cannot give a bus. The guard is that wide because trigger's own
import guard can raise `FileNotFoundError` on a host with no readable working
directory, and an optional dependency's fallback must be at least as wide as the
failures its import can produce. There is no module-level "trigger available"
flag: a flag set once at import could only ever hold the value of the failed
first attempt.

## The discovery watcher cannot kill its own thread

`PythonFileWatcher.on_created` guards its **whole body** with `except Exception`,
and that breadth is deliberate. watchdog's dispatcher loop
(`observers/api.py::EventDispatcher.run`) catches only `queue.Empty`, so any
exception escaping a handler kills the dispatcher thread permanently and
silently, while the emitter keeps filling an **unbounded** queue that nobody
drains again. The process then retains every filesystem event in the ecosystem
for as long as it lives, which shows up as steady memory growth. The ordinary
trigger is a file created and deleted inside the same second: `stat()` on the
vanished path raises `FileNotFoundError` from `on_created`.

Two things guard against it, both pinned by tests that run against a **real**
watchdog observer (a mocked dispatcher cannot die, so a mocked test would pass
against broken code):

- **The guard.** Discovery is best-effort by nature — the file it describes is a
  moving target — so a failure is reported and swallowed. Losing one module
  registration is a rounding error next to losing the watcher.
- **A liveness check that fires.** `check_file_watcher_liveness()` runs throttled
  (one real check per 60 s) on the logging path, reports a death loudly **once**
  with the stranded queue depth, writes the `died` record and fires
  `file_watcher_died` on the trigger bus. It never raises: it is called by the
  logger, and a health check that breaks logging is worse than the condition it
  detects.

The check is throttled *and* lock-free in the common case, both pinned — the
throttle moving inside the lock would change cost rather than answers, and would
put every log call in the ecosystem on one mutex with nothing to catch it.
