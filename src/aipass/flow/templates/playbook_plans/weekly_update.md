# {plan_number} - {subject} (PLAYBOOK)

> **Create:** `drone @flow create . "Update #N — vX.Y.Z" weekly_update pplan` (template name before type)

**Created**: {today}
**Branch**: {location}
**Status**: Active
**Type**: Playbook (SOP run)

---

## What Are Playbooks?

Playbooks (PBPLANs) are **throwaway SOP runs** — a checklist stamped from a reusable
template for a recurring operation (merge, release cut, branch onboarding,
incident response). You tick steps off as you go, log what happened, then close.

- **The template = the SOP.** Stable. Refine it over time as the process improves.
- **The instance (this file) = one run.** Disposable. Close when the run is done.

Closing vectorizes the run to @memory — so the **Run Summary** below (with PR numbers,
tags, anything that broke) becomes a searchable trail. Costs nothing, gives history.

---

## Steps

*The weekly-update multi-channel SOP (Update #N). Owner: VERA. Refined from
PPLAN-0008 / PPLAN-0011 / PPLAN-0015 runs.*

- [ ] 1. Scope: read AIPass CHANGELOG + `git log origin/main` since the last posted
      update. Confirm the shipped version. Only claim what's on origin/main.
- [ ] 2. Draft the r/AIPass body: through-line first, receipts per claim, hyphens
      not em dashes, no banned words, durable numbers. EVERY post on EVERY
      channel includes the website: aipass.ai (Patrick directive 2026-07-27).
      Body ENDS with the series footer BEFORE first fire (bot posts cannot be
      author-edited): Fresh numbers (stars w/ delta, forks, citizens, latest
      release, tests, CI), Website: aipass.ai, changelog link, 'Raw dev logs
      always here at r/AIPass.'
      Title: "AIPass Update #N — ...".
- [ ] 3. Fact-check pass: every number/claim verified against the repo before posting.
- [ ] 4. Reddit: `python3 tools/publish_reddit_update.py --title '..' --body-file
      body.md --dry-run` → check injection → real run (posts as u/aipass-poster
      via Devvit upload + uninstall/reinstall of r/AIPass).
- [ ] 5. Verify the Reddit post landed (Chrome MCP).
- [ ] 6. Bluesky: short promo via `drone @api integrations call publish_bluesky
      "text"` from the AIPass project root (#618). ONE text argument only — every
      argument posts verbatim, there is no --help. Verify via public.api.bsky.app
      XRPC getPostThread.
- [ ] 7. X: Chrome MCP post, verify on profile.
- [ ] 8. Leave mod-approve for Patrick; log any cleanup items.
- [ ] 9. Fill Run Summary + Listen, update .trinity, close the plan (auto-vectorizes).

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
