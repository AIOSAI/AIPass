# Empty Parametrize (static nominator)
**Status:** Active v1
**Tier:** STATIC — nominates, never convicts (Law M1)
**Species:** VANISHING-TABLE
**Rule:** TAXONOMY section 5 rule 3a - a table computed at collection time

---

## What it flags

- parametrize argvalues drawn from a function call, whose empty return pytest reports as SKIPPED while the suite summary reads green

## What it must never flag

- a literal list/tuple/set with elements - it cannot be empty
- a module-level name bound to a non-empty literal
- a safe builtin over a literal: range(24), sorted(LITERAL)
- a file carrying an independent non-empty assertion on the same source

## What it cannot see

- a table legitimately empty on some machines is nominated; that is why this tier nominates and the execution tier convicts (Law M1)
- the guard clause matches an assertion anywhere in the FILE, not one proven to cover this particular table - it errs toward acquitting

## The fix

assert the collection is non-empty in a test of its own, and derive that assertion from the raw data rather than from the function being judged - a probe that calls the collector cannot detect a blinded collector.

## Measured

@drone's test_bypass_anchors.py survived a collector-blinding mutant and reported '1 passed, 2 skipped' (2026-08-31, reported unprompted with the cure)

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
