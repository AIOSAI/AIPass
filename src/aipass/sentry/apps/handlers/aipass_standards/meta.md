# META Block Standards
**Status:** Active v1
**Date:** 2026-03-09

---

## Core Principle: Identity at the Top

Every Python file in AIPass starts with a META block. It is the file's passport -- name, purpose, version, and timestamps. META is always line 1. No exceptions.

**WHY:** When an agent or human opens a file, the first thing they see is what the file is, what it does, and when it was last touched. No scrolling, no guessing, no `git log` required.

---

## Required META Format

```python
# =================== AIPass ====================
# Name: filename.py
# Description: Brief description of the file
# Version: X.Y.Z
# Created: YYYY-MM-DD
# Modified: YYYY-MM-DD
# =============================================
```

### Field Requirements

| Field | Format | Rule |
|-------|--------|------|
| **Header** | `# =================== AIPass ====================` | Exact match. Legacy `META` header also accepted. |
| **Name** | `# Name: filename.py` | Must match the actual filename on disk. |
| **Description** | `# Description: ...` | At least one non-whitespace word after the colon. |
| **Version** | `# Version: X.Y.Z` | Semantic versioning (three integers separated by dots). |
| **Created** | `# Created: YYYY-MM-DD` | ISO date format. Set once, never changed. |
| **Modified** | `# Modified: YYYY-MM-DD` | ISO date format. Updated on every meaningful edit. |
| **Footer** | `# =============================================` | Exact match. Closes the block. |

---

## Placement Rules

1. **META block MUST be line 1** -- the header marker is the very first line of the file.
2. **All code, docstrings, and imports go below** the META block.
3. **No blank lines above** the META block. Nothing precedes it.

**Good:**
```python
# =================== AIPass ====================
# Name: router.py
# Description: Command routing for drone
# Version: 2.1.0
# Created: 2025-10-15
# Modified: 2026-03-01
# =============================================

"""
Command Router

Routes incoming commands to appropriate modules.
"""

import sys
from pathlib import Path
```

**Bad:**
```python
"""This module handles routing."""

# =================== AIPass ====================
# Name: router.py
# ...
```
The docstring pushes META off line 1. META must come first.

**Bad:**
```python
# =================== AIPass ====================
# Name: wrong_name.py
# Description: Command routing
# Version: 2.1.0
# Created: 2025-10-15
# Modified: 2026-03-01
# =============================================
```
Name field says `wrong_name.py` but the file is actually `router.py`. Name must match.

---

## Exceptions

- **`__init__.py` files are skipped** -- they are structural files, not functional modules. No META required.

---

## Legacy Header Support

The checker accepts both the canonical header and the legacy header:

- Canonical: `# =================== AIPass ====================`
- Legacy: `# =================== META ====================`

New files MUST use the `AIPass` header. Legacy headers are tolerated for backward compatibility.

---

## Scoring

The META standard runs 7 checks:

1. **META block present** -- header and footer markers exist
2. **META placement** -- header is on line 1
3. **META Name** -- Name field present, valid, and matches filename
4. **META Description** -- Description field present with content
5. **META Version** -- Version field present in X.Y.Z format
6. **META Created** -- Created field present in YYYY-MM-DD format
7. **META Modified** -- Modified field present in YYYY-MM-DD format

**Pass threshold:** 75% (at least 6 of 7 checks must pass to achieve overall pass).

**Score calculation:** `(passed_checks / total_checks) * 100`

---

## Bypass

Files can be exempted from META checking via `.sentry/bypass.json`. When bypassed, the file receives an automatic 100% score.

---

## Summary

1. **Every `.py` file gets a META block** (except `__init__.py`)
2. **META is always line 1** -- before docstrings, before imports, before everything
3. **Name field must match the actual filename** -- no mismatches tolerated
4. **Use AIPass header** for new files -- legacy META header accepted but deprecated
5. **Update Modified date** on every meaningful change
6. **Version follows semver** -- bump it when behavior changes
