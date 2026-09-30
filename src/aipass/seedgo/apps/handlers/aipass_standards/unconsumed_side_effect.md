# Unconsumed Side Effect Standards
**Status:** v1
**Date:** 2026-09-23

---

## What It Is

Crack class **F**. A test queues several answers for a mock and never checks that they were
all taken.

```python
drive_api.side_effect = [
    {"files": []},
    {"id": "new_folder_456"},
    {"id": "new_folder_456", "name": "AIPass Backups"},   # is this one ever reached?
]
```

A `side_effect` list of three says the product will call this mock three times. Nothing in
the test says so. If the product calls it twice, the third answer is never consumed, the test
still passes, and whatever branch that answer was written to feed is unpinned — deletable,
with the suite green.

---

## The cure is one line

```python
assert drive_api.call_count == 3
drive_api.assert_has_calls([...])     # when the arguments matter
```

Either one turns the list's length from a hope into a claim.

---

## What acquits, what is scored, what is counted

| verdict | shape | fleet |
|---|---|---|
| acquitted | the test asserts the mock's calls — `call_count`, `assert_called*`, `assert_has_calls`, `mock_calls`, `call_args`, `assert_not_called`, the `await_` forms | 9 |
| scored | the mock is never mentioned in any assertion in the test | 17 |
| counted | the mock is asserted some OTHER way — its return value reaches an assert — so the test is watching it, just not counting it | 0 |

The counted bucket is empty in this fleet today. It is here because the shape is legitimate
and the count should be ready when it appears.

A list of ONE is never judged: a single queued answer is a return value spelled differently,
and there is no unconsumed tail to lose.

---

## Check first

Measured 2026-09-23 over the fleet's 572 test files.

| | |
|---|---|
| files | 5 |
| scored | 17 |
| counted | 0 |
| acquitted | 9 |

Lengths among the judged: 2 eleven times, 3 five times, 4 once.

---

## Why it cannot be satisfied by accident

The list's length is an assertion the test declines to make. The fix is additive — one more
assert — and no threshold exists to tune.

## Scoring

Scored, per file. Every hit names the line, the mock and how many answers it was queued, on
ONE check.

## The cure

`assert mock.call_count`, or `assert_has_calls` when the arguments matter.

---

[← Back to README](../../../README.md)
