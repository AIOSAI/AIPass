# entry_point_diff — has the suite ever said this verb out loud?

> A verb the suite has never once said out loud is a verb nothing covers,
> however green the line-coverage number over the handler behind it. Rename it,
> and every test still passes.

**Scope:** `branch_level` · **Severity:** advisory · **Ported from:** TAXONOMY section 5 rule 10

---

## Why this rule exists

Every other check in this pack reads a test and asks what it proves. This one
reads **production** first.

It enumerates the entry points production *declares* — CLI verbs in a
`COMMANDS`-style tuple, HTTP routes on a decorator — and diffs them against every
string literal in the test corpus. In wave 1 it found **six unexercised HTTP
routes over a 97%-covered handler lane**, and it was the only
security-consequential finding in the sweep. The branch that proposed it
estimated the cost at ten lines of code.

The companion finding is why it matters more than its size suggests: a `daemon`
branch's `install-timer` arm could be renamed and the verb would fall through to
`_uninstall`, stopping the fleet's scheduler, with all 481 tests green.

## What counts as a declaration

```python
COMMANDS = ("status", "install-timer", "uninstall")     # and HANDLED_COMMANDS,
                                                        # VERBS, SUBCOMMANDS

@app.route("/admin/purge")                              # and @get @post @put
def purge():                                            # @patch @delete
    ...                                                 # @websocket
```

The route string is argument 0 — the spelling flask, fastapi, starlette and
aiohttp all share.

## What counts as a mention

The **whole string literal** equalling the verb, anywhere in the test corpus: an
argument, a parametrize entry, a fixture table, a module-level list.

```python
handle("purge-all")                               # mentioned
@pytest.mark.parametrize("verb", ["purge-all"])   # mentioned
VERBS_UNDER_TEST = ["purge-all"]                  # mentioned - module level counts

"A suite covering purge-all end to end."          # NOT mentioned - prose, not the verb
# purge-all is covered by test_x                  # NOT mentioned - a comment is text
```

This is the weakest test of coverage that still means something: a verb passed to
a function that immediately discards it acquits, and the execution tier is where
"mentioned" becomes "exercised".

**It is not a substring search**, and the nominator this was ported from
described it loosely enough to suggest otherwise. A substring search over raw
text is precisely the v4 defect this pack exists to delete — it is what let a
file of pattern strings with no code score 94%, and it would let any branch clear
this rule by writing its verbs into a comment.

So the rule over-*convicts* where the mention is only prose, rather than
over-acquitting where the mention is only a substring. Wrong in the direction
that produces a finding a human dismisses in ten seconds, never in the direction
that produces a green number nobody earned.

## Bad

```python
# apps/modules/inventory.py
COMMANDS = ("test-inventory", "rebuild", "status")

def handle(command, args):
    if command == "test-inventory":
        return _inventory(args)
    ...
```

```python
# tests/test_inventory.py
def test_rebuild_writes_the_rows_file(tmp_path):
    """Rebuild writes rows."""
    assert handle("rebuild", [tmp_path]).ok
```

`"test-inventory"` is declared and no test names it. The handler behind it can be
renamed, misrouted, or deleted, and the suite stays green.

## Good

```python
# tests/test_inventory.py
@pytest.mark.parametrize("verb", ["test-inventory", "rebuild", "status"])
def test_every_declared_verb_routes_somewhere(verb):
    """Every verb in COMMANDS reaches a handler - a fall-through is silent."""
    assert handle(verb, []) is not None
```

One parametrize table names all three, and the diff goes empty.

## What it cannot see

- **A verb named only in prose.** A docstring or comment that talks about
  `purge-all` without ever writing it as a literal reads as an absence. That is
  a false flag, and it is the deliberate direction — see above.
- **A verb assembled at runtime.** `f"{prefix}-install"`, a dict built in a loop,
  a registry filled by a plugin entry-point group. Invisible to a static reader,
  never counted, therefore never flagged — the bias runs toward *fewer* findings.
- **A route reached only through a mounted sub-app.** A known false positive,
  recorded in TAXONOMY.
- **A verb shorter than three characters.** Not measured rather than measured
  badly: a literal match on a two-character string means nothing.

## It reads production, so it publishes its holes

A production file that will not parse declares nothing this rule can read, so
every entry point inside it is a finding that never happens. The unread count is
printed beside the score on **every** return path:

```
Production readable: 2 production file(s) could not be parsed and were NOT read:
apps/modules/broken.py, apps/x.py - an entry point declared inside one of them is
invisible to this rule, so this score is biased toward FEWER findings
```

A hole and an unread file look identical from outside. The difference is the
entire honesty of the claim *"no test mentions it"*.

## Scoring

Declared entry points named by some test, over declared entry points.

**The denominator is entry points, not test units** — a deliberate break from
this rule's siblings. The finding is an *absence*: there is no unit at fault, so
a per-unit score would read 100 on every project forever, and a number that
cannot move says nothing.

**Advisory**: it reports a number and never fails a board. A project with no
tests, or with no declared entry point, reports `not_applicable` rather than
zero — zero measured is not zero found.

## How to fix a flag

Add a test that names the entry point, or delete the entry point. **Nothing is
deleted by this checker**, and nothing should be: an absence of tests is not
evidence the code is dead. That is Law M11, and it exists because acting on a
nomination by deleting is how a coverage tool becomes an outage.

*Design: DPLAN-0323 / FPLAN-0469*
