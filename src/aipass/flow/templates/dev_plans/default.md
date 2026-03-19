# {plan_number}: {subject}

Tag: {tag}

> One-line description

---

## What is a DPLAN?

Design Plans (DPLANs) are for **THINKING** -- capturing ideas, brainstorming, investigating, planning, and making decisions. They are the space where conversations, research, and design work get written down so they can be reclaimed later.

**This IS for:**
- Capturing an idea or concept worth exploring
- Brainstorming and design discussions
- Investigating a problem -- sending agents to research, running tests, gathering data
- Planning an upgrade, refactor, or new feature before building it
- Recording decisions and the reasoning behind them
- Anything that needs to be thought through before (or instead of) executing

**This is NOT for:**
- Building code or executing tasks -- that's an FPLAN (Flow Plan)
- Quick fixes -- just do those directly

**DPLANs have no fixed structure.** The sections below are starting points. Add sections, remove sections, go wherever the thinking takes you. A DPLAN might be a quick idea capture or a 50-phase investigation -- both are valid.

**When this plan is ready to build**, create an FPLAN: `drone @flow create . "Subject"` (default for focused tasks, `master` for multi-phase builds). The DPLAN stays as the design record.

**Never trim a DPLAN.** The story -- conversations, decisions, dead ends, pivots -- is as important as the results.

---

## Vision
What we're trying to achieve

## Current State
What exists now

## What Needs Building
- [ ] Item 1
- [ ] Item 2

## Design Decisions

| Decision | Options | Leaning | Notes |
|----------|---------|---------|-------|
| Example  | A / B   | A       | Why   |

## Ideas
Captured ideas, brainstorms, future possibilities. Add freely.

## Relationships
- **Related DPLANs:** None yet
- **Related FPLANs:** None yet
- **Owner branch:** Who builds this
- **Seedgo standards:** `drone @seedgo audit aipass @branch` | `drone @seedgo standards_query aipass_standards`

## Status
- [x] Planning
- [ ] In Progress
- [ ] Ready for Execution
- [ ] Complete
- [ ] Abandoned

## Notes
Session notes, discoveries, changes

---
*Created: {today}*
*Updated: {today}*
