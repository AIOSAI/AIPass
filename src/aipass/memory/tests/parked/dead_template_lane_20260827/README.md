# The pre-`.trinity` template lane — retired 2026-08-27

`pusher.py` and `differ.py` powered `drone @memory push-templates` and
`diff-templates`. Both scanned a branch's **root directory** for files whose
names end in `.local.json` / `.observations.json`:

    pusher._find_memory_files()   handlers/templates/pusher.py:309-322
    differ                        differ.py:236, 275

That naming convention predates `.trinity/`. The live layout is
`<branch>/.trinity/local.json` — a file named `local.json` does not end with
`.local.json`, and it is not in the directory being scanned.
**Zero real matches were possible.**

Measured live before archiving: `diff-templates` reported "16 branches have
template differences" and not one was a `.trinity/` file. The only thing it
ever matched was `CLOSED_PLANS.local.json`, an unrelated archive file that ends
in the right suffix by coincidence. It had never seen an `observations.json`.

## What replaced them

| Was | Is |
|---|---|
| `push-templates` (branch files) | `drone @memory push` — the trinity push, with gates |
| `push-templates` (spawn scaffolds) | `drone @memory templates spawn-templates` — the half that always worked, `spawn_pusher.py`, still live |
| `diff-templates` | `drone @memory push --dry-run` |
| `template-status` | `drone @memory templates template-status` — now reads the per-branch `.trinity/.template_version.json` receipts, which live lanes actually write |

## Why kept rather than deleted

A lane aimed at a dead layout is a silent no-op waiting to be trusted, and its
`get_template_status()` reported a `last_push` date only a push down this same
dead lane could ever move. Kept here because the placeholder-replacement and
deprecated-key logic is the only written record of the pre-`.trinity` file
shape, and DPLAN-0318's history refers to both files by line number.

Retired under DPLAN-0318 marker 7, item 3.

## Why a tracked park and NOT `.archive/`

They landed in `.archive/dead_template_lane_20260827/` first, and that was
wrong by this branch's own ruling. Patrick, 2026-08-18, fleet-wide: `.archive/`
is the disposal zone — gitignored, cleaned without warning, ships in no clone.
The reason for keeping these files is that they are *the written record*, and a
record that exists on exactly one machine is not one. Worse, the pin asserting
they are still here would have passed only where the files happened to survive —
the precise CI failure this branch already hit once, on 2026-08-18, with the two
parks that moved out of `.archive/` that night.

Same ruling, same shape, same month. Moved the day it was noticed.

## The tests came with them

`test_templates.py` (38) and `test_templates_display.py` (29) are parked here
too, under the `(disabled)` suffix — pytest collects `test_*.py` whatever the
rootdir, and `tests/parked/conftest.py` is the collection barrier that makes
that safe. They pinned the retired module's surface — `_find_repo_root`,
`_discover_handlers`, `_load_branches_from_registry`, `_display_diff_results`,
`_display_status` — none of which survive the rewrite. Sixteen of them still
passed at the moment of retirement, all on help-flag safety and routing;
those behaviours are re-pinned against the LIVE surface in
`tests/test_templates_lane.py`, which also covers the two verbs' refusals and
the bump lane.

Tests for retired code are retired with it. Keeping them green against a module
that no longer has those functions is how a suite starts measuring itself.

## The fleet-side ledger came with them

`fleet_ledger.pre_trinity.json` was `memory/templates/.template_version.json`,
written by `pusher.py` and by nothing else. It holds a `last_push` of
2026-06-25 and sixteen branch names in the pre-`.trinity` uppercase form —
and no version field at all, because the retired lane never recorded one.

The bump lane reads the same path for a ledger of the shape
`{"template_versions": {...}}`. A file with no `template_versions` is not a
record of a push, so `bump_pending()` reports PENDING and says why — but a
fossil sitting in `templates/` still reads to a human as a live ledger with
a stale date. Moved here so the directory says what is true: no push has yet
run through the bump lane, and the first `templates bump --confirm` will
stamp the first real one.

Pinned by `test_the_retired_lanes_own_ledger_shape_reads_as_pending_not_as_current`
against exactly this file's shape.

## The fleet-side ledger came with them too

`fleet_ledger.pre_trinity.json` was `memory/templates/.template_version.json`,
written by `pusher.py` and by nothing else. It holds a `last_push` of
2026-06-25 and sixteen branch names in the pre-`.trinity` uppercase form — and
no version field at all, because the retired lane never recorded one.

The live bump lane reads that path for a ledger shaped
`{"template_versions": {...}}`. A file with no `template_versions` is not a
record of a push, so `bump_pending()` reported PENDING and said why — but a
fossil sitting in `templates/` still reads to a human as a live ledger with a
stale date. Moved here so the directory says what is true: no push has yet run
through the bump lane, and the first `templates bump --confirm` will stamp the
first real one.

Pinned by `test_the_retired_lanes_own_ledger_shape_reads_as_pending_not_as_current`
against exactly this file's shape.

## Revival

Strip the `(disabled)` suffix. `pusher.py` and `differ.py` return to
`apps/handlers/templates/`, the two test files to `tests/`. Nothing should
revive them as they stand — they scan a layout no citizen has used since
`.trinity/` landed. What is worth reading is the placeholder-replacement and
deprecated-key logic, and the file shape it implies.
