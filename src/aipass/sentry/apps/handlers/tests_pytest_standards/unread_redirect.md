# Unread Redirect (static nominator)
**Status:** Active v1
**Tier:** STATIC — nominates, never convicts (Law M1)
**Species:** UNREAD-REDIRECT
**Rule:** DPLAN-0352 round 3 ask 2 - an autouse redirect whose target no test reads

---

## What it flags

- an autouse fixture that redirects a seam (monkeypatch setenv/setattr/chdir) and returns or yields the redirect target, where no test in the suite requests it

## What it must never flag

- a fixture that returns and yields nothing: it is an isolation fence, there is no target to read, and nothing reading it is the design
- a fixture any test requests by parameter or through usefixtures
- a suite that SUBSTITUTES the seam writer (monkeypatch.setattr(..., 'log_operation', ...)) and asserts on what it recorded - that is the second door onto the same seam
- a fixture that is not autouse: one nobody requests simply never runs

## What it cannot see

- PROXY, AND A FLOOR. 'Requested' is read as 'a test takes it as a parameter or names it in usefixtures', which is weaker than 'a test asserts against the redirect target'. A suite that requests the fixture for its tmp_path and never looks at the seam reads as clean here.
- Conftest only. A redirect declared inside one test module applies to that module, and this rule does not read it.
- It nominates a MECHANISM, not a defect. Whether any write through the seam deserved to be observed is the execution tier's question - statement_deletion is what answers it.
- The writer-substitution acquittal is BRANCH-WIDE and blunt: one test file that names a seam writer clears the whole suite. A branch that watches the seam in one place and is blind everywhere else reads as clean, which is the under-reporting direction a nominator should err in, but it is not free.

## The fix

either assert against the redirect target in at least one test, so writes through the seam are observable, or stop handing the target back and let the fixture be the fence it is

## Measured



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
