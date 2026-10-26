# .codex/ -- Codex CLI configuration

What Codex reads from this repo. Claude Code reads `.claude/`; the two-CLI picture, the spelling of each ritual on each CLI and the compact flow are in `src/aipass/aipass/docs/two_clis.md`.

```
.codex/
├── hooks.json          # The Codex hook rows, written by aipass doctor --fix from .claude/provider_manifest.json (cli.codex). Not hand-edited
├── skills/claude/      # $claude: the switch back to Claude Code. Codex-only on purpose; the shared skills ($prep, $memo, $compass) live in .agents/skills
├── hooks/              # Retired hand scripts
└── .backup/settings/   # Doctor's backups of the files it rewrites
```

## How hooks run

Codex reads `hooks.json` from the project and calls the bridge `src/aipass/hooks/apps/handlers/bridges/codex.py` with the event, or one hook as `Event:name`. The bridge tags each payload `provider: codex`, runs the same engine and handlers as Claude Code (`.aipass/hooks.json` says what is enabled here) and answers in Codex's envelope: a gate refusal is exit 0 with `permissionDecision: deny` and the reason, because Codex paints any non-zero handler exit as "Hook failed". Codex runs hooks and tool shells from its app-server daemon with the daemon's environment, not the pane's: `AIPASS_HOME` has to come from `~/.profile` (`setup.sh` writes it), and a daemon started before that export is stale until it is killed once. Rollouts live in `~/.codex/sessions/`; the session pointer hook reads the first line's `source` and skips `exec` runs.

## Skills

Codex scans `.agents/skills/` (the Agent Skills standard) and this folder's `skills/`. Custom slash commands do not exist in Codex; a skill is invoked as `$name` or picked from `/skills`. The words after `$name` arrive in the user message, so a skill states what they mean instead of using a placeholder. Only the switch skill stays here; everything shared goes in `.agents/skills/`.

`drone rm` refuses paths inside `.codex/`; the owner removes files here by hand.
