[<- Back to the README](../README.md)

# Diagnostics: the two log streams and the post-edit block

**Branch** hooks · **Code** `apps/handlers/lifecycle/auto_fix.py`, `apps/modules/diagnostics_state.py`, `apps/handlers/config/diagnostics.py`

---

## Two Log Streams

Hook execution is recorded twice, at different levels of detail:

| Stream | Contents | Default |
|--------|----------|---------|
| `logs/engine.jsonl` | Every hook — agent, exit code, timing, stderr, cwd. Source of truth for diagnostics. | Always on |
| `system_logs/hooks_engine.log` (prax) | Warnings, errors, blocks, engine lifecycle. Per-hook narration suppressed. | Quiet |

Per-hook narration runs ~3 lines per tool call, enough to dominate the prax stream and trip the runaway detector during ordinary multi-agent operation. It is off by default; nothing is lost, since `engine.jsonl` carries strictly more detail.

```bash
AIPASS_HOOKS_VERBOSE_LOG=1    # restore per-hook lines in the prax stream
```

A per-hook row in `engine.jsonl` has this shape (Notification shown):

```json
{"ts": 1793400000.1, "event": "Notification", "hook": "notification_sound", "agent_type": "", "agent_id": "",
 "exit_code": 0, "elapsed_ms": 3.2, "stdout_len": 0, "stderr_preview": "", "cwd": "/path", "session_id": "…",
 "notification_type": "permission_prompt"}
```

`notification_type` (Claude Code sends `permission_prompt` or `idle_prompt`) and `tool_name` are copied from the payload only when it carries them, so a Stop row has neither. An event with no hooks configured still logs one row, `{"ts", "event", "action": "no_hooks_configured"}`, plus the payload's `tool_name`, `notification_type` and `session_id` when present. Wiring Claude Code's `PermissionRequest` as a bare row (`claude.py PermissionRequest`) therefore logs which tool waits on a prompt, and decides nothing: no hook runs, the answer is empty, and Claude Code shows its own prompt.

The switch lives in `engine._log_detail()`, read per call, and is separate from prax's own DEBUG level (`SystemLogger.debug()`, silent under the default INFO level and opened with `AIPASS_LOG_LEVEL`). Blocks, crashes, timeouts, and trust-break banners are never suppressed.

## The diagnostics block

After an edit leaves type errors behind, `auto_fix` records them per seat under `aipass-diagnostics-state/` in the system temp dir and `edit_gate` stops you editing *other* files in that branch until they are fixed. Two rules keep that block honest:

**The block must be satisfiable.** An error whose cause is a name missing from another module is cross-file and never blocks edits to other files: `"X" is unknown import symbol`, `Import "Y" could not be resolved`, `"X" is not a known attribute of module "Y"`, `Cannot access attribute "X" for class "ModuleType"`. A red pin that imports or reaches names its module does not define yet therefore leaves the module, and every other file, open to edit. Red-first is mandated fleet-wide and the test and the implementation always live in different files, so blocking the resolving edit is unsatisfiable by any allowed action. One locally-fixable error among them keeps the block: a typo the file makes itself (`"x" is not defined`, an attribute missing from a class or from `None`) still blocks edits to other files.

**The block must be live, not remembered.** Before blocking, the gate re-runs pyright on the recorded file. Clean now → the state is dropped and the edit proceeds; still failing → the block quotes the *current* errors, not the recorded ones. So a resolving write the hook never observed (a Bash heredoc, an external editor) clears the block too. If the file cannot be re-checked (pyright missing, timed out), the recorded errors stand — unknown is not clean.

Re-validation is not free, and the cost is **not** confined to the blocking path: an edit to another file in the
branch while a state is recorded re-runs pyright first, whether it ends allowed or blocked. The common path (nothing
recorded) costs a few milliseconds; a pyright re-check runs over a second. `drone @hooks diagnostics_state` shows what is recorded and re-checks it live.

Known gap: if the recorded file no longer
exists — hard-deleted, renamed to `name(disabled).py`, or moved to `.archive/` — re-validation returns
"unknown" rather than "clean", and the block stands forever, quoting a path with nothing on it. Two of
those three are the house cleanup pattern. Escape: recreate the file clean, let re-validation drop the
state, then remove it.

**Scratch is not judged.** An edit under a directory
named `docs.local`, `dropbox`, `.backup` or `.archive`, or under the harness scratchpad (a `scratchpad`
directory below a `claude-<uid>` one), runs no check, records nothing, and answers
`[diagnostics] skipped: <ground> is scratch`. The lane's rows are the shipped tree's; on scratch they would be an order to dress throwaway code, and a
recorded error would block the seat's next edit. Git-ignored
paths are deliberately NOT skipped: `.trinity/` is ignored, and its JSON is what the corruption check guards.

## The injection ledger — what a seat was told, per turn

`apps/modules/injection_ledger.py` writes one JSONL line per engine dispatch that
put something in front of the model: `{ts, event, token, turn, hooks: {name: {chars, sha}}, total, delivered}`,
to `aipass-ledger-<session>.jsonl` in the temp dir beside cadence's state. Only what reaches the model is
counted — plain stdout on UserPromptSubmit and SessionStart, `additionalContext` on tool events — in UTF-16
units, the way Claude Code measures. `total` is what the hooks produced, `delivered` what the merged document
carried; they differ only when the merge dropped a block.

Rows are grouped on cadence's **turn token** (the transcript size at the prompt), not the turn number:
parallel UserPromptSubmit siblings share the token exactly, while a sibling that finishes before the counter
increments reads the previous number.

A UserPromptSubmit row also carries `automated`: whether the harness sent the prompt, as
`cadence.is_automated` read it. The verb marks those rows `automated`, so idle wakes can be counted from the
ledger without reading transcripts.

```bash
drone @hooks ledger                    # this session (else the most recently written, said so)
drone @hooks ledger --session <id> --last 5
```

**Warn-only.** Nothing reads it to decide anything. It warns in two cases: a single injection over the
10,000-unit persist line (the model saw a preview), and a record it could not write.

---

## Related

- [engine.md](engine.md) — what is written to each stream and when
- [edit_gate.md](edit_gate.md) — the gate the block is enforced by
- [prompt_injection.md](prompt_injection.md) — the caps and the cadence each ledger row is measured against
