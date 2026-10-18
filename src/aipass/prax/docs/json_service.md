[<- Back to the README](../README.md)

# The fleet json service

The config/data/log triplet every branch writes through, its write rules, and its test seam.

---

## The fleet json service

**Prax owns the fleet's one JSON handler implementation.** One source; every
branch follows the one file.

```python
from aipass.prax import json_handler          # the entry point, the only sanctioned import
```

- `apps/handlers/json/json_service.py` — the implementation. Stdlib only, so it
  imports without the logger graph. No `resolve()`, no `getcwd()`, no
  `inspect.stack()`: it runs with a deleted working directory.
- `apps/handlers/json/json_handler.py` — prax's own shim, byte-identical in
  every branch; seedgo accepts it by hash, not by substring. It BINDS the
  service's callables and never wraps them: a wrapper would add a stack frame and
  silently rename every entry in the operations log.
- The default document is in code, not a template file — a default that lives in
  a file can go missing, and a handler whose default is missing stops
  self-healing exactly when it is needed.

**What the entry point hands you.** `from aipass.prax import json_handler` gives
you the **service module** — `for_module()`, `JsonHandle`, `InvalidDocument`,
`WriteFailed`. That is what a branch's shim imports before binding a handle to
itself with `for_module(__file__)`. Branch code calls its own shim
(`from aipass.<branch>.apps.handlers.json import json_handler`) and gets the
bound names — `load_json`, `save_json`, `log_operation`, and the rest.

**Three documents per module, three jobs.** The log
(`<module>_log.json`) is the per-module operation trail, one entry per
`log_operation`, rotating at the config's cap. The data document
(`<module>_data.json`) is lifetime state: every log write that lands also bumps
`operations_total` and stamps `last_operation` and `last_updated`, merging those
keys into the document and never replacing it, and a data document missing its
base keys (`created`/`last_updated`) is healed, not refused. The config
(`<module>_config.json`) is the rotation cap, `config.max_log_entries`, default
100. The bump is telemetry: a data write that fails logs a warning and
`log_operation` still answers the log's own `True`. There is no success/failure
counter, because the call carries no success signal; older
`operations_successful`/`operations_failed` keys are left exactly as they are.
The bump is a read-modify-write like the log itself, so under racing writers
`operations_total` is a lower bound, not an exact count, and it costs one more
staged write per call. `rate_tracker` keeps its `files` in that same
`rate_tracker_data.json`, and its save sets only `files` (and `module_name` when
absent) on the document it loaded, so `created` and the counters survive a scan.

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
`from aipass.prax import json_handler` in a fresh interpreter imports a fixed set
of prax modules (`EXPECTED_COLD_FOOTPRINT`) and no third-party package: `aipass.trigger` and the whole watchdog edge
stay cold. Pinned by `TestLazyInitImportFootprint` in
`tests/test_logger_module.py`, which measures in a subprocess — in-process the
number is meaningless, pytest has already imported prax's world.

**Return semantics:** `save_json` raises `WriteFailed` rather than answering
`False` (a lost document must not look like success) and `InvalidDocument`
rather than `False` (a caller bug is not a disk failure). `write_json` answers
`bool`. `log_operation` is telemetry and answers `False` on a write failure — it
runs on the monitor's display and watchdog threads, where a raising writer is
silent half-death.

## Write rules

**A write never changes a document's mode.** `os.replace` carries the **staged**
file's mode onto the target, and a temp file is created at `0600`, so an
unguarded staged write narrows every document it rewrites. An existing document
keeps its own mode (read off the target, applied to the staged fd with `fchmod`,
which the umask does not touch) and a new one is created with `0o666` for the
**kernel** to narrow by the process umask — byte for byte what `open(path, "w")`
would produce. The umask is never read: `os.umask()` both sets and returns, so
reading it means briefly widening it for every other thread, and prax runs
watchdog and display threads. Pinned at 664/644/600/640, and for a fresh document
against a reference file created by a plain `open()` in the same directory — the
expectation is measured, never the constant `0664`.

**NaN and Infinity are refused.** `json.dumps` defaults to `allow_nan=True` and
writes the bare tokens `NaN`/`Infinity`/`-Infinity`, which are not JSON: the
document lands, prax reads it back happily, and it fails in some other
language's strict parser days later, nowhere near the branch that wrote it. The
service passes `allow_nan=False` and lets json's own **`ValueError`** out — the
same answer it already gives an unknown `json_type`. `log_operation` still
answers `False` rather than raising, because it runs per event on threads where
a raising writer is silent half-death.

**A staged file's name does not read the clock.** Names come from `os.getpid()`
+ `itertools.count()`: seedgo's cross-branch contract stubs the module's `time`
to take the sleep out of the bounded retry, so a clock-derived name breaks every
branch's contract tests.

## The test seam

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
works. A module-level constant cannot be redirected by a conftest that runs after
something already imported the module, and a comparison against an import-time
value breaks on `importlib.reload` (a monkeypatch teardown writes the pre-reload
Path onto the post-reload module, and the redirect dies silently for the rest of
the session). A property has no fixed point to go stale: there is nothing to
compare and nothing to write back.

An **empty** value is absence, not a redirect — `Path("") / "prax"` is relative
and would scatter state wherever the process happens to stand. Pinned in
`tests/test_json_handler.py`, and in subprocesses (both import orderings) in
`tests/test_json_durability.py`, because in-process the ordering under test is
already decided.

Each branch gets this by binding the service; no branch adopts a spelling of its
own. And the per-module logger patch stays **opt-in per module, never blanket
autouse** — a blanket mock silences a test's `caplog` pin on a refused-and-named
error, and a suite that cannot show its refusals are loud has traded evidence for
a number.
