# platform_oracle — is the verdict about the code, or about the host?

> `sorted()` did not save you. `sorted()` over **Path objects** uses
> `PurePath.__lt__`, which is case-sensitive on POSIX and case-folded under
> ntpath. The list is deterministic on each host and a *different* deterministic
> list on the other one.

**Scope:** `branch_level` · **Severity:** advisory · **Species:** `LISTING_ORDER`,
`MODE_INJECTOR` *(scored)* · `OSERROR_ATTRIBUTE`, `UNRESOLVED_TMP_PATH`,
`SHALLOW_SANDBOX` *(nominated, never scored)*

---

## Why this rule exists

A CI matrix ran Linux and Windows for the first time after eight waves of test
work had landed overnight on Linux-only verification. Nobody wrote a bad test.
Everybody wrote down the only platform they could see.

The pack had no rule for this. Four existing rules mention platform divergence and
**three of them mention it only to acquit it** — `self_skip` acquits a genuine
platform skip, `empty_parametrize` acquits a matrix that empties on one leg,
`assertion_shape` acquits a separator comparison. `posix_literal` is the only one
that convicts, and it is scoped to exactly one syntactic shape: a rooted literal
put through a resolver. Everything between those two positions was unowned.

This rule is that gap. It asks about the **outcome**, not about the spelling: not
"does this line contain a slash" but "would this assertion have gone the other way
on the other runner".

## The split: two score, three do not

| species | scored? | why |
| --- | --- | --- |
| `LISTING_ORDER` | **yes** | the flagged shape is wrong on one host, always |
| `MODE_INJECTOR` | **yes** | the flagged shape silently stops testing anything |
| `OSERROR_ATTRIBUTE` | no | an assertion on `.errno` is often perfectly right |
| `UNRESOLVED_TMP_PATH` | no | usually right on the host that wrote it, often right everywhere |
| `SHALLOW_SANDBOX` | no | only a defect when production walks up, which no reader here can see |

**An arm that would convict correct tests must not move a number.** The first time
a fleet watches its score drop for a test that was right, the score stops being
read — and then the arms that *are* sound stop being read with it. So the three
nominate-only species get their own check line, `passed: True`, and are excluded
from both the score and the failing count. They are places to look. They are not
verdicts.

## `LISTING_ORDER` — scored

@skills, `tests/test_template.py:167-173`:

```python
files = sorted(p for p in target.rglob("*") if p.is_file())
assert [f.name for f in files] == ["SKILL.md", "handler.py"]     # flagged
```

The list is **sorted and still platform-ordered**. `sorted()` over Paths compares
`PurePath` objects: POSIX gives `["SKILL.md", "handler.py"]` because `'S' < 'h'`;
Windows folds the case, reads `handler.py < skill.md`, and hands back the other
order. Production laid down the same two files on both. The pin is what disagreed.

Both flavours ship in the standard library on every host, so the divergence is
runnable here, on Linux, in two lines — and `templates/platform_oracle_test.py`
runs it:

```python
[p.name for p in sorted(PurePosixPath(n)   for n in names)]   # ['SKILL.md', 'handler.py']
[p.name for p in sorted(PureWindowsPath(n) for n in names)]   # ['handler.py', 'SKILL.md']
```

**Flagged:** an ordered `==` against a list literal whose other side was built from
`iterdir`, `listdir`, `glob`, `rglob`, `scandir` or `os.walk` — with or without
`sorted()` applied to Paths, and through one hop of name binding, because the row
above binds `files` on one line and compares it on the next.

**Never flagged:**

- `sorted(..., key=...)` — any key at all. Supplying one displaces
  `PurePath.__lt__` entirely, which is the whole hazard. The spellings that appear
  in real cures are `key=str` and `key=lambda p: p.name`.
- `sorted()` applied to **strings** rather than Paths — `sorted(p.name for p in
  d.glob(...))` never touches Path comparison and is byte order everywhere.
- the comparison is `set(...)`, `frozenset(...)` or `Counter(...)` on either side.
- `sorted` textually on **both** sides. On the literal side alone it does not
  acquit: the listing side is still in Path order and the two agree on exactly one
  platform.
- a **one-element** literal — order cannot differ.

## `MODE_INJECTOR` — scored

@hooks, `tests/test_telegram_response.py:1706-1723`. Note that it is **not**
`chmod` — it is purer than that:

```python
impossible = Path("/dev/null/impossible/log.jsonl")
with patch(LOGGER_PATCH) as mock_logger, patch(f"{MOD}._get_delivery_log", return_value=impossible):
    _write_delivery_log(...)

assert mock_logger.warning.call_count == 1                       # flagged
```

The failure is injected by the **filesystem's mood** rather than at a seam.
Windows ignores POSIX mode bits for the owner and has no `/dev/null` directory
semantics, so the write succeeds, nothing raises, nothing is reported, and the
must-warn assertion sees **zero** calls — while `_write_delivery_log` is behaving
perfectly.

The contrast is in the same class, three rows above it. `test_mismatch_reports_culprit`,
`test_failed_chunk_culprit` and their sibling all take `tmp_path` and hand
`_get_delivery_log` a **real, writable file inside it**:

```python
log_path = tmp_path / "delivery.jsonl"
with patch(LOGGER_PATCH), patch(f"{MOD}._get_delivery_log", return_value=log_path):
    _write_delivery_log(...)                                     # NOT flagged
```

Nothing there depends on the OS refusing anything. Those three are green on every
host. The flagged row is the one that asked the kernel for a favour.

**Flagged:** `os.chmod` / `Path.chmod` to a mode with no owner-write bit (`0o444`,
`0o555`, `0o400`, `0o000`), a `stat.S_IREAD` / `S_IRUSR`-style expression carrying
no `W` name, **or** a POSIX device-path literal (`/dev/null/...`, `/dev/full`,
`/proc/...`, `/sys/...`) — where the unit then asserts on the failure, either
through `pytest.raises(OSError)` and kin or through a mock's
`warning` / `error` / `call_count`.

`/dev/null` **exactly** is not flagged. As a sink it is correct, common and
portable through `os.devnull`. It is `/dev/null/something` — null used as a
*directory* — that provokes the `ENOTDIR` this species is about.

**Never flagged, without exception:** the failure is injected at a **patched
seam** — `patch` on `open`, `write_text`, `write_bytes`, `os.replace`, `Path.open`,
or any patch carrying an `OSError` `side_effect`. That **is** the cure this rule
teaches, so an arm that could flag it would be teaching a rewrite into something
it also flags.

## `OSERROR_ATTRIBUTE` — nominated, not scored

@drone, `tests/test_executor.py:205`:

```python
cause = exc_info.value.__cause__
assert isinstance(cause, FileNotFoundError)
assert cause.filename == "this_executable_does_not_exist_xyz"    # nominated
```

Windows raises `FileNotFoundError` from a subprocess launch with `filename=None`
(`[WinError 2] The system cannot find the file specified`); POSIX fills it in. The
**production claim holds on both** — it is chained, and it is a `FileNotFoundError`.
The pin over-reached by one line.

**Nominated:** an assertion on `.filename`, `.filename2`, `.strerror`, `.errno` or
`.winerror` of an exception captured by `pytest.raises` or an `except` clause, and
through one hop, because `cause = exc_info.value.__cause__` puts it in a second
name.

**Never flagged: an exception the unit built itself.** The attribute is only
OS-filled when the OS filled it. A stand-in the unit installs and raises from —
`raise OSError(errno.EXDEV, "invalid cross-device link")` inside a monkeypatched
`os.replace` — puts the test's **own literal** in `.errno`, and a literal is the
same number on every platform because the test wrote it down. `side_effect=OSError(...)`
on a patch is the same thing spelled shorter.

**Why it does not score:** the checker cannot see where the exception came from. An
`.errno` off a plain `open()` is filled on both platforms and asserting on it is
fine. That the exception came from a `subprocess` / `os.exec*` / `shutil.which`
launch — the case where Windows leaves `.filename` empty — is not provable from
the unit, and a rule that cannot tell the two apart has no business moving a
number.

**Cure:** assert the **type** and the **chain**, and if the name matters assert it
in **our own wrapper's message**, which we fill on every platform. That is
strictly stronger: it still says which program was missing, and it now fails if we
ever stop naming it.

## `UNRESOLVED_TMP_PATH` — nominated, not scored

@spawn, `tests/test_contracts.py:103`:

```python
with tempfile.TemporaryDirectory() as td:
    target = Path(td) / "init_test"
    result = _spawn_agent(str(target))
    assert Path(result["path"]) == target                        # nominated
```

`tmp_path` on the Windows runner is an 8.3 **short name** (`RUNNER~1`) until
something resolves it — and the code under test resolves what it returns. `Path ==
Path` compares **text**. Both sides name one directory; neither side is the same
string.

**Nominated:** an `==` between a temp-directory-derived path (`tmp_path`,
`tmpdir`, `tempfile.TemporaryDirectory`, `mkdtemp`) and a value the code under
test handed back, where **neither** side carries `.resolve()`, `.absolute()`,
`os.path.realpath` or `samefile`.

"Handed back" is **positive evidence**, not the absence of sandbox evidence: the
produced side has to trace, through the unit's own bindings, to a call the subject
made — tuple unpack included, because `email, cwd = guard_mod._resolve_caller()`
binds both names to the call — or to a parameter of a stand-in the unit installs
and production then calls, which is production handing the value in.

**Never flagged: two things the TEST built.** `found == parent_dir`, where the test
walked `[current, *current.parents]` itself and compared its own answer against its
own directory, cannot drift on an 8.3 short name — neither side ever went through
production's resolver, so both are the same unresolved text.

**Never flagged:** a unit that rebinds the sandbox through a resolver anywhere —
`tmp_path = tmp_path.resolve()` as the first line cures every comparison below it.

**Why it does not score:** on the host that wrote it the comparison is true, and on
most hosts it stays true. It is a latent text-versus-identity confusion, not a
defect, until a runner hands out two spellings.

**Cure:** resolve both sides, or `os.path.samefile`. The template line is
`tmp_path = tmp_path.resolve()` as the first line of the unit.

## `SHALLOW_SANDBOX` — nominated, not scored

@prax, `tests/test_operations.py:1620-1652` (two rows):

```python
with _patch("pathlib.Path.cwd", return_value=tmp_path):
    mod._handle_refresh([])

assert f"[dim]Refreshing {tmp_path.name.upper()} dashboard...[/dim]" in printed   # nominated
```

On the Windows leg this rendered `RUNNERADMIN` instead of the sandbox's name.

### What is proven, and what is not

This is the species whose cause the dossier could **not** prove end to end, and
saying which half is which is part of the finding.

**Proven, from the code, read end to end:**

- `prax/apps/modules/dashboard.py` **never calls `Path.home()` anywhere**. The only
  expression in that module that can print `RUNNERADMIN` is
  `branch_path.name.upper()` at line 280.
- **The patch is not the failure.** `patch("pathlib.Path.cwd", ...)` sets the
  attribute on the `pathlib.Path` **class**; the module holds that same class
  object and resolves `.cwd` off it at call time, and `importlib.reload` rebinds to
  the same object. So `Path.cwd()` **did** return `tmp_path`.
- What follows is that the `while` loop at `dashboard.py:272` walked **out** of the
  sandbox and broke at an ancestor named `runneradmin` holding
  `DASHBOARD.local.json` or `.aipass`.
- Green on Linux and red on Windows follows from **one asymmetry**: Windows TEMP
  lives under the user profile, so `tmp_path` **has** home as an ancestor there;
  `/tmp` does not.
- The fleet's own code manufactures a home `.aipass` in **five places** — @daemon's
  `timer_install`, @hooks' `trust_registry` among them — so a marked ancestor under
  the profile is not a hypothetical.

**Not proven, and it needs a probe from the Windows job to settle:** *which marker
file existed on that runner at that moment, and which step created it.*

### The class

**The seam is one level too shallow — `cwd` is sealed, its ancestors are not.**

**Nominated:** a unit that patches a `cwd` / root seam (`pathlib.Path.cwd`,
`os.getcwd`, `os.chdir` onto a temp directory) **and** then asserts on a rendered
**name** or path component derived from it, with nothing rooting the ancestors.

**Never flagged:** a unit that furnishes its sandbox — any `mkdir`, `touch`,
`write_text` or `write_bytes` landing inside it. A test that lays its own marker
down is not relying on what an ancestor happens to hold.

**Why it does not score:** whether an upward walk exists at all is a fact about
production, and this checker reads test units. A sealed `cwd` beside a rendered
name is perfectly correct code whenever the module does not walk.

**Cure:** patch a seam **the module owns, by the module's own name** —
`dashboard.current_dir()`, or better, the seam that produces the *answer* —
rather than a stdlib classmethod one level below it. If the walk itself is the
claim, root the sandbox first.

## The class this rule's own template was, for one day

**A proof of a divergence must MANUFACTURE both halves. Asking the host for one
of them is the species, not the demonstration of it.**

The teaching template shipped with this rule, `templates/platform_oracle_test.py`,
went red on the Windows leg of run 34290037771 - the first completed matrix run
carrying the rule. Three failures and two errors, all of one shape: the proofs of
the WRONG shapes ran the wrong shape against the real machine and asserted the
POSIX half of the answer.

| what it did | what Windows did |
| --- | --- |
| wrote to `/dev/null/impossible/log.jsonl` and expected ENOTDIR | created it - an ordinary path under the current drive - so the write succeeded, nothing was reported, and the proof's `== 1` read zero |
| ran the sealed-cwd walk against the real ancestors of `tmp_path` | `tmp_path` lives under the user profile there; an ancestor carried the marker and answered first |
| symlinked `RUNNER~1` to a long directory to make two spellings of one path | `FileExistsError [WinError 183]` - the 8.3 generator had already minted `RUNNER~1` for that same directory one line earlier, and symlinks need privilege besides |

The third is worth reading twice: the platform collided with the fixture by
proving the fixture's own thesis.

The cures are the ones this rule teaches, applied to itself: two injected writers
instead of one real filesystem; a `WALK_CEILING` that declares where the built
world ends, so the walk cannot reach the host; and a dot-dot spelling, which is
two strings for one directory on every platform and needs no filesystem feature.
Verified on Linux against a Windows-SHAPED world - a marked ancestor above the
sandbox makes the unbounded walk answer `runneradmin` and the bounded one answer
`sandbox` - and then re-run on the matrix.

**The gap this exposes, stated plainly.** This pack's corpus is `tests/`. The
templates live under `apps/`, so no rule in this pack has ever audited them, and
a copy of the six templates into a `tests/` tree scores 100 on six rules and 80
on `no_oracle` (8 rows, all the delegation limit that rule publishes). Even
audited, no arm here would have caught it: the defect lived in helper functions
and a fixture, and this rule does not follow calls. What caught it was the
Windows leg RUNNING the template through the suite pin that runs every template.
That is the honest order of proof for this whole subject - a static rule narrows
the search, and only the other runner returns a verdict.

## How to fix a flag

`templates/platform_oracle_test.py` runs all five cures against both halves of the
matrix, on this machine, and shows a wrong shape that passes here beside the right
one:

1. **assert the set, or sort the strings** — not the Paths
2. **inject at the seam** — `side_effect=OSError`, never the kernel's mood
3. **assert the type and the chain**, and put the name in **our** wrapper
4. **resolve both sides**, or `os.path.samefile`
5. **patch a seam the module owns**, and root the sandbox if the walk is the claim
6. **run the module's EXISTING pins under every lane you add** — not just the new
   cases. @devpulse's FPLAN-0554 cure proved its macOS lane on Linux by forcing
   `sys.platform`, and the old pins in the same files were never run under it:
   `test_wire_never_spawns_anything` patched `Popen` to explode on ANY spawn, the
   new darwin lane's `lsof` probe went through `Popen`, and macOS went red
   (34704362515). The same cure, never run under win32, turned 25 Windows units
   red (34704362507). A lane you add is a lane every pin in the file now lives on.

## Three divergences a fake cannot manufacture

Absent binaries and absent `/proc` can be stood in for on Linux. These cannot,
because the difference is in the kernel's semantics, not in what is installed:

- **A read on a pid after the call that ends it.** @api's
  `test_a_real_child_ends_up_owning_the_terminal` read `os.getpgid(pid)` after
  `session.hangup()`. Linux keeps a hung-up child's pgid readable as a zombie
  until the parent reaps; macOS answers `ESRCH` (34707099650). The tell: a
  `finally` or teardown that hangs up or waits on the child, before an assertion
  that still names its pid (`getpgid`, `getsid`, `kill(pid, 0)`, `/proc/<pid>`).
  Cure: read while the subject is alive, hold the values, assert on the held values.
- **`os.kill(pid, 0)` on Windows terminates the target.** It is a liveness probe on
  POSIX. A test that forces `sys.platform = "darwin"` on a Windows host and reaches
  it kills the process it meant to ask about.
- **A working directory inside a tree being deleted.** Linux removes a directory
  that is some process's cwd; Windows refuses with `WinError 32` (drone
  `test_rm.py`, 34686193857, ruled a test defect and cured at d2f359d3). Step out
  of the tree before deleting it, as a Windows user would have to.

## What this rule cannot see

Every limit runs toward **fewer** flags, which is the safe direction for a rule
that accuses.

- **It does not follow calls.** A `chmod` applied by a helper, or a listing done in
  a fixture, is invisible. So is the seam patch that would have acquitted it.
- **It cannot see where an exception came from.** That is the stated reason
  `OSERROR_ATTRIBUTE` nominates instead of scoring.
- **It reads one hop and stops.** `files = sorted(...rglob(...))` then a comparison
  naming `files` is resolved, because the row this rule was written for is spelled
  exactly that way. A value travelling through a second function, a module-level
  constant or another file is not followed.
- **It never asks the running machine.** `"/dev/full"` is judged as text; Path
  ordering is judged from the shape of the comparison. A portability rule that
  consulted the host would report a different standard on every leg of the matrix,
  which is the exact defect it exists to find — and it is why these findings mean
  the same thing run from either runner.
- **A flagged site may be perfectly correct** for a reason a human can see and this
  reader cannot. It nominates. A human decides.

## Where the species came from

Two sources, and they are not the same kind of thing. The **rows** came from the
first full Linux/Windows matrix run of 2026-09-08 (Linux 34269557965, Windows
34269557911) — real red, in this fleet, with a nodeid. The **names** were checked
against @devpulse's cross-platform defect catalog, which is prior art from outside
this repo, so that a species this fleet met once is spelled the way the literature
already spells it:

| catalog row | what it names | here |
| --- | --- | --- |
| 1 | slash literals in expected paths | `posix_literal`, arms 1–2 |
| 3 | comparing sorted `Path` objects — `PurePath.__lt__` is case-folding on Windows | `LISTING_ORDER` |
| 7 | `tmp_path` handed back through an 8.3 short name, so the string differs from the sandbox that made it | `UNRESOLVED_TMP_PATH` |
| 10 | `chmod` as a failure injector — the mode is advisory for an administrator on Windows | `MODE_INJECTOR` |
| 20 | asserting on `FileNotFoundError.filename` and kin — the OS fills those fields | `OSERROR_ATTRIBUTE` |
| 32 | `patch("pathlib.Path.cwd")` | **not a species here** |

Row 32 is cited and **not** used. @devpulse offered it as class G's proven cause
and then withdrew it in the same thread — *"your code reading of class G beats the
catalog... That is measured; row 32 is a possibility from the literature."* The
reading that stands is from the code: the patch DID take, and the walk at
`dashboard.py:272` climbed out of the sandbox to an ancestor named `runneradmin`.
A catalog row is a name to check a finding against, never evidence that a finding
happened.

## What it measured

Across **18 branches with a `.trinity`**, 17,833 test units:

| | rows |
| --- | --- |
| `LISTING_ORDER` (scored) | 1 — @skills |
| `MODE_INJECTOR` (scored) | 1 — @hooks |
| `OSERROR_ATTRIBUTE` | 2 — @api, @drone |
| `UNRESOLVED_TMP_PATH` | 83 |
| `SHALLOW_SANDBOX` | 2 — @prax |
| **total nominated** | **87** |

**Two scored rows fleet-wide**, and both are the rows this rule was written for.

`LISTING_ORDER` measured **5 before it was narrowed**. Four of those five were
@memory sorting `.name` off a glob — string sort, byte order, portable — and two of
those four are that branch's own case-folding pins, which handle both hosts in an
`if len(entries) == 1:` and are the most portable code in the corpus. Narrowing the
arm to sorts that actually touch `PurePath.__lt__` took it from 5 to 1.

`SHALLOW_SANDBOX` measured **0 before the alias fix**. The two rows it exists for
are written `from unittest.mock import patch as _patch` — the units already take a
`monkeypatch` fixture and the author wanted the two spellings to read apart — so a
reader keyed on the exact name `patch` saw no seal at all and called both rows
clean. After: 2, and they are the two.

`UNRESOLVED_TMP_PATH` measured **2,832 rows across five branches** on its first
run, and the number is what exposed the defect: the arm's helper answers `""` for
"not this species", and the caller tested it against `None`. Every comparison in
every unit was therefore a row, with an empty description where the produced side
should have been. A rule reporting half the fleet is a rule nobody opens twice.
Fixed, the same five branches report **35**.

`UNRESOLVED_TMP_PATH` was then **classified row by row**, because 84 of 87
nominations is a number worth doubting before it is reported. Of the 84: **82**
trace to a call the subject made, **1** is a parameter production hands to a spy,
and **1** is a path the test built through its own `parents` loop. Requiring
positive evidence removed exactly that one — a parked, disabled file under
@memory — and cost no true row. **84 → 83.**

`MODE_INJECTOR` had a **hole in its own headline spelling**, found while its pins
were being written and cured the same afternoon: the mode reader collected bare
names and dotted CALL targets and no plain attribute, so `stat.S_IREAD |
stat.S_IRGRP` arrived as the single name `stat` and came back clean, while the
bare `S_IREAD | S_IRGRP` scored 0 — two units differing in nothing but a module
prefix, one flagged and one not, with the dotted form the one printed above as the
shape this arm flags. Cured with a reader of its own so the seven other callers of
the shared name-walker did not move. Fleet rows after the cure: **still 1** — the
hole cost no branch a number, and it is pinned in both spellings so it cannot
reopen.

`OSERROR_ATTRIBUTE` measured **4**, and two of them were artefacts: @spawn's and
@seedgo's atomic-write retry pins each install a stand-in that raises
`OSError(errno.EXDEV, ...)` and then assert on `.errno` — the test's own literal,
portable by construction. Acquitting a unit that manufactures its own OS error
took the arm from **4 → 2**, and the two that remain (@api's `os.fstat` on a
closed descriptor, @drone's subprocess launch) both capture an exception the host
raised.

## Scoring

Units not flagged by a **scoring** species, over total units, counted **per unit**:
a unit carrying both scoring species is one unit a reader has to go and look at,
not two. Nominated units are deduped separately and appear in their own line — a
unit can be in both, because the second line is not a penalty.

**Advisory**: it reports a number and never fails a board.

A project with no test files reports `not_applicable` rather than zero — zero tests
measured is not zero quality found. A project whose test files are present but
unparseable says so explicitly, and is never reported as a project without tests.

*Design: DPLAN-0323 · built from the first Linux/Windows matrix run, 2026-09-08*
