[<- Back to the README](../README.md)

# Wake providers: Codex and OpenCode

**Branch** ai_mail · **Code** `apps/handlers/dispatch/wake.py`, `apps/handlers/dispatch/dispatch_monitor.py`

---

A wake spawns Claude by default. `--provider codex` and `--provider opencode` spawn the other two CLIs through the same monitor, lock, register and wake-back; this page holds what differs. The common path is in [wake_pipeline.md](wake_pipeline.md).

## The Codex provider (`--provider codex`)

`dispatch` and `dispatch wake` take `--provider claude|codex|opencode` (default `claude`); any other
value is refused before the mail is sent. `wake_branch(..., provider="codex")` spawns the
Codex CLI through the same monitor, lock, register and wake-back as a Claude wake, with
the same prompt text.

```
codex exec [-m <model>] --json -o <branch>/logs/dispatch_last_message.txt \
  --dangerously-bypass-approvals-and-sandbox "<prompt>"                      # fresh
codex exec resume <thread_id> [-m <model>] --json -o ... "<prompt>"          # resume
```

- **Model.** `--model` is passed verbatim as `-m`; without it no `-m` is sent and Codex
  uses `~/.codex/config.toml`. `resolve_wake_model` and the Fable grant are not consulted:
  both are Claude's. The status block prints `provider → codex` and `model → <slug>` or
  `model → codex config default`.
- **No `--cd`.** The monitor already runs with `cwd=<branch>`, and `resume` has no `--cd`.
- **Managers wake on Codex in the same lanes as on Claude.** Mailed, not woken, by default;
  headless through the monitor in the scheduled and admin lanes; on a @daemon self-wake, a tmux
  session runs `codex [-m <model>] --dangerously-bypass-approvals-and-sandbox "$(cat
  .daemon/last_wake_prompt.txt)"`.
- **The pointer.** `.ai_mail.local/session.json` carries `provider`; a pointer without the
  key is a Claude pointer. A pointer for one provider never resumes the other (`pointer is
  for claude, waking on codex - starting fresh`). A Codex pointer resumes only while its
  rollout file `~/.codex/sessions/YYYY/MM/DD/rollout-*-<thread_id>.jsonl` exists; otherwise
  the wake is fresh (Codex has no `-c`). `--fresh` always starts a new thread.
- **Codex mints the thread id**, so a fresh codex wake writes no pointer before the spawn.
  After a successful run the monitor records `thread.started.thread_id` with
  `set_by: "monitor-codex"`, `provider: "codex"`.
- **The monitor** is told `--provider=codex` before `--`. Startup is any byte on stdout
  within `STARTUP_TIMEOUT` (the `--json` stream is live), not the `~/.claude` JSONL probe.
  A run succeeds when it exits 0, the stream has `turn.completed`, and it has no `error`
  event. Exit 0 without that is `CODEX_STREAM_FAILED` (-5): bounced with the error line
  verbatim and never re-run, because the turn ran and may already have acted. The result is
  the LAST `agent_message` (the text `-o` writes); the report takes it and `usage` from the
  stream. Retries re-run the argv; strike 3 of a `resume` drops `resume <id>` to a fresh
  `exec`.
- **Processes.** `pgrep -l -x 'claude|codex'` and the zombie scan see both CLIs; the occupancy row
  names the one it found (`Interactive codex session in ...`). A `codex` whose first argument is
  `app-server`, `mcp-server` or `exec` is not a session: the app-server daemon a TUI leaves behind
  in its folder (parented by `systemd --user`) never blocks a wake. An unreadable argv counts as a
  session.
- **Not covered for Codex:** no `--max-turns` equivalent (`HARD_TIMEOUT` bounds the run) and
  no rate-limit reading; `_check_rate_limited` reads stderr as for Claude.

## The OpenCode provider (`--provider opencode`)

`wake_branch(..., provider="opencode")` spawns OpenCode 2 through the same monitor, lock,
register, pointer and wake-back as Claude and Codex, with the same prompt text. The binary is
found on `PATH`, else in `~/.opencode/bin` (the installer's home), then the usual directories.

```
opencode run --standalone --format json --auto [-m <provider/model>] "<prompt>"                       # fresh
opencode run --standalone --format json --auto [-m <provider/model>] --session <ses_id> "<prompt>"  # resume
```

- **Flags.** `--standalone` runs a private `opencode serve --stdio` child instead of the user's
  background service, so the wake owns its process and env; the shared server would never see
  provider keys from the waking shell. `--auto` approves every permission
  not explicitly denied; the AIPass hooks are the gates.
- **Model.** `--model` is passed verbatim as `-m` (`provider/model`, optionally `#variant`, e.g.
  `opencode/glm-5.3-flash-free`, one of the two free models documented zero-retention);
  without it no `-m` is sent and OpenCode chooses. The status block prints `provider → opencode`
  and `model → <slug>` or `model → opencode default`. `resolve_wake_model` and the Fable grant
  are Claude's and are not consulted.
- **OpenCode mints the session id.** A fresh wake passes no `--session` and writes no pointer.
  OpenCode's free tier refuses a session whose id is not in OpenCode's own shape, and that
  shape is undocumented, so the fleet never invents one. `sessionID` arrives on the first
  stream line, before any model call; at the end of every attempt, failed ones included, the
  monitor records it (`set_by: "monitor-opencode"`, `provider: "opencode"`). A run refused
  at once still leaves the branch pointing at the session OpenCode created. A resume passes
  the pointer's id as `--session`.
- **The pointer check reads OpenCode's store, never a file glob.** Sessions live in SQLite at
  `~/.local/share/opencode/opencode.db` (`OPENCODE_DB` overrides), table `session_v2`. The
  pointer resumes only when `session_v2` has its id with `directory` equal to the branch; the
  store is opened read-only (`mode=ro`), so a missing store is reported, never created. Any other
  answer, or a pointer for another provider, starts fresh with a new id.
- **Managers** wake in the same lanes as on Codex. On a @daemon self-wake the tmux session runs
  `[OPENCODE_CONFIG_CONTENT='{"model": "<slug>"}'] opencode --standalone --auto --prompt "$(cat
  .daemon/last_wake_prompt.txt)"`. `--standalone` keeps the TUI off the user's shared
  `opencode serve --service`, which keeps the env of whoever started it, so `AIPASS_HOME` would
  never reach the hooks. The TUI has no model flag; the inline config carries the slug.
- **`--opencode-config '<json>'`** hands OpenCode a config at launch, for example
  `{"compaction": {"buffer": 180000}}`. It must be a JSON object and applies to
  `--provider opencode` only; anything else is refused before the mail is sent. It is merged with
  `--model`, which wins on `"model"`. Headless, the merge rides to the monitor as
  `--opencode-config=<json>` and is set as `OPENCODE_CONFIG_CONTENT` after the `OPENCODE*`
  strip, so a parent seat's value never leaks. The tmux lane puts it in its inline prefix. The
  status block and wake log print it.
- **The monitor** is told `--provider=opencode` before `--`. Startup is the first stdout byte.
  The stream is one JSON object per line, `{type, timestamp, sessionID, part|error}`, with no
  closing event. The result is the LAST `text` part; `usage` and `total_cost_usd` sum every
  `step_finish`, and `num_turns` counts them, in the report's shape. An `error` event fails the
  run and stops the retries, because the stream has named its cause; the bounce carries the
  line verbatim. `provider.free-limit` or `status: 429` bounces as `API rate limit (opencode
  429, retryAfter <s>s, ...)` from `retryAfterMs`. Exit 0 with no `text` part is
  `OPENCODE_STREAM_FAILED` (-6), bounced and never re-run. Other failures retry the same argv;
  strike 3 of a resume drops `--session <id>`, so OpenCode mints a new session.
- **Env.** The monitor strips every `OPENCODE*` variable from the agent's env except
  `OPENCODE_DB`, which the wake's store check and the child must agree on.
  It also sets `PWD` to the branch: OpenCode files a session under `PWD`, not the process
  cwd, so an inherited `PWD` would record the caller's directory and break every resume.
- **Processes.** `opencode` is in the pgrep and zombie set. An `opencode serve` with
  `--service` (the user's daemon) or `--stdio` (a standalone child) is not a session; the TUI
  and any other form are.

## Related

- [wake_pipeline.md](wake_pipeline.md) — the wake path every provider shares
