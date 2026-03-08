# DPLAN-0002: Prompt Architecture & Standards

Tag: infrastructure

> Design the prompt system so every branch has exactly what it needs — no more, no less — and seedgo can enforce it.

## Vision

Every branch gets a local prompt that orients it instantly. The system prompt (CLAUDE.md) + hook-injected global prompt + branch local prompt work together without duplication. Seedgo has a standard to audit prompt quality. New branches get a prompt template from spawn.

## Current State

- **CLAUDE.md** — lean system prompt (startup, hard rules, navigation, memory, docker). ~30 lines. Good.
- **Hook-injected global prompt** — identity_injector.py injects AIPass system context every turn. Contains terminology, branch structure template, commands, dispatch syntax, hard rules, memories. ~80 lines. Heavy — overlaps with CLAUDE.md.
- **Devpulse local prompt** — rewritten session 14. Lean, operational. Has branch list (needed for orchestrator role). ~55 lines.
- **Other branch prompts** — vary wildly. Some copied from devpulse template, some minimal, some empty. No standard.
- **No seedgo standard** for prompt quality.
- **No spawn template** for local prompts — spawn scaffolds branches but doesn't generate a prompt.

### Key Insight: Three Prompt Layers

| Layer | File | Injected | Purpose |
|-------|------|----------|---------|
| System | `CLAUDE.md` | Every turn (by Claude Code) | Hard rules, startup, navigation |
| Global | Hook output (`identity_injector.py`) | Every turn (by hook) | AIPass context, terminology, commands |
| Local | `.aipass/aipass_local_prompt.md` | Every turn (by hook) | Branch identity, role-specific guidance |

**Problem:** System + Global overlap significantly. Both have commands, rules, structure. That's ~110 lines injected every turn with duplication.

## What Needs Building

### Phase 1: Prompt Templates
- [ ] Define what goes in each layer (system vs global vs local) — no overlap
- [ ] Create local prompt template for **worker branches** (most branches)
- [ ] Create local prompt template for **orchestrator** (devpulse only)
- [ ] Create local prompt template for **infrastructure** branches (drone, prax, seedgo — they serve others)
- [ ] Add template to spawn's scaffold so new branches get a prompt automatically

### Phase 2: Consolidate System + Global
- [ ] Audit overlap between CLAUDE.md and hook-injected global prompt
- [ ] Decide: merge into one, or split responsibilities cleanly
- [ ] Option A: CLAUDE.md has rules + startup, hook has AIPass context (no rules)
- [ ] Option B: Kill CLAUDE.md, put everything in hook (single source)
- [ ] Option C: Kill hook injection, put everything in CLAUDE.md (simpler)
- [ ] Reduce total injected tokens

### Phase 3: Seedgo Standard
- [ ] Add prompt standard to seedgo audit pack (e.g. `prompt_quality`)
- [ ] Checks: file exists, not empty, has Identity section, has Current Context, under max lines
- [ ] Checks: no directory structures (belong in README), no duplicated rules (belong in system prompt)
- [ ] Checks: has @branch address references where needed (orchestrator only)

### Phase 4: Migrate All Branches
- [ ] Audit all 15 branch prompts against the template
- [ ] Rewrite each to match template
- [ ] Run seedgo prompt_quality checker on all

## Design Decisions

| Decision | Options | Leaning | Notes |
|----------|---------|---------|-------|
| System + Global merge | A: split clean / B: merge to CLAUDE.md / C: merge to hook | A | Hook gives dynamic injection, CLAUDE.md is static. Both have value. |
| Branch list in prompts | Devpulse only / All branches / None | Devpulse only | Orchestrator needs awareness. Workers get instructions, don't need full map. |
| Prompt max lines | 30 / 50 / 80 | 50 | Worker branches ~30, orchestrator ~55, infra ~40. Ceiling at 80. |
| Seedgo enforcement | Advisory / Blocking | Advisory first | Start with checklist, not gate. Tighten later. |
| Local prompt sections | Fixed template / Flexible | Fixed core + flexible extras | Identity + How You Work + Current Context required. Rest optional per role. |

### What Goes Where

| Content | Layer | Why |
|---------|-------|-----|
| Startup protocol | System (CLAUDE.md) | Universal, rarely changes |
| Hard rules (imports, paths) | System (CLAUDE.md) | Universal, authoritative |
| Memory update guidance | System (CLAUDE.md) | Universal behavior |
| AIPass terminology | Global (hook) | Context, not rules |
| Branch structure template | Global (hook) | Shows what a branch looks like |
| Command reference | Global (hook) | Available to all, operational |
| Dispatch syntax | Global (hook) | Operational pattern |
| Branch identity/role | Local | Unique per branch |
| Branch-specific commands | Local | What THIS branch does |
| Branch list (15) | Local (devpulse only) | Orchestrator needs it |
| Current context/session | Local | Unique per branch |

### Worker Branch Template (draft)

```
# {BRANCH} — Branch Prompt

## Identity
You are {BRANCH} — {one-line role}. {What you do, what you don't do.}

## Your Commands
{Branch-specific commands from --help, just the key ones}

## How You Work
{Role-specific operational guidance — 3-5 bullets}

## Current Context (Session N)
**Date:** YYYY-MM-DD
{Active work, blockers, recent changes}
```

## Ideas

- Could generate prompt health report: `drone @seedgo prompt-audit` showing all branches, line counts, missing sections
- Prompt version tracking — when template changes, detect stale prompts across branches
- "Prompt diff" tool — compare branch prompt against template, show gaps
- Dynamic section injection — hook could inject inbox count, active plans, etc. (already does email count)

## Relationships
- **Related DPLANs:** DPLAN-0001 (system bootstrap — prompts are part of bootstrap)
- **Related FPLANs:** Will spawn FPLANs for Phase 2 (consolidation) and Phase 4 (migration)
- **Owner branches:** @devpulse (design), @seedgo (standard), @spawn (template)

## Status
- [x] Planning
- [ ] In Progress
- [ ] Ready for Execution
- [ ] Complete
- [ ] Abandoned

## Notes
- Session 14: Discovered prompt vs memory distinction through Patrick's feedback. "Prompts are signposts, memories are knowledge." Every-turn injection must be minimal.
- The hook-injected global prompt is the biggest opportunity — it's ~80 lines injected every single turn across every branch. Reducing that by even 30% saves significant tokens per session.
- Patrick's key insight: "branches take instructions from devpulse — they don't need the full map, just their own commands and identity."

---
*Created: 2026-03-08*
*Updated: 2026-03-08*
