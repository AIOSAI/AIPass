# README Standards
**Status:** Active v1.3
**Date:** 2026-09-19

---

## What This Covers

Standards for branch README.md files. The README is the face, for strangers and other agents; the live inventory is `drone @<branch>` and `--help`, generated from code; the depth is `docs/`. Every section is human-written, and a README stays accurate by pointing at what regenerates rather than copying it.

---

## README Required

Every branch root must have a `README.md` file. Without one, the branch has no human-readable documentation of its current state.

---

## Canonical Section Order

The face is eight `##` sections, names exact, order fixed. This is the fleet's de facto order (DPLAN-0351); 6 of 18 READMEs carried it exactly on the day it was written down:

1. **Quick Start** — the first commands a newcomer runs
2. **What It Does** — what the branch owns, in a few lines
3. **Live Inventory** — a pointer to `drone @<branch>` and `--help`, never a copy
4. **How To Reach Me** — mail, dispatch, the address
5. **Commands** — a pointer to `--help`, and the few verbs worth naming
6. **Architecture** — the layout and the idea behind it
7. **Documentation** — the `docs/` index, one line per page
8. **Integration Points** — what the branch depends on and what depends on it

Above the first section sit the back-link, the H1 and the purpose. Every README carries all eight. The advisory line `readme sections` names what is missing, what is renamed ("What I Do" for **What It Does**), what is out of order and any `##` heading that is not one of the eight. `###` subsections under a section are free.

---

## Retired: Generated Sections

The `<!-- AUTO:NAME -->` marker sections (TREE, MODULES, COMMANDS, HEADER, LAST_UPDATED) are retired. No README in the fleet carries one, and a generated copy of the inventory in the face is exactly what the live inventory replaced: `drone @<branch>` and `--help` are generated from code on every call. `drone @seedgo readme update` finds no marker on any branch and writes nothing.

---

## Freshness Rules

1. **Last Updated** — README must carry a parseable `Last Updated: YYYY-MM-DD` line. Presence and shape only: recency is not a property of the files on disk, so the audit never compares it against code history (that would score a working tree and a clean CI checkout differently)
2. **Directory Tree** — Tree in README must match actual filesystem
3. **Module List** — All files in `apps/modules/` should be listed

**WHY:** A README that says one thing while the code says another is worse than no README at all.

---

## Enforcement

| Tool | Purpose | Location |
|------|---------|----------|
| `readme_check.py` | 8 scored checks (>= 75% to pass) + the advisory lane | `apps/handlers/aipass_standards/` |

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
12. **sections** — the eight `##` sections of the Canonical Section Order, names exact, order fixed

---

## Advisory Lane — the docs index and rot bait

The README is the **face** for strangers and other agents, plus an **index of `docs/`**. The live inventory is `drone @<branch>` and `--help`, generated from code, so it never rots. The depth lives in `docs/`, one file per module or handler group, indexed from the README and read when something breaks. (DPLAN-0347, boardroom thread 16, 2026-09-15.)

Four readings arrive as non-scored info lines on `drone @seedgo audit aipass @<branch>`:

| Reading | What it says | Scope boundary |
|---------|--------------|----------------|
| docs index | Every `docs/*.md` must be reachable from the README — a relative link that resolves to it, or the literal `docs/<name>` in the text. A link to `docs/` covers `docs/README.md`. | No `docs/` directory is **silence**, not a finding |
| named paths | A path the README names, rooted in one of this branch's own top-level directories, must exist | Link targets belong to check 8, directories to check 4. Paths relative to somewhere deeper, a neighbour branch's files and illustrations are out of scope — an audit of one branch cannot tell a stale reference from a foreign one |
| rot bait | Counts ("46 standards"), dated or Status/Latest Audit headings, and a Commands section that re-types `--help` | The `Last Updated` line is exempt (check 3 requires it). The Commands line asks for a **pointer**, not a deletion — checks 2 and 6 still want the section |
| sections | The eight `##` sections, names exact, order fixed: what is missing, a rename (a heading sharing its first word with a missing section), the out-of-order pairs, and any `##` heading that is not one of the eight | `#`, `###` and fenced lines are not sections. All eight in order is **silence**. Advisory because 12 of 18 READMEs are off the order today |

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

**Good:** A Live Inventory that points at what regenerates
```markdown
## Live Inventory

The modules and commands are generated from the code that runs them:
`drone @mybranch` for the self-map, `drone @mybranch --help` for every verb.
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
| Sections | The eight `##` sections, names exact, order fixed (advisory) |
| Last Updated | A parseable `Last Updated: YYYY-MM-DD` line (presence and shape, not recency) |
| Tree accuracy | Must match filesystem |
| Module completeness | All `apps/modules/` files listed |
| Pass threshold | Score >= 75% on `readme_check.py` |
| docs index | Every `docs/*.md` linked from the README (advisory) |
| Rot bait | No counts, no dated status, no copy of `--help` (advisory) |
