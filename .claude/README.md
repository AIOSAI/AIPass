# .claude/ -- Claude Code configuration

What Claude Code reads from this repo. Codex reads `.codex/` and `.agents/`; the two-CLI picture, the spelling of each ritual on each CLI and the compact flow are in `src/aipass/aipass/docs/two_clis.md`.

```
.claude/
├── AGENTS.md                  # Project instructions Claude Code loads beside the root AGENTS.md (the culture file)
├── commands/codex.md          # /codex: the switch to Codex. Claude-only on purpose, so Codex never lists a switch to itself
├── skills -> ../.agents/skills   # Symlink. The shared skills (/prep, /memo, /compass) live once, in .agents/skills; Codex scans that folder natively
├── provider_manifest.json     # The hook rows per CLI (cli.claude, cli.codex). aipass doctor --fix writes them to ~/.claude/settings.json and ~/.codex/hooks.json
├── settings.json              # Project settings: permissions, env (AIPASS_HOME for the bridge commands)
├── settings.local.json        # Personal override, untracked
├── hooks/                     # Retired hand scripts, all (disabled), plus hook_test.py, hook_report.py and probes/ for diagnostics
├── sounds/                    # Audio for the sound hooks
└── CLAUDE.md(disabled)        # Retired; AGENTS.md is the instruction file both CLIs read
```

## How hooks run

`~/.claude/settings.json` calls the bridge `src/aipass/hooks/apps/handlers/bridges/claude.py` with an event (`PreToolUse`) or one hook (`UserPromptSubmit:identity`, so each prompt injector gets its own block). The bridge runs the engine, which reads `.aipass/hooks.json` for what is enabled in this project and calls the Python handlers under `src/aipass/hooks/apps/handlers/`. Provider settings carry the wiring because Claude Code fires `UserPromptSubmit` and the tool hooks from user-level settings only; `.aipass/hooks.json` carries the control, so a hook is switched per project without touching the provider file. `setup.sh` wires a fresh clone; `aipass doctor --fix` repairs the wiring; `drone @hooks verify` checks it. The event table and the two-tier model: `src/aipass/hooks/docs/wiring.md`; the engine: `src/aipass/hooks/docs/engine.md`.

## Skills and commands

Claude Code reads a skill folder `.claude/skills/<name>/SKILL.md` exactly like a command file `.claude/commands/<name>.md`: both create `/name`. A shared ritual is a skill in `.agents/skills/` (the rule in `.agents/skills/README.md`), never a new file under `commands/`. Claude Code does not read `.agents/skills` natively; the symlink is why it sees them.
