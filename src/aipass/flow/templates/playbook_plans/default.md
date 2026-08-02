# {plan_number} - {subject} (PLAYBOOK)

**Created**: {today}
**Branch**: {location}
**Status**: Active
**Type**: Playbook (SOP run)

---

## What Are Playbooks?

Playbooks (PPLANs) are **throwaway SOP runs** — a checklist stamped from a reusable
template for a recurring operation (merge, release cut, branch onboarding,
incident response). You tick steps off as you go, log what happened, then close.

- **The template = the SOP.** Stable. Refine it over time as the process improves.
- **The instance (this file) = one run.** Disposable. Close when the run is done.

Closing vectorizes the run to @memory — so the **Run Summary** below (with PR numbers,
tags, anything that broke) becomes a searchable trail. Costs nothing, gives history.

**This is NOT for:** building features (FPLAN), design/investigation (DPLAN),
research (RPLAN), or multi-branch builds (TDPLAN). Playbooks are for *operating the
system*, not changing it.

**Add a new SOP:** drop `templates/playbook_plans/<sop_name>.md`, then
`drone @flow create . "Subject" <sop_name> pplan` (template name before type).
No registration needed — any .md file stem in the type's templates/ dir works.

---

## Steps

Replace with the actual checklist for this SOP.

- [ ] Step 1
- [ ] Step 2
- [ ] Step 3

---

## Run Summary

Fill as you go — this is the vectorized trail. Be specific: PR numbers, tags, SHAs,
anything that broke and how it was handled.

- **Date:** {today}
- **Outcome:**
- **PRs / tags / commits:**
- **Issues hit:**
- **Notes for next run:**

---

## Listen (TTS-friendly summary)

Write a plain English summary of this run here. No markdown, no symbols, no tables,
no code blocks, no asterisks, no bullet points. Just natural sentences for text to speech.

---

## Close Command

When all steps are ticked and the Run Summary is filled:
```bash
drone @flow close {plan_number}
```
