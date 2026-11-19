[<- Back to the README](../README.md)

# Quality and proof

**Branch** memory · **Code** `tests/`

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
scores a push with @sentry's checker. While that checker still renders the retired todos tab, the
only miss it allows is the `todos_meta` byte-match, and it xfails; once sentry's todos-tab mirror
renders the pad tab, it asserts strictly on its own
([todos_v2_shape_contract.md](todos_v2_shape_contract.md)).

**Every skip names its reason.** One skip appears only on a fresh clone: the health test that reads this branch's real
`.trinity/` files, which are gitignored (`tests/test_health.py`, "no live .trinity files in this
checkout"). A skip that names its reason is honest; a pass that needed this machine is not.

**Two different counts exist, deliberately, and neither substitutes for the other.**
`grep -c 'def test_'` over `tests/test_*.py` counts the test functions **on disk**. Some of those
live in modules that call `pytest.skip(allow_module_level=True)` at import, so pytest never collects
them individually; they surface as one skip each. The rest expand through
`@pytest.mark.parametrize` into more **collected** cases than there are functions. Both numbers are
true: sentry's `readme` rule counts the functions on disk, a green board counts the cases that
execute. Quoting one where the other is meant is how a README ends up arguing with its own audit.

The `.trinity/` json_handler shim pins do not live here: they run once for every branch inside
sentry's `tests/test_json_handler_contract.py`, because a per-branch contract is the right home for
a shim every branch carries.

---

## Sentry

The audit is `drone @sentry audit aipass @memory`, `apps/` only. Findings are fixed, not bypassed,
where the code can carry the fix:

- The entry seam says for itself that a bare `rollover` introspects; the no-args gate is not
  hidden behind a delegation (`introspection`).
- The top-level command chain is flat `if`/`return`, one arm per command (`deep_nesting`).
- Report rendering lives in `handlers/templates/push_report.py`; modules do no direct file I/O.
- `--json` output goes through the shared console as
  `console.print(payload, markup=False, soft_wrap=True, highlight=False)`, which emits byte-exact
  JSON, so no Rich `cli` bypass is needed to serve a machine. The `json_flag.py` rule
  (`json_structure`) mirrors `help_flags.py` for its sibling predicate.

**Bypass registry.** `.sentry/bypass.json` holds the per-file rules that remain. Every rule names a
file that is in the tree; a bypass for an absent file suppresses nothing and would be dead weight.

---

## Retired code leaves the tree

Code no lane runs leaves the tree for the owner's local archive; git history keeps it. No live
file reads, imports, prints or documents it. A retired tier a caller may still reach keeps only a
refusal stub that names the ruling and the live replacement: `apps/modules/symbolic.py` and
`apps/handlers/symbolic/__init__.py`, pinned by `test_symbolic_parked.py`.

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

## Dead code leaves with its tests

A handler file with no caller leaves the tree together with the tests that covered it: tests over
unreachable code report coverage that does not exist. The in-process ChromaDB paths went this way,
superseded by `chroma_subprocess.py`.

Files that look unreferenced can be load-bearing: `handlers/storage/chroma_subprocess.py` and
`handlers/vector/embed_subprocess.py` are executed as *scripts* by path in memory's `.venv`, never
imported. Disposition is per-file and measured (repo-wide grep, dynamic `importlib` check, and a
path-invocation check), never "the checker said unreferenced".

---

## Related

- [vector_search.md](vector_search.md) — the subprocess tier that replaced the in-process paths
- [trinity_push.md](trinity_push.md) — the lane whose proof-before-prune law the push tests pin
