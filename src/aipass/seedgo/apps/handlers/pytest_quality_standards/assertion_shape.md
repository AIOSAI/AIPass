# assertion_shape — can this test's assertion actually fail?

> An assertion that is true of every possible program is worse than a missing
> one. A missing assertion looks like a gap. A tautology looks like coverage.

**Scope:** `branch_level` · **Severity:** advisory · **Ported from:** TAXONOMY section 5 rule 5

---

## Why this rule exists

`no_oracle` asks whether a test verifies anything at all. This rule asks the next
question down: the oracle is right there in the body — can it ever say no?

Three shapes came out of a hand audit of the fleet's test corpus, and they are
not the same kind of claim. One is a fact, one is a property of the whole unit,
and one is a judgement call that has to be made carefully or the rule gets
switched off for crying wolf.

## TAUTOLOGY — true of every program

Per assertion, and the only species this rule is confident about:

```python
assert True                     # true of every program that reaches the line
assert len(rows) >= 0           # true of every possible sequence
assert len(rows) < 0            # false of every possible sequence
assert flag in (True, False)    # true of every bool
assert config.name == config.name   # both sides are the same expression
```

Nothing in the surrounding test rescues these. `len(x) > 0` and `len(x) == 3` are
real claims and are not flagged — only the two directions that are decided before
the program runs.

The fix is to say what you meant:

```python
assert len(rows) == 3
assert flag is True
assert config.name == "prod"
```

## TYPE-ONLY — a property of the unit, never of a line

This one is flagged only when a unit's **entire** oracle is `isinstance`:

```python
def test_parse_returns_a_dict():
    result = parse(SAMPLE)
    assert isinstance(result, dict)      # flagged: nothing about the value
```

Any implementation returning the right shape of garbage passes that test. But
the moment a value assertion stands beside it, the pairing is correct and common
and must never be flagged:

```python
def test_parse_returns_the_offsets():
    result = parse(SAMPLE)
    assert isinstance(result, dict)      # not flagged — it has company
    assert result["offset"] == 3
```

Getting that backwards is the failure mode that would sink the rule: it would
flag the *right* answer and teach projects to delete their type assertions.

## OR-ESCAPE — the assertion with an exit

```python
assert result == [] or isinstance(result, list)   # flagged
```

The second clause is true whenever the first one is, so the assertion cannot
fail on the path it was written for. One real example of this shape survived a
probe that replaced an entire diff engine with an echo — all nineteen tests in
the file passed.

**A capability clause acquits an `or`.** This is not an escape hatch:

```python
assert not hasattr(signal, "SIGKILL") or signal.SIGKILL not in handlers
```

The first clause asks about the **machine**, not about the result — it is
platform-divergent code written honestly. `hasattr`, `sys.platform`, `os.name`,
`platform.system`, `sys.version_info` and `shutil.which` all acquit the whole
assertion. That acquittal is generous on purpose: a false flag on real
platform-divergent code is exactly the kind of wrong that gets a standard
disabled.

In a real OR-ESCAPE, **both** clauses are about the result.

## What this rule does not claim

- **Not every unfailable assertion.** A tautology assembled at runtime from a
  variable is invisible to a static reader, and so is one hiding inside a helper
  the unit calls. Nothing here follows a call.
- **Not that a flagged unit is a bad test.** A tautology can sit beside four real
  assertions in the same body. The unit still scores as flagged, because the
  shape is worth thirty seconds of a reader's eye — not because the test is
  worthless.
- **Not that an `or` was written as an escape.** Sometimes two answers really are
  legal. The rule cannot tell tolerance from evasion from the outside, so it
  nominates and a human decides.

## Scoring

Units with no flagged assertion, over total units. **Per unit, not per finding**:
a unit holding four tautologies is one unit somebody has to go and look at, and
counting findings would let a single sloppy test push a project's score below
zero. A score that can go negative is one nobody believes twice.

**Advisory**: it reports a number and never fails a board.

A project with no test files reports `not_applicable` rather than zero. Zero
tests measured is not zero quality found. A project whose only test file is
unparseable says so explicitly, and is never reported as a project without tests.

*Ported from `tests_pytest_standards/assertion_shape_check.py` · Design: DPLAN-0323 / FPLAN-0469*
