# The registry, sync, repair and the admin ceremony

**Branch** spawn · **Code** `apps/handlers/registry.py`, `apps/handlers/sync_registry_ops.py`,
`apps/handlers/repair_ops.py`, `apps/handlers/passport_migration.py`,
`apps/handlers/seed_ops.py`, `apps/handlers/regenerate_registry_ops.py`,
`apps/modules/` (`sync_registry.py`, `repair.py`, `migrate_passports.py`,
`export_seeds.py`, `regenerate_registry.py`, `grant_admin.py`)
**Moved out of README.md** (DPLAN-0347, the layer contract).

Flags and usage are in `drone @spawn --help` and each verb's own `--help`. Everything below
is the behaviour behind them.

---

## What sync-registry does

It compares `AIPASS_REGISTRY.json` against the filesystem and reports healthy, stale and
unregistered branches. The scan is CWD-first, so it works inside an external project: it
checks the project root, then `src/*`, then `src/*/*`, and a directory counts as a branch
when it holds `.trinity/passport.json`. It is a stat-level walk — it never reads a README,
a prompt or a dashboard.

Three modes past the bare report: `--fix` rebuilds `.spawn/` tracking, registers strays and
repairs passport `registry_id` values; `--fix --dry-run` previews exactly that;
`--check` (optionally `--json`) is the read-only owner and identity health check, which
writes nothing and answers with an exit code.

---

## Registry entry shape — mixed casing is historical, not a rule

`AIPASS_REGISTRY.json` carries entries in two shapes: UPPERCASE names with
registry-relative paths, and lowercase names with absolute paths.

**The uppercase-plus-relative shape is what `create` writes today.** `core.py` hands
`add_to_registry` the uppercased name and a path relativized to the registry's own
directory, falling back to absolute only when relativization raises. So that shape is
spawn's own lane; the lowercase absolute entries predate it or were written by another hand.

Nothing reads the difference: registry lookups lowercase both sides before comparing
(`is_protected`, `ensure_admin`), and a path is resolved as `registry_dir / entry_path`,
which pathlib returns unchanged when the entry is already absolute. It is cosmetic — two
shapes a reader sees and no code does. **Normalising is not done here** and `sync-registry`
does not currently touch casing; whether it should is the orchestration branch's call to
make, not a defect to fix silently under a docs pass.

---

## Passport migration

`migrate-passports` is the one-shot fleet migration to schema 2.0 (DPLAN-0319). It is
dry-run by default, can be restricted to a single branch, can be pointed at another repo
root, and backs each passport up before writing. It either completes a passport or raises;
there is no partial write.

A run against a root with no discoverable passports **refuses** rather than reporting
success — see [cli_contract.md](cli_contract.md) for why that distinction is load-bearing.

---

## Passport seeds

`export-seeds` regenerates each branch's tracked `.aipass/passport.seed.json` from its live
passport, stripping machine-local values. Dry-run by default; `--only` restricts to one
branch and `--root` targets another project. The seeds are what a fresh clone carries, so
they are compared, never assumed — see [birth.md](birth.md).

---

## Template registry regeneration

`regenerate-registry` rebuilds a template's `.spawn/.template_registry.json`: the manifest
of every file and directory the template ships, each with a content hash. It is the file
`create` verifies a mint against and the file `update` walks, so **any change to a template
file must be followed by a regeneration** or the manifest and the tree disagree.

---

## Repair

The bare scan is read-only ALWAYS: it reports pollution (duplicate branch directories) and
registry path mismatches and writes nothing. Two submodes act, and each refuses to act
without `--apply`:

- `--relocate` moves a branch to a new location and updates its registry entry; add the
  artifacts flag to carry its vector store along.
- `--clean-pollution` archives and removes duplicate directories.

The archive copy skips build and VCS noise — `ARCHIVE_EXCLUDE` in `repair_ops.py` is
`.venv`, `.git`, `__pycache__`, `.chroma`, `node_modules`, `.pytest_cache`. The same set
guards the relocation lane, so neither carries a virtualenv into `.archive/`.

---

## Grant admin (ceremony)

The admin privilege belongs to the orchestration branch alone (DPLAN-0288). Spawn owns
exactly one leg of it: the `admin: true` flag on that branch's registry entry. The flag
**grants nothing on its own** — the dispatch lane verifies five legs (verified caller, cert
path, cert content, HMAC signature, and this flag).

There is no branch argument: the seat is a constant, and an explicit registry path is the
only option the verb takes. `admin` is also permanently refused as a citizen class or
template value — `create`, `update` and `sync` all say no by name. Admin is never minted
from a template; only the owner's ceremony grants it.

---

**Last Updated:** 2026-09-15
