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

**APLANs are never trimmed.** They accumulate history.

**Finished = closed.** APLANs too: an audit whose findings are resolved or handed off is finished, and whoever finishes it closes it, no permission asked: `drone @flow close {plan_number}`. A standing audit still being worked is simply not finished yet -- that, not its type, is why it is open. Closing loses nothing: the registry keeps its row and `drone @flow restore {plan_number}` reopens it. When several open plans orbit one audit, any agent may close the lot and open ONE new plan for the live remainder, pointing back to the closed IDs.

**Keep items current.** Check boxes when work done. Add ! issues as found. Update metrics when you verify. Document should always reflect reality.

**ONE APLAN per branch.** Before creating, check for an existing one (`drone @flow list open` or your branch root) -- future audits UPDATE the living doc, never create a second. If the branch has a closed one, restore it instead of recreating: `drone @flow restore <ID>` fetches it back from the archive.

---

## Quick Status

| Metric | Value |
|--------|-------|
| **Health** | GREEN / YELLOW / RED |
| **Last verified** | {today} |
| **Open items** | 0 |
| **Tests** | 0 pass, 0 fail |
| **Sentry** | 0% with bypasses / 0% without (publish BOTH -- one number is how a branch lies about itself) |
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
- **Sentry:** `drone @sentry audit aipass @{tag}`

## Notes
Session notes, discoveries, changes. Stamp each entry: session number + date.

**S00 ({today}):** Initial audit created.

*Spoken summary: written only when the user asks for one, in plain sentences with no markup.*

Last verified {today}.

---
*Created: {today}*
*Updated: {today}*
