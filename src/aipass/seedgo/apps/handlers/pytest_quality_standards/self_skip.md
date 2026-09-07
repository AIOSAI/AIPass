# self_skip — where does this test's skip condition get its answer from?

> A test that skips itself when the thing it tests changes name has stopped being
> a test. Rename the symbol and it does not fail — it evaporates, and the board
> stays green.

**Scope:** `branch_level` · **Severity:** advisory

---

## Why this rule exists

Renaming one constant in one branch made **75 tests silently vanish**. The run
stayed green. Nothing failed, because nothing ran, and nothing said so.

The shape that did it lived at module level:

```python
import mypkg.storage as storage

if not hasattr(storage, "JSON_DIR"):
    pytest.skip("storage layout changed", allow_module_level=True)


def test_writes_the_row(): ...
def test_reads_the_row(): ...
# ...73 more
```

Rename `JSON_DIR` and the whole file disappears from collection. The suite's
answer to *"should I run?"* came from the very thing whose disappearance it was
written to catch.

## Three provenances, and only one of them is a defect

### The machine — correct code, never flagged

```python
@pytest.mark.skipif(sys.platform == "win32", reason="posix only")
def test_uses_a_fifo(): ...

@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_reads_the_log(): ...
```

`sys.platform`, `sys.version_info`, `os.name`, `os.environ`, `os.getenv`,
`shutil.which`, `platform.system`, `platform.machine`, `find_spec`. A Linux-only
test that skips on Windows is right, and a rule that flagged it would teach
branches to delete their own portability. A machine probe anywhere in the
condition — or anywhere in a helper the condition calls — acquits the whole site.

### The subject — SELF-SKIP and SKIP-ON-DRIFT

```python
@pytest.mark.skipif(not hasattr(registry, "build"), reason="not available")
def test_builds_the_registry(): ...          # SKIP-ON-DRIFT

def test_uses_the_dir():
    if JSON_DIR is None:                      # JSON_DIR imported from the subject
        pytest.skip("no dir")                 # SELF-SKIP
    assert read(JSON_DIR) == {}
```

`hasattr` and `getattr` are the defining shape: the test asks whether the symbol
still exists, so a rename turns a failure into a silence. Reading a name imported
from the code under test is the same defect one step less obvious.

### Nothing — PERMA-SKIP

```python
@pytest.mark.skip(reason="flaky, will fix")
def test_the_important_thing():
    assert everything_works()
```

A test that never runs proves nothing, whatever it asserts. The assertions inside
are a decoration on a green board.

## How to fix a flag

Make the condition read the machine:

```python
# before
@pytest.mark.skipif(not hasattr(mypkg, "FEATURE_X"), reason="not built yet")
def test_feature_x(): ...

# after
@pytest.mark.skipif(sys.platform == "win32", reason="posix only")
def test_feature_x(): ...
```

Or, if the symbol's absence is the thing worth knowing, **assert it** instead of
skipping on it:

```python
def test_the_registry_still_exposes_build():
    assert hasattr(registry, "build"), "the build entry point was renamed or removed"
```

That version fails on the rename. The skip version disappears on it.

## The module scope is measured

`pytest.skip(..., allow_module_level=True)` removes an entire file and belongs to
no test function, so a reader that walked only test functions would miss the most
expensive skip in the catalog — which is exactly the one that took the 75 tests.

Every file therefore carries a `<module>` scope of its own, reported as
`tests/test_thing.py::<module>`, and it is scored like any other scope.

## One hop into a local helper, and no further

```python
def _factory_still_raises():
    return hasattr(factory, "raise_on_unknown")


@pytest.mark.skipif(not _factory_still_raises(), reason="behaviour changed")
def test_rejects_unknown(): ...
```

The provenance is real and it is one function away. The same is true of a
module-level flag whose reasoning lives in the statement that computes it — often
a `for` loop around a `hasattr`, not a bare assignment — so the enclosing
top-level statement is what gets followed.

It stops at one hop on purpose. A rule that chased an arbitrary call graph would
be an interpreter, and an interpreter that runs the subject is the thing this pack
refuses to be.

## It nominates, it does not convict

A suite testing an optional plugin legitimately asks whether the plugin is there,
and at this distance that is indistinguishable from the defect:

```python
@pytest.mark.skipif(not hasattr(mypkg, "redis_backend"), reason="extra not installed")
def test_redis_backend(): ...
```

That is honest code and it will be flagged. The rule names the provenance; a human
decides what it means. Nothing here fails a board.

## What this rule does not claim

- A condition **built at runtime** from a variable it cannot follow is invisible.
- A skip reached through an **unrecognised alias** is invisible.
- `skipif(condition=..., reason=...)` written with the condition as a **keyword**
  is invisible: this reader takes the first positional argument only.
- **Class-level markers** are not read. `@pytest.mark.skipif(...)` on a
  `class Test...:` reaches every method in it; this check reads each method's own
  decorators and body, and the file's module scope, and nothing between them.

Every one of those is a finding that does not happen, so the bias runs toward
**clean** — the direction nobody notices, which is why it is written down here.

## Scoring

Clean scopes over total scopes, where a **scope** is every test unit *plus* every
file's module scope.

The denominator has to include the files, and getting that wrong makes the number
meaningless rather than merely coarse: a module-level skip names a scope that is
not among the units, so dividing by units alone lets the flagged count exceed the
total and the score go **negative** on a small project. Counting each file's
module scope is also the honest reading — a file-wide skip is a separate place
where the same defect lives, and it is the expensive one.

Deduped per scope: three self-skips in one test is one place to go and look.

**Advisory**: it reports a number and never fails a board. A project with no test
files reports `not_applicable` rather than zero — zero tests measured is not zero
quality found.

*Design: DPLAN-0323 / FPLAN-0469*
