# Constant Predicate Standards
**Status:** v1
**Date:** 2026-09-22

---

## What It Is

Crack class **C** from the 2026-09-22 eyes-on review of @backup's tests. A `lambda` whose
body is a constant, handed to product code as an argument. It cannot discriminate a product
that honours the callable from one that ignores it entirely.

```python
mirror_tree(src, dst, should_ignore=lambda p: False)    # test_ignore_pathspec.py:491
```

`mirror.py:95` never calls `should_ignore`. The lambda answers `False` for every path, and a
product that dropped the parameter passes the same test.

---

## The split is the judgement

**SCORED — the body is a `bool`.** `lambda p: False` is a *predicate*, and a predicate that
returns the same answer for every input cannot discriminate. There is no input for which it
says anything, so no test using it can tell a product that consults it from one that does
not. **163 hits.**

**REPORTED — the body is anything else.** 309 hits, and **236 of those return `None`**:
`lambda *a: None` as an `on_progress` or a logger. That is an inert *callback*, not a
predicate, and a no-op stub for a callback that is not under test is a legitimate thing to
write. The other 73 return a value the product then uses — `0`, `'HEADER'`,
`'/usr/bin/python3'` — a stand-in answering a question, not a predicate refusing to.

`163 + 309 = 472`, which is the review's own first cut to the hit. We are measuring the same
population; this rule scores the third of it that cannot be right.

### Why `bool` is checked before `int`

In Python `isinstance(True, int)` is `True`. Reading a predicate as a numeric stand-in loses
the whole rule, so the `bool` branch comes first.

---

## Not restricted to test bodies

The one place this reads wider than the brief's wording. A constant predicate handed to the
product from a fixture or a module-level helper is the same defect reaching the same product
call, and the file it lives in is test code either way. Every hit is still inside a `tests/`
file.

---

## Fleet standing on arrival

Measured 2026-09-22 over 565 test files.

| | value |
|---|---|
| scored | **38 files, 163 hits** |
| reported | **309** (236 `None`) |
| runtime | **3.9s** |

Evidence lands: `test_ignore_pathspec.py:491`, `test_snapshot_fidelity.py` 89, 107, 124, 149.

---

## Why it cannot be satisfied by accident

A bool-constant lambda returns the same answer for every argument it is ever given. Delete
the product's call to it and nothing about the test changes. **There is no threshold and
nothing to tune.**

---

## Known limits

**A named function that returns a constant is invisible.** `def never(p): return False` is
the same defect one indirection away; only the `lambda` form is read.

**A lambda bound to a name and handed over later** is not judged — the argument position is
what makes it a predicate the product will consult.

**A file Python cannot parse yields no findings.** `ruff` already convicts the syntax error.

---

## Provenance

Crack class C of the owner's 2026-09-22 ruling, built on @devpulse's dispatch f66ac9d0
(DPLAN-0354). The brief is `dropbox/test_review_cracks_brief_2026-09-22.md`.
