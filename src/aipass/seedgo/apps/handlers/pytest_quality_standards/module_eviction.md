# module_eviction — did the test put the import cache back?

> A test may evict a cached module to force a fresh import. It may not walk away
> leaving the cache holding a different object from the one it found. This rule is
> about the **restore**, never about the eviction.

**Scope:** `branch_level` · **Severity:** advisory · **Species:** `SYS_MODULES_EVICTION`,
`PACKAGE_ATTRIBUTE_EVICTION`

---

## Why this rule exists

CI on PR #769 flickered red on one memory test, on some platforms and Pythons only:

```
tests/test_contracts.py::TestUnknownArgumentExitsNonZero::
    test_a_known_verb_given_a_bogus_subargument_exits_non_zero      assert 0 == 2
```

The contract test was right. The cause was a **helper** in another file,
`tests/test_rollover.py`:

```python
def _import_rollover(monkeypatch):
    mocks = _prepare_rollover_mocks(monkeypatch)        # the cli is a MagicMock now
    sys.modules.pop("aipass.memory.apps.modules.rollover", None)
    parent = sys.modules.get("aipass.memory.apps.modules")
    if parent is not None and hasattr(parent, "rollover"):
        delattr(parent, "rollover")
    from aipass.memory.apps.modules import rollover     # re-executed against the mock
    return rollover, mocks
```

Teardown put the cli back. Nothing put the **module** back. The re-import minted a
rollover bound to a mock `error()`, and it stayed in `sys.modules` and on its parent
package after the test ended. The next in-process `memory.main()` on the same xdist
worker found that module, routed `rollover <bogus>` through the mock error, and exited
0. Which worker inherited it depended on loadscope's ordering, so the red came and
went. A flicker, and the flicker was a leak.

The cure on disk records first, then evicts:

```python
monkeypatch.setitem(sys.modules, _ROLLOVER_MODULE, None)
del sys.modules[_ROLLOVER_MODULE]
parent = importlib.import_module("aipass.memory.apps.modules")
monkeypatch.setattr(parent, "rollover", None, raising=False)
delattr(parent, "rollover")
```

monkeypatch saw what stood there before the eviction — the real module, or nothing —
and teardown puts exactly that back.

## Why a rule, and not a `host_state` species

`host_state` has the same ruling (touching is allowed, leaving it changed is the
defect), but it judges test units and fixtures. The incident's site was neither: it
was a module-level helper. That is where the shape lives across the fleet. Teaching
`host_state` to read helpers would change what all six of its species read, and its
denominator with them. A separate rule reads every function, scores against every
function, and leaves `host_state` measuring exactly what it was measured to measure.

## What is read

Every function defined in a test file, each on its own scope: test functions,
fixtures, and helpers at module, class or nested level. A nested def is its own
subject, reported once under `outer::inner`. No call is followed and no other file is
opened.

## The two species

**`SYS_MODULES_EVICTION`** — the cache entry:

```python
sys.modules.pop(NAME, None)                                   # flagged
del sys.modules[name]                                         # flagged
```

**`PACKAGE_ATTRIBUTE_EVICTION`** — the module's second home, the parent package's
attribute, which `from package import name` reads:

```python
parent = sys.modules.get("pkg.modules")
delattr(parent, "rollover")                                   # flagged
```

`delattr(M, "attr")` counts only when `M` is **provably a module**: a name bound in the
same function from `importlib.import_module(...)`, `__import__(...)`,
`sys.modules[...]` or `sys.modules.get(...)`, a name bound by an `import` statement at
module level or in the function, or one of those expressions written in place.

`sys.modules.get` is on that list because of the half-cure. memory's intake helper
moved its `sys.modules` evictions onto `monkeypatch.delitem` and kept a bare
`delattr(parent, "pool_processor")` on a `parent` read with `.get`. That is the other
half of the same leak.

`monkeypatch.delitem(sys.modules, ...)` and `monkeypatch.delattr(...)` are never
evictions here. They are the cure.

## What is never flagged

**Monkeypatch recorded it first.** `setitem`/`delitem` on `sys.modules` with the same
key expression, or `setattr`/`delattr` with the same object and attribute, *earlier*
in the same function. Earlier is the whole point: a record made after the eviction
saw the eviction, and teardown faithfully restores the hole.

**`patch.dict(sys.modules ...)`** — as a `with` around the eviction, or as a
decorator on the function, spelled `patch.dict`, `mock.patch.dict` or
`unittest.mock.patch.dict`, over `sys.modules` or `"sys.modules"`. It snapshots the
dict and restores it on exit. **It acquits cache evictions only.** It never touches a
package attribute, so a `delattr` inside the block is still read — backup's own
conftest says so in as many words.

**An explicit restore** after the eviction, or in any `finally` of the same function:
`sys.modules[K] = ...` or `sys.modules.update(...)` for the cache,
`setattr(M, "attr", ...)` or `M.attr = ...` for the attribute. A restore in a `finally`
covers every eviction of that key in the function, which is how drone's registry test
(pop, try, restore-or-pop in the finally) reads correctly.

**A re-import is not a restore.** `importlib.import_module(K)` after the eviction
mints a new module object and caches *that* — the pollution, not the cure.

**A fixture with any statement after its last yield.** The teardown is where a fixture
puts things back, and pytest runs it for a failing test too. This is `host_state`'s
convention, adopted after demanding `try`/`finally` convicted thirty correct fixtures.
A fixture that `return`s — memory's `verbs` — has no teardown at all.

**An autouse fixture in the same file that records the key.** `setitem`/`delitem` on
`sys.modules` inside an `autouse=True` fixture runs around every test in the file, so
the key it records is put back after each of them, whatever a helper did to it in
between. Both sides must resolve to the same literal name — a string, a module-level
string constant, or a `for` over a literal list or a module-level literal tuple — one
hop, same file. Cache evictions only.

This one was added because the fleet run demanded it. memory's
`test_symbolic_extras.py` records five symbolic modules in its autouse
`_mock_handler_deps` and pops the same five bare in five `_import_*` helpers. A
runtime probe found every one of those module objects unchanged after teardown. Five
rows, zero leaks — so the reading was wrong, and it was cured.

## How to fix a flag

Record, then evict:

```python
monkeypatch.delitem(sys.modules, NAME, raising=False)
monkeypatch.delattr(parent, "leaf", raising=False)
```

or, when the eviction has to stay a bare `del`:

```python
monkeypatch.setitem(sys.modules, NAME, None)
del sys.modules[NAME]
```

A fixture that evicts should put back what it took after its `yield`, or do the
eviction through `monkeypatch` so there is nothing to put back by hand.

## What this rule deliberately does not claim

Every limit runs toward **fewer** flags.

- **It does not follow calls.** A restore performed by a helper the function calls, a
  fixture it requests, or a caller's `patch.dict` is invisible — and so is an eviction
  performed by one.
- **`conftest.py` is not a test file and is not read.** An autouse conftest fixture
  that records the same key really does restore it, and this rule cannot see that.
  That is the one false positive the sample below still holds.
- **`delattr` on a name that is not provably a module is not read.** A
  `from x import y` name may be a function; so may a parameter. A name bound to a
  module and rebound to anything else in the same function is not provably a module.
- **Code in a string is not code.** A harness script handed to a child interpreter
  evicts modules in a process that dies with it.
- **Module-level statements outside any function are not read.**
- **`sys.modules.clear()`, `popitem()`, `del M.attr` and a manually started
  `patch.dict(...).start()`** are not read as evictions or as restores.
- **`sys.modules.update(...)` acquits every cache eviction in its function** without
  comparing keys. Generous on purpose.
- **A flagged site may be harmless** — a module with no state, re-imported to an
  identical copy. The identity still changed. It nominates. A human decides.

## What it measured

Over the 18 citizens on 2026-09-15: **61 rows** — @prax 30, @memory 29, @backup 2,
every other branch 0. Six of memory's 29 sit in `tests/parked/`, files named
`test_*(disabled).py` that pytest never collects; the pack's corpus reads every
`test_*.py`, so they are reported like any other file. Before the autouse acquittal
the same corpus produced 66.

Sites acquitted fleet-wide, by reason: `patch.dict` 39 (prax 36, backup 3), fixture
teardown 7, same-file autouse record 5, recorded first 2 (memory's cure), explicit
restore 2 (drone).

Against memory's incident files: `tests/test_rollover.py`'s cured `_import_rollover`
(lines 181–188) produces **no row**. `tests/test_config_verbs.py::verbs` is flagged at
**lines 128 and 153**. And `tests/test_rollover.py` still carries **one** row, line 243
in `test_reimport_survives_a_cold_submodule_cache`: a bare pop of three cli submodules
before the helper re-imports them. That one is real. A probe that compared module
identity before and after the test found all three cli submodules replaced after
teardown, because the helper's `monkeypatch.setitem` then recorded the fresh copies.

**Precision, measured rather than argued.** 27 collected rows across @prax, @backup and
@memory were read by hand, and for each one a pytest plugin snapshotted every
`aipass.*` module object before the test and compared it after full teardown, conftest
included:

| Verdict | Rows |
|---|---|
| Leak proven — the module object was replaced or removed after teardown | 23 |
| Shape correct, not observable in that run (module not yet imported) | 3 |
| **False positive** — restored by an autouse **conftest** fixture | 1 (`prax tests/test_jsonl_writer.py::_get_append_jsonl`) |

## Scoring

Functions that leave the cache as they found it, over **every function the rule
reads** — tests, fixtures and helpers — one row per function however many lines it
evicts, with every line named in the row. Counting units alone would let a file of
flagged helpers drive a project below zero.

**Advisory**: it reports a number and never fails a board.

A project with no test files reports `not_applicable` rather than zero. A project whose
test files are present but unparseable says so, and is never reported as a project
without tests.

*Incident: PR #769 CI flicker, memory `tests/test_rollover.py` `_import_rollover`*
