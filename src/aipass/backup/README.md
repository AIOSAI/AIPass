[<- Back to AIPass](../../../README.md)

# BACKUP

**Purpose:** Project-owned, local-first backups for any directory on this machine
**Module:** `aipass.backup`
**Version:** 1.1.0
**Created:** 2026-04-16
**Last Updated:** 2026-09-15

---

## Quick Start

```bash
drone @backup register /path/to/project --name myapp   # register and scaffold .backup/
drone @backup snapshot @myapp                          # full mirror copy
drone @backup versioned @myapp                         # incremental, timestamped
drone @backup status @myapp                            # what is stored, and when
```

---

## What It Does

- **Snapshot** — a full mirror of a project as it stands right now.
- **Versioned** — an incremental, timestamped store that keeps the current copy
  and a baseline beside it, so a file can be recovered as it was.
- **Restore** — finds a version by path or by name and writes it where you say.
- **Registration** — a project registers once, gets its own `.backup/` store and
  its own `.backupignore`, and answers to `@name` afterwards.
- **Ignore rules** — gitignore-style patterns, with a built-in floor that reaches
  every project whether or not its ignore file knows about the rule.
- **A run ceiling** — every run measures what it is about to copy and refuses
  loudly rather than walking a build-artifact tree for hours.
- **Drive sync** — optional, off by default, and the only lane that leaves the
  machine.

The backups belong to the project, not to this branch: the store and the ignore
file live in the target project's own root, so a project keeps its backups when
this branch is not around. There is no compression, no encryption, and no
schedule — a backup happens when something asks for one.

---

## Live Inventory

The list of what this branch can do is generated from the code, never typed
here, because a typed copy starts rotting the day it is written:

- `drone @backup` — the self-map: every module discovered, one line each.
- `drone @backup --help` — the full reference: every command, every flag, and
  the examples that go with them.

A `--help` anywhere in the arguments prints the page and runs nothing, so both
are safe to probe against a real project.

---

## Commands

Deliberately no list here. The command reference is `drone @backup --help`, and
what it prints is the truth of the moment; a second copy in this file could only
disagree with it. For the parts `--help` cannot tell you about itself — how the
router resolves relative paths, which flag belongs to which verb, and the legacy
entry form that still works — see [docs/cli.md](docs/cli.md).

---

## Architecture

Three layers. `apps/backup.py` is the entry point: it discovers the modules,
routes a verb to whichever one claims it, and resolves `@name` to a path.

The modules are the verbs. `register` scaffolds a project's store; `snapshot`
mirrors, `versioned` keeps history, and `all` runs both lanes over one shared
scan before handing off to `drive_sync`. `restore` reads history back out,
`status` reports what is stored, and `display` renders the panels the other
lanes print. The Drive lane is `drive_sync`, `drive_check`, `drive_stats`,
`drive_clear` and `share`. `settings` is a stub that fails honestly rather than
pretending to have saved anything.

Underneath, the handlers do the work: walking and filtering a tree, applying
ignore rules, copying, diffing, building store paths, reading and writing the
project's config and registry, keeping the changelog, talking to Drive, and
writing this branch's own operation trail. They are shared by every module, and
they refuse to be imported from outside this branch —
see [docs/module_fence.md](docs/module_fence.md).

The directory tree lives in one place only, the branch prompt
(`.aipass/aipass_local_prompt.md`), so it cannot disagree with itself.

---

## Documentation

Depth lives in [docs/](docs/), one page per lane or handler group:

| Doc | What it covers |
|---|---|
| [store.md](docs/store.md) | The `.backup/` store, and who else writes there |
| [ignores.md](docs/ignores.md) | Seed, built-in floor, runtime — the whole rule set |
| [run_ceiling.md](docs/run_ceiling.md) | The guard that refuses a runaway run |
| [store_cleanup.md](docs/store_cleanup.md) | Deletions that exist, and ones that do not |
| [restore.md](docs/restore.md) | Finding a version and recovering it |
| [drive_sync.md](docs/drive_sync.md) | The Drive lane, and what is verified |
| [cli.md](docs/cli.md) | Router behaviour, flags by verb, legacy entry form |
| [module_fence.md](docs/module_fence.md) | The handlers access guard |
| [path_resolution.md](docs/path_resolution.md) | Why nothing here resolves at import |
| [tests.md](docs/tests.md) | Running the suite |

---

## Integration Points

### Depends On

- **@prax** — logging; every lane writes its trail through it.
- **@cli** — Rich console output, shared with the rest of the fleet.
- **@api** — the gateway the Drive lane authenticates through.

### Provides To

- **Any project on this machine** — registered or named by path; the store is
  written into the project, not into this branch.
- **@memory** — rollover safety copies share the `.backup/` directory.
- **@flow** — closed plans are archived under the repo root's `.backup/`.

---

[<- Back to AIPass](../../../README.md)
