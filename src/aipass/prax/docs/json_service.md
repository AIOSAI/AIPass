# The fleet json service

The config/data/log triplet every branch writes through, its test seam, and the post-sweep bundle.

Moved out of `README.md` on 2026-09-15 (DPLAN-0347, the layer contract): the README is the
face, the depth lives here. Back to the [branch README](../README.md).

---

## The fleet json service (DPLAN-0325)

**Prax owns the fleet's one JSON handler implementation.** Boardroom
`r/boardroom-json-service` post 8, the owner's ruling 2026-09-03: the fleet's drift
no longer matters — one source, every branch follows the one file.

```python
from aipass.prax import json_handler          # the entry point, the only sanctioned import
```

- `apps/handlers/json/json_service.py` — the implementation. Stdlib only, so it
  imports without the logger graph. No `resolve()`, no `getcwd()`, no
  `inspect.stack()`: it runs with a deleted working directory.
- `apps/handlers/json/json_handler.py` — prax's own shim, byte-identical in all
  18 branches. **1724 bytes, sha256 `3456b766…cf0b7`** (verified 2026-09-05);
  seedgo accepts it by hash, not by substring. It BINDS the service's callables
  and never wraps them: a wrapper would add a stack frame and silently rename
  every entry in the operations log.
- The old handler and `json_templates/` are in
  `apps/handlers/json/.archive/`. The default document is in code now — a
  default that lives in a file can go missing, and a handler whose default is
  missing stops self-healing exactly when it is needed.

**What the entry point hands you.** `from aipass.prax import json_handler` gives
you the **service module** — `for_module()`, `JsonHandle`, `InvalidDocument`,
`WriteFailed`. That is what a branch's shim imports before binding a handle to
itself with `for_module(__file__)`. Branch code calls its own shim
(`from aipass.<branch>.apps.handlers.json import json_handler`) and gets the
bound names — `load_json`, `save_json`, `log_operation`, and the rest.

**Three documents per module, three jobs (FPLAN-0542, 2026-09-11).** The log
(`<module>_log.json`) is the per-module operation trail, one entry per
`log_operation`, rotating at the config's cap. The data document
(`<module>_data.json`) is lifetime state: every log write that lands also bumps
`operations_total` and stamps `last_operation` and `last_updated`, merging those
keys into the document and never replacing it, and a data document missing its
base keys (`created`/`last_updated` — `prax_json/prax_logger_data.json` is
literally `{}`) is healed, not refused. The config (`<module>_config.json`) is
the rotation cap, `config.max_log_entries`, default 100. The bump is telemetry:
a data write that fails logs a warning and `log_operation` still answers the
log's own `True`. There is no success/failure counter, because the call carries
no success signal; the old-era `operations_successful`/`operations_failed` keys
are left exactly as they are. The bump is a read-modify-write like the log
itself, so under racing writers `operations_total` is a lower bound, not an
exact count. It also costs one more staged write per call: median 9.5 ms before,
14.7 ms after, per `log_operation` (a single-machine reading, 5 interleaved runs
of 200 calls). `rate_tracker` keeps its `files` in that same
`rate_tracker_data.json`, and its save now sets only `files` (and `module_name`
when absent) on the document it loaded. The old save rebuilt the whole dict,
which re-stamped `created` on every scan and would have wiped the counters.

**Healing is per module, per call — there is no sweep.** `ensure_json_exists`
regenerates exactly one document (`<module>_<type>.json`) when it is missing,
empty, unreadable or structurally invalid. The one exception is a data document
that parses as a dict: it is healed in place (missing base keys added, every
other key kept) rather than regenerated. `ensure_module_jsons` does the
three types for one module. Nothing walks a directory and nothing repairs
another module's documents: a self-heal that ranges wider than the call that
triggered it would rewrite state nobody asked about, in a process that may only
have wanted to log one line.

**The package init is lazy** (PEP 562 `__getattr__` in `aipass/prax/__init__.py`).
`logger`, `append_jsonl` and `json_handler` resolve on first attribute access.
Measured, `from aipass.prax import json_handler` in a fresh interpreter:

| | aipass modules | third-party |
|---|---|---|
| eager init (before) | 30 | `watchdog` |
| lazy init (now) | **6** | **none** |

`aipass.trigger` and the whole watchdog edge stayed cold. Pinned by
`TestLazyInitImportFootprint` in `tests/test_logger_module.py`, which measures in
a subprocess — in-process the number is meaningless, pytest has already imported
prax's world.

**Return semantics changed with the service:** `save_json` raises `WriteFailed`
rather than answering `False` (a lost document must not look like success) and
`InvalidDocument` rather than `False` (a caller bug is not a disk failure).
`write_json` still answers `bool`. `log_operation` is telemetry and still answers
`False` on a write failure — it runs on the monitor's display and watchdog
threads, where a raising writer is silent half-death.

## The post-sweep bundle (2026-09-04, commit 08359ec2)

Four defects found after the migration, all in prax's tree, all fixed and pinned.

**A write no longer changes a mode nobody asked it to change.** The staged write
went through `tempfile.NamedTemporaryFile`, which creates at a hardcoded `0600`,
and `os.replace` carries the **staged** file's mode onto the target — so every
service write narrowed the document it rewrote, fleet-wide: a `664` config came
back `600` on its next write, and the group that could read it yesterday could
not today. Nothing failed loudly. Now an existing document keeps its own mode
(read off the target, applied to the staged fd with `fchmod`, which the umask
does not touch) and a new one is created with `0o666` for the **kernel** to
narrow by the process umask — byte for byte what `open(path, "w")` would have
produced. The umask is never read: `os.umask()` both sets and returns, so reading
it means briefly widening it for every other thread, and prax runs watchdog and
display threads. Pinned at 664/644/600/640, and for a fresh document against a
reference file created by a plain `open()` in the same directory in the same
breath — the expectation is measured, never the constant `0664`.

**NaN and Infinity are refused.** `json.dumps` defaults to `allow_nan=True` and
writes the bare tokens `NaN`/`Infinity`/`-Infinity`, which are not JSON: the
document lands, prax reads it back happily, and it fails in some other
language's strict parser days later, nowhere near the branch that wrote it. The
service passes `allow_nan=False` and lets json's own **`ValueError`** out — the
same answer it already gives an unknown `json_type`. `log_operation` still
answers `False` rather than raising, because it runs per event on threads where
a raising writer is silent half-death.

**A staged file's name must not read the clock.** The first cut of the mode fix
named temp files with `time.time_ns()`, and seedgo's cross-branch contract stubs
the module's `time` to take the sleep out of the bounded retry — 45 contract
tests across 15 branches went red on `AttributeError`. Names come from
`os.getpid()` + `itertools.count()` now. Worth writing down: the fleet contract
caught a prax defect within minutes of it existing.

**Superseded 2026-09-12 (DPLAN-0339 step 4): the logger starts no watcher at all
any more.** The section below is the record of how the cost was chased around
the process before the walk was removed from the logging path entirely; see
"Discovery is a scheduled scan" in [discovery.md](discovery.md).

**The watcher start does not block the first log line.** `SystemLogger._ensure_watcher`
called `start_file_watcher()` inline, and watchdog installs one inotify watch per
directory under the ecosystem root. Measured 2026-09-04 on this machine, 1605
directories: **0.119 s** when the calling thread is alone, **13.949 s (117×)**
when one other Python thread is CPU-busy — each `inotify_add_watch` drops the GIL
and then has to win it back from a thread that never blocks, so the walk pays up
to a full switch interval (5 ms) per directory. A suite whose only crime was to
log something waited seconds for a watcher it never asked about. The logger now
calls `start_file_watcher_in_background()`: same walk, same watches, on a thread
nobody joins — caller blocked **5.72 ms**, the walk finishing ~4.5 s later off to
the side. Neither cure first proposed would have worked: yielding between
directories adds handoffs to a walk already starving on them, and bounding the
walk to `apps/` (what Mission Control does) would stop discovering the 113 of 196
registered modules that live in `tests/` and elsewhere (counted 2026-09-05). `start_file_watcher()`
itself still blocks, for its one remaining caller
(`lifecycle.run_initialization`, which explicitly asked to initialise), and both
doors share one lock — without it each finds no observer, each walks, and the
second assignment orphans the first: two watches per directory and every event
delivered twice.

---

**`AIPASS_TEST_LOG_DIR` is the fleet contract, and the service made it simple.**
Every branch's documents are redirected by one variable, honoured by the service
itself:

```python
@property
def json_dir(self) -> Path:                      # json_service.py
    name = self.branch_root.name
    test_dir = os.environ.get("AIPASS_TEST_LOG_DIR")
    if test_dir:
        return Path(test_dir) / name / f"{name}_json"
    return self.branch_root / f"{name}_json"
```

**Resolved per call, never captured at import**, and that is the whole reason it
works. The two predecessors of this design both failed on import order — a
module-level constant cannot be redirected by a conftest that runs after
something already imported the module, and the "compare against the import-time
value" refinement that followed broke on `importlib.reload` (a monkeypatch
teardown writes the pre-reload Path onto the post-reload module, and the redirect
dies silently for the rest of the session — measured against @daemon's adoption,
2026-08-30). A property has no fixed point to go stale: there is nothing to
compare and nothing to write back. Both of those older mechanisms retired with
the old handler and are in `apps/handlers/json/.archive/json_handler.py` if
anyone needs the reasoning.

An **empty** value is absence, not a redirect — `Path("") / "prax"` is relative
and would scatter state wherever the process happens to stand. Pinned in
`tests/test_json_handler.py`, and in subprocesses (both import orderings) in
`tests/test_json_durability.py`, because in-process the ordering under test is
already decided.

Each branch gets this by binding the service; no branch adopts a spelling of its
own. And the per-module logger patch stays **opt-in per module, never blanket
autouse** — @daemon proved a blanket mock silenced their refused-and-named
`caplog` pin, and a suite that cannot show its refusals are loud has traded
evidence for a number.

