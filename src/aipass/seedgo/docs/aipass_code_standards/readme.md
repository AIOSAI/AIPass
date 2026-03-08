# README Standards
**Status:** Active v1.0
**Date:** 2026-02-21

---

## What This Covers

Standards for branch README.md files. Every branch must have a README that stays accurate without manual effort. Auto-generated sections update via Seedgo audit integration. Manual sections remain human-written.

---

## README Required

Every branch root must have a `README.md` file. Without one, the branch has no human-readable documentation of its current state.

---

## Canonical Section Order

READMEs should follow this structure:

1. **Identity Header** — Name, purpose, location, profile
2. **Overview** — What I Do / What I Don't Do / How I Work
3. **Architecture** — Pattern, structure, orchestrator
4. **Directory Structure** — Auto-generated tree
5. **Commands** — Auto-generated from `--help`
6. **Modules** — Auto-generated from `apps/modules/`
7. **Key Capabilities** — Manual
8. **Integration Points** — Manual
9. **Memory System** — Files and persistence
10. **Last Updated** — Auto-generated timestamp

Not every branch needs every section. Omit sections that don't apply (e.g., a branch with no CLI commands skips Commands).

---

## Auto-Generated Markers

Use HTML comment markers for auto-populated sections:

```markdown
<!-- AUTO:TREE -->
```
apps/
├── branch.py
├── modules/
│   └── operations.py
└── handlers/
    └── ops.py
```
<!-- /AUTO:TREE -->
```

**Supported markers:**

| Marker | Content | Source |
|--------|---------|--------|
| `AUTO:TREE` | Directory structure | Filesystem scan |
| `AUTO:MODULES` | Module list with descriptions | `apps/modules/*.py` docstrings |
| `AUTO:COMMANDS` | CLI commands and usage | `--help` output |
| `AUTO:HEADER` | Identity block | `.trinity/passport.json` fields |
| `AUTO:LAST_UPDATED` | Timestamp | Most recent file modification |

**Rules:**
- Opening marker: `<!-- AUTO:NAME -->`
- Closing marker: `<!-- /AUTO:NAME -->`
- Content between markers is overwritten on regeneration
- Content outside markers is never touched

---

## Freshness Rules

1. **Last Updated** — README's "Last Updated" date should be within 7 days of most recent code change
2. **Directory Tree** — Tree in README must match actual filesystem
3. **Module List** — All files in `apps/modules/` should be listed

**WHY:** A README that says one thing while the code says another is worse than no README at all.

---

## Manual Sections

These sections require human judgment and are NOT auto-generated:

- **Purpose / Overview** — What the branch does and why it exists
- **Architecture** — Design decisions and patterns
- **Key Capabilities** — What makes this branch valuable
- **Integration Points** — How this branch connects to others

Auto-generation handles facts (file lists, timestamps). Humans handle meaning.

---

## Enforcement

| Tool | Purpose | Location |
|------|---------|----------|
| `readme_check.py` | 6 automated checks, score >= 75% to pass | `src/aipass/seedgo/apps/standards/aipass/handlers/standards/` |
| `readme_generator.py` | Auto-populates TREE, MODULES, COMMANDS, HEADER, LAST_UPDATED | `src/aipass/seedgo/apps/standards/aipass/handlers/standards/` |
| `seedgo readme update @branch` | On-demand regeneration (Phase 4, coming soon) | CLI |

**Checks performed by `readme_check.py`:**
1. README.md exists
2. Contains auto-generated markers
3. Last Updated is within 7 days
4. Directory tree matches filesystem
5. Module list is complete
6. Required sections present

---

## What Goes in README vs Elsewhere

| Content | Location | Why |
|---------|----------|-----|
| Current state | README.md | Human-readable snapshot |
| Future plans | FPLAN files (flow) | Not current state |
| Past work | .local.json sessions | History, not docs |
| Patterns learned | .observations.json | AI context, not docs |
| Technical deep-dives | docs/ directory | Too detailed for README |

---

## Examples

**Good:** Auto-generated tree with `<!-- AUTO:TREE -->` markers that stays current
```markdown
<!-- AUTO:TREE -->
```
apps/
├── seedgo.py
├── modules/
│   ├── imports_standard.py
│   └── readme_standard.py
└── handlers/
    └── standards/
        ├── readme_check.py
        └── readme_generator.py
```
<!-- /AUTO:TREE -->
```

**Bad:** Manually maintained tree that drifts from reality within a week
```markdown
## Directory Structure
```
apps/
├── seedgo.py
├── modules/
│   └── old_module.py    # deleted 3 weeks ago
└── handlers/
    └── missing_new_handler.py  # never added
```
```

---

## Quick Reference

| Rule | Requirement |
|------|-------------|
| README.md exists | Required for every branch |
| Section order | Follow canonical order |
| Auto markers | Use `<!-- AUTO:NAME -->` / `<!-- /AUTO:NAME -->` |
| Freshness | Last Updated within 7 days |
| Tree accuracy | Must match filesystem |
| Module completeness | All `apps/modules/` files listed |
| Manual sections | Human-written, never auto-generated |
| Pass threshold | Score >= 75% on `readme_check.py` |
