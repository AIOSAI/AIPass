# State Leak Standards
**Status:** v1
**Date:** 2026-09-22

---

## What It Is

Test template v1, **item 18** — no test leaks state into the next. Every patch through
`monkeypatch`, every file under `tmp_path`, nothing left in `sys.modules`.

This is the only item in the series whose violation **does not fail the file that commits
it**. A leaking test makes an unrelated test lie, in a file its author never opened, and
alphabetical order decides whether anybody ever sees it.

seedgo carried exactly one for months, as todo 139. Twenty-five test files here share a
fixture that stubs `sys.modules["...handlers.bypass"]` with a `MagicMock` and re-imports a
checker against it. `monkeypatch` restores the `sys.modules` **entry** — but it cannot undo
a name another module already bound, and `trigger_check.py:31` does
`from ...bypass.utils import matching_rule` at import time. `test_bypass.py` then ran on
`mock.utils.matching_rule()`. It was green because `test_bypass` sorts before
`test_checkers_batch9`. Reverse the order and it failed.

Two further mechanisms came out of curing it, and both are why the rule is shaped as it is:

- **Importing a submodule sets it as an ATTRIBUTE on its parent package**, and
  `from pkg import sub` reads that attribute **before** it consults `sys.modules`. Popping
  `sys.modules` alone does not evict a poisoned module — it comes straight back through the
  package, still holding its mock.
- **`monkeypatch.delitem(sys.modules, name, raising=False)` records nothing when the key is
  absent** — the cold-run case. It is a restore that restores nothing. 104 sites in 68
  fleet files use that exact spelling.

---

## Check first: nothing is charged twice

| standard | scope | why it does not reach this |
|---|---|---|
| `import_site` (item 8) | `APPLIES_TO = "tests"` | **the sys.modules stub-and-reimport of an aipass module.** Its ground, already landed |
| `literal_path` (item 22) | `APPLIES_TO = "tests"` | a path written as a literal, not state left behind |
| `mock_console` (item 14) | `APPLIES_TO = "tests"` | what a test puts where the product looks for its console |
| `trinity`, `hardcoded_path` | `APPLIES_TO = "production"` | never see `tests/` |

Item 18 had no checker at all. Nine `tests`-bucket standards now, this one ninth.

### The one conflict in the brief, stated rather than papered over

The dispatch says both *"The sys.modules stub-and-reimport of an aipass module is item 8's,
import_site, already landed: do not charge it twice"* and *"The checker must convict that
exact leak"* — where "that exact leak" **is** a sys.modules stub-and-reimport of an aipass
module. Both cannot hold.

`import_site` already convicts `tests/test_checkers_batch9.py` at lines **43, 48 and 51** —
the leak lines themselves. So `state_leak` does **not** convict that file, by the brief's
own no-double-charge rule, and the rule that would have convicted it is the one shape this
checker deliberately declines.

The leak was cured anyway, in the same dispatch — see below.

---

## The rule

A write to shared state, **at test time**, with nothing to put it back. Three shapes,
measured 2026-09-22 over the fleet's 582 test files:

| shape | hits | spelling |
|---|---|---|
| (a) a product module's attribute | **145** | `log_watcher.WATCHDOG_AVAILABLE = False` |
| (a) the same through `setattr` | **108** | `setattr(mod, "_queue", None)` |
| (a) `sys.modules.pop()` | **75** | |
| (a) a write to `sys.modules` | 6 | a key that is **not** an aipass module |
| (a) `os.environ.pop()` | 5 | |
| (a) a write to `os.environ` | 3 | |
| (c) `os.chdir` with no restore | 1 | |
| (b) a patcher started, never stopped | **0** | fires on input; no fleet instance |

**Shape (b) ships with zero fleet instances.** All 28 `.start()` calls in the corpus are on
threads, observers and monitors (`t.start()`, `thread.start()`, `observer.start()`), not on
patchers. The shape is implemented, unit-tested both ways, and convicts nothing today. It
is kept because the habit it names is cheap to acquire and invisible once acquired.

### Depth ONE, and that restriction is the rule

`mod.FLAG = False` rebinds the module's own name and the next test reads it.
`mod.helper.return_value = x` configures an object the module holds — ordinarily a Mock,
and nobody's shared state. Only depth one is convicted. That single restriction drops **45
nominations** from @prax and @trigger, and without it the message reads
`a write to the product's mod.return_value`, which is not even the right address.

---

## Never convicted, each for a measured reason

| acquittal | count | why |
|---|---|---|
| every `monkeypatch` verb | **4,890** | setattr 3,321 · setitem 608 · setenv 415 · chdir 257 · delenv 178 · delitem 104 · delattr 5 · undo 2 |
| `with patch(...)` | **7,222** | restores on exit |
| `@patch` decorators | **2,078** | same |
| `try`/`finally` in the same function | 141 | item 18 done by hand, and it works |
| a restoring fixture in scope | — | see below |
| a `sys.modules` stub naming an aipass module | — | `import_site` owns it |
| a write to a local, a Mock, a `tmp_path` file | — | not shared state |

**A verb credits its own family and no other.** `monkeypatch.setenv` says nothing about
`sys.path`, and a function that uses one while writing the other is still convicted for the
other. `_MONKEYPATCH_COVERS` is that map.

**A fixture is matched by REQUEST, not by presence.** `autouse=True` covers the file;
anything else covers only the tests that name it in their signature. @ai_mail's `clean_env`
pops fourteen keys, yields, and puts them back — the tests that ask for it are acquitted and
the tests in the same file that do not ask are not. That distinction is the difference
between 39 honest acquittals and a rule that trusts a fixture nobody invoked.

**And a restoring fixture is credited for its own body.** Without that, the one function in
the file doing item 18's job by hand gets convicted for the `os.environ.update(saved)` that
**is** the restore. It cost 4 hits and one whole file when it was found.

**A fixture with no teardown credits nothing** — no `yield`, no `finally`, so it never runs
after the test. Its own setup write is convicted too: a setup-only autouse fixture leaks
into the next file all by itself.

---

## The import-time write is counted, not convicted

A module-level `os.environ[k] = v` happens **once, before any test**, and every test in the
file sees the same thing. Item 18 is about one test leaking into the **next**, so it is
counted in the passing message and never charged — the device `named_encoding` uses for
latin-1, `literal_path` for drive-rooted paths and `mock_console` for renderer consoles.

```
Every change this file makes is put back (1 import-time write is counted, which the rule allows)
```

**22 sites in 20 files.**

---

## Todo 139, cured in the same dispatch

The checker was proven on its first real catch by curing the leak it declines to charge.
The fix is **central**, in `tests/conftest.py`, not per-file — bisection showed the pair
`test_checkers_batch9.py` + `test_checkers_batch7.py` broke the reverse run, and 25 files
share the fixture shape.

An autouse teardown fixture evicts any checker module left holding a `MagicMock`, sweeping
**both** `sys.modules` **and** `vars(package)` — because a module popped from `sys.modules`
comes back through its parent package's attribute, which is what four earlier attempts
missed. The fifth found it by probing: `sys.modules["...trigger_check"]` was absent while
`aipass_standards.trigger_check` still held the poisoned module.

| | before | after |
|---|---|---|
| forward run | 4756 passed | 4756 passed |
| **reverse run** | **2 failed** | **4756 passed** |

### A second, opposite instance — reported, not fixed

`tests/test_handler_import.py` fails **5 of 6 in isolation** and passes in the suite. It
**depends** on another file having imported `bypass.utils` first. Verified pre-existing by
disabling the new fixture. It is the mirror image of the same disease — a test that reads
state it did not set — and this checker does not convict it, because nothing in that file
writes anything. Item 18's rule cannot see a test that only reads.

---

## Known limits

**A fixture in the file's `conftest.py` is invisible.** One pass reads one file, so a
restoring fixture next door cannot be credited. Nothing in the fleet currently relies on one
for these families; a future one would be a false positive, and an obvious one.

**A helper that writes on the test's behalf is missed.** Same one-file boundary as
`mock_console`'s cross-file console factory.

**Runtime.** 8.5s over the corpus against a bare `ast.parse`'s 2.4s. The first cut measured
**19.3s**, 14.1s of which was `_functions` doing a fresh `ast.walk` per function — every
node re-walked once for each function above it. One descent that carries the enclosing
function down and collects each function's nodes on the way, plus one materialised
`list(ast.walk(tree))` shared by the three tree passes, took it to 8.5s with identical
findings.

**A file Python cannot parse yields no findings.** `ruff` already convicts the syntax error.

---

## Fleet standing on arrival

Measured 2026-09-22 by this checker, before the rule landed:

| | value |
|---|---|
| test files in the corpus | 582 |
| convicted | **49 (8%)** |
| hits | **343** |
| import-time writes counted, not charged | 22 in 20 files |

| branch | convicted / test files | hits |
|---|---|---|
| ai_mail | 1 / 49 | 3 |
| aipass | 0 / 30 | 0 |
| api | 1 / 50 | 2 |
| backup | 5 / 15 | 6 |
| canary | 0 / 9 | 0 |
| cli | 1 / 12 | 3 |
| commons | 0 / 23 | 0 |
| daemon | 0 / 21 | 0 |
| devpulse | 0 / 24 | 0 |
| drone | 3 / 33 | 3 |
| flow | 1 / 29 | 5 |
| hooks | 4 / 54 | 14 |
| memory | 8 / 46 | 14 |
| prax | **21 / 38** | **177** |
| seedgo | 1 / 72 | 1 |
| skills | 0 / 17 | 0 |
| spawn | 0 / 30 | 0 |
| trigger | 3 / 30 | **115** |

Two branches carry 85% of the hits and they carry them for the same reason: @prax and
@trigger both test log watchers, and a log watcher is a module full of flags
(`WATCHDOG_AVAILABLE`, `_observer`, `_queue`) that a test flips and never flips back.
`trigger/test_log_watcher.py` alone is 92 hits; `prax/test_logging_handlers.py` is 41,
`prax/test_monitor_module.py` 34, `prax/test_watcher.py` and `prax/test_instance_lock.py`
20 each. Nine branches are clean.

Two branches were audited for real on the day it landed:

| branch | overall before | overall after | `state_leak` | files |
|---|---|---|---|---|
| memory | 94% | 94% | 83% | 8 of 46 |
| aipass | 93% | 93% | 100% | 0 of 30 |

---

## Provenance

`templates/test_template_v1.md` item 18, built 2026-09-22 on @devpulse's dispatch
56121e07 (DPLAN-0354). Ninth checker in the per-item series, after `router_assert`,
`oversize_test_file`, `import_site`, `through_the_command`, `named_encoding`,
`literal_path`, `file_top` and `mock_console`. The model file
`tests/test_readme_update.py` passes clean and defines the shape; three mutations of that
real file — a product-attribute write, an unstopped patcher, and the same write through
`monkeypatch.setattr` — are what pin convict, convict, acquit.
