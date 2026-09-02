# unentered_assert — does the assertion ever run?

> An assertion proves nothing until it executes. A test whose only assertion
> sits behind a branch that may never be entered reports green whether or not
> anything was checked, and the run says nothing about which happened.

**Scope:** `branch_level` · **Severity:** advisory · **Species:** `VACUOUS-GUARD`, `VACUOUS-LOOP`

---

## Why this rule exists

Two shapes were found repeatedly in the triage corpus, and both are invisible in
a passing run.

**The guard.** A test's only assertion sits inside an `if` with no `else`:

```python
def test_log_operation_empty_dict_not_attached():
    entry = log_operation({})
    if "payload" in entry:
        assert entry["payload"] != {}
```

When `"payload"` is absent the test passes having checked nothing. One instance
of exactly this shape was traced through a real suite: the assertion **had never
once executed**. Nothing in the report said so — a green line looks the same
either way.

**The loop.** A test's only assertion sits inside a `for` over something that
may be empty:

```python
def test_every_citizen_declares_itself():
    for project in (root / "projects").iterdir():
        assert (project / "passport.json").exists()
```

Run this against an empty `projects/` directory and the body never executes. It
was observed live in a suite reporting `478 passed, 3 skipped` — one of those
478 passes was this test asserting nothing.

## What is never flagged

**An `if` that asserts on both arms.** This is correct divergent code, not a
vacuous guard, and it must pass:

```python
def test_the_payload_round_trips():
    if payload.compressed:
        assert decode(payload) == EXPECTED
    else:
        assert payload.raw == EXPECTED
```

Whichever way the condition falls, something is checked. Getting this wrong
would teach a project to delete the branch it cannot run on the machine it is
sitting at — worse code, produced by the checker.

**Any assertion on a path that always runs.** If the unit asserts in its own
body, or inside a `with` or `try` body — neither of which branches — the unit is
excused however many conditional assertions it also carries. Something in it
ran. This rule is about assertions that may never execute, not assertions that
are merely conditional.

**A loop with a floor.** A literal collection is a floor by construction; so is
an assertion before the loop that reads the iterable's size or truth.

```python
def test_each_row_is_shaped():
    rows = load_rows()
    assert len(rows) == 3          # the floor
    for row in rows:
        assert row.width == 3
```

An empty `rows` now fails the test instead of passing it silently.

## What this rule does not claim

It does not claim the flagged assertion **is** dead. It claims nothing in the
file proves it is alive.

A guard whose condition is effectively constant, or a loop over an iterable a
fixture has already filled, reads from the outside exactly like one that never
fires. The floor lives one call away and a static reader does not follow it. So
some flags are false, they cost a reader thirty seconds, and this tier is
advisory either way — the cheap direction to be wrong in.

It also does not rank the species. A vacuous loop and a vacuous guard are the
same finding wearing different syntax, and a unit carrying both is **one** flag,
not two.

## How to fix a flag

Assert the floor as well as the contents:

```python
def test_every_citizen_declares_itself():
    projects = sorted((root / "projects").iterdir())
    assert projects, "fixture planted no projects - the loop below would prove nothing"
    for project in projects:
        assert (project / "passport.json").exists()
```

Or check the other case:

```python
def test_log_operation_empty_dict_not_attached():
    entry = log_operation({})
    if "payload" in entry:
        assert entry["payload"] != {}
    else:
        assert "payload" not in entry
```

If the guard exists because the case genuinely cannot occur on this host, the
honest spelling is a `skipif` with a reason. A skip is visible in the report; a
guard that quietly does not fire is not.

## Scoring

Units with no unentered assertion, over total units. One flag per unit.
**Advisory**: it reports a number and never fails a board.

A project with no test files reports `not_applicable` rather than zero. Zero
tests measured is not zero quality found — a 0 would blame a project for a fact
about its layout, and a 100 would claim a measurement that never happened. A
project whose only test file is unparseable says so explicitly, because a broken
file must never read as an absent one.

## A stated limit

`has_floor` accepts an assert-shaped floor as well as a literal iterable. From
`check_branch` that arm is subsumed by the exemption above it: an assertion
standing in the body already proves something always runs, so the unit is
excused a step earlier and the literal-iterable arm is the one that fires. It is
written down here rather than left for the next reader to discover as a
surprise.

*Design: DPLAN-0323 / FPLAN-0469*
