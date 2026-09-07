# empty_parametrize — the table that vanished at collection time

> A parametrized test over an empty table generates no cases, is marked SKIPPED,
> and the run prints `1 passed, 1 skipped` with exit code 0. The instrument
> checked nothing and reported the same green a clean tree reports.

**Scope:** `branch_level` · **Severity:** advisory · **Ported from:** TAXONOMY section 5 rule 3a

---

## Why this rule exists

```python
@pytest.mark.parametrize("item", collect())
def test_every_found_item_is_valid(item):
    assert item["ok"]
```

If `collect()` returns `[]`, pytest has nothing to generate. The test is skipped
and the summary is green. This was reproduced verbatim before the rule was
written.

Every other reachability question in this pack reads a skip, a guard or a loop
that a reader can find in the source. Here **there is no skip in the source at
all** — pytest manufactures one from an empty sequence. Somebody grepping the
file for `skip` finds nothing, which is what makes this the quietest species of
the family.

## Where it came from

A branch building a content-anchored bypass rule found that its first test file
survived a mutant which blinded the collector to `return []`: the anchor checks
were parametrized over the collector's output, and the whole file came back
`1 passed, 2 skipped`. Their arming probe asserted the raw *input* list was
non-empty — a different question from whether the collector found anything.

They reported it unprompted, with the cure this rule now asks for: recount the
entries **independently**, from the raw data, rather than by calling the function
under judgement.

## The two species

**VANISHING-TABLE** — a computed table in a file with no independent guard:

```python
@pytest.mark.parametrize("rule", load_rules())     # flagged
def test_each_rule_has_an_anchor(rule):
    assert rule.anchor
```

**SHORT-TABLE** — the same table, in a file whose guard only asks *did it find
anything*:

```python
def test_rules_were_found():
    assert len(load_rules()) > 0        # a collector dropping ONE entry passes this
```

An empty run at least looks odd. A run two cases lighter than it should be looks
like a normal run.

## The acquittals matter more than the flags

A literal table cannot be empty, and most of every corpus is literal tables — 312
parametrize sites were measured across one fleet, 217 of them plain literals this
rule never even looks at.

```python
@pytest.mark.parametrize("value", [1, 2, 3])       # never flagged
@pytest.mark.parametrize("hour", range(24))        # never flagged — shorthand, not a query
@pytest.mark.parametrize("world", sorted(WORLDS))  # never flagged when WORLDS is a literal
```

`range`, `sorted`, `list`, `tuple`, `reversed`, `enumerate` and `set` are
unwrapped **one layer**, so `sorted(WORLDS)` is judged on `WORLDS`. One layer
deliberately: following an arbitrary chain would make this an interpreter, and
nothing in this pack runs the subject.

A file that pins an expected **count** is acquitted outright — it has already
done the thing the rule exists to ask for:

```python
def test_all_five_rules_load():
    assert len(load_rules()) == 5
```

## How to fix a flag

```python
def test_the_rule_file_declares_five_rules():
    raw = json.loads(RULES_PATH.read_text())      # the raw data, not the collector
    assert len(raw["rules"]) == 5

def test_the_collector_finds_all_five():
    assert len(load_rules()) == 5
```

The first test is the one that matters. A probe that calls the collector cannot
detect a blinded collector.

## What this rule does not claim

- **It does not claim a flagged table is empty.** A table legitimately empty on
  some machines — a platform sweep with no rows on this OS — is the honest case,
  and no static reader can tell it from the broken one. This tier nominates; an
  execution tier convicts.
- **The guard is matched file-wide and loosely.** Any `len(...)` inside any
  assert counts, which means even `assert len(rows) == 0` acquits the file's
  tables. Both are deliberate errors toward *acquitting*: a false flag on a file
  that already did the work teaches nothing and gets a standard switched off.
- **Class-level parametrize is invisible.** The corpus's units are functions, so
  a mark applied to a whole test class is not read.
- **A class-body constant is not acquitted, and that is a measured false
  positive.** Only module-level assignments enter the safe-name set, so a table
  written as a class attribute beside the tests that use it — `HELP_ARGV = [...]`
  in the class body, `@pytest.mark.parametrize("argv", HELP_ARGV)` on the method —
  is reported as computed although the decorator can see the literal. One live
  site in the fleet is exactly this shape. Widening the safe-name set changes
  what the rule *acquits*, and that half is measured before it moves.
- **One arm decides nothing, and is documented rather than dressed up.** A count
  guard is an assert containing `len(...)`, so a file that pins a count always
  also satisfies the non-empty guard. The skip condition reads `guarded and
  counted` because that states the rule — a file is excused when it has done
  both — but the first operand can never be the deciding one, and no test pins it.

## Scoring

Units with no vanishing table, over total units. **Per unit, not per finding**: a
unit stacking three parametrize decorators is one test somebody has to go and
look at, and counting findings would let it be subtracted three times and report
a negative score.

**Advisory**: it reports a number and never fails a board.

A project with no test files reports `not_applicable` rather than zero. A project
whose only test file is unparseable says so explicitly, and is never reported as
a project without tests.

*Ported from `tests_pytest_standards/empty_parametrize_check.py` · Design: DPLAN-0323 / FPLAN-0469*
