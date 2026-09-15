# AIPass

Multi-agent framework. Autonomous agents (citizens) live in branches, deploy disposable sub-agents to do work.

User: user

# Startup protocol

On any greeting, silently run this sequence — no narration, no announcing steps. Just do it and respond with the status.

These steps are sequential and dependent — run each ONCE, wait for the result, then proceed. Never batch a command with its own follow-up read, and never fire duplicate calls. If output looks blank, wait — don't retry.

 - Read: `.trinity/passport.json`, `.trinity/local.json`, `.trinity/observations.json`, `README.md`
 - Refresh: `drone @prax dashboard refresh @<self>` — where `<self>` is your branch name (CWD directory name)
 - Dashboard: Read `DASHBOARD.local.json` — act on what needs attention (new mail → check inbox, active plans → note them). This is your single status glance.
 - announce ur current (PID)


Use drone commands for all operations. Never raw git, gh, file access, or python -m when drone provides it.

# Memories

Update `.trinity/` at natural breakpoints, after milestones, and on `/memo`.

Todos[] are a sticky-note pad, not a log: 10 live, each `{number, date, task, priority?}`, the task one line under 100 chars ("Check on seedgo's errors in logs"), no `status` field — the story lives in plans and sessions. **Delete each todo the moment it's done.** The oldest roll off by number to `.backup/todo/<branch>/backlog.json` at rollover (PreCompact) and at @memory's push; `drone @memory todo backlog` reads them, `todo restore <n>` brings one back. Rolling never closes anything, so **reconcile on load**: remove what is finished so it never resurfaces as open. A truncated `.trinity` read is a signal, not noise — say so first, then measure the file.