# Sleep In Test Standards
**Status:** v1
**Date:** 2026-09-22

---

## What It Is

Crack class **N**, and test template v1 item 23. A `sleep` inside a test. It is always one of
two mistakes, and both are curable without waiting.

---

## A sleep to move an mtime

On a filesystem with one-second timestamp granularity a `0.01s` nudge does not move the mtime
at all, so the test goes red for a reason that has nothing to do with the product. On a
coarse or loaded host a `1.1s` sleep is simply 1.1s of the suite's life, repeated.

```python
time.sleep(1.1)                         # hope the mtime moved
os.utime(path, (when, when))            # set it, exactly, instantly, everywhere
```

## A sleep to wait for something

A fixed sleep is a bet that the machine is fast enough today. Flaky on a loaded CI box, slow
on a fast one. A deadline poll on the **real** condition — read the flag, join the thread
with a timeout — is both faster and honest about what it is waiting for.

---

## Match through the alias, not through `time.sleep`

The whole implementation lesson. The rule is "a call whose tail name is `sleep`", because the
fleet spells the module four different ways:

| spelling | hits | where |
|---|---|---|
| `time.sleep` | 35 | most of the fleet |
| `_time.sleep` | 5 | @prax `test_watcher.py` |
| `time_module.sleep` | 2 | @hooks `test_engine.py` |
| `time_mod.sleep` | 1 | @ai_mail `test_dispatch_monitor.py` |

Matching `time.sleep` and a bare `sleep` found 14 files / 35 hits and **silently missed
eight**. Matching the call's tail name found all of them — and lands on the review's first
cut of 17 / 43 exactly.

---

## Fleet standing on arrival

Measured 2026-09-22 over 565 test files. **17 files, 43 hits, 4.0s.**

Every hit is scored. The dispatch's ruling is "score all", and there is no legitimate form:
both shapes above have a cure that is strictly better.

Evidence lands: `test_versioned_engine.py` 89, 110, 126, 240, 315, 441 — @backup's
baseline/diff suite, which is exactly the mtime shape.

---

## Why it cannot be satisfied by accident

A sleep asserts nothing. It can only make the suite slower, or make it pass on one machine
and fail on another. **There is no threshold and nothing to tune.**

---

## Known limits

**`asyncio.sleep` is caught by the same tail-name rule** — its cure is different (an event,
not `os.utime`) but the finding is the same.

**A sleep behind an indirection is invisible.** `_settle()` that sleeps inside is not read;
only the call site named `sleep` is.

**A file Python cannot parse yields no findings.** `ruff` already convicts the syntax error.

---

## Provenance

Crack class N of the owner's 2026-09-22 ruling, built on @devpulse's dispatch f66ac9d0
(DPLAN-0354). The brief is `dropbox/test_review_cracks_brief_2026-09-22.md`.
