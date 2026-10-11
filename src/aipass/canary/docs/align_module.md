[<- Back to the README](../README.md)

# The align module

A column aligner: `align table.txt` prints a ragged text table with its columns
lined up. `apps/modules/align.py` routes and prints; `apps/handlers/table/aligner.py`
reads the file, lays the rows out, and owns every refusal.

It exists as a test subject, not as a feature. Built to a dispatched contract
(@devpulse, 2026-09-20) whose interesting half is not the padding but what the
contract did not say: what separates two fields when the file was written with
tabs, what "width" means when a character is two terminal cells wide, and which
of two applicable refusals speaks when a row is wrong in more than one way.

## The file

Plain UTF-8 text. Every non-blank line is two or more fields.

- **Fields are separated by a run of spaces or tabs.** The contract says "one
  or more spaces"; a tab is not a space, and the ruling below says why it
  separates a column anyway.
- **Leading and trailing whitespace on a line is ignored,** and blank or
  whitespace-only lines are skipped — but they still count toward the line
  number a refusal names, so the number matches what an editor shows.
- **The first non-blank line sets the column count.** Every later row must have
  the same number of fields; one that does not refuses the file.
- **A missing final newline is fine.** This file is somebody else's: an
  unterminated last line is how half the world's text files end, not the torn
  write the note store has to refuse.

## The layout

Every column is left-aligned to the width of its widest value, columns are
exactly two spaces apart, and no line ends in whitespace — the last column is
never padded, so there is none to strip afterwards. Rows print in the order
they were written: this lines columns up, it does not sort.

```
alice     12  red
bo        3   blue
carolina  7   g
```

## The rulings

The contract left four things open. Each was decided once, written down here
and in the handler docstring, and pinned by a test.

**A tab separates a column, like a space does.** The contract says spaces, and
a text table is written with either — `leaderboard/reader.py` already reads
`alice<TAB>12` the same as `alice 12`, so the branch is consistent with itself.
The second reason is mechanical: splitting on spaces and tabs means no field
can contain a tab, and a field holding one would be padded to a width it does
not print at — a tab is one character to `len()` and a jump to the next tab
stop on a terminal.

**Every other whitespace character is data.** `str.split()` would have been the
one-line way to do this, and it breaks a row on a no-break space, an en quad
and every other `str.isspace()` character — turning a value somebody
deliberately typed as one field into two. The regex is `[ \t]+` for that
reason. Two honest footnotes: a vertical tab or a form feed never reaches this
decision, because `str.splitlines()` treats both as line boundaries and splits
the FILE before anything splits a row; and a no-break space at the START or END
of a line IS still stripped, because `str.strip()` takes any whitespace. Both
are pinned by tests rather than left as prose.

**Width counts code points, not terminal cells.** `zoë` is three characters and
a double-width CJK character counts as one, so `日本` and `ab` pad to the same
width. Counting cells means either a dependency or a guess about the reader's
terminal, and a guess is the thing this branch exists to refuse. The cost is
visible: a CJK table looks ragged in a terminal even though every column holds
the same number of characters.

**A row with fewer than two fields is named as that, never as a count
mismatch.** Both checks apply to a one-field row halfway down a three-column
file. The field-count check runs first, so the refusal points at what is
actually wrong with the row rather than at the first check that happened to
notice. A refusal that fires first hides every check behind it (canary key
learning 23), so which one speaks is part of the contract and has its own test.

A fifth call was made by precedent rather than by argument: **more than one
FILE is refused as "too many arguments"**, the same reason `top` gives, checked
before any file is opened.

## The refusals

All exit 2, print to stderr, and write **nothing** to stdout. That second half
is the contract: a table is the kind of output that gets piped, so a
half-aligned one printed beside a refusal would be read as the answer. The
tests assert an empty stdout on every refusal case, in the plain form and the
`--json` form both.

| Input | Refused as |
|-------|-----------|
| `align --json` | no FILE given |
| `align FILE other` | too many arguments |
| a path that is not there | file not found |
| a directory, or a file that will not open | cannot read *path* (*reason*) |
| a file with a byte that is not UTF-8 | not valid UTF-8, with the byte offset |
| a row with one field | line *n* has fewer than two fields |
| a row with more or fewer fields than the first | line *n* has *k* fields, the first row set *m* |
| an empty file, or one holding only blank lines | *path* has no non-blank lines |

One bad row refuses the whole file. The rows before it are read and held in
memory, never printed as they go, so a partial table cannot escape ahead of the
refusal — that case has its own test.

Unlike `top`, an empty file is a refusal here rather than an empty answer. The
contract lists "a file with no non-blank lines at all" among the refusals, and
the two commands differ for a reason worth keeping: an empty ranking is a
result ("nobody scored"), while an empty table is not a table.

Bare `align` with no arguments prints the usage and exits 0. `align --json`
with nothing else is a refusal — arguments were given, output was asked for,
and no FILE came with the request. It is also the only way to reach the no-FILE
refusal at all, since no arguments whatsoever prints the usage instead.

## The refusal trail

Every refusal goes through one function, `_refuse`, which records it on the
json operation trail as `table_refused` with its reason before raising. A row
with one field halfway down a long file is the interesting half of this
command, and a reason that only ever reached a terminal is one nobody can count
afterwards. Successful runs are recorded by the module as `table_aligned` with
the row and column counts; both land in `canary_json/`.

## The JSON form

`align --json FILE` prints one array of arrays — every field a string, every
row in file order — on one line, and nothing else on stdout. The flag is
accepted anywhere in the arguments and is removed before the positional
arguments are read. The payload carries **no padding**: the alignment belongs
to the printed form, and a caller that parses stdout wants the fields as they
were written. Rich markup, highlighting and emoji are off, and `ensure_ascii`
is off, so a field reaches stdout as typed: `zoë` stays `zoë`, and a field
written `[bold]x[/bold]` prints as those fourteen characters — and pads to
fourteen — rather than becoming a style.

## What the tests actually measure

`tests/test_align.py`, 58 cases. Alignment is asserted as **exact lines**,
never as "contains" — the padding IS the output, so a test that only looked for
the fields would pass on a formatter that never padded anything. The layout
half covers the widest value arriving in the last row, five columns, a single
row, runs of spaces, tabs, blank and whitespace-only lines, indentation,
trailing spaces, a missing final newline, CRLF endings, rich markup inside a
field, and the three ruling pins (CJK width, a composed accent, a no-break
space inside a field and at a line edge). The refusal half runs six bad-file
cases twice each, plain and `--json`, plus the argument, absence, unreadable
and encoding refusals, asserting exit 2, an empty stdout and the reason on
stderr. Two ordering pins: the one-field reason beats the count mismatch, and
the argument count is checked before a file is opened.

Fifteen mutants were run against the two sources. Thirteen died on the first
pass: the column gap narrowed to one space (19 red), the padding removed (16),
the last column padded too (13), width taken from the first row instead of the
widest (7), `MIN_FIELDS` lowered to 1 (7), the column-count check deleted (4),
the empty-file refusal deleted (4), the separator widened to `\s+` (1, the
no-break-space pin), the line no longer stripped (2), `_refuse` raising an
empty reason (20), the rows sorted (3), the two row checks swapped in order
(5), and the too-many-arguments check deleted (3).

Two survived, and both were worth the pass. `splitlines()` swapped for
`split("\n")` passed all 56 cases as first written — the CRLF test could not
see it, because `strip()` removes the trailing `\r` on its own. Two pins were
added for the boundaries only `splitlines()` finds, a carriage return alone and
a vertical tab, and the mutant then died on both. The second survivor was a bad
mutant rather than a test gap: it "padded" the JSON payload by rendering each
row on its own, which pads nothing, so it reproduced the correct output exactly.
Rewritten to pad against the real column widths, it died on three cases.

Both sources were restored byte-identical afterwards, verified by sha256, and
the full branch suite re-run: 267 passed.

One more finding came out of writing them. `@cli` renders a refusal through rich,
which **wraps stderr at the console width** — 80 when stdout is not a terminal.
A refusal naming a long path is therefore broken across lines at whatever space
falls near column 80: `has no non-blank lines` arrived as `has\nno non-blank
lines`, and only in the parametrised cases whose `tmp_path` happened to be long
enough, so two of six otherwise identical cases failed. The tests now flatten
stderr whitespace before asserting, which keeps them about the reason rather
than about path length. The wrapping is the shared console's behaviour, not
this branch's, and it means any caller grepping stderr for a refusal phrase can
miss it on a long path.

[<- Back to the branch README](../README.md)
