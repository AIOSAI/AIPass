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

**Fail-open is loud (cadence 2.5.0).** Turn 0 fires *every* loader, so any path that forces turn 0 —
no `CLAUDE_CODE_SESSION_ID`, an unreadable state file, a cadence import that raises — makes the session
pay the whole grounding bill on every prompt. Those paths logged at INFO for months and the fleet log
held no such line since 09-13. They now log
`[HOOKS] cadence FAIL-OPEN loader=<name>: turn forced to 0, so it fires EVERY turn — <cause>`.

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
