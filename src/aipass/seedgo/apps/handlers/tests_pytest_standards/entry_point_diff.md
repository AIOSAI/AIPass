# Entry Point Diff (static nominator)
**Status:** Active v1
**Tier:** STATIC — nominates, never convicts (Law M1)
**Species:** WRONG-LAYER
**Rule:** TAXONOMY section 5 rule 10 - entry-point diff

---

## What it flags

- a CLI verb declared in a COMMANDS/HANDLED_COMMANDS tuple that no string literal in the test corpus ever names
- an HTTP route declared by a @route/@get/@post decorator that no test literal names

## What it must never flag

- a verb shorter than 3 characters is skipped - a literal match on it means nothing
- a route reached only through a mounted sub-app is a known false positive (TAXONOMY)

## What it cannot see

- 'mentioned' is the weakest possible test: an exact string literal anywhere in the corpus acquits, including in a docstring. This over-acquits on purpose - a guessing nominator is worse than a blind spot with a name
- a verb assembled at runtime is invisible to a static reader

## The fix

add a test that names the entry point, or delete the entry point - but see Law M11 first.

## Measured

6 unexercised HTTP routes over a 97%-covered handler lane - the only security-consequential finding in wave 1 (TAXONOMY section 5 rule 10)

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
