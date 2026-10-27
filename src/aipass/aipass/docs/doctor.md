[<- Back to the README](../README.md)

# doctor

*What `aipass doctor` checks, what each flag adds, and what it refuses to do
for you.*

`aipass doctor` is the one command that answers "is this machine wired
correctly?". It aggregates — it owns no state of its own, and every row it
prints is something another owner could be asked directly.

## The groups

One pass produces seven groups, in this order:

- **System** — OS, shell, Python, RAM, CPU, install method, and the Claude Code
  version (AGENTS.md is read from v2.1.277; below it the row warns)
  ([`apps/handlers/system_detect/`](../apps/handlers/system_detect)).
- **Identity** — `AIPASS_HOME`, the registry and its shape, `hooks.json`, the
  passport's role, and the registry's record of the owner (repaired through
  `drone @spawn sync-registry --fix`).
- **Services** — what a session depends on: `drone systems` reachability,
  pytest collection, the provider manifest rows (hooks, env vars, permission
  rules, the settings scalars), the wire verification and stale deny rules.
- **Community** — the mailbox is readable and `dropbox/` is writable.
- **Structure** — agent placement, stray-file detection, and the instruction
  fence: every nested `projects/<name>` excludes the host's `AGENTS.md` and
  `CLAUDE.md` pairs through `claudeMdExcludes`; and the instruction shadow:
  Claude Code reads `AGENTS.md` only when no `CLAUDE.md` or `CLAUDE.local.md`
  sits in cwd or above, so a live one at the project root or in `.claude/`
  beside an `AGENTS.md` is a FAIL naming the file, the
  `mv <file> '<file>(disabled)'`, and whether its text equals `AGENTS.md`
  (different text is the owner's to copy over). `--fix` only renames: never a
  copy or a delete, never over an existing `(disabled)` file, never when the
  root holds `$HOME` or the file's folder resolves outside the root. Then
  gitignore coverage, read-only: a file on disk that git tracks under
  `.chroma`, `docs.local`, `dropbox`, `.spawn` or a `*_json` folder, or a
  `*_REGISTRY.json`, is one FAIL per folder or file with its count and
  `drone @git untrack [--recursive] <path>` as the fix; `--fix` never touches
  the index. The AIPass source tree is not measured: its `.gitignore` ships
  spawn's templates tracked on purpose
  ([`apps/handlers/structure_scan/`](../apps/handlers/structure_scan)).
- **Scaffold** — the stamped scaffold version, tier0 drift, missing and retired
  hook handlers for the project you are standing in. This is the group that
  tells you a scaffold update is owed; see
  [`scaffold_update.md`](scaffold_update.md).
- **Sandbox** — with `AIPASS_SANDBOX_ENABLED` off (the default; the hook gates
  do the containing), one PASS row and no prerequisite is checked. On, the
  kernel sandbox prerequisites — bwrap and whether it runs, node, srt, rg, the
  broker daemon — each a row, a missing one a FAIL; Linux only
  ([`apps/handlers/sandbox_check/`](../apps/handlers/sandbox_check)).

An `admin lane` row (`lit` / `dark` / `partial`) rides in the report as well.
It observes presence only and never errors —
`drone @devpulse admin_grant verify` is the authoritative check, and
[`admin_setup.md`](admin_setup.md) is the walkthrough.

## The flags

| Form | What it adds |
|---|---|
| `doctor` | The interactive report — the default, and it may offer to wire what it found |
| `doctor --verbose` | The same report with per-check detail |
| `doctor --fix` | A remediation report: the repair command for each failing row. A settings change is shown and asked first |
| `doctor --fix --yes` | The same, writing the settings change without the question |
| `doctor --fix --json` | That report as JSON, with the planned settings change under `provider_settings`; written only with `--yes`. `--json` alone falls through to the normal report |
| `doctor --cross-os` | Cross-OS pre-flight — OS-gap cross-reference plus routing, versions and hook status |
| `doctor --cross-os --e2e` | ...also runs the real e2e wiring suite. Heavy, opt-in |
| `doctor --cross-os --record [PATH]` | Write a machine-filled Run Record for the human acceptance pass |
| `doctor --info` | Module introspection, no checks |

A non-zero exit means at least one row failed. Measure it with output
redirected to a file — a pipe into `head` closes the stream early and reports
the wrong code.

## The provider wiring door

`doctor --fix` (and the interactive wire prompt) is the only in-process writer
of the personal `~/.claude/settings.json`. It reads what AIPass wants from
`.claude/provider_manifest.json` — hooks, env vars, permission rules, and the
`settings` scalar slot — and merges additively: a key that is absent is set, a
key that already carries your value is reported and **never** overwritten. The
same merge, all four parts, runs from the installer's `refresh_provider_hooks`,
so both doors agree; under Git Bash on Windows both also set `PYTHONUTF8=1`.
The one difference: install re-points `AIPASS_HOME` to the tree being installed,
and says so; `doctor --fix` never does, so a fix from a second checkout cannot
take the home from the first (the home-agreement row flags that split). The
row compares the tree Claude Code's settings name with the terminal's tree:
the registry root when it is an AIPass tree (it holds `src/aipass`), else the
tree an external project's `.claude/settings.local.json` or `settings.json`
names in `env.AIPASS_HOME`. Two AIPass trees fail the row.

Codex reads the same hook shape from the user-level `$CODEX_HOME/hooks.json`
(`~/.codex/hooks.json` when `CODEX_HOME` is unset), from every directory. Both
doors merge the manifest's `cli.codex.hooks` rows into it: rows running the
AIPass Codex bridge are replaced, every other row is kept, and the AIPass groups
come first in each event. A manifest with no `cli.codex` rows leaves the file
as it is. The `codex hooks` row passes when the AIPass rows match the manifest,
and warns, naming `aipass doctor --fix`, when they are missing or differ. Once
they match, `codex trust` checks that `~/.codex/config.toml` holds a
`trusted_hash` under `[hooks.state."<file>:<event>:<group>:<index>"]` for each
of them, and warns with the step that trusts them: run `codex` once and choose
'Trust all and continue'. `codex double-fire` fails when the repo's
`.codex/hooks.json` still holds bridge rows, since Codex loads both files and
runs every hook twice; `--fix` leaves that file to the project.
Next to it, the `codex binary`, `codex login`, `codex model` and `codex pins`
rows read the Codex side and never write `~/.codex/config.toml`; see
[`two_clis.md`](two_clis.md).

Nothing is written before you see it. `doctor --fix` and plain `doctor` print
the planned changes, one line each, then a unified diff per file, and ask
once: `Apply these N changes to the provider settings? [y/N]`. Anything but
`y` writes nothing. With no terminal to ask on, `doctor --fix` writes nothing
and its row says `not applied: no tty — aipass doctor --fix --yes`; `--yes`
writes without the question. The install tail never asks: it runs inside the
one Enter you already gave the installer. Each receipt records the consent:
`y (tty)`, `--yes` or `install`. Code: [`apps/handlers/provider_wire.py`](../apps/handlers/provider_wire.py),
[`apps/handlers/provider_reconcile.py`](../apps/handlers/provider_reconcile.py)
and [`apps/modules/_doctor_wire.py`](../apps/modules/_doctor_wire.py).

## Every write to your provider settings backs up first

Before any of these doors writes the personal settings file (`doctor --fix`,
the install tail's doctor run, setup.sh's settings refresh, the stale-deny cleanup),
it copies the file into `~/.claude/.backup/settings/` as
`settings.json.<date>T<time>.<door>`. A write to Codex's `hooks.json` backs up
to `.backup/settings/` beside it the same way. Then, after the write, it adds one line to
`receipts.jsonl` in the same folder: when, which door, who, the backup's name,
and the file's sha256 before and after. `doctor --fix` prints both paths. The
backups are never pruned or rotated. If the backup or the receipt cannot be
written, the command fails and the settings file is left as it was. If the
write itself fails, the command fails too and no receipt is written; the
backup taken just before it stays. Code:
[`apps/handlers/settings_backup.py`](../apps/handlers/settings_backup.py).

## Both CLIs see every shared skill

The Scaffold group carries four rows about the skills in `.agents/skills/` and
the provider switch.
`shared skills` passes when each `SKILL.md` has a `name` and a `description` in
its frontmatter. `skills link` passes when `.claude/skills` is a symlink
resolving to `.agents/skills`, and warns when it is missing, a copy, or points
elsewhere. `legacy prep` warns when an old `.claude/commands/prep.md` sits
beside the skill, so `/prep` is offered twice. `provider switch` passes when
the project holds both `.claude/commands/codex.md` (`/codex`) and
`.codex/skills/claude/SKILL.md` (`$claude`), and names a missing one.
`doctor --fix` makes a missing link, writes a missing switch file and renames an
unedited legacy `prep.md` to `prep(disabled).md`, one `skills fix` row per
change; a copy, a foreign link, an existing switch file and an edited `prep.md`
are left for you. On Windows the link needs `git config core.symlinks true` and the
right to make links; without them `--fix` writes a copy that will not follow
`.agents/skills`, and the row says so.

## What it will not do

`doctor --fix` will not apply a scaffold update. An update can replace files, so
it is a decision and not a repair — the plan goes to a human first. The one
exception is a stamp-only plan; [`scaffold_update.md`](scaffold_update.md) has
the rule. The skills link and the legacy `prep.md` above are repairs, not an
update: neither overwrites a file.

Code: [`apps/modules/doctor.py`](../apps/modules/doctor.py), with the
remediation report in [`apps/modules/_doctor_fix.py`](../apps/modules/_doctor_fix.py),
the wiring rows in [`apps/modules/_doctor_wire.py`](../apps/modules/_doctor_wire.py),
the cross-OS lane in [`apps/handlers/cross_os/`](../apps/handlers/cross_os) and
the admin-lane reader in [`apps/handlers/admin_lane.py`](../apps/handlers/admin_lane.py).

---

[← Back to the AIPASS README](../README.md)
