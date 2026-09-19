[← Back to the cli README](../README.md)

# Rich markup — what eats placeholders, and how to print literal brackets

Everything printed through this branch's console goes through Rich's markup
parser. A square-bracketed token is a style tag, and a token Rich does not
recognise as a style is still consumed as one: it disappears from the output
without an error, a warning, or a non-zero exit. A help page that documents
`drone @git log [count] [path]` therefore ships a line that tells the reader
nothing about its own arguments.

Measured through a capture console, one string, five spellings:

| spelling | what reaches the terminal |
|----------|---------------------------|
| `console.print("... log [count] [path]")` | `... log` — both tokens eaten |
| `console.print("...", markup=False)` | `... log [count] [path]` — literal, but no styling anywhere on the line |
| `console.print(escape("... log [count] [path]"))` | `... log [count] [path]` — literal, styling still available |
| `console.print("... log \\[count]")` | `... log [count]` — this is what `escape()` emits |
| `console.print("[green]...[/green] [count]")` | `...` styled, `[count]` eaten |

## The rule

**Escape the data; do not disarm the line.** Reach for
`rich.markup.escape()` on the token that must survive, not for `markup=False` on
the statement that prints it.

- `escape()` is per-value and composes: the rest of the line keeps its colours,
  and a styled label beside a literal placeholder both come out right. It is the
  correct spelling for any help page, table cell or message that interpolates a
  value the author does not control.
- `markup=False` is per-call and absolute: it turns the parser off for the whole
  string, so every style tag on that line becomes literal text too. It is the
  right answer in exactly one case — a block of pre-formatted text that carries
  no styling at all and is printed verbatim, which is why it fixed `drone`'s
  returned help literal. Used on a styled line, it does not just fail to help;
  it prints the tags.
- A hand-written `\[` is what `escape()` produces. For a runtime value it is the
  wrong spelling, because it cannot be applied to a value the author never sees.
- **The one exception, found by @seedgo:** a *styled literal that also carries a
  literal bracket* — `"[dim]  console.print('\\[bold]Hello\\[/bold]')[/dim]"`. The
  data and the styling live in the same string, so `escape()` on it eats the
  styling too, and `markup=False` prints the style tags. Neither tool can tell the
  two apart. Escape that one bracket by hand; it is the only spelling that renders
  both. This branch's own `--help` page carried exactly this shape and printed
  `console.print('Hello')` until 2026-09-17.

The rule in one line: **escape the data, do not disarm the line — and where the
data and the styling share one literal, escape the bracket by hand.**

## What this branch provides

```python
from aipass.cli import escape            # or aipass.cli.apps.modules
success(f"Updated {escape(path)}")
```

`escape` is Rich's own function, bound on this surface and not wrapped, so a
branch never has to import Rich to print safely.

The render surface is **split**, and `escape()` is only right for half of it.
Measured through a capture console with the value `log [count]`:

| function (argument) | raw value | `escape(value)` |
|---------------------|-----------|-----------------|
| `header` (title, detail values) | `log` — eaten | `log [count]` |
| `success` (message, kwarg values) | `log` — eaten | `log [count]` |
| `section` (title) | `log` — eaten | `log [count]` |
| `operation_start`, `operation_complete` (all values) | `log` — eaten | `log [count]` |
| `error` (message, suggestion) | `log [count]` | `log \[count]` — backslash shows |
| `warning` (message, details) | `log [count]` | `log \[count]` — backslash shows |
| `fatal` (message, suggestion) | `log [count]` | `log \[count]` — backslash shows |

`error`, `warning` and `fatal` build Rich `Text` objects, which never parse
markup, so they print any value literally. Escape for the first four rows; never
for the last three. Both halves are pinned in `tests/test_display.py`
(`TestEscapeExport`), so this table fails a test before it goes stale.

## The checker

seedgo's `Rich_Markup` checker used to read only the print site, so a help page
assembled as a returned literal and printed by a caller elsewhere scored 100
while its placeholders were eaten. It now follows a literal one hop to the call
that consumes it (seedgo f23fab69). It deliberately does not flag a hand-escape,
because of the styled-literal exception above.

---
[← Back to the cli README](../README.md)
