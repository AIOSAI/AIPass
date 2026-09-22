# Through The Command Standards
**Status:** v1
**Date:** 2026-09-21

---

## What It Is

Test template v1, **item 10**: a test reaches behaviour the way a user does — through the module's commands and its public functions. An underscore helper is never called directly by a test.

```python
from aipass.memory.apps.handlers.chroma import chroma_subprocess

def test_source_matches():
    assert chroma_subprocess._source_matches(source, "DPLAN-0012")   # convicted
```

Owner ruling, 2026-09-20 22:28: *through the command*.

---

## Why It Matters

A private helper is not a contract. It is the shape the author happened to cut the work into this week, and a test bolted to it pins that shape rather than the behaviour.

That cuts both ways, and both ways are bad:

- **Rename the helper** and a green suite goes red with nothing user-visible changed. The test costs maintenance it never earned.
- **Reroute the command past the helper** and the suite stays green while the product breaks. The test was never watching the thing the user touches.

A test that goes through the command has neither failure mode. It asks for what is promised, and it is right for exactly as long as the promise holds.

Measured 2026-09-21 across 591 fleet test files (`test_*.py` and `conftest.py` under each branch's `tests/`):

| | files | hits |
|---|---|---|
| any hit | 258 of 591 | — |
| shape a — private import | 148 | 1,114 |
| shape b — private reach | 151 | 1,336 |

---

## What the Checker Scans For

Two shapes, both convicted.

**a. An import of an underscore name from a product module, at any scope.**

```python
from aipass.seedgo.apps.handlers.audit.audit_display import _format_standard_name
```

**b. A call or attribute READ of an underscore name on a product base.**

The base is resolved from the file's own import bindings and nothing deeper:

| The file bound | A hit looks like |
|---|---|
| `import aipass.a.b as m` | `m._helper(...)`, `m._TABLE` |
| `from aipass.a import b` | `b._helper(...)` |
| `import aipass.a.b` | `aipass.a.b._helper(...)` |

A name this file never imported from the product is not the product.

---

## Never convicted

| Shape | Why |
|---|---|
| `__init__`, `__version__`, `__all__` | Dunders are language surface, not private helpers |
| An underscore helper the test file or its conftest defines | The test's own scaffolding — not the product. A module whose dotted path has a `tests` or `conftest` segment is not a product module |
| `result._x`, where `result` came back from a product call | Dataflow. The checker resolves a base to an import binding or it declines |
| `m._cache = {}` · `monkeypatch.setattr(m, "_cache", ...)` · `patch("aipass.x._helper")` | **Item 15**, mock only at the edge. A different rule with a different cure |

That last row is a deliberate boundary, not an oversight. The same fleet scan counted **152 direct writes** to a product private name and **2,113 patch-target strings** naming one. They are left to item 15, and this checker reports zero of them.

---

## How to fix a violation

Call the verb the user calls, and assert on what comes out.

```python
from aipass.memory.apps.handlers.chroma import chroma_subprocess

def test_a_plan_id_matches_its_own_file(capsys):
    chroma_subprocess.handle_command(["check-plan", "DPLAN-0012"])
    assert "DPLAN-0012" in capsys.readouterr().out
```

If the helper's logic cannot be reached through any command at all, **that is a question about the product** — you have found an unreachable branch, and a direct test would only make it look covered. Mail @devpulse with the helper's name.

---

## Scope, and why no score moves

`APPLIES_TO = "tests"`, so only the per-file checklist lane runs it — on the write that creates the shape. The audit's corpus is `apps/` (`_collect_py_files` never walks `tests/`), so no branch's number moves on the day this lands. The audit reports the standing backlog through `check_branch_info`, **unscored**:

```
through_the_command backlog: 291 private import(s) and 138 private helper reach(es)
across 32 test file(s) (unscored - convicted on the next write of the file)
```

Files are allowed to fail on arrival — the owner's ruling, 2026-09-20.

**Seedgo is under this rule like everyone else.** Item 3 grants this branch its own per-checker test layout, not a pass on item 10: the backlog quoted above is seedgo's own, 433 hits across 32 of its files, and the cure is the public entry — `scan`, `check_module`, `handle_command`.

---

## Known limit

```python
import aipass.x._private as m        # NOT convicted
```

The plain-import form of shape (a). Item 10 names the `from` form, and the checker implements what item 10 names. Measured rather than assumed: **0 of 591** fleet test files use it today. The day one does, this is the paragraph that changes.

---

## Provenance

`templates/test_template_v1.md` item 10, accepted by the owner 2026-09-20 (DPLAN-0354). Fourth checker in the per-item series, after `router_assert`, `oversize_test_file` and `import_site`, and built to the same two-lane shape.
