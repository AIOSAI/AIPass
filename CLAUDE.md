# AIPass

A multi-agent framework where autonomous Agents(AIPass citizens) live in branches and deploy disposable sub-agents to do work.

**User:** Name

# AIPass — Startup protocol

On any greeting, silently read these files from CWD and run the commands — no narration, no announcing steps. Just do it and respond with the status.

**Read:** `.trinity/passport.json`, `.trinity/local.json`, `.trinity/observations.json`, `README.md`, `STATUS.local.md`
**Check:** If `.ai_mail.local/inbox.json` exists, read it. Process any mail — don't ask, 
**list:** `dropbox` files. Always report dropbox status,Ignore README.md
**Run:** `git status`

## Security

- NEVER read, access, or reference files in `~/.secrets/` or `/home/patrick/.secrets/`. This directory contains API keys, tokens, and recovery codes. No agent needs to see this. Code that programmatically reads keys (like the api branch) handles it — you don't.
- NEVER output credentials, tokens, or API keys in responses.

## Memories

Update `.trinity/` at natural breakpoints, after milestones, and on `/memo`. 