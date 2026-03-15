# Pre-Compact Prep

Purpose: Button up everything before a manual /compact. Memories, plans, git — all tidy so the compacted summary has clean state to work from.

**Workflow:** `/prep` → review output → `/compact`

## Execution

1. Read `.trinity/passport.json` first — re-absorb your identity before writing anything
2. Do ALL of the following, then confirm what was updated

## 1. Memories (same as /memo)

- **.trinity/local.json** — Add/update session entry with summary of work done. Add new key_learnings for anything learned this session. Trim oldest sessions if over 20.
- **.trinity/observations.json** — Add collaboration insights if anything notable happened. Skip if nothing new.
- **.trinity/passport.json** — Only update if role/purpose/principles genuinely changed this session.

## 2. Active Plans

- Check any DPLANs or FPLANs referenced in this session
- Update their execution logs, status, decision logs with current state
- If a plan was completed, note it (but don't close — Patrick does that)

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
- Plans: [which ones updated]
- Git: [branch, uncommitted count, suggestion]
- Inbox: [count, action taken]
- Loose ends: [any flagged]

Ready for /compact.
```
