# AIPass — Project Prompt

Project-level instructions loaded by Claude Code. Persists in context for the entire conversation.
Details live in README, --help, .trinity/ memories, and the Global Prompt (.aipass/aipass_global_prompt.md).

## Startup

On any greeting, silently read these files from CWD and run the commands — no narration, no announcing steps. Just do it and respond with the status.

**Read:** `.trinity/passport.json`, `.trinity/local.json`, `.trinity/observations.json`, `STATUS.local.md`, `README.md`
**Run:** `git status`, `drone systems`

## Navigation

- 15 branches under `src/aipass/` (+ commons at `src/commons/`, skills at `src/skills/`)
- `drone @branch --help` for commands. `drone systems` for branch list. README.md for architecture.

## Memories

Update `.trinity/` at natural breakpoints, after milestones, and on `/memo`. If compaction hits before you save, it's gone. Details in your branch prompt.


