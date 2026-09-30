[<- Back to the README](../README.md)

# The span module

A duration parser: `span "2d 4h"` prints `187200`. `apps/modules/span.py`
routes and prints; `apps/handlers/duration/parser.py` does the parsing and
owns every refusal.

It exists as a test subject, not as a feature. Built to a dispatched contract
(@devpulse, 2026-09-19) whose interesting half is not the arithmetic but the
refusals: six ways a text is not a duration, each of them exiting 2 with
nothing on stdout.

## The grammar

A duration is a sequence of parts. A part is a plain non-negative integer
followed by a unit.

- **Units:** `d`, `h`, `m`, `s` — 86400, 3600, 60 and 1 seconds. Lowercase.
- **Order is free:** `30m 1h` is `1h 30m`.
- **Whitespace is insignificant,** not merely optional: the text is squeezed
  before it is read, so `1h30m`, `1h 30m` and `1h  30 m` are one duration. A
  shell that split the text into several arguments is rejoined first.
- **Each unit at most once:** `1h 1h` is refused rather than summed. Two
  readings of the same text are possible — 2 hours, or a typo — and guessing
  between them is not this parser's job.
- **Leading zeros are accepted:** `007h` is 25200. `007` is a plain
  non-negative integer, which is what the contract asks for.
- **The total may not exceed 366 days** (31,622,400 seconds).

## The refusals

All exit 2, print to stderr, and write **nothing** to stdout. That second half
is the contract: a refusal that printed a number would be read as an answer by
whatever consumes the output, so the tests assert an empty stdout on every
refusal case, in the plain form and the `--json` form both.

| Text | Refused as |
|------|-----------|
| `""`, `"   "` | no duration text |
| `1h 1h` | unit `h` is given more than once |
| `2x` | unknown unit `x` |
| `2H` | unknown unit `H` — the parser never case-folds |
| `1.5h`, `-3h`, `+3h` | not a plain non-negative integer |
| `٣h` | not a plain non-negative integer — `int("٣")` is 3, so the check is ASCII-only |
| `90`, `1h 30` | a bare number with no unit |
| `d` | unit `d` with no number in front of it |
| `367d`, `366d 1s` | over the 366-day limit |

The refusal names the part that is wrong, not the whole text. That is why the
parts are split by character class — number up to the next letter, then the
letter run — rather than matched against a pattern of what is valid: `1.5h`
arrives as `("1.5", "h")` and is refused as a bad number, where a stricter
split would have reported an unknown unit `.` and pointed at the wrong half.

`span --json` with no text is a refusal, not the usage: arguments were given
and none of them was a duration. Only a bare `span` with no arguments at all
prints the usage and exits 0.

## The refusal trail

Every refusal goes through one function, `_refuse`, which records it on the
json operation trail as `duration_refused` with its reason before raising. The
refusals are the interesting half of this command, and a reason that only ever
reached a terminal is a reason nobody can count afterwards. Successful parses
are recorded by the module as `span_parsed`; both land in `canary_json/`.

## The JSON form

`span --json TEXT` prints one object, `{"seconds": N}`, and nothing else on
stdout — one line, one key. The flag is accepted anywhere in the arguments and
is removed before the text is rejoined. Rich markup and highlighting are off
for the payload, so what a caller reads is what was written.

## What the tests actually measure

`tests/test_span.py`, 56 cases. Fourteen valid forms assert the exact stdout
line and an empty stderr; fifteen refusal cases run twice, plain and `--json`,
asserting exit 2, an empty stdout and the reason on stderr. The 366-day limit
has a case on each side of the boundary, so an off-by-one cannot pass. Help in
any position asserts that no line of stdout is a bare number — the help page
quotes `187200` in an example, so a substring check would have passed for the
wrong reason.

Nine mutants were run against the source, all nine killed: the repeated-unit
check deleted (4 red), the limit's `>` weakened to `>=` (2), the ASCII-digit
check swapped for `str.isdigit` (2), the bare-number check deleted (4), the
whitespace squeeze weakened to `strip()` (13), `_refuse` logging without
raising (33), a refusal that also prints `0` to stdout (32), a second key added
to the JSON payload (2), and an hour worth 360 seconds instead of 3600 (11).
The source was restored byte-identical afterwards.

[<- Back to the branch README](../README.md)
