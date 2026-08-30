# Coverage Slot (static nominator)
**Status:** Active v1
**Tier:** STATIC — nominates, never convicts (Law M1)
**Species:** COVERAGE-SLOT
**Rule:** TAXONOMY section 5 rule 6 - confession grep

---

## What it flags

- a test docstring, comment or class name stating a PURPOSE that is not the behaviour: 'for coverage', 'to satisfy the checker', 'the standard requires', 'keeps X honest'

## What it must never flag

- a docstring that merely MENTIONS coverage while asserting real behaviour - the patterns are purposive phrases, never bare topic words
- string literals in test DATA are not scanned; only docstrings, comments and class names

## What it cannot see

- a coverage slot written without confessing is invisible to this rule, by construction
- phrase matching cannot tell a test ABOUT confessions from a confession - this file's own docstring is why the scan excludes non-test modules

## The fix

if the behaviour matters, say what it is and assert it. If it does not, the test is a nomination for review - never for deletion (Law M11).

## Measured

small but exact - TAXONOMY records 'every hit is a confession' (section 5 rule 6)

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
