[← Back to Flow](../README.md)

# Plan Types — the filesystem-driven registry

How a plan type is registered, what makes one discoverable, and the three self-healing behaviours of the registry: auto-close of missing files, ignored folders, and orphaned locations. Owned by `template_manager` and `registry_monitor`.

---

| Type | Prefix | Registry | Templates |
|------|--------|----------|-----------|
| flow_plans | FPLAN | fplan_registry.json | default, master |
| dev_plans | DPLAN | dplan_registry.json | default |
| research_plans | RPLAN | rplan_registry.json | default |
| team_dev_plans | TDPLAN | tdplan_registry.json | default |
| audit_plans | APLAN | aplan_registry.json | default |
| playbook_plans | PPLAN | pplan_registry.json | default, merge, prompt_change, weekly_update |
| capture_plans | CPLAN | cplan_registry.json | default |

Plans follow the naming convention `{PREFIX}-{NNNN}_topic_slug_YYYY-MM-DD.md` where NNNN auto-increments per type.

**Where a prefix comes from.** `_derive_prefix()` (`handlers/template/registry_ops.py`)
drops a trailing `plans` segment, takes one initial per remaining word, and adds
`PLAN`: `dev_plans` → `DPLAN`, `team_dev_plans` → `TDPLAN`. The rule is
deterministic — the same directory name yields the same prefix on every install,
and all seven directories above derive exactly the prefix their registry row
holds (pinned against the live registry, not a table in a test). It used to read
the FIRST word only, so `team_dev_plans` derived `TPLAN` on a fresh clone while
this machine held `TDPLAN` from an earlier manual registration, and every
existing `TDPLAN-NNNN` file was unreadable there (ruled 2026-09-07). Only a
COLLISION still consults what is registered: a second directory wanting a taken
prefix widens to its first two letters, then returns None for manual
registration.

### Adding a New Plan Type
1. Create a directory in `templates/` with one or more `.md` template files
2. Run `drone @flow register <dirname> <PREFIX>` (or let auto-registration detect it on next command)
3. Use `drone @flow create . "Subject" <shorthand>` to create plans of the new type

### Auto-healing
- Template registry auto-prunes orphaned types (directory deleted → entry + plan registry JSON removed)
- Plan registries auto-close entries for missing files
- New template directories auto-register on next command

Auto-prune only fires while the type is **still registered** and its directory
has gone missing. `unregister <dir>` deliberately leaves the plan registry JSON
in place (see `remove_type()`), so unregistering *and then* deleting the
directory slips past the prune and strands a `<shorthand>_registry.json`
forever. `flow_json/pbplan_registry.json` is one such orphan.

### Ignored Folders

`IGNORE_FOLDERS` (`apps/handlers/registry/monitor_ops.py`) is the set of directory
names the registry scan never descends into — dev/VCS tooling, backups, archives,
and system paths that legitimately contain files matching the PLAN filename
pattern but should never be registered as live plans.

**Exact-match only, never substring/pattern matching.** A folder name is skipped
only when it equals an entry in the set exactly. Substring matching was tried
historically and broke: a folder named `dev` would substring-match inside
`devpulse`, silently skipping the entire `devpulse/` tree from scanning (see
`key_learning #33`, `registry_monitor_runaway_log_fix`). Exact-match avoids that
trap entirely — adding `dropbox` only ever matches a folder literally named
`dropbox`, never `devpulse-dropbox-clone` or similar.

`dropbox` is in the set because every branch has one as its received-files
inbox — anything can land there, including old snapshot/backup copies of plan
files with real `PLAN-NNNN` filenames, so no live plan should ever be scanned
out of a `dropbox/` tree.

The current folder list lives in `monitor_ops.py` itself (`IGNORE_FOLDERS`) —
that file is the source of truth; this README doesn't duplicate the list to
avoid drift. Both `registry_monitor`'s scan pass and `heal_registry`'s doctrine
self-heal (collisions / unregistered files / wrong-prefix rows) import this
same set, so a folder added here is skipped by both in lockstep.

### Orphaned Locations Heal Themselves

Branches get tested, moved and re-seated constantly, so plan rows pointing at
stale paths are **expected debris, not an anomaly** (ruling 2026-08-16). Hand-
editing the JSON is the wrong fix: it does not stick while code elsewhere still
writes the stale value. `drone @flow registry scan` re-attributes them instead,
as part of a normal scan.

A row is orphaned when its `location` is not where its citizen lives — either
the path is gone from disk, or it exists but merely *contains* the seat (a
project root holding records that belong to the branch inside it). Detection is
deliberately those two signals only: a plan filed at the repo root or inside a
citizen's own subdirectory is a normal filing, and treating every non-seat path
as debris buried the real orphans under ~30 false positives when first tried.

Attribution runs on evidence, in order: a directory containing exactly one live
seat *is* that citizen's ground; failing that, exactly one live citizen sharing
the directory name **within the same repository**. A bare name match across
repositories is a coincidence, not an identity, and is refused.

Anything unattributable is **quarantined, never guessed and never dropped** —
the row stays untouched and `drone @flow registry status` lists it with the
reason, for a human ruling. Re-running the healer changes nothing the second
time.

---

