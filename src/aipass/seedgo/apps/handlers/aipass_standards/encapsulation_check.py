# =================== AIPass ====================
# Name: encapsulation_check.py
# Description: Handler Encapsulation Standards Checker
# Version: 1.4.2
# Created: 2026-03-05
# Modified: 2026-10-30
# =============================================

"""Handler Encapsulation Standards Checker"""

import ast
import re
import json
from functools import lru_cache
from pathlib import Path
from typing import AbstractSet, Dict, List, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.aipass_standards.applicability import is_test_path
from aipass.seedgo.apps.handlers.aipass_standards.prose_lines import UnparseableSource, classify, hash_lines
from aipass.seedgo.apps.handlers.aipass_standards.string_imports import STRING_IMPORT_NOTE, iter_string_imports

AUDIT_SCOPE = "all_files"
READS_BRANCH = True
# A test file is asked ONE thing: reaching into its own branch's internals is what a
# unit test is for, so a test is judged only on another branch's handlers (check_test_file).
APPLIES_TO = "everywhere"

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
    """Infer branch info from filesystem path when registry is unavailable."""
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
    """Extract branch name from an import statement"""
    match = re.search(r"from\s+(\w+)\.apps\.handlers", import_line)
    if match:
        return match.group(1)

    # Handlers anywhere under a branch's tree are that branch's (aipass.skills.lib.telegram).
    match = re.search(r"(?:from|import)\s+aipass\.(\w+)\.(?:\w+\.)*?apps\.handlers", import_line)
    if match:
        return match.group(1)

    match = re.search(r"import\s+(\w+)\.apps\.handlers", import_line)
    if match:
        return match.group(1)

    return None


def extract_handler_package(import_line: str) -> Optional[str]:
    """Extract the handler package name from an import"""
    match = re.search(r"apps\.handlers\.(\w+)", import_line)
    if match:
        return match.group(1)
    return None


def _posix(file_path: str) -> str:
    """The path as a string with forward slashes, whatever host handed it in.

    The checks below search the path for "apps/handlers/" and "apps/modules/";
    a Windows path with backslashes matches neither.
    """
    return str(file_path).replace("\\", "/")


def get_file_handler_package(file_path: str) -> Optional[str]:
    """Get the handler package a file belongs to"""
    path_str = _posix(file_path)

    if "apps/handlers/" not in path_str:
        return None

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


#: The conviction for the eager line, dated to the commit that planted it.
EAGER_HANDLERS_MESSAGE = (
    "apps/__init__.py imports handlers: the fence sees its own package as every caller (2026-04-25)"
)


def _imports_handlers(node: ast.stmt) -> bool:
    """Whether one statement imports a handlers package or something under it."""
    if isinstance(node, ast.Import):
        return any(".apps.handlers" in alias.name for alias in node.names)
    if not isinstance(node, ast.ImportFrom):
        return False
    module = node.module or ""
    names = {alias.name for alias in node.names}
    if node.level:
        return module.split(".")[0] == "handlers" or (not module and "handlers" in names)
    return ".apps.handlers" in module or (module.endswith(".apps") and "handlers" in names)


def _apps_package_imports_handlers(apps_init: Path) -> Optional[Dict]:
    """The failing guard check when apps/__init__.py imports handlers, else None.

    Read from the parse tree, so a docstring that names the line is prose.
    An unreadable or unparseable package fails the check by its own message:
    a file this check could not read is not evidence the line is absent.
    """
    if not apps_init.exists():
        return None
    try:
        tree = ast.parse(apps_init.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError) as exc:
        logger.info("encapsulation: cannot read %s: %s", apps_init, exc)
        return {"name": "Handler security guard", "passed": False, "message": f"Cannot read apps/__init__.py: {exc}"}
    if any(_imports_handlers(node) for node in ast.walk(tree) if isinstance(node, ast.stmt)):
        return {"name": "Handler security guard", "passed": False, "message": EAGER_HANDLERS_MESSAGE}
    return None


def _calls_the_guard(content: str) -> bool:
    """Whether handlers/__init__.py calls _guard_branch_access() at module level (guard v2)."""
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError) as exc:
        logger.info("encapsulation: handlers/__init__.py unparseable, v2 marker unseen: %s", exc)
        return False
    return any(
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "_guard_branch_access"
        for node in tree.body
    )


def check_handler_guard(module_path: str, bypass_rules: list | None = None) -> Optional[Dict]:
    """Check that a branch's handlers/__init__.py contains a security guard."""
    branch_path = _resolve_branch_path(module_path)
    if branch_path is None:
        return None

    branch_key = str(branch_path)

    if branch_key in _handler_guard_cache:
        return _handler_guard_cache[branch_key]

    init_path = branch_path / "apps" / "handlers" / "__init__.py"
    if is_bypassed(str(init_path), "encapsulation", bypass_rules=bypass_rules):
        result = {"name": "Handler security guard", "passed": True, "message": "Handler guard check bypassed"}
        _handler_guard_cache[branch_key] = result
        return result

    handlers_dir = branch_path / "apps" / "handlers"
    if not handlers_dir.is_dir():
        _handler_guard_cache[branch_key] = None
        return None

    # An apps/__init__.py that imports handlers makes itself the first frame the guard
    # sees, so every caller reads as kin.
    eager = _apps_package_imports_handlers(branch_path / "apps" / "__init__.py")
    if eager is not None:
        _handler_guard_cache[branch_key] = eager
        return eager

    if not init_path.exists():
        result = {
            "name": "Handler security guard",
            "passed": False,
            "message": "Missing handlers/__init__.py — no handler security guard",
        }
        _handler_guard_cache[branch_key] = result
        return result

    try:
        content = init_path.read_text(encoding="utf-8")
    except Exception:
        logger.info("Cannot read handlers/__init__.py at %s", init_path)
        result = {"name": "Handler security guard", "passed": False, "message": "Cannot read handlers/__init__.py"}
        _handler_guard_cache[branch_key] = result
        return result

    code_lines = [ln for ln in content.split("\n") if ln.strip() and not ln.strip().startswith("#")]

    if _calls_the_guard(content):
        result = {
            "name": "Handler security guard",
            "passed": True,
            "message": "Handler security guard present (module-level _guard_branch_access() call)",
        }
    elif len(code_lines) < 10:
        result = {
            "name": "Handler security guard",
            "passed": False,
            "message": "Missing handler security guard — cross-branch imports unprotected",
        }
    else:
        result = {
            "name": "Handler security guard",
            "passed": False,
            "message": "handlers/__init__.py has code but no recognized security guard pattern",
        }

    _handler_guard_cache[branch_key] = result
    return result


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check if file respects handler encapsulation"""
    checks = []
    path = Path(module_path)

    if is_bypassed(module_path, "encapsulation", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "ENCAPSULATION",
        }

    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "ENCAPSULATION",
        }

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

    # A test is kin to its own branch only: one check, the cross-branch one
    if is_test_path(module_path):
        test_check = check_test_file(content, lines, module_path, bypass_rules)
        score = 100 if test_check["passed"] else 0
        json_handler.log_operation(
            "check_completed", {"file": str(module_path), "score": score, "standard": "encapsulation"}
        )
        return {"passed": test_check["passed"], "checks": [test_check], "score": score, "standard": "ENCAPSULATION"}

    file_branch = get_branch_from_path(module_path)
    file_branch_name = file_branch.get("name", "").lower() if file_branch else None
    file_handler_package = get_file_handler_package(module_path)
    is_handler_file = file_handler_package is not None
    is_module_file = "apps/modules/" in _posix(module_path)

    cross_branch_check = check_cross_branch_imports(lines, module_path, file_branch_name, bypass_rules)
    checks.append(cross_branch_check)

    if is_handler_file:
        cross_package_check = check_cross_package_imports(lines, module_path, file_handler_package, bypass_rules)
        checks.append(cross_package_check)

    if not is_handler_file and not is_module_file:
        direct_import_check = check_direct_handler_imports(lines, module_path, bypass_rules)
        checks.append(direct_import_check)

    guard_check = check_handler_guard(module_path, bypass_rules)
    if guard_check is not None:
        checks.append(guard_check)

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


def _not_import_lines(lines: List[str]) -> AbstractSet[int]:
    """Docstring, comment and string-body lines: none of them can hold an import statement."""
    source = "\n".join(lines)
    try:
        kinds = classify(source)
    except UnparseableSource as exc:
        logger.info("encapsulation: unparseable, comment lines only skipped: %s", exc)
        return hash_lines(source)
    return kinds.prose | kinds.string_bodies


def check_cross_branch_imports(
    lines: List[str], module_path: str, file_branch: Optional[str], bypass_rules: list | None = None
) -> Dict:
    """Check for cross-branch handler imports"""
    violations = []

    skipped = _not_import_lines(lines)
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if i in skipped or not stripped:
            continue

        if not ("from " in stripped or "import " in stripped):
            continue

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

        code_part = stripped.split("#")[0] if "#" in stripped else stripped

        if "apps.handlers" not in code_part:
            continue

        if is_bypassed(module_path, "encapsulation", line=i, bypass_rules=bypass_rules):
            continue

        imported_branch = extract_branch_from_import(code_part)

        if imported_branch is None:
            # Local import (from apps.handlers.X) - will be caught by cross-package check
            continue

        if file_branch and imported_branch.lower() == file_branch.lower():
            continue

        violations.append(
            {
                "line": i,
                "code": code_part.strip(),
                "from_branch": imported_branch,
                "to_branch": file_branch or "unknown",
            }
        )

    # A target named as a call's string is an import too; the parse tree tells an import
    # argument from prose, where the line reader above skips quoted handlers by design.
    violations.extend(_string_violations(lines, module_path, file_branch, bypass_rules))
    violations.sort(key=lambda v: v["line"])

    if violations:
        return {"name": "Cross-branch handler imports", "passed": False, "message": _conviction(violations[0])}

    return {
        "name": "Cross-branch handler imports",
        "passed": True,
        "message": "No cross-branch handler imports detected",
    }


def _conviction(violation: Dict) -> str:
    """The message for a cross-branch violation; a string import quotes its line."""
    head = f"Line {violation['line']}: {violation['from_branch']}.apps.handlers imported"
    if violation.get("string"):
        return f"{head} {STRING_IMPORT_NOTE} (use modules entry point): {violation['code']}"
    return f"{head} (use modules entry point)"


def _target_branch(target: str) -> str:
    """The branch a dotted handlers target belongs to.

    ``aipass.<branch>.`` names it whatever nests below: skills' telegram lives at
    ``aipass.skills.lib.telegram.apps.handlers`` and is skills' own, where the
    segment before ``apps`` would answer "telegram".
    """
    parts = target.split(".")
    if parts[0] == "aipass" and len(parts) > 1:
        return parts[1]
    return target.split(".apps.handlers", 1)[0].split(".")[-1]


def _is_foreign(target: str, file_branch: Optional[str]) -> bool:
    """Whether a dotted handlers target names a branch other than the file's own."""
    return not (file_branch and _target_branch(target).lower() == file_branch.lower())


def _violation(lines: List[str], lineno: int, target: str, file_branch: Optional[str], string: bool) -> Dict:
    """One cross-branch violation row, the shape check_cross_branch_imports reports."""
    return {
        "line": lineno,
        "code": lines[lineno - 1].strip() if 0 < lineno <= len(lines) else target,
        "from_branch": _target_branch(target),
        "to_branch": file_branch or "unknown",
        "string": string,
    }


def _string_violations(
    lines: List[str], module_path: str, file_branch: Optional[str], bypass_rules: list | None
) -> List[Dict]:
    """Cross-branch handler targets a file names as a call's string argument."""
    return [
        _violation(lines, lineno, target, file_branch, string=True)
        for lineno, target in iter_string_imports("\n".join(lines))
        if _is_foreign(target, file_branch)
        and not is_bypassed(module_path, "encapsulation", line=lineno, bypass_rules=bypass_rules)
    ]


def _import_violations(
    content: str, lines: List[str], module_path: str, file_branch: Optional[str], bypass_rules: list | None
) -> List[Dict]:
    """Cross-branch handler imports read from import NODES, never from lines.

    The test lane reads the parse tree because a test file carries source
    fixtures: a handlers import inside a triple-quoted string is prose there,
    and the line reader cannot see the quotes that open three lines above.
    """
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError) as exc:
        logger.info("encapsulation: unparseable test file %s: %s", module_path, exc)
        return [
            {
                "line": getattr(exc, "lineno", None) or 0,
                "code": "unparseable",
                "from_branch": "unknown",
                "to_branch": "?",
            }
        ]
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and not node.level:
            targets = [node.module or ""]
        elif isinstance(node, ast.Import):
            targets = [alias.name for alias in node.names]
        else:
            continue
        for target in targets:
            if ".apps.handlers" in target and _is_foreign(target, file_branch):
                if not is_bypassed(module_path, "encapsulation", line=node.lineno, bypass_rules=bypass_rules):
                    found.append(_violation(lines, node.lineno, target, file_branch, string=False))
    return found


def check_test_file(content: str, lines: List[str], module_path: str, bypass_rules: list | None = None) -> Dict:
    """A test is kin to its own branch only (DPLAN-0404 leg 1).

    Reaching into a module's internals is what a unit test is for; a test that imports
    or patches ANOTHER branch's handlers is a cross-branch caller like any product file.
    """
    branch_root = _branch_root(module_path)
    file_branch = branch_root.name if branch_root else None
    violations = _import_violations(content, lines, module_path, file_branch, bypass_rules)
    violations.extend(_string_violations(lines, module_path, file_branch, bypass_rules))
    violations.sort(key=lambda v: v["line"])
    if violations:
        return {"name": "Cross-branch handler imports", "passed": False, "message": _conviction(violations[0])}
    return {
        "name": "Cross-branch handler imports",
        "passed": True,
        "message": "No cross-branch handler imports detected",
    }


#: Handlers every module may import by name, because a branch cannot function
#: without them. Anything else must EARN the exemption structurally (_infrastructure_handlers).
_DEFAULT_HANDLERS = frozenset({"json_handler", "file_handler"})


#: The fleet-ratified spellings of the guarded ``__file__`` / repo-root
#: resolution shim. A module that DEFINES one of these at module level IS that
#: shim; a module that merely calls it is not. Names, not files: the file name varies by branch.
_RESOLUTION_SHIM_FUNCTIONS = frozenset({"module_file", "find_repo_root", "source_root", "resolved_file"})


@lru_cache(maxsize=32)
def _infrastructure_handlers(branch_root_str: str) -> frozenset:
    """Handler modules that sit BENEATH everything else in the branch.

    A module every other module stands on cannot be encapsulated behind one of them: the
    entry point needs it first. Reference: encapsulation.md (allowed handler imports).
    """
    handlers_root = Path(branch_root_str) / "apps" / "handlers"
    names: set = set()
    for source in sorted(handlers_root.glob("*.py")):
        if source.name == "__init__.py":
            continue
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError) as exc:
            # Unreadable is not evidence: the branch keeps the ordinary rule.
            logger.info("encapsulation: cannot read %s for the infrastructure set: %s", source, exc)
            continue
        published = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if published & _RESOLUTION_SHIM_FUNCTIONS:
            names.add(source.stem)
    return frozenset(names)


def _branch_root(module_path: str) -> Optional[Path]:
    """The ``src/aipass/<branch>`` directory above a file, else the nearest package holding ``apps/``, or None.

    The second reading is a project branch (``beo/beo``); it comes second so a nested
    ``aipass.skills.lib.telegram`` still answers skills, not telegram.
    """
    parents = Path(module_path).resolve().parents
    for parent in parents:
        if parent.parent.name == "aipass" and (parent / "apps").is_dir():
            return parent
    for parent in parents:
        if (parent / "apps").is_dir() and (parent / "__init__.py").is_file():
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
    """Check for cross-package handler imports within same branch"""
    violations = []

    allowed_handlers = _allowed_handler_names(module_path)

    skipped = _not_import_lines(lines)
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if i in skipped or not stripped:
            continue

        if not ("from " in stripped or "import " in stripped):
            continue

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

        if stripped.startswith("from ."):
            continue

        code_part = stripped.split("#")[0] if "#" in stripped else stripped

        if "apps.handlers" not in code_part:
            continue

        imported_branch = extract_branch_from_import(code_part)
        if imported_branch is not None:
            continue

        if is_bypassed(module_path, "encapsulation", line=i, bypass_rules=bypass_rules):
            continue

        imported_package = extract_handler_package(code_part)

        if imported_package is None:
            continue

        if imported_package == file_package:
            continue

        # Whole names: profile_handler is not file_handler.
        if allowed_handlers & set(re.findall(r"\w+", code_part)):
            continue

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
    """Check that non-handler, non-module files don't import handlers directly"""
    violations = []

    allowed_handlers = _allowed_handler_names(module_path)

    skipped = _not_import_lines(lines)
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if i in skipped or not stripped:
            continue

        if not ("from " in stripped or "import " in stripped):
            continue

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

        code_part = stripped.split("#")[0] if "#" in stripped else stripped

        if "apps.handlers" not in code_part:
            continue

        if is_bypassed(module_path, "encapsulation", line=i, bypass_rules=bypass_rules):
            continue

        # Whole names: profile_handler is not file_handler.
        if allowed_handlers & set(re.findall(r"\w+", code_part)):
            continue

        violations.append({"line": i, "code": code_part.strip()})

    if violations:
        first = violations[0]
        return {
            "name": "Direct handler imports",
            "passed": False,
            "message": f"Line {first['line']}: Handler imported directly (use module entry point)",
        }

    return {"name": "Direct handler imports", "passed": True, "message": "No direct handler imports from entry point"}
