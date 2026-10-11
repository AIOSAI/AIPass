# Conftest Fixtures Standards
**Status:** v1
**Date:** 2026-09-22

---

## What It Is

Test template v1, **item 20** — a branch's `tests/conftest.py` pins the console width once,
session scope, on every console the product exports, and resets the command state after
every test.

Rich sizes an unpinned console **on every print**: 80 on POSIX and 79 on Windows under
pytest's capture, the terminal's width under `-s`, `COLUMNS` when exported. The template
measured 4 of the trial's 31 tests flipping at width 40, none with the pin. A suite that is
green on one developer's terminal and red in CI, for no reason anybody can see, is what this
prevents.

`error()` marks the process failed. C2 is item 18 wearing a conftest's clothes: that flag
belongs to one test and must not reach the next.

---

## The unit is the conftest, not the test file

Every other file under `tests/` passes silently and says so. These two fixtures belong in
exactly one place — item 16, *shared fixtures live in `conftest.py`, never copied per file*
— so a rule that read them anywhere else would convict 563 files for not being the conftest.

The checker also **never convicts a branch for a missing conftest**. It cannot see a file
that is not there. Measured: **0 of 18 branches lack one**, so there is nothing it would have
to say today.

---

## Check first: nothing is charged twice

| standard | scope | why it does not reach this |
|---|---|---|
| `state_leak` (item 18) | `tests` | a write left behind. C2's *absence* is not a write |
| `mock_console` (item 14) | `tests` | a console stand-in installed over the product |
| `cli`, `output_routing` | `production` | how production **builds** a console |
| `import_site`, `file_top` | `tests` | conftest's imports and its header — and both already convict seedgo's own conftest, which is not this item |

Item 20 had no checker at all. Ten `tests`-bucket standards now.

---

## The two sub-rules, both on ONE check

`checklist._format_failure()` prints the first failed check and appends "(+N more)". Two
checks would show C1 and hide C2 behind a count, so both ride on one.

### C1 — a session-scope autouse fixture pins `.width`

```python
@pytest.fixture(autouse=True, scope="session")
def pinned_console_width() -> None:
    for console in (display.CONSOLE, display.err_console):
        console.width = 200
```

Three things have to hold, and each is its own test: **autouse**, **session scope**, and a
`.width` assignment whose base is a console the **product** exports.

### C2 — an autouse fixture resets after the test

```python
@pytest.fixture(autouse=True)
def clean_command_state() -> Generator[None, None, None]:
    yield
    display.reset_command_state()
```

**Order is the whole point.** A reset *before* the yield clears the flag the **previous**
test set and then hands this test's flag straight on. The rule requires the call to sit at a
line after the yield.

---

## The pin has to land on the product's consoles

A `Console(width=200)` the fixture builds itself is a console the product never prints to. It
pins nothing, and C1 is not satisfied. The name has to come from an `aipass.cli` import —
`display.CONSOLE`, `display.err_console`, or the `console` / `err_console` those modules
export — or be the loop variable of a `for` over them, which is the template's own spelling.

Same install-site restriction `mock_console` took from `host_portability` ARM A: a thing that
merely **sits** somewhere is data; only a thing reaching the product is in use.

A loop is checked element by element. `for console in (display.CONSOLE, Console()):` does not
satisfy C1 — one product console in a tuple cannot launder a locally built one.

**C2 is deliberately looser.** `reset_command_state` is one unambiguous name in the fleet, and
a conftest that calls it without importing `display` raises `NameError` on the first test
rather than leaking anything. The checker does not police an import the interpreter polices
harder.

---

## Check first: all 18 branch conftests, measured 2026-09-22

| branch | C1 pin | C2 reset | shared-console imports | verdict |
|---|---|---|---|---|
| ai_mail | — | — | 16 | **0** |
| aipass | — | — | 17 | **0** |
| api | — | — | 12 | **0** |
| backup | — | — | 14 | **0** |
| canary | — | — | 6 | **0** |
| cli | *(helper only)* | — | 3 | **0** |
| commons | — | ✓ | 45 | **0** (C1) |
| daemon | — | — | 14 | **0** |
| devpulse | — | — | 9 | **0** |
| drone | — | — | 29 | **0** |
| flow | — | — | 9 | **0** |
| hooks | — | — | 24 | **0** |
| memory | — | — | 21 | **0** |
| prax | — | — | 13 | **0** |
| **seedgo** | **✓** | **✓** | 22 | **100** |
| skills | — | — | 7 | **0** |
| spawn | — | — | 11 | **0** |
| trigger | — | — | 20 | **0** |

**1 of 18 pins width. 2 of 18 reset command state. 17 of 18 convicted.**

@cli's conftest is the one that looks like a pin and is not: it carries
`Console(width=..., force_terminal=...)` inside `make_capture_console`, a **helper the test
prints to**, not a pin on the product's consoles. Its docstring says why it exists — to
defeat the colour env vars `capsys` cannot control — and that purpose is real. It is simply
not item 20.

### Every branch has a console, and it is the same one

**292 import sites** across the 18 branches pull `console` / `err_console` from
`aipass.cli.apps.modules`. In `display.py`, `console = CONSOLE` — the same object. C1 works
fleet-wide because it mutates the shared Console **instance**; which name a branch reaches it
through is irrelevant to the pin.

No branch's product is without a console. The lowest is @canary at 6 sites.

---

## The one open template question for the owner

48 other `Console()` builds exist in the fleet's live `apps/` trees. **47 of them sit inside a
`try`/`except ImportError` fallback** that fires only when `aipass.cli` cannot be imported —
never in the suite. @commons has 22 of those, @drone 12, @trigger 8.

The 48th is real, and it is **seedgo's own**:

```
apps/handlers/diagnostics/diagnostics_check.py:33   console = Console()
```

A module-level console that C1's two names do not reach. The template's C1 cannot pin it.

Whether C1 should name **every module-level console a branch builds**, rather than the two the
page names, is a question about the template — not a conviction to soften. The checker asks
for exactly what the page asks for, and this paragraph is the flag.

(@ai_mail has four more `Console()` builds under `if __name__ == "__main__"` demo blocks in
`central_writer.py`, `inbox_cleanup.py`, `create.py` and `delivery.py`. They are CLI entry
scaffolding, never imported by the product path, and are not the same question.)

---

## Known limits

**A fixture in a parent conftest is invisible.** One pass reads one file. A branch with
`tests/unit/conftest.py` inheriting the pin from `tests/conftest.py` is judged on each file
separately — and since only the branch conftest is ever convicted, the nested one passes as
"not the branch conftest". No fleet branch does this today.

**A fixture imported from elsewhere is missed.** `from .fixtures import pinned_console_width`
would satisfy pytest and not this rule. Same one-file boundary as `mock_console`'s cross-file
console factory. Zero fleet instances.

**Runtime.** 0.9s over the corpus against a bare `ast.parse`'s 2.4s — it is *faster than
parsing everything* because 563 of the 582 files never get parsed at all: the filename check
returns first.

**A file Python cannot parse yields no verdict.** `ruff` already convicts the syntax error.

---

## Provenance

`templates/test_template_v1.md` item 20 and its `conftest.py` section (C1, C2), built
2026-09-22 on @devpulse's dispatch faced7be (DPLAN-0354). Tenth checker in the per-item
series, after `router_assert`, `oversize_test_file`, `import_site`, `through_the_command`,
`named_encoding`, `literal_path`, `file_top`, `mock_console` and `state_leak`. The model is
seedgo's own `tests/conftest.py`, the fleet's only passing one; three mutations of that real
file — the width fixture gutted, the reset gutted, and the pin moved onto a locally built
`Console(width=200)` — are what pin C1, C2 and the install-site restriction.
