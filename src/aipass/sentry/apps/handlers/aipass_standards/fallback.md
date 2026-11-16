# Fallback Standards
**Status:** v1, ADVISORY (scored, never gating)
**Date:** 2026-11-16

---

## What It Is

A fallback answers a failure with a stand-in instead of an error: a default, an empty file, a
second import, a check that reads as passed. In an autonomous system a fallback is how a broken
part keeps running and nobody finds out. The owner's rule: a fallback is used only when it is
absolutely necessary, and then it is flagged in the audit and explained in a bypass row.

`silent_catch` asks whether a handler logs. `logged_fallback` asks whether the default a handler
returns can be told apart from an answer. This rule asks whether the handler is a fallback at all,
and a log line does not answer that. The prax logger writes only to log files, so a warning is
read by nobody unless something goes looking.

---

## The shapes

An `except` handler that does not raise, exit or show the failure (`print`, `echo`, `error(...)`,
a write to stdout or stderr), and does not hand the failure on as a value, is a fallback when:

| shape | the handler |
|---|---|
| import-failure stand-in | catches `ImportError`/`ModuleNotFoundError`, or guards `import_module`, `find_spec`, `exec_module` |
| unreadable file read as a default | catches a decode or I/O error (`JSONDecodeError`, `ValueError`, `OSError`, `Exception`, bare ...) around a read (`open`, `read_text`, `json.load`, `read_*`, `load_*`, `*_json`) |
| check that cannot run reads as passed | sits in a function named for a check (`check`, `gate`, `lint`, `valid`, `verif`, `guard`, `protect`, `trust`, `allow`, `permit`, `authori`, `enforce`) |
| fallback disguised as a word | names itself `best effort`, `graceful`, `legacy`, `compat` or `fall back` in its body, the two lines over its `try`, or its function's name |
| default with no warning-level log | logs at `debug` or `info` only, or not at all |

One shape outside an `except`: **a missing tool reads as passed**, an `if not tool:` (or `tool is
None`) that returns without raising, where `tool` came from `shutil.which` or `find_spec`.

"Hands the failure on" is read mechanically: the handler uses the bound exception outside a log
call, or returns, assigns or passes to a call a non-empty string (a reason), an upper-case name (a sentinel such as
`BOOT_UNREACHABLE`), or `False` outside a check-named function. The reason may sit inside a record
(`[CheckResult("registry", FAIL, "corrupt JSON")]`). A value that also holds `True` claims success
(`result(True, "Not judged")`), so its string is a note, not a reason. An import handler carries the
failure only when it imports nothing in its place and returns the exception or a record with a reason
(`{"stderr": "plugin not available", "exit_code": 1}`); a flag (`X_AVAILABLE = False`), a sentinel
or a bare string is the stand-in.

## Not flagged

| case | why |
|---|---|
| a handler that only `continue`s or `break`s, after warning-level log lines if any | the loop tries its next candidate; nothing stands in. An `info`/`debug` line before the skip is read by nobody, so that skip is judged, and an import loop's skip with a log line is judged too: the module's commands vanish |
| `FileNotFoundError` alone around a read | absence, not corruption: a missing file read as empty is a documented default |
| `ProcessLookupError` alone around `kill`/`killpg`/`_kill`/`send_signal` | "no such process" is the answer: the state a kill wanted, or what a liveness probe (`os.kill(pid, 0)`) asked. Caught beside `OSError`, or around any other call, it is judged as usual |
| a handler that logs at warning or above and takes none of the first four shapes | `silent_catch` and `logged_fallback` judge it |

## What a checker cannot judge

These are fallbacks too, and they are review rules, not checks:

- **`dict.get(key, default)`**: an optional field and a required field read with a default look the same. About 1,300 sites in the 2026-11-14 corpus; a check over them is noise.
- **An env-or-default (`os.environ.get("X", default)`, `${X:-default}`)**: a convention and a dropped required setting look the same.
- **A helper that swallows**: `return _broken(event, exc)` hands the exception to a function; whether that function shows it is not read across the call.
- **A missing program read as a missing file**: `FileNotFoundError` around `subprocess.run(...)` plus `json.loads(...)` is a missing binary, yet it passes as absence.
- **A boolean's polarity in a check**: `return False` from `is_protected` passes the gate, from `is_valid` fails it. Only the name tells, and the rule does not read names that far.

On review, ask of each one: if this default is used, does anyone find out?

## Waivers

One bypass row per site, with `lines` or `functions` and a reason. A whole-file row for this
standard waives nothing. A whole-file row for `silent_catch` or `logged_fallback` still waives its
file for now; the audit's bypass notes list each one as outlawed so it can be pinned.

```json
{"file": "apps/handlers/config/loader.py", "standard": "fallback", "lines": [199],
 "reason": "the gates load from gates.builtin_config(); identity injectors stand down and the ERROR line is the trace"}
```

## Measured

On the 2026-11-14 corpus (5,641 sites, about 870 read by eye), eye-read rows within three lines of a hit:

| | eye-read rows | silent_catch + logged_fallback | with fallback |
|---|---|---|---|
| SILENT | 91 | 4 | 18 |
| LOGGED | 283 | 16 | 109 |

Over the eye-read `except` rows the corpus judged LEGIT, LOUD or FALSE, 77 of 405 are flagged too. Over `src/aipass/*/apps`: 868 hits in 388 files. That is why this rule is advisory.

## Scoring

Scored per file, 0 on any unwaived hit, else 100; every hit goes on ONE check as
`<file>:<line> <shape> - <cure>`. ADVISORY: the score prints and never enters the branch average.

## The cure

Raise, so the failure reaches someone. When the fallback is necessary, keep it and waive that one
site with a bypass row that says why it is safe.

---

[← Back to README](../../../README.md)
