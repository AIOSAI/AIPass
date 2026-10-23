# {plan_number}: {subject}

Tag: {tag}

> One-line description

---

## What is a TDPLAN?

Team Design Plans (TDPLANs) are **collaborative thinking across multiple branches** -- capturing ideas, brainstorming, investigating, planning, making decisions that span branch boundaries. Each participating branch owns section + works within it.

**This IS for:**
- Cross-branch design work where multiple branches each have responsibilities
- Coordinated planning where branches need to see each other's progress
- Problems touching multiple systems needing parallel investigation
- Shared decision-making where each branch contributes domain expertise

**This is NOT for:**
- Single-branch thinking -- that's DPLAN (Design Plan)
- Building code or executing tasks -- that's FPLAN (Flow Plan)
- Quick fixes -- just do those directly

**TDPLANs have no fixed structure beyond Team Sections.** Shared sections above are starting points. Add sections, remove sections, go wherever thinking takes you. Team Sections below are structured part -- each branch owns theirs.

**When plan ready to build**, create FPLANs per branch: `drone @flow create . "Subject"`. Each branch can create their own FPLAN from their section. TDPLAN stays as shared design record.

**Never trim TDPLAN.** Story -- conversations, decisions, dead ends, pivots -- as important as results.

---

## Vision
What we're trying to achieve together

## The Problem
What exists now + why it needs multiple branches to solve

## The Fix
High-level approach -- how pieces fit together across branches

## Design Decisions

| Decision | Options | Leaning | Notes |
|----------|---------|---------|-------|
| Example  | A / B   | A       | Why   |

---

## Team Sections

**Each branch owns their section. Edit freely within your section. Don't touch other sections.**

---

### {tag} SECTION (description of role)

**Owner:** @{tag}

**Responsibilities:**
- What this branch responsible for in this plan

**Implementation:**
- How this branch plans to approach their part

**Tests needed:**
- [ ] Test case 1
- [ ] Test case 2

**Notes:**
- Working notes, discoveries, decisions for this section

**Status:** Planning / In Progress / Ready / Complete

---

### BRANCH_B SECTION (description of role)

**Owner:** @branch_b

**Responsibilities:**
- What this branch responsible for in this plan

**Implementation:**
- How this branch plans to approach their part

**Tests needed:**
- [ ] Test case 1
- [ ] Test case 2

**Notes:**
- Working notes, discoveries, decisions for this section

**Status:** Planning / In Progress / Ready / Complete

---

### BRANCH_C SECTION (description of role)

**Owner:** @branch_c

**Responsibilities:**
- What this branch responsible for in this plan

**Implementation:**
- How this branch plans to approach their part

**Tests needed:**
- [ ] Test case 1
- [ ] Test case 2

**Notes:**
- Working notes, discoveries, decisions for this section

**Status:** Planning / In Progress / Ready / Complete

---

Add or remove branch sections as needed. Copy template above each participating branch.

---

## Ideas
Captured ideas, brainstorms, future possibilities. Add freely. Any branch can contribute here.

## Relationships
- **Related DPLANs:** None yet
- **Related FPLANs:** None yet
- **Related TDPLANs:** None yet
- **Coordinating branch:** Who created this plan + coordinates
- **Participating branches:** List * branches with sections
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
