# Posix Literal (static nominator)
**Status:** Active v1
**Tier:** STATIC — nominates, never convicts (Law M1)
**Species:** POSIX-LITERAL
**Rule:** TAXONOMY section 5 rule 3b - a rooted path literal put through a resolver

---

## What it flags

- a path constructor over a rooted string literal with .resolve() called on it
- os.path.realpath or os.path.abspath over a rooted string literal

## What it must never flag

- any other object's resolve() - a branch-name resolver shares the verb and nothing else (6 of 10 sites in the loose arm were exactly that)
- a literal that is not rooted - a relative fragment carries no platform claim
- a path built from tmp_path, os.sep or a fixture rather than written down

## What it cannot see

- reads the RECEIVER, so a path handed through a variable is not seen - this rule errs short rather than nominating every resolve in the fleet
- a test deliberately exercising POSIX spelling is nominated; that is why this tier nominates and the execution tier convicts (Law M1)
- walks TEST UNITS, so a literal resolved in a fixture or at module level is not seen - the same bias toward FEWER nominations the rest of this tier has

## The fix

derive the path from tmp_path or os.sep, or state the platform claim out loud - parametrise both dialects, or assert on Path.parts rather than on a spelling. Where the literal IS the subject, keep it and say so: a rooted literal is drive-relative on Windows, not invalid.

## Measured

@drone's windows-setup red, round 7: a pin comparing against 'RESOLVED: /tmp' got D:\tmp from ntpath and accused a working wrapper (2026-08-31, reported with the species named and the acquittal rate asked for before the rule)

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
