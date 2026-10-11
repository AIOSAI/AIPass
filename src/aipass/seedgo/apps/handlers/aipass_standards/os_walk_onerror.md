# Os Walk Onerror Standards
**Status:** v1
**Date:** 2026-09-25

---

## What It Is

`os.walk` swallows every `OSError` its `scandir` raises unless it is handed `onerror=`. A
directory it cannot list is not walked. Nothing is raised and nothing is returned, so the run
reports success over a tree it never saw.

The specimen is @backup's `apps/handlers/scan/walk.py:34`, the scan every backup starts from:

```python
for dirpath, _dirnames, filenames in os.walk(root_path, followlinks=False):  # :34 an unreadable subtree drops out of the backup
```

---

## The shape

A call that resolves to `os.walk` and has:

- no `onerror=` keyword, or `onerror=None`, which is the default again.

The hit is reported on the call's line. Names resolve through the file's own imports, so
`import os as o` and `from os import walk` are both followed. Product code only: a test walking
its own `tmp_path` is not the hazard.

## What is not convicted

| case | why |
|---|---|
| `onerror=` with any value but `None` | a hook is named; what it does cannot be read from the call (see the cure) |
| a third positional argument | that slot is `onerror` |
| `**kwargs` | it can carry `onerror` |
| `Path.rglob`, `Path.glob` | there is no error hook to pass; counted below, never judged |
| the words inside a string or comment | not a call |
| test files | `APPLIES_TO = "production"` |

---

## Check first

Measured 2026-09-25 over `src/aipass/*/apps`, before the rule landed.

| | |
|---|---|
| product files | 1,214 |
| `os.walk` calls | 13 |
| convicted | 8 calls in 8 files, 6 branches |
| already pass `onerror` | 5: @drone `rm_handler.py` x2, @flow `heal_registry.py` and `monitor_ops.py`, @devpulse `release_notify/managers.py` |
| `rglob`, counted only | 62, 43 of them @seedgo's |

| branch | convicted |
|---|---|
| seedgo | `aipass_standards/readme_check.py`, `audit_tests/m10.py` |
| drone | `deletion_log.py`, `broker/daemon.py` |
| ai_mail | `central_writer.py` |
| aipass | `init/git_auth.py` |
| backup | `scan/walk.py` (the specimen) |
| devpulse | `watchdog/agent.py` |

A grep for `os.walk(` without `onerror` finds nine. The ninth is a docstring, not a call.

## Scoring

Scored per file: 0 on any finding, else 100. Every hit goes on ONE check, as
`<file>:<line> os.walk without onerror - <why>; <cure>`.

## The cure

Pass `onerror=` a callable that raises, or one that records the error into what the function
returns, so the caller can see the part of the tree that was not read. A callable that only logs
is the same swallow with a line in a log. The checker cannot tell these apart, so it accepts any
hook; that judgment is the reviewer's.

---

[← Back to README](../../../README.md)
