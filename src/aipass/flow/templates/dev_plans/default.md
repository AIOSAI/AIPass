# {plan_number}: {subject}

Tag: {tag}

> One-line description

---

## What is a DPLAN?

Design Plans (DPLANs) are **thinking** -- capturing ideas, brainstorming, investigating, planning, making decisions. Space where conversations, research, design work get written down so they can be reclaimed later.

**This IS for:**
- Capturing idea or concept worth exploring
- Brainstorming + design discussions
- Investigating problem -- sending agents to research, running tests, gathering data
- Planning upgrade, refactor, or ! feature before building it
- Recording decisions + reasoning behind them
- Anything that needs thought through before (or instead of) executing

**This is NOT for:**
- Building code or executing tasks -- that's FPLAN (Flow Plan)
- Quick fixes -- just do those directly

**DPLANs have no fixed structure.** Sections below are starting points. Add sections, remove sections, go wherever thinking takes you. DPLAN might be quick idea capture or 50-phase investigation -- both valid.

**When plan ready to build**, create FPLAN: `drone @flow create . "Subject"` (default for focused tasks, `master` for multi-phase builds). DPLAN stays as design record.

**Never trim DPLAN.** Story -- conversations, decisions, dead ends, pivots -- as important as results.

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

*Spoken summary: written only when the user asks for one, in plain sentences with no markup.*

---
*Created: {today}*
*Updated: {today}*
