# docstring_pin — does the docstring name anything the test touches?

> A test's docstring should name the defect it pins. That rule is accepted
> **structurally only** — never as a prose match, because a prose match is the
> same gameable defect one level up.

**Scope:** `branch_level` · **Severity:** advisory · **Mode:** reporting, not scoring

---

## Why this rule is structural and not a prose match

The standard this pack replaces scored tests by searching for pattern substrings
in raw source, and branches complied by writing the patterns into comments. A
file of strings with no code scored 94%.

A prose version of "the docstring must name the defect it pins" would be that
exact defect, one level up. This passes any prose matcher:

```python
def test_the_parser(self):
    """Pins the contract that the parser rejects malformed input, a regression
    that recurred twice, and guards the invariant the defect violated."""
    assert True
```

Every keyword a prose checker could look for is present. Nothing is named.
Nothing is checkable. It cost eight seconds to write.

So this file never reads the docstring for **meaning**.

## What it actually asks

1. Collect the names the unit **calls**.
2. Pull every identifier and dotted path out of the docstring with a regex.
3. Anchored if any docstring token matches any called name — on the full dotted
   string or on the final segment, in either direction.

`parse` in prose anchors a call to `mod.parse`. `mod.parse` in prose anchors a
call to `parse`. Requiring the author to reproduce the import path would be
scoring on typing, not on knowledge.

That is the entire test. It is satisfiable **only** by naming a real symbol the
unit really calls, and unsatisfiable by any amount of well-formed English.

## What it is forbidden to do

It never scores on docstring length, word count, sentence count, or the presence
of words like `pins`, `contract`, `defect`, `regression`, `invariant`. If a
future maintainer finds themselves matching prose here, they have rebuilt the
thing this pack exists to delete.

## Bad

```python
def test_roster_excludes_the_self_branch(tmp_path):
    """The self branch is never watched - self-completions are meaningless."""
    registry = _build_registry(tmp_path)
    assert "devpulse" not in baseline._read_registry_branches(registry)
```

A good sentence. It explains *why*. But a reader cannot get from the docstring to
the code: neither `_build_registry` nor `_read_registry_branches` is named, so
when `_read_registry_branches` is renamed and this test starts covering something
else, the docstring still reads true. Species `UNANCHORED_DOCSTRING`.

```python
def test_it_works(tmp_path):
    build(tmp_path)
    assert (tmp_path / "out").exists()
```

Species `NO_DOCSTRING` — there is nothing to anchor.

## Good

```python
def test_read_registry_branches_excludes_the_self_branch(tmp_path):
    """_read_registry_branches never returns the calling branch - a
    self-completion is meaningless and the watchdog would loop on it."""
    registry = _build_registry(tmp_path)
    assert "devpulse" not in baseline._read_registry_branches(registry)
```

Same sentence, one symbol added. Now the docstring and the code are welded: the
day the function is renamed, the docstring is visibly stale.

## The known false-flag family

**A unit that makes no call at all can never be anchored.** A test whose subject
is a constant (`assert mod.LIMIT == 10`), an operator, or an attribute read has
no `ast.Call` for this rule to find, so its docstring is unanchorable no matter
how well it is written. Every such unit is flagged. That is a family of false
flags, not a discovery, and the row carries `call_count` so a reader can filter
them in one pass.

**The reverse error exists too.** A docstring word that happens to equal a called
name — `raises`, `open`, `list`, `format`, `next` — anchors a unit by accident.
This rule is a floor, never a ceiling.

## Scoring — reporting, not scoring

`SCORED = False`. This ships the ruling as accepted: structural, with an unscored
report-line fallback.

The full violation list and every check line are still returned. The reported
score is **100**, and the measured number travels in `measured_score` and in a
check line that names the fallback:

```
Docstring anchor scoring: REPORTING, NOT SCORING - this rule is structural and
unscored while SCORED is False, so the reported score is 100. The measured score
is 10 (498/554 units flagged); the findings above are complete
```

A fallback that silently discarded its own measurement would be indistinguishable
from a rule that found nothing — and the whole point of the shadow cycle is to
see what the rule *would* have said before anything is gated on it.

A project with no test files reports `not_applicable` rather than zero. Zero tests
measured is not zero quality found.

*Design: DPLAN-0323 / FPLAN-0469*
