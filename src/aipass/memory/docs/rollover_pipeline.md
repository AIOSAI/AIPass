[<- Back to the README](../README.md)

# The rollover pipeline

**Branch** memory · **Code** `apps/modules/rollover.py`, `apps/handlers/rollover/`, `apps/handlers/monitor/`

Everything below is the machinery *behind* `drone @memory rollover run|check|status` and the
`watch` daemon that fires it. The verbs themselves are in `drone @memory --help`; the bare
`drone @memory` prints the live module inventory.

---

## The json handler is the fleet's one service

`apps/handlers/json/json_handler.py` is not an implementation. It is the fleet shim, binding the public names of `aipass.prax.json_handler` to a
handle for this branch and adding nothing. It BINDS rather than wraps — every name is the service's
own callable, so the service resolves the calling module and this branch's `memory_json/` directory
itself, per call. The file is byte-identical in every branch by design and @seedgo checks it by
hash, not by reading it. Anything this
branch needs beyond the service belongs in a module of its own, never in this file.

---

## Rollover pipeline

```
detector.check_all_branches()        # scan AIPASS_REGISTRY.json + external registries
→ _should_rollover(file)             # ENTRY COUNTS ONLY — no line-count trigger, no 600 fallback
                                     # regular sessions > count (default 15), auto-compact lane
                                     # against auto_compact_cap (3), key_learnings, observations
                                     # per_branch[branch][file_type] → defaults[file_type]
                                     # no limit either place = CONFIG GAP, logged, skipped
                                     # unparseable file = logged, skipped — never a fallback
→ orchestrator.execute_rollover()
  → extract_items()                  # the len - count oldest entries; none at exactly the limit
  → embed via subprocess             # fastembed (ONNX) — see vector_search.md re: venv
  → upsert in ChromaDB               # content-hash IDs (sha256[:16]), no duplicates
  → commit_trimmed()                 # the file is written LAST, only once the store holds the entries
```

A refused embed or store leaves the live file untouched; the next run upserts the same content-hash
IDs, so a retry never duplicates. The watcher skips the rollover outright when the store's
dependencies are missing.

`commit_trimmed()` re-reads the file before it writes. Storage takes seconds, and the owner may edit
the file meanwhile; when the file moved since extraction, only the archived entries leave the fresh
image, so a todo, a meta line or an entry written during storage stays.

**Todos are not in this pipeline.** `detector.check_all_branches()` never counts them, so the fleet
walk never rolls a pad. `rollover run` rolls ONE branch's pad before the walk (file only, no
embedding) and `rollover check` counts it after — see
[todos_and_backlog.md](todos_and_backlog.md).

---

## A rollover normalizes the branch it touched

After `rollover run` rolls a branch, it re-renders **that branch's** machine
frame — `handlers/rollover/normalizer.py`, called from `rollover._normalize_rolled()`. The frame is
built by `trinity_push.build_frame`, the same function the push's step 1 uses, so there is one
renderer rather than two free to drift: closed `document_metadata`, `managed_by` in exact
branch-directory casing, `_usage` and `guidelines` verbatim from the gold templates, all four
`*_meta` lines re-composed from config.

It **never prunes.** Every entry carries over exactly as found, canonical or not — pruning is the
push's mandate and the push earns it with a report, a verified vector round-trip, a receipt and an
in-file note.

It is **scoped to the branches this run actually rolled**, like the tab refresh beside it:
`normalize_branch()` takes one branch and touches one branch, and there is no fleet entry point in
that handler on purpose. A rolled branch the fleet scope cannot see is logged by name, never silently
skipped.

---

## One definition of the fleet

`handlers/monitor/registry_scope.py` answers "which
branches are ours" once, for three tiers:

| tier | where it is found | what makes it a member |
|---|---|---|
| `core` | `AIPASS_REGISTRY.json` at the repo root | listed and `active` |
| `resident` | `projects/*/*_REGISTRY.json` | its passport declares `citizenship.residency: "resident"` |
| `external` | a registry at the top level of a **declared** root | a passport EXISTS — presence, not declaration |

`modules/fleet.py` is the public door; cross-branch callers import from there, never from the handler.
`fleet_branches()` gives the live count; this document does not.

There is no list of residents anywhere: a project joins by saying so in its own passport
(`citizenship.residency`), inside a registry the walk discovers. That is why `marketstand(on _hold)`,
`active` in a registry inside a directory whose name says otherwise, needs no special case. A
resident never depends on some caller's cwd having persisted its registry into
`known_registries.json`.

**The walk law:** one shallow glob at a declared root's top level for `*_REGISTRY.json`, then that
registry's own branches. Never a passport walk: a project's `.backup/` copies of its passport are still declarations, so a
passport walk would over-count. A root that overlaps AIPass home is refused in
either direction; a root holding several registries is a named refusal, not a `sorted()[0]` pick.

**Declaration order is the order.** `declared_roots()` returns rows in file order, first
declaration wins a duplicate, and an N-root tie is broken by *declaration* order, never by
alphabetical-by-resolved-path. Both would be deterministic; only the rows a human wrote carry intent.

---

## The external tier declares itself

The external tier has its own anchor. `AIPASS_ROOTS.json` sits beside
`AIPASS_REGISTRY.json` and is the same species: blessed, the trust anchor of a tier. Paths are
relative to AIPass home so `/home/<someone>` stays out of a public repo.
`handlers/monitor/roots_file.py` is the write half behind `drone @memory roots` — it refuses to
overwrite an existing anchor (unreadable is not absent), and `heal` is a verb you type, never
something that happens to you: it preserves the original bytes to `AIPASS_ROOTS.json.corrupt`,
reports the path-shaped strings it can see, and writes none of them back.

**One consumer subtracts a tier on purpose.** `trinity_push.resolve_scope()` drops `external`, because
every other consumer of `fleet_branches()` reads and the push WRITES. Nothing in this branch writes
into another repository, and the push is not the exception.

---

## Safety valve and the two session lanes

`sessions` holds two lanes with separate budgets: regular entries against `count`, and AUTO-COMPACT
SNAPSHOT entries (`status == "auto-compact"`) against `auto_compact_cap`. Snapshots never push regular
sessions out early, and vice versa.

Before archiving a tail entry as "oldest", `_is_misplaced_entry()` holds back anything that looks like
a fresh write landed at the wrong end — numbered above the array head, or dated today.

The **date** half is off for the snapshot lane (`date_guard=False`). Snapshots are machine-written
several times a day, so at cap the oldest one is nearly always dated today: with the date rule on, the
valve would refuse every candidate and the lane could never drain. Ordering says which snapshot is oldest there, not the date. Numbering still guards both lanes,
and when an entry carries no usable `number` the date rule stays on regardless of the caller.

---

## Newest-first guardrail (normalize)

`sessions`, `key_learnings`, `todos` and `observations` are newest-first by contract — rollover
archives the **tail** as "oldest", so a misordered array is silent memory loss.
`normalize_memory_file()` re-sorts them by `number`, and **never fails open silently**:

- **Per-entry tolerance.** An entry whose `number` cannot be read as an int keeps its exact index; the
  readable entries beside it are still ordered among the slots they occupy. One bad row does not
  forfeit protection for the whole container.
- **Loud skip.** Every unreadable row is reported — `result["warnings"]` names the container and the
  offending indices and a prax `WARNING` is logged. Warnings are *not* mutations, so a file with
  nothing to change is left byte-identical.
- **Type repair.** A `number` stored as a numeric string (`"171"`) or integral float is coerced to
  `int`, recorded in `changes`, and persisted, so a half-repaired container heals itself rather than raising `TypeError` inside
  `sorted()`.
- A container with **no** numbers at all is skipped silently — that is a legitimate shape, not
  corruption.

---

## Related

- [cli_surface.md](cli_surface.md) — the entry point, the refusals, and the `watch` module
- [vector_search.md](vector_search.md) — the embed/store half of the pipeline
- [trinity_standard.md](trinity_standard.md) — the write gate a rollover's write must pass
- [trinity_push.md](trinity_push.md) — the lane that prunes, which a rollover never does
- [todos_and_backlog.md](todos_and_backlog.md) — the pad lane that sits beside the fleet walk
- [config_verbs.md](config_verbs.md) — where the counts this engine reads come from
