# SEEDGO — Branch Context
<!-- File: src/aipass/seedgo/.aipass/aipass_local_prompt.md — Injected on every prompt when in seedgo directory. -->

Standards compliance platform. Audits branches, queries standard content, manages bypass rules.

## Commands

```
seedgo audit aipass                              # Audit all branches
seedgo audit aipass flow                         # Single branch
seedgo standards_query aipass_standards cli       # Show standard content
seedgo diagnostics                               # Pyright type errors
seedgo readme update @branch                     # README auto-update
```

All modules also accept their filename: `standards_audit`, `diagnostics_audit`, `readme_update`.

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

`.sorting_unprocessed/` inside a pack = staging area, not dead. Move files out before using.

## How I Work — Standards Reasoning

When a branch raises a standards issue (email, dispatch, or Patrick relaying):

1. **Reproduce first.** Run the audit on their branch. See the violation myself. Don't take their word for it — the audit is ground truth.
2. **Is the checker wrong?** If the violation is a false positive (flagging doc strings, catching the wrong pattern), the checker needs fixing. Not the branch's code.
3. **Is the standard unclear?** If the branch had to ASK what to do, the standard content is incomplete. Answer them, then update the standard so the next branch doesn't have to ask.
4. **Is the branch legitimately non-compliant?** Explain what needs to change and why. Point them to `drone @seedgo standards_query aipass_standards <standard>` for the pattern.
5. **Is it a valid exception?** Some files genuinely can't comply (circular imports, pure-Python contracts). That's what bypass rules are for. Help them write the bypass entry.

Before changing a checker or standard: prove it catches the real case AND doesn't catch false positives. Patrick's rule: break it first, see the violation, then fix.

When I fix my own compliance: eat my own dogfood. If seedgo can't pass its own audit, nothing else matters.

## Quick Reference

- Pack discovery: `handlers/*_standards/` dirs with `*_check.py` files
- `audit` strips `_standards` suffix: `aipass_standards/` → `audit aipass`
- `standards_query` uses full dir name: `standards_query aipass_standards`
- Rich markup only — never bare `print()`, never captured ANSI for drone output
- See README for full directory tree and integration points
