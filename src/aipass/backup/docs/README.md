[<- Back to the README](../README.md)

# Docs

Depth for the `BACKUP` branch. The face is [../README.md](../README.md); the
live command surface is `drone @backup` and `drone @backup --help`.

| Doc | What it covers |
|---|---|
| [store.md](store.md) | The `.backup/` store: what is created when, and who else writes there |
| [ignores.md](ignores.md) | Seed, built-in floor, runtime — the whole ignore rule set |
| [run_ceiling.md](run_ceiling.md) | The guard that refuses a runaway run before it copies |
| [store_cleanup.md](store_cleanup.md) | Which deletions exist, and which are advertised but absent |
| [drive_sync.md](drive_sync.md) | The optional Drive lane and what is verified |
| [cli.md](cli.md) | Router behaviour, flags by verb, and the legacy entry form |
| [schedule.md](schedule.md) | Each project's scheduled backup: the job, the commands, the JSON |
| [module_fence.md](module_fence.md) | The handlers access guard and its test rules |
| [path_resolution.md](path_resolution.md) | What reads the cwd, the dead-cwd pins, and where backups land |
| [tests.md](tests.md) | Running the suite, and what it is careful about |
