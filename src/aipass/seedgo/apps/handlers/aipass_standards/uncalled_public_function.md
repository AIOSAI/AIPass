# Uncalled Public Function Standards
**Status:** v1
**Date:** 2026-09-22

---

## What It Is

Crack class **O** from the 2026-09-22 eyes-on review of @backup's tests. A public function
of a test file's **declared subject** module — the path in its one-line docstring, test
template v1 item 6 — that no test in the branch ever calls.

The file says in its own docstring that it tests that module. One of the module's public
functions is not tested by anything.

---

## The crisp part is what counts as called

**Called** — named in a `Call`, or an attribute access that is then called.
`share_mod.run_share(file_arg)` is a call.

**O1 replaced** — named *only* as a `patch` / `monkeypatch.setattr` target, replaced and
never run:

```python
patch.object(entry, "discover_modules", return_value=[fake_module])   # ×4 in one file
```

`apps/backup.py:125 discover_modules` is exactly this. Nothing anywhere runs the real
importlib discovery.

**Reached through the product** — the false conviction to avoid, and the dispatch asked how
the rule decides it. A **name-level call graph** over the branch's whole `apps/`, seeded
with every function name the tests *do* call, closed to a fixed point. If the function is in
that closure, some test already drives a real path into it and the rule acquits.

That guard is not decoration: it acquits **18 of the 20** candidates, including
`route_command` and every `print_introspection`, which `main()` reaches for tests that call
`main()`.

A name-level graph collapses two modules that both define `run`, so it **over-acquits**
rather than under-acquits. For a scored rule that is the right direction, and the number it
acquits rides in the passing message rather than being hidden.

---

## Read the docstring properly

```python
"""Tests for apps/modules/share.py and apps/handlers/drive/share.py."""
```

Two subjects. `findall`, not `search` — taking only the first match mis-attributes the
second module's functions to nobody.

---

## Fleet standing on arrival

Measured 2026-09-22. **2 files, 2 hits, 9.7s.**

| file | function | shape |
|---|---|---|
| `backup/apps/backup.py:125` | `discover_modules` | O1 replaced |
| `backup/apps/handlers/report/result.py:50` | `new_result` | O2 never named |

`new_result` is defined once and referenced nowhere in `apps/` or `tests/`.

**Only 69 of the fleet's 561 test files declare a subject path at all.** That is the
headline and it caps the rule: O cannot judge a file that never says what it tests.
`file_top`'s item 6 sub-rule convicts the other 492, and every file it cures hands this rule
a new subject to read.

Of the 20 uncalled public functions in those 69 files' subjects: 18 reachable through the
product, 1 O1, 1 O2.

---

## Where it disagrees with the review, with the line number

**`apps/modules/share.py run_share`** is given as the evidence line — "replaced at
`test_share.py` 100, 112, 122 and never runs anywhere in the suite."

**It runs.** `test_caller_path.py:86` calls `share_mod.run_share(file_arg)` for real, with
Drive mocked beneath it. The brief's own wording is "no test anywhere in the branch's
`tests/` calls", so this rule **acquits** it and is right to. The three `test_share.py`
monkeypatches are real, and `discarded_patch` already examined them and found them sound —
they are recorders that are asserted — but they are not the whole suite's relationship to
that function.

**`apps/handlers/diff/generator.py generate_diff_content`** is offered conditionally, "if
`generator.py` is within the subject of a backup test file". It is not.
`test_versioned_engine.py` declares `apps/handlers/copy/versioned.py` and
`apps/modules/restore.py`, and no @backup test file names `generator.py`. The rule does not
see it — correct, and also a hole: a module nothing declares as a subject is invisible to O
no matter how untested it is.

**`apps/modules/restore.py`'s bare-basename fallback** is a coverage gap inside a function,
not a function. O does not see it and should not, exactly as the dispatch said.

---

## Why it cannot be satisfied by accident

If a public function of a module a test file claims as its subject is never called, never
reachable from anything called, and named only where it is being replaced, then nothing in
the suite has ever run it. **There is no threshold and nothing to tune.**

---

## Known limits

**No subject line, no verdict.** 492 of 561 test files are invisible to this rule today.

**Module-level defs only.** A public method on a class is not judged; the subject of the
rule is the module's exported surface.

**A name-level graph over-acquits**, by design, as above.

**An indirect call is invisible.** `getattr(mod, name)()` or a dispatch table keyed by
string names the function nowhere the AST can see.

---

## Provenance

Crack class O of the owner's 2026-09-22 ruling on the eyes-on review of @backup's tests,
built on @devpulse's dispatch cb55cc37 (DPLAN-0354). The brief is
`dropbox/test_review_cracks_brief_2026-09-22.md`.
