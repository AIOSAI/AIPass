[<- Back to the README](../README.md)

# Provider parity

`drone @hooks parity` runs the same scripted prompts headless on Claude Code, Codex and OpenCode from one branch's cwd and compares what the hooks did in each session, row by row. Exit 0 when every row is the same or an accepted difference; exit 1 on a real difference or a session that left no record, so a merge train can gate on it.

```
drone @hooks parity [--branch @canary|<path>] [--lane A,B,C,D,E,F] [--provider claude,codex,opencode] [--json]
```

`--branch` takes a path or `@name`, looked up in AIPass's registry, then in each project enrolled with `aipass trust`. Lane `J` expands to `A,B,C`; point `--branch` at an external project's citizen for it. `--json` also writes `artifacts/reports/parity_<date>.json`.

## The oracle

`logs/engine.jsonl`. Every per-hook line carries the payload's `session_id`, and each CLI prints its session's id (Claude's result JSON `session_id`; Codex's first `--json` event, `thread.started`, `thread_id`; OpenCode's `sessionID` on every stream line, minted by OpenCode). The runner reads both log generations for that id right after the session ends. engine.jsonl keeps two generations of about 500 KB, about 25 minutes on a busy fleet, so a session is read back before the next starts.

A row reads one hook in one session:

| Kind | Readings |
|---|---|
| inject | `injected` (stdout carried text), `silent`, `not reached` |
| ran | `ran`, `not reached` |
| refused | `refused` (an exit 2), `not refused`, `not reached` |
| pointer | `untouched` / `written`: the branch's `.ai_mail.local/session.json` mtime across the session |

A provider whose session printed no id, or whose id has no lines, reads `no data`.

## Launch shapes

Each runs from `cwd = <branch>`, with the prompt on stdin (the edit gate refuses a long prompt as an argument), and with the env `dispatch_monitor` gives a headless wake: `AIPASS_SESSION_TYPE=dispatched`, every `CLAUDE*` and `CODEX*` variable stripped, `AIPASS_CALLER_BRANCH`, `AIPASS_CALLER_CWD`, `AIPASS_BOT_ID` and `OPENCODE_SESSION_ID` dropped. `PWD` is set to the branch: OpenCode takes its directory from `$PWD` before its real cwd, so an inherited one runs the lane as the caller. `--provider` defaults to `claude,codex`; `opencode` is named to run.

- Claude: `claude -p --model sonnet --permission-mode bypassPermissions --output-format json`
- Codex: `codex exec --dangerously-bypass-approvals-and-sandbox --json -` (the model is the Codex config default)
- OpenCode: `opencode run --standalone --format json --auto -m opencode/deepseek-v4.1-flash-free` (`opencode` on PATH, else `~/.opencode/bin/opencode`). The free tier's quota is per model and per day: a stream carrying `provider.free-limit` reruns the lane once on `opencode/nemotron-3.5-lightning-free`, and a second refusal reads `no data`. The run never passes `--session`: the free tier answers an id not in OpenCode's own shape with a false 429. The plugin loads from the user-level install or from `OPENCODE_CONFIG_DIR` when the caller sets it; a session the plugin never reached has no engine lines and reads `no data`.

A session that runs past 600 seconds reads `no data`.

## Lanes

Each lane sends one prompt, the same text to both providers. It asks the model to do each step once, and not to retry or work around a refusal. A and B share one session.

| Lane | Prompt | Rows |
|---|---|---|
| A | reply OK, no tools; one unread probe mail is sent to the branch first | the twelve UserPromptSubmit handlers, injected or silent |
| B | (A's session) | SessionStart `cadence_reset`, `release_notice`, `session_pointer`, `culture`; the pointer file untouched |
| C | write into a sibling branch, `git status`, `touch` + `rm` in the temp dir, create `tests/test_parity_probe.py` | `pre_edit_gate`, `git_gate`, `rm_gate`, `testwrite_gate` refused |
| D | create `docs.local/parity_probe.md`, then change its line | `pre_edit_gate` does not refuse; PostToolUse `auto_fix_diagnostics`, `comment_budget`, `trinity_tripwire`, `post_compact_regrounding` ran |
| E | start one sub-agent that replies OK | Stop `presence_release`, `stop_sound`; SubagentStop `subagent_stop_gate` |
| F | read the three `.trinity` files one per call, refresh the dashboard, add a 150-character todo | `pre_edit_gate` refuses the over-cap edit; `trinity_tripwire_snapshot` and `trinity_tripwire` ran |

The probe mail stays in the target's inbox (subject "Parity probe (no action)"): ai_mail closes a mail only from its recipient's seat. The mail fence refuses it across projects, so an external project's lane A runs with no unread mail. Lane D leaves `docs.local/parity_probe.md` in the branch.

## Accepted differences

Marked `accepted (<reason>)`, never counted:

- `start: culture`: a SessionStart row on both CLIs; on Claude inside `AIPASS_HOME` it is silent, since the CLI reads `.claude/AGENTS.md` natively there.
- `subagent stop`: the sub-agent mechanism differs (the Agent tool on Claude, multi-agent on Codex).

The settings gate (ask on Claude, deny on Codex), the status line and the Notification hook are accepted differences in the parity matrix, and no lane probes them. PreCompact is not probed: a headless session does not reach compaction.

## Not observed here

engine.jsonl carries no command, so a `refused` row cannot name the call it refused. `not refused` means the gate refused none of the session's calls: it allowed the probe, or the model never made it. A model that declines a step on its own instructions reads `not refused` when it made other tool calls and `not reached` when it made none; the rollout or transcript tells which. Rows that need a person or BAUD (skills, the switch, the cards) and mail and dispatch rows are run as a playbook, not by this runner.
