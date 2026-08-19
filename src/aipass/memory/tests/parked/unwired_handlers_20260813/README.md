# Unwired handlers — archived 2026-08-13

Three of `apps/handlers/`'s files had no caller anywhere. `dead_code` scored 95%
and named two of them (Patrick's 16:47 fleet audit; dispatch 40e33e8b); the third
surfaced only after the first two left. The owner call was wire-it or archive-it:
**all three archived**, because each is superseded by the path that replaced it,
and wiring dead code back in to satisfy a checker would have been the worse answer.

Nothing here is deleted. Restore = move the file back, drop the `(disabled)` suffix,
and re-add its tests.

**Moved here 2026-08-18, same bytes.** This park used to live in
`.archive/unwired_handlers_20260813/`. Patrick's archive ruling that night made `.archive/`
always-ignored and named it his disposal zone, cleaned without warning, so a park kept there
ships with nothing. "Archived not deleted" is only true while the bytes are somewhere a fresh
clone can reach. Every `.py` here wears the `(disabled)` suffix, the house convention for code
that is present but must not run: not importable by dotted path, never collected by pytest —
which matters here, because four of these files ARE tests and would otherwise run against
code that is no longer in the tree.

## What was measured, before deciding

- **Repo-wide grep**, not branch-only: `learnings.manager`, `learnings import
  manager`, `search.vector_search`, `import vector_search` across every `.py`,
  `.json` and `.md` in `AIPass/`. Zero hits outside the files themselves — the
  only matches were seedgo's own audit artifacts and one CHANGELOG paragraph.
  This matters because the `dead_code` checker only sees one branch; a cross-branch
  or hooks-side caller would have made either file load-bearing and the correct
  disposition a documented bypass instead.
- **Dynamic-invocation check**: `importlib` / `__import__` across `apps/`. The
  branch does have a dynamically-invoked handler — `intake/auto_process.py`
  carries its own `importlib.import_module(...)` invocation string — so this was
  a real possibility, not a formality. Neither archived file is reached that way.
- **Class sweep** (the checker names instances, defects are classes): all 44
  module/handler files re-checked for prod references, not just the 2 reported.
  Exactly these 2 came back unreferenced — no hidden third.

## manager.py — learnings manager

`apps/handlers/learnings/manager.py` (+ the package `__init__.py`, kept here as
`learnings__init__(disabled).py`; the empty directory was removed).

Managed `key_learnings` and `recently_completed`: timestamps in the value string,
`max_entries` enforcement, vectorize-before-drop. Superseded on both halves —
`recently_completed` no longer exists in schema 3.0.0, and cap enforcement plus
vectorize-before-drop is what `handlers/rollover/extractor.py` does today. The
CHANGELOG entry for the 3.0.0 migration records it as "used by rollover +
symbolic"; both callers were rewired away since, leaving the file orphaned. That
same entry already noted "1 pre-existing unused-function on an unwired manager
API" — the orphaning was visible then and was not acted on.

Its tests came with it, because tests over unreachable code report coverage that
does not exist:

- `test_learnings(disabled).py` (39 tests)
- `test_manager_vectorize(disabled).py` (37 tests)
- `test_rollover_pipeline_TestProcessAllBranches(disabled).py` (5 tests + the
  `_import_manager` fixture) — extracted verbatim from
  `tests/test_rollover_pipeline.py`, whose remaining 63 tests cover the live
  pipeline and stayed put.

## vector_search.py — in-process search service

`apps/handlers/search/vector_search.py`. Zero references and zero tests: the only
mention anywhere was a stale docstring line in `tests/test_search_extras.py`,
which actually tests `query_executor`.

Superseded by `handlers/search/query_executor.py` + `handlers/storage/chroma_subprocess.py`.
It also contradicts the branch's standing design rule — it imports `chromadb`
and `fastembed` **in-process**, while every live ML path runs them via subprocess
(README, "Subprocess Isolation"). Every collection listing in the live tree goes
through `chroma_subprocess._list_collections`.

## chroma.py — in-process Chroma storage service (the cascade)

`apps/handlers/storage/chroma.py`, with `test_storage(disabled).py` (24 tests).

Not in the audit's original finding. It appeared *because* `vector_search.py`
left: vector_search was its only referencer, so archiving one orphaned the other.
Re-running the audit after a removal is what caught it — a checker reports the
frontier, not the closure.

Measured the same way before archiving: no importer anywhere in the repo, and —
the check that matters for this directory — **no path-based invocation**. Its two
siblings `storage/chroma_subprocess.py` and `vector/embed_subprocess.py` are also
unreachable by import, and both are load-bearing: they are executed as scripts
via `_HANDLERS_DIR / "storage" / "chroma_subprocess.py"` and run in memory's
`.venv`. `chroma.py` has no such call site — nothing builds a path to it, nothing
runs it. Superseded by `chroma_subprocess.py`, same in-process-ML reason as
vector_search.

A full transitive reachability walk (roots: entry point + all 9 modules, plus any
module path appearing in a string literal, to catch `importlib` invocation) was
run before touching anything. It flagged four files; two are the subprocess
scripts above, one is `intake/plans_processor.py` — which is called by @flow's
`post_close_runner.py` across the branch boundary, and was reached by a relative
import inside `modules/rollover.py` that the walk could not see. Only `chroma.py`
survived as genuinely unreachable. **This is why the disposition is per-file and
measured, never "the tool said unreferenced".**

## Effect

- `dead_code` 95% → 100%, with no bypass rule added.
- 105 tests archived alongside the code they covered: 1081 → 976. The same
  session's `watch` module work then took the suite to 997, all green.
