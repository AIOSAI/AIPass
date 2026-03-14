# DPLAN-003: Registry Credential Model

## The Idea

Registries get a unique token. Passports carry that token. Access is identity-based, not filesystem-based. No walk-up needed — your credential proves which registry is yours.

## Why

Current system finds registries by walking up directories. Works for one project, breaks with multiple. If two AIPass projects exist on one machine, a citizen launched from the wrong directory finds the wrong registry. Credentials solve this — your passport carries proof of membership.

## Prior Art (Research)

| System | Pattern | Fit |
|--------|---------|-----|
| **Macaroons** (Google Research) | Token IS the credential. Delegatable with caveats. Offline verification. DeepMind validated for AI agent delegation (2026). | Highest |
| **Vault Namespaces** | Project = namespace. Token scoped to namespace. Mini-registry per project. | High |
| **AWS STS / Token Vending** | Agent presents project ID, gets scoped credential. Credential itself is the boundary. | High |
| **K8s Namespace + ServiceAccount** | Token carries project scope as claim. RBAC composable. | High |
| **SPIFFE/SPIRE** | Process-level attestation without static secrets. | Medium |
| **direnv** | Auto-set env vars on directory entry. Zero-friction UX. | UX pattern |

Full research: agent output from session 25.

## Design: Two Stages

### Stage 1: UUID Match (Manual, Now)

Simple. Prove the concept works before adding crypto.

**Registry gets an ID:**
```json
{
  "metadata": {
    "id": "a1b2c3d4-...",
    "name": "AIPASS",
    "version": "1.0.0",
    "last_updated": "2026-03-13",
    "total_branches": 15
  },
  "branches": [...]
}
```

**Passports get the matching ID:**
```json
{
  "citizenship": {
    "registered": true,
    "registry_id": "a1b2c3d4-...",
    "registry_name": "AIPASS",
    "citizen_number": 7
  }
}
```

**Lookup flow:**
1. Walk up from CWD, find `*_REGISTRY.json`
2. Read its `metadata.id`
3. Check citizen's `citizenship.registry_id` matches
4. If mismatch → error ("citizen belongs to registry X, found registry Y")
5. If match → proceed

**Spawn changes:**
- `aipass init` (or manual setup) generates the UUID for the registry
- Spawn reads registry UUID and injects into new passports via `{{REGISTRY_ID}}` placeholder
- Existing 15 branches get the UUID added to their passports (one-time migration)

### Stage 2: Macaroon Tokens (Future, When Cross-Project Needed)

Upgrade path when we need delegation and cross-project access.

**Root token:** Created at `aipass init`. HMAC-based. Stored at `~/.secrets/aipass/projects/<uuid>.token`

**Citizen token:** Attenuated copy in passport. Can prove membership but can't mint new citizens.

**Agent token:** Further attenuated. Carries:
- Registry ID (which project)
- Scope (full access — agents do the real work in AIPass)
- Expiry (session-scoped, dies when agent dies)
- Issuer (which citizen spawned this agent)

Agents are NOT read-only. They're the builders — they write code, run tests, modify files. The token proves they belong to a project, it doesn't restrict what they do within it. Scope restrictions would be role-based (e.g., "can't modify other branches' files") not capability-based.

**Verification:** Local HMAC check. No daemon needed for basic validation. Daemon is optional enhancement for audit logging and revocation.

**direnv integration:** Entering a project directory auto-sets `AIPASS_PROJECT_TOKEN` in env. Agents inherit it.

## What Changes (Stage 1)

| Component | Change |
|-----------|--------|
| `AIPASS_REGISTRY.json` | Add `metadata.id` (UUID) |
| Passport template | Add `citizenship.registry_id` placeholder |
| Spawn `build_replacements_dict()` | Read registry UUID, add `{{REGISTRY_ID}}` |
| Spawn `add_to_registry()` | No change (branch entries stay the same) |
| Drone `find_registry()` | Optional: verify passport.registry_id matches found registry |
| All 15 passports | One-time: add `registry_id` field |

## What Does NOT Change

- Registry filename stays `*_REGISTRY.json`
- Walk-up discovery still works (credential is verification layer on top, not replacement)
- Branch structure unchanged
- No daemon needed
- No new dependencies

## Resolved Questions

1. **Registry ID location** → `metadata.id` — it's the project's identity, not the citizen's.
2. **UUID4 vs hash** → UUID4 (random). Simple, guaranteed unique, no inputs needed.
3. **Verification mode** → Hard error on mismatch. Fail loudly — that's the AIPass way.
4. **Where does init live?** → Temporary: `src/aipass/devpulse/apps/init_project.py`. Future: CLI branch.

## Bugs, Quirks, and Findings

Discovered during testing. Reference for future work.

### init_project.py (10 edge cases tested)
- **Spaces in dir name** → registry filename gets spaces (`MY COOL PROJECT_REGISTRY.json`). Fixed: `_sanitize_name()` replaces non-alphanumeric with `_`.
- **Root path `/`** → `Path("/").name` is empty string, creates `_REGISTRY.json`. Fixed: validation rejects empty name.
- **Permission errors** → raw traceback instead of clean message. Fixed: `main()` catches `OSError`.
- **Passport overwrite on re-init** → if registry deleted but `.trinity/` survives, re-init would silently overwrite passport with new UUID. Fixed: passport guarded with `exists()` check.
- **Double init** → correctly blocked by `FileExistsError` on registry file.
- **Deep nested paths** → `mkdir(parents=True)` handles correctly.
- **UUID uniqueness** → 5 runs, 5 unique UUIDs. No collisions.
- **JSON validity** → all generated files parse clean.

### Drone isolation (6 scenarios tested)
- **Sibling projects** → PASS. Two projects in same parent dir, fully isolated.
- **Nested project** → PASS. Inner registry wins over outer. No bleed-through.
- **Deep subdir walk-up** → PASS. Finds nearest ancestor registry correctly.
- **Cross-project contamination** → PASS. Branches are registry-scoped; modules are global.
- **Empty directory (no registry)** → CONCERN. Drone silently falls back to AIPass source registry via `__file__` walk-up. Any dir on this machine without a registry sees production branches. This is by design in `find_registry()` but will be dangerous with multi-project. Credential verification would catch this — citizen's registry_id won't match the fallback registry.
- **`drone @ai_mail` from mock project** → correctly returns "Branch not found in registry" (empty project has no branches).

### Registry/passport gitignore
- `AIPASS_REGISTRY.json` and all `.trinity/passport.json` files are gitignored. UUID migration is local-only. This is correct for now — credentials are machine-specific, not repo state. But means `aipass init` must run on every clone/install. Future: consider whether UUID should be in-repo or machine-local.

### AI mail after migration
- Send/receive works fine after UUID migration. AI mail's 4 internal `find_registry()` copies still hardcode `AIPASS_REGISTRY.json` — functional for now since that filename exists, but won't find `*_REGISTRY.json` in other projects.

### Drone built-in modules vs branches
- `@drone` and `@seedgo` are hardcoded as "modules" in `module_registry.py`, always visible everywhere. Other branches (`@ai_mail`, `@spawn`, etc.) are registry-scoped. This distinction matters: modules are global services, branches are project citizens.

## Decision Log

- **2026-03-14:** Patrick proposed credential-based registry access. Agents do the real work — tokens prove membership, not restrict capability. Manual first, `aipass init` later.
- **2026-03-14:** Research confirmed macaroons as best-fit pattern (Google Research + DeepMind 2026 validation). Stage 1 = UUID match, Stage 2 = macaroon upgrade.
- **2026-03-14:** Scope limited to `src/aipass/` branches only. Commons and skills excluded.
- **2026-03-14:** All 4 open questions resolved. `init_project.py` built and tested — creates registry with UUID, passport with matching registry_id, .trinity/, .aipass/, AIPASS.md. Tested with temp directory — drone isolation confirmed (only built-in modules visible, not AIPass branches).
- **2026-03-14:** UUID migration executed (FPLAN-0030). Registry + 13 passports updated. Registry and passports are gitignored — UUID is machine-local, not repo state.
- **2026-03-14:** Drone verification added (`_verify_registry_credential` in load_registry). Drone dispatched and fixed error propagation — new `RegistryMismatchError` class separates "not found" (fallback OK) from "mismatch" (hard error). Spawn templates updated with `{{REGISTRY_ID}}` placeholder.
- **2026-03-14:** Stage 1 complete. Credential model is end-to-end: init creates credentialed registries, drone verifies on load, spawn injects into new passports, mismatch = hard error. Remaining: drone CLI stderr surfacing (DPLAN-0031), `aipass init` CLI command (future).
- **2026-03-14:** FPLAN-0032 executed — CLI stderr standardization Phase 1+2 done. CLI owns err_console, error()/warning() go to stderr. Drone imports from CLI instead of creating its own Console(stderr=True). Credential mismatch errors now properly surface to terminal via stderr. The stderr issue that blocked error visibility during DPLAN-003 testing is resolved.
- **2026-03-14:** CLI confirmed as owner of credential model + project commands. CLI owns: `aipass init` (create project), `aipass help` (project help), display API (error/warning/fatal/err_console). Drone owns verification (registry_handler). Spawn owns injection (passport templates). Access via `drone @cli aipass init/help` for now; `aipass init` entry point is future icing.
- **2026-03-14:** Seedgo `stderr_routing` standard created (24th standard). Checker bug found — was scanning all files but not displaying module/handler results. Seedgo fixed display + aggregation. Agent-verified across 3 branches. FPLAN-0033 parked for Phase 3 migration (343 error prints, 10 branches).
- **2026-03-14:** FPLAN-0033 Phase 3 executed autonomously (Patrick away). 15+ agents across 3 waves migrated 10 branches. 48 files, 666 insertions. System stderr avg 49%→69%. Post-migration verification found 63% of remaining seedgo violations are false positives ([yellow]Label:[/yellow] section headers flagged as warnings). Seedgo dispatched for checker refinement. 93 real violations remain (48 in commons which was out of scope).
