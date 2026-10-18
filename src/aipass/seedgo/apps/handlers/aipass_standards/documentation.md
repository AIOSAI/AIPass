# Documentation Standards
**Status:** v2.0 - Aligned with meta_check.py (source of truth)
**Date:** 2026-03-06

---

## File Header Structure

Every Python file follows this header pattern:

```python
# =================== AIPass ====================
# Name: filename.py
# Description: Brief description of the file
# Version: 1.0.0
# Created: 2026-03-06
# Modified: 2026-03-06
# =============================================

"""
Module Title

Brief description of module purpose.
Key functionality:
- Feature 1
- Feature 2
- Feature 3
"""
```

---

## No Shebangs Required

AIPass is a pip package. All execution goes through entry points defined in `pyproject.toml` or `python3 -m`. Shebangs are not needed and should not be added.

---

## META Block

**Standard format (enforced by `meta_check.py`):**
```python
# =================== AIPass ====================
# Name: example_module.py
# Description: Example module for demonstration
# Version: 1.0.0
# Created: 2026-03-06
# Modified: 2026-03-06
# =============================================
```

**Required fields:**
- **Name:** Must match the actual filename (e.g., `example_module.py`)
- **Description:** Brief description of what the file does
- **Version:** Semantic versioning (X.Y.Z)
- **Created:** Date the file was created (YYYY-MM-DD)
- **Modified:** Date the file was last modified (YYYY-MM-DD)

**Markers:**
- Header: `# =================== AIPass ====================`
- Footer: `# =============================================`

**Rules:**
- `__init__.py` files are exempt (skipped by checker)
- Name field is validated against the actual filename
- All five fields are required
- Pass threshold: 75% of checks

**WHY META blocks:**
- **AI scannable:** Agents can extract metadata without parsing code
- **Version tracking:** Know what version you're looking at immediately
- **Traceability:** Created/Modified dates show file history at a glance
- **Standardization:** Every file has same metadata structure

---

## Module-Level Docstrings

**Pattern:** Triple-quoted string immediately after META block

```python
"""
Module Title

Brief description of module purpose.
Longer explanation if needed.

Key functionality:
- Feature 1
- Feature 2
- Feature 3

May include usage examples or workflow notes.
"""
```

**Examples:**

**Module:**
```python
"""
Create Branch Module

Creates a new AIPass branch from template with all necessary structure.
Workflow: template copy, file renaming, module migration, branch registration
"""
```

**Handler:**
```python
"""
File Operations Handler

Functions for file and directory operations:
- File renaming with placeholder replacement
- Directory renaming
- Template content copying
- Module migration
- Memory file management
"""
```

**With usage example:**
```python
"""
Standards Checker

Validates code against AIPass standards.

Usage:
    from aipass.seedgo.apps.modules.checker import run_checks

    results = run_checks(module_path)
"""
```

**WHY:** First thing you see after metadata. Tells you what the file does and key features. No need to read code to understand purpose.

---

## Function Docstrings

**Pattern:** Google-style with Args/Returns/Raises

```python
def function_name(arg1: Type, arg2: Type) -> ReturnType:
    """
    Brief one-line description

    Longer description if needed (optional).
    Can span multiple lines for complex functions.

    Args:
        arg1: Description of arg1
        arg2: Description of arg2

    Returns:
        Description of return value

    Raises:
        ExceptionType: When this exception occurs (optional)
    """
```

**Examples:**

```python
def find_files(target_dir: Path, branch_name: str) -> Dict[str, Path]:
    """
    Find files matching branch naming convention.

    Args:
        target_dir: Path to branch directory
        branch_name: Branch name to match against

    Returns:
        Dict mapping file types to Path objects
    """
```

```python
def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check if module has a valid library-profile META block.

    Args:
        module_path: Path to Python module to check
        bypass_rules: Optional bypass rules

    Returns:
        dict with passed, checks, score, standard keys
    """
```

**WHY Google-style:**
- **Readable:** Args/Returns sections visually separate
- **Parseable:** Tools can extract parameter docs automatically
- **Standard:** Widely used, AI understands it well

**When to skip Raises:** If function doesn't raise exceptions or uses decorators for error handling.

---

## Type Hints

**Rule:** ALL function signatures have type hints

```python
# Standard types
def function(path: Path, name: str, count: int) -> bool:

# Optional types
def function(data: Optional[str]) -> Optional[Path]:

# Generic types
def function(data: Dict[str, Any]) -> List[str]:

# Tuple returns
def function() -> Tuple[List[str], List[str]]:

# Modern union (Python 3.10+)
def validate_path(path: Path) -> tuple[bool, str | None]:
```

**Complex example:**
```python
def copy_template_contents(
    template_dir: Path,
    target_dir: Path,
    replacements: Dict[str, str],
    branch_name: str,
    exclude_patterns: List[str],
    file_renames: Dict[str, str],
    allowed_placeholders: set = None
) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
```

**WHY:**
- **AI comprehension:** Knows what types to expect/return
- **IDE support:** Autocomplete, error detection
- **Self-documenting:** Function signature tells you data shapes
- **Error prevention:** Catch type mismatches before runtime

---

## Section Separators

**Pattern:** Comment blocks to organize code sections

```python
# =============================================================================
# SECTION NAME
# =============================================================================
```

**Common sections (verified in actual code):**
- `CONSTANTS`
- `FILE DISCOVERY AND MATCHING`
- `HELPER FUNCTIONS`
- `CORE WORKFLOW`
- `MODULE INTERFACE`
- `FILE OPERATIONS`
- `METADATA EXTRACTION`
- `STANDALONE EXECUTION`

**Example:**
```python
# =============================================================================
# CONSTANTS
# =============================================================================

MODULE_DIR = Path(__file__).parent
EXCLUDE_PATTERNS = [".git", "__pycache__"]
```

**Example:**
```python
# =============================================================================
# FILE DISCOVERY AND MATCHING
# =============================================================================

def find_files(target_dir: Path, branch_name: str) -> Dict[str, Path]:
    """Find files matching branch naming convention"""
```

**WHY:**
- **Quick navigation:** Scan file, find section instantly
- **Logical grouping:** Related functions together
- **AI parsing:** Clear boundaries for context extraction

---

## Inline Comments

**When to use:**
1. Clarifying non-obvious logic (what and why)
2. Important warnings or gotchas
3. Algorithm steps in complex operations
4. Protection rules or edge cases

**Patterns:**

```python
# Single-line explanation above code
backup_branch()

# Inline explanation for single statement
result = complex_operation()  # Extracts metadata from template

# Multi-step process markers
# Step 1: Backup branch
backup()

# Step 2: Remove from registry
remove()
```

**Examples:**

```python
# Memory file suffixes to check (JSON format)
memory_suffixes = [".json", ".local.json", ".observations.json"]

# Normalize to check if it matches branch name
prefix_normalized = prefix.replace("-", "_").upper()
```

**When NOT to use:**
- Obvious code (don't narrate what's already clear)
- Repeating what docstring says
- Commenting out old code (delete it instead)

**WHY:**
- **Context for future you:** Why did I do it this way?
- **Warning flags:** PROTECTION RULE stands out
- **Algorithm clarity:** Step markers show workflow

---

## Import Organization

**Standard pattern:**

```python
# [META BLOCK]

"""Module docstring"""

# Standard library imports
import json
from pathlib import Path
from typing import Dict, List, Optional

# Third-party imports (if any)

# Internal imports (always use pip namespace)
from aipass.module.apps.modules import something
```

**Import sections (in order):**
1. Standard library imports
2. Third-party imports
3. Internal imports (always `from aipass.{module}...`)

**WHY this order:**
- **Standard library grouped:** Easy to see external dependencies
- **Third-party separate:** Clear boundary between stdlib and packages
- **Internal last:** After all external dependencies resolved
- **Namespace required:** Always `from aipass.{module}...`, never bare imports

---

## Constants

**Pattern:** ALL_CAPS names with inline comments

```python
# =============================================================================
# CONSTANTS
# =============================================================================

# Paths resolved relative to module location
MODULE_DIR = Path(__file__).parent

# Files to exclude from template copy
EXCLUDE_PATTERNS = [
    ".git",
    "__pycache__",
]

# Configuration mappings
FILE_RENAMES = {
    "LOCAL.json": "{BRANCHNAME}.local.json",
    "OBSERVATIONS.json": "{BRANCHNAME}.observations.json",
}
```

**WHY:**
- **ALL_CAPS signals:** This is configuration, not a variable
- **Comments explain purpose:** Not just WHAT, but WHY we need it
- **Grouped together:** All config in one place, easy to modify
- **No hardcoded paths:** Use `Path(__file__)` or registry lookups

---

## Summary: Documentation Hierarchy

**File level (top to bottom):**
1. Module docstring (optional, before META)
2. META block (metadata)
3. Imports (organized)
4. Constants (configuration)
5. Section separators + functions (implementation)

**Function level:**
- Type hints (signature)
- Docstring (Args/Returns/Raises)
- Inline comments (clarification only)

**WHY this matters:**
- **AI scannable:** Can extract metadata/purpose without reading all code
- **Human scannable:** Read top to bottom, understand file in 30 seconds
- **Consistent:** Same structure everywhere, know where to look

---

## Quick Reference

| Element | Pattern | Required? |
|---------|---------|-----------|
| META Block | Library META format (5 fields) | **Yes** |
| Module Docstring | Triple-quoted | **Yes** |
| Function Docstring | Google-style | **Yes** |
| Type Hints | Full typing | **Yes** |
| Section Separators | `# ===...===` | Recommended |
| Inline Comments | Clarification only | As needed |
| Import Organization | Standard → Third-party → Internal | Yes |

**Source of truth:** `meta_check.py` defines and enforces the META block format.

---

## Verification Notes

**Source of truth for META format:** `seedgo/apps/standards/aipass/handlers/standards/meta_check.py`

META block format aligned with checker enforcement on 2026-03-06.

## How the checker reads a file

Both checks read the parse tree, never the spelling:

- **Module docstring:** the first statement of the module body IS a string (`ast.get_docstring`).
  A prefixed docstring (`r"""..."""`) counts; a triple-quoted string later in the file (a class
  or function docstring, a multi-line constant) does not.
- **Function docstrings:** public functions (not starting with `_`) are AST `def` and `async def`
  nodes, nested ones included. A `def` inside a docstring example or a source string is not a
  function.
- A file that does not parse falls back to a line scan and says so in the message, so a
  fallback never reads like a verdict from the real arm.
