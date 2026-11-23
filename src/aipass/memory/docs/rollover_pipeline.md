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
itself, per call. The file is byte-identical in every branch by design and @sentry checks it by
hash, not by reading it. Anything this
branch needs beyond the service belongs in a module of its own, never in this file.

---

## Rollover pipeline

```
detector.check_all_branches()        # walk detector.write_scope(): core, residents, callers, declared externals
→ _should_rollover(file)             # ENTRY COUNTS ONLY — no line-count trigger, no 600 fallback
                                     # regular sessions > count (default 15), auto-compact lane
                                     # against auto_compact_cap (3), key_learnings, observations
                                     # per_branch[branch][file_type] → defaults[file_type]
                                     # no limit either place = CONFIG GAP, logged, skipped
                                     # a DAMAGED file is never a trigger (below)
→ orchestrator.execute_rollover()
  → extract_items()                  # the len - count oldest entries; none at exactly the limit
  → embed via subprocess             # fastembed (ONNX) — see vector_search.md re: venv
  → upsert in ChromaDB               # content-hash IDs (sha256[:16]), no duplicates
  → commit_trimmed()                 # the file is written LAST, only once the store holds the entries
```

A refused embed or store leaves the live file untouched; the next run upserts the same content-hash
IDs, so a retry never duplicates. An ID is `<branch>_<type>_<hash>` with the branch label in
lowercase; rows stored before that carry a capitalised label and stay as they are, so a text stored
under both labels holds two rows. The watcher skips the rollover outright when the store's
dependencies are missing.

`commit_trimmed()` re-reads the file before it writes. Storage takes seconds, and the owner may edit
the file meanwhile; when the file moved since extraction, only the archived entries leave the fresh
image, so a todo, a meta line or an entry written during storage stays.

**Todos are not in this pipeline.** `detector.check_all_branches()` never counts them, so the fleet
walk never rolls a pad. `rollover run` rolls ONE branch's pad before the walk (file only, no
embedding) and `rollover check` counts it after — see
[todos_and_backlog.md](todos_and_backlog.md).

A trigger the extractor skips is a file over its limit that was not rolled: `rollover run` prints
it through `error()`, so the run exits 2, never "complete" with exit 0.

---

## A damaged file is refused by name

`detector.damage_in()` is the one judge, shared by the detector, the extractor and `lint`. A file is
damaged when it is empty or not valid JSON, when its top level is not an object, when a capped
container (`sessions`, `key_learnings`, `observations`) is neither a list nor a 2.0.0 dict, or when
a list over its count holds an entry rollover cannot order: no int `number`
(`sessions[0] (sessions entry) has no 'number'`) or a repeated one
(`sessions[16] repeats number 2 of sessions[0]`).

A damaged file is never a trigger. `rollover check`, `run` and `status` list it with its reasons
through `error()` (exit 2), and `extract_items` refuses it with the same words if it is handed one
anyway. Rollover never numbers an entry or reshapes a container itself: a person repairs it.

Why each shape is refused, not rolled:

- **No number.** With an unnumbered head the valve below loses its number rule and falls back to
  dates, so on the day the entries were written every tail candidate is held back and nothing drains.
- **A repeated number.** The extractor re-sorts by `number` before taking the tail, so a newest entry
  that reuses an old number moves into the tail and is archived as oldest history.
- **Oldest-first is not damage.** The re-sort archives the lowest numbers and the trim persists the
  newest-first order, so it rolls. `lint` and `health` still name it.

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
that handler on purpose. The rolled names are matched against `detector.write_scope()`, the scope
that rolled them, so a declared external heals like a core branch. A rolled branch that scope cannot
see is logged by name, never silently skipped.

---

## One definition of the fleet

`handlers/monitor/registry_scope.py` answers "which
branches are ours" once, for three tiers:

| tier | where it is found | what makes it a member |
|---|---|---|
| `core` | `AIPASS_REGISTRY.json` at the repo root | listed and `active` |
| `resident` | `projects/*/*_REGISTRY.json` | its passport declares `citizenship.residency: "resident"` |
| `external` | a registry at the top level of a **declared** root | a passport EXISTS — presence, not declaration |

Cross-branch callers import through the package door, `from aipass.memory import fleet_branches`, never from the handler.
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

**One consumer subtracts a tier.** `trinity_push.resolve_scope()` drops `external`: the template push
(`templates bump`, the prune and re-frame) stops at the repo edge. Every other write lane serves the
declared externals, below.

---

## The write fence: services write where they serve

`handlers/write_fence.py` is the one gate every memory writer passes: `fence_write(path, lane=...)`.
A write is admitted when its **resolved** path is the AIPass root or under it, or is a branch
directory of a declared root or under one (`registry_scope.external_branches()`: a row in that
root's registry with a passport on disk). Nothing else. Containment is judged on resolved paths,
never `startswith`, so `/x/aipass_other` is not inside `/x/aipass` and a symlink cannot carry a write
out. A declared root's own files and directories outside its branches stay refused, and so does a
listed branch with no passport.

A refusal is an ERROR naming the lane, the path and the root, and a `write_fence_refused` line in
the operation log. A root that resolves to the filesystem root fences nothing, so it admits nothing,
external or not.

## Which scope each lane reads

| scope | holds | read by |
|---|---|---|
| `detector.write_scope()` | core, accepted residents, caller registries inside the root, declared externals | the rollover walk, the local `.chroma` lookup, a plan's owner, `rollover backfill-local`, the frame re-render, the tab refresh, the watcher |
| `detector.read_scope()` | the write scope, plus any declared external it left out by name | `health`, `lint`, `rollover config` |
| `todo_roll.in_scope_branches()` | `fleet_branches()`, all three tiers | the todo roll, `rollover run/check --branch`, `todo restore` |
| `trinity_push.resolve_scope()` | `fleet_branches()` less `external` | the template push |

Every write lane matches a branch by **name**, so the write scope never holds two branches under one
name: a declared external whose name a core or resident branch already holds is left out of it and
named in a WARNING. The read scope still names it. The todo lane refuses a shared directory name
outright, since two pads would merge into one backlog.

A declared external rolls like a core branch: its files are trimmed in place, its entries are stored
in its own `<branch>/.chroma` and in the global store, its todo pad rolls to
`.backup/todo/<branch>/backlog.json` under the AIPass root, and its frame, tabs and template receipt
are written in its own `.trinity/`.

## Plans land in both stores

`process-plans` stores each archived plan's chunks in the global `flow_plans` collection (label
`flow`) and in its owner's local `<branch>/.chroma`, collection `flow_plans`, with the same
content-hash IDs through the same chroma lane. The owner is the plan file's own `**Branch**:` line,
a name or a path, resolved inside the archive's project (`project` tag) against the write scope. A
resident project nested in the host is its own project, so a name shared across projects never
crosses. The local write goes through `local_store_lookup`, so it passes the write fence, and it
must land on that same citizen's store. Each chunk carries a `branch` tag naming its owner.

A plan whose Branch line resolves to no one citizen is logged by name and stored globally only, and
its manifest row is written. A local store that fails keeps the global write, and the plan gets no
manifest row, so the error is reported and the next run retries both. The global upsert is
idempotent.

## Backfilling the local stores

`drone @memory rollover backfill-local [--branch @name] [--apply]` copies rows from the global store
into each write-scope branch's local store: `<branch>_local`, `<branch>_observations` and the
`flow_plans` chunks it owns. A chunk's owner is its `branch` tag. An untagged chunk uses its
`project` with the Branch line in any chunk of the same file, or in the archived file itself. A
chunk with no `project` tag has no owner and stays global only. Rows are copied as stored (ids,
embeddings, documents, metadatas), with no re-embedding and no renaming, so a capitalised
`FLOW_plans_...` id stays as it is. `add_missing` never touches an id the local store already holds,
so a re-run adds nothing.

It is a dry run by default and prints, per branch and collection, how many rows it would copy and
how many are already present. `--apply` writes. @memory's own store is the global store, so it is
skipped. Only @memory's seat or the verified admin may run it (`caller_gate`, the rail `rollover run
--branch` uses). Any other seat gets the mail-@devpulse sentence and exit 2.

---

## Safety valve and the two session lanes

`sessions` holds two lanes with separate budgets: regular entries against `count`, and AUTO-COMPACT
SNAPSHOT entries (`status == "auto-compact"`) against `auto_compact_cap`. Snapshots never push regular
sessions out early, and vice versa.

Before archiving a tail entry as "oldest", `_is_misplaced_entry()` holds back anything that looks like
a fresh write landed at the wrong end — numbered above the array head, or dated today.

The **date** half is off for the snapshot lane (`date_guard=False`). Snapshots are machine-written
several times a day, so at cap the oldest one is nearly always dated today: with the date rule on, the
valve would refuse every candidate and the lane could never drain. Ordering says which snapshot is oldest there, not the date. Numbering still guards both lanes;
an over-count list with an entry carrying no usable `number` is damaged and never reaches the valve.

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
