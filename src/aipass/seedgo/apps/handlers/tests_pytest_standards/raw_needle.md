# Raw Needle (static nominator)
**Status:** Active v1
**Tier:** STATIC — nominates, never convicts (Law M1)
**Species:** WIDTH-FRAGILE-ASSERT
**Rule:** TAXONOMY section 5 rule 9 - a needle matched against output the same test normalises

---

## What it flags

- a string literal matched with `in`/`not in` against captured console output that is NOT normalised, in a test that normalises that same output in another comparison

## What it must never flag

- a test that never normalises anything - matching raw console output is ordinary and correct
- a haystack that is not a pytest capture read; file bytes and return values do not wrap
- the normalising comparison itself, whose two sides are both put through the same call
- a wrapper that returns a number rather than text: len, bool, int, float, type, id

## What it cannot see

- a needle with no spaces may be genuinely wrap-proof and is still nominated; that is why this tier nominates and the execution tier convicts (Law M1)
- the normalising call is matched by SHAPE, not by reading what it does - a helper that takes the haystack and returns something unrelated would read as normalisation here
- a haystack laundered through more than one intermediate name is invisible to a static reader, which biases this rule toward FEWER nominations

## The fix

put BOTH sides of the raw assertion through the same normalising call the test already uses, or state the width the suite requires and pin it - a test whose colour depends on an unstated column count is measuring the terminal, not the code.

## Measured

on the canary fixture, COLUMNS=40-41 produces 18 failures and COLUMNS=42 produces nine, while COLUMNS>=43 passes all 34 - and the suite names no column count anywhere

---

## Why this group is never scored

Law M1 splits the tiers: static **nominates**, execution **convicts**. A nomination
says a test is suspect; it never says a test is worthless, and Law S7b closes the
verdict vocabulary against the delete family for exactly that reason.

Law M11 is the reason the rows carry a `deletion_safety` field that currently says
`probed: false`. TAXONOMY corpus row 26 is the worked example: @daemon's
`HANDLED_COMMANDS` membership tests read as tautologies and are the only pins on the
name of a verb that, renamed, falls through and turns the fleet's scheduler off — with
all 481 tests green. A checker that flagged those pins and got them deleted would have
made the branch worse.

## Why the static tier can never be retired

Design section 4.2a-bis, CONTRACT 0. Mutation's unit of judgement is the **mutant**,
not the **test**, so any healthy test on a symbol masks every weak one beside it.
Measured: a MIRROR-EXPECT test survived a constant mutant while its spelled-out twin
killed the same mutant — so nothing was reported at all. A per-mutant verdict cannot
structurally name a per-test defect, whatever the execution tier grows into.
