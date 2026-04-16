# Session Wrap-Up

Purpose: Button up everything at the end of a session — or before a /compact. Memories, plans, git — all tidy. Works for both closing out a chat and preparing for compaction.

**Workflow:** `/prep` → review output → close chat or `/compact`

## Execution

1. Read `.trinity/passport.json` first — re-absorb your identity before writing anything
2. Do ALL of the following, then confirm what was updated

## 1. Memories

Each memory file plays a distinct role. Update based on what actually changed this session.

- **`.trinity/passport.json`** — IDENTITY. Who you are: role, capabilities, principles. Only update if identity genuinely evolved this session.
- **`.trinity/local.json`** — YOUR MEMORY. Add/update session entry with a summary of work done. Add key_learnings for anything learned. Trim oldest sessions if over 20.
- **`.trinity/observations.json`** — YOUR MEMORY OF THE USER. Collaboration insights, preferences, friction points. Skip if nothing new about the user this session.
- **`STATUS.local.md`** — PUBLIC STATUS BEACON. Current work, known issues, todos, notepad. Auto-synced to central STATUS.md on PR events — this is how other branches see you. Keep Current Work accurate.

## 2. Active Plans

- Check any DPLANs or FPLANs referenced in this session
- Update their execution logs, status, decision logs with current state
- If a plan was completed, note it (but don't close — the user does that)

## 3. Git State

- Run `git status` — report uncommitted changes
- If there's a logical commit waiting, suggest it (don't commit without asking)
- Note the current branch and any open PRs

## 4. Inbox

- Run `drone @ai_mail inbox 2>/dev/null` — report any unread emails
- Close any that were already processed but not formally closed

## 5. Loose Ends

- Flag anything in-flight: running background agents, dispatched branches waiting for replies, pending decisions
- If anything can't survive compaction (e.g., agent IDs needed for resume), write it to STATUS.local.md Notepad

## Confirm

List everything updated. Format:
```
Prep complete:
- local.json: [what was added]
- observations.json: [updated / skipped]
- STATUS.local.md: [updated / skipped]
- Plans: [which ones updated]
- Git: [branch, uncommitted count, suggestion]
- Inbox: [count, action taken]
- Loose ends: [any flagged]
```
