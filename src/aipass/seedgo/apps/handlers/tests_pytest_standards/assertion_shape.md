# Assertion Shape (static nominator)
**Status:** Active v1
**Tier:** STATIC — nominates, never convicts (Law M1)
**Species:** TAUTOLOGY, TYPE-ONLY, OR-ESCAPE
**Rule:** TAXONOMY section 5 rule 5 - assertion shape

---

## What it flags

- assert on a bare literal - assert True, assert 1, assert 'text'
- len(x) >= 0 or len(x) < 0 - true of every possible sequence
- x in (True, False) - true of every bool
- self-comparison: the two sides of the compare are the same expression
- a unit whose ONLY assertions are isinstance checks (TYPE-ONLY)
- assert A or B where neither clause probes the machine (OR-ESCAPE)

## What it must never flag

- an isinstance assertion PAIRED with a value assertion in the same unit is correct
- an `or` whose first clause is a platform-capability probe (hasattr, sys.platform) is platform-divergent code, not an escape

## What it cannot see

- a tautology assembled at runtime from a variable is invisible to a static reader
- a helper function that asserts on the unit's behalf is not followed across the call

## The fix

assert the VALUE. If the type matters too, assert both - the pairing is what makes it real.

## Measured

16 in @daemon, 13 in @api half 1, 11 in @backup, 6 in @api half 2 (TAXONOMY section 5 rule 5)

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
