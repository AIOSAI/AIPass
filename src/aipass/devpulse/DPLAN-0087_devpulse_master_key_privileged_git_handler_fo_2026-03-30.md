# DPLAN-0087: Devpulse Master Key — Privileged Git Plugin for System-Wide Operations

Tag: master-key, git, devpulse-ops, plugin

> A drone plugin that gives devpulse (and future authorized users) the ability to create system-wide PRs, merges, and other privileged git operations — without raw git workarounds that cause rebase headaches.

---

## What is a DPLAN?

Design Plans (DPLANs) are for **THINKING** -- capturing ideas, brainstorming, investigating, planning, and making decisions. They are the space where conversations, research, and design work get written down so they can be reclaimed later.

**This IS for:**
- Capturing an idea or concept worth exploring
- Brainstorming and design discussions
- Investigating a problem -- sending agents to research, running tests, gathering data
- Planning an upgrade, refactor, or new feature before building it
- Recording decisions and the reasoning behind them
- Anything that needs to be thought through before (or instead of) executing

**This is NOT for:**
- Building code or executing tasks -- that's an FPLAN (Flow Plan)
- Quick fixes -- just do those directly

**DPLANs have no fixed structure.** The sections below are starting points. Add sections, remove sections, go wherever the thinking takes you. A DPLAN might be a quick idea capture or a 50-phase investigation -- both are valid.

**When this plan is ready to build**, create an FPLAN: `drone @flow create . "Subject"` (default for focused tasks, `master` for multi-phase builds). The DPLAN stays as the design record.

**Never trim a DPLAN.** The story -- conversations, decisions, dead ends, pivots -- is as important as the results.

---

## Vision

Devpulse orchestrates system-wide work (night shifts, audit waves, multi-branch dispatches) that produces changes across 10-15 branches simultaneously. Currently, the only way to PR these changes is raw git — which causes rebase divergence when Patrick merges and pulls.

The existing `drone @git pr` is correctly scoped: one branch, one PR. We don't want to change that. We want to ADD a privileged layer on top — a plugin in drone's `apps/plugins/` directory that only devpulse (and eventually Patrick) can access.

This is the "master key" — not a backdoor, but a front door with a lock that only certain passports can open.

## The Problem (with examples)

**S65 Night Shift:** 14 branches dispatched, 60+ files changed across the whole repo. `drone @git pr` failed because it only stages files under the caller's branch directory. Devpulse used raw git commands instead:
- `git checkout -b feat/s65-night-shift-cli-fixes`
- `git add <60 files manually>`
- `git commit`
- `git push`
- `gh pr create`
- `git checkout main`

This worked, but when Patrick merged the PR on GitHub (squash merge) and tried to pull, local main diverged from origin/main (different commit hashes for the same content). VS Code git integration crashed. Rebase headaches followed.

**The root cause:** Raw git commits on local main before creating the feature branch. The existing `drone @git pr` avoids this by creating the feature branch FIRST, committing only there, then returning to main clean. The plugin needs to follow the same pattern.

**Patrick's workflow:** Patrick also can't easily create PRs. Branch protection blocks direct pushes to main. He needs to create feature branches, commit, push, create PR — the same workflow `drone @git pr` automates. A `--author patrick` flag (future) would let him use the same plugin.

## Current State

### What exists
- `drone @git pr` — works perfectly for single-branch PRs (handlers/git/pr_handler.py)
- `drone @git status|sync|lock|unlock` — supporting commands
- `drone/apps/plugins/` — empty plugin directory with README and __init__.py, designed for exactly this
- Lockfile mechanism — atomic O_CREAT|O_EXCL, stale detection, PID tracking
- Caller detection — walks up from CWD to find .trinity/passport.json

### What's missing
- No way to stage files across multiple branches in one PR
- No identity-gated access (any branch can call any @git command)
- No merge capability (only Patrick can merge via GitHub UI)
- No way for Patrick to use the drone git workflow himself

## What Needs Building

### Phase 1: MVP — System-Wide PR Plugin
- [ ] `devpulse_ops/` plugin directory in `drone/apps/plugins/`
- [ ] `auth.py` — passport verification (only devpulse allowed, extensible to other identities later)
- [ ] `pr_plugin.py` — system-wide PR creation following the same safe pattern as pr_handler.py
- [ ] Route registration — `drone @git system-pr "description"` (or similar command name)
- [ ] Tests for auth, staging, and end-to-end PR creation

### Phase 2: Future Extensions (not building now, just noting)
- [ ] `merge_plugin.py` — merge PRs via `drone @git merge <PR#>`
- [ ] `--author patrick` support for Patrick to use the workflow
- [ ] Approval prompts for dangerous operations (configurable per-plugin)
- [ ] `rebase_plugin.py` — safe rebase with rollback
- [ ] `sync_plugin.py` — pull + rebase that handles divergence gracefully

## Design Decisions

| Decision | Options | Chosen | Notes |
|----------|---------|--------|-------|
| Command name | `system-pr` / `pr --system` / `devpulse-pr` | `system-pr` | Clear, distinct from regular `pr`. No ambiguity. |
| Where to put plugin | `plugins/devpulse_ops/` / `handlers/git/` | `plugins/devpulse_ops/` | Plugins dir exists for this. Keeps privileged ops separate from standard git handlers. |
| Auth mechanism | Passport check / env var / hardcoded name | Passport check | Read caller's .trinity/passport.json, verify branch_name is in allowed list. Extensible. |
| Staging scope | `git add -u` (all tracked) / explicit file list / `git add .` | `git add -u` | Stages all tracked modified files. Won't add untracked files (prevents accidental inclusion of secrets, test artifacts). Caller can review via `drone @git status` first. |
| Feature branch pattern | `citizen/devpulse` / `feat/system-*` / `system/*` | `system/devpulse-*` | Distinguishes system PRs from branch PRs. Pattern: `system/devpulse-{slugified-description}` |
| Commit on main? | Yes (current raw git) / No (branch first) | No — branch first | CRITICAL. This is what prevents the rebase divergence. Create feature branch, commit THERE, push, PR. Main stays clean. |

## Architecture

```
drone/apps/plugins/devpulse_ops/
├── __init__.py              # Plugin registration + handle_command()
├── auth.py                  # verify_caller() — passport-based identity gate
├── pr_plugin.py             # create_system_pr() — the actual PR logic
└── README.md                # Plugin documentation

Flow:
1. User runs: drone @git system-pr "S65 night shift fixes"
2. git_module.py sees "system-pr" command → routes to devpulse_ops plugin
3. auth.py checks caller passport → devpulse? proceed. Anyone else? denied.
4. pr_plugin.py:
   a. Acquire lock (same lockfile as regular pr)
   b. Verify on main branch, working tree has changes
   c. Create feature branch: system/devpulse-s65-night-shift-fixes
   d. Stage all tracked changes: git add -u
   e. Commit with Co-Authored-By
   f. Push feature branch
   g. Create PR via gh cli
   h. Return to main (git checkout main)
   i. Release lock
5. Print PR URL
```

### Key difference from regular `drone @git pr`:
- Regular: stages only files under caller's branch_dir (`git add src/aipass/<branch>/`)
- System: stages ALL tracked changes (`git add -u`)
- Everything else (lock, branch creation, push, PR, cleanup) is identical

### Auth model:
```python
# auth.py
ALLOWED_CALLERS = ["devpulse"]  # Extensible list

def verify_caller() -> str:
    """Returns caller name if authorized, raises PermissionError if not."""
    # Walk up from CWD to find .trinity/passport.json
    # Read branch_name from passport
    # Check against ALLOWED_CALLERS
    # Return name for use in commit message
```

Future: `ALLOWED_CALLERS` could include `"patrick"` with a special passport or env var check.

## Integration Points

### git_module.py changes needed
The existing `_handle_pr()` in git_module.py (line ~100) handles the "pr" command. Need to add routing for "system-pr" that imports and calls the plugin:

```python
elif command == "system-pr":
    from aipass.drone.apps.plugins.devpulse_ops import handle_command
    return handle_command("pr", args)
```

### Reusing existing infrastructure
- `lock_handler.py` — same lock mechanism, same lockfile
- `pr_handler.py` — reference implementation for the safe PR pattern (branch first, commit there, push, PR, return to main)
- The plugin is essentially pr_handler.py with the scoped staging replaced by `git add -u`

## Ideas

- **Dry-run mode:** `drone @git system-pr --dry-run "description"` shows what would be staged and the PR description without actually creating anything. Good for reviewing before committing.
- **Selective staging:** `drone @git system-pr --include "src/aipass/backup/ src/aipass/drone/" "description"` to stage only specific branch directories. Useful when not all changes should go in one PR.
- **PR template:** Auto-generate the PR body from git diff stats, listing which branches were modified and how many files/lines per branch.
- **Patrick mode:** `drone @git system-pr --author patrick "description"` changes the Co-Authored-By to Patrick's name. Requires a separate auth check (env var, config file, or interactive prompt).

## Phase 2 Plugins (dispatched to drone)

### merge_plugin.py — `drone @git merge <PR#>`
- Squash-merges a PR via gh cli, auto-syncs local main after
- Same auth gate as system-pr

### sync_plugin.py — `drone @git smart-sync`
- Detects diverged local/origin main, rebases cleanly
- Aborts and reports on conflict instead of leaving a mess

### fix_plugin.py — `drone @git fix`
- Emergency button: detects stuck rebase, detached HEAD, diverged state, dirty index
- Auto-resolves common broken states, reports what it did

## Phase 3: Git Snapshot Cache (Patrick's design)

**IMPORTANT: This is NOT a plugin.** Plugins are devpulse-only privileged extensions. The snapshot cache protects ALL git operations for ALL branches — it's a handler. Lives in `drone/apps/handlers/git/snapshot_handler.py` alongside pr_handler, lock_handler, sync_handler. Both `pr_handler.py` and the devpulse plugins call it before any destructive action.

### snapshot_handler.py — safety net for all git operations

**Concept:** Before every git action (PR, merge, rebase), the affected files get copied to a local snapshot folder. Rolling history of ~10 snapshots. When the 11th comes in, the oldest rolls off — but not deleted, rolls to the backup system (like plans and deleted branches do).

**Why:** We lost files in the past due to git operations gone wrong. The drone git workflow was built partly for this reason. But even with safe workflows, things can go sideways — a rebase drops a file, a merge conflict resolution loses changes, a force-push overwrites work. The snapshot cache means files are never truly lost.

**Design:**
```
drone/apps/plugins/devpulse_ops/
├── snapshot_plugin.py          # Snapshot before action, restore on demand
```

Each branch gets a `.git_snapshots/` directory (or a central one in the repo root):
```
.git_snapshots/
├── 001_2026-03-30T14:00_system-pr/    # Snapshot of files before PR #148
│   ├── manifest.json                   # What files, what action, timestamp
│   └── files/                          # Actual file copies
├── 002_2026-03-30T14:30_merge-148/    # Snapshot before merge
│   ├── manifest.json
│   └── files/
└── ...up to 010 (rolling)
```

**Integration:** Every other plugin calls `snapshot_plugin.take_snapshot(action, files)` before doing anything destructive. The snapshot happens silently — no user interaction needed.

**Rolloff:** When snapshot 11 arrives, snapshot 1 gets moved to the backup system (same pattern as deleted branches and closed plans — they don't delete, they archive).

**Restore:** `drone @git restore <snapshot_id>` or `drone @git restore latest` to recover files from a snapshot. Shows what would be restored before doing it.

**Patrick's words:** "Even if there were multiple errors where files got lost and the temp file got overridden, at least we have the previous versions. When you make a PR, the files that you've included get cached to a temporary folder. They don't delete, they just roll off somewhere. So there's always like — what happened to those files? They were there last week. We look at the backup system, we see the trail."

**Not building now** — this is Phase 3, after merge/sync/fix are proven. But the architecture should accommodate it from the start.

## Relationships
- **Related DPLANs:** DPLAN-0086 (Patrick's git workflow cheat sheet — this solves several of his pain points)
- **Related FPLANs:** None yet — drone will create one after reviewing this design
- **Owner branch:** @drone (builds it), @devpulse (primary consumer)
- **Seedgo standards:** `drone @seedgo audit aipass @drone` | `drone @seedgo standards_query aipass_standards`

## Status
- [x] Planning
- [ ] In Progress — dispatched to drone for review
- [ ] Ready for Execution
- [ ] Complete
- [ ] Abandoned

## Notes
- Session 65 (2026-03-30): Created. Patrick wants devpulse to have a proper way to create system-wide PRs instead of raw git workarounds. The raw git approach caused rebase divergence after S65 night shift PR #147 was merged. The plugins directory in drone already exists and is empty — perfect fit. Patrick also wants to eventually add himself as an authorized user so he can use the same workflow.
- Patrick explicitly said: don't change how the existing system works, just add another layer. The regular `drone @git pr` stays exactly as is. This is additive.
- Patrick wants this testable — create dummy test files, push them through the plugin, merge them, verify the pull works clean. We can delete test files afterward.
- Future note from Patrick: he wants `--author patrick` or similar so he can create PRs using drone's workflow instead of manual git. Not part of this build, but the auth.py should be designed to accommodate it.

## Listen (TTS-friendly summary)

This plan is about giving devpulse a proper way to create pull requests that span multiple branches at once. Right now, drone git PR only works for one branch at a time, which is correct for normal branch work. But when devpulse runs a night shift and dispatches fourteen branches, the changes end up spread across sixty plus files in fourteen different directories. The only way to PR those changes is using raw git commands, which causes rebase problems when Patrick merges and tries to pull.

The solution is a plugin in drones existing plugins directory. It is called devpulse ops. It has three files. An auth module that checks the callers passport to make sure only devpulse or other authorized users can access it. A PR plugin that creates system wide pull requests following the same safe pattern as the regular git PR handler, but staging all tracked changes instead of just one branch. And an init file that registers the plugin with drone.

The key design decision is that the plugin creates the feature branch first, then commits there, then pushes. It never commits on main. This is what prevents the rebase divergence that caused problems after session sixty five. The command will be drone at git system dash PR followed by a description.

Patrick also wants to eventually add himself as an authorized user so he can create PRs using the same workflow. That is not part of this build but the auth system is designed to accommodate it later.

---
*Created: 2026-03-30*
*Updated: 2026-03-30*
