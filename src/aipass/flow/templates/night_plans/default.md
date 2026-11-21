# {plan_number} - {subject} (NIGHT SHIFT)

**Created**: {today}
**Branch**: {location}
**Status**: Active
**Type**: Night Plan

---

## What is an NPLAN?

Night Plans (NPLANs) are **one night shift**: the owner hands over a brief and goes away, the shift runs to it, and the morning report hands it back. Four sections, in order: Expectations (the contract), Ground Rules (how the shift behaves), Night Log (what happened), Morning Report (what he reads first).

**Finished = closed.** Posting the Morning Report to the owner finishes the shift, and whoever posted it closes the plan, no permission asked: `drone @flow close {plan_number}`. An NPLAN never outlives its night. Closing loses nothing: the registry keeps its row and `drone @flow restore {plan_number}` reopens it. When several open plans orbit one shift, any agent may close the lot and open ONE new plan for the live remainder, pointing back to the closed IDs.

---

## 1. Expectations

The owner's go-brief, near verbatim. This is the contract; the morning report is measured against it.

- **Wanted by morning:**
- **Out of scope:**
- **Limits** (pushes, max dispatches, branches not to touch):

## 2. Ground Rules

- **The owner is away until further notice.** Meet the expectations: keep rolling. A milestone is not a stopping point; pick up the next item. Stopping to idle is the failure mode.
- **No performance for its own sake.** Real work only, checked as it would be by day.
- **A true blocker is written down, then left.** Note it in the Night Log and move to what can still be done.
- **A question that needs the owner** (it touches many branches, or forks the direction) is PARKED under Morning Questions, multiple choice where it can be. Then carry on with something else.
- **Nothing short of data loss wakes him.**

## 3. Night Log

Timestamped, newest at the bottom. Write each entry so an agent resuming after a mid-shift compaction knows what is done, what is in flight and what comes next.

- `HH:MM` —

### Morning Questions

1. *Question* — (a) … (b) … (c) …

## 4. Morning Report

Written last, from the Night Log. Post it to the owner, then close this plan.

- **Done:**
- **Not done:**
- **Issues worked around:**
- **Questions parked:**

*Spoken summary: written only when the user asks for one, in plain sentences with no markup.*

---
*Created: {today}*
*Updated: {today}*
