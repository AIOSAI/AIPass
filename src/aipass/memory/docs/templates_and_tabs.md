[<- Back to the README](../README.md)

# Gold templates and the state tabs

**Branch** memory · **Code** `apps/modules/templates.py`, `apps/handlers/templates/`, `apps/handlers/tracking/tab_renderer.py`

The gold templates in `memory/templates/` own the *prose* of every branch's `.trinity/` files;
`memory.config.json` owns the *numbers*; the `*_meta` tabs are where the two meet and become an
instruction the editing agent reads. Everything below is the machinery behind
`drone @memory templates <verb>`; the verbs themselves are in `drone @memory --help`.

---

## The retired verbs, and what replaced them

`push-templates` and `diff-templates` still **route and refuse**, naming the live lane
(`modules/templates.RETIRED_VERBS`); a removed verb tells a caller nothing about its replacement.
They scanned the branch root for a naming convention that predates `.trinity/` and could match no
real memory file. `pusher.py`, `differ.py` and the tests that pinned them are parked in
`tests/parked/dead_template_lane_20260827/`, with the measurement written down there.

- `push-templates` → `drone @memory push` (branch memory files, gated) and
  `drone @memory templates spawn-templates` (@spawn's scaffold sets)
- `diff-templates` → `drone @memory push --dry-run`

`templates spawn-templates` (`spawn_pusher.py`) propagates the gold templates into @spawn's template
sets at `spawn/templates/*/.trinity/{local,observations}.json`.

`template-status` reads each branch's own `.trinity/.template_version.json` receipt through
`template_bump.receipt_status()`, plus the fleet ledger below.

---

## The template bump site

`drone @memory templates bump` is where a gold-template version bump gets acted on.
`handlers/templates/template_bump.py` compares the gold templates against a **fleet-side ledger**
(`memory/templates/.template_version.json`, not to be confused with a branch's own receipt of the
same name), announces `trinity_template_bumped` on @trigger's bus, and heals the fleet by running the
trinity push with every gate intact.

- **Trigger-driven, never polled.** Nothing watches the templates: `bump_pending()` compares two files
  already on disk and runs only when the lane is invoked. No timer, no poller, idle costs nothing.
- **DRY RUN by default; `--confirm` executes.** A version bump that rewrote every branch's memory
  files on its own is exactly the unattended fleet-wide write `--confirm` exists to prevent.
- **The ledger is stamped only by a push that actually ran and actually succeeded.** A dry run that
  stamped it would tell the next bump the work was done, and a stamped failure would do the same while
  leaving the fleet stale. No readable ledger, or one with no `template_versions`, reads as
  *BUMP PENDING*: a missing record of a push is not a record of a push. Pinned by
  `test_the_retired_lanes_own_ledger_shape_reads_as_pending_not_as_current`.
- The event's **name** lives in the handler (`BUMP_EVENT`); the **firing** lives in
  `modules/templates._announce_bump()`, because reaching the bus means importing @trigger's module
  layer, and a handler that does that is orchestration in a handler's clothes.
- **No subscriber is registered for `trinity_template_bumped`.** The bump acts through the push,
  never through a listener; the announcement is not wiring that does something.

`template-status` reports two separate things, and both can be true at once: each branch's receipt
(branches with no receipt are listed; external-tier branches are out of push scope by design, since
`resolve_scope()` drops `external` because the push writes), and the fleet ledger. With no ledger
file in `memory/templates/`, the ledger line reads **BUMP PENDING** even while every in-scope branch
carries the current version; the first `templates bump --confirm` that succeeds writes it.

**Strays.** The push reports files in a `.trinity/` that are not push scope as files, never as a
verdict on the branch: `N file(s) in .trinity/ are not push scope (reported, never deleted)`.
`_trinity_strays()` does not count `*.pre_v2_backup` / `*.pre_v3_backup`
(`_KNOWN_MIGRATION_BACKUPS`): each is an accounted-for artifact of a named migration, and the push may
not delete them and does not need them gone. An unexplained file in a `.trinity/` is still a stray
and is still reported; the backups are never deleted, which is pinned.

---

## State-Tabs (`*_meta` keys)

Every `.trinity/local.json` and `.trinity/observations.json` carries inline `*_meta` banner strings that tell the editing agent what rollover rules apply to each section. Example:

```
"sessions_meta": "⟦ rollover ON → oldest archived to @memory · keep 15 · summary ≤300 chars · draft to 240 ⟧"
```

**The draft target.** Every cap renders with `draft to N` beside it: `DRAFT_PERCENT` (80) of the
cap, floored, from `entry_limits.draft_target()`. 300/200/100 read 240/160/80, and a `per_branch` cap
of 500 reads 400. It is derived, not a config key: a second stored number per entry type would go
stale the first time an override moved only the cap. The write gate never reads it; the cap and
`enforce` are unchanged. The line states a number so the text is drafted to it, below the cap.
@seedgo's `expected_meta_line` mirrors this format byte for byte, so a format change here is mailed
there before files are re-rendered.

**Nothing hand-edits that file.** `drone @memory config` is the verb surface over rollover limits — see [config_verbs.md](config_verbs.md).

**Source of truth:** `memory_json/custom_config/memory.config.json` — the operator-edited file *is* the runtime authority for rollover counts and entry char limits. `config_loader.DEFAULT_CONFIG` in code is the **regeneration seed**: when the file is genuinely *missing*, `load()` rebuilds it in full from those defaults so there is always a real file to edit. A file that *exists* but cannot be read — for **any** reason: bad syntax, bad bytes, bad permissions — is never written over and never raises at the caller. `load()` logs an ERROR, serves defaults in memory, and leaves the bytes alone for the operator to fix; healing a stray comma must not cost them their per-branch tuning. `rollover push` refuses on the same condition rather than rebuilding from the seed. A file that parses is never rewritten either, so operator edits persist, and anything it omits is deep-merged from the defaults. Tab strings are *generated* from the effective config, never hand-written.

**Sections:** `todos_meta` (a pad of `rollover.defaults.local.todos.count` todos; the oldest roll to a backlog file, never to vectors), `key_learnings_meta`, `sessions_meta`, `observations_meta` (all rollover ON). The todos tab carries the pad size, the backlog path, the task cap and `next #N`, derived at render time as max(pad ∪ backlog) + 1. This branch's, as rendered on its own `local.json`:

```
"todos_meta": "⟦ pad of 10 · oldest roll to .backup/todo/memory/backlog.json · task ≤100 chars · draft to 80 · next #13 ⟧ One line of what to do: …"
```

### One resolver, because the tab is an instruction

A tab is written **into** the agent's own memory file, where it reads as an instruction about that
agent's limits — so a tab naming a number the engine does not enforce is a lie in the one place an
agent trusts. `render_tab` therefore asks `config_loader.resolve_limits()` and never re-derives
anything; that is the same function behind `config get`, itself pinned against
`detector._should_rollover` with the engine as the test oracle.

It falls back per **file-key**, so a `per_branch` entry missing its `local` block uses the defaults
the engine would use, and it never hard-defaults a missing `count`. Where no limit is configured the
tab says `no entry limit configured` rather than naming a number. `TestTabAgreesWithTheEngine` pins
all of it, including a guard that fails if a `count` fallback is ever reintroduced into this file.

### Two value flows

| Scenario | How tabs arrive |
|---|---|
| **Live branches** | `refresh_all_tabs(branches=…)` renders tabs from config with per-branch overrides and writes them into `.trinity/` files. It has two callers under `apps/`, both scoped: after `rollover run`, **to the branches that run actually rolled** (the same rollover then re-renders those branches' whole frame through `rollover/normalizer.py`); and after a `config` limit write, through `tab_renderer.refresh_moved_limits()`, to the branches whose enforced count moved. `report-lines` writes nothing. |
| **New branches** | Templates carry `{{TODOS_META}}`, `{{KEY_LEARNINGS_META}}`, `{{SESSIONS_META}}`, `{{OBSERVATIONS_META}}` placeholders. `spawn_pusher` propagates these (unresolved) from memory templates → spawn template sets. At branch creation, @spawn calls `render_all_meta_tabs()` to get rendered defaults and resolves the placeholders. |

### Public API

```python
from aipass.memory.apps.handlers.tracking.tab_renderer import render_all_meta_tabs

tabs = render_all_meta_tabs()
# → {"TODOS_META": "⟦ pad of 10 · oldest roll to .backup/todo/<branch>/backlog.json · task ≤100 chars · draft to 80 · next #? ⟧", "KEY_LEARNINGS_META": "⟦ rollover ON ...", ...}

tabs = render_all_meta_tabs(branch_dir="canary")
# → the todos tab names .backup/todo/canary/backlog.json; next #N from an empty pad + that backlog
```

Returns defaults (not per-branch overrides) — appropriate for template resolution at branch creation. With no `branch_dir` the todos tab renders `<branch>` and `next #?` rather than guess a number.

---

## Related

- [trinity_standard.md](trinity_standard.md) — the numbers half, and the receipt this lane stamps
- [trinity_push.md](trinity_push.md) — the lane the bump acts through
- [config_verbs.md](config_verbs.md) — `drone @memory config`, the verb surface over those numbers
- [todos_and_backlog.md](todos_and_backlog.md) — the pad and backlog the todos tab describes
- [rollover_pipeline.md](rollover_pipeline.md) — the scoped tab refresh after a roll
