# Tautology Assert (static nominator)
**Status:** Active v1
**Tier:** STATIC — nominates, never convicts (Law M1)
**Species:** TAUTOLOGY-ASSERT
**Rule:** TAXONOMY section 5 rule 10 - an assertion whose two sides are the same object

---

## What it flags

- an `assert` whose `==`/`is` compares two structurally identical expressions - it cannot fail
- an `assert` whose `!=`/`is not` compares two structurally identical expressions - it cannot pass
- an `assert` comparing a name bound from importlib.reload(X) against another name for the same module: reload returns the object it was handed, so both sides are one object

## What it must never flag

- any comparison whose two sides differ in any way - this rule makes no judgement call
- a reload compared against a value captured BEFORE the reload, which is the correct shape
- a sys.modules lookup no reload touched - the rule reads reload bindings, not the table
- a module object laundered through an intermediate variable, which is not resolved here

## What it cannot see

- a deliberate `__eq__` pin on a value type is nominated; that is why this tier nominates and the execution tier convicts (Law M1)
- two identical CALL expressions are reported as identical, and a call with side effects may legitimately return different values each time
- module identity is resolved through import aliases and sys.modules only - any other route to the same object is invisible, which biases this rule toward FEWER nominations

## The fix

capture the value BEFORE the action under test and compare the after against the captured before, or assert against a spelled-out expected value. importlib.reload returns the same module object it was handed, so reloading proves nothing on its own.

## Measured

canary's test_branch_name_is_set_at_import_time asserts reloaded.__version__ == canary_entry.__version__ under a docstring explaining that the reload is what makes it meaningful; reload returns its own argument, so the line compares an attribute to itself

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
