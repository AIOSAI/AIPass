# Weak Oracle Standards
**Status:** v1
**Date:** 2026-09-22

---

## What It Is

Crack class **D** from the 2026-09-22 eyes-on review of @backup's tests, and the largest
verdict class the reviewers found: **51 WEAK rows out of 285 tests**.

A test whose **entire oracle** cannot exclude the failure its name claims to exclude.

---

## Scored only when it is the whole oracle

A test that asserts the effect *and* also checks `isinstance` is a good test with a
redundant line. Charging it would be charging the thoroughness.

Every form below is judged against the test's complete set of assertions — `assert`
statements plus `mock.assert_*` calls — and one **strong** assertion anywhere in the test
acquits all of them.

---

## The six scored forms

| | form | why it cannot fail |
|---|---|---|
| **D1** | `assert <constant>` | `assert True` cannot fail |
| **D2** | `assert <name>` alone | a bare local's truthiness |
| **D3** | `is not None` alone | every object is not None |
| **D4** | `isinstance(...)` alone | the type, never the value |
| **D5** | `assert_called` / `assert_called_once`, no args | the call happened; nothing it was given |
| **D6** | `assert f(...) is None`, `f` annotated `-> None` | the function cannot return anything else |

### D2 is a bare **name**, never a call

```python
assert is_ignored("app.log", spec)      # strong — the claim IS the question
assert result                           # D2   — a local's truthiness
assert isinstance(result, Path)         # D4   — the exception: answers about the TYPE
```

A predicate CALL's truthiness is the claim: it asks the product a specific question and
asserts its answer. Scoring it cost **1,356 false hits** in the first cut and failed the
model file, whose second assertion is
`assert hasattr(generator, "update_readme_auto_sections")`.

### D6 is the rarest form that exists at all — **two** in the fleet

```python
assert trail.log_operation("x", {}) is None     # log_operation is -> None
```

The resolver reads `from mod import f` **and** module aliases, because the real instance is
`trail.log_operation(...)` where `trail` is a submodule. Handling only the direct import
found zero.

---

## Reported with a count, never scored

`is None` alone (not a `-> None` function) · `len` and `count` compares · `>= <= > <`
bounds · `in` and `not in` · `== {}` on a loader.

Each of these can legitimately be the right oracle and a rule cannot tell which, so the
number rides in the **passing** message and nobody is charged for it:

> Every test here asserts something that can fail (11 soft oracles in 1 form are counted,
> which the rule allows)

---

## A soft companion does not acquit; only a strong one does

This is the one place the rule bites harder than it reads, so it is named here.

```python
breach = check_ceiling(_files(tmp_path, [f"t/{i}.o" for i in range(6)]), {"max_backup_files": 5})
assert breach is not None                 # D3
text = "\n".join(breach.detail_lines())
assert "max_backup_files" in text         # soft
assert ".backupignore" in text            # soft
```

Scored **D3**: nothing in it pins a value the product computed. `test_ceiling_guard.py` 153
and 162 are exactly that shape. The dispatch asked for this directly with
`test_module_isolation.py:48`, whose companion is a `not in sys.modules`.

---

## `pytest.raises` acquits outright

"It raised the right exception" is a real oracle, and it is often the only one a refusal
test needs.

---

## Not charged twice

`router_assert` already owns `assert handle_command(...) is True`. That form is a `Compare`
against a constant, which this rule reads as strong, so the two never meet.

---

## Fleet standing on arrival

Measured 2026-09-22 over 561 test files.

| | value |
|---|---|
| convicted | **177 (32%)** |
| hits | **468** |
| runtime | **8.3s** |

| form | hits |
|---|---|
| D5 `assert_called`, no args | 162 |
| D3 `is not None` alone | 143 |
| D2 bare name truthiness | 113 |
| D4 `isinstance` alone | 48 |
| D6 `-> None` tautology | 2 |
| D1 `assert True` | **0** |

There is not one `assert True` in the fleet.

| branch | files |
|---|---|
| memory | 20 |
| trigger | 18 |
| ai_mail | 17 |

Worst single file: @prax's `test_log_watcher.py` at 25.

**Reported, not scored:** 430 files, 4,667 soft oracles — `in`/`not in` 3,346, plain
`is None` 632, `len`/`count` 428, `== {}` 132, bound compares 129.

---

## Why it cannot be satisfied by accident

Every scored form is true of a value the product never computed. `assert True` holds with
the product deleted; `is not None` holds for every object that exists; `isinstance` holds
for a stub of the right class; `assert_called` holds however wrong the arguments were; and
a `-> None` function cannot return anything but None. **There is no threshold and nothing
to tune.**

---

## What it declines, and why

| evidence line | verdict | reason |
|---|---|---|
| `test_cli_routing.py:328` | **convicted D5** | `spy.assert_called()`, 11 params unpinned |
| `test_error_resilience.py:372` | **convicted D6** | `-> None` tautology, 1 of only 2 in the fleet |
| `test_module_isolation.py:48` | **convicted D3** | companion is a `not in`, which is soft |
| `test_ceiling_guard.py:107` | **declined** | see below |
| `test_handlers_filesystem.py` 119, 136, 192, 205, 212 | **declined** | the dispatch said so in advance |

**`test_ceiling_guard.py:107`** is plain `is None`, and `check_ceiling` returns a breach
**or** None. Asserting None is a real claim about a real return. The reviewer's own mutant
for it (`continue`→`break` survives because the ghost is last) is a coverage gap, not a
tautology. Its count rides in the passing message.

**119, 136, 192, 205, 212** each have a live oracle beside the type check.
`test_build_snapshot_path` at 207 is **not** one of them and **is** convicted D4 — its
companion is `"snapshots" in str(result)`, a substring — where `test_backup_root` one test
above asserts `result.name == ".backup"` and is acquitted. Two tests, four lines apart, and
the rule separates them.

---

## The E-vs-D judgement call the dispatch asked for

**An assertion on a value the test itself set up does not count as a real oracle** — that
is class E's shape, and the answer is no, it is not an oracle.

But **this checker does not detect it.** That is class E's whole job, and building half of
E inside D would put one finding in two places under two names. D reads a self-set assert
as strong and leaves it to E. **If E never ships, that is a known hole, and this is where
it is written down.**

---

## Known limits

**Class E is out**, as above.

**An indirect assertion helper is invisible.** A test that calls
`assert_report_is_sound(result)` has no `assert` of its own; the rule sees no oracle at all
and skips it rather than guessing.

**A `-> None` function in another branch is not resolved.** Only imports this file names.

**A file Python cannot parse yields no findings.** `ruff` already convicts the syntax error.

---

## Provenance

Crack class D of the owner's 2026-09-22 ruling on the eyes-on review of @backup's tests,
built on @devpulse's dispatch eb5602d0 (DPLAN-0354), restricted to the forms that cannot be
right. The brief is `dropbox/test_review_cracks_brief_2026-09-22.md`; the nine reviewer
reports are in `dropbox/test_review_reports_2026-09-22/`. The model file
`tests/test_readme_update.py` passes clean.
