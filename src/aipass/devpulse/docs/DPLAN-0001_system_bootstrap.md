# DPLAN-0001: System Bootstrap

Tag: bootstrap

> Get all 15 modules operational with citizenship, comms, and branch awareness.

## Vision
Every module has citizenship (.trinity/), can receive email, and can be woken via dispatch. DevPulse has full visibility. The system runs as a coordinated multi-agent team.

## Current State
- All 15 branches registered and discoverable via `drone systems`
- All 5 new citizens granted birthright citizenship
- Registry cleaned of stale test entries (manually — sync-registry can't detect /tmp dirs that still exist)
- 13/15 branches respond to `drone @branch --help` (devpulse has no apps/ by design, commons needs DB init fix)
- Backup, daemon import fixes complete (relative → absolute)
- Skills import fixes complete + __main__ block added
- Commons entry point renamed (the_commons.py → commons.py)
- Wake dispatch tested on @memory — agent spawned successfully
- Tests need --isolate-registry flag or mock to stop polluting live registry

## What Needs Building

### Phase 1: Test Spawn Safety
- [x] Create mock test branch with apps/ to verify spawn passport doesn't clobber existing code
- [x] Verify birthright grants .trinity/ without touching apps/
- [x] Clean up test branch after verification

### Phase 2: Grant Citizenship
- [x] Grant birthright to backup (has apps/, is builder — but existing code, use passport)
- [x] Grant birthright to daemon (has apps/, same situation)
- [x] Grant birthright to memory (has apps/, same situation)
- [x] Grant birthright to skills (src/skills/, external)
- [x] Grant birthright to commons (src/commons/, external)
- [x] Clean stale test entries from registry (sync-registry --fix removed 6 stale)

### Phase 3: Drone Discovery
- [x] Verify `drone systems` shows all 15 branches
- [x] Test `drone @backup --help` — FIXED: agent converted 16 files relative→absolute imports
- [x] Test `drone @daemon --help` — FIXED: agent converted 8 files relative→absolute imports
- [x] Test `drone @memory --help` — WORKS
- [x] Test `drone @skills --help` — FIXED: added __main__ block + converted relative→absolute imports
- [x] Test `drone @commons --help` — FIXED: renamed the_commons.py → commons.py (DB init still fails, separate issue)
- [ ] Fix commons DB initialization (ported code, SQLite path issue)

### Phase 4: Wake & Comms
- [x] Send test email to each new citizen (all 5 delivered)
- [x] Verify inboxes receive messages (confirmed all 5)
- [x] Test wake on @memory — agent spawned successfully via dispatch
- [x] Confirm round-trip communication — memory replied to both emails, replies in devpulse inbox.json
- [ ] Fix `drone @ai_mail inbox` display — shows stale cached message, doesn't reflect actual inbox.json content

### Phase 5: Branch Prompts
- [x] Update devpulse local prompt (fixed paths, added all 15 modules with descriptions)
- [x] Fix devpulse passport (builder → manager)
- [ ] Build local prompts for new citizens (backup, daemon, memory, skills, commons)
- [x] Update global prompt branch count (10 → 15)
- [x] Disabled stale aipass_local_prompt.md

## Design Decisions

| Decision | Options | Leaning | Notes |
|----------|---------|---------|-------|
| commons/skills location | Move to src/aipass/ vs keep outside | Keep outside | They're not aipass system apps, they're external projects with their own namespace |
| Citizenship for existing code | spawn create vs spawn passport | passport | Passport adds .trinity/ without touching apps/ |
| Registry cleanup | Manual vs sync-registry --fix | sync-registry --fix | Let spawn's built-in tool handle it |

## Relationships
- **Related DPLANs:** None yet
- **Related FPLANs:** None yet
- **Owner branches:** devpulse (coordination), spawn (execution)

## Status
- [x] Planning
- [x] In Progress
- [ ] Ready for Execution
- [ ] Complete
- [ ] Abandoned

## Notes
Session 11. First DPLAN in AIPass. Patrick confirmed: commons and skills are NOT aipass system apps — they live outside src/aipass/ intentionally. Use spawn passport for existing directories to avoid clobbering code.

**Progress:** Phases 1-3 complete. All 15 branches discoverable, 13/15 responding to --help. Phase 4 in progress — wake tested on @memory, agent spawned. Phase 5 partial — devpulse prompt and passport updated, global prompt updated, 5 new citizens still need local prompts. 300 tests passing.

**Session 12 additions:** Fixed skills (added __main__ + absolute imports), fixed commons routing (renamed entry point), cleaned registry stale entries manually, tested wake dispatch on @memory. Tests pollute registry — needs isolation fix in spawn tests.

---
*Created: 2026-03-07*
*Updated: 2026-03-07*
