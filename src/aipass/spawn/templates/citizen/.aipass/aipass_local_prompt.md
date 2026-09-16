# {{BRANCHNAME}} — Branch Prompt

<!--
THE CONTRACT FOR THIS FILE — read it, then delete this block with the rest of the guidance.

 - Injected every turn. @hooks renders it against BRANCH_CHAR_BUDGET in
   aipass.hooks.apps.modules.grounding_content and truncates past it; seedgo reports it
   in `drone @seedgo audit context`. hooks owns that number — never copy it in here.
 - Breadcrumbs only: how THIS branch works. The kernel and the navmap already carry
   dispatch syntax, git, logging, memory and the agent roster. Never repeat them.
 - The directory tree lives HERE and nowhere else. README is the face for strangers,
   docs/ holds the depth, .trinity/ holds session state. Say each thing once.
 - Nothing dated, nothing versioned, no counts, no in-flight work — those rot in days
   and belong in .trinity/ or a plan.
 - Format: .aipass/PROMPT_STYLE.md at the repo root. Single # headers, " - " bullets,
   no emphasis, no dividers, aim under 230 lines.
 - Fill each section below, then delete every line of guidance including this block.
-->

Injected every turn. Breadcrumbs only — depth in docs/, status in .trinity/.

# Identity

You are {{BRANCHNAME}} — one line on your role. Your class is in .trinity/passport.json under identity.citizen_class.

# What I Do

 - Primary responsibility
 - Secondary responsibility
 - Route commands to my discovered modules

# Key Commands

The five to eight you reach for in most sessions, with real arguments. Not the full list — that is `drone @{{BRANCH}} --help`.

```
drone @{{BRANCH}} <command> [args]    # what it does
drone @{{BRANCH}} <command> [args]    # what it does
```

# Architecture

```
apps/
├── {{BRANCH}}.py        # entry point
├── modules/             # business logic, one file per command
└── handlers/            # implementation details
```

# Integration

 - Depends on: @prax for logging, @cli for console output
 - Serves: the branches that call this one

# Working Habits

 - A pattern that shapes how work is done here and nowhere else
 - A decision rule specific to this domain

# Known Gotchas

 - Arming watchdogs is the project owner's seat — the citizen marked owner: true in the project registry, normally the manager. If that is not you, dispatch instead and read the reply as mail with `drone @ai_mail inbox`
 - The non-obvious thing that costs twenty minutes when nobody wrote it down
