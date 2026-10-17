[<- Back to the README](../README.md)

# The trinity push

**Branch** memory · **Code** `apps/modules/push.py`, `apps/handlers/templates/trinity_push.py`

`drone @memory push` is the one lane that brings a branch's `.trinity/` files to the trinity
standard. Per branch it does exactly three things:

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

Then it stamps `.template_version.json` via `receipt.py` with `stamped_by: "memory push"`, for
branches it actually changed.

---

## The law: vectorize → VERIFY → prune

Pruning is a safety feature, not a deletion. Each entry is serialized **verbatim** (the stored
document *is* the entry as JSON, never a summary), embedded into both the branch's local `.chroma`
and the global store, and then **read back by ID and compared byte-for-byte** to what was sent. Only
then is it removed from the live file.

**If verification fails for any entry, NOTHING is pruned from that branch** and the file is left
exactly as found. A store call's own `success` flag is the writer's opinion; the read-back is the
evidence. This is the same law `vectorize_and_store` follows. `get_by_ids` (`chroma_subprocess`)
exists to make the second half of it possible, because `get_by_source` matches a metadata substring
and caps at `n_results`, so a partial hit reads like a full one.

`tests/test_trinity_push.py::TestNothingIsPrunedWithoutProof` pins all six failure shapes: the store
refuses, the vector never lands, it lands corrupted, one of several goes missing, the read-back call
itself fails, and a second destination fails after the first succeeded. Absent and corrupted get
**different** refusal sentences, because the repair differs, as with `missing_field` vs
`unmeasurable`.

---

## What counts as non-canonical

Shape **and** size, because they are two different scan groups in the standard and an entry can pass
one while failing the other. A perfectly-shaped 315-char session summary under a 300 cap is
canonical to look at and still leaves its branch short of 100 — and it is exactly the entry @hooks'
`edit_gate` lets through when the write did not author it. Caps come from
`entry_limits.resolve_entry_types`, the same resolver the write gate and the tab renderer use, so the
push cannot prune on a number the gate does not enforce.

The note the push writes is itself measured against that same gate before it is written: a push that
left behind a note the standard would refuse would re-introduce, in its own hand, the exact
violation it came to remove.

### The shape lives in the config, not in this module

Three copies of one contract are three chances for a push to prune an entry the write gate would have
accepted, or to carry one it would have refused. The shape has **ONE home**:
`entry_limits.entry_types.<type>.fields` in `memory.config.json`. `trinity_push.py` holds no copy of
it; `trinity_push.entry_rules(section, cap_spec)` derives the required/optional split from it. The
derivation is mechanical: a field is required when the config says so, optional otherwise, and
`type` is the same three type names both sides speak.

- The push hands in its own resolved type definition (`resolve_caps` → `cap_spec`), so a
  `per_branch` override is honoured without ever reaching the global fallback.
- Only that global fallback is cached, so a shape-only caller in a loop does not re-read the config
  per entry.
- An unknown section returns `None` and **stays unknown** rather than quietly becoming an open one.

@seedgo's `trinity_groups` scores the same standard; see [trinity_standard.md](trinity_standard.md).

---

## Todos go to the backlog, never to vectors

**A todo never goes to vectors.** Sessions, key_learnings and
observations are records, and a record in a vector is still a record. A todo is a debt, and a debt
only works if it resurfaces unbidden on the next load; vectorized, it never does. A restored then
re-rolled vector copy would also land a second copy with nothing linking the two.

When a todo cannot stay on the pad it goes to the backlog file. The canonical todo is
`{number, date, task, priority?}`, with no `status` field, and `task` held to its entry_limits cap.
`plan_todos` sorts the pad:

- a todo that is not canonical leaves with reason `non-canonical`, in file order. `todo_defect` names
  ONE defect per todo, the first in `DEFECT_ORDER`: not an object > status present > task over cap >
  missing field > unknown field > wrong type;
- then, when the canonical todos left exceed the pad count, the oldest by number leave with reason
  `overflow`.

They land in `.backup/todo/<branch_dir>/backlog.json` json-equal — never reshaped, never shortened.
`move_todos` makes one verified append per reason (append, replace atomically, read back, compare
every record) **before** the pad is written; a failed or mismatched append refuses the branch whole
and leaves its `local.json` untouched. Reshaping by machine is refused: a machine that rewrites
a 150-char task into 100 has rewritten someone's open work.

There is no migration code: a todo carrying `status` is non-canonical, so a push moves it to the
backlog like any other.

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

`--branch` pushes one branch. Fleet mode covers `trinity_push.resolve_scope()`: the `core` and
`resident` tiers of `fleet_branches()` (`handlers/monitor/registry_scope.py`, through
`modules/fleet.py`), never the `external` tier, because the push writes. Residents are not a list:
they are the branches of `projects/*/*_REGISTRY.json` whose passport declares
`citizenship.residency: "resident"`, so `marketstand`, marked `active` inside a directory named
`(on _hold)`, is not swept in. Every lane reads the same definition; see
[One definition of the fleet](rollover_pipeline.md#one-definition-of-the-fleet).

A branch whose files cannot be read is **refused by name**, never skipped — and refused *whole*, so
a branch never ends up with one canonical file and one drifted one.

---

## The two gates

- **`--dry-run` writes nothing anywhere** — not the memory files, not the vector store, not the
  receipts. Its report is the artifact, written to `artifacts/push_reports/` and echoed to the
  terminal.
- **A fleet write requires `--confirm`.** Encoding the gate as a flag rather than as an operator's
  memory is the difference between a rule and a hope.

---

## What the push leaves alone

Files in a `.trinity/` that are not push scope (stray files, migration backups) are **reported, never
deleted**: deleting another citizen's files and authoring README prose are both outside the
three-part mandate. See *Strays* in [templates_and_tabs.md](templates_and_tabs.md).

---

## Related

- [todos_and_backlog.md](todos_and_backlog.md) — the pad, the backlog file and the restore verb
- [trinity_standard.md](trinity_standard.md) — the standard this lane pushes to
- [templates_and_tabs.md](templates_and_tabs.md) — the gold templates, the `*_meta` tabs, the receipt
- [vector_search.md](vector_search.md) — where a pruned entry lands and how it comes back
