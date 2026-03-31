# {plan_number} - {subject}

**Created**: {today}
**Branch**: {location}
**Status**: Active
**Type**: Standard Plan

---

## What Are Flow Plans?

Flow Plans (FPLANs) are for **building** - autonomous construction of systems, features, modules.

**FPLANs are disposable.** They exist for exactly one task. When the task is complete, close this plan immediately — do not leave it open. Open FPLANs mean unfinished work. If the work is done, the plan is done: `drone @flow close {plan_number}`

**This is NOT for:**
- Research or exploration (use agents directly)
- Quick fixes (just do it)
- Discussion or planning (that happens before creating the FPLAN)

**This IS for:**
- Building features or modules
- Single focused construction tasks
- Sub-plans within a master plan

---

## When to Use This vs Master Plan

| This (Default) | Master Plan |
|----------------|-------------|
| Single focused task | 3+ phases, complex build |
| Self-contained | Roadmap + multiple sub-plans |
| Quick build | Multi-session project |
| One phase of a master | Entire branch/system build |

**Need a master plan?** `drone @flow create "subject" master`

---

## Branch Directory Structure

Use dedicated directories - don't scatter files:

| Directory | Purpose |
|-----------|---------|
| `apps/` | Code (modules/, handlers/) |
| `tests/` | All test files |
| `tools/` | Utility scripts |
| `artifacts/` | Agent outputs |
| `docs/` | Documentation |

---

## Critical: Branch Manager Role

**You are the orchestrator, not the builder.**

Your 200k context is precious. Burning it on file reads and code writing risks compaction during autonomous work. Agents have clean context - use them for all building.

| You Do (Orchestrator) | Agents Do (Builders) |
|-----------------------|----------------------|
| Create plans | Write code |
| Give instructions | Run tests |
| Review output | Read/modify files |
| Course correct | Research/exploration |
| Update memories | Heavy lifting |
| Send status emails | Single-task execution |

**Pattern:** Instruct agent -> Wait for completion -> Review output -> Next step

---

## Seek Branch Expertise

Don't figure everything out alone. Other branches are domain experts - ask them first.

**Before building anything that touches another branch's domain:**
```bash
ai_mail email @branch "Question: [topic]" "I'm working on X and need guidance on Y. What's the best approach?"
```

**Common examples:**
- Building something with email? Ask @ai_mail how delivery works
- Need routing or @ resolution? Ask @drone
- Unsure about standards? Ask @seedgo for reference code
- Need persistent storage or search? Ask @memory
- Event-driven behavior? Ask @trigger about their event system
- Dashboard integration? Ask @devpulse about update_section()

They have deep memory on their systems. A 1-email question saves you hours of guessing.

---

## Notepad

Keep `notepad.md` in your branch directory as a shared scratchpad during the build. Use it for:
- **Status updates** - Quick progress lines so the user can glance without asking
- **Questions for the user** - Non-urgent questions that can wait for the next check-in
- **Notes to self** - Decisions made, things to revisit, gotchas discovered

Update it as you work - lightweight, not formal. The user checks it when they want to, skips it when busy.

---

## Command Reference

When unsure about syntax, use `--help`:

```bash
# Flow - Plan management
drone @flow create . "subject"         # Create plan (. = current dir)
drone @flow close {prefix}-XXXX           # Close plan
drone @flow list open                  # List active plans
drone @flow --help                     # Full help

# Seedgo - Quality gates
drone @seedgo checklist <file>           # 10-point check on file
drone @seedgo audit @branch              # Full branch audit
drone @seedgo --help                     # Full help

# AI_Mail - Status updates
drone @ai_mail email @devpulse "Subject" "Message"
drone @ai_mail --help                  # Full help

# Discovery
drone systems                          # All available modules
drone list @branch                     # Commands for branch
```

---

## Planning Phase

### Goal
[What do you want to achieve? Specific end state.]

### Approach
[How will agents tackle this? What instructions will they need?]

### Reference Documents
[List any planning docs, specs, or examples to reference]

---

## Agent Preparation (Before Deploying)

Agents can't work blind. They need context before they build.

**Your Prep Work (as orchestrator):**
1. [ ] Know where agent will work (branch path, key directories)
2. [ ] Identify files agent needs to reference or modify
3. [ ] Gather any specs, planning docs, or examples to include
4. [ ] Prepare complete instructions (agents are stateless)

**Agent's First Task (context building):**
- Agent should explore/read relevant files before writing code
- "First, read X and Y to understand the current structure"
- "Look at Z for the pattern to follow"
- Context-first, build-second

**What agents don't have:**
- No prior conversation history
- No memory files loaded automatically
- No knowledge of other branches
- Only what you put in their instructions

**Your instructions determine success - be thorough and specific.**

---

## Agent Instructions Template
```
You are working at [branch_path].

**Task:** [Specific single task]

**Context:**
- [What they need to know]
- Reference: [planning docs, existing code to study]
- First, read the relevant files to understand current structure

**Deliverables:**
- [Specific file or output expected]
- Tests -> tests/
- Reports/logs -> artifacts/reports/ or artifacts/logs/

**Constraints:**
- Follow Seedgo standards (3-layer architecture)
- Do not modify files outside your task scope
- Cross-branch: never modify other branches' files unless explicitly authorized by the user
- Two-attempt rule: if something fails twice, note the issue and move on
- Do not go down rabbit holes debugging

**When complete:**
- Verify code runs without syntax errors
- List files created/modified
- Note any issues encountered (with what was attempted)
```

---

## Execution Log

### {today}
- [ ] Created {plan_number}
- [ ] Agent deployed for: [task]
- [ ] Agent completed: [outcome]
- [ ] Seedgo checklist passed: [file]
- [ ] Memories updated

**Log Pattern:** Task -> Agent -> Outcome -> Quality check -> Next

**If production stops (critical blocker):**
```bash
drone @ai_mail email @devpulse "Production stopped: {plan_number}" "Issue: [description]. Attempted: [what was tried]. Awaiting guidance."
```

---

## Notes

[Working notes, issues encountered, decisions made]

---

## Completion Checklist

### Before Closing

- [ ] All goals achieved
- [ ] Agent output reviewed and verified
- [ ] Seedgo checklist on new code: `drone @seedgo checklist <file>`
- [ ] Branch memories updated:
  - [ ] `BRANCH.local.json` - session/work log
  - [ ] `BRANCH.observations.json` - patterns learned (if any)
- [ ] README.md updated (if build changed status/capabilities)
- [ ] Status email sent to @devpulse:
  ```bash
  drone @ai_mail email @devpulse "{plan_number} Complete" "Summary of what was done, any issues, outcomes"
  ```

**Completion Order:** Memories -> README -> Email (README before email - don't report complete with stale docs)

### Definition of Done
[What specifically defines complete for this plan?]

---

## Listen (TTS-friendly summary)

Write a plain English summary of this plan here. No markdown, no symbols, no tables, no code blocks, no asterisks, no bullet points. Just natural sentences that can be read aloud by a text to speech tool. Update this section whenever the plan changes significantly.

---

## Close This Plan

**This is your final step.** When all goals are achieved and the completion checklist above is done, close this plan. Do not leave it open. An open plan means unfinished work.

```bash
drone @flow close {plan_number}
```

If you are an agent finishing the last task in this plan, close it yourself before your session ends. If you are the orchestrator reviewing agent output, close it once verified. Someone must close it — plans do not close themselves.
