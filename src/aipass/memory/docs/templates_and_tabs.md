# Gold templates and the state tabs

**Branch** memory · **Code** `apps/modules/templates.py`, `apps/handlers/templates/`, `apps/handlers/tracking/tab_renderer.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

The gold templates in `memory/templates/` own the *prose* of every branch's `.trinity/` files;
`memory.config.json` owns the *numbers*; the `*_meta` tabs are where the two meet and become an
instruction the editing agent reads. Everything below is the machinery behind
`drone @memory templates <verb>`; the verbs themselves are in `drone @memory --help`.

---

## The templates lane was retired

Retired 2026-08-27. `push-templates` and `diff-templates` scanned the **branch root** for files ending `.local.json` /
`.observations.json` — a naming convention that predates `.trinity/`. The live layout is
`<branch>/.trinity/local.json`, which does not end with `.local.json` and is not in the directory
being scanned: **zero real matches were possible.** Measured before retirement, `diff-templates`
reported "16 branches have template differences" and not one was a `.trinity/` file — the only thing
it ever matched was `CLOSED_PLANS.local.json`, an unrelated archive file with the right suffix by
coincidence.

Both verbs still **route and refuse**, naming the live lane (`modules/templates.RETIRED_VERBS`); a
removed verb tells a caller nothing about its replacement. `pusher.py`, `differ.py` and the two test
files that pinned them are in `tests/parked/dead_template_lane_20260827/`, with the measurement written
down there.

- `push-templates` → `drone @memory push` (branch memory files, gated) and
  `drone @memory templates spawn-templates` (@spawn's scaffold sets)
- `diff-templates` → `drone @memory push --dry-run`

**The half that always worked survives under its own name.** `spawn_pusher.py` propagates the gold
templates into @spawn's template sets at `spawn/templates/*/.trinity/{local,observations}.json` — the
real layout. It used to run as a side effect of the dead verb, which is why it went unnoticed; it is
`templates spawn-templates` now.

`template-status` survives too, **repointed**: it read a fleet-side push log whose `last_push` only
the retired lane could ever move, and now reads each branch's own `.trinity/.template_version.json`
receipt through `template_bump.receipt_status()` — written by lanes that are alive.

---

## The template bump site

Since 2026-08-27, `drone @memory templates bump` is where a gold-template version bump gets acted on.
`handlers/templates/template_bump.py` compares the gold templates against a **fleet-side ledger**
(`memory/templates/.template_version.json` — not to be confused with a branch's own receipt of the
same name), announces `trinity_template_bumped` on @trigger's bus, and heals the fleet by running the
trinity push with every gate intact.

- **Trigger-driven, never polled.** Nothing watches the templates: `bump_pending()` compares two files
  already on disk and runs only when the lane is invoked. No timer, no poller, idle costs nothing.
- **DRY RUN by default; `--confirm` executes.** A version bump that rewrote 22 branches' memory files
  on its own is exactly the unattended fleet-wide write `--confirm` exists to prevent.
- **The ledger is stamped only by a push that actually ran and actually succeeded** — a dry run that
  stamped it would tell the next bump the work was done, and a stamped failure would do the same while
  leaving the fleet stale. No ledger at all reads as *bump pending*: absent and up-to-date are opposite
  answers.
- The event's **name** lives in the handler (`BUMP_EVENT`); the **firing** lives in
  `modules/templates._announce_bump()`, because reaching the bus means importing @trigger's module
  layer, and a handler that does that is orchestration in a handler's clothes.

**The first real ledger was stamped 2026-09-07 17:50 (FPLAN-0492 wave 6).** `templates/.template_version.json`
now holds `local 3.0.0 · observations 3.0.0`, `last_push 2026-09-07T17:50:09`, `stamped_by "memory push"` —
written by a `templates bump --confirm` that actually ran: 22 branches, 44 files written, 22 receipts stamped,
**5 entries archived and pruned**, 854 carried. Verified rather than assumed: a fleet `push --dry-run` taken
straight after reports **0 entries to archive**, where the run before it reported 5. `template-status` now
reads *no bump pending*. The six `NO RECEIPT` branches (`wren`, `research`, `vera`, `verify`, `writer`,
`my-agent`) are external-tier and out of push scope by design — `resolve_scope()` drops `external` because the
push writes.

**What held it back for a day was this branch's own wording, not the fleet's state.** Every branch printed
`NOT push scope — N stray file(s) in .trinity/`, which reads as a verdict on the *branch*; @spawn measured it
that way on 2026-09-07, declined to fire `--confirm` on the reasoning that a push doing nothing would stamp a
false ledger, and @devpulse relayed the same reading. Both were right to stop, and both were reading a line
that meant something else: the *files* are out of scope, and the line directly above it showed those same
branches pruning and carrying normally. Two things changed. The line now says the files are not push scope,
never the branch. And `_trinity_strays()` no longer counts `*.pre_v2_backup` / `*.pre_v3_backup`
(`_KNOWN_MIGRATION_BACKUPS`): 54 of them across 22 branches, every one an accounted-for artifact of a named
migration — @spawn's `migrate-passports --confirm` and this branch's own v3 rollover — reported on every run
forever, on a line no run could ever clear, because the push may not delete them and does not need them gone.
An unexplained file in a `.trinity/` is still a stray and is still reported; the backups still exist and are
still never deleted, which is pinned.

The old paragraph, kept because the reasoning in it is still the standard: `templates/.template_version.json` did
exist — written by the retired `pusher.py` and by nothing else, holding `last_push: 2026-06-25` and
sixteen uppercase branch names, no version field anywhere. A file with no `template_versions` is not
a record of a push, so `bump_pending()` already read it as PENDING; but a fossil sitting in
`templates/` reads to a human as a live ledger with a stale date, so it moved to
`tests/parked/dead_template_lane_20260827/fleet_ledger.pre_trinity.json` with the lane that wrote it.
`template-status` therefore reports **BUMP PENDING** while every branch reads *current* — both are
true: 22/22 carry `3.0.0` by their own receipts, and no push has yet run through the bump lane to
stamp a fleet ledger. The first `templates bump --confirm` writes the first real one. The old shape
is pinned by `test_the_retired_lanes_own_ledger_shape_reads_as_pending_not_as_current`, so a ledger
that cannot name a version can never be mistaken for one that can.

**Nothing listens for `trinity_template_bumped` yet** — grepped across @trigger's tree, no handler is
registered. The announcement is fired and lands on an empty subscriber list, which is the intended
shape (the bump acts through the push, never through a listener) but is stated here so the event is
not read as wiring that already does something.

---

## State-Tabs (`*_meta` keys)

Every `.trinity/local.json` and `.trinity/observations.json` carries inline `*_meta` banner strings that tell the editing agent what rollover rules apply to each section. Example:

```
"sessions_meta": "⟦ rollover ON → oldest archived to @memory · keep 15 · summary ≤300 chars · draft to 240 ⟧"
```

**The draft target** arrived 2026-09-13 with DPLAN-0342. Every cap renders with `draft to N` beside it:
`DRAFT_PERCENT` (80) of the cap, floored, from `entry_limits.draft_target()` — 300/200/100 read
240/160/80, and a `per_branch` cap of 500 reads 400. It is derived, not a config key: a second stored
number per entry type would go stale the first time an override moved only the cap. The write gate
never reads it; the cap and `enforce` are unchanged. Why it is in the line: @devpulse's fleet miner
found 226 of 2280 `.trinity` edits refused (9.9%), median overage 7% of the cap, and a field replica
shown only the meta line wrote its summary to 294/300. The line states a number and the text goes to
it. @seedgo's `expected_meta_line` mirrors this format byte for byte, so a format change here is
mailed there before files are re-rendered.

**Nothing hand-edits that file.** `drone @memory config` is the verb surface over rollover limits — see [config_verbs.md](config_verbs.md).

**Source of truth:** `memory_json/custom_config/memory.config.json` — the operator-edited file *is* the runtime authority for rollover counts and entry char limits. `config_loader.DEFAULT_CONFIG` in code is the **regeneration seed**: when the file is genuinely *missing*, `load()` rebuilds it in full from those defaults so there is always a real file to edit. A file that *exists* but cannot be read — for **any** reason: bad syntax, bad bytes, bad permissions — is never written over (DPLAN-0206 red flag, `json_structure` v3.0.0) and never raises at the caller. `load()` logs an ERROR, serves defaults in memory, and leaves the bytes alone for the operator to fix; healing a stray comma must not cost them their per-branch tuning. `rollover push` refuses on the same condition rather than rebuilding from the seed. A file that parses is never rewritten either, so operator edits persist, and anything it omits is deep-merged from the defaults. Tab strings are *generated* from the effective config, never hand-written.

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

Until 2026-08-16 it carried its own lookup and drifted two ways (found by @devpulse's wiring
research, both reproduced before fixing): it fell back per-branch-**dict** rather than
per-**file-key**, so a `per_branch` entry missing its `local` block ignored the defaults the engine
would have used; and it hard-defaulted a missing `count` to **15**, printing a limit that did not
exist. Where no limit is configured the tab now says `no entry limit configured` rather than naming
a number. `TestTabAgreesWithTheEngine` pins all of it, including a guard that fails if a `count`
fallback is ever reintroduced into this file.

### Two value flows

| Scenario | How tabs arrive |
|---|---|
| **Live branches** | `refresh_all_tabs(branches=…)` renders tabs from config with per-branch overrides and writes them into `.trinity/` files. Wired after `rollover run` only, **scoped to the branches that run actually rolled** — the same rollover then re-renders those branches' whole frame through `rollover/normalizer.py`. Grep for `refresh_all_tabs` under `apps/` finds exactly that one caller: `report-lines` writes nothing, and the retired template verbs never called it. |
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
