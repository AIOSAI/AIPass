# mock_drift — does this patch replace a function, or a whole module?

> Patch the attribute, never the module. A patched module becomes a `MagicMock`,
> and a `MagicMock` answers every attribute access that will ever be made of it —
> including the ones production no longer has.

**Scope:** `branch_level` · **Severity:** advisory · **Reads:** tests *and* production

---

## Why this rule exists

Deleting `auth.validate_credentials` from one branch left **46 of 46 tests
green**. Not one of them failed. Not one of them was ever talking to the
function; they were all talking to a mock that happily invented it.

The shape that did it:

```python
_MOD = "aipass.api.apps.modules.auth_flow"

@patch(f"{_MOD}.auth")          # `auth` is a MODULE, not a function
def test_rejects_a_bad_token(mock_auth):
    mock_auth.validate_credentials.return_value = False
    assert login("bad") is False
```

`mock_auth.validate_credentials` exists because `mock_auth` is a `MagicMock`, and
a `MagicMock` has every attribute you ask it for. Delete the real
`validate_credentials` and the test still passes. Rename it and the test still
passes. The test's subject can be removed from the codebase entirely and the
board stays green.

## The bad shapes

```python
@patch("myproj.services.worker.json_handler")     # target IS a module file
def test_writes_the_row(mock_handler): ...

with patch("myproj.services.json_handler"):       # same, as a context manager
    ...

_MOD = "myproj.services.worker"
@patch(f"{_MOD}.json_handler")                    # f-string, the common spelling
def test_reads_the_row(mock_handler): ...
```

All three replace a whole module. The third is the one that matters most in
practice, because it is how the shape is actually written.

## The good shapes

Patch the attribute, one hop further down:

```python
@patch(f"{_MOD}.json_handler.read_json")
def test_reads_the_row(mock_read): ...
```

Now deleting or renaming `read_json` makes the patch itself raise
`AttributeError`, and the test fails the day the thing it is about disappears —
which is the entire job.

Or keep the module target and make the mock refuse unknown attributes:

```python
@patch(f"{_MOD}.json_handler", autospec=True)
def test_reads_the_row(mock_handler): ...
```

`spec=`, `spec_set=`, `autospec=True` and `new_callable=` all acquit. A specced
mock raises on an attribute the real object does not have, which is precisely the
property whose absence this rule is about.

## What is *not* flagged

```python
@patch(f"{_MOD}.console")     # `console` is a Rich object, not a module
def test_prints_the_table(mock_console): ...
```

To a last-segment match this is identical to the `json_handler` case. It is not
the same thing at all, and flagging it would make the rule a name-collision
guess. So the checker reads what the parent file actually imports: `console` is
bound from a library, `json_handler` is bound from a file in this project. Only
the second is a module patch.

A target that resolves to no file in the project is also left alone. The rule
reports what it can resolve and stays quiet about the rest.

## How the target is resolved

By **file**, never by import. This checker does not run the project it measures —
a checker that imported a stranger's test tree would execute it, which is the
failure the whole pack refuses. So a dotted target is a module when it matches
the path of a `.py` file the corpus parsed (`a/b/c.py` or `a/b/c/__init__.py`,
matched on any suffix of the path, because a test patches `mypkg.apps.thing` and
not a path relative to the project root), or when the file named by its parent
segment binds that last segment to a module by `import`.

That is strictly weaker than an import, and the weakness is the point.

## What this rule does not claim

- **A module created at runtime is invisible.** Nothing here executes.
- **Class-level decorators are not read.** `@patch(...)` on a `class Test...:`
  reaches every method in it; this checker reads each method's own decorators and
  body. Stated rather than hidden, because a reader who knows the shape exists
  will otherwise assume it was measured.
- **A computed target is never flagged.** F-strings resolve only when every
  interpolation is a module-level string constant.
- **`spec=` is taken at face value.** A `spec` pointed at the wrong object is
  still a lie, and nothing static can see that.

Every one of those is a finding that does not happen. The bias runs toward
**clean**, which is the direction nobody notices — so it is written down here.

## It reads production, so it says what it could not read

This is the only check in the pack that parses production code, and that gives it
a way to be quietly wrong: a production file that will not parse contributes no
module path and no import binding, so a real module patch inside it resolves to
nothing and is never flagged.

So every result carries a `Production readable` line when anything was unreadable.
A hole and an unread file look identical from the outside, and only the check
itself is in a position to tell them apart.

## Scoring

Units that patch attributes rather than modules, over total units. Deduped **per
unit**: a test with four module patches is one place a reader has to go and look
at, and counting findings instead would let a single sloppy test drive a small
project's score below zero. A score that can go negative is one nobody believes
twice.

**Advisory**: it reports a number and never fails a board. A project with no test
files reports `not_applicable` rather than zero — zero tests measured is not zero
quality found.

*Design: DPLAN-0323 / FPLAN-0469*
