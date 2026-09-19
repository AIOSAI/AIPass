[← Back to Flow](../README.md)

# Location Discovery — handlers/repo_root.py

The one location answer for the branch, and the cross-platform test worlds that keep it honest. Six structural rules earned from reds that a single-dimension test could not see.

---

**Nothing in flow reads the process working directory to find itself.** One
module answers both location questions, and every caller routes through it.

| Function | Answers | Guard it carries |
|----------|---------|------------------|
| `module_file(__file__)` | where is *this module* | `.resolve()` attempted, falls back to the absolute spelling |
| `find_repo_root(start=None)` | which repo root is this | falls back to `SOURCE_ROOT`, **never** `Path.cwd()` |
| `exists_exactly(path)` | is this filename spelled exactly so | lists the parent; `exists()` alone folds case |
| `exactly_named(paths, suffix)` | post-filter for a cased glob | a glob is case-blind on Windows/macOS |

Built 2026-08-31 (Windows round 4, @memory's finding via @devpulse).
`ntpath.realpath` reads `os.getcwd()` **unconditionally** — before it checks
whether the path is even absolute, where `posixpath` only reads it for a
relative one — and `Path.resolve()` routes through it. So on Windows every
module-level `Path(__file__).resolve()` is an import-time working-directory
dependency: a process whose cwd is gone cannot import the module. Guarding
inside the module's functions changes nothing, because the import died before
any of them existed.

Measured red-first, in a subprocess, before any cure: **61 of 61 flow modules
died on import** in both injected worlds. The count only became true as cures
landed, because the first crash line masks everything under it — 61 → 43 after
the guard, → 0 after the 29 module-level sites. Flow carried:

- **29** `_PKG_ROOT = Path(__file__).resolve().parents[N]` sites — every module,
  nearly every handler
- **7** private `_find_repo_root` copies, each ending `return Path.cwd()`, **6
  of them called at module level**
- **2** `inspect.stack()` calls — the import guard, and `log_operation`'s
  caller detection (which no import probe reaches; it runs at write time)

The `Path.cwd()` fallback carried two defects, and only the loud one was a
crash. The quiet one: cwd is a *guess*. Four of those seven callers are
**writers** — `push_central`/`aggregate_central` build
`.ai_central/PLANS.central.json`, `close_helpers` and `restore_ops` build the
`.backup/processed_plans` path — and on a registry-less checkout (the core
registry is gitignored, so every clean clone and CI runner qualifies) each one
resolved against whatever directory the caller's shell happened to be in. A
`try`/`except` would have fixed the traceback and kept the wrong answer.

**Two `Path.cwd()` reads remain, and both are correct.**
`project_scope.caller_cwd()` and `resolve_location._get_caller_cwd()` ask
*where did the caller stand* — a location, observed — and fall back to the
process directory only when `AIPASS_CALLER_CWD` is absent. They are named in
`tests/test_import_dead_cwd.py` so the ban can never delete a right answer, and
the exemption is keyed on **(file, function)**, not on the name alone.

Enforced by `tests/test_import_dead_cwd.py`: two injected worlds with their own
liveness controls, an AST ban, **and** a behavioural sibling that reaches the
caller-is-None branch by calling the guard directly from a `python -c` child
under a realpath denial. Both instruments are kept: regrowing the deleted walk
kills both, and each catches what the other cannot — the ban names the offending
line anywhere in the tree with no subprocess, the behavioural pin proves the cure
in the world it was built for. (The round-4 guidance said only an AST ban could
watch that branch; @spawn measured the correction — it is unreachable from
*import-shaped* pins, not unreachable.)

### The bare-checkout world is a tested world

`AIPASS_REGISTRY.json` is **gitignored and machine-local**, so a dev box and a CI
runner disagree about whether `find_repo_root` takes its fallback. That is not a
detail — it is a whole second world flow's tests must pass in, and it is where
round 5's CI red came from.

The fallback logs `repo_root_fallback` through `json_handler.log_operation`, and
six modules take the walk while **loading**. On a bare checkout that import-time
diagnostic lands inside whichever test window triggers the first import, where
the autouse `mock_json_handler` counts it — so a test pinning
`assert_called_once` breaks on CI and passes everywhere else.

Still true after the json sweep, verified 2026-09-05. `handlers/json/json_handler.py`
is now the fleet **shim**: it binds `aipass.prax.json_handler`'s callables and adds
nothing (DPLAN-0325 — byte-identical in every branch, seedgo accepts it by hash).
`repo_root._record_fallback` still resolves `json_handler.log_operation` as a module
attribute at **call** time, so the autouse `mock_json_handler` still intercepts it —
measured, not reasoned: patching that name and calling `_record_fallback` directly
records exactly one `repo_root_fallback` call.

What changed is the division of labour in `conftest.py`. `mock_json_handler` is now a
**spy only**, and it steps aside for `tests/test_json_handler.py`, whose whole subject
is that each name IS the service's bound method. Containment moved to the autouse
`mock_infrastructure`, which sets `AIPASS_TEST_LOG_DIR` and measures the sandbox off
the shim: the service recomputes its directory on every call, so a fixture that
patches names could no longer keep writes out of `flow_json/`.

`tests/conftest.py` therefore **pre-imports all six module-level callers**,
settling the walk before any test window exists on every machine. The list is
guarded by `TestThePreImportListIsComplete`, which measures the callers off the
tree by parse and compares them against what conftest actually imports — neither
side hand-copied, because a hand-written list is exactly where an undercount
hides.

Measured, not assumed: with the marker denied and every count-asserting test run
in **full isolation**, **2 of 10** failed. CI had named one.

### An instrument must not import behaviour it is not testing

Round 7's Windows red, and it is the sharper half of the lesson above. The
accessor probes captured the live `os.path.realpath`, then asked *"did a later
patch reach it?"* by denying `os.getcwd` and reading raise/no-raise. That
discriminates on posix, where the captured function ignores the cwd for an
absolute path — so a raise can only mean the patch landed. On nt `os.path` **is**
`ntpath`, and `ntpath.realpath` reads `os.getcwd` unconditionally, so the
**original** raises too and *raised* stops meaning *reached*.

Three rules came out of it (@memory measured the same species on four of their
own reds; each is verified here rather than imported on their word):

1. **Emulate both platforms or neither.** A table with one emulated row and one
   bare row is host-dependent in the half nobody thought about — "no emulation"
   reads as posix only while the host is posix.
2. **Build an emulation from the dialect module by name** (`posixpath`,
   `ntpath`), never from `os.path`, which *is* the host.
3. **When a probe asks "did my patch reach X", let X have captured a sentinel.**
   Otherwise the original's own platform behaviour answers the question.

The litmus that finds all three: run each probe under the *opposite* platform's
emulation and require the verdict not to move. `TestTheWorldArmsOnAPreCapturedAccessor`
runs it on every direction, with a control pinning that the two emulated hosts
are genuinely different worlds — two identical hosts would pass the litmus for
free.

### An instrument's INPUTS are behaviour too

Round 8's Windows red, and it is the round-7 rule one level along. The
emulations were built from `posixpath`/`ntpath` by name and were correct — but
the probe *path* was still built from `os.sep` and `pathlib.__file__`, which are
the **runner's**. On the Windows runner that yields `\definitely\not\here`,
which `posixpath` reads as **relative**; `posixpath.realpath` reads the cwd for a
relative path on every platform, so the posix row convicted for the path's shape
and announced *"the posix emulation is not posix-shaped"* about an emulation that
was doing its job.

Each host now publishes its own dialect-absolute literal, pinned with `isabs`
from the dialect module by name. **The table is not symmetric**, and saying so
matters: `posixpath` refuses an nt literal, while `ntpath` *accepts* a posix one
and treats it as drive-relative — so an nt probe path must carry a drive, and
`isabs` alone is not enough.

The missing instrument was a second dimension. Round 7's litmus varied the
emulated **host**; nothing varied the **runner**. `WINDOWS_RUNNER` fakes exactly
what a probe can read to construct a path — `os.sep`, `os.path`,
`pathlib.__file__` — and every direction must return the same verdict with and
without it. Reverting the dialect-absolute literals reds it on Linux, which is
the point: the failure was otherwise only observable on hardware nobody here has.

### Host == faked is one layer

Round 9, named by @seedgo. Round 8 shipped `WINDOWS_RUNNER`, a fake of everything
a probe can read to build a path. It works on Linux — and it is **dark on the
runner it was written for**. On a Windows host the fake installs Windows-shaped
values over Windows-shaped values, so the faked and unfaked runs are
byte-identical and the control that requires them to *differ* can never arm. A
single fake cannot arm on the host it imitates, for the same reason a
`nt`-emulating world proves nothing on `nt`.

What the campaign reported was that control going dark. The bigger hole was
behind it: the **litmus** was dark too. Round 8's check varied the emulated host
only, so on Windows it measured nothing at all — *a one-dimension litmus is blind
on the host that already IS that dimension.*

The cure is a **set**, not a fake: `RUNNERS` carries a posix-shaped and a
windows-shaped runner, every direction runs under both, and the verdict must not
move. Whichever one matches the host is inert there — and it says so, in
@spawn's three-state shape: **CHANGED / ALREADY-with-the-reason /
UNAVAILABLE-with-the-child's-own-reason.** A row that cannot arm here reports
*why*; it never passes quietly and never fails on someone else's platform. One
pin then simulates *both kinds of host* so the Windows leg is falsifiable from
Linux, forever.

Two rules ride along. Each fake must override **every** host read a probe makes,
pinned per attribute — a partial fake (`os.sep` without `os.path`) survived
otherwise. And the probe path itself must be a **published literal**: anything
computed from the running host — `os.sep`, `sys.executable`, `__file__` — is the
round-8 defect returning under a new spelling, so the source is parsed and a
non-`Constant` right-hand side is refused by name (@trigger's shape, and their
own round-8 red).

### A sentinel cannot arm, so it takes the eagerness pin dark

@trigger's correction, adopted. A sentinel is stale-proof by construction, so a
lazy wrapper *around* the sentinel returns exactly what an eager capture of it
returns — and the behavioural eagerness pin answered the same either way
(measured: that mutation left it green). An identity check cannot be satisfied by
accident, but it **can go dark when the thing whose identity you are checking
stops being able to differ.**

The durable form is a difference you *construct*: two distinguishable sentinels
and a source name rebound after the class body runs. An eager capture answers
`CAPTURED`, a lazy one follows the name and answers `MOVED` — return-value, with
no filesystem, cwd or path dialect anywhere in the question.

### An injected world has to ARM, and the arming is version-shaped

The dead-cwd pins install their world by patching `os.path.realpath` in a
subprocess. On **Python 3.10 that patch reaches nothing**: `pathlib` still has
`_NormalAccessor`, whose `realpath = staticmethod(os.path.realpath)`
(`Lib/pathlib.py:358`) takes its copy when `pathlib` is first imported, and
`Path.resolve` reads it as `self._accessor.realpath(self, strict=strict)`
(`:1077`). Patching the module attribute afterwards rebinds a name nothing will
read again. 3.11 removed the accessor and calls `os.path.realpath` at use —
which is why one CI leg reddened and three stayed green.

Both worlds therefore end in `_ACCESSOR_CURE`, which patches the accessor as a
`staticmethod` behind a `hasattr` — order-independent on 3.10, inert on 3.11+.
A plain function would arrive **bound** and eat the path into `self`.

Because only 3.12 exists on a dev box, that cure would otherwise be a row nobody
here could contradict. So `TestTheWorldArmsOnAPreCapturedAccessor` **rebuilds
3.10's construction locally** and pins both directions — bare module patch →
`ACCESSOR_DIES: NO` (CI's failure, reproduced), plus the cure →
`ACCESSOR_DIES: YES` — with the three traps that make the shape vacuously green
(lazy capture, class-level read, relative probe path) pinned as their own
controls.

---

