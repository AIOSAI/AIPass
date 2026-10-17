[<- Back to the README](../README.md)

# The trinity standard

**Branch** memory · **Code** `apps/handlers/json/entry_limits.py`, `apps/handlers/json/memory_files.py`, `apps/handlers/json/config_loader.py`

The standard has one rule: **numbers come from `memory.config.json`, prose comes from
`memory/templates/*.template.json`, entry content comes from the agent**, and nothing holds a fact
it can derive. The contract lives in `@devpulse dropbox/trinity_pattern.md`; this document is what
the code does.

---

## An unmeasurable field is a violation, not a zero

The write gate (`entry_limits`) and `lint_handler` both refuse what they cannot measure. A `note`
holding a list of dicts does not measure as 0 chars, and it is not counted by elements:

```
observations[0]: UNMEASURABLE — list, expected str (cap 300 chars cannot be applied)
```

The refusal payload keeps `length`/`cap`/`over_by` as ints (the @hooks `edit_gate` formats them with
`%d`) and adds `reason: "unmeasurable"` and `found_type`. Only authored entries are refused; see
[Judged by what it authors, not by what it carries](#judged-by-what-it-authors-not-by-what-it-carries).

### …and a field it cannot FIND is the same species

A `key_learning` carrying its text under `learning` where the config says `value` is not an absent
text; it is a text the reader cannot find. `_extract_text` returns `None` for it, and the violation
carries its own reason because the repair differs:

| `reason` | Means | What the agent does |
|---|---|---|
| `missing_field` | the canonical key is absent (`field` names it) | rename the key |
| `unmeasurable` | the key is there holding a non-string (`found_type` names it) | fix the shape |

`""` stays a legitimate answer for a field that is present and empty.

**Lint names them too.** `run_lint` reports an entry whose canonical field is absent, because the
write gate refuses it: a branch told it was compliant would otherwise be blocked on its next write
for a shape lint had already seen.

### Judged by what it authors, not by what it carries

**A write is refused for the text it wrote, never for the text it is holding.** `classify_entries`
splits every over-cap entry in one traversal: `["authored"]` (new or edited, and the only thing a
write may be refused for) and `["carried"]` (byte-identical to what is on disk, reported and let
through). `changed_entries` is the authored half alone, kept under that name because @hooks'
`edit_gate` calls it; the six-key payload is unchanged.

The rule covers every container. It does not rely on the write gate to detect drift, because the
gate never measures the writes that cause it: @hooks' `edit_gate` measures caps on the Edit/Write
lane only, and a write made from the shell never reaches the cap check. An entry the gate never
measured cannot be caught by refusing the *next* write. **Rollover's write is always a shrink**: it
removes the tail and hands back a smaller document, and it may not edit the entry in the head; a
gate that refused it for carried debt would leave a file unable to get smaller because it is too
big.

Carried debt is reported on every write, naming the branch, the entry and the numbers, and drift
detection sits in the lane that reads disk: `drone @memory lint` scans every branch's entries,
read-only, and owes nothing to write order.

`todos` are not a special case here; the rule is one rule. A non-canonical todo is not left in place
for its agent to reshape; it moves, json-equal, to its branch's backlog file. See *Todos go to the
backlog, never to vectors* in [trinity_push.md](trinity_push.md).

Touch an entry and you own it: the exemption covers byte-identical text only, so editing a fat entry
into a slightly less fat one is authorship and is refused. Identity in a list is the **text**, never
the index: a prepend shifts every entry down, and an index-keyed diff would call the whole file
newly authored on exactly the write that authored nothing.

**The rollover lane is tested end to end.** Extractor tests mock `memory_files` away, which is
correct for extraction logic and blind to the component that refuses. `TestRolloverSurvivesCarriedDebt`
(`tests/test_rollover_pipeline.py`) mocks nothing below the extractor and asserts on **what is
written to disk**, because a lane can report success while the file never changes.

### The entry shape is closed

A cap on one field does not bound an entry, it bounds a field, and the entry grows through the
fields nobody measured. So `entry_limits.entry_types.<type>.fields` in `memory.config.json` is the
CLOSED shape: every field an entry may carry, its type, whether it is required, and its cap. Nothing
else may appear. There is no per-entry TOTAL, for the same reason: a total lets one field eat the
entry.

The canonical text field keeps its own top-level `field` / `max_chars` keys: @seedgo's
`trinity_groups` and the state-tab renderer read them. `load_entry_limits` reconciles the two so they
can never disagree at runtime: the top-level `max_chars` wins, because it is the number the agent is
shown in its own `*_meta` line.

Two reasons, in the SAME shape as the over-cap violation so @hooks' `%d` formatting keeps working:

| `reason` | Means |
|---|---|
| `unknown_field` | a field outside the closed shape; `field` names it |
| `field_over_cap` | a non-canonical field over its cap; `field` names it, `units` is `"chars"` or `"items"` |

A missing REQUIRED field and a wrongly-typed one reuse the existing `missing_field` / `unmeasurable`
reasons: the consumer already renders them, and the agent's action is identical. The canonical field
is checked ONLY by the original path and the non-canonical fields ONLY by the new one, so no entry is
reported twice for one defect.

**Carried, at field resolution.** The canonical path calls an entry carried when its TEXT matches
disk, and a write that edits only `status` leaves the summary byte-identical. Judging the other
fields by that test would wave through exactly the edit this shape exists to catch. For field
violations an entry is carried only when the WHOLE entry dict is present verbatim in *before*.

**A third label.** `classify_entries` returns `["near"]` beside `authored` and `carried`: authored
entries CLOSE to the cap, at `NEAR_CAP_RATIO` 0.9, because nothing in the act of writing otherwise
shows the agent the limit. Only authored entries are reported near; a carried near-cap entry is not
this write's doing, and warning about it on every write is how a channel becomes noise nobody reads.

---

## keep 15 keeps 15

`extractor._extract_tail_excess` drains only entries beyond the limit, so a file sitting at exactly
the limit loses nothing, and `detector._should_rollover` fires only above the limit, never at it. Both move together, and
`test_detector_and_extractor_never_disagree` sweeps the boundary so they cannot drift apart.

---

## One resolver for char caps, too

`entry_limits.resolve_entry_types()` is the single implementation that both the write gate
(`load_entry_limits`) and `render_tab` call, so `entry_limits.per_branch` overrides apply to both,
as `rollover.per_branch` does. A branch is never *told* one number in its `*_meta` line and
*measured* against another, which would fail @seedgo's Meta-lines rule permanently because the
renderer would keep rewriting the line the checker keeps rejecting.

---

## The renderer reads the template

`tab_renderer` holds no copy of the `_usage` prose: `template_usage()` and `template_semantics()`
read the gold-source templates, and a missing or malformed template **raises** rather than falling
back to a stale string. `refresh_all_tabs()` replaces only the `⟦ … ⟧` tab portion of a `*_meta`
value and preserves the template-owned sentence beside it.

---

## `status.health` does not exist

A field with no consumer that stores a derivable fact is a second source of truth waiting to go
stale. Nothing writes `status.health`: there is no `memory_files.update_metadata()`, no post-drain
stamper in the extractor, and `normalize.py` neither relocates a root `status` nor adds
`last_health_check`. The template-conformance pass strips the orphan block from files that still
carry it. Health is a checker-computed report value, never a stamp in the file. Source-scan tests pin
that the writers stay gone.

---

## Line counts are reported, not stored

`line_counter.update_line_count()` is **read-only**, and the line count is computed and returned,
never persisted. The verb is **`rollover report-lines`**, and it writes **nothing at all**: a
reporter that rewrites every branch's files would be a lie in the other direction. `sync-lines` still
routes (`modules/rollover.RENAMED_VERBS`): it prints a notice naming `report-lines` and runs the
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
`version`: the two templates disagree on `version` (LOCAL 2.0.0, OBSERVATIONS 1.0.0) and agree on
`schema_version` (3.0.0), and the receipt reports the *structure* a branch was stamped with. Pinned
by a test; @seedgo's checker compares against the same field.

Written by `handlers/templates/receipt.py`. Only three lanes may stamp it (`memory push`,
`spawn birth`, `reset`) and any other value is refused. The push lane stamps **only branches it
actually changed**; a tab refresh calls `bump_config_rendered()`, which **refuses to create** a
receipt that does not exist, because the renderer has no authority to claim a template version it
never wrote. @spawn's birth lane stamps its own copy of the shape
(`spawn/apps/handlers/receipt_ops.py`), copied rather than imported so birth carries no runtime
dependency on this branch.

---

## Related

- [trinity_push.md](trinity_push.md) — the lane that enforces this standard fleet-wide
- [templates_and_tabs.md](templates_and_tabs.md) — the prose half, and the tabs that publish these numbers
- [config_verbs.md](config_verbs.md) — `drone @memory config`, the verb surface over the numbers
- [todos_v2_shape_contract.md](todos_v2_shape_contract.md) — the canonical todo, field by field
- [rollover_pipeline.md](rollover_pipeline.md) — the rollover write this gate lets through
