[← Back to Flow](../README.md)

# Location Discovery — handlers/repo_root.py

The one location answer for the branch, and the cross-platform test worlds that keep it honest.

---

**Nothing in flow reads the process working directory to find itself.** One
module answers both location questions, and every caller routes through it.

| Function | Answers | Guard it carries |
|----------|---------|------------------|
| `module_file(__file__)` | where is *this module* | `.resolve()` attempted, falls back to the absolute spelling |
| `find_repo_root(start=None)` | which repo root is this | falls back to `SOURCE_ROOT`, **never** `Path.cwd()` |
| `exists_exactly(path)` | is this filename spelled exactly so | lists the parent; `exists()` alone folds case |
| `exactly_named(paths, suffix)` | post-filter for a cased glob | a glob is case-blind on Windows/macOS |

`ntpath.realpath` reads `os.getcwd()` **unconditionally** — before it checks
whether the path is even absolute, where `posixpath` only reads it for a
relative one — and `Path.resolve()` routes through it. So on Windows a
module-level `Path(__file__).resolve()` is an import-time working-directory
dependency: a process whose cwd is gone cannot import the module, and guarding
inside the module's functions changes nothing.

A `Path.cwd()` fallback for the repo root is wrong twice: it crashes when the
cwd is gone, and when it does not crash it is a *guess*. Writers that build
`.ai_central/PLANS.central.json` and the `.backup/processed_plans` path would
resolve against whatever directory the caller's shell happened to be in.

**Two `Path.cwd()` reads remain, and both are correct.**
`project_scope.caller_cwd()` and `resolve_location._get_caller_cwd()` ask
*where did the caller stand* — a location, observed — and fall back to the
process directory only when `AIPASS_CALLER_CWD` is absent. They are named in
`tests/test_import_dead_cwd.py` so the ban can never delete a right answer, and
the exemption is keyed on **(file, function)**, not on the name alone.

Enforced by `tests/test_import_dead_cwd.py`: two injected worlds with their own
liveness controls, an AST ban, **and** a behavioural sibling that reaches the
caller-is-None branch by calling the guard directly from a `python -c` child
under a realpath denial. Each catches what the other cannot — the ban names the
offending line anywhere in the tree with no subprocess, the behavioural pin
proves the cure in the world it was built for.

### The bare-checkout world is a tested world

`AIPASS_REGISTRY.json` is **gitignored and machine-local**, so a dev box and a CI
runner disagree about whether `find_repo_root` takes its fallback. That is a
whole second world flow's tests must pass in.

The fallback logs `repo_root_fallback` through `json_handler.log_operation`, and
six modules take the walk while **loading**. On a bare checkout that import-time
diagnostic would land inside whichever test window triggers the first import.

`handlers/json/json_handler.py` is the fleet **shim**: it binds
`aipass.prax.json_handler`'s callables and adds nothing (byte-identical in every
branch, seedgo accepts it by hash). `repo_root._record_fallback` resolves
`json_handler.log_operation` as a module attribute at **call** time, so the
autouse `mock_json_handler` spy intercepts it. Containment is the autouse
`mock_infrastructure`, which sets `AIPASS_TEST_LOG_DIR`: the service recomputes
its directory on every call, so a fixture that patches names cannot keep writes
out of `flow_json/`.

`tests/conftest.py` **pre-imports all six module-level callers**, settling the
walk before any test window exists on every machine. The list is guarded by
`TestThePreImportListIsComplete`, which measures the callers off the tree by
parse and compares them against what conftest actually imports — neither side
hand-copied, because a hand-written list is where an undercount hides.

### Rules for a cross-platform instrument

1. **Emulate both platforms or neither.** A table with one emulated row and one
   bare row is host-dependent in the half nobody thought about — "no emulation"
   reads as posix only while the host is posix.
2. **Build an emulation from the dialect module by name** (`posixpath`,
   `ntpath`), never from `os.path`, which *is* the host.
3. **When a probe asks "did my patch reach X", let X have captured a sentinel.**
   Otherwise the original's own platform behaviour answers the question: on nt
   `ntpath.realpath` reads `os.getcwd` unconditionally, so *raised* stops
   meaning *reached*.
4. **An instrument's inputs are behaviour too.** A probe path built from `os.sep`
   or `pathlib.__file__` is the runner's: `\definitely\not\here` is relative to
   `posixpath`, which then reads the cwd. Each host publishes its own
   dialect-absolute literal, pinned with `isabs` from the dialect module by name.
   The table is not symmetric: `posixpath` refuses an nt literal, while `ntpath`
   *accepts* a posix one as drive-relative, so an nt probe path must carry a
   drive.
5. **The probe path is a published literal.** Anything computed from the running
   host — `os.sep`, `sys.executable`, `__file__` — is refused: the source is
   parsed and a non-`Constant` right-hand side is refused by name.
6. **Vary the runner as a set, not one fake.** A single fake cannot arm on the
   host it imitates: on Windows a Windows-shaped fake installs the same values,
   so the control that requires faked and unfaked runs to differ never arms.
   `RUNNERS` carries a posix-shaped and a windows-shaped runner; every direction
   runs under both and the verdict must not move. Each fake overrides **every**
   host read a probe makes, pinned per attribute. A row that cannot arm here
   reports **CHANGED / ALREADY-with-the-reason /
   UNAVAILABLE-with-the-child's-own-reason**; it never passes quietly and never
   fails on someone else's platform.

The litmus that finds rules 1 to 3: run each probe under the *opposite*
platform's emulation and require the verdict not to move.
`TestTheWorldArmsOnAPreCapturedAccessor` runs it on every direction, with a
control pinning that the two emulated hosts are genuinely different worlds — two
identical hosts would pass the litmus for free.

### A sentinel cannot arm an eagerness pin

A sentinel is stale-proof by construction, so a lazy wrapper *around* the
sentinel returns exactly what an eager capture of it returns. An identity check
cannot be satisfied by accident, but it **goes dark when the thing whose
identity you are checking cannot differ.** The durable form is a difference you
*construct*: two distinguishable sentinels and a source name rebound after the
class body runs. An eager capture answers `CAPTURED`, a lazy one follows the
name and answers `MOVED` — return-value, with no filesystem, cwd or path dialect
anywhere in the question.

### An injected world has to ARM, and the arming is version-shaped

The dead-cwd pins install their world by patching `os.path.realpath` in a
subprocess. On **Python 3.10 that patch reaches nothing**: `pathlib` still has
`_NormalAccessor`, whose `realpath = staticmethod(os.path.realpath)` takes its
copy when `pathlib` is first imported, and `Path.resolve` reads it as
`self._accessor.realpath(self, strict=strict)`. Patching the module attribute
afterwards rebinds a name nothing reads again. 3.11 removed the accessor and
calls `os.path.realpath` at use.

Both worlds therefore end in `_ACCESSOR_CURE`, which patches the accessor as a
`staticmethod` behind a `hasattr` — order-independent on 3.10, inert on 3.11+.
A plain function would arrive **bound** and eat the path into `self`.
`TestTheWorldArmsOnAPreCapturedAccessor` **rebuilds 3.10's construction
locally** and pins both directions — bare module patch → `ACCESSOR_DIES: NO`,
plus the cure → `ACCESSOR_DIES: YES` — with the three traps that make the shape
vacuously green (lazy capture, class-level read, relative probe path) pinned as
their own controls.

---
