# Quality and proof

**Branch** memory · **Code** `tests/`, `tests/parked/`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

How this branch's suite is judged, and the three rulings that shaped what "green" is allowed to
mean here. No test count is written down in this document on purpose: the number is one
`python -m pytest` away and a written one rots within the day.

---

## How the suite is run

Two invocation shapes, and both are expected to agree: from the repo root in the CI shape
(`python -m pytest src/aipass/memory/tests --rootdir=. -n auto --dist loadscope`, or
`python -m pytest src/aipass/memory -c pyproject.toml --rootdir=. -q`) and from this directory
(`python -m pytest tests -n auto`). A reading taken from only one of them has not been taken.

**The xfail is deliberate.**
`test_trinity_push.py::TestThePushedFileIsCanonical::test_a_pushed_branch_satisfies_the_trinity_checker`
scores a push with @seedgo's checker, whose todos-tab mirror (DPLAN-0345 row 6) has not landed, and
asserts strictly once it does ([todos_v2_shape_contract.md](todos_v2_shape_contract.md) §8). The same
test has played this role before: it read red on this tree before seedgo's byte-match mirror of the
`draft to N` tab landed, and green after (DPLAN-0342).

**Every skip names its reason.** What skips at import is what is left of the parked
symbolic-fragments tier — `test_symbolic_extras.py` and its embedder `test_vector.py`, see
`tests/parked/symbolic_20260814/`. One further skip appears only on a fresh clone: the health test
that reads this branch's real `.trinity/` files, which are gitignored (`tests/test_health.py`, "no
live .trinity files in this checkout"). A skip that names its reason is honest; a pass that needed
this machine is not.

**Two different counts exist, deliberately, and neither substitutes for the other.**
`grep -c 'def test_'` over `tests/test_*.py` counts the test functions **on disk**. Some of those
live in modules that call `pytest.skip(allow_module_level=True)` at import, so pytest never collects
them individually — they surface as one skip each. The rest expand through
`@pytest.mark.parametrize` into more **collected** cases than there are functions. Both numbers are
true: seedgo's `readme` rule counts the functions on disk, a green board counts the cases that
execute. Quoting one where the other is meant is how a README ends up arguing with its own audit.

**Files have left this tree on purpose, and that moves both numbers.** The DPLAN-0323 seal of
2026-09-07 archived the three parked symbolic test files (below) and `tests/test_json_handler.py`,
whose six shim-pin tests now run once for **every** branch inside seedgo's
`test_json_handler_contract.py` — a per-branch contract is the right home for a shim every branch
carries. FPLAN-0492 wave 6 added the other direction the same week: four exit-code pins in
`test_contracts.py` and two known-migration-backup pins in `test_trinity_push.py`. A count that moved
is not the same thing as coverage that moved, which is why each of those is written down as a file
and a reason rather than as a delta.

**Carried forward from the 2026-08-27 trinity-push build and never re-measured since:** 10 mutations
were run against the push lane, and **all 10 bit**. It is marked as carried forward rather than
restated as fresh, because a mutation run nobody repeated is evidence about the code as it stood that
night.

---

## Seedgo

The audit is `drone @seedgo audit aipass @memory`, `apps/` only. Re-run 2026-09-13 after the
DPLAN-0342 draft-target change: **100% on all 47 scored categories, 0 type errors.** That is 46
standards plus diagnostics, matching CI's `EXPECTED_STANDARDS = 47` — seedgo's `host_portability`
landed 2026-09-12 (FPLAN-0554). The 2026-09-07 reading was 46, one fewer than 09-05's 47 because
`test_quality` (v4) retired from the pack that night. A count drift the README once carried for an
hour after the tests moved (`Readme` 90) was cleared by re-measuring, not by bypass.

The detail below is from the 2026-08-27 marker-7 run and is kept as the record of how those findings
were cleared, not as a fresh measurement.

Two findings that build itself introduced were fixed, not bypassed: extracting
`_handle_rollover_verb()` out of `rollover.handle_command()` moved the no-args gate behind a
delegation (`introspection` 85%, and the checker was right — the entry seam should say for itself
that a bare `rollover` introspects), and adding the renamed verb to the top-level `elif` chain pushed
it to depth 5 (`deep_nesting`); the chain is now flat `if`/`return`, one arm per command.

The four findings the first audit raised on the new files were fixed rather than bypassed: report
rendering moved out of the module into `handlers/templates/push_report.py` (modules do no direct file
I/O), `json_handler` logging added to both new handlers, and the `unused_function` hit on
`is_canonical()` was cleared by giving it a real caller — the guard that measures the push's own
session note against the same gate everything else was pruned against.

The `--json` lane added exactly one rule (`json_flag.py` / `json_structure`), a verbatim mirror of the
`help_flags.py` rule for its sibling predicate. The `cli` bypass it first appeared to need was
**not** taken: `console.print(payload, markup=False, soft_wrap=True, highlight=False)` emits
byte-exact JSON through the shared console, so no Rich bypass is required to serve a machine.

**Bypass registry.** Counted 2026-09-05: **114** rules across **40 distinct files** in
`.seedgo/bypass.json` (its own `last_updated` read `2026-08-31` at that reading), of which **41 point
at 12 files that are no longer in the tree** — parked on
08-14 / 08-18 (`symbolic/*.py` ×6, `vector/embedder.py`, `storage/chroma.py`,
`search/vector_search.py`, `learnings/manager.py`) and on 08-27 with the retired template lane
(`templates/differ.py`, `templates/pusher.py`). One duplicate `(file, standard)` pair as well —
`learnings/manager.py` / `architecture`, twice. This superseded the 08-25 reading of 37 rules across
10 files, which was correct when taken and drifted with the template-lane retirement. The rules are
inert — a bypass for an absent file suppresses nothing — but the registry is a record of a tree that
stopped existing. Cleanup is an open item; see [known_issues.md](known_issues.md).

---

## A park in the disposal zone is not a park

The owner's ruling of 2026-08-18, fleet-wide: `.archive/` is always ignored, no
exceptions, and it is his disposal zone — cleaned without warning. Both of this
branch's parks lived there. `test_symbolic_parked.py` had nine pins asserting the
parked implementation was still on disk, and they had been green on every dev
machine and red on every fresh clone since the doctrine landed: 11 failures per
CI run, `missing from the park: handlers/chroma_client.py`.

The pins were not wrong about preservation. They were asking a question that
cannot detect the failure: **asserting a file exists cannot tell a tracked home
from a local one.** Both parks moved to `tests/parked/`, byte-identical (verified
by sha256 before and after), and a new pin asserts the *home* instead — no
component of the park's path may be `.archive`.

Two things the move surfaced that the ruling did not mention:

- **`(disabled)` does not stop pytest.** The suffix is the house convention for
  code that is present but must not run, and it does disable dotted-path import
  — `test_storage(disabled)` is not a valid identifier. But
  `test_storage(disabled).py` still matches pytest's default `test_*.py` glob,
  and four of the archived files in `unwired_handlers_20260813/` are the tests
  that covered handlers which left the tree. First landing: **66 failed, 39
  errors**, all of them parked tests running against absent code. The barrier is
  a `conftest.py` in `tests/parked/` — deliberately *not* a `norecursedirs` line
  in this branch's `pytest.ini`, because CI runs the whole repo from its root
  where the root config is in force and this branch's ini is never read. A
  conftest is loaded from its own directory whatever the rootdir, which is the
  only property that holds on the lane that broke. Pinned by a real collection
  run in a subprocess; emptying the conftest turns it red.
- **"Archived not deleted" was quietly false for the second park.** Nothing
  pinned `unwired_handlers_20260813/`, so CI never complained — but the README
  claim that 105 tests were preserved alongside their code was true only of this
  machine. It moved too.

The `recovery_*` snapshots stay in `.archive/`. They are not parks and are meant
to be disposable, which is what that directory is now for.

---

## A suite that needs this machine is not a suite

PR #734, on 2026-08-17, ran this branch's tests on a fresh ubuntu runner for the
first time (an unrelated `httpx` fix stopped killing whole suites at collection).
156 of the repo's 165 CI failures were mine, identical on 3.11/3.12/3.13 —
deterministic, not flake. Every one of them was the suite depending on state that
exists only where AIPass has already run.

Four species, all fixed by making the fixtures mint their own state:

1. **The fixture copied the live operator config.** `memory.config.json` lives
   under `memory_json/custom_config/` and is gitignored — present on every dev
   machine, absent on a clone. 77 setup errors. The config is now built from
   `config_loader.DEFAULT_CONFIG` (the in-tree regeneration seed) and written by
   the real `_write_config_file`, so the fixture cannot drift from the shape the
   engine produces, and a hand-formatted copy cannot make the byte-identity
   tests assert against the test file's formatting instead of the writer's.
2. **The verbs resolve branches through `AIPASS_REGISTRY.json`**, also
   machine-managed and gitignored. Every branch-addressed test got
   `Unknown branch: @memory`. The registry is now minted in `tmp_path`, and
   **both** doors are shut: `detector._REPO_ROOT` *and*
   `_find_caller_registries`, which otherwise walks up from the caller's CWD and
   quietly finds the fleet's own registry whenever the suite runs inside a
   checkout. A test pins that the reachable registry holds exactly the three
   minted branches.
3. **Rich width is an environment variable.** Refusal sentences carry a tmp
   path; under an xdist worker that path is long enough that an 80-column
   console folds a newline *into* the sentence. Green on a wide terminal, red on
   a runner with none. `COLUMNS` was the old defence and it is still the
   environment deciding — both shared consoles are now pinned via `_width`
   (not the public `width` setter, which monkeypatch would restore by writing
   back the number it read, leaving the shared object pinned for the next
   suite). Long path assertions additionally compare whitespace-free, the only
   form that survives a fold landing mid-token. Removing both defences at
   `COLUMNS=40` turns 33 tests red — 29 more than CI had reached.
4. **A MagicMock standing in for a package has no `__path__`.**
   `test_rollover.py` mocks `handlers.cli` and registered only `help_flags`; a
   `json_flag` import added on 08-16 then resolved out of `sys.modules` **by
   accident**, because some earlier test in the same process had imported the
   real one. On a worker running that file first, all 18 tests in it died at
   import. Now both submodules are imported and registered, and a test reads
   `rollover.py`'s own import lines so the *next* submodule added to that
   package fails here instead of on a runner three days later.

Verified three ways: the branch suite as usual, the repo-root
`-n auto --dist loadscope` invocation, and a fresh-runner simulation — a pytest
plugin that makes `os.stat` and `open()` raise `FileNotFoundError` for exactly
the gitignored paths a clone does not carry, so nothing on this machine is moved
aside. Under the strongest combination (fresh-clone simulation, repo root, 8
workers, loadscope) the suite passed, carrying one extra skip: the health test
that deliberately reads real `.trinity/` files, and it says so out loud.

---

## Dead code, archived not deleted

Three handler files had no caller, found 2026-08-13: `learnings/manager.py` (superseded by the
rollover extractor), `search/vector_search.py` and `storage/chroma.py` (both
in-process ChromaDB paths, superseded by `chroma_subprocess.py`). All three moved
to `tests/parked/unwired_handlers_20260813/` together with the 105 tests that covered
them — tests over unreachable code report coverage that does not exist.

`chroma.py` was **not** in the original finding; it surfaced only after
`vector_search.py`, its sole referencer, was archived. Two sibling files look
equally unreferenced and are load-bearing: `chroma_subprocess.py` and
`embed_subprocess.py` are executed as *scripts* by path in memory's `.venv`, never
imported. Disposition here is per-file and measured — repo-wide grep, dynamic
`importlib` check, and a path-invocation check — never "the checker said
unreferenced". See that directory's README for the full method.

---

## Related

- [known_issues.md](known_issues.md) — what is still open, with the measurement behind each one
- [vector_search.md](vector_search.md) — the subprocess tier the parked in-process paths were replaced by
- [trinity_push.md](trinity_push.md) — the lane whose proof-before-prune law the push tests pin
