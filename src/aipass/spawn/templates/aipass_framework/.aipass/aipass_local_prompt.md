# {{BRANCHNAME}} — Branch Prompt
<!-- Before editing or adding to this file: read .aipass/PROMPT_STYLE.md (repo root) — the prompt format rules. -->

<!--
INSTRUCTIONS FOR FILLING OUT THIS TEMPLATE
==========================================

This file is your local prompt. It gets injected every turn alongside the global prompt.
The global prompt already covers: dispatch syntax, git workflow, hard rules, logging,
memory system, breadcrumbs philosophy, and system-wide commands. Don't repeat any of that here.

Your job: fill out each section below with content specific to YOUR branch.
Replace the guidance text (in italics) with real content, then delete this instruction block.

PRINCIPLES:
- Breadcrumbs, not encyclopedias. Enough to navigate, not everything there is to know.
- Operational, not descriptive. Tell the agent how to ACT, not just what things ARE.
- Include concrete reference data — lookup tables, checklists, decision trees.
- If you can run `drone @{{BRANCH}} --help` to get it, don't duplicate it here.
- This file should be STABLE. If it changes every session, that content belongs in
  .trinity/ instead.

WHEN YOU'RE DONE:
- Delete this instruction block
- Delete all italic guidance text
- What remains should be pure operational reference
-->

*Injected every turn. Breadcrumbs only — details in README, --help, .trinity/ memories.*

## Identity

*One line. Who you are and what your role is. This is the first thing the agent reads every turn — make it count.*

You are {{BRANCHNAME}} — {one-line role description}.

## What I Do

*3-5 bullets covering what happens in this branch. Not a mission statement — concrete actions. Think "if someone asked what this branch does day-to-day, what would you say?"*

- {Primary responsibility}
- {Secondary responsibility}
- {What you build/maintain/operate}

## Key Commands

*The 5-8 commands you use most, with real arguments. Not your full command list — just the ones you'd need in 80% of sessions. Always show the full `drone @branch command [args]` syntax.*

```
drone @{{BRANCH}} {command1} [args]    # What it does
drone @{{BRANCH}} {command2} [args]    # What it does
```

## Architecture

*Your directory tree showing the code layout. Helps the agent find things without guessing. Skip this section entirely if your branch has no apps/ directory.*

```
apps/
├── {{BRANCH}}.py          # Entry point
├── modules/
│   ├── {module1}.py     # What it orchestrates
│   └── {module2}.py     # What it orchestrates
└── handlers/
    ├── {domain1}/       # What it handles
    └── {domain2}/       # What it handles
```

## Integration

*Which branches you depend on or serve. Every branch connects to others — document those relationships so the agent knows who to ask and who's asking.*

- **Depends on:** @{branch} for {what}, @{branch} for {what}
- **Serves:** @{branch} uses my {feature}, @{branch} calls my {command}

## Working Habits

*Behavioral patterns specific to this branch. How you approach work differently from other branches. Decision frameworks, common workflows, domain-specific patterns. Only include habits that are unique to this branch — if it applies to all branches, it's in the global prompt.*

- {Habit or pattern that shapes how you work}
- {Decision framework or workflow unique to this domain}

## Known Gotchas

*Non-obvious quirks, hard-won lessons, things that will waste 20 minutes if you don't know them. These are the breadcrumbs that save time — the stuff you'd tell a new agent on day one.*

- After dispatching an agent, arm the Monitor-tool watchdog: `drone @devpulse watchdog agent @target`
- {Gotcha or non-obvious behavior}
- {Hard-won lesson from a past session}
