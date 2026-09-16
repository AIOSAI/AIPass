# discovery — the module registry and its watcher

The scheduled scan that builds the registry, and the watcher's own lifecycle events.

Moved out of `README.md` on 2026-09-15 (DPLAN-0347, the layer contract): the README is the
face, the depth lives here. Back to the [branch README](../README.md).

---

## Discovery is a scheduled scan

**DPLAN-0339 step 4, 2026-09-12.** `drone @prax discover run` walks the ecosystem
once and writes `prax_registry.json` as a **snapshot**: modules added, modules
whose file is gone removed, `discovered_time` carried over for anything already
on record. It runs daily as `module-scan-daily` in `.daemon/schedule.json`
(04:30, `timeout_seconds` 60, `notify: false`). The verb existed before and was
archived 2026-03-18 when discovery became a per-process watch; this brings it
back and retires the watch. Bare `drone @prax discover` shows introspection and
scans nothing — the fleet's module standard, and the right default for a verb
that rewrites a registry.

**What it replaced.** `SystemLogger._ensure_watcher` started
`start_file_watcher_in_background()` on the **first log line of every process**:
a daemon thread that walked 1,589 directories and installed one inotify watch per
directory, then died with the process. Short-lived processes never finished it.
Long-lived processes that merely logged carried a whole-tree watch by accident —
6,356 of this machine's 6,634 inotify watches were four such processes.

**It was also not working.** Measured 2026-09-11: the registry held **250 of the
1,442 modules a scan finds — 17%** — because a module was registered only if it
happened to be created while some process was both alive and still walking. It
never pruned either: the first real scan removed **55** entries, including probe
files deleted in August and flagged as unpruned back on 09-04.

| | before | after |
|---|---|---|
| modules in the registry | 250 | **1,442** |
| inotify watches held by a process that logs | ~1,589 | **0** |
| threads started by the first log line | 1 (`prax-watcher-start`) | **0** |
| first `.info()` | 0.420 s | **0.011 s** |
| steady state | 0.402 ms/line | **0.232 ms/line** |

The first scan reported **+1,245 / -55 / 197 unchanged**; a second run over the
unchanged tree reports **0 and 0**, which is what makes it safe to schedule. A
full scan is 5.5 s wall end to end (the walk alone is 0.18 s).

**Steady state improved, which was not the plan.** Step 3 measured 0.402 ms/line
with the background walk still running; the walk was contending with the caller
for the GIL for its whole life. With it gone the line costs 0.232 ms. The
contention DPLAN-0339 measured in both directions is simply not there any more.

**Logging never depended on discovery.** A module gets its log file when it logs,
not when it is registered; nothing outside prax reads the registry, and nothing
anywhere reads `discovered_time`. What the registry feeds is prax's own dedupe
and the module count in `drone @prax status`.

**What still starts a watcher.** `initialize_logging_system()` →
`run_initialize` → `start_file_watcher()`, synchronously, for the life of that
process. That door is deliberate and unchanged, and it is why the liveness check,
the `died` record and the `file_watcher_died` fire all stay: a process that opens
it can still lose its watchdog dispatcher (DPLAN-0305) and must still find out.
(Both the `died` record and the fire work as of FPLAN-0556 — until then the fire
was gated behind an import that always failed. See "The watcher's own events".)

## The watcher's own events were never reaching the bus

**FPLAN-0556, 2026-09-12.** Proving the section above turned up three
`aipass.trigger` *package shells* in a process that only logged, and pulling that
thread found a fire that had never fired.

`handlers/discovery/watcher.py` held a module-level
`from aipass.trigger.apps.modules.core import trigger`. It could not succeed, and
never had: this module is still executing its own import when it reaches that
line → trigger's `core.py:20` does `from aipass.prax.apps.modules.logger import
system_logger` → prax's logger does `from ...discovery.watcher import
is_file_watcher_active` → the watcher is partially initialised and those names do
not exist yet → `ImportError`. Python discarded `core` and kept the three parent
packages it had already created, which is where the shells came from.

The cost was not the shells. The fallback set a module-level
`_HAS_TRIGGER = False` that nothing could ever set back to True, and both fires
in the file sat behind it: **`module_discovered` and `file_watcher_died` had
never once reached the bus.** `file_watcher_died` is the one that matters — it is
the escalation path for DPLAN-0305, and the step-4 decision in DPLAN-0339 to keep
it was made about a fire that was already dead. Nobody knew, because a gate that
is always closed and a bus with no listener look identical from outside.

The cure is the same shape as the lifecycle doors in [logging_api.md](logging_api.md): `_get_trigger()` imports
at the fire site, guarded `(ImportError, OSError)` to a warning, and returns
`None` when the host cannot give us a bus. `_HAS_TRIGGER` is gone — a flag that
could only ever hold one value was not telling anyone anything. By the time a
fire site runs, this module is fully imported and the cycle is gone, so the same
import succeeds. Proven live: a throwaway that drives `on_created` and
`_report_watcher_death` under `AIPASS_TEST_LOG_DIR` sees
`[('module_discovered', 'fplan0556_probe_module'), ('file_watcher_died', 7)]` on
a listener double attached to the real bus.

What the 2026-08-31 Windows CI incident taught is kept in full — the guard is
still `(ImportError, OSError)`, because trigger's own import guard can raise
`FileNotFoundError` on a host with no readable working directory, and an optional
dependency's fallback must be at least as wide as the failures its import can
produce. Only the *placement* those pins encoded was dropped, and the placement
was the defect.

## The discovery watcher cannot kill its own thread

`PythonFileWatcher.on_created` guards its **whole body** with `except Exception`,
and that breadth is deliberate. watchdog's dispatcher loop
(`observers/api.py::EventDispatcher.run`) catches only `queue.Empty`, so any
exception escaping a handler kills the dispatcher thread permanently and
silently, while the emitter keeps filling an **unbounded** queue that nobody
drains again. The process then retains every filesystem event in the ecosystem
for as long as it lives.

That happened. On 2026-08-18 at 02:19 an archived probe file
(`api/apps/handlers/host/.archive/probe.py`) was created and deleted inside the
same second; `stat()` on the vanished path raised `FileNotFoundError` from
`on_created`; **six** long-running processes lost their dispatcher at the same
instant and grew to ~2.3GB RSS each — 13.7 of 15GB with swap full — over the
next 15 hours, with nothing logged. Diagnosed by @devpulse in DPLAN-0305.

The evidence is reproduced here rather than referenced, because the log it came
from lives in an archive directory and plans are not tracked either — under the
archive doctrine, a record that must survive belongs in tracked prose:

```
Exception in thread Thread-1:
Traceback (most recent call last):
  File "/usr/lib/python3.12/threading.py", line 1073, in _bootstrap_inner
    self.run()
  File ".../watchdog/observers/api.py", line 213, in run
    self.dispatch_events(self.event_queue)
  File ".../watchdog/observers/api.py", line 391, in dispatch_events
    handler.dispatch(event)
  File ".../watchdog/events.py", line 217, in dispatch
    getattr(self, f"on_{event.event_type}")(event)
  File ".../prax/apps/handlers/discovery/watcher.py", line 88, in on_created
    "size": py_file.stat().st_size,
            ^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/pathlib.py", line 842, in stat
    return os.stat(self, follow_symlinks=follow_symlinks)
FileNotFoundError: [Errno 2] No such file or directory:
  '.../src/aipass/api/apps/handlers/host/.archive/probe.py'
```

Note the last frame: `run` catches `queue.Empty` and nothing else, so the thread
simply ends. Nothing above it ever hears about it.

Two things came out of it, both pinned by tests that run against a **real**
watchdog observer (a mocked dispatcher cannot die, so a mocked test would pass
against the broken code):

- **The guard.** Discovery is best-effort by nature — the file it describes is a
  moving target — so a failure is reported and swallowed. Losing one module
  registration is a rounding error next to losing the watcher.
- **A liveness check that can actually fire.** `is_file_watcher_active()` already
  existed *and was already called* — but only from `SystemLogger._ensure_watcher`,
  whose body runs once per process behind a `_watcher_started` flag that is never
  reset. It answered at the one moment the watcher could not yet have died, and
  never again. `check_file_watcher_liveness()` runs throttled (~1 real check per
  60s) on the logging path, reports a death loudly **once** with the stranded
  queue depth, and fires `file_watcher_died` on the trigger bus. It never raises:
  it is called by the logger, and a health check that breaks logging is worse
  than the condition it detects.

The check is throttled *and* lock-free in the common case, both pinned — the
throttle moving inside the lock would change cost rather than answers, and would
put every log call in the ecosystem on one mutex with nothing to catch it.

