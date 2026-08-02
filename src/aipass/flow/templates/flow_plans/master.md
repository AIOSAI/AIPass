# {plan_number} - {subject} (MASTER PLAN)

**Created**: {today}
**Branch**: {location}
**Status**: Active
**Type**: Master Plan (Multi-Phase)

---

## What Are Flow Plans?

Flow Plans (FPLANs) are **BUILDING** - autonomous construction: systems, features, modules. Structured way to execute work without constant human oversight.

**FPLANs are disposable.** Exist exactly one build. When ALL phases complete, close this plan immediately -- do not leave open. Open FPLANs mean unfinished work. Work done = plan done: `drone @flow close {plan_number}`

**This is NOT for:**
- Research or exploration (use agents directly)
- Quick fixes (just do it)
- Discussion or planning (happens before creating FPLAN)

**This IS for:**
- Building ! branches/modules
- Implementing features
- Multi-phase construction projects
- Autonomous execution

---

## Master Plan vs Default Plan

| | Master Plan | Default Plan |
|---|-------------|--------------|
| **Use when** | 3+ phases, complex build | Single focused task |
| **Structure** | Roadmap + sub-plans | Self-contained |
| **Phases** | Multiple, sequential | One |
| **Sub-plans** | Yes, one per phase | No |
| **Typical use** | Build entire branch | One phase of master |

**Pattern:**
```
Master Plan (roadmap)
+-- Sub-plan Phase 1 (default template)
+-- Sub-plan Phase 2 (default template)
+-- Sub-plan Phase 3 (default template)
+-- Sub-plan Phase 4 (default template)
```

**How to start:**
1. User provides planning doc DPLAN or instructions (coordinate @devpulse)
2. Branch manager reads + understands scope
3. Branch manager creates master plan: `drone @flow create . "Build X" master`
4. Branch manager fills phases, then executes autonomously
5. Devpulse may provide a complete plan to you. Always confirm the plan is sound and accurate.

---

## Critical: Branch Manager Role

**You are ORCHESTRATOR, not builder.**

Your context is finite -- spend it on orchestration, not building. Agents have clean context - use them for ALL building. Auto-compact is survivable by design (PreCompact injects recovery state), but context burned on solo building is context lost to coordination.

| You Do (Orchestrator) | Agents Do (Builders) |
|-----------------------|----------------------|
| Create plans + sub-plans | Write code |
| Define phases | Run tests |
| Give agent instructions | Read/modify files |
| Review agent output | Research/exploration |
| Course correct | Heavy lifting |
| Update memories | Single-task execution |
| Send status emails | Build deliverables |
| Track phase progress | Quality checks on code |

**Master Plan Pattern:** Define * phases -> Create sub-plan Phase 1 -> Deploy agent -> Review -> Close sub-plan -> Email update -> Next phase

---

## Seek Branch Expertise

Don't figure everything out alone. Other branches are domain experts - ask them first.

**Before building anything touching another branch's domain:**
```bash
drone @ai_mail email @branch "Question: [topic]" "I'm working on X and need guidance on Y. What's the best approach?"
```

**Common examples:**
- Building something email? Ask @ai_mail how delivery works
- Need routing or @ resolution? Ask @drone
- Unsure about standards? Ask @seedgo reference code
- Need persistent storage or search? Ask @memory
- Event-driven behavior? Ask @trigger about their event system
- Dashboard integration? Ask @devpulse about update_section()

They have deep memory on their systems. 1-email question saves you hours guessing. Master plans spanning multiple domains: identify which branches to consult during phase definitions.

---

## Notepad

Keep `notepad.md` in branch directory as shared scratchpad during build. Use for:
- **Status updates** - Quick progress lines so user can glance without asking
- **Questions for user** - Non-urgent questions that can wait next check-in
- **Notes to self** - Decisions made, things to revisit, gotchas discovered

Update as you work - lightweight, not formal. User checks when they want, skips when busy. Low friction both ways.

```bash
# Create at plan start
echo "# Notepad - {plan_number}" > notepad.md
```

---

## Command Reference

When unsure about syntax, use `--help`:

```bash
# Flow - Plan management
drone @flow create . "Phase X: subject"      # Create sub-plan (. = current dir)
drone @flow create . "subject" master        # Create master plan
drone @flow close {prefix}-XXXX           # Close plan
drone @flow list open                  # List active plans
drone @flow --help                     # Full help

# Seedgo - Quality gates
drone @seedgo checklist <file>           # 10-point check on file
drone @seedgo audit aipass @branch       # Full branch audit (before master close)
drone @seedgo --help                     # Full help

# AI_Mail - Status updates
drone @ai_mail email @devpulse "Subject" "Message"
drone @ai_mail inbox                   # Check your inbox
drone @ai_mail --help                  # Full help

# Discovery
drone systems                          # All available modules
drone list @branch                     # Commands for branch
```

---

## What is a Master Plan?

Master Plans are **complex multi-phase projects**. Define * phases upfront, then create focused sub-plans each phase.

**When to use:**
- 3+ distinct sequential phases
- Work spanning multiple sessions
- Need clear phase completion milestones
- Complex builds requiring sustained focus

**Pattern:** Master Plan = Roadmap | Sub-Plans = Focused Execution

---

## Project Overview

### Goal
[What is end state when ALL phases complete?]

### Reference Documentation
[List planning docs, specs, existing code to reference]

### Success Criteria
[What defines DONE entire project?]

---

## Branch Directory Structure

Every branch has dedicated directories. Use them correctly:

```
branch/
+-- apps/           # Code (modules/, handlers/)
+-- tests/          # All test files go here
+-- tools/          # Utility scripts, helpers
+-- artifacts/      # Agent outputs (reports, logs)
+-- docs/           # Documentation
+-- logs/           # Execution logs
```

**Rules:**
- Tests -> `tests/` (not root, not random locations)
- Tools/scripts -> `tools/`
- Agent artifacts -> `artifacts/`
- Create subdirs if needed: `mkdir -p artifacts/reports artifacts/logs`
- **Never delete** - devpulse manages cleanup
- Future: artifacts auto-roll to @memory

---

## Phase Definitions

Define ALL phases before starting work:

### Phase 1: [Name]
**Goal:** [What this phase accomplishes]
**Agent Task:** [What agent will build]
**Deliverables:** [Files/outputs expected]

### Phase 2: [Name]
**Goal:** [What this phase accomplishes]
**Agent Task:** [What agent will build]
**Deliverables:** [Files/outputs expected]

### Phase 3: [Name]
**Goal:** [What this phase accomplishes]
**Agent Task:** [What agent will build]
**Deliverables:** [Files/outputs expected]

### Phase 4: [Name]
**Goal:** [What this phase accomplishes]
**Agent Task:** [What agent will build]
**Deliverables:** [Files/outputs expected]

[Add more phases as needed]

---

## Execution Philosophy

### Autonomous Power-Through

Master plans are **autonomous execution**. Don't halt production every phase waiting for review.

**The Pattern:**
- Power through * phases
- Accumulate issues as you go
- Deal with issues at end
- User reviews final result, not every step

**Why this works:**
- Context is precious - don't burn it chasing bugs
- Complete picture reveals which issues actually matter
- Many "bugs" resolve themselves when later phases complete
- Coordination time is for decisions, not babysitting

### The 2-Attempt Rule

When agent encounters issue:

```
Attempt 1 -> Failed?
    |
Attempt 2 -> Failed?
    |
STOP. Mark as issue. Move on.
```

**Do NOT:**
- Try 5 different approaches
- Go down rabbit holes
- Burn context debugging
- Stop production every error

**DO:**
- Note issue clearly
- Note what was tried
- Move to next task
- Let branch manager decide priority

### Critical vs Non-Critical Issues

When you see issue, decide:

| Question | If YES -> | If NO -> |
|----------|----------|---------|
| Does this block ALL future phases? | STOP. Investigate. | Continue. |
| Can system work around this? | Continue. | STOP. Investigate. |
| Is this syntax/import error? | Quick fix, continue. | - |
| Is this logic/design problem? | Note it. Continue. | - |

**Critical (stop production):**
- Core module won't import at all
- Database/file system inaccessible
- Fundamental architecture wrong

**Non-critical (note + continue):**
- One command throws error but others work
- Registry not updating properly
- Edge case not handled
- Test failing but code runs

**Pattern:** Note issue -> Continue building -> Fix at end with complete picture

### False Positives Awareness

Seedgo audits are helpful but not infallible.

**When Seedgo flags something:**
1. Check if code actually correct from your understanding
2. If confident it's right -> mark false positive, move on
3. If unsure -> note it, continue, review later

**Don't stop production for:**
- Style preferences (comments, spacing)
- Patterns that differ from Seedgo's but still work
- Checks that don't apply to your context

### Forward Momentum Summary
- **Don't stop to fix bugs during phases** - Note them, keep moving
- **Get complete picture first** - All phases done, THEN systematic fixes
- **Prevents:** Bug-fixing rabbit holes, premature optimization, scope creep
- **Review happens at END** - not every phase

### Production Stop Protocol

If something causes production STOP (critical blocker), **immediately email @devpulse**:

```bash
drone @ai_mail email @devpulse "PRODUCTION STOPPED: {plan_number}" "Phase X halted. Issue: [description]. Attempted: [what was tried]. Awaiting guidance."
```

**Never leave branch stopped without reporting.** Orchestration hub needs visibility into * work.

### Monitoring Resources

Quick status checks + debugging, these resources available:

| Resource | Location | Purpose |
|----------|----------|---------|
| Branch logs | `logs/` directory | Local execution logs |
| JSON tree | `<branch>_json/` | Module firing status |
| Prax monitor | `drone @prax monitor` | Real-time system events |
| Seedgo audit | `drone @seedgo audit @branch` | Code quality check |

Use when you need to confirm status or investigate issues.

### Agent Deployment Per Phase
Each phase = focused agent deployment:
1. Create sub-plan: `drone @flow create . "Phase X: [name]"`
2. Write agent instructions in sub-plan
3. Deploy agent with single-task focus
4. Review agent output (don't rebuild yourself)
5. Seedgo checklist on ! code
6. Close sub-plan
7. Update memories
8. Email status > @devpulse
9. Next phase

### Agent Preparation (Before Deploying)

Agents can't work blind. They need context before they build.

**Your Prep Work (as orchestrator):**
1. [ ] Know where agent will work (branch path, key directories)
2. [ ] Identify files agent needs to reference or modify
3. [ ] Gather any specs, planning docs, or examples to include
4. [ ] Prepare COMPLETE instructions (agents are stateless)

**Agent's First Task (context building):**
- Agent should explore/read relevant files BEFORE writing code
- "First, read X and Y to understand current structure"
- "Look at Z for pattern to follow"
- Context-first, build-second

**What Agents DON'T Have:**
- No prior conversation history
- No memory files loaded automatically
- No knowledge other branches
- Only what you put in their instructions

**Your instructions determine success - be thorough + specific.**

### Agent Instructions Template
```
You are working at [BRANCH_PATH].

TASK: [Specific single task for this phase]

CONTEXT:
- [What they need to know]
- Reference: [planning docs, existing code to study]
- First, READ relevant files to understand current structure

DELIVERABLES:
- [Specific file or output expected]
- Tests -> tests/
- Reports/logs -> artifacts/reports/ or artifacts/logs/

CONSTRAINTS:
- Follow Seedgo standards (3-layer architecture: apps/modules/handlers)
- Do NOT modify files outside your task scope
- CROSS-BRANCH: Never modify other branches' files unless explicitly authorized by user in planning doc
- 2-ATTEMPT RULE: If something fails twice, note issue + move on
- Do NOT go down rabbit holes debugging

WHEN COMPLETE:
- Verify code runs without syntax errors
- List files created/modified
- Note any issues encountered (what was attempted)
```

---

## Phase Tracking

### Phase 1: [Name]
- [ ] Sub-plan created: {prefix}-____
- [ ] Agent deployed
- [ ] Agent completed
- [ ] Output reviewed
- [ ] Seedgo checklist passed
- [ ] Sub-plan closed
- [ ] Memories updated
- [ ] Email > @devpulse
- **Status:** Pending / In Progress / Complete
- **Notes:** [Outcomes, issues, adjustments]

### Phase 2: [Name]
- [ ] Sub-plan created: {prefix}-____
- [ ] Agent deployed
- [ ] Agent completed
- [ ] Output reviewed
- [ ] Seedgo checklist passed
- [ ] Sub-plan closed
- [ ] Memories updated
- [ ] Email > @devpulse
- **Status:** Pending / In Progress / Complete
- **Notes:** [Outcomes, issues, adjustments]

### Phase 3: [Name]
- [ ] Sub-plan created: {prefix}-____
- [ ] Agent deployed
- [ ] Agent completed
- [ ] Output reviewed
- [ ] Seedgo checklist passed
- [ ] Sub-plan closed
- [ ] Memories updated
- [ ] Email > @devpulse
- **Status:** Pending / In Progress / Complete
- **Notes:** [Outcomes, issues, adjustments]

### Phase 4: [Name]
- [ ] Sub-plan created: {prefix}-____
- [ ] Agent deployed
- [ ] Agent completed
- [ ] Output reviewed
- [ ] Seedgo checklist passed
- [ ] Sub-plan closed
- [ ] Memories updated
- [ ] Email > @devpulse
- **Status:** Pending / In Progress / Complete
- **Notes:** [Outcomes, issues, adjustments]

[Copy template additional phases]

---

## Issues Log

Track issues here as encountered. Don't fix during build - log + continue.

| Phase | Issue | Severity | Attempted | Status |
|-------|-------|----------|-----------|--------|
| 1 | [description] | Low/Med/High | [what was tried] | Open/Resolved |
| 2 | [description] | Low/Med/High | [what was tried] | Open/Resolved |

**Severity Guide:**
- **High:** Blocks future phases, must fix before continuing
- **Med:** Affects functionality but can work around
- **Low:** Cosmetic, edge case, or false positive

**End Build:** Review this log. Tackle High->Med->Low. Some Low issues may not need fixing.

---

## Master Plan Notes

**Cross-Phase Patterns:**
[Patterns discovered spanning multiple phases]

**Blockers + Resolutions:**
[Significant blockers + how resolved]

**Adjustments:**
[Changes to planned phases - scope changes, phases added/merged]

---

## Final Completion Checklist

### Before Closing Master Plan

- [ ] All phases complete
- [ ] All sub-plans closed
- [ ] Issues Log reviewed - High/Med issues addressed
- [ ] Full branch audit: `drone @seedgo audit aipass @branch`
- [ ] Branch memories updated:
  - [ ] `BRANCH.local.json` - full session log
  - [ ] `BRANCH.observations.json` - patterns learned
- [ ] README.md updated (status, architecture, API - if build changed capabilities)
- [ ] Artifacts reviewed (devpulse manages cleanup)
- [ ] Final email > @devpulse:
  ```bash
  drone @ai_mail email @devpulse "{plan_number} MASTER COMPLETE" "Full build summary: phases completed, deliverables, remaining issues (if any)"
  ```

**Completion Order:** Memories -> README -> Email (README before email - don't report complete stale docs)

**Note:** Devpulse will perform its own Seedgo audit for visibility into work.

### Definition of Done
[What specifically defines project complete?]

---

## Listen (TTS-friendly summary)

Write a plain English summary of this plan here. No markdown, no symbols, no tables, no code blocks, no asterisks, no bullet points. Just natural sentences that can be read aloud by a text to speech tool. Update this section whenever the plan changes significantly.

---

## Close Command

When ALL phases complete + checklist done:
```bash
drone @flow close {plan_number}
```
