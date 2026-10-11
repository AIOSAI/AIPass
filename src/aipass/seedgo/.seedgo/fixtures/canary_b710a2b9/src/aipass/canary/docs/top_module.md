[<- Back to the README](../README.md)

# The top module

A leaderboard reader: `top 3 scores.txt` prints the three highest counts.
`apps/modules/top.py` routes and prints; `apps/handlers/leaderboard/reader.py`
reads the file, ranks it, and owns every refusal.

It exists as a test subject, not as a feature. Built to a dispatched contract
(@devpulse, 2026-09-19) whose interesting half is not the ranking but the two
things a careless reader gets wrong: seven ways a file or an argument is not a
leaderboard, each exiting 2 with nothing on stdout, and an order that has to be
the same every run rather than merely stable within one.

## The file

Plain UTF-8 text. Every non-blank line is a name, whitespace, and an integer
count.

- **A row is exactly two fields:** `alice 12`. The split is on any whitespace,
  so a tab between them reads the same as a space.
- **Leading and trailing whitespace is ignored,** and blank or whitespace-only
  lines are skipped — but they still count toward the line number a refusal
  names, so the number matches what an editor shows.
- **A name may appear more than once.** Its counts are added together before
  anything is ranked: the file is a tally, not a table of final scores.
- **Leading zeros are accepted** (`007` is 7), and so is `-0`, which equals
  zero. A plain integer is what the contract asks for and both are one.
- **A missing final newline is fine.** Unlike the note store, this file is
  somebody else's: an unterminated last line is how half the world's text files
  end, not the torn write the store has to refuse.

## The order

Count descending, then **name ascending by code point** within an equal count.

The tie-break is the part worth reading. Sorting by count alone leaves
dictionary insertion order deciding equal counts — stable within one run, and
therefore a result that passes a single-run assertion while being a property of
how the file happened to be written. Reorder the rows in the file and the
output changes. The tests write the same three tied rows in three different
orders and demand one ranking, which is what makes "the same every run" a
measured claim rather than an observed coincidence.

Fewer rows than `N` is an answer, not a refusal: what there is gets printed. A
file with no rows at all prints nothing and exits 0 — and `[]` in the JSON
form, because a caller that parses stdout needs something to parse.

## The refusals

All exit 2, print to stderr, and write **nothing** to stdout. That second half
is the contract: a partial ranking printed beside a refusal would be read as an
answer by whatever consumes the output, so the tests assert an empty stdout on
every refusal case, in the plain form and the `--json` form both.

| Input | Refused as |
|-------|-----------|
| `top --json` | no N given |
| `top 3` | no FILE given |
| `0`, `-1`, `1.5`, `three`, `""` as N | N must be a positive integer |
| `٣` as N | N must be a positive integer — `int("٣")` is 3, so the check is ASCII-only |
| `top 2 FILE extra` | too many arguments |
| a path that is not there | file not found |
| a directory, or a file that will not open | cannot read *path* (*reason*) |
| a file with a byte that is not UTF-8 | not valid UTF-8, with the byte offset |
| `alice`, `12`, `alice 12 extra` | line *n* is not exactly a name and an integer count |
| `alice 1.5`, `alice +3`, `alice twelve`, `alice ٣`, `alice -` | line *n* has a count that is not an integer |
| `alice -3` | line *n* has a negative count |

Two of those rows are deliberate separations. A negative count gets its own
reason rather than being folded into "not an integer", because `-3` **is** an
integer and a refusal has to point at what is actually wrong. And `alice 12
extra` is refused rather than read as a name and a count with a third field
ignored: a reader that silently drops a field cannot be measured from outside.

One bad row refuses the whole file. A ranking assembled from the rows that
happened to parse is not a ranking of that file.

N is checked before the file is opened, so `top 0 missing.txt` names N and not
the missing file — the tests pin that order, because a refusal that fires first
hides every check behind it.

Bare `top` with no arguments prints the usage and exits 0. `top --json` with
nothing else is a refusal: arguments were given, output was asked for, and no N
came with the request.

## The refusal trail

Every refusal goes through one function, `_refuse`, which records it on the
json operation trail as `leaderboard_refused` with its reason before raising.
A malformed row halfway down a long file is the interesting half of this
command, and a reason that only ever reached a terminal is one nobody can count
afterwards. Successful rankings are recorded by the module as `top_ranked` with
how many names were read and how many were printed; both land in `canary_json/`.

## The JSON form

`top --json N FILE` prints one array of objects, each with exactly `name` and
`count`, in the ranked order and nothing else on stdout — one line. The flag is
accepted anywhere in the arguments and is removed before the positional
arguments are read. Rich markup, highlighting and emoji are off for the
payload, and `ensure_ascii` is off, so a name reaches stdout as it was typed:
`zoë` stays `zoë` rather than becoming an escape.

## What the tests actually measure

`tests/test_top.py`, 68 cases. The ranking half asserts exact stdout lines —
summing, the tie-break under three write orders, a tie created only by the
summing, a short file, an empty file, whitespace and blank lines, `0`, `-0`,
`007`, and a file with no final newline. The refusal half runs eight argument
cases and nine row cases twice each, plain and `--json`, asserting exit 2, an
empty stdout and the reason on stderr, plus the three file-level refusals
(absent, unreadable, not UTF-8). Help in any position asserts that no line of
stdout is `alice 12` or `bob 30` — the help page quotes `alice 12` in an
example, so a substring check would have passed for the wrong reason.

Twelve mutants were run against the source, all twelve killed: the tie-break
deleted (3 red), the field count weakened from `==` to `<` (2), the
negative-count check deleted (4), the ASCII-digit check swapped for
`str.isdigit` (4), N's lower bound moved from 1 to 0 (4), counts overwritten
instead of summed (3), `rank` ignoring N (2), a missing file read as an empty
one (2), `_refuse` logging without raising (38), bad UTF-8 replaced instead of
refused (1), the too-many-arguments check deleted (2), and a refusal that also
renders an empty ranking (16).

That last one is worth its own sentence. All sixteen of its kills come from the
`--json` cases: in the plain form an empty ranking prints nothing, so a refusal
that also rendered one is invisible there. The JSON form is what makes that
mutant visible at all, which is the argument for running every refusal case
twice rather than trusting the plain form to speak for both.

The sources were restored byte-identical afterwards, verified by sha256.

[<- Back to the branch README](../README.md)
