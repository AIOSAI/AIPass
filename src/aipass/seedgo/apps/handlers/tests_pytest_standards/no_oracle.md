# No Oracle (static nominator)
**Status:** Active v1
**Tier:** STATIC — nominates, never convicts (Law M1)
**Species:** NO-ORACLE
**Rule:** TAXONOMY section 5 rule 7 - no-oracle pass

---

## What it flags

- a test unit with no assert statement, no pytest.raises/warns/fail, no assert_* mock call, and no call to a locally defined assertion helper

## What it must never flag

- a unit calling a helper whose name begins with assert/check/verify/expect - the oracle is one hop away, and flagging it would teach branches to inline helpers
- pytest.raises, pytest.warns, pytest.approx, pytest.fail and any assert_* method

## What it cannot see

- a bare trailing call CAN be a working exception oracle - TAXONOMY rates this rule MED as a verdict and LOW as a nomination, which is why it only nominates (Law M1)
- a parametrised unit whose oracle lives in the parameter table is not followed

## The fix

if the call raising is the property under test, say so with pytest.raises or a comment; otherwise assert the result.

## Measured

5 in @api half 2, 1 in @backup, 1 in @daemon, plus every IMPLICIT-ORACLE (TAXONOMY section 5)

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
