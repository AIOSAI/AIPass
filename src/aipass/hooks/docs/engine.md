[<- Back to the README](../README.md)

# The engine

**Branch** hooks · **Code** `apps/modules/engine.py`, `apps/handlers/config/output_merge.py`, `apps/handlers/module_root.py`

The dispatch path from a normalized event to a handler, how the stdouts become one document, and why every module in this branch must import in a process whose working directory is gone.

---

## How It Works

1. Provider settings invoke the bridge one of two ways: `claude.py <Event>` (one fan-out entry, all enabled handlers — tool events) or `claude.py <Event>:<hook_name>` (one entry per handler — UserPromptSubmit, PreCompact, SessionStart). There is no bare `claude.py UserPromptSubmit` entry; it is 13 named ones.
2. Bridge normalizes stdin, loads project config via `loader.find_project_config()`
3. Bridge calls `engine.dispatch(event_type, stdin_data, config)`
4. Engine runs matching hooks sequentially, logs each to JSONL
5. First hook returning `{"decision": "block"}` with exit code 2 = bail (block the action)
6. Exit code 2 without JSON = crash (log error, continue to next hook)
7. Hook stdouts returned to the platform as ONE document (`handlers/config/output_merge.py`). Claude Code parses a hook's stdout as a single document: two JSON objects on two lines are a non-blocking hook error and NEITHER is applied. So:
   - a single output passes through untouched, and plain-only outputs are newline-joined as before;
   - once any handler answers in JSON, the answer is one object: `additionalContext` joined in handler order by a blank line, `systemMessage` joined by a newline, other keys first-handler-wins (a conflict is logged);
   - the merged context stays within Claude Code's 10,000 UTF-16-unit display limit. The post-compact re-ground is placed first, and a context that would cross the limit is dropped with a WARNING naming it — never silently.

## Dynamic Dispatch

Handlers are called **dynamically at runtime** — the engine uses `importlib.import_module()` + `getattr()` on the dotted handler path from `hooks.json` (e.g., `aipass.hooks.apps.handlers.prompt.identity.handle`). Handlers are never statically imported. This means static analysis tools (including seedgo's dead_code checker) cannot see that they are used — the last unshielded run scored `dead_code` at 40% and reported 29 of 49 files unreferenced, which is this indirection and not rot. That measurement is historic and not re-verified here: `apps/` now carries 59 live non-`__init__` files (61 on disk, two parked as `(disabled)`), and re-running unshielded needs a bypass-rule change this branch does not make for a doc pass. Shielded, `dead_code` audits 100%.

Every handler is verified wired in `hooks.json` (32 entries, 31 distinct names — `auto_process` is the one name wired twice, on UserPromptSubmit and PreCompact). **30 of the 32 are `enabled: true`** as of 2026-09-07: `feedback_pulse` is off by choice in this repo, and `auto_watchdog` was flipped off when it was retired (FPLAN-0495 item 3). Editing `.aipass/hooks.json` breaks its enrolled hash, which disables EVERY hook for the project until a human re-enrolls with `aipass trust <repo-root>` — that checkpoint is deliberate, it does not auto-heal, and it is outstanding right now. Firing evidence is a *narrow* window — `logs/engine.jsonl` rotates at `JSONL_MAX_BYTES = 500_000` keeping one `.1` backup (prax `jsonl_writer.py`), so it holds minutes to tens of minutes of live traffic and absence from it is **not** evidence of a dead wire. Measured 2026-09-05 over a 4.3-minute window: **27 of the 31 names appear**. The four absentees are the three PreCompact-only handlers (`pre_compact`, `pre_compact_rollover`, `pre_compact_prep`) and `cadence_reset` — PreCompact did not fire in the window and SessionStart fired before it opened. `feedback_pulse` does appear, but as `{"action": "skipped_disabled"}`: it is wired `enabled: false` in this repo, so it is dispatched and declines.

## Importing Without a Working Directory

Every hooks module must import in a process whose working directory is gone.
`ntpath.realpath` reads `os.getcwd()` UNCONDITIONALLY — not only for relative
paths, the way `posixpath` does — and `Path.resolve()` routes through it. So on
Windows every `Path(__file__).resolve()` *reached at import time* is an
import-time working-directory dependency, and a process whose cwd was deleted
cannot import the module at all. (Measured on the Windows CI gate 2026-08-31,
@memory's finding, routed here by @devpulse.)

**The one spelling:** `apps/handlers/module_root.py` → `module_file(__file__)`.
It still attempts `.resolve()` — normalising symlinks is why the call exists —
and falls back to the absolute spelling only in the world where the alternative
is a dead import. New module-level `__file__` resolution goes through it.

**The count was wrong until the guard was cured.** `apps/handlers/__init__.py`
runs a cross-branch import guard on *every* hooks import, and it died first, so
all 68 modules reported that one line and no other site was visible. Curing the
guard is what made the remaining sites measurable — the honest sequence was
1 → 5 → 6, each cure unmasking the next. `tests/test_import_dead_cwd.py` pins
the whole tree, discovered by walk rather than listed.

**Two worlds, because one proves half.** World A emulates ntpath (`realpath`
reads cwd, `getcwd` denied) and convicts an unguarded `resolve()`; on Linux it
does NOT convict `inspect.stack()`, because there the raise happens inside
`getabsfile()` where inspect catches it. World B denies `os.path.realpath`
outright and convicts `inspect.stack()` at `inspect.py:1009`. The guard now
walks frames with `sys._getframe` and reads the import line with `linecache`.

The `inspect.stack()` ban is **structural** (AST, not grep): the guard's
caller-is-None branch is unreachable from any import probe, so a regrown call
there is invisible to the world tests — a mutant proved exactly that, killed
only by the AST pin. AST and not a string ban because this guard's own
docstrings name the defect, and a spelling ban convicts prose while acquitting
code.

---

## Related

- [wiring.md](wiring.md) — how the event reaches the bridge in the first place
- [diagnostics.md](diagnostics.md) — the two streams every dispatch is written to
