# Mock Console Standards
**Status:** v1
**Date:** 2026-09-22

---

## What It Is

Test template v1, **item 14** — the edge is real, not mocked.

The product's consoles write to `sys.stdout` and `sys.stderr` **at print time**, so
pytest's `capsys` captures every one of them, the cli header channel included. A test
asserts on `capsys`, by channel:

```python
def test_refusal_is_reported(capsys):
    run(["--bad"])
    assert "Refused" in capsys.readouterr().err
```

What a mock console costs:

```python
console.print.assert_called_with("[red]Refused")
```

That passes when the product hands Rich a string. It also passes when the string never
reaches a terminal, when the console was the wrong one, when the markup is malformed,
when stderr went to stdout. The assertion measures the **call**; what the user reads is
the **channel**. @prax's `test_display_resilience.py` carries the receipt in its own
header — the live monitor died on a line Rich could not render, and every mock-console
test in that branch stayed green.

---

## Check first: nothing is charged twice

| standard | scope | why it does not reach this |
|---|---|---|
| `cli` | `APPLIES_TO = "production"` | Rich console usage, no bare `print()` — never sees `tests/` |
| `output_routing` | `APPLIES_TO = "production"` | status output through @cli helpers, not raw `console.print` |
| `stderr_routing` | `APPLIES_TO = "production"` | which channel a product line takes |
| `no_oracle`, `unentered_assert` | v5 pack, **scores nothing** | assertion quality in general, and not gating |

Three standards own how production **builds** a console. None of them has ever looked at
what a test puts in its place. Item 14 had no checker at all.

---

## The rule is the install site, not the value's spelling

A Mock that sits in a test is a Mock. A Mock the test puts **where the product looks** is
an oracle. Same restriction `literal_path` took from `host_portability` ARM A — a thing
that merely sits somewhere is data, and only a thing handed to the product is in use.

Measured 2026-09-22 by this checker over the fleet's 580 test files:

| site | hits |
|---|---|
| `patch(f"{MOD}.console")` | 297 — 284 of them given no replacement at all |
| `setattr(mod, "console", Mock())` (2-arg and 3-arg) | 70 |
| `cli_mod.console = MagicMock()` | 30 |
| `patch.object(display, "CONSOLE", cons)` | 26 |
| `product_call(console=MagicMock())` — handed, not installed | 9 |

The patch **target** may be a product attribute (`{MOD}.console`), a product function
that returns one (@drone's `git_module._get_console`) or Rich's class itself (@prax's
`patch("rich.console.Console")`). All three end with the product holding a Mock, so all
three are one finding.

### What is installed

| stand-in | hits | what the message calls it |
|---|---|---|
| a Mock family call, or a bare `patch` | 415 | `a Mock` / `a patch with no replacement (the default MagicMock)` |
| `Console(file=buf)` | 16 | `a Rich Console on a buffer` |
| a test-local class with a `print` method | 1 | `a fake console class` |

The **third shape is convicted**, against the dispatch's default of two, because the
install site makes it unambiguous: a class defined in the test file, carrying a `print`,
put where the product looks for its console. It is item 14's oracle with a different
spelling. The one instance is seedgo's own `_Recorder`.

---

## Pinning a colour or a style without a mocked console

`capsys` reads plain text: the style is gone before the test sees it. The old habit pinned
it through a mock, `print.assert_called_with("[red]Errors: 15[/red]")`. Do not put a
console in the product's place for it, not a Mock and not a `Console(file=buf)`. Turn on
the **real console's own recording** and read the style back per character:

```python
from rich.color import Color
from rich.text import Text

def test_errors_line_is_red(capsys, monkeypatch):
    console = module.console                        # the product's own console object
    monkeypatch.setattr(console, "record", True)    # Rich's switch; restored after the test
    console.export_text(clear=True)
    module.print_summary(result)
    lines = [Text.from_ansi(l) for l in console.export_text(styles=True, clear=True).splitlines()]
    line = next(l for l in lines if l.plain == "  Errors: 15  Warnings: 3")
    start = line.plain.index("Errors: 15")
    colours = {line.get_style_at_offset(console, i).color.number for i in range(start, start + 10)}
    assert colours == {Color.parse("red").number}
```

The product still prints to its real channel, so `capsys` asserts the text in the same test.
Compare the colour **number** from `Color.parse`, never an ANSI string: Rich's highlighter
adds its own styles to numbers and quotes, and the ANSI form changes with them.
`Text.from_ansi` and `get_style_at_offset` are public Rich API and answer the same on every
platform. Measured on seedgo's `test_diagnostics_audit.py` (fleet green leg 5): a colour
mutant that keeps the glyph and changes the colour is killed on both the errors line and the
glyph.

---

## Never convicted, each for a measured reason

- **`capsys` and `capfd`.** 79 of the 580 files already read the channel. They are the
  fix, not the offence.
- **A console the PRODUCT builds.** This checker never reads `apps/`.
- **A restore** — `setattr(module, "console", original)`, where `original` came from
  `getattr(module, "console")`. 5 sites. Putting the real console back is the opposite of
  the habit.
- **A Mock for something that is not a console.** Console-named means **one qualifier at
  most** — `console`, `CONSOLE`, `err_console`, `Console`. A first cut that took any name
  ending in the word convicted @prax's helper `_print_event_to_console` twice, and mocking
  a helper is not item 14's offence.

---

## The renderer console is counted, not convicted — and this diverges from the brief

The dispatch names shape (b) as *"a Rich Console constructed in a test on a StringIO or
any file argument whose output the test then reads"*. Measured, that description covers
**two different things**:

| | files | what the test is doing |
|---|---|---|
| installed over the product | 6 | the product prints into a buffer, so the channel is empty |
| **the test prints to it itself** | 4 | the subject is what **Rich** does to a string |

The second group is not item 14's oracle: no product console is in the picture, and
`capsys` cannot capture an output the product never wrote. The receipt is @cli's
`conftest.make_capture_console`, whose own docstring says why it exists —

> force_terminal=False and color_system=None pin the two knobs FORCE_COLOR, NO_COLOR and
> TERM move. Callers still assert through strip_ansi()

— and `test_output_capture.py` proves the point by spawning real subprocesses, because
Rich resolves the colour system once per process. A buffered console with
`color_system=None` is precisely the environment-independence `capsys` cannot give.

So 8 consoles in 4 files (ai_mail `test_format`, seedgo `test_rich_markup`, seedgo
`test_bypass`, cli `conftest`) are **counted in the passing message and never charged** —
the device `named_encoding` uses for latin-1 and `literal_path` for drive-rooted paths.

```
The console the product prints to is the real one (2 renderer consoles are counted, which the rule allows)
```

**This is the one place the checker does not do what the dispatch's letter said**, and it
is flagged rather than quietly taken. Convicting the other four files would cost 81 → 85
and tell those authors to use `capsys` for output no product ever wrote.

---

## A name is resolved one hop, and through a helper's return

@prax binds `real_console = Console(file=buffer)` and installs the name. @devpulse's
`_real_console()` returns `(console, buffer)` and eight tests install the first element —
without following a same-file `return`, that file reads clean while eight tests run on a
substituted console.

A name assigned anything else anywhere in the file is **dropped**: which value reaches the
install is a question one pass cannot answer. `literal_path` and ARM A's `_proc_bindings`
are the precedent.

---

## Known limits

**A factory in another file is missed.** @cli's `conftest.make_capture_console` returns a
buffered console and two test files (`test_integration.py`, `test_display.py`) install it
over the product. One pass over one file cannot see into a helper it imported. Those two
are the whole of @cli's 0-of-12, and the only false negatives measured.

**`console.print = lambda ...` is not a rule of its own.** Patching the method rather than
the object is 47 hits in 5 files, and all 5 are already convicted for installing the
console that carries it. A second rule would charge one habit twice.

**Runtime.** Five passes over one materialised `ast.walk`: 6.0s over the fleet's 581
test files, against `literal_path`'s 5.2s and a bare `ast.parse`'s 2.4s. The first cut
walked the tree six separate times and measured 10.8s for the same 81 files and 432 hits.

**A file Python cannot parse yields no findings.** `ruff` already convicts the syntax
error, and an invented line number sends its author to the wrong place.

---

## Fleet standing on arrival

Measured 2026-09-22 by this checker, before the rule landed:

| | value |
|---|---|
| test files in the corpus | 580 |
| convicted | **81 (14%)** |
| hits | **432** |
| files already reading the channel with `capsys`/`capfd` | 79 |
| renderer consoles counted, not charged | 8 in 4 files |

| branch | convicted / test files | hits | capsys files |
|---|---|---|---|
| ai_mail | 6 / 49 | 53 | 0 |
| aipass | 13 / 30 | 135 | 3 |
| api | 10 / 50 | 106 | 5 |
| backup | 5 / 15 | 6 | 1 |
| canary | 0 / 9 | 0 | 6 |
| cli | 0 / 12 | 0 | 2 |
| commons | 3 / 23 | 9 | 0 |
| daemon | 2 / 21 | 7 | 5 |
| devpulse | 1 / 24 | 1 | 12 |
| drone | 3 / 33 | 11 | 5 |
| flow | 4 / 29 | 28 | 1 |
| hooks | 2 / 54 | 9 | 9 |
| memory | 4 / 46 | 8 | 11 |
| prax | 7 / 38 | 10 | 0 |
| seedgo | 12 / 70 | 23 | 11 |
| skills | 0 / 17 | 0 | 2 |
| spawn | 3 / 30 | 14 | 5 |
| trigger | 6 / 30 | 12 | 1 |

The worst single file is aipass `test_init_flow.py` at 53 hits; ai_mail
`test_email_module.py` is 46, and 42 of those also rebind `console.print` to a lambda.
@canary, @cli and @skills are clean, and @cli's zero is two parts habit and one part the
cross-file limit above.

Two branches were audited for real on the day it landed:

| branch | overall before | overall after | `mock_console` | files |
|---|---|---|---|---|
| memory | 94% | 94% | 90% | 4 of 46 |
| aipass | 94% | **93%** | 55% | 13 of 30 |
| seedgo | 94% | 94% | 82% | 12 of 70 |

Only aipass moves: 13 of its 30 test files carry the habit, and `test_init_flow.py`
alone holds 53 of the 135 hits.

---

## Provenance

`templates/test_template_v1.md` item 14, built 2026-09-22 on @devpulse's dispatch
b552d057 (DPLAN-0354). Eighth checker in the per-item series, after `router_assert`,
`oversize_test_file`, `import_site`, `through_the_command`, `named_encoding`,
`literal_path` and `file_top`. The model file `tests/test_readme_update.py` passes clean
and defines the shape.
