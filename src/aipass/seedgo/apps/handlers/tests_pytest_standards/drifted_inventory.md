# Drifted Inventory (static nominator)
**Status:** Active v1
**Tier:** STATIC — nominates, never convicts (Law M1)
**Species:** DRIFTED-INVENTORY
**Rule:** TAXONOMY section 5 rule 11 - a hand-kept inventory that claims completeness and drifted

---

## What it flags

- a module-level list of dotted module names, parametrized over, carrying a written completeness claim, that omits modules the tree actually holds - each omission is a module nothing probes, and the suite stays green because the list is also the oracle
- the same list naming modules the tree does NOT hold - a probe pointed at nothing, or a rename the list never followed

## What it must never flag

- a list with no completeness claim in a comment above it, the module docstring, or the docstring of a test that parametrizes over it - a subset promises nothing
- a list no parametrize decorator consumes; if it is not the oracle its drift costs no coverage
- a list that matches the walked tree exactly in both directions
- tests/, docs/, __pycache__ and any dot-directory, which an importable inventory never claims

## What it cannot see

- a module may be legitimately excluded - an optional extra, a platform shim - and is still nominated; that is why this tier nominates and the execution tier convicts (Law M1)
- the walk root is inferred - the outermost package still holding the test file, never above the corpus root - and a literal whose entries mostly do not exist there is LOGGED and skipped, never published, because the mapping rather than the list is what failed
- a literal built at runtime, or spread across several assignments, is invisible to a static reader - which biases this rule toward FEWER nominations

## The fix

derive the list from a walk of the tree instead of maintaining it by hand, or pin the expected COUNT beside it from an independent source so a forgotten module reds the suite. A list that is both the input and the oracle cannot notice its own gaps.

## Measured

canary's CANARY_MODULES lists eight modules under the comment 'Every importable module in canary's tree' while the tree holds eleven; the three it forgot - apps.modules.note, apps.handlers.notes and apps.handlers.notes.store - are never import-probed

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
