[← Back to AIPass](../../../README.md)

# DAEMON

**Purpose:** The fleet's scheduler. A systemd user timer fires one tick every couple of minutes; the tick discovers every citizen's own `.daemon/schedule.json`, decides what is due, and either wakes the owner or runs a drone command as a subprocess. It also reports fleet activity and runs the night watch.
**Module:** `aipass.daemon`
**Version:** 2.0.0
**Created:** 2026-03-07

---

## Quick Start

```bash
drone @daemon
drone @daemon queue
drone @daemon run --dry-run
```

---

## What It Does

- **Fires the decentralized scheduler.** Each citizen owns its schedule file; this branch only discovers and fires. Nothing here decides what another branch should be doing.
- **Wakes a due owner** through ai_mail's `wake_branch()` — the only way a job reaches a live agent.
- **Runs command jobs.** A job may carry a drone command instead of a prompt: it runs as a subprocess in the owner's branch, with a timeout, and wakes nobody. No seat, no session, no tokens.
- **Keeps the night watch.** One citizen a night gets a maintenance turn, walked alphabetically across the framework fleet.
- **Reports.** Activity across branches, a per-branch deep dive, memory-entry health through @memory, and red flags such as code that moved while its memory did not.
- **Refuses what it does not recognise.** An unknown verb or argument fails by name with a non-zero exit, never a default.

---

## Live Inventory

`drone @daemon` prints the live self-map: every module discovered in this branch, with the one-line purpose each module declares about itself. It is generated from the code at the moment you ask, so it cannot fall behind the code.

`drone @daemon --help` is the reference: every verb, its arguments and worked examples. Each verb also answers `--help` on its own for the detail that belongs to it — the job-authoring reference for the scheduler tick, the roster rules for the rounds, the staleness flags for the sweep.

---

## How To Reach Me

- **To schedule something,** write it into your own branch's `.daemon/schedule.json`. You own that file; the tick finds it. The contract is in [docs/schedule_contract.md](docs/schedule_contract.md), and the same reference prints live from the scheduler tick's own `--help`.
- **To ask for a fleet report,** run the activity or branch-health verb from the inventory above.
- **To report a defect in a job that fired wrong,** mail @daemon with the job id and the timestamp; the tick log and `logs/run.log` keep every fire.
- **To get woken,** nothing extra is needed: a job that names a prompt wakes its owner when due.

---

## Commands

There is no command list on this page, deliberately: a hand-typed copy of a branch's own help output rots the next time a verb is added or retired. The generated surface is the one above under **Live Inventory**, and it is always current.

---

## Architecture

Three layers. `apps/daemon.py` is the entry point: it discovers the modules, routes a verb to one of them, and renders help. `apps/modules/` holds one module per verb — `run` for the scheduler tick, `queue` for the unified job view, `rotation` for the night watch, `inbox_sweep` for the unread-mail backstop, `activity_report` for the three reporting verbs, `update` for the status digest, `timer_install` for the systemd units, with `schedule` and `actions` kept only as retirement notices pointing at the schedule file, and `wakeup_ops` an orphaned facade recorded in the known issues.

`apps/handlers/` holds the implementation, grouped one directory per concern: `schedule/` (job discovery, the runstate and due logic, command-job execution, the catch-up lane, the rounds roster, the tick lock, the authoring reference, the fail-soft notifier), `monitoring/` (activity collection, inbox scanning, memory health, red flags, report rendering), `cli/` (the argument gate that refuses unknown tokens), `update/` (data loading for the digest), and the json shim every branch shares.

The directory tree and this branch's sharp edges live in its own prompt, `.aipass/aipass_local_prompt.md` — one place, so they cannot disagree with themselves.

---

## Documentation

Depth lives in [docs/](docs/), one file per module or handler group:

| Doc | What it covers |
|---|---|
| [docs/architecture.md](docs/architecture.md) | The layer map: what each module and each handler group is for |
| [docs/scheduler_tick.md](docs/scheduler_tick.md) | One tick end to end: the code split, the scheduled lane, what a fire consumes, staggering |
| [docs/schedule_contract.md](docs/schedule_contract.md) | The job file: schema, schedule types, optional fields such as `slot` and `catch_up`, wake options |
| [docs/command_jobs.md](docs/command_jobs.md) | A job that runs a drone command instead of waking an agent: rules, timeout, notify mail, what a fire records |
| [docs/recovery_and_catch_up.md](docs/recovery_and_catch_up.md) | Gap detection after the machine was away, missed windows, the catch-up queue and the wake header |
| [docs/rounds.md](docs/rounds.md) | The night watch: roster scope, the pointer, the budget a steward night runs under |
| [docs/inbox_sweep.md](docs/inbox_sweep.md) | The unread-mail backstop, and why it is a hand tool rather than a scheduled job |
| [docs/monitoring.md](docs/monitoring.md) | Activity reports, branch health, and memory-entry health through @memory |
| [docs/cli_and_arguments.md](docs/cli_and_arguments.md) | The refusal contract for unknown verbs and arguments, and the retired verbs |
| [docs/testing.md](docs/testing.md) | How the suite is run and judged, the two rules a test here may not break, and safe mutation runs |

---

## Integration Points

### Depends On

- `@ai_mail` — `wake_branch()`, the only way a job or a sweep wakes a citizen, plus its wake blocklist
- `@prax` — the logger every module writes through
- `@memory` — branch health, rendered by the per-branch deep dive
- `@cli` — the shared Rich console
- `@skills` — lifecycle pings, imported lazily and fail-soft; the Telegram channel behind it is retired
- Python stdlib, and a systemd *user* instance for the tick timer

### Provides To

- The fleet — job discovery and firing for any citizen that writes a `.daemon/schedule.json`
- The fleet — the night watch, and the unread-mail backstop as a hand tool
- `@skills` — the queue view's `--json`, a frozen schema
- `@devpulse` — activity reports and the notify mail a command job can send

---

**Last Updated:** 2026-09-15

[← Back to AIPass](../../../README.md)
