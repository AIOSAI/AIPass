[<- Back to the README](../README.md)

# Prompt injection: the caps, the cadence, the alerts

**Branch** hooks · **Code** `apps/modules/grounding_content.py`, `apps/modules/cadence.py`, `apps/handlers/prompt/`

Every grounding block is rendered under a number, and the number is read from its owner rather than copied here.

---

## Injection caps — every grounding block is rendered under a number (DPLAN-0347)

The owner ruled the layer contract on 2026-09-15: each grounding layer has one job and one cap, and the
cap is **read, never copied**. The branch prompt is capped at **9,000** chars and each
`apps/integrations/*/private_prompt.md` at **2,000** (`grounding_content.py`); the rendered identity
block at **4,000** (`IDENTITY_CHAR_BUDGET`, declared 2026-09-08 and read by nothing until now).
Over-budget content is **cut with a marker naming the source file**, never dropped — Claude Code
persists a hook output over 10,000 UTF-16 units and shows the agent a 2,000-char preview, so a prompt
that crosses that line is not read at all. Every cut logs a WARNING naming the file and both numbers.
The `.trinity` caps and `passport.json`'s 6,000/600 are @memory's numbers; README 10,000 is @seedgo's.

**Degraded fail mode: kernel only, plus a warning (cadence 2.6.0, DPLAN-0347 hooks row 1).** When cadence
cannot count turns — no `CLAUDE_CODE_SESSION_ID`, an unreadable state file, a cadence import that raises —
it used to force turn 0, and turn 0 fires *every* loader: the whole grounding bill (21,383 chars measured)
on every prompt. Now only `DEGRADED_LOADERS` fire — the kernel and the two notice channels (alerts, mail) —
and navmap, branch and identity are **withheld**, not replaced: 3,750 chars a turn. cadence logs one WARNING
per degraded turn from the kernel's decision
(`[HOOKS] cadence DEGRADED loader=tier0 fires: turns cannot be counted, … — <cause>`) and the rest at INFO.
Dropping alerts and mail from `DEGRADED_LOADERS` makes the mode literally kernel-only. Measured before the
change: 0 real fail-opens in 1,190 cadence decisions over 24 h — this is a rare path made cheap and loud.

**The degraded banner.** Grounding a seat was promised but did not get — a stamped tree with no kernel, a
branch root with no prompt, a `.trinity` that will not render, a loader that raises — opens the kernel
block (and part 1 of the post-compact re-ground) with `[GROUNDING DEGRADED — …]`: what was carried, what is
missing and why, and that nothing was substituted, so any rule that lives there is unread. A tree that
promises nothing (no `.aipass/`, not a branch root) stays silent. `grounding_content.grounding_report()`
decides it in under a millisecond; the log line is WARNING on turn 0 and INFO on later beats, one warning
per context.

**Cadence-by-default: measured and NOT shipped (FPLAN-0593 Phase 5, hooks row 2).** The row was fenced as a
restatement: the same handlers fire on the same turns afterwards, or stop. DPLAN-0347 named 4 opt-outs
(`temporal`, `context_gauge`, `compass_recall`, `feedback_pulse`). This repo's `hooks.json` has 13
UserPromptSubmit entries and only 4 are plain period-5 loaders (`tier0`, `navmap`, `identity`, `branch`),
so a restatement needs **9** opt-outs: the named 4 plus `presence_gate` (a gate on every prompt),
`persistent_alert` and `email_notification` (fire on arrival first), `auto_process` and `user_message_relay`.
And a default lives in the engine, which every stamped project runs: Vera-Studio and wren carry `temporal`
and `context_gauge` with no opt-out key, so they would drop from every turn to every fifth until re-stamped.
That changes what fires, so it stopped there. What fires today is the record: an 11-turn trace per handler
(kernel, navmap, branch, identity, mail on turns 0/5/10; `temporal` every turn), identical before and after
this phase's other rows.

**A turn the harness sent is not a turn (cadence 2.7.0, DPLAN-0348).** Since Claude Code 2.1.271 a Monitor
dies at 30 minutes and wakes the seat with a `<task-notification>` prompt, and UserPromptSubmit hooks fire on it.
On 09-16 an idle seat took 33 of those in 15 hours, and 7 paid the full ~20,400-char stack. `cadence.is_automated`
reads the payload's `source` first (`system` = automated). The 2.1.273 schema declares that field, but no live
payload carried it: 6 were measured on 2.1.273 and 2.1.274, and the build hard-codes it out. So the
fallback is how the prompt *opens*: `<task-notification>` or `[SYSTEM NOTIFICATION`, left-stripped, never a
substring. A missing prompt reads as human. On an automated turn the counter does not advance, the state
file is not written (token included), and `should_fire` answers False for every loader, turn 0 too. Mail still
announces on arrival, and an alert's arrival never asks cadence. One behaviour change: a notification no
longer cancels queued post-compact re-ground parts.

**Ground once after a compaction (DPLAN-0348).** The PostToolUse backstop used to record nothing, so the next
prompt's turn-0 fire-all sent the same grounding again: 21,688 chars at 09:03, 20,310 more at 09:30. When
the backstop hands out its final part, it now stamps `aipass-regroup-done-<session>.json`: the window and the
transcript size at completion. A degraded or partial re-ground stamps nothing. At turn 0, `tier0`/`navmap`/
`identity`/`branch` stand down once if the stamp's window is the current one, and the prompt sits within
`regroup_fresh_bytes` of it: 150,000 in `DEFAULTS`, which a clone runs on, and an operator can override it in
the gitignored `cadence_config.json`. Every sibling of that prompt shares its
token, so all four agree. The number comes from the 09-16 ledgers. The double ground sat 126,258 bytes past
the last part. The other two post-compact prompts came after 308,557 and 587,488 bytes of autonomous work,
and those still ground. A second compaction opens a new window. A prompt straight after a compaction had no
backstop, so it grounds through turn 0 as before (DPLAN-0276's dead zone stays closed).

## Persistent Alerts

The `persistent_alert` handler (`prompt/persistent_alert.py`) injects advisory banners into every prompt when active alerts exist. General-purpose — any agent can raise alerts (prax for runaway logs, trigger for medic, backup for sync failures).

**How it works:** Reads `.aipass/alerts.json` at the project root. Each alert has an ID, source, severity (`warning`/`critical`), title, body, and optional `expires_at`. Expired alerts are auto-cleaned on read.

**On arrival, then on the beat (1.1.0, DPLAN-0347).** An alert announces on the turn it lands — a notification that waits four turns is not a notification — and after that the banner re-injects only on the cadence beat (loader `alert`, period 5). Until 1.1.0 the guard file silenced the *sound* alone and the full banner was re-injected every single turn for as long as the alert stayed active, up to ten alerts with uncapped bodies. Each body is now cut at 300 chars.

**Sound:** Piper TTS fires on first injection per alert ID — subsequent turns are silent for known alerts. New alerts trigger a fresh announcement.

**Dismissing alerts:** `drone @hooks dismiss <alert-id>` removes an alert by ID from `alerts.json`.

**Schema:**
```json
{
  "alerts": [{
    "id": "uuid", "source": "prax", "severity": "warning",
    "title": "High log rate", "body": "commons exceeds 50 lines/s",
    "created_at": "iso", "expires_at": "iso or null"
  }]
}
```

---

## Related

- [cadence_investigation.md](cadence_investigation.md) — the per-turn counter and why it is keyed per session
- [trinity_memory_gate.md](trinity_memory_gate.md) — the write-time half of the same contract
- [engine.md](engine.md) — how the injected blocks are merged into one document
