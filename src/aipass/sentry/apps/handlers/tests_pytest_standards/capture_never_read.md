# Capture Never Read (static nominator)
**Status:** Active v1
**Tier:** STATIC — nominates, never convicts (Law M1)
**Species:** RETURN-ONLY
**Rule:** TAXONOMY section 5 rule 8 - capture-never-read

---

## What it flags

- a unit requesting capsys/capfd that never calls readouterr()
- a unit whose SOLE assertion is `is True` or `== 0` on a print_*/show_*/report_* call

## What it must never flag

- `is True` paired with any other assertion or any assert_* mock call is KEEP - the species is the SOLE assertion (TAXONOMY known-good rows 9 and 10)
- a predicate under test, where the boolean IS the behaviour, is KEEP
- a callee whose name does not declare it an output function is never nominated

## What it cannot see

- a unit that reads the capture inside a helper is not followed across the call
- an output function not named with an output prefix is invisible to the second shape
- MEASURED UNDER-COUNT: TAXONOMY records 24 RETURN-ONLY units in @backup and this rule finds 0 there. The difference is real and deliberate - backup's are sole `is True` assertions on `handle_command`, a ROUTER receipt, and rule 8 as written names only print_*/show_*/report_* callees. Widening the prefix list to catch routers would also catch every predicate under test, which TAXONOMY's known-good rows 9 and 10 forbid. The gap is published rather than closed by guessing

## The fix

read what you captured: assert on readouterr().out, or assert the emitted text directly.

## Measured

18 in @daemon, 24 in @backup, 4 + 4 across @api; @daemon test_timer_install.py:39 requests capsys, never reads it, and survived probe P20 (TAXONOMY corpus row 16)

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
