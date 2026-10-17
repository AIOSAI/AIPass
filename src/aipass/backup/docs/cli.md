[<- Back to BACKUP](../README.md)

# The command surface

How the router behaves, which flags exist, and the two entry forms that are easy
to miss. The live list of verbs is `drone @backup` and `drone @backup --help` —
this page covers what those two cannot tell you about themselves.

## The router

The router auto-discovers every file in `apps/modules/` that exposes a
`handle_command()`. One of them, `display`, is a rendering helper rather than a
backup verb — it answers only to its own name (`drone @backup display` prints
its introspection and does nothing else) and is intentionally undocumented as a
command.

**A `--help` anywhere in the arguments prints help and runs nothing** — `drone
@backup snapshot @myapp --help` is a safe probe, not a backup. That rule is a
cure, not a convenience: checking only the first argument once let `snapshot
<project> --help` fall through and execute a real backup.

**Relative paths resolve where you are.** Backup runs as an installed entry
point, so its process CWD is its own branch directory. Drone exports
`AIPASS_CALLER_CWD`; `handlers/path/caller.py` re-anchors every user-supplied
relative path to it, so `drone @backup share docs/notes.md` means the caller's
`docs/notes.md`. Absolute paths are untouched.

## Flags, by verb

Flags live in the verbs, not in the router, which is why the top-level command
reference lists verbs and this page lists their options.

| Verb | Flag | Effect |
|---|---|---|
| `register` | `--name <name>` | Register under a short name, so `@name` resolves to the path |
| `all` | `--quiet` | Suppress the Rich panels; the run itself is unchanged |
| `all` | `--registered` | Run the cycle for every registered project, in registry order (below) |
| `drive_sync` | `--force` | Re-upload files the tracker already recorded |
| `drive_sync` | `--project <name>` | Sync a registered project by name |
| `drive_sync` | `--note <text>` | Attach a note to the sync record |
| `drive_clear` | `--force` | Required — the verb refuses to clear the tracker without it |
| `share` | `--public` | Share the uploaded file with anyone holding the link |
| `status` | `--json` | Print one JSON object on stdout and nothing else: the backup door's status contract (below) |
| `status` | `--sizes` | With `--json` only: add `store.snapshots_bytes` and `store.versioned_bytes` (walks both stores) |
| `prune` | `--apply` | Delete what the listing names; without it nothing is deleted |

`restore` takes subcommands rather than flags: `list <file>` and `file <file>
<output>`. See [restore](restore.md).

## `all` and the Drive step

`all <project>` runs snapshot, then versioned over the same scan, then
`drive_sync` -- but the Drive step only when the project's `drive_sync` setting
is on. Off (the default), it prints `Drive sync off for this project` and moves
on. The bare `drive_sync` verb ignores the setting: naming the verb is the
decision. See [the Drive lane](drive_sync.md).

`all --registered [--quiet]` runs that cycle for every project in the registry,
in registry order. A project that refuses or raises is recorded and the next one
still runs. After the last project it prints one line each:

```
<name> ok|FAILED snapshot=<files> versioned=<files> drive=uploaded|skipped|failed <seconds>s
```

and exits non-zero when any project failed, naming them on stderr. A project
path or `@name` given together with `--registered` is refused and nothing runs;
so is an empty registry. This is the line the nightly daemon job runs.

## `settings`

`settings drive_sync on|off <project_path|@name>` is the one live setting. It
writes the key into the project's own `.backup/config.json` through the project
config handler, keeping every other key as written, and prints the new value
(`drive_sync: on (<root>)`). A wrong word, a missing project, or a directory
with no `.backup/` store is refused on stderr with a non-zero exit. Any other
`settings` line still fails honestly: the settings UI is deferred.

## `status --json`

`status <project_path|@name> --json [--sizes]` prints the object the backup door
reads, exactly the shape pinned in devpulse's `backup_door_contract.md`
("@backup: status --json"), as one JSON object on stdout with nothing else there.
`store` is present only with `--sizes`, which walks both stores. `running`
(round 2, DPLAN-0412) lists the lanes in flight, `[]` when none; see
[Running lanes and `stop`](#running-lanes-and-stop) below. Each lane's
`last` and `files` come from the project's changelog: the last entry of that
mode, its `timestamp` and `files_copied`. A snapshot that found no changes writes
no entry, so `snapshot.last` is the last snapshot that copied; the same rule holds
for `drive_sync`, whose entry counts the files a clean run uploaded. `runs` counts
every entry, Drive runs included. `registered` means the root has a
`.backup/config.json`. A root with no store answers `registered: false`, every
`last` null, `runs: 0`, exit 0; an absent root exits non-zero with one line on
stderr. `--sizes` without `--json` is refused.

## Running lanes and `stop`

Every lane that does work (snapshot, versioned, drive_sync) announces itself in
`<project>/.backup/running/<lane>.json` for as long as it runs, whoever started
it. The document is the contract's `running` entry (devpulse's
`backup_door_contract.md`, "running"): `verb`, `lane`, `pid`, `started_at` and
`progress` (`done`, `total`, `failed`, `bytes_done`, `bytes_total`, `current`,
`updated_at`). `progress` is null while the lane scans; after that the file is
rewritten from the lane's per-file callback at most once a second, atomically,
and removed when the run ends, however it ends. Under `all` each sub-lane
writes its own file in turn with `verb: "all"` and the one pid; the shared scan
counts as the snapshot lane's. `current` is project-relative for snapshot and
versioned, store-relative for drive_sync; `bytes_total` is known only to
drive_sync. A reader (status, stop) drops and removes a file whose pid is gone,
a zombie, or younger than the lane's `started_at` (a recycled pid). The handler
is `apps/handlers/state/progress.py`.

`stop <project_path|@name> [lane]` ends them. The lane word is `snapshot`,
`versioned`, `drive_sync`, or `all` (whatever sub-lane an `all` run is in);
without one, every running lane of the project. Each chosen lane's process gets
SIGTERM, up to 30 s to go, then SIGKILL; stdout says `stopped <lane> (pid N)`
per lane and the verb exits 0. Nothing running prints one line, `nothing running
for <project>` or `<lane> is not running for <project>`, and exits 2.
`<project>` is the name `status --json` reports: the config's `project_name`,
else the root's directory name. A pid is signalled only when, through psutil,
its process started no later than the lane and its command line is backup's
entry point running that verb for that root (`@name` and `all --registered`
resolve through the registry); anything else is refused on stderr, nothing is
signalled, exit 2. psutil reads the process table on Linux, macOS and Windows
alike; on Windows its terminate is TerminateProcess, so a Windows lane gets no
chance to save and its running file is cleared by the next reader.

The stopped lane, in the main thread, turns SIGTERM into a flag. The copy loops
read it between files, so the file in flight finishes; `upload_batch` cancels
the uploads not yet started and lets the ones in flight finish. Then: the Drive
tracker is saved (drive_sync), a trail row `<lane>_stopped` records `done`,
`total`, `failed` and `bytes_done`, and the run's last stdout line is
`stopped by request: <done> of <total> files, <bytes>` (`1,204 of 15,414 files,
310 MB`). No changelog entry is written, and snapshot keeps its old timestamp
map, so a stopped run never reads as a completed one. Under `all` the sub-lane
in flight stops and the next ones never start; `all --registered` starts no
further project and prints no summary after the stopped line. A lane run off
the main thread cannot install the handler, logs that, and a stop ends it the
default way.

**Exit code 130 means stopped by request.** The lane returns normally and
`main()` in `apps/backup.py` maps the stop mark to 130, ahead of the usual
0/2; drone passes the child's exit code through unchanged.

## `prune`

`prune <project_path|@name>` lists, per store and per top-level directory, the
`snapshots/` files and `versioned/` file-folders whose project path the ignore
spec now matches (`.backupignore` plus the built-in floor, minus the whitelist),
with counts, bytes and a grand total. It deletes nothing, and its last line says
so. `--apply` deletes them, one `prune_removed` row per path in the audit trail,
and prints what it removed. See [store cleanup](store_cleanup.md).

## Two entry forms

The documented form is `<verb> <project>`: the verb first, the project second.

There is also a legacy form, `backup <project|@name>`, which runs `snapshot` by
default and accepts `--versioned` or `--all` to pick another lane
(`apps/backup.py`, in `main()`). It resolves registered names the same way the
verbs do. It predates the auto-discovery router, nothing in the tree calls it,
and no test exercises it — it is documented here because it is live, not because
it is recommended. Use the verbs.

`--version` and `-V` both print the entry point's version; `help` on its own
behaves like `--help`.

---

[<- Back to BACKUP](../README.md)
