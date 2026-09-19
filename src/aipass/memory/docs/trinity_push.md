[<- Back to the README](../README.md)

# The trinity push

**Branch** memory · **Code** `apps/modules/push.py`, `apps/handlers/templates/trinity_push.py`

`drone @memory push` is the one lane that brings a branch's `.trinity/` files to the trinity
standard (DPLAN-0318, built 2026-08-27). Per branch it does exactly three things:

1. **Re-renders the machine frame.** `document_metadata` is rebuilt as a **CLOSED set** — any key
   the standard does not name is pruned, `status` with it; `managed_by` takes the exact branch
   **directory** name (what @seedgo's checker compares against — the registry's own `name` field
   disagrees in casing for six citizens); `_usage` and the `guidelines` block come **verbatim** from
   the gold-source templates; all four `*_meta` lines are re-composed from config + template prose.
2. **Prunes every non-canonical entry — and moves todos to a file, never to vectors.** See the law
   below, and *Todos go to the backlog, never to vectors* under it.
3. **Writes one canonical session note** in the branch's own `sessions[]` saying where its entries
   went, how to get them back, and which todos moved to the backlog. Skipped entirely when nothing
   was archived and no todo moved.

Then it stamps `.template_version.json` via `receipt.py` with `stamped_by: "memory push"` — the
push-lane wiring the receipt build left pending.

---

## The law: vectorize → VERIFY → prune

Pruning is a safety feature, not a deletion. Each entry is serialized **verbatim** (the stored
document *is* the entry as JSON, never a summary), embedded into both the branch's local `.chroma`
and the global store, and then **read back by ID and compared byte-for-byte** to what was sent. Only
then is it removed from the live file.

**If verification fails for any entry, NOTHING is pruned from that branch** and the file is left
exactly as found. A store call's own `success` flag is the writer's opinion; the read-back is the
evidence. This is the same law `vectorize_and_store` was built for after @ai_mail deleted four
months of mail on the strength of an unread success flag — `get_by_ids` (chroma_subprocess 1.5.0)
exists to make the second half of it possible, because `get_by_source` matches a metadata substring
and caps at `n_results`, so a partial hit reads like a full one.

`tests/test_trinity_push.py::TestNothingIsPrunedWithoutProof` pins all six failure shapes: the store
refuses, the vector never lands, it lands corrupted, one of several goes missing, the read-back call
itself fails, and a second destination fails after the first succeeded. Absent and corrupted get
**different** refusal sentences, because the repair differs — the lesson from `missing_field` vs
`unmeasurable`.

---

## What counts as non-canonical

Shape **and** size, because they are two different scan groups in the standard and an entry can pass
one while failing the other. A perfectly-shaped 315-char session summary under a 300 cap is
canonical to look at and still leaves its branch short of 100 — and it is exactly the entry @hooks'
`edit_gate` grandfathers when the write did not author it (refused between 2026-08-27 and 08-30, when
that refusal was found to deadlock rollover). Caps come from
`entry_limits.resolve_entry_types`, the same resolver the write gate and the tab renderer use, so the
push cannot prune on a number the gate does not enforce.

The note the push writes is itself measured against that same gate before it is written. A push that
left behind a note the standard would refuse would have re-introduced, in its own hand, the exact
violation it came to remove.

### The shape lives in the config, not in this module

Until 2026-09-15 `trinity_push.py` carried its own literal copy of the entry shape (`ENTRY_RULES`)
and @seedgo's `trinity_groups` carried a third. Three copies of one contract are three chances for a
push to prune an entry the write gate would have accepted, or to carry one it would have refused.
The shape now has **ONE home** — `entry_limits.entry_types.<type>.fields` in `memory.config.json` —
and `trinity_push.entry_rules(section, cap_spec)` derives the required/optional split from it
(FPLAN-0593 Phase 1). The derivation is mechanical: a field is required when the config says so,
optional otherwise, and `type` is the same three type names both sides already spoke.

- The push hands in its own resolved type definition (`resolve_caps` → `cap_spec`), so a
  `per_branch` override is honoured without ever reaching the global fallback.
- Only that global fallback is cached, so a shape-only caller in a loop does not re-read the config
  per entry.
- An unknown section returns `None` and **stays unknown** rather than quietly becoming an open one.

@seedgo's mirror retires against the same key in Phase 2; see
[trinity_standard.md](trinity_standard.md) for the standard those groups score.

---

## Todos go to the backlog, never to vectors

*Handler 1.2.0, landed 2026-09-15. Supersedes "Todos are never archived" (1.1.0, 2026-08-27), which
kept a non-canonical todo in the file for its own agent to reshape. With nothing moving them,
`status` grew into a log: 190 todos across 18 branches, 106,408 chars of todo JSON, devpulse alone
69,680 (DPLAN-0345, measured 2026-09-15).*

The half of the old rule that stands: **a todo never goes to vectors.** Sessions, key_learnings and
observations are records, and a record in a vector is still a record. A todo is a debt, and a debt
only works if it resurfaces unbidden on the next load; vectorized, it never does. A restored then
re-rolled vector copy would also land a second copy with nothing linking the two (the CPLAN-0002
duplicate).

What changed is where a todo goes when it cannot stay on the pad. The canonical todo is
`{number, date, task, priority?}` — `status` is gone — with `task` held to its entry_limits cap.
`plan_todos` sorts the pad:

- a todo that is not canonical leaves with reason `non-canonical`, in file order. `todo_defect` names
  ONE defect per todo, the first in `DEFECT_ORDER`: not an object > status present > task over cap >
  missing field > unknown field > wrong type;
- then, when the canonical todos left exceed the pad count, the oldest by number leave with reason
  `overflow`.

They land in `.backup/todo/<branch_dir>/backlog.json` json-equal — never reshaped, never shortened.
`move_todos` makes one verified append per reason (append, replace atomically, read back, compare
every record) **before** the pad is written; a failed or mismatched append refuses the branch whole
and leaves its `local.json` untouched. Reshaping by machine is still refused: a machine that rewrites
a 150-char task into 100 has rewritten someone's open work.

There is no migration code. Without `status` in the shape every legacy todo is non-canonical, so the
first push empties those pads into their backlogs and every later push finds nothing to move.

**The report states it on every branch, every run** (`push_report._todo_lines`):

```
   todos N seen · M to backlog (C chars) · K stay on the pad of 10
     reasons: <defect> <count>, …
     backlog .backup/todo/<branch>/backlog.json (exists, appended to | does not exist yet, created by the push; never overwritten)
```

and the fleet totals carry `TODOS TO BACKLOG: N across M branches, C chars`, how the chars are
measured, and the defect order. The in-file session note names the moved numbers and the backlog
(`NOTE_TODOS_NAMED`), stepping down to a bare count (`NOTE_TODOS_COUNTED`) when the names would
bust the session cap it is measured against.

The pad and the backlog file have their own document: [todos_and_backlog.md](todos_and_backlog.md).

---

## Scope

`--branch` pushes one branch. Fleet mode covers the DPLAN scope: the **18** active citizens in
`AIPASS_REGISTRY.json` plus the **4** named resident projects (`baud`, `earmark`, `finch`,
`aipass_site`) — **22** branches.

The resident list is a **named constant, never a glob** over `projects/`. A glob would sweep in
`marketstand`, which is marked `active` inside a directory literally named `(on _hold)`. That constant
moved to `handlers/monitor/registry_scope.py` on 2026-08-27 and `trinity_push` re-exports it, so the
lane that always saw 22 and the lanes that saw 19 now read one list — see
[One definition of the fleet](rollover_pipeline.md#one-definition-of-the-fleet).

A branch whose files cannot be read is **refused by name**, never skipped — and refused *whole*, so
a branch never ends up with one canonical file and one drifted one.

---

## The two gates

- **`--dry-run` writes nothing anywhere** — not the memory files, not the vector store, not the
  receipts. Its report is the artifact, written to `artifacts/push_reports/` and echoed to the
  terminal.
- **A fleet write requires `--confirm`.** Encoding the gate as a flag rather than as an operator's
  memory is the difference between a rule and a hope; this branch has already demonstrated the
  alternative.

---

## Measured live on @canary

Measured 2026-08-27, end-to-end on @canary, the sanctioned guinea pig: **15 entries archived and
pruned, 25 carried over, trinity 77 → 100**, receipt stamped, note written. The promise in that note
was then tested rather than assumed — a `drone @memory search "…" --branch canary` returns pruned
key_learning **#30 verbatim**. Re-running the push prunes 0 and holds 100: the lane is idempotent.

Fleet dry-run the same day: **366 entries to archive, 560 carry over, 22 branches, 0 refused, 0
errors.** Projected by applying the push into a temp copy of each branch's real `.trinity/` and
scoring it with @seedgo's own checker: **fleet average 70.1 → 97.2**.

---

## The todo exemption, as it was measured

*The record of the retired reshape-in-place rule, measured 2026-08-27; the lane these numbers
measured was replaced on 2026-09-15 — see
[Todos go to the backlog, never to vectors](#todos-go-to-the-backlog-never-to-vectors).*

The exemption was proven by replaying @spawn's real incident: its three archived todos recovered
**verbatim from the vectors they were pruned into**, re-inserted into a temp copy of @spawn's live
`.trinity/`, plus one drifted session so the archive lane fired in the same run. Through the real
handler and the real `push_store` against a throwaway `.chroma`: **1 session pruned, 3 todos left in
place byte-identical, note written at 266/300 chars naming all three, report roll-call correct.**
Nothing under `src/aipass/spawn/` was touched.

Fleet dry-run after the change: **0 entries to archive, 582 carry over, 22 branches, 0 todos to
reshape** — the fleet was already canonical, so the fix protects future pushes; the sweep is what
healed that day's.

The one remaining blocker is the **File set** group, and it is **not push scope**: branches carry
stray files in `.trinity/` (mostly `*.pre_v2_backup` / `*.pre_v3_backup` migration leftovers, plus
devpulse's older `*.pre-aipl` pair). Deleting another citizen's files and authoring README prose are
both outside the three-part mandate, so the push **reports** them and leaves them alone. They need a
ruling; with it executed the fleet reaches 100 across the board.

**Re-measured 2026-09-05**, superseding the two 08-27 dry-run figures above: fleet dry-run reports
**13 entries to archive, 835 carry over, 22 branches**, and **4 todos left to reshape across 2
branches** (backup 2, skills 2) — the 08-27 reading of 0-to-reshape was true when taken and drifted
as new todos were written in non-canonical shape. The stray-file count is now **22 branches of the 28
`fleet_branches()` returns, 56 files**; the `.trinity/README.md` half is down to **1** branch
(`wren`, an external root), from 6. The `70.1 → 97.2` fleet-average projection above was **not**
re-run that night and is carried forward from the 08-27 build.

---

## Related

- [todos_and_backlog.md](todos_and_backlog.md) — the pad, the backlog file and the restore verb
- [trinity_standard.md](trinity_standard.md) — the standard this lane pushes to
- [templates_and_tabs.md](templates_and_tabs.md) — the gold templates, the `*_meta` tabs, the receipt
- [vector_search.md](vector_search.md) — where a pruned entry lands and how it comes back
