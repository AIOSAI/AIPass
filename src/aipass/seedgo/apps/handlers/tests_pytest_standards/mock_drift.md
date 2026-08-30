# Mock Drift (static nominator)
**Status:** Active v1
**Tier:** STATIC — nominates, never convicts (Law M1)
**Species:** MOCK-DRIFT
**Rule:** TAXONOMY section 5 rule 4 - patch-target resolution

---

## What it flags

- @patch('a.b.c') where c resolves to a MODULE file inside the target - the whole module becomes a MagicMock that answers every attribute, including deleted ones

## What it must never flag

- spec=, spec_set=, autospec=True or new_callable= - a specced mock raises on an attribute the real object does not have, which is the whole property at stake
- a patch target that resolves to no file in the target tree is NOT nominated - the rule reports what it can resolve and says so, rather than guessing

## What it cannot see

- resolution is by FILESYSTEM, not by import: Law M10 forbids importing the subject, so a module created dynamically is invisible here
- an f-string target resolves only when every interpolation is a module-level string constant; anything computed is unreadable and is never nominated

## The fix

patch the attribute, not the module - or add autospec=True. One line per decorator.

## Measured

deleting auth.validate_credentials from @api left 46/46 tests green (TAXONOMY corpus row 23); 25 instances found in one half of one branch

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
