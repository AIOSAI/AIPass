# DPLAN-003: CLAUDE.md Replacement — aipass.md Architecture

Tag: architecture

> Replace all CLAUDE.md files with a single global pointer + per-directory aipass.md. End the cascade confusion permanently.

## Vision

One `~/.claude/CLAUDE.md` for the entire system. It says one thing: "read `aipass.md` in your current directory." Each project/branch/agent has an `aipass.md` that IS the startup file. No cascade, no bleed, no repos needed for containment. We control the system, not Claude Code's CLAUDE.md resolution.

## Current State

- CLAUDE.md cascade walks up to git root and merges everything — causes bleed between branches, between projects, between agents
- Multi-agent setups inside one project are impossible without git sub-repos (ugly, fragile)
- Trinity Pattern tried to solve this with hooks + templates but added more confusion (3 different CLAUDE.md files, hidden templates, wrong output format)
- Trinity Pattern now disabled/private — hooks removed, pip uninstalled
- AIPass project-level `UserPromptSubmit` hooks exist but aren't firing (needs investigation — possibly Claude Code session/scope issue)
- `.trinity/` memory files remain in place across projects — data is fine, just the tooling is disabled
- Dev-Pass CLAUDE.md still present and bleeding into AIPass (Patrick deleted some, context stale in current session)

## What Needs Building

- [ ] Write `~/.claude/CLAUDE.md` — universal pointer: "read aipass.md in your CWD"
- [ ] Define `aipass.md` format — what goes in it, how startup works, how branches use it
- [ ] Create `aipass.md` for devpulse (replace current CLAUDE.md + branch prompt setup)
- [ ] Delete ALL CLAUDE.md files from AIPass repo (root, .claude/, devpulse, all branches)
- [ ] Delete ALL CLAUDE.md files from other projects (Speakeasy, feel_good_app, test folders)
- [ ] Update spawn to create `aipass.md` instead of CLAUDE.md when scaffolding citizens
- [ ] Decide: do AIPass hooks stay in project `.claude/settings.json`? Or do we move prompt injection into `aipass.md` directly?
- [ ] Test: fresh session from devpulse with new setup — verify agent gets correct context
- [ ] Test: fresh session from feel_good_app — verify no AIPass bleed
- [ ] Clean up test folders (TEST-FOLDER-01, 02, 03, TEST_DIR.)

## Design Decisions

| Decision | Options | Leaning | Notes |
|----------|---------|---------|-------|
| Global CLAUDE.md content | A: Just "read aipass.md" / B: Include AI culture/philosophy | A first, evolve | Keep it minimal. One instruction. |
| aipass.md location | A: Project root / B: Branch directory / C: Both | C | Root = project-level, branch dir = branch-specific. Branch reads both. |
| Memory files (.trinity/) | A: Keep as-is / B: Rename to .aipass/ / C: Leave for now | C | Data is fine. Format can evolve later. Don't touch working files. |
| Hook strategy | A: Keep UserPromptSubmit hooks / B: Remove hooks, aipass.md does everything / C: Hybrid | TBD | Hooks are powerful but broken right now. Need to fix or replace. |
| Spawn integration | A: Update spawn templates / B: New scaffold command | A | Spawn already creates per-branch files. Just change the template. |

## Ideas

- `aipass.md` could be generated/updated by spawn, so format stays consistent across branches
- Could include a "last updated" timestamp so agents know if it's stale
- The global CLAUDE.md could also mention: "if no aipass.md exists, you're in an unmanaged directory — just be a normal assistant"
- CLAUDE.local.md is a real Claude Code feature (confirmed) — could be useful for per-machine overrides without touching aipass.md
- Long term: aipass.md could be the universal startup for ANY AI system (Claude, ChatGPT, Gemini) — not tied to Claude Code's CLAUDE.md at all

## Relationships

- **Related DPLANs:** DPLAN-002 (AIPass as portable infrastructure)
- **Related FPLANs:** None yet
- **Owner branch:** devpulse (architecture), spawn (implementation)
- **Seedgo standards:** `drone @seedgo audit aipass @branch` | `drone @seedgo standards_query aipass_standards`

## Notes

- Trinity Pattern disabled 2026-03-13. Repo made private. Pip uninstalled. Hooks purged from global + all projects. Memory files (.trinity/) preserved.
- The UserPromptSubmit hook output format issue was discovered: plain text stdout required, NOT JSON {"output":"..."}. This broke Trinity inject for all external projects since inception.
- CLAUDE.local.md confirmed as real Claude Code feature — "user's private project instructions, not checked in"
- Patrick: "if I'm confused, imagine someone new. We need to control our own system, not fight Claude Code's cascade."

---
*Created: 2026-03-13*
*Updated: 2026-03-13*
