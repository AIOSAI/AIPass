[<- Back to the README](../README.md)

# doctor

*What `aipass doctor` checks, what each flag adds, and what it refuses to do
for you.*

`aipass doctor` is the one command that answers "is this machine wired
correctly?". It aggregates — it owns no state of its own, and every row it
prints is something another owner could be asked directly.

## The groups

One pass produces seven groups, in this order:

- **System** — OS, shell, Python, RAM, CPU, install method
  ([`apps/handlers/system_detect/`](../apps/handlers/system_detect)).
- **Identity** — `AIPASS_HOME`, the registry and its shape, `hooks.json`, the
  passport's role, and the registry's record of the owner (repaired through
  `drone @spawn sync-registry --fix`).
- **Services** — what a session depends on: `drone systems` reachability,
  pytest collection, the provider manifest rows (hooks, env vars, permission
  rules, the settings scalars), the wire verification and stale deny rules.
- **Community** — the mailbox is readable and `dropbox/` is writable.
- **Structure** — agent placement and stray-file detection
  ([`apps/handlers/structure_scan/`](../apps/handlers/structure_scan)).
- **Scaffold** — the stamped scaffold version, tier0 drift, missing and retired
  hook handlers for the project you are standing in. This is the group that
  tells you a scaffold update is owed; see
  [`scaffold_update.md`](scaffold_update.md).
- **Sandbox** — sandbox and containment detection
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
take the home from the first (the home-agreement row flags that split).

Nothing is written before you see it. `doctor --fix` and plain `doctor` print
the planned changes, one line each, then a unified diff of the file, and ask
once: `Apply these N changes to ~/.claude/settings.json? [y/N]`. Anything but
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
`settings.json.<date>T<time>.<door>`. Then, after the write, it adds one line to
`receipts.jsonl` in the same folder: when, which door, who, the backup's name,
and the file's sha256 before and after. `doctor --fix` prints both paths. The
backups are never pruned or rotated. If the backup or the receipt cannot be
written, the command fails and the settings file is left as it was. Code:
[`apps/handlers/settings_backup.py`](../apps/handlers/settings_backup.py).

## What it will not do

`doctor --fix` will not apply a scaffold update. An update can replace files, so
it is a decision and not a repair — the plan goes to a human first. The one
exception is a stamp-only plan; [`scaffold_update.md`](scaffold_update.md) has
the rule.

Code: [`apps/modules/doctor.py`](../apps/modules/doctor.py), with the
remediation report in [`apps/modules/_doctor_fix.py`](../apps/modules/_doctor_fix.py),
the wiring rows in [`apps/modules/_doctor_wire.py`](../apps/modules/_doctor_wire.py),
the cross-OS lane in [`apps/handlers/cross_os/`](../apps/handlers/cross_os) and
the admin-lane reader in [`apps/handlers/admin_lane.py`](../apps/handlers/admin_lane.py).

---

[← Back to the AIPASS README](../README.md)
