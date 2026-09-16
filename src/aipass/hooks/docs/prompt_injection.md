# Prompt injection: the caps, the cadence, the alerts

**Branch** hooks · **Code** `apps/modules/grounding_content.py`, `apps/modules/cadence.py`, `apps/handlers/prompt/`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

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
