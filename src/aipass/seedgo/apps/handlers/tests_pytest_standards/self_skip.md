# Self Skip (static nominator)
**Status:** Active v1
**Tier:** STATIC — nominates, never convicts (Law M1)
**Species:** SELF-SKIP, SKIP-ON-DRIFT, PERMA-SKIP
**Rule:** TAXONOMY section 5 rule 3 - skip-predicate provenance

---

## What it flags

- a skip condition that asks whether a production symbol still exists (hasattr/getattr)
- a skip condition that reads a name imported from the subject under test
- an unconditional skip - the test never runs at all

## What it must never flag

- machine probes: sys.platform, sys.version_info, os.name, os.environ, shutil.which, find_spec
- a platform-divergent test that skips on the platform it cannot run on is correct code

## What it cannot see

- a suite legitimately testing an optional plugin will be nominated; that is why this tier nominates and the execution tier convicts (Law M1)
- a condition built at runtime from a variable is invisible to a static reader

## The fix

make the skip condition read the MACHINE, never the SUBJECT. If the symbol's absence is the thing worth knowing, assert it instead of skipping on it.

## Measured

renaming JSON_DIR in @daemon made 75 tests silently vanish with the run still green (TAXONOMY corpus row 20); the SELF-SKIP shape ships fleet-wide via the branch template (corpus row 25)

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
