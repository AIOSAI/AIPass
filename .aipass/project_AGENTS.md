# {name}
<!-- Before editing or adding to this file: read .aipass/PROMPT_STYLE.md (repo root) — the prompt format rules. -->

Agent workspace powered by AIPass.

# Startup protocol

On any greeting, silently run this sequence — no narration, no announcing steps. Just do it and respond with the status.

 - Read: `.trinity/passport.json`, `.trinity/local.json`, `.trinity/observations.json`, `README.md`

Use drone commands for all operations. Never raw git, gh, or file access when drone provides it.

# Memories

Update `.trinity/` at natural breakpoints, after milestones, and on `/memo`.
