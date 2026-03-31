# {plan_number}: {subject}

Tag: audit, branch-audit, {tag}

> Branch audit for @{tag} -- living document tracking health, issues, and improvements

---

## What is an APLAN?

Audit Plans (APLANs) are **living documents** -- they track the ongoing health, issues, and improvements for a specific branch. Unlike DPLANs (which capture a moment of thinking) or FPLANs (which track a build), APLANs persist across sessions and grow as the branch evolves.

**This IS for:**
- Recording branch health status and key metrics
- Tracking bugs, issues, and improvement opportunities as they're discovered
- Logging what's been dispatched and the results
- Maintaining a clear picture of what's open vs resolved
- Serving as working memory for the next time we touch this branch

**This is NOT for:**
- Building code -- that's an FPLAN
- One-off design thinking -- that's a DPLAN
- Quick fixes -- just do those directly

**APLANs are never trimmed and rarely closed.** They accumulate history. When a branch gets a major overhaul, start a fresh APLAN and archive the old one.

**Keep items current.** Check boxes when work is done. Add new issues as they're found. Update the metrics when you verify. This document should always reflect reality.

---

## Quick Status

| Metric | Value |
|--------|-------|
| **Health** | GREEN / YELLOW / RED |
| **Last verified** | {today} |
| **Open items** | 0 |
| **Tests** | 0 pass, 0 fail |
| **Seedgo** | 0% (0 standards) |
| **Bypass entries** | 0 |
| **CLI score** | Nav 0/5, Output 0/5 |

## Current State

### Summary
- Key facts about the branch

### Architecture
Brief description of how the branch is structured and what it does.

### What Works Well
- Things that are solid and don't need attention

## Issues Found

### Open

Use checkboxes. Mark resolved items with `[x]` and note which session resolved them.

- [ ] Issue description -- context and impact

### Resolved

- [x] Example resolved issue (S00 -- brief note on how it was fixed)

## What Needs Doing

### For @{tag} to handle (dispatch)
Items that require the branch itself to fix.

- [ ] Item description

### For devpulse to handle
Items that devpulse coordinates or fixes directly.

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
Session notes, discoveries, changes. Stamp each entry with session number and date.

**S00 ({today}):** Initial audit created.

## Listen (TTS-friendly summary)

Write a plain English summary of this audit here. No markdown, no symbols, no tables, no code blocks, no asterisks, no bullet points. Just natural sentences that can be read aloud by a text to speech tool. Cover the branch health, key open issues, and what needs attention next. Update this section whenever the audit changes significantly.

Last verified {today}.

---
*Created: {today}*
*Updated: {today}*
