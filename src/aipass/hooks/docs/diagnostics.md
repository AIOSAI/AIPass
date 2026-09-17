# Diagnostics: the two log streams and the post-edit block

**Branch** hooks · **Code** `apps/handlers/lifecycle/auto_fix.py`, `apps/modules/diagnostics_state.py`, `apps/handlers/config/diagnostics.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

---

## Two Log Streams

Hook execution is recorded twice, at different levels of detail:

| Stream | Contents | Default |
|--------|----------|---------|
| `logs/engine.jsonl` | Every hook — agent, exit code, timing, stderr, cwd. Source of truth for diagnostics. | Always on |
| `system_logs/hooks_engine.log` (prax) | Warnings, errors, blocks, engine lifecycle. Per-hook narration suppressed. | Quiet |

Per-hook narration ran ~3 lines per tool call, which dominated the prax stream and tripped the runaway detector during ordinary multi-agent operation. It is off by default; nothing is lost, since `engine.jsonl` carries strictly more detail.

```bash
AIPASS_HOOKS_VERBOSE_LOG=1    # restore per-hook lines in the prax stream
```

The switch lives in `engine._log_detail()`, read per call. **Correction, 2026-09-05:** this section used to say prax's `SystemLogger` exposes only `info`/`warning`/`error` and so had no DEBUG level to demote to. It does now — `prax/apps/modules/logger.py:154` has `debug()`, silent under the default INFO level and opened with `AIPASS_LOG_LEVEL`. The env switch here predates it and still works; folding `_log_detail` onto `logger.debug` is an open cleanup, not a done one. Blocks, crashes, timeouts, and trust-break banners are never suppressed.

## The diagnostics block

After an edit leaves type errors behind, `auto_fix` records them in `.diagnostics_state.json` and `edit_gate` stops you editing *other* files in that branch until they are fixed. Two rules keep that block honest (both reported by @seedgo with a live repro, 2026-08-13):

**The block must be satisfiable.** An error that can only be resolved in another file — `"X" is unknown import symbol`, `Import "Y" could not be resolved` — never blocks edits to other files. Red-first is mandated fleet-wide and the test and the implementation always live in different files, so blocking the resolving edit is unsatisfiable by any allowed action. One locally-fixable error among them keeps the block.

**The block must be live, not remembered.** Before blocking, the gate re-runs pyright on the recorded file. Clean now → the state is dropped and the edit proceeds; still failing → the block quotes the *current* errors, not the recorded ones. Any resolving write the hook never observed (a Bash heredoc, an external editor) used to leave a block behind that outlived the error. If the file cannot be re-checked (pyright missing, timed out), the recorded errors stand — unknown is not clean.

Re-validation is not free, and — measured 2026-08-13, correcting an earlier claim here — the cost is
**not** confined to the blocking path. Of the `pre_edit_gate` invocations over 500ms in a live window,
7 of 8 **allowed** the edit, and 3 of the 4 blocks returned in ~0.1s. Common-path median is 6.8ms; the
slow path runs ~1.35s. So the expensive work is real but is not gated on blocking the way this section
originally described. `drone @hooks diagnostics_state` shows what is recorded and re-checks it live.

Known gap (reported by @seedgo, 2026-08-13, unfixed and escalated): if the recorded file no longer
exists — hard-deleted, renamed to `name(disabled).py`, or moved to `.archive/` — re-validation returns
"unknown" rather than "clean", and the block stands forever, quoting a path with nothing on it. Two of
those three are the house cleanup pattern. Escape: recreate the file clean, let re-validation drop the
state, then remove it.

## The injection ledger — what a seat was told, per turn

`apps/modules/injection_ledger.py` (DPLAN-0347 hooks row 3) writes one JSONL line per engine dispatch that
put something in front of the model: `{ts, event, token, turn, hooks: {name: {chars, sha}}, total, delivered}`,
to `aipass-ledger-<session>.jsonl` in the temp dir beside cadence's state. Only what reaches the model is
counted — plain stdout on UserPromptSubmit and SessionStart, `additionalContext` on tool events — in UTF-16
units, the way Claude Code measures. `total` is what the hooks produced, `delivered` what the merged document
carried; they differ only when the merge dropped a block.

Rows are grouped on cadence's **turn token** (the transcript size at the prompt), not the turn number:
parallel UserPromptSubmit siblings share the token exactly, while a sibling that finishes before the counter
increments reads the previous number.

A UserPromptSubmit row also carries `automated` (DPLAN-0348): whether the harness sent the prompt, as
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
