# Hook Probe Suite (Legacy)

> **Note:** The probe suite predates the `hook_log.py` always-on logger (S132, DPLAN-0167).
> For most hook debugging, use `hook_report.py` and `hook_test.py` in the parent directory
> instead -- they cover all hooks automatically without manual wiring. The probes below remain
> useful for one-off event investigation when you need to enable/disable individual events.

> **Post-migration note (DPLAN-0184):** Production hooks now route through the bridge at
> `src/aipass/hooks/apps/handlers/bridges/claude.py`. Probes are independent of the bridge
> pipeline -- they wire directly into `~/.claude/settings.json` as standalone commands.
> The wiring examples below still work as-is.

This directory contains ping-response probe scripts for each Claude Code hook event type.
Probes are **opt-in** -- they are never auto-wired. See below for how to enable them.

---

## What this directory is

Each `probe_*.py` script in this directory is a passive observer for one Claude Code hook event.
When enabled in `settings.json`, a probe fires on its event, records a structured entry to
`last_ping.jsonl`, and exits 0 immediately -- it never blocks execution.

---

## Probe scripts

| Script                         | Hook event        |
|--------------------------------|-------------------|
| `probe_pre_tool_use.py`        | PreToolUse        |
| `probe_post_tool_use.py`       | PostToolUse       |
| `probe_user_prompt_submit.py`  | UserPromptSubmit  |
| `probe_subagent_stop.py`       | SubagentStop      |
| `probe_pre_compact.py`         | PreCompact        |
| `probe_stop.py`                | Stop              |
| `probe_notification.py`        | Notification      |

---

## How to enable probes (settings.json snippets)

Add any subset of the following to your `~/.claude/settings.json` `hooks` object.
Use `$AIPASS_HOME` (set by provider settings) or replace with your actual repo root.

```json
{
  "hooks": {
    "PreToolUse": [
      {"hooks": [{"type": "command", "command": "python3 $AIPASS_HOME/.claude/hooks/probes/probe_pre_tool_use.py"}]}
    ],
    "PostToolUse": [
      {"hooks": [{"type": "command", "command": "python3 $AIPASS_HOME/.claude/hooks/probes/probe_post_tool_use.py"}]}
    ],
    "UserPromptSubmit": [
      {"hooks": [{"type": "command", "command": "python3 $AIPASS_HOME/.claude/hooks/probes/probe_user_prompt_submit.py"}]}
    ],
    "SubagentStop": [
      {"hooks": [{"type": "command", "command": "python3 $AIPASS_HOME/.claude/hooks/probes/probe_subagent_stop.py"}]}
    ],
    "PreCompact": [
      {"hooks": [{"type": "command", "command": "python3 $AIPASS_HOME/.claude/hooks/probes/probe_pre_compact.py"}]}
    ],
    "Stop": [
      {"hooks": [{"type": "command", "command": "python3 $AIPASS_HOME/.claude/hooks/probes/probe_stop.py"}]}
    ],
    "Notification": [
      {"hooks": [{"type": "command", "command": "python3 $AIPASS_HOME/.claude/hooks/probes/probe_notification.py"}]}
    ]
  }
}
```

---

## Example `last_ping.jsonl` output

```jsonl
{"event": "PreToolUse", "tool": "Bash", "cwd": "/home/user/Projects/AIPass", "agent_id": "sess-abc123", "timestamp": "2026-04-20T12:00:00.123456Z", "script_elapsed_ms": 2.1, "cli_version": "1.0.0", "env_has_claude_project_dir": true, "env_has_aipass_home": false}
{"event": "PostToolUse", "tool": "Read", "cwd": "/home/user/Projects/AIPass", "agent_id": "sess-abc123", "timestamp": "2026-04-20T12:00:01.456789Z", "script_elapsed_ms": 1.8, "cli_version": "1.0.0", "env_has_claude_project_dir": true, "env_has_aipass_home": false}
{"event": "Stop", "tool": "", "cwd": "/home/user/Projects/AIPass", "agent_id": "sess-abc123", "timestamp": "2026-04-20T12:05:00.000000Z", "script_elapsed_ms": 1.5, "cli_version": "1.0.0", "env_has_claude_project_dir": true, "env_has_aipass_home": false}
```

---

## How to run `drone @sentry hooks probe`

```bash
# Display a table of recent probe entries
drone @sentry hooks probe

# Test whether PostToolUse and SubagentStop fire in headless mode
drone @sentry hooks probe --subagent

# Generate a full matrix report grouped by event type
drone @sentry hooks probe --matrix
```

### Flag reference

| Flag          | What it does |
|---------------|--------------|
| *(no flag)*   | Read `last_ping.jsonl`, display Rich table of recent entries |
| `--subagent`  | Spawn a headless Claude Code process, then check if PostToolUse / SubagentStop fired |
| `--matrix`    | Group all entries by event, show counts and env-var truth table, write markdown report |

---

## Notes

- `last_ping.jsonl` is gitignored -- it is a live log file, not source.
- Probes are opt-in. The AIPass repo does **not** auto-wire them into `settings.json`.
- Each probe script contains its own `settings.json` snippet in its module docstring.
- Probes are pure stdlib Python -- no aipass imports, no third-party packages.
