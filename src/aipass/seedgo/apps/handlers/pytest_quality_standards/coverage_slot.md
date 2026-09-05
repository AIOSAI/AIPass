# coverage_slot — the test that says out loud why it exists

> Nobody writes *"added for coverage"* about a test they believe in.

**Scope:** `branch_level` · **Severity:** advisory · **Species:** `COVERAGE-SLOT`

---

## Why this rule is the precise one

It is the only rule in the pack whose detector is a phrase match, and that is
exactly why it is the most precise one in the set: **every hit is a confession**.
The test tells you what it is, in its own words, in writing, on purpose.

```python
def test_config_loads():
    """Placeholder test — the standard requires one per module."""
    assert load_config() is not None
```

Nothing static needs to be inferred here. The author already said it.

## Phrases, never words

The naive version of this rule greps the bare word `coverage`. Run that over a
suite whose subject matter is checkers and it flags dozens of honest tests — and a
rule that noisy is one people switch off inside a week.

So the patterns are **purposive**: they state a *reason*, not a *topic*.

```python
def test_every_file_appears_in_the_report():
    """The coverage report lists every file under src/."""   # NOT flagged — subject
    assert set(report.files) == set(source_files())

def test_every_file_appears_in_the_report():
    """Added for coverage."""                                # flagged — reason
    assert report.files
```

Word boundaries are anchored on both ends, so `"the report groups coverage slots
by file"` is prose and `"a coverage slot"` is a confession. That anchor cuts both
ways and the cost is stated rather than hidden: a confession written in the plural
— *"these are coverage slots"* — is missed. Matching is case-insensitive: a
sentence that opens with a confession is still one.

The list, in full: *for coverage*, *coverage slot*, *to satisfy*, *satisfies the
checker/standard/audit/linter*, *the standard requires*, *seedgo requires*,
*keeps X honest*, *placeholder test*, *boilerplate test*, *exists (only)
so/because the checker/audit/standard*.

## Where it looks

Docstrings, and full-line comments inside the unit.

```python
def test_writer_flushes():
    # for coverage of the error arm
    writer.flush()                     # flagged — the comment is the confession
```

**Not** arbitrary string literals. A test whose *data* contains the phrase is
testing a string:

```python
def test_the_report_renders_its_own_note():
    note = "for coverage"              # NOT flagged — this is data
    assert render(note) == "for coverage"
```

Lines inside triple-quoted blocks are excluded by reading the parsed tree, so a
`#` that opens a line of sample content is never mistaken for a comment:

```python
def test_sample_config_parses():
    sample = """
# for coverage
key = 1
"""
    assert parse(sample) == {"key": 1}   # NOT flagged — that # is content
```

A comment sitting *between* two tests belongs to neither. A module-level note is
not a test's confession.

## It nominates, it does not convict

A flag is never a licence to delete. A confessing test can still be the last thing
standing between a rename and a broken release — and the corpus that produced this
rule contains exactly that: pins that read as tautologies and hold a scheduler
together.

If the behaviour matters, say what it is and assert it:

```python
def test_config_loads_the_declared_timeout():
    """A config without `timeout` takes the documented 30s default."""
    assert load_config({}).timeout == 30
```

If it does not, the test is a nomination for review. Review, not deletion.

## What it cannot see

**A coverage slot written without confessing is invisible here.** By construction.

That is not a gap to be closed with heuristics — it is the boundary that keeps
every hit meaning something. The moment this rule starts guessing at intent, it
stops being the one rule in the pack whose findings need no triage.

It also cannot tell a test *about* confessions from a confession, which is why it
reads only test files, and only the prose a test writes about itself. A class
whose *name* looks like a confession is not flagged on its name alone: an
identifier cannot contain whitespace, so none of the purposive phrases can match
one, and splitting `TestCoverageSlotDetection` back into words would flag a class
that is *about* the subject. That was considered and refused.

Its comment range ends at a unit's last statement, so a comment after the final
line of a body is attributed to nobody. A trailing comment on a line of code is
not read either — the `#` has to start the line.

## Scoring

Units that state a behaviour, over total units, counted **per unit**: three
confessions in one docstring is one confessing test.

**Advisory**: it reports a number and never fails a board.

A project with no test files reports `not_applicable` rather than zero. Zero tests
measured is not zero quality found.

*Design: DPLAN-0323 / FPLAN-0469*
