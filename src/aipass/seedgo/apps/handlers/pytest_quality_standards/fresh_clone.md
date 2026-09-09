# fresh_clone — would this test pass on a machine that has only what the repo ships?

> A test that **builds** the world it reads has one oracle. A test that **asks the
> host** for the world has as many oracles as there are hosts, and proves none of
> them.

**Scope:** `branch_level` · **Severity:** advisory
**Species:** `IGNORED_PATH` · `BOTH_WORLDS` · `DERIVED_EXPECTED`

---

## Where this rule came from

**2026-09-08.** CI ran on a **fresh clone** for the first time after eight waves of
test work had landed overnight against Linux-only verification. Two rows went red.
Neither was a bug in the code it covered: in both, the **expected value came from
state a clone does not have**.

Both were `self_skip` cures. A skip had stood in front of a test that reads *this*
machine; the cure removed the skip, correctly; and the assertion underneath it
turned out to depend on the machine. The cure was right. What it uncovered had
been hidden, not absent.

### Row 1 — `ai_mail/tests/test_cross_project_bridge.py:634`

```python
def test_the_live_fleet_still_resolves_its_four_residents(self):
    projects_tree = reg.find_repo_root() / reg.RESIDENT_PROJECTS_DIR
    live = reg.get_resident_branches()
    if projects_tree.is_dir():
        assert set(live) == {"@baud", "@earmark", "@finch", "@aipass_site"}, sorted(live)
    else:
        assert live == {}, "no projects/ tree on this machine — nothing may resolve"
```

The `else` arm is there **for CI**. It never runs in CI. `.gitignore` line 178 is
`projects/*` and line 179 is `!projects/README.md`, so a fresh clone **has** a
`projects/` directory — the tracked README lives in it — and **none** of the four
resident repos. CI took the first arm, found nothing, and went red on the line
written to protect it.

**The same file gets it right at line 626**, twelve lines up:

```python
def test_a_passport_cannot_add_a_branch_no_registry_lists(self, tmp_path):
    stray = tmp_path / "projects" / "ghost" / "src" / "ghost" / ".trinity"
    stray.mkdir(parents=True)
    ...
    assert reg.get_resident_branches(tmp_path) == {}
```

Same resolver. **One argument.** The world it reads is the world it built two
lines up, so the answer is the same on every machine that will ever run it. The
red one calls the same resolver with **zero** arguments and lets the host answer.
That contrast is this whole rule, in one file.

### Row 2 — `daemon/tests/test_memory_health.py:617`

```python
class TestRealTrinityFiles:
    BRANCH_ROOT = Path(__file__).resolve().parents[1]        # line 592

    def test_real_branch_reports_no_structure_issues(self) -> None:
        result = mh.get_memory_health_status(str(self.BRANCH_ROOT), "DAEMON")
        assert sorted(result["structure_checks"]) == [
            ".trinity/local.json",
            ".trinity/observations.json",
        ]
```

`.gitignore` line 28 is `.trinity/`. A fresh clone has no memory files; the
producer builds that dict **conditionally on `exists()`**, so on a clone the dict
is empty and the pinned list is a list of two things that are not there.

Two **green** siblings in the same class carry an existence guard and
`pytest.skip`. The red one does not — and that is why the skip-guarded shape is
acquitted here rather than convicted twice (see below).

## The three species

### `IGNORED_PATH` — a path the repo refuses to ship

```python
def test_original_data_files_gone(self):
    daemon_root = Path(__file__).resolve().parents[1]
    assert not (daemon_root / "daemon_json" / "schedule.json").exists()   # flagged
```

**This species is about a proof that evaporates, not about a test that breaks.**
`**/*_json/` is ignored, so a clone has nothing there — and the assertion above
*cannot go red on a clone*. It stays green, forever, having stopped checking
anything, and nobody finds out. A row that reads the machine and goes red is at
least loud. A row that reads the machine and asserts an **absence** goes quiet
instead: on the developer's box it is a real regression guard, and on every clone
and every CI leg after that it is a line that runs and proves nothing.

Three of the surviving fleet rows are exactly that shape — @daemon above, @memory
asserting `not (_MEMORY_ROOT / ".archive" / ...).exists()`, @prax asserting
`not (real_tree / "seam_probe_config.json").exists()` under `prax_json/`. All
three are correct, useful tests **here**. The rule names them so that "here" is a
decision rather than an accident.

The path has to be **reached on the filesystem** — `exists`, `is_dir`, `iterdir`,
`glob`, `read_text`, `open`, `stat`, `os.listdir` — not merely spelled. A bare
`".trinity/local.json"` sitting in an *expected-value list* is what a producer
**returned**, not a directory this unit opened. Reading spellings instead of
reaches convicted eleven correct @ai_mail units on the first run.

### `BOTH_WORLDS` — an oracle that is a runtime `if` on the machine

```python
if projects_tree.is_dir():
    assert set(live) == {...}          # flagged: asserts in both arms
else:
    assert live == {}
```

Two assertions, two different claims, and whichever arm this host selects is the
only one anybody ever runs. The other is prose. This is the arm that catches
row 1. The probe (`exists` / `is_dir` / `is_file`) must be on a non-`tmp_path`
path, and both arms must assert.

### `DERIVED_EXPECTED` — an expected value copied off one checkout

```python
result = mh.get_memory_health_status(str(self.BRANCH_ROOT), "DAEMON")
assert sorted(result["structure_checks"]) == [".trinity/local.json", ...]   # flagged
```

A machine root — `find_repo_root()`, a climb from `Path(__file__)`, `Path.cwd()`,
or a **module-level or class-level constant** built from one — handed **bare** to
the code under test as the world it should describe, or listed for its contents,
with the answer then compared against a value **spelled out in the file**.

`BRANCH_ROOT` is a *class* attribute, so class-level and module-level assignments
are resolved **one hop** — the same single hop `host_state` uses to read a
`parametrize` list. A reader that only knew module-level names would have called
that unit clean.

**Three words do the work here, and each was bought with a measurement.**

| word | what it excludes | measured cost of not having it |
| --- | --- | --- |
| **bare** | `Path(__file__).parent / "fixtures" / "a.json"` — the repo ships that file | a derived root carrying any literal is not a candidate at all |
| **climb** | `module_file(__file__)` — the test file *is* shipped, it is the thing running | 7 rows across @backup, @commons, @devpulse, all correct code |
| **written down** | `assert root.is_dir()`, `len(hits) == len(set(hits))`, one implementation equals another | 4 families — @drone, @memory, @hooks ×2 — every one green on a clone |

The "written down" requirement is what makes the species name true: this arm is
about an **expected value**, not about a test that hands a root to production and
then asserts a *property* of the answer.

## The ignore list is shipped as a constant

The needles were **derived by reading**
`/home/patrick/Projects/AIPass/.gitignore` line by line — `.trinity/`,
`.ai_mail.local/`, `logs/`, `projects/*`, `**/*_json/`, `DASHBOARD.local.json`,
`.archive/`, `docs.local/`, the `*PLAN-*` prefixes, `*.local.md` — and then
**frozen into the checker**. `.gitignore` is never read at audit time.

That is a deliberate trade. The pack is portable: it lifts onto any Python project
and must not go asking that project's VCS for its configuration — a checker that
read `.gitignore` would behave differently in a worktree, a submodule or an
export, and the pack's one standing promise is *stdlib plus corpus, and nothing
about the audited tree beyond its Python files*.

**The price, stated rather than discovered:** a project with a different ignore
file gets the AIPass-shaped list. It **under-reports** there — a directory that
project ignores and this list does not spell is invisible — and it can
**over-report** a segment another project tracks.

**Reading the file literally is part of that price being honest.** Two candidates
were dropped by checking rather than assuming:

- **`.seedgo`** is not in the ignore file at all, and `git ls-files` shows
  `.seedgo/README.md` and `.seedgo/bypass.json` **tracked**.
- **`.daemon`** is not a directory line. The only `.daemon` entry is the *file*
  `**/.daemon/last_wake_prompt.txt`, and `.daemon/schedule.json` is tracked —
  carrying `.daemon` as a segment convicted @daemon's
  `test_schedule_file_is_a_valid_job` for reading a file the repo ships.

`tools/` and `artifacts/` carry negations of their own and are left out for the
same reason. A rule that invents ignores is worse than one that misses some.

## What is never flagged

These acquittals are the whole difference between a rule and a nuisance.

**A path rooted at `tmp_path`.** `tmp_path`, `tmp_path_factory`, `tmpdir`, a
`TemporaryDirectory`, an `mkdtemp` — directly, or one hop through a name bound
from one by an assignment, a `with ... as`, a `for ... in`, a comprehension **or a
tuple unpack**. `project, reg = _make_project(tmp_path, ...)` binds two names off
one sandbox-rooted call; a reader that only understood a bare `Name` target called
both of them live state (9 rows, @spawn and @memory).

```python
stray = tmp_path / "projects" / "ghost" / ".trinity"     # NOT flagged
```

**A same-file fixture that hands out a sandbox**, to a fixed point over the file's
fixtures. @ai_mail's `hosted_baud` requests `repo_root`, and `repo_root` is the one
that requests `tmp_path`. A single hop called `hosted_baud` live state when it is a
temp directory two frames up (6 rows).

**`temp_test_dir`, carried by name — a named exception with a reason, not a
wildcard.** It is not a pytest builtin. It is the *fleet's own* sandbox, defined in
`seedgo/templates/test_conftest_template.py` as:

```python
@pytest.fixture
def temp_test_dir(tmp_path: Path):
    test_dir = tmp_path / "test_workspace"
    test_dir.mkdir(parents=True, exist_ok=True)
    yield test_dir
```

and copied into branch conftests fleet-wide. A conftest fixture is invisible to
this reader — that limit is published below — so the one name the whole fleet
shares is listed beside `tmp_path`, `tmp_path_factory` and `tmpdir`, and listed
*because* the template that mints it roots it at `tmp_path`. Measured: 1 @drone
row, `test_project_root_message_does_not_claim_a_passport`, which plants its own
registry under that fixture and then asserts the passport is absent from it.

**A nested `def` inside a unit that already roots a sandbox.** A stand-in the test
wrote is the test's own scope, and the values its parameters receive are values the
unit produced — directly, or through the code under test out of data the unit
built:

```python
def test_missing_file_skipped(self, tmp_path):
    branch_dir = tmp_path / "src" / "aipass" / "empty_branch"
    branch_dir.mkdir(parents=True)
    mock_branches = [{"name": "empty_branch", "path": str(branch_dir)}]

    def mock_get_path(branch, mem_type):
        p = Path(branch["path"]) / ".trinity" / f"{mem_type}.json"   # NOT flagged
        return p if p.exists() else None
```

The world is `tmp_path` all the way down; the only thing a static reader could see
was a parameter name. **The gate matters:** a unit that names no sandbox at all
gets no such acquittal, so a nested `def` reading real host state is still a row.
Generous inside one unit is the safe direction — which is why it is spelled as a
gate rather than as a blanket.

**The test builds the tree it then reads.** A `mkdir`, `write_text`, `write_bytes`
or `touch` on a path carrying the same spelling — in the unit, or in a same-file
fixture the unit requests — means the world under the assertion is the world the
test made.

**A `pytest.skip` or `skipif` guarded by an existence check.** That is a
**`self_skip` row** — a test that reads this machine and steps aside when the
machine is not it — and it is that rule's business, not this one's. Convicting it
here would hand a fleet two findings for one defect, and a fleet that gets two
findings for one defect discounts both.

```python
local_file = self.BRANCH_ROOT / ".trinity" / "local.json"
if not local_file.exists():
    pytest.skip("no live .trinity/local.json in this checkout")   # NOT flagged here
```

**A path reached through a negated region.** The root `.gitignore`'s only `!` lines
re-admit `src/aipass/spawn/templates/*/.trinity/**` and its siblings, with a
comment saying why: *a template must ship WHOLE*. A frozen list cannot express a
negation, so the negated region is spelled by the **root's name** instead —
`get_template_dir()`, `self._template()`, `tpl`, one hop (7 @spawn rows). The price
of that: a project whose `templates/` really is ignored gets a hole there.

**A path used only to import or locate the module under test.** `sys.path.insert`,
`spec_from_file_location`, `SourceFileLoader` are excluded by name, and such a path
carries a literal anyway.

## How to fix a flag

**1. Give the reader an argument.** This is the cure for row 1 and it is one
argument wide. A function that takes the world it should read can be asked about
any world, including one a fixture just built.

```python
def test_the_tree_resolves_what_it_holds(tmp_path):
    (tmp_path / "projects" / "baud").mkdir(parents=True)
    ...
    assert set(reg.get_resident_branches(tmp_path)) == {"@baud"}
```

**2. Make the fresh-clone claim against an empty `tmp_path`, as its own test.**
Not in an `else` arm, not in a `skipif`, not in CI — which you cannot read from
here and cannot debug when it disagrees with you.

```python
def test_a_tree_with_no_projects_resolves_nothing(tmp_path):
    """A real claim about the reader: no fallback to a global registry."""
    (tmp_path / "projects").mkdir()          # a clone HAS the directory
    assert reg.get_resident_branches(tmp_path) == {}
```

**3. If the test really must read this machine, `skip` behind an existence
check** — and then it is `self_skip`'s question whether that skip is honest, not
this rule's.

The full pattern, runnable, is `templates/fresh_clone_test.py` in this pack. It
carries the part the sketches above leave out: a `a_fresh_clone_tree()` world where
the directory **exists** and holds only its tracked README, so the `is_dir()` guard
reads TRUE and walks into the arm that expects four residents. That is the
incident, in seven collected units.

## `is_dir()` is not a guard

The most useful sentence on this page. A clone has `projects/`, because
`!projects/README.md` puts it there. A branch that has been checked out and never
run has `.trinity/` absent but `apps/` present. "Does the directory exist" is a
question about **packaging**, and the thing your test depends on is what is
**inside** it. Guard on the content, or build the content.

## What this rule cannot see

Every limit runs toward **fewer** flags, which is the safe direction for a rule
that accuses.

- **It does not read `.gitignore`**, so it cannot know what *this* project
  ignores — see the trade above.
- **It does not follow calls.** A read performed by a helper the unit calls, or by
  a fixture in a **conftest** one directory up, is invisible; so is the build that
  would have acquitted it. @drone's `temp_test_dir` is exactly that shape and is
  reported for it.
- **A path the code under test handed back** — `Path(result["archive_path"])` — is
  not traced to whatever built it. @spawn's birth-receipt row is hermetic under
  `tmp_path` and is reported anyway.
- **One hop of name resolution, never a chain.** `a = ROOT`, `b = a / ".trinity"`
  is followed; a third assignment is not.
- **It cannot run the clone.** Nothing here checks out anything, imports anything,
  or asks the filesystem a question. A rule about what a stranger's machine has
  must not be answered by asking this one. It reads text.
- **A flagged site may be perfectly safe** for a reason a reader can see and this
  checker cannot — a project that ships the directory anyway, a CI stage that
  populates it first. It nominates. A human decides.

## What it measured

At the time of writing, over 18 branches and 17,833 test units: **6 rows
fleet-wide** — @ai_mail 1, @daemon 2, @memory 1, @prax 1, @spawn 1. **Sixteen of
eighteen branches are at 100.**

Two of those six are the rows CI went red on. Three more are the
absence-under-an-ignored-path shape described above, which is a real and distinct
defect. The sixth, @spawn's `test_retire_carries_the_whole_trinity_into_the_archive`,
is a **known false positive of a published limit**: the world under it *is*
`tmp_path`-rooted, but it is reached through `Path(result["archive_path"])` — a
path the code under test handed back — and this rule does not follow a production
return value to whatever built it. It is reported rather than narrowed for,
because narrowing on it would mean guessing what a returned path is rooted at.

The first run of the same corpus, before the acquittals above, produced **41**.
What came off, in order of size:

| narrowing | rows removed | why |
| --- | --- | --- |
| `IGNORED_PATH` must be a filesystem **reach**, not a mention | 11 | `Path("/repo/.../.ai_mail.local/inbox.json")` handed to a *parser* is a string, not a directory |
| a same-file fixture handing out a sandbox, to a fixed point | 6 | `hosted_baud` → `repo_root` → `tmp_path` |
| `DERIVED_EXPECTED` must pin a **written-down** value | 8 | property assertions answer the same on any machine |
| `__file__` must be **climbed** | 7 | `module_file(__file__)` is the running test file |
| the `templates/` negation | 7 | those `.trinity` payloads are tracked on purpose |
| tuple-unpack and `for`-target sandbox binding | 9 | `project, reg = _make_project(tmp_path, ...)` |
| `.daemon` and `.seedgo` dropped from the needle list | 2 | both tracked; checked with `git ls-files`, not assumed |
| a name is only resolved one hop when it holds a **path** | 2 | `result = _run(script, cwd=Path(__file__).parent)` is a `CompletedProcess` |
| `temp_test_dir` listed by name | 1 | the fleet's conftest template roots it at `tmp_path / "test_workspace"` |
| a nested `def`'s parameters, in a unit that roots a sandbox | 1 | `mock_get_path(branch, ...)` closes over a dict built from `tmp_path` |

The two rows the rule was written for are still there, by nodeid, and they are the
two CI went red on.

## Scoring

Units not flagged, over total units, counted **per unit**: a unit carrying two
species is one unit a reader has to go and look at, not two. A per-finding count
lets one path-heavy test push a project below zero, and a score that can go
negative is one nobody believes twice.

**Advisory**: it reports a number and never fails a board.

**Scored from the first run.** No shadow-only pass, no `SCORED=False` — Patrick's
ruling is that a rule which cannot repeat its landing must not need to.

A project with no test files reports `not_applicable` rather than zero — zero tests
measured is not zero quality found. A project whose test files are present but
unparseable says so explicitly, and is never reported as a project without tests.

*Design: DPLAN-0323 · Built from the 2026-09-08 fresh-clone CI reds*
