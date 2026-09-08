# posix_literal — a path claim that is only true on one platform

> `Path("/tmp").resolve()` is `/tmp` on POSIX and `D:\tmp` under ntpath, because a
> rooted literal is *drive-relative* there. And in reverse: `str(some_path)` spells
> the separator the **host's** way, so `== "apps/x.py"` on the other side is right
> on exactly one leg of a CI matrix. Either way the line means a different thing on
> the other half, and the assertion underneath it accuses code that is working
> perfectly.

**Scope:** `branch_level` · **Severity:** advisory
**Scoring species:** `POSIX-LITERAL` · `RENDERED-PATH` · `REPR-HAYSTACK`
**Nominate-only species:** `RETURNED-PATH` — reported, never scored

---

## Where this rule came from

A windows-setup leg went red on a return-value pin written that same morning to
catch a platform assumption. The pin compared against `RESOLVED: /tmp`. CI handed
it `D:\tmp`.

The test was new, the code it accused was fine, and the author had done nothing
wrong except write down a root. That is the shape this rule looks for.

## Where the second half came from

**2026-09-08.** A CI matrix ran Linux and Windows together for the first time,
after eight waves of test work had landed overnight on Linux-only verification.
Four rows went red on a separator, and **not one of them held a rooted literal or
a resolver**. They were the mirror image of the two arms above: the code under
test rendered a `Path` to *text*, and the test compared that text with a literal
that hardcodes a forward slash.

| row | shape | lands in |
|---|---|---|
| `test_coverage_arch_checklist.py::TestCheckTemplateBaselineFull::test_template_baseline_missing_file_bypassed` | `assert bypassed[0]["name"] == "File: apps/something.py"` | nominated |
| `test_coverage_arch_checklist.py::TestCheckTemplateBaselineFull::test_template_baseline_missing_dir_bypassed` | `assert dir_checks[0]["name"] == "Dir: apps/handlers/"` | nominated |
| `prax tests/test_discovery.py::TestDiscoverPythonModules::test_returns_dict` | `assert result["gamma"]["relative_path"] == "pkg/gamma.py"` | nominated |
| `trigger tests/test_watchers_log_watcher.py::TestWatcherOnModified::test_a_read_failure_is_reported_and_costs_only_that_event` | `assert str(logs_dir / "app.log") in str(warned.call_args)` | **scored** |

Named by **nodeid**, not by line: the seedgo file gained 28 lines the same
afternoon and the two rows moved from 992/1028 to 1020/1056. A line number is a
fact about a moment; a nodeid is a fact about a test.

The producers are ordinary: `str(item.relative_to(template_path))` at
`architecture_check.py:452`, `str(relative_path)` at prax `scanner.py:57`. `str()`
of a `Path` is the **host's** dialect — `apps/something.py` here,
`apps\something.py` there.

## What gets flagged

### Arms 1 and 2 — `POSIX-LITERAL`

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

### Arm 3, split down the middle — `RENDERED-PATH` (scored) and `RETURNED-PATH` (nominated)

The arm reads an `==`, `!=`, `in`, `not in`, `startswith` or `endswith` where
**one side is a string literal holding a relative filesystem path**. What the
*other* side is decides whether the row moves a number.

**Why the split exists, as a measurement.** The undivided arm's first fleet run
returned **64 rows, 27 of them on seedgo — and most of seedgo's are correct,
portable code.** `corpus.py:202` returns `path.relative_to(root).as_posix()`, so
every test asserting `"tests/test_broken.py" in named[0]["message"]` is reading a
string that is posix on every host, on purpose, forever. Sixteen of those 27 are
in this pack's own `test_pytest_quality_pack.py` alone.

And they are the **same AST shape** as the rows that broke CI. What separates
`result["relative_path"] == "pkg/gamma.py"` (red on Windows) from
`named[0]["message"]` (right everywhere) is entirely off-screen: prax
`scanner.py:57` renders with `str()`, seedgo `corpus.py:202` renders with
`.as_posix()`. No AST reader of the *test* can see that, and this rule does not
read production.

A scoring arm that convicts correct code is how a standard gets switched off —
`assertion_shape.md` says exactly that in its own text. So the arm is split by
what the checker **can** see: *who wrote the rendering down.*

#### `RENDERED-PATH` — scored

The rendering is visible in the unit, over something that looks like a path:

```python
def test_the_relative_path_is_recorded(tmp_path):
    assert str(tmp_path / "pkg" / "gamma.py") == "pkg/gamma.py"   # scored
```

| rendering | read when |
|---|---|
| `str(x)` / `repr(x)` | `x` looks like a path |
| an f-string | some interpolated value looks like a path |
| `"%s" % x` | `x` looks like a path |

The **test** chose the dialect, on the line the reader is looking at. Nothing
off-screen can make it right, so the row moves the number.

"Looks like a path" is a reading of **spelling**, not a type inference: a `Path`
constructor, a `/` join, a `tmp_path`-shaped fixture, a pathlib attribute, or a
name / attribute / key containing `path`, `dir`, `file`, `root`, `src`, `dest`,
`target` or `location`.

#### `RETURNED-PATH` — nominated, never scored

The compared value came **back from the code under test** — a dict subscript, an
attribute, a call result:

```python
def test_the_relative_path_is_recorded(tmp_path):
    assert result["gamma"]["relative_path"] == "pkg/gamma.py"   # nominated
    assert parsed.path == "foo/bar.txt"                          # nominated
    assert ".trinity/local.json" in self._watch_rels(root)       # nominated
```

Whether the producer normalised the separator is unreadable from here. These rows
are reported in **their own check line, with `passed: True`**, and are excluded
from the score and from the failing count. A nomination is a place to look, not a
charge.

**The checker cannot know a returned value came from a Path.** It never claims to.
It reads the accompanying evidence instead, and nominates when **either** holds:

1. the **spelling is path-ish** — `result["relative_path"]`, `entry["path"]`,
   `parsed.path`;
2. or the **unit builds a Path** anywhere in its body — a `Path(...)`, a `/` join,
   a `tmp_path` fixture.

So it fires on `result["path"] == "src/demo/vera"`. It fires on
`bypassed[0]["name"] == "File: apps/something.py"` — the key `"name"` says nothing,
but the unit builds a whole tree under `tmp_path`, and *that* is the evidence. It
does **not** fire on `payload["body"] == "a/b.txt"` inside a unit that never
touches the filesystem. And it **cannot** fire on a dict a helper filled in
another file, because nothing here follows a call.

That is circumstantial evidence, written down as circumstantial evidence — and a
second reason this half does not score.

`str(entry["path"])` is asked for its **written** rendering first: it is both a
subscript and a `str()`, and the `str()` is the honest reading, because the test
put the value through the renderer itself.

### Arm 4 — `REPR-HAYSTACK`

```python
def test_the_failure_names_the_file(tmp_path):
    reported = str(warned.call_args)                       # the haystack
    assert str(logs_dir / "app.log") in reported           # flagged
```

`str(mock.call_args)` renders its arguments through **`repr()`**, and `repr()` of
a Windows path doubles the separator. A needle built correctly still cannot be
found inside that haystack, because the haystack is not the argument — it is a
*rendering* of the argument.

Flagged: `str()`, `repr()` or an f-string over `.call_args`, `.call_args_list`,
`.mock_calls`, `.await_args`, `.await_args_list` or `.method_calls` — directly, or
one hop through a local `name = ...` — used as the haystack of an `in` / `not in`
whose needle is path-ish.

**Cure, and the template line:** assert on `call_args.args[n]` or
`call_args.kwargs` directly. Never on a rendered repr.

```python
# after
assert warned.call_args.args[0] == logs_dir / "app.log"
```

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

## The second measurement — what the new arms cost

The table above is **history**: it is the reading that chose the *receiver* over
the *name*, and it still governs arms 1 and 2. The 2026-09-08 arms were measured
the same way before they landed, over the 18 branches with a `.trinity` directory.

| stage | sites |
|---|---|
| comparisons holding a literal with a slash between two path characters | 353 |
| …of those, with a rendering *or a returned value* on the other side | 155 |
| **arm 3 as it ships** — the literal must also read as a filesystem path | **68** |
| **arm 4 as it ships** — a path needle in a rendered call record | **2** |

The narrowing between 155 and 68 is the load-bearing one. A run of path characters
only counts when it has two segments **and** one of: a trailing slash
(`apps/handlers/`), a second separator (`src/aipass/prax`), or a file extension on
its last segment (`pkg/gamma.py`). The 87 it drops were read one by one:

- a **rooted literal the test wrote down as input** and got back — `/bin/bash`,
  `/usr/local/bin/claude`, `/logs/flow.log`. Much the largest group, and arms 1–2's
  subject, not this one.
- a **fraction or a rate** — `11/10`, `343/300`, `2/2 test scopes`,
  `150 lines/min`, `Log rate exceeds 50/s`.
- **prose that happens to carry a slash** — `Throwaway path (temp/scratchpad)`.
- a **pytest nodeid** (`::`) — pytest spells nodeids posix on every platform, by
  contract, so asserting on one is correct.
- a **name that is not a path** — `anthropic/claude-3.5-sonnet`,
  `citizen/drone-fix`, an scp-style remote, the route `/v1/fleet`. URLs *do* appear
  in this fleet (85 literals carry `://`), which is why `://` and a bare `@` are
  named markers rather than an assumed edge case.
- three **two-segment relative paths with no extension** — `src/daemon`,
  `src/my_agent`, `apps/handlers`. These are real paths and the floor gives them up
  on purpose, because the same floor is what removes the fractions.

Widening the nominate-only half from subscripts to **attributes and call
results** cost **6 rows**, measured: 62 → 68, every one of them unscored.
seedgo +4, drone +1 (`parsed.path == "foo/bar.txt"`), spawn +1
(`baud.relative_path == "src/baud/baud"`). A returned value is a returned value
whichever way the source spells the access; reading only subscripts would have
been a hole with no reason behind it.

### Before and after, per branch

Arms 1–2 find **0 rows fleet-wide** today — the five sites the 2026-09-07 dialect
measurement named have since been cured. Everything below is new, and the split
decides what it costs:

| branch | before | scored | nominated | score |
|---|---|---|---|---|
| seedgo | 0 | 0 | 31 | 100 |
| spawn | 0 | 0 | 14 | 100 |
| daemon | 0 | 0 | 9 | 100 |
| api | 0 | 0 | 6 | 100 |
| drone | 0 | 0 | 4 | 100 |
| prax | 0 | 0 | 3 | 100 |
| trigger | 0 | **2** | 0 | **99** |
| aipass | 0 | 0 | 1 | 100 |
| *the other ten branches* | 0 | 0 | 0 | 100 |

**70 rows, 8 branches. Two of them score.** Seventeen branches stay at 100 and
trigger goes to 99.

`RENDERED-PATH` — the scoring half of arm 3 — finds **zero rows in this fleet**,
and that is said out loud rather than hidden: nobody here writes
`str(p) == "a/b.py"` in a test. The arm is kept because it is the shape the cure
turns into if the cure is done wrong.

The nominate-only half is a **superset** of the shape that broke CI, which is the
point: seedgo's two rows and prax's one are in it, named by nodeid, in a check
line a reader can act on — and they move no number they cannot be defended
against.

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

**`RENDERED-PATH` and `RETURNED-PATH` get the same cure** — which is the other
reason the split costs a reader nothing. Compare Path to Path, or put
`.as_posix()` on both sides:

```python
# before
assert result["relative_path"] == "pkg/gamma.py"

# after — compare paths, not strings
assert Path(result["relative_path"]) == Path("pkg") / "gamma.py"

# or — as_posix() on both sides, saying posix out loud
assert result["relative_path"] == Path("pkg/gamma.py").as_posix()
```

A `RETURNED-PATH` nomination has one extra honest outcome the scored half does
not: **go and read the producer.** If it already ends in `.as_posix()`, the test
is right, and the nomination has cost thirty seconds and bought a fact. That is
the whole reason it does not touch the number.

`.as_posix()`, `os.sep`, `os.path.join`, `os.path.normpath` and `os.fspath` inside
the comparison all acquit the site, because each of them is the cure a flagged
line gets rewritten into. Convicting the cure is the mistake arm 2 already made
once, with `ntpath`, and it is not repeated here.

For a `REPR-HAYSTACK` flag, assert on the argument instead of on a rendering of it:

```python
# before
reported = str(warned.call_args)
assert str(logs_dir / "app.log") in reported

# after
assert warned.call_args.args[0] == logs_dir / "app.log"
```

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

And the 2026-09-08 arms have their own, in the same direction:

- **arm 3 reads one comparison.** A relpath rendered into a variable on one line
  and compared on the next is invisible; nothing here follows an assignment except
  arm 4's single hop.
- **arm 3 cannot see an `.as_posix()` that lives in production.** That is the
  seedgo cluster above: the string really is posix on every host, the test really
  is right, and the evidence is in a file this rule does not open. It is also the
  whole reason the returned half nominates instead of scoring.
- **text that merely *contains* a path is read like text that *is* one.**
  `"   M src/x.py"` — a line of porcelain output — is nominated. Narrowing to
  whole-literal paths would have dropped `"File: apps/something.py"`, which is one
  of the four rows the arm exists for.
- **arm 4 follows a haystack one hop** through a local `name = ...` and no
  further, and reads only `in` / `not in`. A rendered repr compared with `==` is a
  different and much rarer mistake.
- **arm 4 nominates a rendered repr even when the argument was a plain string.**
  `trigger/tests/test_log_watcher.py:1080` sets `event.src_path` to a string and
  would pass on either host. It is the same shape as the row three files over that
  does not, and telling them apart needs the producer.

## What it never asks

The running machine. `"/tmp"` is judged by its first character as *text*, never by
asking this interpreter what it would do with it, and `"pkg/gamma.py"` is judged by
the shape of its characters and not by `os.sep`. A portability rule that consulted
the host would report a different standard on every leg of a matrix — which is the
exact defect it exists to find, and it is also why this rule's own pins can be
written on any host and mean the same thing.

## Scoring

Units with no **scoring** finding, over total units, counted **per unit**: four
literals in one test is one unit to go and read, not four. A per-finding count
lets one loop-heavy test push a project below zero, and a score that can go
negative is one nobody believes twice.

`RETURNED-PATH` is outside the number entirely. It gets its own check line —
`Path provenance nominations` — with `passed: True`, and appears in the result
under `nominations` rather than `violations`. Both lists carry **every line**, not
one row per unit: a reader chasing a separator wants each one, and the dedupe
happens later, where the score is computed.

**Advisory**: it reports a number and never fails a board.

A project with no test files reports `not_applicable` rather than zero. Zero tests
measured is not zero quality found.

*Design: DPLAN-0323 / FPLAN-0469 · arms 3–4 added 2026-09-08 after the first
Linux/Windows CI matrix*
