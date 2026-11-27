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
It goes through the same gates (pause, manager, occupancy), the same dispatch lock, the same
register row and the same systemd-scope monitor. The monitor runs no local agent: it starts
the session, polls for its PR and writes the mails itself, then does the report, register
close, feed line and lock release as for any dispatch. No sandbox wraps it and no local
session pointer is touched.

The poll holds the target's dispatch lock and register row until it ends, so no local
dispatch reaches that branch meanwhile. The register's expected-by is the ceiling plus 300s.

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
- `--model apply to local wakes, not --cloud` — likewise `--provider`, `--opencode-config` and
  the grant flags.

`--fresh` and `-c` are accepted and ignored: a cloud session is always fresh, and the wake
says so (`cloud sessions are always fresh — --fresh / -c ignored`).

## The start

The brief is the mail body as written, then ai_mail's fixed footer: the session is `@x` in a
cloud VM at the clone root with AIPass installed; it opens exactly one PR with base dev from
its harness branch; the PR body starts with `dispatch: <mail id>` and ends with its report;
no mail, no dispatch, no git commands; touched test files only.

`claude --cloud` refuses to start without a terminal, so the monitor runs it under
`script -qfec <command> <log>`. `script` takes one command string, built with `shlex.join`
over the argv, so a `$WORD` in the body reaches the brief literally; nothing is ever passed to
a shell as interpolated text. The environment id goes in as
`--settings {"remote":{"defaultEnvironmentId":"<id>"}}`.

The session id is parsed from the start's `View: https://claude.ai/code/<id>?...` line. A start
with no View line has no session: the sender gets `Cloud dispatch refused: @x` with the last
lines of the start output, the status is `REFUSED (cloud start printed no View line)`, the exit
code `-8`, and nothing polls.

## The cloud block on the mail

The dispatch mail in the target's inbox carries a `cloud` block, written under the inbox lock:

| Field | Written | Meaning |
|---|---|---|
| `requested` | at send | `true`: this dispatch asked for the cloud |
| `session_id`, `url`, `started` | at start | the session and its View URL |
| `done`, `results` | per PR | `results` is `[{number, head, state, ci}]` for every PR reported |
| `ended` | when the poll stops | `closed` (a reported PR left the list) or `ceiling` |

The lane never closes the mail.

## The poll

Every `cloud_poll_seconds` (180) until `cloud_ceiling_seconds` (14400), both in the safety
config (`wake.CONFIG_FILE`), the monitor reads
`drone @git pr list --base dev --head claude/ --marker <mail id> --json` and keeps rows with
base `dev` and a `claude/` head. A read that fails is logged and retried at the next poll.

Each new PR number mails the sender `Cloud dispatch result: @x PR #N (ci <state>)`: the title,
`drone @git pr view N`, head and base with state and CI, the session URL, the steer command and
the first 12 lines of the PR body. A result mail that does not go is logged and the report's
`wake_result` reads `failed_result_mail`. The status is `completed (cloud PR #N...)`.

The poll runs on after a result so a steer's next PR is caught too; it stops early once a
reported PR leaves the list. At the ceiling with no PR, the sender gets
`Cloud dispatch timeout: @x, no PR after <min> min` with the session URL; the status is
`TIMEOUT (cloud, no PR in <s>s)` and the mail stays open.

## Steering

`email @x "text" --cloud` finds the newest mail in @x's inbox whose cloud block has a
`session_id` and is not closed, runs `claude -p <text> --cloud <session_id> --output-format json`
(an argv, never a shell string) and records the mail as any email. The steer queues the text
and returns `{ok, session_id, url}`; it never carries the session's reply, which comes back as
a PR. With one text argument the subject is `Cloud steer`.

- `Not steered: @x has no open cloud dispatch; start one with dispatch @x "S" "B" --cloud`
- `Not steered: claude -p --cloud <sid> exited <rc> without ok: <output>`
- A steer whose poll has already stopped warns `Its poll has ended (<ended>): a new PR will not
  be mailed back`.

## Limits

- A push to an existing PR is not a new result: the pr list rows carry the head branch name,
  no commit sha, so only a new PR number is reported.
- The result mail names the PR number and `drone @git pr view N`, not a URL: the rows carry no
  URL.
- Mail does not cross machines; the VM's mailbox dies with it, so every mail of this lane is
  written by the local monitor.
- An idle VM pauses and the next message restores it; after a long stop the conversation
  survives and its files do not.

## Related

- [wake_pipeline.md](wake_pipeline.md) — the wake path every provider shares
- [wake_providers.md](wake_providers.md) — the Codex and OpenCode providers
- [dispatch_register_and_feed.md](dispatch_register_and_feed.md) — the register row and feed line
