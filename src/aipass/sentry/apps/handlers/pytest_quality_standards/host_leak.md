# host_leak — is the fake world faked all the way?

> A test that pretends to be somewhere else must MANUFACTURE the whole of that
> elsewhere. The moment a faked world takes one value from the host it is really
> running on, the fake is half real — and the real half is the half that differs
> between runners.

**Scope:** `branch_level` · **Severity:** advisory · **Species:**
`FAKE_PLATFORM_HOST_TEXT` *(nominated, never scored)*

---

## Why this rule exists

@ai_mail, `tests/test_wake.py::test_get_pid_cwd_darwin`, Windows run
**35058244702**:

```python
monkeypatch.setattr("sys.platform", "darwin")
target = str(tmp_path / "project")

class FakeResult:
    returncode = 0
    stdout = f"p100\nn{target}\n"            # flagged

monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeResult())
assert _get_pid_cwd("100") == target
```

The parser under test accepts exactly one grammar:

```python
for line in result.stdout.strip().split("\n"):
    if line.startswith("n/"):                # wake.py:424 — POSIX, and only POSIX
        return line[1:]
```

On the Windows runner `tmp_path` renders `C:\Users\RUNNER~1\...`, so the line the
test wrote was `nC:\Users\...`, the `n/` prefix the parser requires never
appeared, `_get_pid_cwd` answered `None`, and the assertion read `None == a
path`. **The unit could not parse the line the unit itself had written.**

Nothing was wrong with `_get_pid_cwd`. The test declared it was on macOS and then
asked the real machine for half of its own fixture.

## The acquittal, and it sits three lines above the defect

`test_get_pid_cwd_linux` is in the same file, fakes the same oracle, and binds
the identical expression:

```python
monkeypatch.setattr("sys.platform", "linux")
target = str(tmp_path / "project")
monkeypatch.setattr(os, "readlink", lambda p: target)
assert _get_pid_cwd("100") == target         # NOT flagged
```

It is portable on every host. The two units differ in **one** thing:

| | the host path is | production |
| --- | --- | --- |
| `..._linux` | handed to the subject as a **value** | returns it unchanged |
| `..._darwin` | woven into **text**, beside a literal | **parses** the text |

What goes in comes out, in whatever spelling the host uses. The darwin row put
the host inside a string whose literal half was a POSIX grammar.

So this rule does **not** ask "does this unit use `tmp_path` while faking a
platform". It asks the narrower question: **was a host path woven into composed
text.**

## What is flagged

A unit that does **both**:

1. **Fakes a platform oracle** — `sys.platform`, `platform.system`,
   `platform.machine`, `platform.release`, `platform.platform`,
   `platform.uname`, `os.name` — through `monkeypatch.setattr`, `patch`,
   `patch.object`, `monkeypatch.setitem`, or a decorator on the unit.

   Read as a **suffix**, because the real spellings reach the oracle through the
   module under test: @aipass writes `patch("...provider_wire.os.name", "nt")`
   and @devpulse writes `monkeypatch.setattr(wire.sys, "platform", "darwin")`. A
   reader keyed on the bare dotted name sees neither.

2. **Weaves a host path into composed text** — an f-string, `+`, `%`, or
   `"sep".join(...)` — where the host-derived side traces through the unit's own
   bindings to a temporary directory (`tmp_path`, `tmpdir`,
   `tempfile.TemporaryDirectory`, `mkdtemp`) or to a machine probe (`Path.cwd`,
   `os.getcwd`, `Path.home`, `expanduser`, `which`, `realpath`, `abspath`).

### The literal is the grammar

The composed text must carry a **non-empty string literal** beside the host path.

- `f"n{target}"` is a protocol line with a host path dropped into it. **Flagged.**
- `f"{target}"` is `str(target)` spelled with more characters, and makes no claim
  about shape at all. **Not flagged.**

Requiring the literal is what separates a fake protocol line from a
stringification, and it is the cheapest arm in the rule.

## Never flagged

- **The host path handed over as a value.** `readlink` returning `target`,
  `return_value=tmp_path`, a `Path` passed as an argument. Production hands back
  whatever it was given.
- **A unit that fakes nothing.** 223 units fleet-wide weave a host path into
  text without touching a platform oracle. They are running on the machine they
  describe, and the text is their own. That is not this species and never was.
- **Composition one hop away.** A fixture or helper that builds the string is
  invisible, and so is the platform fake that would have paired with it.

## What it measured

Across **18 branches**, **18,997 test units**, on the tree as it shipped:

| arm | rows | verdict |
| --- | --- | --- |
| platform fake **+ any** host value | 23 | **rejected** — all 23 hand-read, all correct code |
| host path into text, **no** platform fake | 223 | **rejected** — a unit not claiming to be elsewhere may describe its machine |
| **platform fake + host path into TEXT** | **0** | shipped |

Each half is harmless on its own. **Only the pair is the species.**

The 23 rows of the rejected broad arm were hand-read one by one across five
branches — @ai_mail (14), @aipass (3), @trigger (3), @prax (2), @devpulse (1).
Not one is a cross-OS defect. Fourteen of them use `tmp_path` as a **real file
location** the subject opens, which is correct on every host; six hand a path to
the subject and get it back; three inject a fake `msvcrt` and never touch a path
shape at all. An arm that reports 23 correct tests to catch one defect is an arm
nobody opens twice — that is the measured reason it is not the arm that shipped.

The narrow arm reports **zero** rows because the row it exists for was cured
hours before it landed. Its proof is the reconstruction: run it over
`test_get_pid_cwd_darwin` as that unit stood before the cure and it fires; run it
over the sibling `..._linux`, which is still in the tree in exactly that shape,
and it does not; run it over the cured file's 168 units and it does not.

## Why it does not score

Two reasons, and both are measurements rather than taste.

**It has never been observed convicting.** Zero rows means zero live positives,
so the arm's precision against a real hit is unmeasured. One reconstructed unit
proves the arm **fires**; it does not calibrate it. `platform_oracle` states the
commitment this inherits: *an arm that would convict correct tests must not move
a number*, because the first time a fleet watches its score drop for a test that
was right, the score stops being read.

**It cannot see the parser.** Whether a woven host path is a defect is a fact
about **production** — `_get_pid_cwd`'s darwin arm parses and went red, its linux
arm passes the value through and is green — and the two are indistinguishable
from inside the test. A rule that cannot tell them apart has no business moving a
number.

So it publishes its full finding list and the measured number, and reports 100.
**This is a regression guard, not a finder.**

## What this rule cannot see

Every limit runs toward **fewer** flags.

- **It does not follow calls.** A helper that builds the fake string, or a
  fixture that forces the platform, is invisible.
- **It reads the unit's own decorators only.** A class-level or module-level
  mark that applies the fake is not attributed to the units beneath it.
- **It never asks the running machine.** A finding means the same thing from
  either leg of the matrix, which is precisely the property that the defect it
  hunts destroys.
- **A flagged site may be perfectly correct** for a reason a human can see and
  this reader cannot. It nominates. A human decides.

## How to fix a flag

**Fake data is DATA the subject reads, not a directory the host has to own.**

```python
target = str(tmp_path / "project")                          # red on the other runner
target = "/private/var/folders/aipass/pytest-project"       # the cure, as landed
```

The cured unit's docstring says why, in the file, where the next reader will find
it — which is the shape of cure this pack asks for. If the value genuinely has to
be a real directory, then stop faking the platform around it: a unit that needs
the real filesystem is a unit that belongs on the real platform, or on a matrix
leg that runs there.

## Where the species came from

One row, with a nodeid and a run id: @ai_mail's `test_get_pid_cwd_darwin`,
Windows run **35058244702**, 2026-09-15. @devpulse framed the class that night as
*"a test whose expected value comes from the host it happens to run on, inside a
test that is pretending to be somewhere else"* — and that framing is what this
rule narrows, because the broad reading of it measures 23 correct tests and the
narrow reading measures the one that was wrong.

The sibling half of the same framing — a fixture depending on module-level state
another test warms (@memory's push dry-run pins, macOS run 35050261305) — was
measured and **refused**. See the closing section.

## The half that was refused, stated so nobody re-derives it

The other cross-OS red of the same night was @memory's push dry-run: a test
helper built a config without its closed `fields` map, production's
`entry_rules()` fell through to a module-level `_RULES_CACHE`, and the pin passed
or failed on whether an earlier test on the same xdist worker had warmed that
cache from the real config.

**No arm in this pack can see it, and the measurement says why.** The failing
units never name the cache — `_RULES_CACHE` appears in exactly one test unit in
the fleet, and that unit is its *contract* test, which clears it and asserts on
it correctly. What a static reader would have to see instead is the **absence**
of one key from a dict literal three levels deep, and that the absence matters
only because a function in another module, in another branch, has an
`if isinstance(fields, dict) and fields:` early return above a cache read.

The cheap arm was built and measured anyway: *a test that reads a production
module-level mutable container it never seeds, where a sibling in the same file
does seed it.* Fleet-wide, over 393 such containers in production, it returns
**8 rows** — and all 8 are false. Six are @prax's `mod._tracked`, seeded by a
`_import_tracker` helper that clears it one call hop away; two are @prax's
`relay._buffer`, cleared by an `autouse` fixture. **0 real, 0 recall on the
defect it was built for.** Both halves fail, so it is not here.

*Design: DPLAN-0323 · built from the Windows leg of FPLAN-0593 Phase 5, 2026-09-15*
