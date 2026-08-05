# {plan_number} - {subject} (PLAYBOOK)

> **Create:** `drone @flow create . "Update #N - vX.Y.Z" weekly_update pplan` (template name before type)

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

---

## Steps

*The weekly-update multi-channel SOP (Update #N). Owner: VERA. Refined from
PPLAN-0008 / 0011 / 0015 / 0017 runs.*

### Ground truth first

- [ ] 0. **Open `r/AIPass/new` and READ the last posted update number and date.**
      The series number comes from the live sub — never from a plan title, a draft
      filename, or an unticked checklist. **An empty playbook is not evidence that
      its post never fired.** PPLAN-0017 sat with zero ticks and an empty run
      summary while its post had been live for 7 days; trusting the plan produced
      two posts numbered #11 and cost a delete-and-repost. Reddit titles are
      immutable, so the number is the one mistake that cannot be fixed in place.
      Chrome not running? Start it yourself — see **Driving Chrome** below.

### Scope and draft

- [ ] 1. Scope: read AIPass CHANGELOG + `git log origin/main` since the last posted
      update's window closed. Confirm the shipped version on main. Only claim what
      is on origin/main. If the plan was stamped a while ago, re-scope to current
      reality rather than shipping the stale window.
- [ ] 2. Draft the r/AIPass body: through-line first, receipts per claim, hyphens
      not em dashes, no banned words, durable numbers. Report losses and misses,
      not only wins — a dev log that only reports wins reads as marketing.
      EVERY post on EVERY channel includes the website: aipass.ai (Patrick
      directive 2026-07-27).
      Body ENDS with the series footer BEFORE first fire (bot posts cannot be
      author-edited): Fresh numbers (stars w/ delta, forks, citizens, latest
      release, tests, CI), Website: aipass.ai, changelog link, 'Raw dev logs
      always here at r/AIPass.'
      Title: `AIPass Update #N - ...` using the number confirmed in step 0.
- [ ] 3. Fact-check pass: every number/claim verified against the repo before
      posting. Re-verify anything carried over from an older draft — it may sit in
      a previous update's window and must not be presented as new.

### Fire and verify, one channel at a time

- [ ] 4. Reddit: `python3 tools/publish_reddit_update.py --title '..' --body-file
      body.md --dry-run` → check the injection line → real run (posts as
      u/aipass-poster via Devvit upload + uninstall/reinstall of r/AIPass).
- [ ] 5. **Verify the Reddit post yourself** — open `r/AIPass/new` and read it back.
      Confirm: title + number correct, body rendered, footer intact, no duplicate
      of a prior number. This is yours, not Patrick's. If the number collided, fix
      it NOW while the post is minutes old: `--delete <id>`, correct the body, re-fire.
      Content-only mistakes are a 60s `--edit <id>` (title stays immutable).
- [ ] 6. Bluesky: short promo via `drone @api integrations call publish_bluesky
      "text"` from the AIPass project root (#618). ONE text argument only — every
      argument posts verbatim, there is no --help. Verify via public.api.bsky.app
      XRPC getPostThread. Check `atproto` imports first (declared in the `[bluesky]`
      extra since 2026-07-28, but confirm after any venv rebuild).
- [ ] 7. X: Chrome MCP post as @AIPassSystem, verify on the profile. The aipass.ai
      link card renders automatically — free real estate, keep the URL in.
- [ ] 8. Leave mod-approve for Patrick; log any cleanup items.
- [ ] 9. Fill Run Summary + Listen, update `.trinity`, close the plan (auto-vectorizes).
      Post-mortem within 24h → `docs/reference/post_mortems/YYYY-MM-DD_slug.md`.

---

## Driving Chrome (do this yourself — do not wait for Patrick)

*Cold-start tested end to end 2026-08-04: killed Chrome, confirmed `[]`, relaunched,
reconnected, bound, read r/AIPass. Every step below is verified, not assumed.*

Chrome MCP needs a running Chrome carrying the Claude extension. Launching it is
**your** job; only the browser *selection* requires Patrick.

1. Check first: `list_connected_browsers`. An empty array `[]` means **no browser is
   running** — it does NOT mean the tooling is down. Never report Chrome as blocked
   without running this.
2. If empty, launch it yourself:
   ```bash
   nohup /usr/bin/google-chrome > /tmp/chrome.log 2>&1 &
   ```
   Use the **default profile** — plain `google-chrome`, never `--user-data-dir` and
   never a Playwright/CDP launch. The default profile is the one signed into
   @AIPassSystem, Bluesky, and Reddit; a fresh profile is signed into nothing and
   you cannot log it in.
3. Poll until it's up, then `list_connected_browsers` again. **Use `pgrep -x chrome`.**
   The launcher `/usr/bin/google-chrome` is a wrapper that execs
   `/opt/google/chrome/chrome`, so the running process is named `chrome`:
   - `pgrep -f "google-chrome"` → false positive, it matches your own shell command
   - `pkill -f "google-chrome"` → kills nothing, silently
   - `pgrep -x chrome` / `pkill -x chrome` → correct
   Measured cold start: extension reconnects ~1s after launch.
4. **Ask Patrick which browser to bind** — the tool contract requires listing every
   connected browser via AskUserQuestion; you may not self-pick. Then
   `select_browser` with the chosen deviceId. The deviceId is **stable across Chrome
   restarts**, so a choice he already made this session can be reused for the same
   device without re-asking.
5. `tabs_context_mcp {createIfEmpty: true}` → navigate → drive.

Notes:
- The extension can drop mid-session, often right after a click. Recovery is
  `list_connected_browsers` + `select_browser` again — **no Claude Code restart needed.**
- `list_connected_browsers` can briefly report a stale entry after Chrome dies. If a
  browser is listed but calls fail, confirm with `pgrep -x chrome` before concluding
  anything about the tooling.
- **Chrome MCP reads reddit.com fine.** The old "all my tools refuse Reddit" note is
  dead (superseded 2026-08-04). Verify every Reddit fire yourself.
- Close tabs you opened when the run is done.
- General rule this SOP was built on: when a tool "can't" do something, re-test the
  belief before reporting a blocker. Two stale beliefs (Chrome, Reddit) blocked real
  capability for months on nothing.

---

## Run Summary

Fill as you go — this is the vectorized trail. Be specific: PR numbers, tags, SHAs,
anything that broke and how it was handled.

- **Date:** {today}
- **Outcome:** (post IDs per channel, verified how)
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
