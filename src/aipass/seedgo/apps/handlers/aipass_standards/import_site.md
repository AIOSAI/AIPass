# Import Site Standards
**Status:** v1
**Date:** 2026-09-21

---

## What It Is

Test template v1, **item 8**: product imports at the top of the test file, never inside a test.

```python
def test_list_plans_prints_the_table():
    with patch(f"{_MOD}.console") as mock_console:
        from aipass.flow.apps.modules.list_plans import list_plans   # convicted
        list_plans()
```

The import runs *after* the patch. Whatever `list_plans` closes over is whatever the test decided it should close over.

---

## Why It Matters

This is not tidiness, and it is not a style preference.

An import that happens inside a test happens after the test has had its chance to replace what it is about to import. That is the entire mechanism by which a green test can be measuring a stub instead of the product — and the fleet has the receipts. The readme tests this branch retired on 2026-09-20 were the worked example: **source-edit mutants survived them**, because the module under test was rebuilt from a stub inside the test body, so deleting a real `return` changed nothing anyone asserted on.

Measured 2026-09-21 across 590 fleet test files (`test_*.py` and `conftest.py` under each branch's `tests/`):

| | files | hits |
|---|---|---|
| any hit | 369 of 590 | — |
| shape a — deferred product import | 351 | 5,175 |
| shape b — `sys.modules` stub / in-function reload | 132 | 921 |

---

## What the Checker Scans For

Two shapes, both convicted.

**a. A product import inside a function, method or class body.**

| Element | Convicted |
|---|---|
| `import aipass...` inside a `def`, `async def` or `class` body | yes |
| `from aipass... import ...` inside the same | yes |
| Nested one level deeper (inside a `with`, `try`, `if` *within* a function) | yes |
| Any import at module level | **no** |
| A stdlib or third-party import inside a function | **no** |

**b. A `sys.modules` write, or an in-function `importlib` reload, naming an `aipass` module.**

| Mechanism | Fleet count |
|---|---|
| `monkeypatch.setitem(sys.modules, ...)` | 590 |
| `importlib.import_module(...)` | 108 |
| `sys.modules.pop(...)` | 71 |
| `patch.dict(sys.modules, ...)` | 65 |
| `monkeypatch.delitem(sys.modules, ...)` | 63 |
| `importlib.reload(...)` | 12 |
| `sys.modules[key] = ...` | 11 |
| `del sys.modules[key]` | 1 |

A `sys.modules` write counts wherever it sits — at module level it poisons every test in the file rather than one. An `importlib` reload counts only inside a function body: at module level it runs before any test could have staged a replacement for it to pick up.

---

## Module level is never convicted

```python
try:
    from aipass.memory.apps.handlers.monitor.registry_scope import fleet_branches
except Exception:                      # only where @memory is absent
    fleet_branches = None
```

Fine. Nothing at module level can be preceded by a test's own patching, so `try`/`except ImportError` and `if TYPE_CHECKING` guards are both untouched.

Six of the 5,175 shape-a hits sit inside a `try`/`except` **within a function** — an optional-branch probe (`api/tests/conftest.py`, `daemon/tests/conftest.py`, `seedgo/tests/test_json_handler_contract.py`). Those are convicted, because a guard inside a function is still inside a function. They are the one category argued as possibly legitimate, and they are reported to the owner rather than silently exempted.

---

## How to fix a violation

**Shape a — move the import to the top of the file.**

```python
from aipass.flow.apps.modules import list_plans as list_plans_mod   # top of file

def test_list_plans_prints_the_table(monkeypatch, capsys):
    monkeypatch.setattr(list_plans_mod, "load_registry", lambda: ROWS)
    list_plans_mod.list_plans()
    assert "FPLAN-0001" in capsys.readouterr().out
```

**Shape b — import the real module at the top and patch at the edge.**

`monkeypatch.setattr` on the seam the module reads, not `monkeypatch.setitem` on `sys.modules`. The unit stays real; only the thing it talks to is swapped, and the swap is visible in the test rather than buried in an import order.

---

## Scope, and how it scores

`APPLIES_TO = "tests"`, and since **2026-09-21** (owner ruling 21:20) the audit's corpus includes `tests/`, so every `test_*.py` and `conftest.py` is measured and **this standard is a scored row that moves the branch number**. @memory scored 4% on it the day the corpus changed.

It also convicts in the per-file checklist lane, on the write that creates the shape.

The unscored `check_branch_info` backlog line retired with that ruling — it existed because the corpus handed this checker no files. Files are allowed to fail on arrival, the owner's ruling of 2026-09-20, and now they fail in the score rather than in a grey line under it.

---

## Known limit

The `aipass` module has to be named in the statement itself:

```python
key = "aipass.prax"
sys.modules[key] = stub        # NOT convicted
```

The checker reads one statement, not the function's dataflow. No fleet test file does this today. Reaching it would mean convicting every `sys.modules` write, product or not — which would convict a test stubbing a third-party module it has every right to stub.

---

## Provenance

`templates/test_template_v1.md` item 8, accepted by the owner 2026-09-20 (DPLAN-0354). Third checker in the per-item series, after `router_assert` and `oversize_test_file`, and built to the same two-lane shape.
