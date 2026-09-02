# no_oracle — does this test verify anything?

> A test earns its place by proving something. If it verifies nothing, it is a
> smoke test wearing a test's name: it reports green until the code raises,
> while the behaviour it was named for silently rots.

**Scope:** `branch_level` · **Severity:** advisory · **Replaces:** `aipass_standards/test_quality` (v4)

---

## Why this rule exists

The standard this one replaces scored a project by searching its test files for
99 pattern substrings. The match was a bare `in` over raw source text, so
comments and docstrings counted toward the score. A file containing nothing but
those pattern strings — no code, no tests, no assertions — scored 94%.

It was also not optional. The raw percentage became the standard's score, that
score entered the branch average, and CI gated the average at 100. So every
branch was pushed to 51 of 51 pattern items. That is why `importlib.reload`
appears in eighteen of eighteen branches here: not drift, not sloppiness —
compliance. The checker asked for strings, so it got strings.

This rule asks the question v4 never asked: **is there an oracle?**

## What counts as an oracle

Deliberately generous:

- an `assert` statement, anywhere in the unit
- `pytest.raises`, `pytest.warns`, `pytest.fail`, `pytest.approx`, `pytest.xfail`
- any `assert_*` method — the `unittest` and `mock` spellings
- a call to a checking helper: a name starting `assert`, `check`, `verify`, or
  `expect`

That last one matters. A unit calling `_assert_document_is_lawful(...)` has an
oracle one hop away. Flagging it would teach projects to inline their helpers to
please the checker — which is precisely the behaviour v4 produced, and precisely
what this pack exists to stop.

**Why generous:** a false flag costs a reader thirty seconds. A missed one costs
nothing visible at all. Being wrong in the generous direction is the cheap
mistake, so this rule makes it on purpose.

## It nominates, it does not convict

```python
def test_parser_rejects_garbage():
    parse("<<<not valid>>>")     # no assert — flagged
```

This test is not worthless. It really does fail the day `parse` starts accepting
garbage. That is a **weak** oracle, not an absent one, and static reading cannot
tell the two apart from outside the process.

So the flag never says the test is worthless. It says: *no oracle is visible
here, and here is what the test calls.* A human decides what that means.

## How to fix a flag

If the call raising **is** the property under test, say so:

```python
def test_parser_rejects_garbage():
    with pytest.raises(ParseError):
        parse("<<<not valid>>>")
```

Otherwise, assert the result:

```python
def test_parser_keeps_the_offset():
    assert parse("a=1").offset == 3
```

If the test proves nothing either way, it is a deletion candidate — but nothing
is deleted by this checker, and nothing should be deleted by a checker.

## Scoring

Units with a visible oracle, over total units. **Advisory**: it reports a number
and never fails a board.

A project with no test files reports `not_applicable` rather than zero. Zero
tests measured is not zero quality found — a 0 would blame a project for a fact
about its layout, and a 100 would claim a measurement that never happened.

## Note on this file

In `aipass_standards`, the `.md` files are read by nobody: `standards_query`
serves the `*_content.py` handlers, so the markdown is a second source of truth
that quietly drifts. Here it has a real reader. This pack is generic — lifted
onto a project that has no `standards_query`, this file *is* the documentation.

*Design: DPLAN-0323 / FPLAN-0469*
