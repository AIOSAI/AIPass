# =================== AIPass ====================
# Name: encapsulation_check.py
# Description: Handler Encapsulation Standards Checker
# Version: 1.1.0
# Created: 2026-03-05
# Modified: 2026-03-15
# =============================================

"""
Handler Encapsulation Standards Checker

Validates that handlers are properly encapsulated:
- No cross-branch handler imports (Branch A importing Branch B's handlers)
- No cross-package handler imports (handlers/X importing handlers/Y)
- Handlers should be accessed through module entry points, not directly
- Handler security guards present in handlers/__init__.py (inspect.stack guard)
"""

import ast
import re
import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

# Audit scope: all Python files
AUDIT_SCOPE = "all_files"
# Applies to production source only: reaching into another module's internals is
# what a unit test is FOR. 247 of 456 fleet test files failed this (54%, every
# branch) for doing their job.
APPLIES_TO = "production"

# Cross-branch/cross-package handler imports are import-statement checks, so a
# violation hiding in a package marker file must not be invisible to the audit
# the way it would be for content checkers (dead code, naming, etc.).
INCLUDE_INIT_FILES = True


def _find_registry() -> Path:
    """Find AIPASS_REGISTRY.json by walking up from this file's location."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        candidate = parent / "AIPASS_REGISTRY.json"
        if candidate.exists():
            return candidate
    return Path.cwd() / "AIPASS_REGISTRY.json"


def _infer_branch_from_path(file_path: str) -> Optional[Dict]:
    """Infer branch info from filesystem path when registry is unavailable.

    Looks for the ``src/aipass/{branch}/apps/`` or ``{branch}/apps/`` pattern
    and returns a minimal branch dict with name and path.
    """
    resolved = Path(file_path).resolve()
    parts = resolved.parts
    for i, part in enumerate(parts):
        if part == "apps" and i >= 1:
            candidate = Path(*parts[:i])
            branch_name = parts[i - 1]
            if branch_name == "src":
                continue
            return {"name": branch_name, "path": str(candidate)}
    return None


def get_branch_from_path(file_path: str) -> Optional[Dict]:
    """Detect which branch a file belongs to using AIPASS_REGISTRY.json.

    Falls back to path-based inference when the registry is unavailable
    (e.g. in CI clean-checkout environments where the registry is gitignored).
    """
    try:
        registry_path = _find_registry()
        if not registry_path.exists():
            return _infer_branch_from_path(file_path)

        with open(registry_path, "r", encoding="utf-8") as f:
            registry = json.load(f)

        if not registry:
            return _infer_branch_from_path(file_path)

        registry_dir = registry_path.parent
        resolved_path = str(Path(file_path).resolve())

        # Sort branches by path length (longest first) to match most specific
        branches = sorted(registry.get("branches", []), key=lambda b: len(b.get("path", "")), reverse=True)

        for branch in branches:
            raw_path = branch.get("path", "")
            branch_path = Path(raw_path)
            if not branch_path.is_absolute():
                branch_path = (registry_dir / branch_path).resolve()
            branch_path_str = str(branch_path)
            if resolved_path.startswith(branch_path_str + "/") or resolved_path == branch_path_str:
                return branch

        return _infer_branch_from_path(file_path)
    except Exception:
        logger.info("Cannot determine branch for path: %s", file_path)
        return _infer_branch_from_path(file_path)


def extract_branch_from_import(import_line: str) -> Optional[str]:
    """
    Extract branch name from an import statement

    Examples:
        'from flow.apps.handlers.plan.validator import X' -> 'flow'
        'from aipass.api.apps.handlers.openrouter import X' -> 'api'
        'from apps.handlers.json import X' -> None (local, no branch)
    """
    # Pattern 1: branch.apps.handlers...
    match = re.search(r"from\s+(\w+)\.apps\.handlers", import_line)
    if match:
        return match.group(1)

    # Pattern 2: aipass.branch.apps.handlers...
    match = re.search(r"from\s+aipass\.(\w+)\.apps\.handlers", import_line)
    if match:
        return match.group(1)

    # Pattern 3: import branch.apps.handlers...
    match = re.search(r"import\s+(\w+)\.apps\.handlers", import_line)
    if match:
        return match.group(1)

    return None


def extract_handler_package(import_line: str) -> Optional[str]:
    """
    Extract the handler package name from an import

    Examples:
        'from apps.handlers.json.json_handler import X' -> 'json'
        'from apps.handlers.dashboard.refresh import X' -> 'dashboard'
        'from flow.apps.handlers.plan.validator import X' -> 'plan'
    """
    match = re.search(r"apps\.handlers\.(\w+)", import_line)
    if match:
        return match.group(1)
    return None


def get_file_handler_package(file_path: str) -> Optional[str]:
    """
    Get the handler package a file belongs to

    Examples:
        '/home/.../apps/handlers/json/json_handler.py' -> 'json'
        '/home/.../apps/modules/something.py' -> None (not a handler)
    """
    path_str = str(file_path)

    if "apps/handlers/" not in path_str:
        return None

    # Extract package after apps/handlers/
    match = re.search(r"apps/handlers/(\w+)", path_str)
    if match:
        return match.group(1)
    return None


# Cache handler guard results per branch path (reset each audit run)
_handler_guard_cache: Dict[str, Optional[Dict]] = {}


def _resolve_branch_path(file_path: str) -> Optional[Path]:
    """Resolve the branch root directory for a given file path."""
    branch_info = get_branch_from_path(file_path)
    if not branch_info:
        return None
    raw_path = branch_info.get("path", "")
    branch_path = Path(raw_path)
    if not branch_path.is_absolute():
        registry_path = _find_registry()
        branch_path = (registry_path.parent / branch_path).resolve()
    return branch_path


def check_handler_guard(module_path: str, bypass_rules: list | None = None) -> Optional[Dict]:
    """
    Check that a branch's handlers/__init__.py contains a security guard.

    The guard uses inspect.stack() to block cross-branch handler imports
    at runtime. Branches without this guard have unprotected handlers.

    Returns a check dict, or None if the check is not applicable
    (e.g., no handlers/ directory in the branch).
    """
    branch_path = _resolve_branch_path(module_path)
    if branch_path is None:
        return None

    branch_key = str(branch_path)

    # Return cached result if already checked this branch
    if branch_key in _handler_guard_cache:
        return _handler_guard_cache[branch_key]

    # Check if bypassed
    init_path = branch_path / "apps" / "handlers" / "__init__.py"
    if is_bypassed(str(init_path), "encapsulation", bypass_rules=bypass_rules):
        result = {"name": "Handler security guard", "passed": True, "message": "Handler guard check bypassed"}
        _handler_guard_cache[branch_key] = result
        return result

    handlers_dir = branch_path / "apps" / "handlers"
    if not handlers_dir.is_dir():
        # No handlers directory — check not applicable
        _handler_guard_cache[branch_key] = None
        return None

    if not init_path.exists():
        result = {
            "name": "Handler security guard",
            "passed": False,
            "message": "Missing handlers/__init__.py — no handler security guard",
        }
        _handler_guard_cache[branch_key] = result
        return result

    # Read the init file and check for guard patterns
    try:
        content = init_path.read_text(encoding="utf-8")
    except Exception:
        logger.info("Cannot read handlers/__init__.py at %s", init_path)
        result = {"name": "Handler security guard", "passed": False, "message": "Cannot read handlers/__init__.py"}
        _handler_guard_cache[branch_key] = result
        return result

    # Count non-empty, non-comment lines
    code_lines = [ln for ln in content.split("\n") if ln.strip() and not ln.strip().startswith("#")]

    # Guard detection: look for key patterns
    guard_patterns = ["_guard_branch_access", "inspect.stack", "ImportError"]
    has_guard = any(pattern in content for pattern in guard_patterns)

    if has_guard:
        result = {
            "name": "Handler security guard",
            "passed": True,
            "message": "Handler security guard present (inspect.stack guard active)",
        }
    elif len(code_lines) < 10:
        result = {
            "name": "Handler security guard",
            "passed": False,
            "message": "Missing handler security guard — cross-branch imports unprotected",
        }
    else:
        # File has substantial code but no recognized guard patterns
        result = {
            "name": "Handler security guard",
            "passed": False,
            "message": "handlers/__init__.py has code but no recognized security guard pattern",
        }

    _handler_guard_cache[branch_key] = result
    return result


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check if file respects handler encapsulation

    Args:
        module_path: Path to Python file to check
        bypass_rules: Optional list of bypass rules to apply

    Returns:
        dict: {
            'passed': bool,
            'checks': [{'name': str, 'passed': bool, 'message': str}],
            'score': int,
            'standard': str
        }
    """
    checks = []
    path = Path(module_path)

    # Check if entire standard is bypassed
    if is_bypassed(module_path, "encapsulation", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "ENCAPSULATION",
        }

    # Validate file exists
    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "ENCAPSULATION",
        }

    # Read file
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
            lines = content.split("\n")
    except Exception as e:
        logger.info("Cannot read %s: %s", path, e)
        return {
            "passed": False,
            "checks": [{"name": "File readable", "passed": False, "message": f"Error reading file: {e}"}],
            "score": 0,
            "standard": "ENCAPSULATION",
        }

    # Detect this file's context
    file_branch = get_branch_from_path(module_path)
    file_branch_name = file_branch.get("name", "").lower() if file_branch else None
    file_handler_package = get_file_handler_package(module_path)
    is_handler_file = file_handler_package is not None
    is_module_file = "apps/modules/" in str(module_path)

    # Check 1: Cross-branch handler imports
    cross_branch_check = check_cross_branch_imports(lines, module_path, file_branch_name, bypass_rules)
    checks.append(cross_branch_check)

    # Check 2: Cross-package handler imports (only for handler files)
    if is_handler_file:
        cross_package_check = check_cross_package_imports(lines, module_path, file_handler_package, bypass_rules)
        checks.append(cross_package_check)

    # Check 3: Direct handler imports from non-handler/non-module files
    if not is_handler_file and not is_module_file:
        direct_import_check = check_direct_handler_imports(lines, module_path, bypass_rules)
        checks.append(direct_import_check)

    # Check 4: Handler security guard presence (branch-level, cached)
    guard_check = check_handler_guard(module_path, bypass_rules)
    if guard_check is not None:
        checks.append(guard_check)

    # Calculate score
    if not checks:
        return {
            "passed": True,
            "checks": [{"name": "Encapsulation", "passed": True, "message": "No checks applicable"}],
            "score": 100,
            "standard": "ENCAPSULATION",
        }

    passed_checks = sum(1 for check in checks if check["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 100

    json_handler.log_operation(
        "check_completed", {"file": str(module_path), "score": score, "standard": "encapsulation"}
    )
    return {"passed": score >= 75, "checks": checks, "score": score, "standard": "ENCAPSULATION"}


def check_cross_branch_imports(
    lines: List[str], module_path: str, file_branch: Optional[str], bypass_rules: list | None = None
) -> Dict:
    """
    Check for cross-branch handler imports

    BAD: from flow.apps.handlers.plan.validator import X (when not in flow branch)
    BAD: from api.apps.handlers.openrouter.client import X (when not in api branch)

    EXCEPTIONS:
    - Prax logger (from prax.apps.modules.logger) - allowed everywhere
    - CLI services (from cli.apps.modules) - allowed everywhere
    - Same branch imports - allowed
    """
    violations = []

    in_docstring = False
    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Track docstrings
        if stripped.startswith('"""') or stripped.startswith("'''"):
            quote_marker = '"""' if stripped.startswith('"""') else "'''"
            quote_count = stripped.count(quote_marker)
            if quote_count >= 2:
                continue
            else:
                in_docstring = not in_docstring

        if in_docstring or not stripped or stripped.startswith("#"):
            continue

        # Check for imports
        if not ("from " in stripped or "import " in stripped):
            continue

        # Skip string literals - check if line is a string or apps.handlers is inside quotes
        if stripped.startswith('"') or stripped.startswith("'"):
            continue
        if '"from ' in stripped or "'from " in stripped:
            continue
        # Check if apps.handlers appears inside quotes (documentation examples)
        if '"apps.handlers' in stripped or "'apps.handlers" in stripped:
            continue
        if "apps.handlers" in stripped:
            # Check if it's inside a string by looking for quotes before it
            handler_pos = stripped.find("apps.handlers")
            before = stripped[:handler_pos]
            # If there's an odd number of quotes before, it's inside a string
            if before.count('"') % 2 == 1 or before.count("'") % 2 == 1:
                continue

        # Extract code part (before comment)
        code_part = stripped.split("#")[0] if "#" in stripped else stripped

        # Check for handler imports
        if "apps.handlers" not in code_part:
            continue

        # Check if bypassed
        if is_bypassed(module_path, "encapsulation", line=i, bypass_rules=bypass_rules):
            continue

        # Extract the branch being imported from
        imported_branch = extract_branch_from_import(code_part)

        if imported_branch is None:
            # Local import (from apps.handlers.X) - will be caught by cross-package check
            continue

        # Allow same-branch imports
        if file_branch and imported_branch.lower() == file_branch.lower():
            continue

        # Disallow cross-branch handler imports (even from service branches)
        # Service branches should be accessed via modules, not handlers
        violations.append(
            {
                "line": i,
                "code": code_part.strip(),
                "from_branch": imported_branch,
                "to_branch": file_branch or "unknown",
            }
        )

    if violations:
        first = violations[0]
        return {
            "name": "Cross-branch handler imports",
            "passed": False,
            "message": f"Line {first['line']}: {first['from_branch']}.apps.handlers imported (use modules entry point)",
        }

    return {
        "name": "Cross-branch handler imports",
        "passed": True,
        "message": "No cross-branch handler imports detected",
    }


#: Handlers every module may import by name, because a branch cannot function
#: without them. Kept as NAMES only for the two that were always here; anything
#: else must EARN the exemption structurally — see :func:`_infrastructure_handlers`.
_DEFAULT_HANDLERS = frozenset({"json_handler", "file_handler"})


#: The fleet-ratified spellings of the guarded ``__file__`` / repo-root
#: resolution shim. A module that DEFINES one of these at module level IS that
#: shim; a module that merely calls it is not. Names, not files, because the
#: file name varies by branch (module_root.py, paths.py, repo_root.py,
#: module_paths.py) while the function it publishes does not.
_RESOLUTION_SHIM_FUNCTIONS = frozenset({"module_file", "find_repo_root", "source_root", "resolved_file"})


@lru_cache(maxsize=32)
def _infrastructure_handlers(branch_root_str: str) -> frozenset:
    """Handler modules that sit BENEATH everything else in the branch.

    THE ARGUMENT, and it is why this is not just a longer allow-list: a module
    every other module stands on cannot be encapsulated behind one of them.
    Nothing can import it "through" a module entry point, because the entry
    point needs it first.

    WHERE IT CAME FROM. @daemon, 2026-08-31, two adjacent lines in their entry
    point: the json_handler import passed and the module_root import scored the
    file 66%. Both are same-branch handler imports by the branch's own entry
    point, and the handlers guard itself permits exactly this — it blocks
    CROSS-branch imports. The checker was exempting json_handler by NAME rather
    than by the property that makes it fine.

    HOW IT USED TO BE DERIVED, AND WHY THAT STOPPED WORKING. The original read
    the branch's own ``json_handler.py`` and took whatever it imported from
    under ``handlers/``: measured 2026-08-31, 8 of 9 branches carrying the
    resolution cure had json_handler importing it, so the set found it without
    anyone naming a file. DPLAN-0325 removed that basis. Every branch's handler
    is now the one canonical shim, which imports ``aipass.prax`` and nothing
    else — measured 2026-09-04 across all eighteen branches, the old derivation
    returns the EMPTY SET for every one of them. It did not become wrong, it
    became blind, and blind in the silent direction: @daemon reddened on CI
    (f8d7867f) because its entry point is the only one importing the shim
    directly, and the other seventeen were one edit away from the same red.

    WHAT REPLACED IT. The resolution shim is identified by what it PUBLISHES,
    which is the property that made it infrastructure in the first place: it
    has to live under ``handlers/`` to be the one guarded spelling for
    ``Path(__file__)`` on a machine with no readable working directory, and
    every module in the branch resolves through it. A top-level module under
    ``apps/handlers/`` that defines one of :data:`_RESOLUTION_SHIM_FUNCTIONS`
    at module level is that file. Measured 2026-09-04 over the fleet: fifteen
    branches carry one and are found; ``spawn/passport_migration.py`` defines a
    ``repo_root`` of its own and is correctly NOT found, because it publishes
    none of the ratified spellings.

    Deliberately NOT a leaf test ("imports nothing from its own apps/"), which
    was measured first: it blesses ``json_flags.py``, ``metadata.py``,
    ``class_registry.py`` and six others that are ordinary handlers which
    happen to have no local dependencies. Being at the bottom of the import
    graph is not the same as being the thing everything stands on.

    Args:
        branch_root_str: The branch directory, e.g. ``.../src/aipass/daemon``.

    Returns:
        Module basenames (no extension) importable anywhere in the branch.
    """
    handlers_root = Path(branch_root_str) / "apps" / "handlers"
    names: set = set()
    for source in sorted(handlers_root.glob("*.py")):
        if source.name == "__init__.py":
            continue
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:
            # Unreadable is not evidence: the branch keeps the ordinary rule.
            logger.info("encapsulation: cannot read %s for the infrastructure set: %s", source, exc)
            continue
        published = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if published & _RESOLUTION_SHIM_FUNCTIONS:
            names.add(source.stem)
    return frozenset(names)


def _branch_root(module_path: str) -> Optional[Path]:
    """The ``src/aipass/<branch>`` directory above a file, or None."""
    for parent in Path(module_path).resolve().parents:
        if parent.parent.name == "aipass" and (parent / "apps").is_dir():
            return parent
    return None


def _allowed_handler_names(module_path: str) -> frozenset:
    """Default handlers plus whatever this branch's json_handler stands on."""
    branch_root = _branch_root(module_path)
    if branch_root is None:
        return _DEFAULT_HANDLERS
    return _DEFAULT_HANDLERS | _infrastructure_handlers(str(branch_root))


def check_cross_package_imports(
    lines: List[str], module_path: str, file_package: str, bypass_rules: list | None = None
) -> Dict:
    """
    Check for cross-package handler imports within same branch

    BAD (in handlers/standards/): from apps.handlers.json.json_handler import X
    GOOD: Use relative imports or module entry points

    EXCEPTIONS:
    - json_handler is allowed (default handler pattern)
    - Same package relative imports (from .something import X)
    """
    violations = []

    # Allowed default handlers that can be imported anywhere
    allowed_handlers = _allowed_handler_names(module_path)

    in_docstring = False
    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Track docstrings
        if stripped.startswith('"""') or stripped.startswith("'''"):
            quote_marker = '"""' if stripped.startswith('"""') else "'''"
            quote_count = stripped.count(quote_marker)
            if quote_count >= 2:
                continue
            else:
                in_docstring = not in_docstring

        if in_docstring or not stripped or stripped.startswith("#"):
            continue

        # Check for imports
        if not ("from " in stripped or "import " in stripped):
            continue

        # Skip string literals
        if stripped.startswith('"') or stripped.startswith("'"):
            continue
        if '"from ' in stripped or "'from " in stripped:
            continue
        if '"apps.handlers' in stripped or "'apps.handlers" in stripped:
            continue
        if "apps.handlers" in stripped:
            handler_pos = stripped.find("apps.handlers")
            before = stripped[:handler_pos]
            if before.count('"') % 2 == 1 or before.count("'") % 2 == 1:
                continue

        # Skip relative imports (same package)
        if stripped.startswith("from ."):
            continue

        # Extract code part
        code_part = stripped.split("#")[0] if "#" in stripped else stripped

        # Check for handler imports (local, not cross-branch)
        if "apps.handlers" not in code_part:
            continue

        # Skip cross-branch imports (handled by other check)
        imported_branch = extract_branch_from_import(code_part)
        if imported_branch is not None:
            continue

        # Check if bypassed
        if is_bypassed(module_path, "encapsulation", line=i, bypass_rules=bypass_rules):
            continue

        # Extract the handler package being imported
        imported_package = extract_handler_package(code_part)

        if imported_package is None:
            continue

        # Allow same-package imports
        if imported_package == file_package:
            continue

        # Allow default handlers
        is_allowed = False
        for allowed in allowed_handlers:
            if allowed in code_part:
                is_allowed = True
                break

        if is_allowed:
            continue

        # This is a cross-package handler import
        violations.append(
            {"line": i, "code": code_part.strip(), "from_package": imported_package, "to_package": file_package}
        )

    if violations:
        first = violations[0]
        return {
            "name": "Cross-package handler imports",
            "passed": False,
            "message": (
                f"Line {first['line']}: handlers.{first['from_package']} imported from handlers.{first['to_package']}"
            ),
        }

    return {
        "name": "Cross-package handler imports",
        "passed": True,
        "message": "No forbidden cross-package handler imports",
    }


def check_direct_handler_imports(lines: List[str], module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check that non-handler, non-module files don't import handlers directly

    Entry points and other files should use module entry points, not handlers.

    BAD (in api.py): from apps.handlers.openrouter.client import get_response
    GOOD: from apps.modules.openrouter_client import get_response

    EXCEPTIONS:
    - json_handler is allowed (default pattern)
    - file_handler is allowed (default pattern)
    """
    violations = []

    # Allowed default handlers
    allowed_handlers = _allowed_handler_names(module_path)

    in_docstring = False
    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Track docstrings
        if stripped.startswith('"""') or stripped.startswith("'''"):
            quote_marker = '"""' if stripped.startswith('"""') else "'''"
            quote_count = stripped.count(quote_marker)
            if quote_count >= 2:
                continue
            else:
                in_docstring = not in_docstring

        if in_docstring or not stripped or stripped.startswith("#"):
            continue

        # Check for imports
        if not ("from " in stripped or "import " in stripped):
            continue

        # Skip string literals
        if stripped.startswith('"') or stripped.startswith("'"):
            continue
        if '"from ' in stripped or "'from " in stripped:
            continue
        if '"apps.handlers' in stripped or "'apps.handlers" in stripped:
            continue
        if "apps.handlers" in stripped:
            handler_pos = stripped.find("apps.handlers")
            before = stripped[:handler_pos]
            if before.count('"') % 2 == 1 or before.count("'") % 2 == 1:
                continue

        # Extract code part
        code_part = stripped.split("#")[0] if "#" in stripped else stripped

        # Check for handler imports
        if "apps.handlers" not in code_part:
            continue

        # Check if bypassed
        if is_bypassed(module_path, "encapsulation", line=i, bypass_rules=bypass_rules):
            continue

        # Allow default handlers
        is_allowed = False
        for allowed in allowed_handlers:
            if allowed in code_part:
                is_allowed = True
                break

        if is_allowed:
            continue

        # This file shouldn't be importing handlers directly
        violations.append({"line": i, "code": code_part.strip()})

    if violations:
        first = violations[0]
        return {
            "name": "Direct handler imports",
            "passed": False,
            "message": f"Line {first['line']}: Handler imported directly (use module entry point)",
        }

    return {"name": "Direct handler imports", "passed": True, "message": "No direct handler imports from entry point"}
