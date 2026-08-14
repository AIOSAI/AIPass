# {plan_number}: {subject}

Tag: audit, branch-audit, {tag}

> Branch audit @{tag} -- living document tracking health, issues, improvements

---

## What is an APLAN?

Audit Plans (APLANs) are **living documents** -- track ongoing health, issues, improvements for specific branch. Unlike DPLANs (capture moment thinking) or FPLANs (track build), APLANs persist across sessions + grow as branch evolves.

**This IS for:**
- Recording branch health status + key metrics
- Tracking bugs, issues, improvement opportunities as discovered
- Logging what's been dispatched + results
- Maintaining clear picture: open vs resolved
- Serving as working memory next time we touch this branch

**This is NOT for:**
- Building code -- that's FPLAN
- One-off design thinking -- that's DPLAN
- Quick fixes -- just do those directly

**APLANs never trimmed, rarely closed.** They accumulate history. When branch gets major overhaul, start fresh APLAN + archive old one.

**APLANs STAY OPEN -- do not close on task completion.** (Patrick ruling, 2026-08-13.) Dispatch checklists + task footers saying "close your plan" do NOT apply to APLANs -- that instruction is for the task's FPLAN/PPLAN, never this document. Closing an APLAN archives the branch's living health record; a closed APLAN is a bug, not a completion. If one gets closed by mistake, restore it.

**Keep items current.** Check boxes when work done. Add ! issues as found. Update metrics when you verify. Document should always reflect reality.

**ONE APLAN per branch.** Before creating, check for an existing one (`drone @flow list open` or your branch root) -- future audits UPDATE the living doc, never create a second. If you find a closed one in `.backup/processed_plans/`, restore it instead of recreating -- current mechanic: move the file back to your branch root first, THEN `drone @flow restore <ID>` (the restore verb cannot yet fetch the file itself; @flow's APLAN-0004 tracks that build).

---

## Quick Status

| Metric | Value |
|--------|-------|
| **Health** | GREEN / YELLOW / RED |
| **Last verified** | {today} |
| **Open items** | 0 |
| **Tests** | 0 pass, 0 fail |
| **Seedgo** | 0% with bypasses / 0% without (publish BOTH -- one number is how a branch lies about itself) |
| **Bypass entries** | 0 total: 0 live / 0 dead (last measured: date) |
| **CLI score** | Nav 0/5, Output 0/5 |

## Current State

### Summary
- Key facts about branch

### Architecture
Brief description: how branch structured + what it does.

### What Works Well
- Things that are solid + don't need attention

## Issues Found

### Open

Use checkboxes. Mark resolved items `[x]` + note which session resolved them.

- [ ] Issue description -- context + impact

### Resolved

- [x] Example resolved issue (S00 -- brief note how fixed)

## What Needs Doing

### @{tag} to handle (dispatch)
Items requiring branch itself to fix.

- [ ] Item description

### devpulse to handle
Items devpulse coordinates or fixes directly.

- [ ] Item description

### Tracked elsewhere
Items captured in other DPLANs or FPLANs.

- [ ] Item description -- see DPLAN-XXXX

## Dispatch Log

| Date | Action | Result |
|------|--------|--------|
| {today} | Initial audit | Pending |

## Relationships
- **Related DPLANs:** None yet
- **Related FPLANs:** None yet
- **Owner branch:** @{tag}
- **Seedgo:** `drone @seedgo audit aipass @{tag}`

## Notes
Session notes, discoveries, changes. Stamp each entry: session number + date.

**S00 ({today}):** Initial audit created.

## Listen (TTS-friendly summary)

Write a plain English summary of this audit here. No markdown, no symbols, no tables, no code blocks, no asterisks, no bullet points. Just natural sentences that can be read aloud by a text to speech tool. Cover the branch health, key open issues, and what needs attention next. Update this section whenever the audit changes significantly.

Last verified {today}.

---
*Created: {today}*
*Updated: {today}*
