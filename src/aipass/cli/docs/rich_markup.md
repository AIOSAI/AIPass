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
- A hand-written `\[` is what `escape()` produces, and it works. It is still the
  wrong source spelling: it survives only as long as nobody reformats the line,
  and it cannot be applied to a value that arrives at runtime.

So the fleet should not be reaching for `markup=False` by default, and should
not be escaping bracketed tokens by hand. It should be escaping values.

## What this branch should provide

Branches currently have to `from rich.markup import escape` to do the right
thing, which means reaching around the render surface they were given — and a
branch that must import Rich directly to print safely will sometimes not
bother. The surface should offer the escape itself, so that the safe spelling is
also the local one. Not built yet; recorded here as the shape of the fix.

## The blind spot in the checker

seedgo's `Rich_Markup` checker reads the print site. A help page assembled as a
returned string literal and printed by a caller elsewhere scores 100 while
carrying tokens that will be eaten, which is why several branches passed the
check and still lost their placeholders. Following a literal to the console call
that consumes it — or flagging bracketed placeholder tokens in any string that
reaches a `console.print` — is what would catch this class.

---
[← Back to the cli README](../README.md)
