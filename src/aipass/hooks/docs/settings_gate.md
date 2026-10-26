[<- Back to the README](../README.md)

# Provider-settings gate

**Branch** hooks · **Code** `apps/handlers/security/settings_gate.py`, `apps/handlers/bridges/codex.py`, `apps/modules/bash_writes.py` (`changed_paths`)

No AI changes a provider's settings alone, on either CLI, from any seat. The owner accepts every change. `settings_gate` is the PreToolUse gate that enforces it. It is fail-closed (`handlers/config/gates.py`), runs on Bash, Edit, Write, MultiEdit and NotebookEdit, and sits just before `settings_backup`, so a Claude settings write it lets through is still copied and receipted.

## What it protects

| Class | Files |
|---|---|
| Codex settings | `~/.codex/*.toml` (`config.toml`, profiles, requirements), `~/.codex/hooks.json`, `~/.codex/auth.json`, `~/.codex/rules/**`; the same under `$CODEX_HOME` |
| Claude settings | `~/.claude/settings.json`, `~/.claude/settings.local.json` |
| AIPass provider wiring | `$AIPASS_HOME/.claude/provider_manifest.json`, `$AIPASS_HOME/.codex/hooks.json` |
| Provider installer | `aipass doctor --fix`, `setup.sh`, `provider_wire.py`, run from Bash |

A path counts from either end of a symlink: a link anywhere that lands on a protected file is that file.

Directories: `~/.codex`, `$CODEX_HOME`, `~/.claude` and `~/.codex/rules` are protected as folders too. A write into one (`cp x ~/.codex/`) is a write to that class. A move or delete of one, or of any folder that holds one (`mv ~/.codex ~/.codex.saved`, `rm -r ~/.codex/rules`, `mv ~ /tmp/h`), changes every file inside, so it is judged the same way. A copy into a folder that only holds one (`cp notes.txt ~/`) changes the copied file alone and passes. Listing or reading a folder is never judged. Not protected: a branch's or the repo's `.claude/settings.json` and `.claude/settings.local.json`, `.aipass/hooks.json`, and everything else under `~/.codex` (sessions, logs, skills).

## The decision

| Caller CLI | Target | Interactive | Headless |
|---|---|---|---|
| Claude Code | Codex settings, wiring, an installer | `ask`: the owner sees the file and the call | deny |
| Claude Code | Claude settings | allowed: Claude Code prompts on its own settings file natively | deny |
| Codex | any protected file | deny; the reason names the file and says to mail @devpulse, who asks Patrick | deny |

The caller CLI is the payload's `provider` (the Codex bridge sets `codex`; a payload without it is Claude's). A seat is headless when `AIPASS_SESSION_TYPE` is `dispatched` or `headless`, or when no interactive `claude` process runs the call: there is no `claude` ancestor, or it was started with `-p`/`--print` (`cc_sessions.cli_ancestor`). Every ask and every deny is a prax WARNING line: `settings_gate: <ask|deny> caller=<branch> cli=<cli> path=<file> tool=<tool>`.

## Why Codex is deny-only

Codex 0.164 parses `permissionDecision: "ask"` but does not support it. It marks the hook run failed and runs the call, and under `--dangerously-bypass-approvals-and-sandbox` nothing is shown. An ask reaching Codex is therefore an allow. `codex.py` turns any PreToolUse `ask`, from any handler, into a `deny` with the same reason before Codex reads it. `deny` holds under bypass mode.

## Installers

An AI running `aipass doctor --fix`, `setup.sh` or `provider_wire.py` from Bash rewrites provider files in one call, so the run is judged like a write to the wiring. Only an executed installer counts: the program itself (`./setup.sh`, `timeout 60 ./setup.sh`) or an interpreter's script operand (`bash setup.sh`, `python3 provider_wire.py`). A program that reads the file (`cat setup.sh`, `rg needle setup.sh`) passes. A person running them in their own terminal passes no hook, so there is no exemption.

## What it cannot see

The Bash lane sees what `bash_writes.changed_paths` sees: redirects, `sed -i`, `tee`, `cp`/`mv`/`ln` onto the path, a path an interpreter's `-c` program names as a literal, and every operand of a program that does not only read (`crudini --set <file>`, `ed <file>`). A path an interpreter builds at run time (`Path.home().joinpath(".codex/config.toml")`) is not seen; `bash_writes.NOT_CAUGHT` lists the rest.
