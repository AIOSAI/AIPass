# Ruff Pt (static nominator)
**Status:** Active v1
**Tier:** STATIC — nominates, never convicts (Law M1)
**Species:** PT-FAMILY
**Rule:** adopt-half - ruff --select PT (flake8-pytest-style), not a TAXONOMY-ranked rule

---

## What it flags

- every diagnostic ruff's PT family reports over the target's test files, published as a nomination with its code and location

## What it must never flag

- whatever the target's own ruff configuration excludes - the target's config is respected, because a nominator that overrode it would be measuring a project nobody has

## What it cannot see

- ruff may not be installed on a machine measuring an external target; that is reported as not_applicable with a reason, never as a clean result
- severity and fix-availability are discarded - this tier nominates and does not rank

## The fix

most PT codes carry an automatic fix: `ruff check --select PT --fix <tests>`.

## Measured

~0.3s for the whole 18-branch fleet (research section 2.5)

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
