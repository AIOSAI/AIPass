# Unentered Assert (static nominator)
**Status:** Active v1
**Tier:** STATIC — nominates, never convicts (Law M1)
**Species:** VACUOUS-GUARD, VACUOUS-LOOP
**Rule:** TAXONOMY section 5 rule 9 - unentered-assertion pass

---

## What it flags

- the unit's only assert sits under an `if` whose `else` is absent or asserts nothing
- the unit's only assert sits inside a `for` with no floor proving the iterable is non-empty

## What it must never flag

- an `if` that asserts on BOTH branches is correct platform-divergent code and is never nominated (TAXONOMY known-good rows 2 and 3)
- a loop preceded by an emptiness floor - `assert items`, a len() comparison, or a literal collection - is never nominated
- a unit with any assertion at the top level of its body is never nominated: something in it always runs

## What it cannot see

- a floor established inside a fixture is not followed across the call
- an `if` whose condition is statically always true still reads as a guard here

## The fix

assert the floor as well as the contents: `assert items` before the loop, or an else branch.

## Measured

4 in @api half 1, 3 in @daemon, 1 in @backup, including an assertion that has never once executed (TAXONOMY corpus row 14) and a loop observed passing over an empty directory (corpus row 17)

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
