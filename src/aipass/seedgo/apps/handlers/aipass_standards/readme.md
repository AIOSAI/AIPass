# README Standards
**Status:** Active v1.2
**Date:** 2026-09-15

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

1. **Last Updated** — README must carry a parseable `Last Updated: YYYY-MM-DD` line. Presence and shape only: recency is not a property of the files on disk, so the audit never compares it against code history (that would score a working tree and a clean CI checkout differently)
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
| `readme_check.py` | 8 scored checks (>= 75% to pass) + the advisory lane | `apps/handlers/aipass_standards/` |
| `readme_generator.py` | Auto-populates TREE, MODULES, COMMANDS, HEADER, LAST_UPDATED | `apps/handlers/readme/` |
| `drone @seedgo readme update @branch` | On-demand regeneration | CLI |

**Checks performed by `readme_check.py`:**
1. README.md exists
2. Required sections present
3. Last Updated line present and parseable
4. Directory tree matches filesystem
5. Module list is complete
6. Command list presence
7. Test count accuracy (claimed vs actual `def test_` count, >10% drift fails)
8. Markdown link validity (relative `[text](path)` links point to existing files)

**Advisory lane (`check_branch_info`) — reported, never scored:**
9. **docs index** — every `docs/*.md` reachable from the README
10. **named paths** — branch-rooted paths the README claims exist
11. **rot bait** — count claims, dated/Status headings, a Commands section that re-types `--help`

---

## Advisory Lane — the docs index and rot bait

The README is the **face** for strangers and other agents, plus an **index of `docs/`**. The live inventory is `drone @<branch>` and `--help`, generated from code, so it never rots. The depth lives in `docs/`, one file per module or handler group, indexed from the README and read when something breaks. (DPLAN-0347, boardroom thread 16, 2026-09-15.)

Three readings arrive as non-scored info lines on `drone @seedgo audit aipass @<branch>`:

| Reading | What it says | Scope boundary |
|---------|--------------|----------------|
| docs index | Every `docs/*.md` must be reachable from the README — a relative link that resolves to it, or the literal `docs/<name>` in the text. A link to `docs/` covers `docs/README.md`. | No `docs/` directory is **silence**, not a finding |
| named paths | A path the README names, rooted in one of this branch's own top-level directories, must exist | Link targets belong to check 8, directories to check 4. Paths relative to somewhere deeper, a neighbour branch's files and illustrations are out of scope — an audit of one branch cannot tell a stale reference from a foreign one |
| rot bait | Counts ("46 standards"), dated or Status/Latest Audit headings, and a Commands section that re-types `--help` | The `Last Updated` line is exempt (check 3 requires it). The Commands line asks for a **pointer**, not a deletion — checks 2 and 6 still want the section |

**Why advisory, not a ninth check.** `readme` is scored and CI gates every branch at 100 (`.github/scripts/seedgo_audit.py`). 17 of 18 branches have no docs index today, so a scored check would put the whole fleet red on the commit that landed it — the mistake of 2026-09-13, when a renderer change reded 17 of 18 branches. The ruling is *advisory, then ratchet*: measure for a week, then gate per file.

**Why `check_branch_info()` and not the other non-scored channels.** `ADVISORY = True` is a module flag — on a scored standard it drops the whole standard out of the gating average. `check_branch_observe()` carries a would-be score and writes a dated series to `branch_observe_log.json`, but nothing renders it, and these lines exist to be read per branch by the owner doing the diet. `check_branch_info()` renders for every branch at any score and can move no number.

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
| docs index | Every `docs/*.md` linked from the README (advisory) |
| Rot bait | No counts, no dated status, no copy of `--help` (advisory) |
