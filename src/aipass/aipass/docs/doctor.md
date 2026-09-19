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
| `doctor --fix` | A remediation report: the repair command for each failing row |
| `doctor --fix --json` | That report as JSON. `--json` alone falls through to the normal report |
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
same merge runs from the installer's `refresh_provider_hooks`, so both doors
agree. Code: [`apps/handlers/provider_wire.py`](../apps/handlers/provider_wire.py),
[`apps/handlers/provider_reconcile.py`](../apps/handlers/provider_reconcile.py)
and [`apps/modules/_doctor_wire.py`](../apps/modules/_doctor_wire.py).

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
