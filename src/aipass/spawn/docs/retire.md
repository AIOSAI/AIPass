[<- Back to the README](../README.md)

# Retiring a citizen or a project — delete, retire-project, receipts

**Branch** spawn · **Code** `apps/handlers/delete_ops.py`, `apps/handlers/deletion_receipts.py`,
`apps/handlers/repair_ops.py` (`ARCHIVE_EXCLUDE`), `apps/modules/delete.py`,
`apps/modules/retire_project.py`

Usage is in `drone @spawn delete --help` and `drone @spawn retire-project --help`; preview is
available on both and confirmation is explicit. Everything below is what retirement means
once it runs.

---

## The lane

Resolve the branch from the registry: `@name` reads the registry above the current
directory; a path (any target with a `/` or `\`) keeps its case and reads the
`*_REGISTRY.json` that seals that path, matching the entry by resolved path. The path form is
how one seat reaches a branch in another project. Then archive the whole tree into `.archive/`, remove the
live directory, then deregister the entry. The order matters: the archive is the only copy
once the tree is gone, so anything left behind at archive time is lost. The whole
`.trinity/` travels with it — passport, memories and the birth receipt — because a retired
citizen's identity is the part worth keeping, and `tests/test_birth_receipt.py` pins that it
arrives.

The archive copy skips rebuildable noise only — `ARCHIVE_EXCLUDE` is `.venv`,
`__pycache__`, `node_modules`, `.pytest_cache`. `.git` history and `.chroma` vectors are
archived, since the tree is removed after the copy. The same set guards the relocation lane
in [registry_and_repair.md](registry_and_repair.md).

The registry entry is removed under `registry_lock`, reloaded inside it, before the tree is
touched. A failed save deletes the partial archive, leaves the branch registered and in
place, and exits 1.

---

## Delete refuses protected branches; `--retire` is the door for a live citizen

`is_protected()` guards three layers, any one sufficient:

1. The hardcoded floor — the branch factory, the orchestration branch and the router.
2. A registry entry carrying `owner: true`.
3. A passport with `citizenship.registered: true`.

Since `create` writes `registered: true`, a branch is protected from the moment it exists,
and a plain `delete` refuses it, naming the flag that retires it.

`drone @spawn delete @branch --retire` clears layer 3 only: layers 1 and 2 still refuse, and
the confirmation prompt still runs unless `--yes` is given. After the archive is written, the
ARCHIVED passport is rewritten with `citizenship.registered: false`, then the branch is
deregistered and its directory removed. The live passport is never edited: if the archive or
that rewrite fails, the branch stays whole, registered and protected. `--retire --dry-run`
previews and writes nothing.

The infrastructure, owner and active-citizen refusals all exit non-zero. In AIPass the
owner entry also sits on the floor; in an external project the owner is that project's first
citizen, and `delete` refuses it by path too. An owner leaves only with its whole project,
through `retire-project`.

---

## `retire-project`: a whole project, from the admin seat

`drone @spawn retire-project <project_root> --yes` retires a project, owner included. Guards,
in order: the root must not be or hold the AIPass root; it must be a directory with a
`*_REGISTRY.json` directly in it; `--yes` runs only when ai_mail's verified-caller rail
answers that the caller is the admin seat (`is_verified_admin_caller()`, five legs). Without
`--yes` or `--dry-run` it refuses.

The order: build and validate every receipt row; copy the whole tree (minus `ARCHIVE_EXCLUDE`)
to `<AIPass>/.archive/deleted_branches/<project>_<timestamp>/`, the fleet's deleted-branches
store, since the project's own `.archive/` leaves with its tree; rewrite each archived
citizen's passport to `registered: false`; revoke the project's hooks trust entry; remove the
tree last. A failure before the removal deletes the partial archive and leaves the project
whole.

`--dry-run` runs from any seat: it lists each thing that would go with its size and entry
count, the archive path, whether this seat could run `--yes`, and writes nothing.

---

## Receipts

Every removal writes rows to the fleet deletion trail, `<AIPass>/.ai_central/deletions.jsonl`,
through `@drone`'s `door_deletion_log.record_deletion`, beside `drone rm`'s own rows. Rows are
measured and validated before anything is removed: drone's door writes on call and refuses a
row missing `lane`, `outcome`, `caller`, `resolved` or `target`, so a row that would be
refused stops the removal instead.

| Field | `delete` | `retire-project` |
|-------|----------|------------------|
| `lane` | `spawn_delete` | `spawn_retire` |
| `outcome` | `deleted`, `retired` with `--retire`, `failed` if the tree did not go | `retired`, or `failed` |
| rows | one, the branch directory | one per citizen, the registry file, the project root, and the trust entry when one existed |
| `caller` | the verified caller, `unknown` when unprovable (as `drone rm` records) | the verified caller; empty refuses |
| `target` | the archive path | the archive path |

Each row also carries `requested`, `path`, `reason` (naming the registry), the time, the cwd
and drone's measurement (`kind`, `size_bytes`, `entry_count`, `measured`). Read them back with
`grep spawn_retire .ai_central/deletions.jsonl` (or `spawn_delete`) from the AIPass root.
Spawn's own `delete_executed` and `project_retired` log entries carry the caller and the
registry or archive too.

---

## What retirement does not do

It does not delete an archive, and it does not clean up mail, plans, memory vectors or
census entries that named the branch or project. Those live with the branches that own them.

---

**Last Updated:** 2026-10-24
