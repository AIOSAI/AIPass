# posix_literal — a rooted path literal put through a resolver

> `Path("/tmp").resolve()` is `/tmp` on POSIX and `D:\tmp` under ntpath, because a
> rooted literal is *drive-relative* there. The line means a different thing on the
> other half of the matrix, and the assertion underneath it accuses code that is
> working perfectly.

**Scope:** `branch_level` · **Severity:** advisory · **Species:** `POSIX-LITERAL`

---

## Where this rule came from

A windows-setup leg went red on a return-value pin written that same morning to
catch a platform assumption. The pin compared against `RESOLVED: /tmp`. CI handed
it `D:\tmp`.

The test was new, the code it accused was fine, and the author had done nothing
wrong except write down a root. That is the shape this rule looks for.

## What gets flagged

```python
def test_the_root_is_in_the_roster():
    assert Path("/tmp").resolve() in roster          # flagged
```

```python
def test_realpath_normalises():
    assert os.path.realpath("/etc/hosts").startswith("/etc")   # flagged
```

Two arms, and only two:

- a **path constructor** — `Path`, `PurePath`, `PurePosixPath`, `PureWindowsPath`,
  `PosixPath`, `WindowsPath` — over a rooted string literal, with `.resolve()`
  called on the result
- an `os.path`-shaped **resolver function** — `realpath`, `abspath` — handed a
  rooted string literal

A literal is *rooted* when it starts with `/` or `\`, or when it starts with a
drive letter: `C:/tmp`, `C:\tmp`.

## What does not get flagged, and why that matters more

```python
def test_the_branch_resolves():
    assert registry.resolve("/canary", opts) is None   # NOT flagged
```

This is the whole design. Before the rule existed, three shapes were measured over
721 test files and 32,841 assert statements:

| rule | sites | files |
| --- | --- | --- |
| an assert containing a rooted literal | 501 | 112 |
| a rooted literal reaching anything named `resolve`/`realpath`/`abspath` | 10 | 3 |
| **this rule** — the receiver must *be* a path constructor | **4** | **1** |

Six of the middle row's ten sites were `target_module.resolve("@canary", {...})`:
a **branch-name** resolver that happens to share a verb with pathlib, holding a
rooted literal in a dict value it never resolves. A rule keyed on the method
*name* nominates those six forever. A fleet learns to ignore a rule like that
inside a week.

So this one is keyed on the **receiver**, and nominates none of them.

Also not flagged:

```python
def test_relative_fragments_carry_no_claim():
    assert Path("logs").resolve().name == "logs"   # relative — no platform claim

def test_derived_paths_are_fine(tmp_path):
    assert (tmp_path / "a").resolve().exists()     # derived, not written down
```

## It nominates, it does not convict

A test that deliberately exercises POSIX spelling — a fence refusing
`/etc/passwd`, a parser fed a known-rooted input — is a legitimate site, and it
stays. What the flag buys is that the decision gets **made**, rather than
inherited from whichever platform the author happened to be standing on.

## How to fix a flag

Derive the path:

```python
def test_the_root_is_in_the_roster(tmp_path):
    assert tmp_path.resolve() in roster_for(tmp_path)
```

Or state the claim out loud, in both dialects:

```python
@pytest.mark.parametrize("flavour", [PurePosixPath, PureWindowsPath])
def test_the_root_survives_either_dialect(flavour):
    assert flavour("/tmp").parts[0] in ("/", "\\")
```

Or assert on structure rather than on a spelling — `Path.parts`, `.name`,
`.is_absolute()` — none of which spell a separator.

Where the literal **is** the subject, keep it and say so in the docstring. A
rooted literal is drive-relative on Windows, not invalid.

## What it cannot see

Every limit runs toward **fewer** flags, which is the safe direction for a rule
that accuses:

- it reads the **receiver**, so `home = Path("/tmp")` then `home.resolve()` is
  invisible. Following the value through a variable would mean following
  assignments, and the moment it does that it starts nominating the fleet.
- `from os.path import realpath` then `realpath("/tmp")` is invisible: the call
  target is a bare name, and the module gate wants a dotted receiver ending in
  `path`. `import os.path as osp` defeats it the same way.
- it walks **test units**, so a literal resolved in a fixture, a module-level
  constant or a helper is not seen. Nothing here follows a call.
- a rooted literal that is never resolved is not read at all — 501 sites carry
  one, and 497 of them are data.

## What it never asks

The running machine. `"/tmp"` is judged by its first character as *text*, never by
asking this interpreter what it would do with it. A portability rule that
consulted the host would report a different standard on every leg of a matrix —
which is the exact defect it exists to find.

## Scoring

Units with no resolved rooted literal, over total units, counted **per unit**:
four literals in one test is one unit to go and read, not four. A per-finding
count lets one loop-heavy test push a project below zero, and a score that can go
negative is one nobody believes twice.

**Advisory**: it reports a number and never fails a board.

A project with no test files reports `not_applicable` rather than zero. Zero tests
measured is not zero quality found.

*Design: DPLAN-0323 / FPLAN-0469*
