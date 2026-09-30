# No Product Call Standards
**Status:** v1
**Date:** 2026-09-22

---

## What It Is

Crack class **A** from the 2026-09-22 eyes-on review of @backup's tests. A `def test_*`
that never reaches the product: it runs, it asserts, it is green — and no edit anywhere in
`aipass/` can make it red.

The reviewers called these **LIBRARY** tests, because what they usually pin is a third
party. `pathspec` matching a glob. `StringIO` returning what was written to it. `capsys`
capturing a `print`.

285 backup tests, 178 sound, 107 carrying a finding — and **every one of the 107 passes all
ten template checkers**. Those ten measure shape. This one measures whether the test is
pointed at anything.

---

## The rule

A test is convicted when **nothing in its reachable text names the product**.

**Reachable** is the test's own body, its decorators, every same-file helper it calls, and
every fixture it requests.

**Naming the product** is any of:

| form | spelling | why it is needed |
|---|---|---|
| an import binding | `from aipass.backup... import is_ignored` | the obvious half |
| a module-level constant, to a fixed point | `SIMPLE_MODULES = [snapshot, versioned]` | how a parametrized test reaches `mod.handle_command` with the import three screens up |
| a dotted string | `"aipass.backup.apps..."` | `import_module` and `mock.patch` take the product by name, not by binding |
| a multi-line string mentioning `aipass` | a probe source | product code, written down, handed to a subprocess |
| a path from `__file__` | `Path(__file__).parents[1] / "apps"` | it points into the repo tree; a test that reads the guard file's text is testing the guard |

---

## Two acquittals that are not about the product at all

**The file's own apparatus.** A call to a function defined in this file, or to a fixture
defined in the branch conftest, acquits outright. A negative control that feeds a synthetic
source to the file's own detector is a **meta-test**, not a library test, and @backup has
nine of them:

```python
def test_negative_control_a_docstring_mention_is_not_a_call(self) -> None:
    """Prose naming inspect.stack() must not convict."""
    source = '"""Uses sys._getframe rather than inspect.stack() -- see defect."""\n'
    assert _inspect_stack_calls(source) == []
```

The class the review found is *"this test is pointed at nothing."* A control for the
file's own apparatus **is** pointed at something.

**A class whose own body reaches.** A `unittest.TestCase` method reaches the product
through `self.conn`, which `setUp` built and the test body never mentions. The class is the
apparatus there, exactly as the module is for a pytest fixture.

---

## Four cuts, and the number moved by 70x

| cut | what the rule was | files | hits |
|---|---|---|---|
| 1 | a call site whose name comes from an `aipass.*` import | **295** | **5,807** |
| 2 | + same-file helpers, fixtures, `import_module`, subprocess | 213 | 2,849 |
| 3 | + module-level constants, `__file__` paths, the own-apparatus acquittal | 45 | 169 |
| 4 | + the class acquittal | **23** | **82** |

Parametrize argvalues, a probe source handed to a subprocess, a dotted module path built in
an f-string, and a `setUp` that builds the world are four different ways to reach the
product without a call site a checker can see. **Every acquittal above is one of them,
found by reading what an earlier cut convicted** — not by tuning toward a number.

---

## Against the reviewers' ground truth

The nine reports name **12 LIBRARY rows** in @backup. This checker convicts **all 12 and
misses none**:

| file | lines |
|---|---|
| `test_ignore_pathspec.py` | 46, 53, 59, 70, 77, 88, 99, 106, 117, 124 |
| `test_cli_routing.py` | 581, 587 |

It convicts **two more** there — `test_ignore_pathspec.py` **135** and **142** — which the
reviewers marked DUPLICATE. Both build a `pathspec.PathSpec` themselves with no backup
symbol on the path, so this is a **second true reading of the same two rows**, not a false
one. `duplicate_test` charges them as well; the two standards disagree about which defect
is worse, not about whether there is one.

**Eight of the nine reviewed files pass clean.**

### Where it and the reviewers part, said plainly

`test_cli_routing.py:510` is marked OUT-OF-PLACE with the reason *"asserts only on a
literal this file defines; no product edit can fail it"* — which is this rule written as
prose. The checker **acquits** it, because its class `TestHelpNeverExecutes` names the
product elsewhere in its body. The class acquittal is generous on purpose: it costs this
one true row and buys back 38 false ones in @commons alone.

---

## Fleet standing on arrival

Measured 2026-09-22 over 559 test files (`tests/**/test_*.py` plus `conftest.py`, retired
and `(disabled)` excluded).

| | value |
|---|---|
| convicted | **23 (4%)** |
| hits | **82** |
| runtime | **7.9s** |

| branch | files | worst file |
|---|---|---|
| prax | 5 | |
| commons | 3 | `test_commons.py` **29** |
| memory | 3 | `test_contracts.py` 4 |
| backup | 2 | `test_ignore_pathspec.py` 12 |
| cli | 2 | `test_output_capture.py` 6 |
| flow | 1 | `test_import_dead_cwd.py` 6 |

@commons' `test_commons.py` is the whole shape in one file: 29 `unittest` methods that
execute raw SQL against a sqlite connection and read the row back. `setUp` calls a
same-file `_fast_db` helper that copies a template database; no commons code is on the path
at any point. They test SQLite.

---

## Known limits

**One pass reads one file plus its conftest.** A test whose only product contact is a
helper in a *sibling* test file is convicted unless that name also exists here or in the
conftest.

**The class acquittal is coarse.** One product name anywhere in a `TestCase` body clears
every method on it. That is the trade above, and `test_cli_routing.py:510` is its price.

**A file Python cannot parse yields no findings.** `ruff` already convicts the syntax error.

---

## Provenance

Crack class A of the owner's 2026-09-22 ruling on the eyes-on review of @backup's tests,
built on @devpulse's dispatch a3ad380b (DPLAN-0354). The brief is
`dropbox/test_review_cracks_brief_2026-09-22.md`; the nine reviewer reports are in
`dropbox/test_review_reports_2026-09-22/`. The model file
`tests/test_readme_update.py` passes clean.
