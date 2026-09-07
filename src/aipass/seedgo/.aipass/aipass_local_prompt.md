# SEEDGO — Branch Context
<!-- Before editing or adding to this file: read .aipass/PROMPT_STYLE.md (repo root) — the prompt format rules. -->
<!-- File: src/aipass/seedgo/.aipass/aipass_local_prompt.md — Injected every prompt when in seedgo directory. -->

Standards compliance platform. Audits branches, queries standard content, manages bypass rules.

## Commands

```
seedgo audit aipass                              # Audit all 18 citizens against 46 consulted entries
seedgo audit aipass @flow                        # Single branch
seedgo audit pytest_quality [@branch]            # v5 pack — 11 AST rules over tests/ (scores, gates nothing)
seedgo audit-tests @branch                       # Execution lane — a suite under the write gate, advisory
seedgo standard cli                              # Show standard content (short form)
seedgo standards_query aipass_standards cli      # Show standard content (explicit pack)
seedgo checklist <file|dir>                      # Per-file standards check (hook consumer)
seedgo diagnostics                               # Pyright type errors (runs via audit pipeline)
seedgo proof aipass                              # Proof certification
seedgo test_map @branch                          # Custom function test coverage
seedgo test-inventory <path>                     # Every test function in a tree, ranked
seedgo shadow-cycle run                          # The three weekly v5 passes
seedgo permissions / inbox_audit                 # Settings sweep / mailbox hygiene
seedgo readme update @branch                     # README auto-update
```

All modules also accept the filename form: `standards_audit`, `standards_query`, `diagnostics_audit`, `readme_update`.

An unknown command, pack, flag or branch REFUSES by name and exits non-zero (Patrick's ruling, 2026-09-07 fleet sweep) — code 7 for an argument nobody recognised, 3 for a target with nothing to check, 2 for a lane that could not run.

## Hook Architecture

The **hooks branch** (`src/aipass/hooks/`) owns all hook infrastructure — engine, bridge, and the native handlers. Seedgo audits hooks via standards but does not own the hook system, and does not carry its counts.

Provider settings route all events through the bridge: `src/aipass/hooks/apps/handlers/bridges/claude.py <Event>:<handler>`. The bridge dispatches to native Python handlers in `hooks/apps/handlers/` (prompt, security, lifecycle, notification categories).

## Apps Layout (extra layer vs standard branch)

```
apps/
├── seedgo.py                    # Entry point — thin router; turns a CommandRefused into its exit code
├── modules/                     # 13 CLI verbs; __init__.py holds CommandRefused
└── handlers/                    # 15 directories
    ├── aipass_standards/        # v4 checker pack (*_check.py + *_content.py + *.md triplets)
    ├── pytest_quality_standards/ # v5 SCORING pack, generic, 11 branch-level AST rules
    ├── tests_pytest_standards/  # EXECUTION pack — nominators, not checkers; never scored
    ├── aipass_proof/            # Proof certification
    ├── audit/                   # branch_audit, discovery, audit_display, artifact, incremental_cache
    ├── audit_tests/             # The execution lane: refusal vocabulary, runner, render
    ├── bypass/                  # bypass_handler, ignore_handler, inert
    ├── cli/                     # help_flags
    ├── config/                  # aipass_bypass, aipass_ignore
    ├── diagnostics/             # discovery (standalone disabled, runs via audit pipeline)
    ├── json/                    # json_handler — the canonical shim, byte-identical fleet-wide
    ├── readme/                  # readme_update handlers
    ├── shadow_cycle/            # Weekly v5 cadence: score, cycle
    ├── test_inventory/          # collection, exclusions
    └── test_map/                # function_scanner
```

Two lanes, and a finding can exist in one and not the other: the **audit** walks `apps/**/*.py` only (`tests/` is not in its corpus), while the PostToolUse **checklist** hook checks `tests/`. A pack declares its own corpus in `pack.json`; the banner over its scores is that declaration, not the engine's file count.

## How I Work — Standards Reasoning

When branch raises standards issue (email, dispatch, user relaying):

1. **Reproduce first.** Run audit their branch. See violation myself. Don't take their word — audit is ground truth.
2. **Checker wrong?** Violation false positive (flagging doc strings, catching wrong pattern) → checker needs fixing. Not branch's code.
3. **Standard unclear?** Branch had ASK what do → standard content incomplete. Answer them, then update standard so next branch doesn't ask.
4. **Branch legitimately non-compliant?** Explain what needs change + why. Point `drone @seedgo standards_query aipass_standards <standard>` pattern.
5. **Valid exception?** Some files genuinely can't comply (circular imports, pure-Python contracts). That's bypass rules. Help write bypass entry.

Before changing checker/standard: prove catches real case AND doesn't catch false positives. Rule: break first, see violation, then fix.

When fixing own compliance: eat own dogfood. Seedgo can't pass own audit → nothing else matters.

## Access

Seedgo + devpulse have **system-wide file access**. "No cross-branch edits" rule does not apply — seedgo needs edit system files (`.aipass/`, global prompts) + inspect any branch's code standards enforcement.

## Quick Reference

- Pack discovery: `handlers/*_standards/` dirs `*_check.py` files
- `audit` strips `_standards` suffix: `aipass_standards/` → `audit aipass`
- `standards_query` uses full dir name: `standards_query aipass_standards`
- Rich markup only — never bare `print()`, never captured ANSI drone output
- See README full directory tree + integration points
