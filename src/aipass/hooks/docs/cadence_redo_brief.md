[<- Back to the README](../README.md)

# Cadence REDO brief — DPLAN-0200 WS-B (FPLAN-0249 reopen)

Your cadence build passed 435 tests but is **BROKEN in the live environment** — confirmed by direct observation + 3 research sub-agents. The 435 tests lied because they modeled the **wrong execution model**. Fix-forward: commit 2bccf03 stays, build on top, no history surgery.

## ROOT CAUSE (confirmed)
Each loader runs as a **separate OS process**. `settings.json` registers distinct commands: `claude.py UserPromptSubmit:global_prompt`, `:branch_prompt`, `:identity_injector`, `:email_notification`, `:auto_process` — 5 separate python subprocesses. The module-level `_turn` cache assumed **sequential single-process** dispatch (cadence_investigation.md:28 and :99 flagged this as THE fragility "if Claude Code ever parallelizes" — it was ALREADY true). So `global` increments the /tmp counter to N, `branch` (separate process) to N+1 → counter races +2/turn → the two loaders **leapfrog** → firing is erratic, never "both every 5th". Live proof: counter 33 → 35 → 37 across single turns.

## FIX 1 — DEDUP THE COUNTER (keystone)
The counter must advance **exactly once per real user turn** regardless of how many sibling processes call it.

- **PRIMARY — mtime/recency debounce** on the /tmp state file. In `_load_and_increment`, before incrementing, `stat` the file; if last-modified < ~2000 ms ago, treat as the SAME turn → re-read current turn, return WITHOUT incrementing. (The 5 siblings spawn near-simultaneously; the first increments, the rest reuse.)
- **BACKSTOP — per-turn token** = `transcript_path` SIZE / line-count (it grows by one entry per turn, identical across all siblings, monotonic). Only increment if BOTH the debounce window elapsed AND the token changed. Kills the two realistic failure modes (pathologically fast turn; identical-prompt collision).
- **REQUIRED — fcntl.flock** around the read-modify-write. The siblings are truly simultaneous; without the lock, two can both read old-mtime and both increment.
- **SPECIAL-CASE turn < 0** (post-compact reset): ALWAYS increment — don't let the debounce swallow the post-compact turn-0 all-fire guarantee.
- **STDIN FIELDS (corrected — the doc is WRONG):** UserPromptSubmit stdin = `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `prompt`. The field is `prompt`, NOT `user_prompt`; `session_id` IS present. Thread the token from `engine.py`'s parsed dict into `should_fire(loader_name, hook_data)`. Keep the `session_id`-keyed /tmp filename as the partition key (already correct). The `_turn` module cache may remain as an intra-process micro-opt but must NOT be the dedup authority.
- **Correct cadence_investigation.md** outdated claims (user_prompt, no-session_id, single-process).

## FIX 2 — PRAX-VISIBLE FIRE/SKIP LOGGING (the owner wants to SEE it in the monitor)
Cadence already imports prax `system_logger`, and `system_logs/hooks_cadence.log` is ALREADY tailed live by `drone @prax monitor run` as `[HOOKS]`. The gap: `should_fire` logs nothing on the decision. Emit ONE structured INFO line at the `should_fire` choke point (covers all loaders, one site):

```
[HOOKS] cadence <fired|skipped> loader=<name> action=<fired|skipped> turn=<N> period=<P> offset=<O> session=<8char>
```

Use `.info` (SystemLogger has no `.debug`). ALSO gate/dedup the "counter reset" log — it spammed ~8x per cluster; confirm PreCompact reset fires EXACTLY once and logs once.

## FIX 3 — ACTION-GATED SOUND (the false signal the owner HEARD)
Right now `speak("global prompt")` / `speak("branch prompt")` is the FIRST line of each loader, BEFORE the `should_fire` check — so piper announces every turn even when the loader SKIPS injection. The voice lies. The owner's rule: **if global/branch SKIP, they must be SILENT — sound ONLY on actual injection.**

Build the **system-wide** version (the owner wants it right for ALL hooks): handlers return an explicit `sound` key in their result dict, e.g. `{"stdout": content, "sound": "global prompt", "exit_code": 0}`; the engine plays it at `engine.py:208` inside the `if result["stdout"]:` block (or whenever the `sound` key is present) — ONE integration point, every hook auto action-gated + self-identifying. Remove the scattered leading `speak()` calls from the loaders. Preserve the gates/notifications that legitimately emit empty stdout (let them set the `sound` key explicitly). `is_muted()` still short-circuits.

Sound architecture for reference: `hooks/apps/sound.py` `speak()`/`play()` → piper → aplay; mute flag `/tmp/aipass-hooks-muted`.

## TEST PLAN (this is what 435 green MISSED — required)
- **Model separate-process execution:** simulate N independent processes each calling `_load_and_increment` for the same turn (no shared module cache) and assert the counter advances EXACTLY ONCE. REWRITE `test_cadence.py:113` `test_counter_increments_once_per_process` (it encodes the invalid single-process assumption).
- Assert the leapfrog is gone: two loaders in the same turn see the SAME turn number — both fire on offset-0 turns, both skip otherwise.
- Assert reset → next turn = 0 = all fire (the turn<0 special-case survives the debounce).
- Assert SKIP = silent (no `sound` key) AND logs `action=skipped` (not fired).
- Assert flock prevents double-increment under simulated simultaneity.

## ACCEPTANCE
Multi-process simulation tests green + seedgo 100% + pyright 0. But do **NOT** claim "works" from unit tests alone — that is exactly what failed. devpulse will LIVE-VERIFY next session (prax monitor shows correct fire/skip, sound only on inject, counter advances once/turn). Report what you built + test results. NO git commits (devpulse commits). Reply via dispatch if blocked.

Track in your FPLAN (reopen FPLAN-0249). This is the careful re-do — get it right, verify against the REAL execution model.
