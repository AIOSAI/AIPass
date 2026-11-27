[<- Back to the README](../README.md)

# The cloud lane

**Branch** ai_mail · **Code** `apps/handlers/dispatch/cloud.py`, `apps/handlers/dispatch/wake.py`, `apps/handlers/dispatch/dispatch_monitor.py`, `apps/modules/dispatch.py`, `apps/modules/email_send.py`

---

`--cloud` hands a dispatch to the target's Claude Code cloud VM instead of a local agent. The
work comes back as a pull request; the sender gets the result by mail and steers the same
session by mail. On the sender's side nothing changes but the flag.

```bash
drone @ai_mail dispatch @hooks "Subject" "Body" --cloud   # start a cloud session for this dispatch
drone @ai_mail email @hooks "text" --cloud                # steer @hooks' open cloud session
```

## One provider shape, not a second system

The cloud lane is a fourth provider shape in the wake beside claude, codex and opencode
(`provider` `cloud`, reachable only through `dispatch --cloud`, never `--provider cloud`).
It goes through the pause gate, the dispatch lock, the register row and the systemd-scope
monitor like any wake. The blocklist, the manager gate and the occupancy check protect a local
seat the cloud session never sits in, so the cloud lane skips them (the occupancy step reads
`not checked — the cloud lane runs no local seat`); a manager such as @devpulse can be
cloud-dispatched. The monitor runs no local agent: it starts the session, polls for its PR and
writes the mails itself, then does the report, register close, feed line and lock release as
for any dispatch. No sandbox wraps it, no local session pointer is touched, and no result JSON
or max-turns marker is read from the start log.

The monitor releases the target's dispatch lock as soon as the session id is on the mail:
nothing runs locally after that, so a local dispatch may take the branch during the poll. The
register row stays open until the poll ends. Its expected-by is 300s for the start, plus the
ceiling, plus one poll interval, plus 30s for the last mail.

A monitor killed mid-poll leaves its register row open with a dead monitor and the mail's cloud
block without `ended`. The next wake that finds the target's lock free closes every open row of
that target whose monitor is gone, with the status
`closed: its monitor was gone when the next wake reached @x`, and shows
`closed register row <id>: its monitor is gone`. A row whose monitor is unknown stays open.

## What is refused, before any mail is sent

Each refusal reads `Dispatch to @x not sent: <reason>` and the cloud lane never falls back to
a local wake:

- `@x cannot work in the cloud: its passport has no citizenship.cloud_environment_id; the cloud lane never falls back to a local wake`
  — each citizen's hosted environment id lives in its passport.
- `its passport <path> could not be read (<error>)`
- `local dev is N commit(s) ahead of origin/dev; the cloud session would not see them, push first`
  — the session clones dev from GitHub; ahead/behind is read from `drone @git status --all --json`.
- `the checkout tracks '<upstream>', not origin/dev; the cloud session clones dev`
- `cannot tell whether local dev is ahead of origin/dev: <why>`
- `cloud briefs are limited to 64 KB; put the log in the repo and name the path` — the body is
  measured in UTF-8 bytes, because the start passes it as one argument.
- `script not found on PATH or at <paths>`
- `@x is busy: its dispatch lock is held (PID n); re-run when it is done`
- `--model apply to local wakes, not --cloud` — likewise `--provider`, `--opencode-config` and
  the grant flags.

`--fresh` and `-c` are accepted and ignored: a cloud session is always fresh, and the wake
says so (`cloud sessions are always fresh — --fresh / -c ignored`). A cloud wake that fails
after the mail went prints `Email sent but wake failed — re-run: drone @ai_mail dispatch @x "S" "B" --cloud`.

## The start

The brief is the mail body as written, then ai_mail's fixed footer: the session is `@x` in a
cloud VM at the clone root; it first runs `drone @x --help`, and if AIPass is not installed it
opens the PR anyway with the setup output in the body; it opens exactly one PR with base dev
from its harness branch; the PR body starts with `dispatch: <mail id>` and ends with its
report; no mail, no dispatch, no git commands; touched test files only.

`claude --cloud` refuses to start without a terminal, so the monitor runs it under
`script -qfec <command> <log>`. `script` takes one command string, built with `shlex.join`
over the argv, so a `$WORD` in the body reaches the brief literally; nothing is ever passed to
a shell as interpolated text. The environment id goes in as
`--settings {"remote":{"defaultEnvironmentId":"<id>"}}`.

The session id is the first `https://claude.ai/code/<id>` URL anywhere in the start output,
whatever label or colour codes surround it. A start output with no such URL gets
`Cloud dispatch refused: @x`, saying no session id was found, that a session may still exist
(check claude.ai/code) and that nothing ran locally, with the last lines of the start output;
the status is `REFUSED (no session id in the cloud start output)`, the exit code `-8`, and
nothing polls.

## The cloud block on the mail

The dispatch mail in the target's inbox carries a `cloud` block, written under the inbox lock:

| Field | Written | Meaning |
|---|---|---|
| `requested` | at send | `true`: this dispatch asked for the cloud |
| `session_id`, `url`, `started` | at start | the session and its View URL |
| `done`, `results` | per PR | `results` is `[{number, head, head_sha, url, state, ci}]`, the latest row of every PR reported |
| `ended` | when the poll stops | `closed`, `ceiling` or `pr list failed` |

The lane never closes the mail.

## The poll

Every `cloud_poll_seconds` (180) until `cloud_ceiling_seconds` (14400), both in the safety
config (`wake.CONFIG_FILE`), the monitor reads
`drone @git pr list --head claude/ --marker <mail id> --state all --json` and keeps rows with a
`claude/` head, on any base: a PR against the wrong base is still the session's answer, and the
result mail names its base. `--state all` sees a PR merged or closed before its first sighting.

Each new PR number, and each new `head_sha` on a PR already reported (a push after a steer),
mails the sender `Cloud dispatch result: @x PR #N (ci <state>)`: the title, the PR url and
`drone @git pr view N`, head and base with state and CI, the session URL, the steer command and
the first 12 lines of the PR body. A result mail that does not go, or a mail call that raises
or times out, counts as not sent: the report's `wake_result` reads `failed_result_mail`, and
the monitor still writes its report, closes the row and releases what it holds. The status is
`completed (cloud PR #N...)`.

New PRs are mailed first; the poll then ends `closed` once every reported PR is no longer
open, else it runs on so a steer's next PR is caught too. Five failed `pr list` reads in a row
end it: the sender gets `Cloud dispatch failed: @x, pr list unreadable` with the last error and
the session URL, the status is `FAILED (pr list failed 5 times in a row: <error>)`, the exit
code `-9`, and the mail stays open. At the ceiling with no PR, the sender gets
`Cloud dispatch timeout: @x, no PR after <min> min` with the session URL and how many of the
reads failed; the status is `TIMEOUT (cloud, no PR in <s>s)` and the mail stays open.

## Steering

`email @x "text" --cloud` finds the newest mail in @x's inbox whose cloud block has a
`session_id` and is not closed, runs `claude -p <text> --cloud <session_id> --output-format json`
(an argv, never a shell string, waiting up to 300s so a paused VM can restore) and records the
mail as any email. The steer queues the text and returns `{ok, session_id, url}`; it never
carries the session's reply, which comes back as a PR. With one text argument the subject is
`Cloud steer`.

- `Not steered: @x has no open cloud dispatch; start one with dispatch @x "S" "B" --cloud`
- `Not steered: claude -p --cloud <sid> exited <rc> without ok: <output>; the text may still have been queued`
  — a steer that times out or answers no JSON ends the same way.
- A steer whose poll has already stopped warns `Its poll has ended (<ended>): a new PR will not
  be mailed back`.

## Limits

- Mail does not cross machines; the VM's mailbox dies with it, so every mail of this lane is
  written by the local monitor.
- An idle VM pauses and the next message restores it; after a long stop the conversation
  survives and its files do not.

## Related

- [wake_pipeline.md](wake_pipeline.md) — the wake path every provider shares
- [wake_providers.md](wake_providers.md) — the Codex and OpenCode providers
- [dispatch_register_and_feed.md](dispatch_register_and_feed.md) — the register row and feed line
