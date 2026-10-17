[<- Back to the README](../README.md)

# Command Jobs

How a scheduled job runs a drone command instead of waking an agent, and the rules that keep it safe.

---

## Command jobs

A job can run a drone command instead of waking an agent. It runs as a subprocess of the tick, so
it uses no seat, no session and no tokens: a housekeeping sweep should not cost a Claude session.
Every run is logged, pass or fail, and changing what it does is editing one string. @prax's weekly
sweep of stale staging temps is one:

```json
{
  "id": "tmp-sweep-weekly",
  "enabled": true,
  "schedule": { "type": "interval", "interval_minutes": 10080, "slot": "2026-09-13T04:00:00" },
  "command": "drone rm --stale 10d ..",
  "timeout_seconds": 120,
  "notify": { "email": "@devpulse" }
}
```

It lives in `src/aipass/prax/.daemon/schedule.json`, so it runs from `src/aipass/prax/`. A
relative path in the command resolves from there, which makes `..` the `src/aipass/` directory:
one call covers every branch. The slot names a Sunday, 04:00. The live file's `_note` explains its
120-second timeout, which is shorter than the default because a command job holds the tick lock for its whole run.

| Field | Required | Meaning |
|-------|----------|---------|
| `command` | yes, instead of `prompt` | One drone command line. `drone` must be the first token. |
| `timeout_seconds` | no, default **600** | A positive whole number. When it runs out, the command's whole process tree is stopped and the fire is FAILED. 600 matches drone's own executor default. |
| `notify` | no | `false` silences the Telegram pings. `{"email": "@devpulse"}` also sends an ai_mail **email** (never a wake) on start and on finish. |
| `wake` | ignored | A command job wakes nobody. Discovery drops the block and logs a warning if one is present. |

**The rules, and why each one exists.**

- **`drone` is the first token, and nothing else can be.** A schedule file is per-branch and its
  owner can edit it, so whatever it names runs with the tick's authority. Holding command jobs to
  drone verbs means drone's own gates decide what a scheduled command may do: rm's fence, git's
  refusal, the argument gates. `bash -c ...`, `env drone ...`, `/usr/local/bin/drone` and
  `rm ...` are all refused at discovery.
- **No shell.** The command is split with `shlex.split`, which applies POSIX quoting on every
  platform, and runs as an argv list with `shell=False`. That means no globs, no pipes, no `;`
  and no variable expansion. `drone rm *.tmp ; echo x` reaches drone as the literal arguments
  `*.tmp`, `;`, `echo`, `x`. Nothing in a JSON string can turn into a second command.
- **It runs in the owner's branch directory.** Drone reads cwd as identity, so the work is logged
  as the citizen whose schedule asked for it. The directory comes from the same citizen record
  that vouched for the schedule file, looked up by email. It is not looked up again by directory
  name, because two citizens can share one across federated roots. A job with no branch directory
  is refused, never run from the tick's own cwd (the repo root, which would sign it as the project).
- **Never a rotation.** A rotation wakes tonight's citizen on the roster. A command wakes nobody,
  so the two cannot be combined, and the combination is refused.

**What a fire records.** Exit 0 is `fired`. A non-zero exit, a timeout, or a command that could
not start is `failed`, with the detail `exit 2, 0.4s — <last lines of output>`. A command job is
**never** `blocked`: no seat is in use, so no gate can refuse it, and it never takes the
active-agent lock. The runstate row is exactly a wake job's row (`last_run`, `last_status`,
`last_success_at` / `last_failure_at`, `last_error`, and `completed` for `once`). Catch-up,
interval, daily, slot and backoff logic is unchanged, because due-ness never reads what a job does.
`drone @daemon queue` shows `command: <the command>` in the preview column. The frozen `--json`
keys are unchanged.

**Two log lines every fire, pass or fail**, written to both the tick log
(`~/.aipass/daemon-tick.log`) and `logs/run.log`:

```
FIRE: @daemon/dplan-0338-proof -> command: drone @daemon --help
DONE: @daemon/dplan-0338-proof — exit 0, 1.5s —   Fleet mail: | ... |   drone @daemon <command> --help
```

**Notify.** The Telegram pings follow the rule every job follows (`_should_notify`: on unless
`notify` is false). A `notify` block counts as on. `notify.email` sends one mail as the command
starts (owner, id, command, timeout) and one as it finishes (exit code, duration, output tail).
The mail goes out as a `drone @ai_mail email` subprocess from daemon's own directory, so it is
signed `@daemon`. It is not sent through an in-process ai_mail import, for two reasons: ai_mail has
no public send function that takes an explicit sender, and the tick runs from the repo root, so an
in-process send would sign the mail as the project. A mail that fails is logged as a WARNING and
never changes the fire's answer. Each mail costs several seconds of tick time (one drone
call). That is fine for a weekly job and a reason not to set `notify.email` on a job that
runs every few minutes.

**How the subprocess runs.** It uses `Popen`, not `subprocess.run(capture_output=True)`, for two
measured reasons:

- **Output goes to an anonymous temp file, not a pipe.** A pipe only reaches EOF when every
  holder of its write end has closed it. A drone verb that starts anything in the background hands
  that process the pipe, so a command that exited 0 in a second would be reported as a 600-second
  timeout; `test_a_background_child_holding_the_output_is_not_a_timeout` pins it. `TemporaryFile` is unlinked
  the moment it is created, so it leaves no `.tmp` litter behind.
- **A timeout stops the whole process tree.** Drone runs every `@branch` verb in a child of its own
  (`drone/apps/handlers/executor.py`), so killing drone alone would orphan exactly the work that
  overran. On POSIX the command gets its own session, and the timeout sends SIGTERM to the group,
  waits up to 2 s, then sends SIGKILL to the group, and only then reaps the leader. The wait polls
  `os.waitid` with `WNOWAIT`, so a leader that exits on SIGTERM stays an unreaped zombie and still
  holds the group id: a reaped pid can be reissued, and a SIGKILL to its group would reach a
  stranger. Windows has no process group to signal: the direct child is killed and a grandchild
  may outlive it. That is the known residual.

stdin is `/dev/null`: a scheduled command has no human to answer a prompt.

**While a command runs, it holds the tick.** Ticks are single-instance, so a command that takes
ten minutes makes the next four or five timer fires step aside (`Another scheduler instance is
running`). A windowed job still has its ±15 minutes, and the 600 s default stays well under the
30-minute gap threshold. It is still a reason to keep command jobs short.

