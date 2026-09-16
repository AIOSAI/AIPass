# The trinity standard

**Branch** memory · **Code** `apps/handlers/json/entry_limits.py`, `apps/handlers/json/memory_files.py`, `apps/handlers/json/config_loader.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

DPLAN-0318, built 2026-08-25. The standard has one rule: **numbers come from `memory.config.json`,
prose comes from `memory/templates/*.template.json`, entry content comes from the agent** — and
nothing holds a fact it can derive. The contract lives in `@devpulse dropbox/trinity_pattern.md`;
this document is what the code now does.

---

## An unmeasurable field is a violation, not a zero

`entry_limits._extract_text()` returned `""` for anything that was not a string. A `note` holding a
list of dicts therefore measured **0 chars** and cleared a 300-char cap — and `lint_handler` ran
`len()` on that same list, counting **elements**. Two independent gates agreeing is exactly what made
the drift look verified. Both now refuse what they cannot measure:

```
observations[0]: UNMEASURABLE — list, expected str (cap 300 chars cannot be applied)
```

The refusal payload keeps `length`/`cap`/`over_by` as ints (the @hooks `edit_gate` formats them with
`%d`) and adds `reason: "unmeasurable"` and `found_type`. When this shipped, **unchanged legacy
entries still passed** — `enforce: true` was live and 9 branches carried list-shaped notes, so only a
*new or edited* unmeasurable entry was refused and the fix could not brick the fleet it was meant to
protect. That exemption was narrowed to `todos` alone on 2026-08-27 and widened back to every container on
2026-08-30 — see
[Judged by what it authors, not by what it carries](#judged-by-what-it-authors-not-by-what-it-carries).

### …and a field it cannot FIND is the same species

Fixed 2026-08-26. The first pass fixed the wrong-type case and left the **missing-field** case still answering `""`.
A `key_learning` carrying its text under `learning` where the config says `value` therefore measured
as zero characters and cleared a 200-char cap — @hooks proved it live against their own `local.json`
the night 1.3.0 shipped: a 500-char entry, cap 200, **zero violations**. A renamed field is not an
absent text; it is a text the reader cannot find. `_extract_text` now returns `None` for it, and the
violation carries its own reason because the repair differs:

| `reason` | Means | What the agent does |
|---|---|---|
| `missing_field` | the canonical key is absent (`field` names it) | rename the key |
| `unmeasurable` | the key is there holding a non-string (`found_type` names it) | fix the shape |

`""` stays a legitimate answer for a field that is present and empty. Measured across the live fleet
the day of the fix: **42 missing-field entries on 3 branches** (@hooks, @ai_mail, @api — all
`key_learnings`, all the `learning` shape), previously reported as compliant by both gates.

**Lint's boundary moved with it.** `lint` used to skip an entry whose canonical field was absent, on
the reading that shape belongs to the trinity checker rather than to a char-cap scanner. That cost
more than it bought: the write gate refuses those entries, so a branch could be told it was compliant
and then be blocked on its next write for a shape lint had already seen. `run_lint` now names them.

### Judged by what it authors, not by what it carries

The 2026-08-30 ruling. **A write is refused for the text it wrote, never for the text it is holding.** `classify_entries`
splits every over-cap entry in one traversal: `["authored"]` — new or edited, and the only thing a
write may be refused for — and `["carried"]` — byte-identical to what is on disk, reported and let
through. `changed_entries` is the authored half alone, kept under that name because @hooks'
`edit_gate` calls it; the six-key payload is unchanged.

This reverses a narrowing made on 2026-08-27, and the reversal was expensive to learn. That change
exempted `todos` alone, reasoning that the trinity push had cured legacy drift fleet-wide so
"unchanged and over cap passes" now hid new drift instead of protecting old. Both halves were wrong
about the world:

- **Drift recurs.** The evening the deadlock was reported, @ai_mail carried three over-cap
  `key_learnings` and @seedgo one 343-char `summary`.
- **This gate never measures the writes that cause it.** @hooks' `edit_gate` says so in its own
  refusal text: caps are measured on the Edit/Write lane only. A write made from the shell reaches
  their handler — the project fence runs there — but never reaches the cap check, and @baud drifted
  to 2529/300 for a week through that gap. An entry the gate never measured cannot be caught by
  refusing the *next* write.

So the narrowing put drift detection on the one component structurally blind to how drift arrives —
and charged rollover for it. **Rollover's write is always a shrink**: it removes the tail and hands
back a smaller document, and it may not edit the entry in the head it is being refused for. On
2026-08-30 that ran as an identical failure every 20 minutes for three hours against @seedgo's file,
until @trigger escalated four repeat signatures. The file could not get smaller because it was too
big.

What the narrowing was **right** about is the silence: the old clause skipped a carried entry without
a word. Carried debt is now reported on every write, naming the branch, the entry and the numbers —
and drift detection sits where it belongs, in the lane that reads disk: `drone @memory lint` scans
every branch's entries, read-only, and owes nothing to write order.

`todos` are no longer a special case here — the rule is one rule. `RESHAPE_ONLY_SECTIONS`, which
named `todos` as the one container no machine may prune, is **retired** (DPLAN-0345, 2026-09-15): no
code under `src/aipass/` outside the test trees names it. A non-canonical todo is no longer left in place
for its agent to reshape; it moves, json-equal, to its branch's backlog file — see *Todos go to
the backlog, never to vectors* in [trinity_push.md](trinity_push.md).

Touch an entry and you own it: the exemption covers byte-identical text only, so editing a fat entry
into a slightly less fat one is authorship and is refused. Identity in a list is the **text**, never
the index — a prepend shifts every entry down, and an index-keyed diff would call the whole file
newly authored on exactly the write that authored nothing.

**The lane that broke could not see what broke it.** With the rule fixed, restoring the defect as a
mutant killed exactly three tests — all at the *writer*, in `test_changed_entries.py`. Not one
rollover test died, because every extractor test mocks `memory_files` away: correct for testing
extraction logic, blind to the component that actually refused. @hooks found the mirror image in
their own tree the same evening — a mutant making their checker return nothing left their whole
end-to-end suite green, because the union ran @memory's real diff. When two halves overlap, a suite
that cannot tell them apart proves neither. `TestRolloverSurvivesCarriedDebt` mocks nothing below the
extractor and asserts on **what is written to disk**, because "success" is exactly what the lane
reported for three hours while the file never changed. With that test in place the same mutant died
six times over.

### The entry shape is closed

FPLAN-0593 Phase 1 (entry_limits 1.11.0, 2026-09-15) closed the entry shape, so the caps described
above are no longer the whole gate. One field capped per entry type is what let @devpulse carry a
917-char `status` past every gate while the fleet median is 9: a cap on ONE field does not bound an
entry, it bounds a field, and the entry grows through the fields nobody measured. Measured
2026-09-15 across 22 branches, 803 entries: `status` max 917 / p95 12, `key` max 83 / p95 65, `tags`
max 9 items and 100 joined chars, `priority` max 6, `date` max 10 everywhere.

So `entry_limits.entry_types.<type>.fields` in `memory.config.json` is now the CLOSED shape: every
field an entry may carry, its type, whether it is required, and its cap. Nothing else may appear. The
boardroom refused a per-entry TOTAL for the same reason: a total lets one field eat the entry.

The canonical text field keeps its own top-level `field` / `max_chars` keys untouched — @seedgo's
`trinity_groups` and the state-tab renderer read them, and that mirror only retires in Phase 2.
`load_entry_limits` reconciles the two so they can never disagree at runtime: the top-level
`max_chars` wins, because it is the number the agent is shown in its own `*_meta` line.

Two new reasons, in the SAME shape as the existing over-cap violation so @hooks' `%d` formatting
keeps working:

| `reason` | Means |
|---|---|
| `unknown_field` | a field outside the closed shape; `field` names it |
| `field_over_cap` | a non-canonical field over its cap; `field` names it, `units` is `"chars"` or `"items"` |

A missing REQUIRED field and a wrongly-typed one reuse the existing `missing_field` / `unmeasurable`
reasons rather than minting more: the consumer already renders them, and the agent's action is
identical. The canonical field is checked ONLY by the original path and the non-canonical fields ONLY
by the new one, so no entry is reported twice for one defect.

**Carried, at field resolution.** The authored-not-carried rule holds, but its identity had to
sharpen: the canonical path calls an entry carried when its TEXT matches disk, and a write that edits
only `status` leaves the summary byte-identical. Judging the new fields by that test would wave
through exactly the edit this shape exists to catch. For field violations an entry is carried only
when the WHOLE entry dict is present verbatim in *before*.

**A third label, older than this phase.** `classify_entries` returns `["near"]` beside `authored` and
`carried` (1.7.0, 2026-08-31) — authored entries CLOSE to the cap, at `NEAR_CAP_RATIO` 0.9. Asked for
by @ai_mail, who wrote over the cap four hours after being burned by it, knowing the number: "nothing
in the act of writing shows you the limit — the only instrument is downstream." Only authored entries
are reported near; a carried near-cap entry is not this write's doing, and warning about it on every
write is how a channel becomes noise nobody reads.

---

## keep 15 now keeps 15

`extractor._extract_tail_excess` floored the drain at `max(len - limit, 1)`, so a file sitting at
exactly the limit lost one entry every run and every branch settled permanently at **14**. Fixing the
extractor alone would have stranded `detector._should_rollover`, which fired at `>=` — a fleet-wide
`NOTHING DRAINED` skip loop. Both thresholds moved together, and
`test_detector_and_extractor_never_disagree` sweeps the boundary so they cannot drift apart again.

---

## One resolver for char caps, too

`render_tab` read `entry_types` straight off the config and never consulted
`entry_limits.per_branch`, while the write gate (`load_entry_limits`) always did.
The first branch to take a per-branch char-cap override would have been *told* one number in its
`*_meta` line and *measured* against another — and would have failed @seedgo's Meta-lines rule
permanently, because the renderer keeps rewriting the line the checker keeps rejecting. Found by
@seedgo's trinity checker from the other side of the same contract, latent only because that map is
empty today. `entry_limits.resolve_entry_types()` is now the single implementation both call, and
`rollover.per_branch` (which `render_tab` already honoured) is no longer the odd one out.

---

## The renderer reads the template

`tab_renderer` used to carry the `_usage` text as `_CORRECTED_USAGE_*` string constants — a second
copy of prose the templates own. The constants are retired: `template_usage()` and
`template_semantics()` read the gold-source templates, and a missing or malformed template **raises**
rather than falling back to a stale string. `refresh_all_tabs()` now replaces only the `⟦ … ⟧` tab
portion of a `*_meta` value and preserves the template-owned sentence beside it.

---

## `status.health` is deleted, not computed

Patrick's ruling: the field had no consumer, read `healthy` hardcoded since 2025-11, and stored a
fact that is derivable — a second source of truth waiting to go stale. Every writer is gone
(`memory_files.update_metadata()` removed, the extractor's post-drain stamper removed,
`normalize.py` no longer relocates a root `status` or adds `last_health_check`), and the
template-conformance pass strips the orphan block from files that still carry it. Health is a
checker-computed report value now, never a stamp in the file. Source-scan tests pin that the writers
stay gone.

---

## Line counts are reported, not stored

`line_counter.update_line_count()` is **read-only**: its only write was the health stamp, and the
line count itself was never persisted — it was computed, returned and dropped. The verb was therefore
renamed to **`rollover report-lines`** (`modules/rollover.RENAMED_VERBS`), and it now writes **nothing
at all**: the unscoped fleet-wide `refresh_all_tabs()` it used to run on the tail is gone from
`report_line_counts()`, because a reporter that rewrites 22 branches' files is the same lie in the
other direction. `sync-lines` still routes — it prints a notice naming `report-lines` and runs the
reporter, since a removed verb tells a caller nothing about what replaced it. Meta lines are
re-rendered by the lanes that have a reason to: the trinity push, and a rollover's own scoped
normalize.

---

## `.template_version.json` — the per-branch receipt

```json
{
  "template_versions": {"local": "3.0.0", "observations": "3.0.0"},
  "stamped": "2026-08-25T23:37:05",
  "stamped_by": "memory push",
  "config_rendered": "2026-08-25T23:37:05"
}
```

`template_versions` reports each template's **`document_metadata.schema_version`**, not its
`version` — the two templates disagree on `version` (LOCAL 2.0.0, OBSERVATIONS 1.0.0) and agree on
`schema_version` (3.0.0), and the receipt reports the *structure* a branch was stamped with. Pinned
by a test, and confirmed to @seedgo whose checker compares against the same field.

Written by `handlers/templates/receipt.py`. Only three lanes may stamp it — `memory push`,
`spawn birth`, `reset` — and any other value is refused. The push lane stamps **only branches it
actually changed**; a tab refresh calls `bump_config_rendered()`, which **refuses to create** a
receipt that does not exist, because the renderer has no authority to claim a template version it
never wrote. @spawn's birth lane adopts the writer separately — this build ships the callable and
does not touch spawn.

---

## Related

- [trinity_push.md](trinity_push.md) — the lane that enforces this standard fleet-wide
- [templates_and_tabs.md](templates_and_tabs.md) — the prose half, and the tabs that publish these numbers
- [config_verbs.md](config_verbs.md) — `drone @memory config`, the verb surface over the numbers
- [todos_v2_shape_contract.md](todos_v2_shape_contract.md) — the canonical todo, field by field
- [rollover_pipeline.md](rollover_pipeline.md) — the write this gate refused for three hours
