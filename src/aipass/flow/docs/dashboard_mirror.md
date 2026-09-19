[← Back to Flow](../README.md)

# Dashboard Writes — quick_status is shared ground

The flow section contract, why quick_status is merged rather than replaced, the subject cap and whole-file budget mirrored from the dashboard owner, and the writer's refusal to mint a dashboard that does not exist.

---

`DASHBOARD.local.json` has one `quick_status` block and more than one writer.
`@prax`'s dashboard refresh contributes `todo_count` (read straight from
`.trinity/local.json`); Flow's plan push contributes `active_plans` and
`commons_mentions`. Whole-block replacement means last-writer-wins silently
deletes the other's fields — a plan close used to zero the todo count on every
branch card until the next prax refresh.

Flow's push therefore **merges** (`_calculate_quick_status` in
`apps/handlers/dashboard/push_branch_dashboard.py`):

| Keys | Behaviour |
|------|-----------|
| `active_plans`, `commons_mentions` | recomputed — Flow is the authority |
| `new_mail`, `opened_mail` | preserved if already set, seeded only when absent (@prax reads `inbox.json` first-hand; we only see the possibly-stale `ai_mail` section) |
| `action_required`, `summary` | recomputed over every counter present, foreign ones included |
| anything else | carried through untouched |

A foreign key named `*_count` holding an integer is additionally read as a
counter, so it still reaches `action_required` and the summary line
(`todo_count: 9` → `"9 todos"`). Every other foreign key is passed through
without interpretation.

### The `flow` Section Shape

Every branch's `DASHBOARD.local.json` carries a `flow` section, `managed_by`
flow, written by `push_flow_to_branch_dashboard()`:

| Field | Shape | Meaning |
|-------|-------|---------|
| `active_plans` | **int** | count of *all* open plans for this branch |
| `open_recent` | list of `{plan_id, subject, created}` | the **5 newest open plans** by created date, newest first |
| `recently_closed` | list of `{id, subject, closed}` | last 5 closed within 7 days |
| `total_plans` | int | every plan ever filed for this branch |

`open_recent` is the bounded reading window: agents get their bearings from 5
named plans plus a total, never from a wall of rows. **The cap is enforced in
the renderer** (`_build_open_recent`, `OPEN_RECENT_LIMIT = 5`), not in the
consumer — a reader that has to remember to slice will eventually forget. The
full list lives behind `drone @flow list open`, on request.

**`active_plans` is a count, not a list** — ruling of 2026-08-16 (the owner, via
`@devpulse`). Flow's push used to publish every open-plan row here; on a branch
with 23 open plans that was 6,096 of the section's 8,552 bytes, and it was the
unbounded context the ruling exists to kill. The list left the section
entirely, and `active_count` collapsed into this one name. The int also matches
what `@prax`'s refresh already writes, so the field means the same thing no
matter which writer built the section.

Card values are written per-branch on plan events, so a change to this contract
only reaches a branch that files a plan afterwards — a quiet branch keeps the
old shape indefinitely. `push_flow_to_all_branch_dashboards()` sweeps every
branch Flow holds plans for and is how a contract change lands fleet-wide.
Paths without a dashboard are skipped, never created.

> **Two writers, one section.** `@prax`'s dashboard refresh also builds this
> section, wholesale (`recently_closed` as `{plan_id, subject}`, and no
> `open_recent` / `total_plans`). Whichever writer ran last wins the whole
> section — the per-key merge above protects `quick_status` only, not section
> level. `active_plans` now agrees across both writers; `open_recent` should
> still be read as present-or-absent until `@prax`'s side is aligned.

---

