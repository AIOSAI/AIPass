# Session Wrap-Up

Purpose: Button up everything at the end of a session — or before a /compact. Memories, plans, git — all tidy. Works for both closing out a chat and preparing for compaction.

**Workflow:** `/prep` → review output → close chat or `/compact`

## Execution

0. **Pin the interrupted thread FIRST** — before any wrap-up work, write one sentence naming what the conversation was doing when /prep fired (the live task, question, or build mid-flight — "nothing in flight" counts). Prep often auto-triggers mid-task and the wrap-up steps flush the thread from attention; this line is what gets it back. It becomes the Resuming line at the end.
1. Read `.trinity/passport.json` — re-absorb your identity before writing anything
2. Do ALL of the following, then confirm what was updated

## 1. Memories

Each memory file plays a distinct role. Update based on what actually changed this session.

- **`.trinity/passport.json`** — IDENTITY. Who you are: role, capabilities, principles. Only update if identity genuinely evolved this session.
- **`.trinity/local.json`** — YOUR MEMORY. Add/update session entry with a summary of work done. Add key_learnings for anything learned. Update todos[] with current in-flight items.
- **`.trinity/observations.json`** — YOUR MEMORY OF THE USER. Collaboration insights, preferences, friction points. Skip if nothing new about the user this session.

### Entry shape — one rule for all four types

`key_learnings`, `sessions`, `todos` (local.json) and `observations` (observations.json) all share ONE shape: a **list of objects, newest at the top (index 0)**. Every entry carries:

- **`number`** — a monotonic int per type (highest = newest, never reused). New entry's number = current max for that type **+ 1**.
- **`date`** — ISO date/datetime.
- Plus its text field + extras: key_learnings `{number, date, key, value}` · sessions `{number, date, summary, status, tags}` · todos `{number, date, task, priority, status}` · observations `{number, date, note, tags}`.

**When adding:** stamp `number` + `date`, then **prepend** (newest on top). **Don't hand-trim** sessions/key_learnings/observations — rollover archives the oldest *by number* to @memory automatically. **Todos are the exception** — rollover never touches them, so you prune done ones by hand (see Reconcile below).

### Reconcile todos — verify against reality, don't trust the label

Stored status drifts: a todo finished in a past session often never gets closed. Before writing the session entry, **audit every open todo against the actual system** — check the real state, not the stored `status`:

- Does the file/dir still exist (or is it gone)? Is the code path in or out? Does the README/doc actually say what the todo claims? Does the audit pass?
- **Close what's verifiably done** → note it in the session entry, then **DELETE the todo from the array**. Rollover never trims todos (they're operational — only sessions/key_learnings/observations roll), so done items left as `status: done` pile up and go stale across chats. Fail honestly — remove only on evidence, never just to tidy the list.
- **Re-scope what's partially done** → record which sub-items landed, keep the rest open.
- **Leave deferred / pending-decision todos open** — but confirm they're still real.

Quick checks beat assumptions: `ls`/`find` for files, `git ls-files`/`grep` for code/docs, `drone @seedgo audit` for standards. This step is the whole point of "close whats done."

## 2. Active Plans

- Check any DPLANs or FPLANs referenced in this session
- Update their execution logs, status, decision logs with current state
- If a plan was completed, note it (but don't close — the user does that)

## 3. Git State (Devpulse only)

- Run `git status` — report uncommitted changes
- If there's a logical commit waiting, suggest it (don't commit without asking)
- Note the current branch and any open PRs

## 4. Inbox

- Run `drone @ai_mail inbox 2>/dev/null` — report any unread emails
- Close any that were already processed but not formally closed
- Run `drone @devpulse feedback 2>/dev/null` — report unread cross-project feedback; view/reply/clear anything NEW (S304 F46: this box sat unread for 3 months because nothing invoked it)

## 5. Compass Review (Devpulse only)

- Run ONE `drone @devpulse compass review` — it serves the oldest-unreviewed entry. Judge it: still true → confirm; superseded → archive it and note what replaced it; wrong → fix or archive.
- One entry per prep, every prep. This is the curation cadence — review only works if it actually runs (DPLAN-0246: all 127 entries sat unreviewed because nothing invoked it).

## 6. Loose Ends

- Flag anything in-flight: running background agents, dispatched branches waiting for replies, pending decisions
- If anything can't survive compaction (e.g., agent IDs needed for resume), write it to local.json todos[]

## Confirm

List everything updated. Format:
```
Prep complete:
- local.json: [what was added]
- Todos: [reconciled vs reality — N done & removed, M re-scoped, K still open]
- observations.json: [updated / skipped]
- Plans: [which ones updated]
- Git: [branch, uncommitted count, suggestion]
- Inbox: [count, action taken]
- Compass: [entry #N reviewed — verdict]
- Loose ends: [any flagged]

Resuming: [the step-0 line — what was in flight when /prep fired, and the next concrete action on it]
```

**The Resuming line is the LAST line of the /prep reply, always** — even when it's "nothing was in flight; awaiting your direction." If something WAS in flight, don't stop at naming it: pick the thread back up in the same turn (or, before a /compact, make sure the line carries enough for the post-compact self to continue without re-asking). Prep is a pit stop, not a finish line.
