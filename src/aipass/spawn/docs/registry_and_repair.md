[<- Back to the README](../README.md)

# The registry, sync, repair and the admin ceremony

**Branch** spawn · **Code** `apps/handlers/registry.py`, `apps/handlers/sync_registry_ops.py`,
`apps/handlers/repair_ops.py`, `apps/handlers/passport_migration.py`,
`apps/handlers/seed_ops.py`, `apps/handlers/regenerate_registry_ops.py`,
`apps/modules/` (`sync_registry.py`, `repair.py`, `migrate_passports.py`,
`export_vault.py`, `regenerate_registry.py`, `grant_admin.py`)

Flags and usage are in `drone @spawn --help` and each verb's own `--help`. Everything below
is the behaviour behind them.

---

## What sync-registry does

It compares `AIPASS_REGISTRY.json` against the filesystem and reports healthy, stale, damaged
and unregistered branches. Stale means the folder is gone, and only a stale entry is ever removed.
Damaged means the folder is on disk but its passport is missing: the entry stays, the report
names it with the cure, `aipass doctor --fix`, and the command exits 1.

A lost owner passport is never a vacancy. `--check` flags `owner_passport_missing`, naming the
path, and the owner reconcile under `--fix` changes nothing, logs an error and names the same
cure, so the seat never moves to another citizen. The scan is CWD-first, so it works inside an external project: it
checks the project root, then `src/*`, then `src/*/*`, and a directory counts as a branch
when it holds `.trinity/passport.json`. It is a stat-level walk — it never reads a README,
a prompt or a dashboard.

Three modes past the bare report: `--fix` rebuilds `.spawn/` tracking, registers strays and
repairs passport `registry_id` values; `--fix --dry-run` previews exactly that;
`--check` (optionally `--json`) is the read-only owner and identity health check, which
writes nothing and answers with an exit code.

Sync acts on ONE registry, never the fleet: a named `[project-path]` is the registry every step
reads and writes, and with none it takes the nearest `*_REGISTRY.json` walking up from the cwd.
A path with no registry above it, or no registry above the cwd, exits 1 and never falls back. A registry that exists
but will not parse is refused by the sync, `--fix` and `--check` alike (`--check` flags
`unreadable_registry`): rebuilding it would re-mint the project. Each refusal names the way out,
`drone @spawn sync-registry --rebuild`. Under `--fix`, a stale entry
whose branch is found elsewhere in the project has its `path` rewritten, so `owner`, `admin`
and `registry_id` stay; directory names are keyed through `normalize_branch_name`, so
`my-agent` on disk matches `my_agent`. Every registry writer holds `registry_lock` (`flock`
on `.<stem>.lock`) and loads inside it.

`--rebuild` is for a registry that will not parse (empty, `[]`, truncated, or JSON with garbage
after it); a registry that parses is refused untouched and pointed at `--fix`. It reads the
passports the sync scan finds under the registry's folder. Their `citizenship.registry_id` becomes
`metadata.id`, and if they do not all carry the same one the rebuild refuses and names each.
Each passport becomes a row the way `--fix` registers a stray, keeping its `citizen_id` as the
row's `registry_id`. Without `--confirm` it writes nothing and prints the rows it would write. With
`--confirm` the corrupt file is moved aside as `<name>.corrupt-<YYYYmmdd-HHMMSS>` beside it, never
deleted, and the new registry is written atomically. The owner seat is set as a fresh project's is.
`admin` and `ci_cure` are not restored: only their ceremonies write them, so the rebuild lists
`drone @spawn grant-admin` and `drone @spawn grant-ci-cure` to re-run. Spawn's package door
exposes `rebuild_registry`, so `aipass doctor` can call it while drone cannot route `@spawn`.

---

## Registry entry shape — the name is lowercase, the path relative

The system stores an agent's name in lowercase. Every row spawn writes carries the name
in lowercase, hyphens as underscores, and a path relative to the registry's own folder. That
covers `create` (mint and adopt), `add_to_registry`, `sync-registry --fix`, `--rebuild` and
`repair --rename`. `normalize_branch_name` defaults to lowercase. A target outside the
registry's project is refused, never written with an absolute path. The project's own name (the
registry file's stem and `metadata.name`) is not an agent name and stays as it is.

A registry written before this rule can still hold capital rows beside lowercase ones. Spawn
reads such a registry by folding case on both sides. The duplicate guards in `create` and
`add_to_registry` treat `FLOW` and `flow` as one agent, so no writer adds a second row
for a name already present in the other case. Spawn's writers leave an existing capital row's
name as they find it; only `repair --rename` rewrites a name, and it writes lowercase.

Such a registry is converted with `drone @spawn sync-registry <registry-or-project> --lowercase`.
The argument names the registry file itself or a folder to walk up from, so the fleet registry and
each exterior project's are converted one at a time. Without `--confirm` it prints each row that
would change (old name -> new name, old path -> new path) and writes nothing, exiting 1 when there
is something to convert and 0 when there is not. With `--confirm` it copies the registry byte for
byte to `<name>.pre-convert-<YYYYmmdd-HHMMSS>` beside it, prints that path, then writes the
converted registry under `registry_lock` with an atomic replace. Each name becomes
`normalize_branch_name(name)`, the dict-form key moving with it. Each absolute path becomes
relative to the registry's folder. Every other key (`owner`, `admin`, `ci_cure`, `registry_id`,
`email`, dates, keys spawn does not know) and the row order are kept, and `metadata` changes only
in `last_updated`, the stamp every registry writer sets. It refuses, writing nothing and exiting 2,
when two rows fold to one name (it names both; choosing which row lives is the operator's call),
when a row's path is outside the registry's folder (it names the row), or when the file does not
parse (that is `--rebuild`'s case). A second run finds nothing to convert and says so.

The same lane reaches each registered citizen's own copies of its name: the certificate's `owner`
in `artifacts/birth_certificate.json` and the passport's `branch_info.branch_name` in
`.trinity/passport.json`, found under the row's path. The preview lists each file and the one value
that would change. Only that value's bytes are rewritten, in place and atomically: key order,
indent, the certificate's `name` and `description` prose and the trailing newline stay as written.
A missing or unreadable file is skipped and named, not an error. A certificate that carries a
`signature` is signed over its content, so if its `owner` would change the whole run is refused,
naming the file, and exits 2. New citizens are born with both values in lowercase.

---

## Passport migration

`migrate-passports` is the one-shot fleet migration to schema 2.0. It is
dry-run by default, can be restricted to a single branch, can be pointed at another repo
root, and backs each passport up before writing. It either completes a passport or raises;
there is no partial write.

The citizens it walks are the ones @memory's door (`fleet_branches`) answers for the root:
core, resident and external, each with the residency the door gives it. Spawn keeps no census
and no expected count; the receipt's `Fleet:` line is the count the door answered, by tier. A
citizen with no passport on disk is skipped and logged. An external passport keeps its own
`registry_path`: the bare `*_REGISTRY.json` reconcile to `AIPASS_REGISTRY.json` is for core and
resident passports only.

A run against a root with no discoverable passports **refuses** rather than reporting
success — see [cli_contract.md](cli_contract.md) for why that distinction is load-bearing.

---

## Passport vaults

`export-vault` regenerates each branch's tracked `.aipass/passport.vault.json` from its live
passport, stripping machine-local values, and moves an older `passport.seed.json` into the
seat's `.spawn/.recovery/`. `export-seeds` is refused and names `export-vault`. Dry-run by default; `--only` restricts to one
branch and `--root` targets another project. It shares the migration's discovery, so it
reads the same door; residents and externals are counted, never exported. The vaults are what a fresh clone carries, so
they are compared, never assumed — see [birth.md](birth.md). A run that scans nothing, or
hits an error, exits 1 and never prints the all-current line.

---

## Template registry regeneration

`regenerate-registry` rebuilds a template's `.spawn/.template_registry.json`: the manifest
of every file and directory the template ships, each with a content hash. It is the file
`create` verifies a mint against and the file `update` walks, so **any change to a template
file must be followed by a regeneration** or the manifest and the tree disagree.

---

## Repair

Repair acts on ONE registry: the one it is given, else the nearest `*_REGISTRY.json` walking up
from the cwd. `--rename` finds its registry by walking up from the cwd too, then each
`projects/*/*_REGISTRY.json`, then the `*_REGISTRY.json` at each active root `AIPASS_ROOTS.json`
declares (memory's `declared_roots`, in declaration order). It looks a name up rather than
enumerating citizens, and the door cannot answer it, because a renamed directory no longer holds
the passport the door checks. The passport is matched by `citizenship.citizen_id` against the
row's `registry_id`; a passport that already carries the new names is rewritten to the same
values, and a passport with no `citizen_id` refuses.

The bare scan is read-only ALWAYS: it reports pollution (duplicate branch directories) and
registry path mismatches and writes nothing. Two submodes act, and each refuses to act
without `--apply`:

- `--relocate` moves a branch to a new location and updates its registry entry; add the
  artifacts flag to carry its vector store along.
- `--clean-pollution` archives and removes duplicate directories.

The archive copy skips rebuildable noise only — `ARCHIVE_EXCLUDE` in `repair_ops.py` is
`.venv`, `__pycache__`, `node_modules`, `.pytest_cache`. `.git` history and `.chroma`
vectors go into the archive, because the original is removed after the copy. The same set
guards the relocation lane.

`--relocate` resolves the new path before checking it sits inside the project, so
`<root>/../outside` refuses. If the registry write fails after the move, the tree is moved
back and the command exits 1. `--clean-pollution` never flags a nested directory holding
`__init__.py`: that is a flat-layout package, not a duplicate. A grant ceremony whose
registry write fails exits 1 and grants nothing.

---

## Grant admin (ceremony)

The admin privilege belongs to the orchestration branch alone. Spawn owns
exactly one leg of it: the `admin: true` flag on that branch's registry entry. The flag
**grants nothing on its own** — the dispatch lane verifies five legs (verified caller, cert
path, cert content, HMAC signature, and this flag).

There is no branch argument: the seat is a constant, and an explicit registry path is the
only option the verb takes. `admin` is also permanently refused as a citizen class or
template value — `create`, `update` and `sync` all say no by name. Admin is never minted
from a template; only the owner's ceremony grants it.

---

**Last Updated:** 2026-11-09
