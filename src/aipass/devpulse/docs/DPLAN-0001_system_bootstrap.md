# DPLAN-0001: System Bootstrap

Tag: bootstrap

> Get all 15 modules operational with citizenship, comms, and branch awareness.

## Vision
Every module has citizenship (.trinity/), can receive email, and can be woken via dispatch. DevPulse has full visibility. The system runs as a coordinated multi-agent team.

## Current State
- All 15 branches registered, discoverable, and fully scaffolded
- All citizens are builder class (except devpulse = manager)
- 13/15 respond to `drone @branch --help` (devpulse has no apps/ by design, commons DB init fails)
- Import fixes complete: backup (16 files), daemon (8 files), skills (5 files)
- Commons entry point renamed (the_commons.py → commons.py)
- Wake + round-trip comms verified on @memory and @backup
- Seedgo audit: all branches passing (77-98%)
- gh CLI installed and authed for PR workflow
- 3 PRs merged: #17 (bootstrap), #18 (builder scaffold), #19 (commons/skills scaffold)

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
| Citizen class for ported code | birthright vs builder | builder | All branches with apps/ should be builder — birthright is for identity-only |
| External project scaffolding | spawn update vs manual | manual | spawn update can't reach outside src/aipass/, copy template files manually |

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

**Progress:** Phases 1-4 substantially complete. All 15 branches scaffolded as builder class. Wake + round-trip comms verified on @memory and @backup. Phase 5 partial — prompts need building for new citizens.

**Session 12:** Fixed skills (added __main__ + absolute imports), fixed commons routing (renamed entry point), cleaned registry stale entries manually, tested wake dispatch on @memory and @backup — both replied autonomously. Discovered passport was setting birthright instead of builder — fixed all 5, ran spawn update on backup/daemon/memory, manually scaffolded commons/skills. Installed gh CLI. PRs #17, #18, #19 merged.

**Remaining:** Commons DB init fix, ai_mail inbox display bug, branch prompts for new citizens, test registry isolation.

---
*Created: 2026-03-07*
*Updated: 2026-03-07*
