# Logged Fallback Standards
**Status:** v1
**Date:** 2026-09-25

---

## What It Is

`silent_catch`'s sibling. `silent_catch` acquits any `except` that calls the logger. This rule
reads what the handler returns. A handler that logs and then returns a value the success path
can also return hands its caller a failure dressed as an answer. The caller cannot tell "it
failed" from "it worked and found nothing". The log line does not help the caller, because the
caller never reads the log.

The owner's ruling, 2026-09-25 12:17: *"ok narrow it then land it."* The first measurement
(any literal default, 656 hits, about 31% precise) was stopped. This is the narrowed rule.

---

## The shape

An `except` handler that:

- does not raise anywhere in its body (bare `raise`, `raise X`, `raise X from Y`), and
- ENDS in `return` of a literal default: a constant (`None`, `False`, `0`, `""` ...), an empty
  container (`{}`, `[]`, `()`, `set()`, `dict()`, `list()`, `tuple()`), or a string built from
  the exception (an f-string naming it, or `str(exc)`), and
- sits in a function whose success path can return that same value.

"Can return that same value" is mechanical, not judged. Some `return` outside every handler of
the function returns either:

- (a) a literal equal to the default, with the same type and the same value, so `False` is not `0`; or
- (b) a name whose first binding in the function is that literal:

```python
def find(pattern):
    results = []              # first binding: []
    try:
        results = search(pattern)
    except OSError as exc:
        logger.warning(exc)
        return []             # convicted: the success path can return [] too
    return results
```

A string built from the exception matches any string literal, or a name first bound to one.
Logging never acquits. The hit is reported on the handler's `return` line.

## What is not convicted, and why

Each edge case was decided from the 40-hit sample, not from taste.

| case | why |
|---|---|
| a sentinel: `return None` where every success return is a dict, `return -1` where the success path returns a count | the caller can tell the two apart |
| a handler that raises, anywhere in its body | the failure reaches the caller |
| assign-and-fall-through: the handler sets `data = {}` and falls through, or falls through to a `return` after the `try` | real (@backup `state/backup_timestamps.py`, `drive/share.py`), but this rule reads only a handler's own final `return` |
| a generator | a `yield` function has no return value to compare |
| a `return` inside `finally` | it runs on both paths, so it is not the success path |
| a success `return` of a call, an attribute, or a name first bound to a parameter, a call or a loop target | what it returns cannot be read from the statement |
| a nested function | judged on its own returns, never its parent's. The first measurement credited a nested def with its parent's returns; that bug is why this is written down |

---

## Check first

Measured 2026-09-25 over `src/aipass/*/apps`, before the rule landed, through the checker's own
`scan()`.

| | |
|---|---|
| product files | 1,216 |
| convicted | 496 hits in 230 files, 16 branches |
| the stopped rule, same corpus | 656 hits in 294 files, 17 branches |

| branch | files / hits |
|---|---|
| ai_mail | 22 / 71 |
| hooks | 27 / 68 |
| seedgo | 36 / 53 |
| api | 17 / 39 |
| devpulse | 10 / 37 |
| daemon | 10 / 30 |
| prax | 16 / 30 |
| aipass | 15 / 29 |
| memory | 16 / 26 |
| drone, trigger | 13 / 24, 11 / 24 |
| flow | 13 / 22 |
| spawn | 12 / 21 |
| commons | 7 / 12 |
| backup | 3 / 8 |
| skills | 2 / 2 |

**The 40-hit sample, re-run.** The sample was drawn from the stopped rule's hits (seed 20260925) and
hand-classified. The narrowed rule keeps 22 of the 40:

| class | in the sample | kept | dropped |
|---|---|---|---|
| TP | 12 | 8 | 4 |
| FP-SENTINEL | 13 | 5 | 8 |
| FP-BYDESIGN | 12 | 9 | 3 |
| FP-SHAPE | 3 | 0 | 3 |

Precision among kept rows is 8 of 22, about 36%, up from 12 of 39. The five sentinels that survive
are functions whose other failure paths also return the default outside a handler, such as an
exit code `1` returned by an `if`. A mechanical rule reads those as the success path.

**@backup's seven rows from the brief.**

- `drive/tracker.py` is convicted at 114, the `except OSError` row, where `return True` sits beside a success-path `return True`.
- `drive/client.py:128` is NOT convicted. `_api_call`'s success path returns a call, so its `None` is a sentinel by this rule. The conflation happens one function up, in `get_or_create_backup_folder`, and that function's own handler IS convicted at 184 (`return None` beside a success-path `return None`).
- `diff/generator.py:143` is NOT convicted. Its success path returns no string literal.
- `backup_timestamps.py` and `share.py:39-41` are assign-and-fall-through, which is not read.
- `drive_stats.py` and `trail.py` are not convicted either.

@backup is convicted at 8 lines in 3 files: `client.py` 112, 148, 184, 269 and 346, `share.py:81`,
and `tracker.py` 100 and 114.

## Scoring

Scored per file: 0 on any finding, else 100. Every hit goes on ONE check, as
`<file>:<line> except returns <default> - <why>; <cure>`.

## The cure

Re-raise, so the caller sees the failure. Or return a value the success path cannot return and
name it in the docstring: `None` from a function that otherwise returns a dict, or `-1` from one
that returns a count. The caller can then test for it. A log line beside the default is not a
cure, because the caller still reads an answer.

---

[← Back to README](../../../README.md)
