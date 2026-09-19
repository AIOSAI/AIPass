[<- Back to the README](../README.md)

# Docs

Tracked public reference for the `daemon` branch: the depth behind the face.

The branch README is the face for strangers and links every page here. This folder
holds one page per module or handler group, opened when something breaks or when a
contract has to be read exactly:

| Doc | What it covers |
|---|---|
| [architecture.md](architecture.md) | The layer map: what each module and each handler group is for |
| [scheduler_tick.md](scheduler_tick.md) | One tick end to end, and how the code is split |
| [schedule_contract.md](schedule_contract.md) | The job file: schema, schedule types, optional fields, wake options |
| [command_jobs.md](command_jobs.md) | A job that runs a drone command instead of waking an agent |
| [recovery_and_catch_up.md](recovery_and_catch_up.md) | Gap detection, missed windows, the catch-up queue |
| [rounds.md](rounds.md) | The night watch: roster, pointer, budget |
| [inbox_sweep.md](inbox_sweep.md) | The unread-mail backstop, and why it is a hand tool |
| [monitoring.md](monitoring.md) | Activity reports, branch health, memory-entry health |
| [cli_and_arguments.md](cli_and_arguments.md) | The refusal contract, and the retired verbs |
| [testing.md](testing.md) | How the suite is run and judged, and safe mutation runs |

The live inventory is not duplicated here: `drone @daemon` generates it from the code.
Work in progress, research and dated one-offs belong in `docs.local/`, which is not tracked.
