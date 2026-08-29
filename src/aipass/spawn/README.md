[← Back to AIPass](../../../README.md)

# SPAWN

**The agent factory and branch lifecycle manager for AIPass.**

**Module:** `aipass.spawn` | **Version:** 1.0.0 | **Created:** 2026-03-05

---

## What I Do

- Create new branches from the one citizen template — class (`manager` / `specialist`) is decided at mint
- Update branches from templates (single or batch by class, with --dry-run)
- Delete branches (archive + deregister)
- Sync registry against filesystem
- Regenerate template registries with fresh file hashes
- Replace all `{{PLACEHOLDER}}` patterns with branch-specific values
- Register new citizens in `AIPASS_REGISTRY.json`
- Mint each citizen's own `citizen_id` at birth — and a brand-new external project's own registry credential

---

## Quick Start

```bash
# Create a new branch
drone @spawn create /path/to/my_agent --role "Analyst" --purpose "Data reports"

# Preview an update before applying
drone @spawn update @my_agent

# Apply the update
drone @spawn update @my_agent --apply

# Check registry health
drone @spawn sync-registry
```

---

## Citizen Classes

Every branch belongs to a **citizen class**, which determines its template:

| Class | What It Means |
|-------|---------------|
| `manager` | A project's first citizen (citizen #1) — manages the project. ai_mail's wake-block keys on it: managers are emailed, never dispatched |
| `specialist` (default) | Every citizen minted after the first |

Both classes mint from the **one** template, `templates/citizen/` — full 3-layer scaffold:
.trinity/, .aipass/, apps/ (modules/ + handlers/ incl. json shim), tests/, docs/, logs/ —
50 files, 24 dirs. The class is a *behavioral* label in `identity.citizen_class`, not a
choice of scaffold shape (DPLAN-0319), which is why the template directory is named for
what it is rather than for a class.

**The class is decided at mint, not typed.** Citizen #1 of a project is born `manager`,
everyone after is `specialist`. An explicit class still wins if you pass one. The retired
names `aipass_framework`, `project_agent` and `builder` **refuse loudly** at every entry
point — they are never silently remapped, because a passport that quietly disagrees with
the value a caller typed is the exact drift the rename ends.

`admin` is permanently refused as a class or `--template` value — see Grant Admin below.

**Class is resolved from the passport, not guessed.** A leading positional is read
as a target path only when it is either a known class (`create <class> <path>`) or
carries an explicit path marker (a separator, `~`, `.`/`..`, or `@`). A bare token
with neither — `create wizard` — refuses by name instead of silently making a
branch called WIZARD in `./wizard` (APLAN-0007, fixed).

---

## Commands

All commands run through `drone @spawn <command>`.

### Create

```bash
drone @spawn create <path>                                    # Class decided at mint (manager if first, else specialist)
drone @spawn create <path> --role "Analyst" --purpose "Reports"  # With identity
drone @spawn create <path> --dry-run                           # Preview without touching disk
drone @spawn create @existing                                  # Adopt pre-existing agent
drone @spawn create ~/Projects/MyProject/agent_name            # External project (targets that project's own registry)
```

### Update

Update is **preview-only by default** — `--apply` required to execute changes.

```bash
drone @spawn update @branch_name                               # Preview changes (dry-run default)
drone @spawn update @branch_name --apply                       # Execute changes
drone @spawn update specialist --all --apply                   # All specialist-class branches
drone @spawn update @branch_name --dry-run                     # Explicit preview (same as default)
```

### Delete

```bash
drone @spawn delete @branch_name --dry-run                     # Preview
drone @spawn delete @branch_name --yes                         # Archive + deregister
```

**Delete refuses protected branches, and every live citizen is protected.**
`is_protected()` guards three layers, any one sufficient: the hardcoded floor
(spawn, devpulse, drone), a registry entry carrying `owner: true`, and a passport
with `citizenship.registered: true`. Since `create` writes `registered: true`, a
branch is protected from the moment it exists. There is no `--force` — retiring a
citizen means clearing that passport flag first.

Verified live 2026-08-13 (APLAN-0007): the `infrastructure (devpulse, drone, spawn)`
and `active citizen` refusals both fire and exit 1. The `registry owner` layer is
**unreachable in the live fleet** — `devpulse` is the only entry carrying
`owner: true` and it short-circuits at layer 1, so no branch can reach layer 2.
It is covered by unit tests against a synthetic registry, not by live behaviour.

### Sync and Regenerate

```bash
drone @spawn sync-registry                                     # Report healthy/stale/unregistered (registry found from CWD)
drone @spawn sync-registry <project_path>                      # Same report against another project's registry
drone @spawn sync-registry --fix                               # Rebuild .spawn/ tracking, register strays, fix passport registry_ids
drone @spawn sync-registry --fix --dry-run                     # Preview what --fix would change
drone @spawn sync-registry --check [--json]                    # Owner/identity health check only — never writes
drone @spawn regenerate-registry                               # Regenerate the citizen template hashes
drone @spawn regenerate-registry specialist                    # Named class (both classes share one template)
drone @spawn regenerate-registry --all                         # Every template directory

# Passport 2.0 migration — one-shot, dry-run by default (DPLAN-0319)
drone @spawn migrate-passports                                 # Measure every fleet passport, write nothing
drone @spawn migrate-passports --only @canary                  # Restrict to one branch
drone @spawn migrate-passports --confirm                       # Execute: backup to passport.json.pre_v2_backup, then write

# Repair — the bare scan is read-only ALWAYS; only --relocate and --clean-pollution execute, and both need --apply
drone @spawn repair <project_path>                             # Scan: pollution + registry path mismatches (read-only)
drone @spawn repair --relocate @branch src/pkg/branch --apply  # Move branch to new location
drone @spawn repair --relocate @branch path --relocate-artifacts --apply  # Move + .chroma/
drone @spawn repair <project_path> --clean-pollution --apply    # Archive + remove duplicate dirs
```

`repair <project_path> --apply` is not an execute mode — `repair_project()` reports and
never writes, so the flag changes nothing on the scan path. It is the two submodes that
act, and each refuses to act without `--apply`.

### Grant Admin (ceremony)

The devpulse-only admin privilege (DPLAN-0288). Spawn owns exactly one leg of it:
the `admin: true` flag on the devpulse registry entry. The flag **grants nothing on
its own** — the dispatch lane verifies five legs (verified caller, cert path, cert
content, HMAC signature, this flag).

```bash
drone @spawn grant-admin                                       # Write admin:true on the devpulse entry
drone @spawn grant-admin --registry /path/AIPASS_REGISTRY.json # Explicit registry
```

There is no branch argument: the seat is a constant. `admin` is also permanently
refused as a citizen class or template value — `create`, `update` and `sync` all
say no by name. Admin is never minted from a template; only Patrick's ceremony
grants it.

### Introspection

```bash
drone @spawn                                                   # No args — lists connected modules
drone @spawn --help                                            # Full help text
drone @spawn --version                                         # Version string
```

### Class registry — the gateway other branches import through

`apps/handlers/` is internal to this branch; its `__init__` refuses cross-branch
imports and points callers here. Other branches that need to resolve a
`citizen_class` read spawn's registry through the modules gateway rather than
mirroring the class table — a mirror makes the reader a fleet-wide single point
of failure the moment spawn renames a class.

```python
from aipass.spawn.apps.modules import get_template_dir, refuse_legacy_class

get_template_dir("specialist")        # -> Path(.../templates/citizen)
get_template_dir("aipass_framework")  # -> ValueError naming the retired name AND 'specialist'
get_template_dir("admin")             # -> ValueError, permanent refusal
get_template_dir("wizard")            # -> ValueError listing the registered classes
refuse_legacy_class("aipass_framework")  # -> the rename message
refuse_legacy_class("specialist")        # -> "" (not a retired name)
```

`get_template_dir` already refuses forbidden, retired and unknown values by
name, so "resolve, or tell me why not" is one call plus `try/except ValueError`.
`refuse_legacy_class` is the separate lane for callers that must distinguish
"this passport has not been migrated yet" from a hard error.

### Python API

```python
from aipass.spawn import spawn_agent

result = spawn_agent(
    "/path/to/new/agent",
    role="Data Analyst",
    purpose="Process incoming reports",
    traits="Precise, thorough"
)
# Returns on success: { success, branch_name, path, files_copied, dirs_created,
#                       files_skipped, renamed, registry_updated, registry_path,
#                       citizen_number, validation_issues }
# Returns on failure: { success: False, error, ...the same counters, zeroed }
```

---

## Architecture

```
spawn/
├── __init__.py                          # Public API (exports spawn_agent)
├── apps/
│   ├── spawn.py                         # Entry point — CLI routing, version, help
│   ├── modules/
│   │   ├── core.py                      # Create orchestrator (_spawn_agent, handle_command)
│   │   ├── update.py                    # Update CLI — single/batch by class
│   │   ├── delete.py                    # Delete CLI — archive + deregister
│   │   ├── sync_registry.py             # Registry repair CLI
│   │   ├── regenerate_registry.py       # Template registry regeneration CLI
│   │   ├── migrate_passports.py         # One-shot fleet passport 2.0 migration CLI
│   │   ├── export_seeds.py              # Tracked passport seeds CLI — live → .aipass/passport.seed.json, dry-run default
│   │   ├── repair.py                    # Structural repair CLI — scan, relocate, clean pollution
│   │   └── grant_admin.py               # Admin flag ceremony CLI (devpulse-only)
│   ├── handlers/
│   │   ├── class_registry.py            # Citizen class → template directory mapping
│   │   ├── file_ops.py                  # Template copy, path renaming, registry regeneration
│   │   ├── metadata.py                  # Branch name extraction, profile detection
│   │   ├── placeholders.py              # {{PLACEHOLDER}} replacement engine
│   │   ├── passport_migration.py        # Passport 1.x → 2.0 structure migration
│   │   ├── seed_ops.py                  # Passport seeds — build/validate/mint-from-seed, machine-local strip, stamp
│   │   ├── registry.py                  # Registry CRUD, find_registry(), project credential mint
│   │   ├── meta_ops.py                  # Branch metadata generation, hash computation
│   │   ├── mint_verify.py               # Read-only completeness check of a mint vs the template manifest
│   │   ├── receipt_ops.py               # Birth receipt — stamps .trinity/.template_version.json at mint
│   │   ├── update_ops.py                # Update workflow (path-based template walk)
│   │   ├── delete_ops.py                # Delete workflow (resolve → archive → cleanup → deregister)
│   │   ├── sync_registry_ops.py         # Registry sync (CWD-aware, external project support)
│   │   ├── regenerate_registry_ops.py   # Template registry hash regeneration
│   │   ├── repair_ops.py                # Pollution detection, branch relocation, registry path repair
│   │   ├── json_ops.py                  # JSON deep merge, backup utilities
│   │   ├── atomic_write.py              # Atomic text write primitive (stage → fsync → os.replace)
│   │   └── json/
│   │       └── json_handler.py          # JSON I/O + operation logging — 9 functions over aipass.aipass.shared
│   ├── json_templates/                  # Package marker for JSON template assets
│   └── plugins/                         # Package marker — no plugins shipped
├── templates/
│   ├── citizen/                         # The one citizen template (50 files, 24 dirs)
│   └── .archive/                        # Retired templates (aipass_framework, project_agent, birthright)
├── tests/                               # 27 test files, 707 tests
├── spawn_json/                          # JSON tracking directory
├── tools/                               # Branch verification utilities
├── docs/                                # Documentation
└── logs/                                # Prax log output
```

### Three-Layer Design

1. **Entry point** (`spawn.py`) — Routes CLI commands, never imports handlers directly
2. **Modules** (`modules/`) — Business logic coordinators, parse arguments, delegate to handlers
3. **Handlers** (`handlers/`) — Implementation details, pure functions where possible

---

## Workflows

### Create (`_spawn_agent`, core.py)

1. **Resolve** — Extract the branch name from the target path and refuse a target that sits inside another citizen's tree (any parent holding `.trinity/passport.json`). An existing directory that already has a passport is **adopted** instead of refused (see Adopt Existing)
2. **Lookup** — Resolve the citizen class to a template directory via class_registry
3. **Credential** — Resolve the target project's registry credential (`metadata.id`) **before anything is written**. `load_registry` MINTS a fresh uuid4 when the registry file is **missing** — that is what a brand-new external project is, and it stops its first citizen inheriting AIPass's own id. A registry that **exists but will not parse** deliberately gets no mint (id-less schema plus a logged warning): that is a live project whose credential we failed to READ, and inventing a replacement would re-credential it and orphan every passport already carrying the real one. The resolved value is handed to `add_to_registry`, which adopts it **only when it is creating the registry file** — keyed off `registry_path.exists()` captured BEFORE the load, because a `load_registry` that always returns an id makes "is it already set?" useless as a guard (2026-08-24)
4. **Copy** — Recursive copy of the class template to target (skips `__pycache__`)
5. **Rename** — Replace `{{BRANCH}}` in directory and file names
6. **Replace** — Substitute all `{{PLACEHOLDER}}` patterns in file contents, including `{{CITIZEN_CLASS}}` (sourced from the create call, not a baked literal)
7. **Identity ids** — Mint the citizen's own UUID ONCE and use it twice: stamped into the passport as `citizenship.citizen_id` (the citizen's unique id, rendered by faces as the passport number) and written as the `registry_id` of its `branches[]` registry entry. Minting it at registration time instead would be too late — the passport is written before the registry, so the two copies would be different UUIDs for one citizen. Distinct from `citizenship.registry_id`, which is the id of the REGISTRY holding the citizen and is shared by every citizen in a project (Patrick's ruling, 2026-08-24)
8. **Meta** — Generate `.branch_meta.json` (meta tabs load from `@memory` when available, degrading gracefully to empty when it's not)
9. **Verify** — Compare the minted tree against the template's own manifest (`.spawn/.template_registry.json`) and its on-disk contents. A file the template claims but the mint never produced REFUSES the create, names every missing path, and never reaches the registry — a gitignored template file used to mint a citizen with an empty `artifacts/` and no `inbox.json` while printing "Agent created" (2026-08-17). Custom `--template <dir>` trees carry no manifest and are verified against their own contents only. The partial tree is deliberately left on disk for inspection
10. **Receipt** — Stamp `.trinity/.template_version.json`: which trinity template version this citizen carries, in @memory's four-key shape (`template_versions`, `stamped`, `stamped_by: "spawn birth"`, `config_rendered`). The versions are read from the fleet's GOLD source (`memory/templates/*.template.json` → `document_metadata.schema_version`), never from spawn's own seeds — reading the seeds would let a drifted copy mint a receipt claiming a version the fleet never issued, and the lie would score green. Shape copied, never imported: birth must not fail because another branch's package does not import. A gold source that cannot be read stamps NOTHING and surfaces the miss in `validation_issues` — a receipt naming an unverifiable version is worse than an absent one, but a citizen unborn because @memory's files are unreadable is worse than both
11. **Registry** — Register in the target project's own `AIPASS_REGISTRY.json`. Placed after step 10 deliberately: a registered citizen always carries a receipt
12. **Owner** — Ensure at least one citizen in that project carries `owner: true`
13. **Validate** — Scan for any remaining `{{...}}` patterns

### Update (path-based template walk, `update_ops.py` v2.1.0)

The ID-based change-detection engine was replaced (P1 rewrite, TDPLAN-0006). The
current engine walks the template and decides per path — no renames, no pruning,
no snapshot phase.

1. **Resolve** — Branch path from the registry, citizen class from its passport, template directory from the class
2. **Directories** — Walk the template's directories and create any the branch is missing
3. **Files** — Walk the template's files and decide per file: missing → add (placeholders replaced, atomically written) · existing `.py` → **skip by design** · existing `.json` → deep merge (existing values win) · `passport.json` → heal against a narrow allowlist only (DPLAN-0262) · create-only paths → skip entirely
4. **Refresh** — Regenerate `.branch_meta.json` with current state

Create-only (never re-added, never overwritten): everything under `.trinity/`
except the passport heal, everything under `.ai_mail.local/` (a live mailbox is
@ai_mail's data, not spawn's), plus `DASHBOARD.local.json`,
`artifacts/birth_certificate.json`, `.seedgo/bypass.json` and
`tests/test_scaffold.py`.

### Adopt Existing (`create @existing`)

1. **Fix** — Repair `registry_id` in passport if stale (from registry recreation)
2. **Register** — Add to project registry, then ensure the project has an owner
3. **Receipt** — Stamp `.trinity/.template_version.json` **only if the directory has none**. Adoption fills a hole; it never restamps. A branch @memory's push already stamped carries `"memory push"`, and overwriting that with `"spawn birth"` would replace a true record of which lane last touched those files with a false one
4. **Update** — Run template update to sync scaffold files

---

## Tests

**764 passed | 1 skipped | 0 failed** across 27 test files (765 collected — parametrized cases expand),
measured 2026-08-28 from the repo root and from the branch directory (same tally both ways). The one skip is `test_scaffold.py`: the shipped
scaffold smoke test skips by design once a branch has a real conftest (see Known Issues).

| File | Focus |
|------|-------|
| `test_lifecycle.py` | End-to-end spawn lifecycle workflows |
| `test_json_handler.py` | JSON I/O, operation logging, standard API |
| `test_handlers.py` | Handler function behavior and integration |
| `test_modules_gateway.py` | The modules-package gateway other branches import through |
| `test_passport_migration.py` | Passport 1.x → 2.0 fleet migration: order, drops, renames, idempotency |
| `test_passport_birth_schema.py` | 2.0 block and key order on a newly minted passport |
| `test_regenerate_registry_ops.py` | Template registry regeneration |
| `test_update.py` | Branch update mechanics |
| `test_citizen_classes.py` | Citizen class validation and template discovery |
| `test_file_ops.py` | File copy, rename, placeholder replacement |
| `test_cli_routing.py` | Command routing and argument parsing |
| `test_contracts.py` | Handler contracts and interface compliance |
| `test_spawn.py` | Basic CLI routing and help |
| `test_error_resilience.py` | Error handling and edge cases |
| `test_check_fix_identity.py` | Owner/identity check and fix (DPLAN-0239 P4) |
| `test_admin_fence.py` | Admin grant ceremony + permanent admin-class refusal (DPLAN-0288) |
| `test_owner_resolver.py` | Owner resolution + `is_protected()` protection layers |
| `test_passport_drift.py` | Fleet passport drift canary |
| `test_template_hygiene.py` | Template content invariants |
| `test_output_streams.py` | stdout/stderr routing |
| `test_repair.py` | Structural repair + relocation |
| `test_citizen_id.py` | `citizen_id` minted once — passport and registry entry always agree |
| `test_registry_credential.py` | Credential mint asymmetry: missing registry mints, unreadable never does |
| `test_json_durability.py` | Torn-write durability — atomic writes across every JSON/text path |
| `test_birth_receipt.py` | Birth receipt lane — gold versions, receipt shape, seed-vs-gold drift, retire carries `.trinity` |
| `test_scaffold.py` | Shipped scaffold smoke test (skips once a real conftest exists) |
| `conftest.py` | Fixtures: mock templates, registry protection |

**Public functions:** 60 total, 60 tested (100%)

---

## Integration

### Depends On

- **aipass.prax** — Logging via `system_logger`
- **aipass.cli** — Console output (header, error, warning)
- **aipass.aipass.shared** — `json_handler` (the real implementation behind spawn's shim), `json_ops` (`deep_merge`, `backup_json`), `registry_discovery.find_registry`
- **aipass.memory** (optional) — `tab_renderer.render_all_meta_tabs` for meta tabs at create; import is guarded and degrades to empty
- Python stdlib (`pathlib`, `json`, `shutil`, `hashlib`, `re`, `argparse`, `uuid`)

### Provides To

- All branches — creation, template updates, registry management, citizenship
- Registry: CRUD operations on `AIPASS_REGISTRY.json` and `*_REGISTRY.json`

---

## Newborn Compliance

A citizen minted from `templates/citizen/` audits **100%** against the CI gate on
its first day — verified 2026-08-22 by minting one and running
`.venv/bin/python .github/scripts/seedgo_audit.py`, the real gate, floor 100.
Before this the same mint scored 79% and failed the gate, having earned none of
it (@canary's finding: their entry point was byte-identical to the template
apart from name substitution).

**Trinity: 100/100 on both classes, live-measured 2026-08-27** by minting a
citizen and running @seedgo's trinity checker against it. It scored 77 before
this: the receipt group at 0 and the file set at 80 (no
`.trinity/.template_version.json` existed until birth stamped one), top-level
keys at 78 (the seeds carried a `document_metadata.status` block the standard
deletes, and stamped `managed_by` in the wrong case), and meta lines at 0 (the
seeds' `_usage` prose and meta lines had drifted from @memory's gold templates).
The `.trinity` seeds are now derived from those gold templates, and
`tests/test_birth_receipt.py` pins them byte-for-byte — the pin goes red the
moment @memory bumps, which is the only honest way to hold a copy.

Two starter test suites ship at birth (`tests/test_cli_routing.py`,
`tests/test_json_handler.py`) because `test_quality` cannot reach 100 without
real tests. They are listed in the template's `.spawn/.registry_ignore.json`:
seedgo's architecture baseline treats every template file as a structural
requirement of **every** branch of that class, so adding them without that entry
dropped 9 existing branches to 99% and red-boarded the gate. Measured, not
assumed — the exclusion is what keeps a template addition from being a fleet-wide
mandate.

---

## Known Issues

- `.py` files never auto-update during `drone @spawn update` (by design) — template .py changes need individual branch dispatch
- `tests/test_scaffold.py` ships at create and is never re-added on update (`_NEVER_UPDATE_FILES`). In a branch with a real conftest it can only skip, so it cannot inform — @seedgo ruling, DPLAN-0291

---

## Metrics

- **Seedgo:** 100% with bypasses, 98% without — both re-measured 2026-08-25 (17 live bypass rules; the two newest, `atomic_write.py` and `mint_verify.py`, date from 2026-08-16/17)
- **Tests:** 764 passed, 1 skipped, 0 failed (2026-08-28, both rootdirs)
- **Module coverage:** 27/27 files (100%)
- **Template registry:** 50 files, 24 dirs (citizen — the one template both classes mint from)
- **Live command sweep:** 29/29 paths pass, incl. error and refusal paths (APLAN-0007, 2026-08-13)

---

*Last Updated: 2026-08-25*

[← Back to AIPass](../../../README.md)
