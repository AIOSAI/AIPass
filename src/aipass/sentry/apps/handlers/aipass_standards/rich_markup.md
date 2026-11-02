# Rich Markup Standard

## Purpose

**Escape the data; do not disarm the line.**

Everything printed through a Rich console goes through Rich's markup parser. A
square-bracketed token is a style tag, and a token Rich does not recognise as a
style is still consumed as one: it disappears from the output without an error,
a warning, or a non-zero exit. A help page that documents
`drone @git log [count] [path]` therefore ships a line that tells the reader
nothing about its own arguments.

The source string is correct, so a source-reading audit passes at 100 while the
user reads mutilated output. That is what makes this class survive: it is
invisible on both sides.

The adopted rule lives at `src/aipass/cli/docs/rich_markup.md`. This page is
what the checker enforces of it.

## The three spellings, ranked

| spelling | what reaches the terminal | verdict |
|----------|---------------------------|---------|
| `console.print("log [count] [path]")` | `log` — both tokens eaten | **flagged** |
| `console.print(escape("log [count]"))` | `log [count]`, styling still available | the rule |
| `console.print(block, markup=False)` | literal, **and no styling anywhere on the line** | right for one case |
| `console.print("[green]ok[/green]", markup=False)` | `[green]ok[/green]` — the tags, as text | **flagged** |
| `console.print("log \[count]")` | `log [count]` | works; not what the standard asks you to type |

- `escape()` is per-value and **composes**: the rest of the line keeps its
  colours, and a styled label beside a literal placeholder both come out right.
  It is the only spelling that can be applied to a value that arrives at
  runtime.
- `markup=False` is per-call and **absolute**. It is correct in exactly one
  case: a block of pre-formatted text carrying no styling, printed verbatim.
  Used on a styled line it does not merely fail to help — it prints the tags.
- A typed `\[` is what `escape()` emits. It works while the parser is on, so it
  is not flagged. It is not credited either: the violation message prescribes
  `escape()`, and under `markup=False` the backslash itself reaches the
  terminal, which **is** reported.

## The oracle

The checker never guesses which brackets Rich will eat. It asks Rich:

1. `rich.markup.RE_TAGS` — the exact regex Rich uses to find tags. This is what
   makes `[1,2,3]`, `[42, 78]`, `L[42]`, `[]` and `[ spaced ]` mechanically
   safe rather than special-cased.
2. `rich.style.Style.parse()` on the style string Rich itself would build
   (`rich.markup.Tag` partitions on `=`). Parses → a real style, the author
   meant it. Raises `StyleSyntaxError` → literal text, silently eaten.

Closing tags are excluded: a mismatched `[/usr/bin]` raises `MarkupError`, which
is loud and already caught by tests. This standard is only about silent losses.

## Following a literal to its print site — one hop, one file

v1 read the **print site** only. drone's per-verb git help page scored 100 while
eating its own placeholders, because the page is a literal *returned* by
`get_help()` and printed by `print_help()`: the print site carried no literal to
read at all. Measured 2026-09-15 on `drone/apps/modules/git_module.py` with the
`markup=False` cure removed — the file exactly as it stood when the defect was
found — v1 reported **0** tokens. The same file carries **29**.

Two shapes are followed, both inside one file and both one hop:

```python
HELP_TEXT = "compass add ... --rating R [opts]"   # module constant
console.print(HELP_TEXT)

def get_help():                                   # local return
    return "git log [count] [path]"
console.print(get_help())
```

Concatenation (`+`) is read through at both levels, because a help page is
usually a run of adjacent literals with one call spliced into it. A token is
reported on the line it **sits** on; the message also names the line that
prints it, and either line can carry a bypass.

## What this rule deliberately does not claim

Every limit runs toward **fewer** flags. Each one is priced against the fleet
corpus of 2026-09-15 — 5,570 positional arguments at Rich print sites across 18
branches, of which 264 (4.7%) stay unreadable.

- **It does not cross the file boundary.** A literal assembled in module A and
  printed in module B is invisible. Following imports needs a whole-branch call
  graph, and its resolution guesses — re-exports, adapters, `getattr` dispatch —
  are exactly where false positives breed. Priced: a deliberately over-generous
  probe that resolved *every* non-local call at a print site by name across the
  whole fleet found **0** tokens that would be eaten. The arm would cost more
  than it is worth today.
- **It does not chain hops.** A followed function that returns another local
  call — `return HEAD + _door_help() + TAIL` — has `HEAD` and `TAIL` read and
  `_door_help()` left alone.
- **It does not read flow.** A local variable, an `append` loop, `"".join(...)`,
  `%` formatting, a dict or list of literals indexed at the print site: none are
  followed. Each needs intra-procedural analysis to say *which* literal arrives.
  Priced: 4 print sites fleet-wide take a local name whose assignment is
  literal-reachable, and **0** of them carry a token that would be eaten.
- **A name bound twice is not followed.** If a module-level constant or function
  name is rebound anywhere in the file — reassigned in a branch, rebound under
  `global`, shadowed by an import — the binding at the print site is not
  provable, and the name is dropped.
- **A non-constant `markup=` is not read.** `markup=flag` leaves the call alone
  in both directions: whether the parser runs is unknown.
- **A Rich renderable is not opened.** `console.print(Panel("..."))` passes a
  constructor argument, not a print argument. Priced: 58 such sites fleet-wide
  (`Panel`, `Panel.fit`, `Columns`, `Markdown`, `Text.from_ansi`), **0** carrying a
  token that would be eaten.
- **A hand-escape at a normal print site is not flagged.** `\[count]` really
  does reach the terminal intact, and a styled literal help page that must also
  show a literal placeholder has no other spelling — `escape()` over the whole
  page would eat the styling with it. A scored, gating standard does not fail
  working code over a source-spelling preference. The demotion is in the
  guidance, not in the score.
- **The `markup=False` family cannot read intent.** A pre-formatted block that
  quotes a real style tag — documentation *about* `[dim]`, say — is reported,
  because nothing in the source tells it apart from a line the author styled.
  It nominates. A human decides.

## What it measured

Over the 18 citizens on 2026-09-15, across 868 production files: **one** new
finding, and it is real. Branch scores are the mean of the per-file scores, the
way `branch_audit` aggregates them.

| branch | files | files red before | files red after | score before | score after |
|--------|------:|-----------------:|----------------:|-------------:|------------:|
| devpulse | 25 | 0 | 1 | 100.0 | 96.0 |
| every other branch | 843 | 0 | 0 | 100.0 | 100.0 |

`devpulse/apps/modules/compass.py:66` — `[opts]` in `HELP_TEXT`, printed at line
164 by `console.print(HELP_TEXT)`. Rendered through a capture console the usage
line arrives as `compass add "context" "decision" --rating R    Store a rated
decision`: the notation is gone. Not cured here — it is not this pack's file.

No finding v1 reported is dropped by v2.

## How to fix a flag

1. Escape the **value**: `console.print(f"[green]ok[/green] {escape(v)}")`. The
   rest of the line keeps its colours. This is the answer for any help page,
   table cell or message that interpolates a value you do not control, and the
   only one available to a value that arrives at runtime.
2. A block of pre-formatted text carrying **no** styling, printed verbatim:
   `console.print(block, markup=False)`. Nothing else.
3. Do not reach for `markup=False` on a styled line. It prints the tags.
4. Re-run the audit, then **look** at the rendered output to confirm.

## Acceptance criterion for tests

Assertions must be made against **rendered output** read back out of a real
`Console` buffer — not a `MagicMock`, and not a real `Console` whose output is
never read. This defect lives only at render time: a mock records the call
arguments, which are correct, and that is the entire problem.

```python
buffer = io.StringIO()
Console(file=buffer, force_terminal=False).print(text)
assert "[args...]" in buffer.getvalue()
```

## Scope and scoring

- `AUDIT_SCOPE = all_files` — any `.py` file can print.
- `APPLIES_TO = production` — a test file renders nothing a user reads, and
  tests legitimately build broken markup as fixtures; this standard's own suite
  does exactly that.
- One check per file: pass (0 lost tokens) or fail (any, either family).
  Score 100 or 0. Line-level bypass filtering is supported.
