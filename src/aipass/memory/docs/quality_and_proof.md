[<- Back to the README](../README.md)

# Quality and proof

**Branch** memory · **Code** `tests/`, `tests/parked/`

How this branch's suite is run and judged. No test count is written down in this document on
purpose: the number is one `python -m pytest` away and a written one rots within the day.

---

## How the suite is run

Two invocation shapes, and both are expected to agree: from the repo root in the CI shape
(`python -m pytest src/aipass/memory/tests --rootdir=. -n auto --dist loadscope`, or
`python -m pytest src/aipass/memory -c pyproject.toml --rootdir=. -q`) and from this directory
(`python -m pytest tests -n auto`). A reading taken from only one of them has not been taken.

**The xfail is conditional.**
`test_trinity_push.py::TestThePushedFileIsCanonical::test_a_pushed_branch_satisfies_the_trinity_checker`
scores a push with @seedgo's checker. While that checker still renders the retired todos tab, the
only miss it allows is the `todos_meta` byte-match, and it xfails; once seedgo's todos-tab mirror
renders the pad tab, it asserts strictly on its own
([todos_v2_shape_contract.md](todos_v2_shape_contract.md)).

**Every skip names its reason.** What skips at import is the parked symbolic-fragments tier:
`test_symbolic_extras.py` and its embedder `test_vector.py`, see `tests/parked/symbolic_20260814/`.
One further skip appears only on a fresh clone: the health test that reads this branch's real
`.trinity/` files, which are gitignored (`tests/test_health.py`, "no live .trinity files in this
checkout"). A skip that names its reason is honest; a pass that needed this machine is not.

**Two different counts exist, deliberately, and neither substitutes for the other.**
`grep -c 'def test_'` over `tests/test_*.py` counts the test functions **on disk**. Some of those
live in modules that call `pytest.skip(allow_module_level=True)` at import, so pytest never collects
them individually; they surface as one skip each. The rest expand through
`@pytest.mark.parametrize` into more **collected** cases than there are functions. Both numbers are
true: seedgo's `readme` rule counts the functions on disk, a green board counts the cases that
execute. Quoting one where the other is meant is how a README ends up arguing with its own audit.

The `.trinity/` json_handler shim pins do not live here: they run once for every branch inside
seedgo's `tests/test_json_handler_contract.py`, because a per-branch contract is the right home for
a shim every branch carries.

---

## Seedgo

The audit is `drone @seedgo audit aipass @memory`, `apps/` only. Findings are fixed, not bypassed,
where the code can carry the fix:

- The entry seam says for itself that a bare `rollover` introspects; the no-args gate is not
  hidden behind a delegation (`introspection`).
- The top-level command chain is flat `if`/`return`, one arm per command (`deep_nesting`).
- Report rendering lives in `handlers/templates/push_report.py`; modules do no direct file I/O.
- `--json` output goes through the shared console as
  `console.print(payload, markup=False, soft_wrap=True, highlight=False)`, which emits byte-exact
  JSON, so no Rich `cli` bypass is needed to serve a machine. The `json_flag.py` rule
  (`json_structure`) mirrors `help_flags.py` for its sibling predicate.

**Bypass registry.** `.seedgo/bypass.json` holds the per-file rules that remain. Every rule names a
file that is in the tree; a bypass for an absent file suppresses nothing and would be dead weight.

---

## A park in the disposal zone is not a park

`.archive/` is always ignored, fleet-wide, and is the owner's disposal zone, cleaned without
warning. Parked code therefore lives in `tests/parked/`, tracked. **Asserting a file exists cannot
tell a tracked home from a local one**, so the park's pin asserts the *home* instead: no component
of the park's path may be `.archive` (`test_symbolic_parked.py`).

- **`(disabled)` does not stop pytest.** The suffix is the house convention for code that is present
  but must not run, and it does disable dotted-path import (`test_storage(disabled)` is not a valid
  identifier). But `test_storage(disabled).py` still matches pytest's default `test_*.py` glob. The
  barrier is a `conftest.py` in `tests/parked/` (`collect_ignore_glob = ["*"]`), deliberately *not*
  a `norecursedirs` line in this branch's `pytest.ini`, because CI runs the whole repo from its root
  where the root config is in force and this branch's ini is never read. A conftest is loaded from
  its own directory whatever the rootdir. Pinned by a real collection run in a subprocess
  (`TestParkIsNeverCollected`); emptying the conftest turns it red.

The `recovery_*` snapshots stay in `.archive/`. They are not parks and are meant to be disposable.

---

## A suite that needs this machine is not a suite

The suite must pass on a fresh clone, where nothing AIPass writes at runtime exists. The fixtures
mint their own state:

1. **Config.** `memory.config.json` lives under `memory_json/custom_config/` and is gitignored. The
   fixture builds it from `config_loader.DEFAULT_CONFIG` (the in-tree regeneration seed) and writes
   it with the real `_write_config_file`, so the fixture cannot drift from the shape the engine
   produces, and the byte-identity tests assert against the writer's formatting, not a hand copy's
   (`tests/support_config_verbs.py`).
2. **Registry.** The verbs resolve branches through `AIPASS_REGISTRY.json`, also machine-managed and
   gitignored. The registry is minted in `tmp_path`, and **both** doors are shut:
   `detector._REPO_ROOT` *and* `_find_caller_registries`, which otherwise walks up from the caller's
   CWD and finds the fleet's own registry whenever the suite runs inside a checkout. A test pins that
   the reachable registry holds exactly the minted branches.
3. **Rich width.** Refusal sentences carry a tmp path; under an xdist worker that path is long
   enough that an unpinned 80-column console folds a newline *into* the sentence. Both shared
   consoles (`display.CONSOLE`, `display.err_console`) are pinned to width 200 by the session-scoped
   autouse fixture `pinned_console_width` in `tests/conftest.py`. Long path assertions additionally
   compare whitespace-free, the only form that survives a fold landing mid-token.
4. **A MagicMock standing in for a package has no `__path__`.** `test_rollover.py` mocks
   `handlers.cli`, so every real submodule the code imports from it (`help_flags`, `json_flag`) is
   imported and registered explicitly, and a test reads `rollover.py`'s own import lines so the
   *next* submodule added to that package fails here instead of resolving out of `sys.modules` by
   accident of test order.

A fresh-clone run carries one extra skip: the health test that deliberately reads real `.trinity/`
files, and it says so out loud.

---

## Dead code, archived not deleted

Handler files with no caller are parked, not deleted: `learnings/manager.py` (superseded by the
rollover extractor), `search/vector_search.py` and `storage/chroma.py` (both in-process ChromaDB
paths, superseded by `chroma_subprocess.py`) sit in `tests/parked/unwired_handlers_20260813/`
together with the tests that covered them. Tests over unreachable code report coverage that does not
exist.

Files that look unreferenced can be load-bearing: `handlers/storage/chroma_subprocess.py` and
`handlers/vector/embed_subprocess.py` are executed as *scripts* by path in memory's `.venv`, never
imported. Disposition is per-file and measured (repo-wide grep, dynamic `importlib` check, and a
path-invocation check), never "the checker said unreferenced". See that directory's README for the
full method.

---

## Related

- [vector_search.md](vector_search.md) — the subprocess tier that replaces the parked in-process paths
- [trinity_push.md](trinity_push.md) — the lane whose proof-before-prune law the push tests pin
