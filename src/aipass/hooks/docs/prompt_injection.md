[<- Back to the README](../README.md)

# Prompt injection: the caps, the cadence, the alerts

**Branch** hooks · **Code** `apps/modules/grounding_content.py`, `apps/modules/cadence.py`, `apps/handlers/prompt/`

Every grounding block is rendered under a number, and the number is read from its owner rather than copied here.

---

## Injection caps — every grounding block is rendered under a number

Each grounding layer has one job and one cap, and the cap is **read, never copied**. The branch prompt is
capped at **9,000** chars and each `apps/integrations/*/private_prompt.md` at **2,000**
(`grounding_content.py`); the rendered identity block at **4,000** (`IDENTITY_CHAR_BUDGET`).
Over-budget content is **cut with a marker naming the source file**, never dropped — Claude Code
persists a hook output over 10,000 UTF-16 units and shows the agent a 2,000-char preview, so a prompt
that crosses that line is not read at all. Every cut logs a WARNING naming the file and both numbers.
The `.trinity` caps and `passport.json`'s 6,000/600 are @memory's numbers; README 10,000 is @sentry's.

**Degraded fail mode: kernel only, plus a warning.** When cadence cannot count turns — no
`CLAUDE_CODE_SESSION_ID`, an unreadable state file, a cadence import that raises — only `DEGRADED_LOADERS`
fire: the kernel and the two notice channels (alerts, mail). Navmap, branch and identity are **withheld**,
not replaced. The mode does not force turn 0, because turn 0 fires *every* loader, the whole grounding
stack (~21,000 chars) on every prompt. cadence logs one WARNING per degraded turn from the kernel's decision
(`[hooks] cadence DEGRADED loader=tier0 fires: turns cannot be counted, … — <cause>`) and the rest at INFO.
A `should_fire` that raises instead of answering withholds navmap, branch and identity too: each raise is the
engine's ERROR fault line, one marker per loader that stays the same every prompt, so medic hears it once.
Dropping alerts and mail from `DEGRADED_LOADERS` makes the mode literally kernel-only. It is a rare path,
made cheap and loud.

**The degraded banner.** Grounding a seat was promised but did not get — a stamped tree with no kernel, a
branch root with no prompt, a `.trinity` that will not render, a loader that raises — opens the kernel
block (and part 1 of the post-compact re-ground) with `[GROUNDING DEGRADED — …]`: what was carried, what is
missing and why, and that nothing was substituted, so any rule that lives there is unread. A tree that
promises nothing (no `.aipass/`, not a branch root) stays silent. `grounding_content.grounding_report()`
decides it in under a millisecond; the log line is WARNING on turn 0 and INFO on later beats, one warning
per context.

**Cadence is per handler, not an engine default.** Only the loaders that ask cadence (`tier0`, `navmap`,
`identity`, `branch`, `alert`, and mail through `should_fire_mail`) are decided by cadence. Every other
UserPromptSubmit handler (`temporal`, `context_gauge`, `presence_gate`, …) fires on every prompt it is wired for.

**The shipped defaults.** `cadence.DEFAULTS` is what a clone runs on (`cadence_config.json` is gitignored).
`tier0` and `navmap` carry `"beat": false`: they ground at turn 0 (session start, `/clear`, post-compact)
and never on the period. `identity`, `alert` and mail beat every 5th turn and `branch` on the global
period (5), all at offset 0. An operator's `cadence_config.json` merges over each entry, so
`{"loaders": {"tier0": {"beat": true}}}` puts the kernel back on the beat.

**An unreadable cadence config prints to the seat's chat.** A `cadence_config.json` that cannot be read,
does not parse, or is not a JSON object leaves the built-in cadence running: no raise, because edit_gate
reads cadence and a raise there would refuse every memory write. `cadence.config_failure()` returns one
CRITICAL text naming the file, the read error, the lost custom cadence and the cure (`drone @ai_mail
dispatch @hooks`), logged at ERROR. `persistent_alert` prints it on every prompt until the file is fixed:
a `systemMessage` (the chat line on Claude Code and Codex) and model context ahead of any alert banner.
OpenCode's plugin carries the context only.

**The mail line names the kinds.** `notification/email.py` counts the branch's unread inbox rows by
their `kind` (@ai_mail `docs/mail_kinds.md`): `You have 4 new emails: 1 medic, 1 rounds, 2 mail - check
with: drone @ai_mail inbox | then: drone @ai_mail view <id> | close with: drone @ai_mail close <id>`.
`notice` rows (`Dispatch complete:` and the like) are neither counted nor named, so an inbox of only notices
prints no line and cadence sees zero. A stored kind outside the contract is named as it is; a row with no
`kind` is read by `aipass.ai_mail.mail_kind`.

**A turn the harness sent is not a turn.** A Monitor that expires wakes the seat with a `<task-notification>`
prompt, and UserPromptSubmit hooks fire on it. `cadence.is_automated` reads the payload's `source` first
(`system` = automated). The hook schema declares that field but live payloads do not carry it, so the
fallback is how the prompt *opens*: `<task-notification>` or `[SYSTEM NOTIFICATION`, left-stripped, never a
substring. A missing prompt reads as human. On an automated turn the counter does not advance, the state
file is not written (token included), and `should_fire` answers False for every loader, turn 0 too. Mail still
announces on arrival, and an alert's arrival never asks cadence. A notification does not cancel queued
post-compact re-ground parts.

**Ground once after a compaction.** When the PostToolUse backstop hands out its final part, it
stamps `aipass-regroup-done-<session>.json`: the window and the transcript size at completion. A degraded or
partial re-ground stamps nothing. At turn 0, `tier0`/`navmap`/`identity`/`branch` stand down once if the
stamp's window is the current one, and the prompt sits within `regroup_fresh_bytes` of it: 150,000 in
`DEFAULTS`, which a clone runs on, and an operator can override it in the gitignored `cadence_config.json`.
Every sibling of that prompt shares its token, so all four agree. The distance sits above where a prompt
would repeat a fresh re-ground and below a long stretch of autonomous work, after which the prompt still
grounds. A second compaction opens a new window. A prompt straight after a compaction had no backstop, so
it grounds through turn 0, which keeps the post-compact dead zone closed.

**The compaction summary is told what to carry.** Claude Code hands a PreCompact hook's stdout to the
summarizer as its instructions, so `pre_compact` (`lifecycle/compact.py`) writes to the summarizer, not to the
model after it. It asks for a closing section headed "Work still out": every task, dispatch and plan still open
with its next step, the uncommitted files, the unread mail count, the newest open plan and its last log line,
and the user's last instruction verbatim. It hands over the live facts it reads at that moment, and makes the
summary's final sentence `Next turn: resume the Work still out list first; answer the user's last line only
inside that work.` A dispatched seat is also told to save its memories first. Each fact is capped (25 files,
8 dispatches, 1,500 chars of the instruction, 300 per line) so the whole stays under 8,000 characters; Claude
Code cuts a PreCompact output at 10,000.

The facts: the seat tree's `git status --porcelain -- .` (other branches' files are not its work), the
dispatches @ai_mail still holds open that this seat sent or owes, the inbox's `unread_count`, the branch's newest
open @flow plan with the last line under its Night Log or Execution Log heading (fenced blocks and bold notes
skipped), the last session entry, and the newest prompt a person typed (tool results, meta rows and harness
wake-ups skipped). A reader that fails is written into the list as `could not be read (<error>)`, with a
WARNING, never dropped.

**After the summary, the same list is put in front of the model.** `compact_resume`
(`compact.handle_resume`, SessionStart, provider matcher `compact`) reads the same facts again and returns them
as `additionalContext` under `WORK STILL OUT — @<branch>`, ending `Resume this list before replying: answer the
user's last line only inside that work.` It answers nothing on any other source. The PostToolUse re-ground
needs a tool call after the compaction; a model that answers in text and stops never makes one.

**A branch can override a loader.** `cadence_config.json` takes a `branches`
map: `{"canary": {"loaders": {"tier0": {"beat": false}}}}`. The branch is the prompt's cwd's branch root
(`grounding_content.find_branch_root`), by name. Its entry for a loader is merged over the global entry
for that loader only, so a loader it does not name runs the global entry, and a branch with no entry runs
the global entries. `"beat": false` fires a loader at turn 0 (new chat, `/clear`, post-compact) and never on
the period; `period: 0` still means every turn. A cwd under no branch, or a payload with no cwd, runs the
global entries and logs `under no branch`. A malformed override (a non-object, a `beat` that is not a bool,
a `period`/`offset` that is not a whole number) logs ERROR and serves the global entry; the file is never
rewritten. Every decision line ends `beat=on|off session=… branch=<name>`. The post-compact backstop,
the mail loop and the degraded mode never read the override. The shipped config names no branch.

**A repo root can name its seat.** A Claude Code cloud session opens at the clone's root and cannot
leave it, and a root is under no branch. There, and only there, `AIPASS_SEAT=<branch>` stands in for
the cwd. `loader.seat_at_root` answers `src/aipass/<branch>` when the cwd holds `src/aipass` and that
branch holds `.trinity/`; any other name (a path, a dot name, no such branch) answers nothing. The three
walks use it at their no-branch exit: `grounding_content.find_branch_root` (branch prompt, cadence
key, mail banner), `grounding_content._find_passport` (identity) and `context_window.find_branch_dir`.
The same helper serves three more readers at the same edge: the presence gate names the seat and
searches for its occupant in the seat's directory, so a seated root session collides with a live one
in that branch, `compass_recall` judges the seat's passport for the
manager check, and `feedback_pulse` reads the seat's own `.aipass/` toggle. A cwd inside a branch
always wins over the variable. The context gauge reads only the transcript, so it is silent on any
first prompt until an assistant reply carries usage. Its window is the one the status line writes per
session; a session whose status line writes none prints `window unknown` whatever the seat, and a
settings window only caps a known one.

**A cloud session runs every hook.** The cloud environment's `aipass doctor --fix --yes` writes the
manifest's `cli.claude` rows into the VM's `~/.claude/settings.json`, every event included; the
clone's `.claude/settings.json` carries none. So the seat's grounding arrives as on any machine, and
the gates are live: the git gate refuses the agent's raw `git` in the VM as everywhere (seat, cwd and
`CLAUDE_CODE_REMOTE` change nothing), and `drone @git` reads pass. The harness commits and opens the
pull request through its own GitHub tools, which no PreToolUse matcher names, so no gate sees them.

## Persistent Alerts

The `persistent_alert` handler (`prompt/persistent_alert.py`) injects advisory banners into every prompt when active alerts exist. General-purpose — any agent can raise alerts (prax for runaway logs, trigger for medic, backup for sync failures).

**How it works:** Reads `.aipass/alerts.json` at the project root. Each alert has an ID, source, severity (`warning`/`critical`), title, body, and optional `expires_at`. Expired alerts are skipped on read; the file is trigger's, so the handler never removes them from it.

**On arrival, then on the beat.** An alert announces on the turn it lands — a notification that waits four turns is not a notification — and after that the banner re-injects only on the cadence beat (loader `alert`, period 5). Up to ten alerts are shown, and each body is cut at 300 chars.

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
