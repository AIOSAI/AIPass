# SEEDGO — Branch Context
<!-- Before editing or adding to this file: read .aipass/PROMPT_STYLE.md (repo root) — the prompt format rules. -->
<!-- File: src/aipass/seedgo/.aipass/aipass_local_prompt.md — Injected every prompt when in seedgo directory. -->

Standards compliance platform. Audits branches, queries standard content, manages bypass rules.

## Commands

```
seedgo audit aipass                              # Audit all 11 agents (33 audit lines)
seedgo audit aipass flow                         # Single branch
seedgo standard cli                              # Show standard content (short form)
seedgo standards_query aipass_standards cli      # Show standard content (explicit pack)
seedgo checklist <file>                          # Per-file standards check (hook consumer)
seedgo diagnostics                               # Pyright type errors (runs via audit pipeline)
seedgo proof aipass                              # Proof certification
seedgo test_map @branch                          # Custom function test coverage
seedgo readme update @branch                     # README auto-update
```

All modules also accept filename: `standards_audit`, `diagnostics_audit`, `readme_update`. Note: `proof`, `proof_query`, `test_map` currently not --help output (known TODO).

## Hook Architecture

The **hooks branch** (`src/aipass/hooks/`) owns all hook infrastructure — engine, bridge, and 14 native handlers. Seedgo audits hooks via standards but does not own the hook system.

Provider settings route all events through the bridge: `src/aipass/hooks/apps/handlers/bridges/claude.py <Event>:<handler>`. The bridge dispatches to native Python handlers in `hooks/apps/handlers/` (prompt, security, lifecycle, notification categories).

## Apps Layout (extra layer vs standard branch)

```
apps/
├── seedgo.py              # Entry point — thin router
├── modules/               # standards_audit, standards_query, diagnostics_audit, readme_update
└── handlers/
    ├── aipass_standards/   # Checker pack (*_check.py + *_content.py pairs)
    ├── audit/              # branch_audit, discovery, audit_display
    ├── bypass/             # bypass_handler, ignore_handler
    ├── config/             # aipass_bypass, aipass_ignore
    ├── diagnostics/        # discovery (standalone disabled, runs via audit pipeline)
    ├── file/               # file_handler
    └── json/               # json_handler
```

`.sorting_unprocessed/` inside pack = staging area, not dead. Move files out before using.

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
