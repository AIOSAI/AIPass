# =================== AIPass ====================
# Name: json_structure_check.py
# Description: JSON Structure Standards Checker Handler
# Version: 3.4.2
# Created: 2026-03-05
# Modified: 2026-10-24
# =============================================

"""
JSON Structure Standards Checker Handler

Validates three-JSON code wiring in modules and handlers: every .py in apps/modules/ and apps/handlers/
imports json_handler and calls log_operation(); json_handler.py itself is checked for relative paths.
"""

import ast
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

from aipass.prax import logger
from aipass.seedgo.apps.handlers.aipass_standards.check_support import parse
from aipass.seedgo.apps.handlers.aipass_standards.json_handler_check import _is_canonical_shim
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

# APPLIES_TO: a test does not log_operation and should not.
APPLIES_TO = "production"
AUDIT_SCOPE = "all_files"
READS_BRANCH = True

ALLOWED_JSON_SUBDIRS: frozenset[str] = frozenset({"custom_config"})

CUSTOM_CONFIG_DIR = "custom_config"

# The custom_config/ README is scaffolding, not an operator override.
CUSTOM_CONFIG_SKIP_FILES: frozenset[str] = frozenset({"README.md"})

CUSTOM_CONFIG_GUIDE = "Guide: drone @seedgo standard json_structure"


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check if module follows JSON structure standards."""
    path = Path(module_path)

    if is_bypassed(module_path, "json_structure", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "JSON STRUCTURE",
        }

    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "JSON STRUCTURE",
        }

    if path.name == "__init__.py":
        return {
            "passed": True,
            "checks": [
                {
                    "name": "JSON structure check",
                    "passed": True,
                    "message": "__init__.py file (skipped)",
                    "declined": True,
                }
            ],
            "score": 100,
            "standard": "JSON STRUCTURE",
        }

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.info("Cannot read %s: %s", path, e)
        return {
            "passed": False,
            "checks": [{"name": "File readable", "passed": False, "message": f"Error reading file: {e}"}],
            "score": 0,
            "standard": "JSON STRUCTURE",
        }

    path_str = str(path)

    if "json_handler" in path.name and path.parent.name == "json":
        checks = _check_json_handler_config(path, content, bypass_rules)
        passed_count = sum(1 for c in checks if c["passed"])
        total = len(checks)
        score = int((passed_count / total * 100)) if total > 0 else 0
        return {"passed": score >= 75, "checks": checks, "score": score, "standard": "JSON STRUCTURE"}

    in_modules = "apps/modules" in path_str or "apps\\modules" in path_str
    in_handlers = "apps/handlers" in path_str or "apps\\handlers" in path_str

    # Exclude files inside the json/ handler directory itself (they ARE the
    # json infrastructure, not consumers of it)
    if in_handlers and path.parent.name == "json":
        return {
            "passed": True,
            "checks": [
                {
                    "name": "JSON structure check",
                    "passed": True,
                    "message": "JSON handler infrastructure file (not applicable)",
                    "declined": True,
                }
            ],
            "score": 100,
            "standard": "JSON STRUCTURE",
        }

    # --- Declarations-only module: nothing to log, so nothing to ask ---
    if (in_modules or in_handlers) and _declares_no_callable_code(content):
        return {
            "passed": True,
            "checks": [
                {
                    "name": "JSON structure check",
                    "passed": True,
                    "message": (
                        "Declarations only — no functions or methods, so the module performs "
                        "no operations to log (not applicable)"
                    ),
                    "declined": True,
                }
            ],
            "score": 100,
            "standard": "JSON STRUCTURE",
        }

    # --- Pre-logging bootstrap module: importing json_handler here is a cycle ---
    if (in_modules or in_handlers) and _is_prelogging_bootstrap(path, content):
        return {
            "passed": True,
            "checks": [
                {
                    "name": "JSON structure check",
                    "passed": True,
                    "message": (
                        "Pre-logging bootstrap module — reached from the logging chain's own "
                        "imports and holds no aipass import of any kind, so json_handler cannot "
                        "be imported here without a cycle (not applicable)"
                    ),
                    "declined": True,
                }
            ],
            "score": 100,
            "standard": "JSON STRUCTURE",
        }

    if in_modules or in_handlers:
        checks = _check_code_wiring(path, content)
        passed_count = sum(1 for c in checks if c["passed"])
        total = len(checks)
        score = int((passed_count / total * 100)) if total > 0 else 0
        json_handler.log_operation("check_completed", {"file": path_str, "score": score, "standard": "json_structure"})
        return {"passed": passed_count == total, "checks": checks, "score": score, "standard": "JSON STRUCTURE"}

    return {
        "passed": True,
        "checks": [
            {
                "name": "JSON structure check",
                "passed": True,
                "message": "Not in modules/ or handlers/ (not applicable)",
                "declined": True,
            }
        ],
        "score": 100,
        "standard": "JSON STRUCTURE",
    }


def _declares_no_callable_code(content: str) -> bool:
    """True when a module defines no function or method ANYWHERE.

    "Every module must log operations" is about modules that PERFORM operations; pure declarations perform
    none, and both cures (a module-level log_operation, which writes at pytest COLLECTION, or a function added
    only to call it) are worse. ONE method anywhere puts the module back in scope; an unparseable file is not exempt.
    """
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError) as exc:
        logger.info("json_structure: could not parse for the declarations-only test: %s", exc)
        return False
    return not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in ast.walk(tree))


#: How many modules the bootstrap walk will visit before it gives up. The whole
#: fleet's logging chain measures ~100; this is a runaway guard, not a budget.
_BOOTSTRAP_WALK_CAP = 2000


def resolve_relative(module_name: str | None, level: int, package: str | None) -> str | None:
    """Absolute dotted name for a relative import, given the importer's package.

    Public: the resolver is pure name arithmetic and its own unit, so its tests reach it by this name.
    """
    if not package or level <= 0:
        return None
    parts = package.split(".")
    if level - 1 > len(parts):
        return None
    base = parts[: len(parts) - (level - 1)] if level > 1 else parts
    if not base:
        return None
    return ".".join(base + ([module_name] if module_name else []))


def _aipass_imports(content: str, package: str | None = None) -> list[str]:
    """Every ``aipass.*`` module name this source imports, at any nesting depth.

    Function-level imports count: a module reaching aipass only from inside a function has still taken the
    dependency. Relative imports count when ``package`` is supplied; None keeps the absolute-only behaviour
    the "holds no aipass import" clause wants for a file it cannot place.
    """
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError) as exc:
        logger.info("json_structure: could not parse for the bootstrap-chain walk: %s", exc)
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.append(node.module)
                names.extend(f"{node.module}.{alias.name}" for alias in node.names)
                continue
            resolved = resolve_relative(node.module, node.level, package)
            if resolved:
                names.append(resolved)
                names.extend(f"{resolved}.{alias.name}" for alias in node.names)
    return [name for name in names if name.split(".")[0] == "aipass"]


def _aipass_source_root(path: Path) -> Path | None:
    """The ``src/aipass`` directory above this file, or None if it is not there.

    None means no exemption: a file we cannot place in the fleet's import graph
    is measured by the ordinary rule.
    """
    for parent in path.resolve().parents:
        if parent.name == "aipass" and (parent / "prax").is_dir():
            return parent
    return None


def _module_file(module_name: str, source_root: Path) -> Path | None:
    """Resolve a dotted ``aipass.*`` name to the file it would import."""
    candidate = source_root.parent / Path(*module_name.split("."))
    if (candidate / "__init__.py").is_file():
        return candidate / "__init__.py"
    flat = candidate.with_suffix(".py")
    return flat if flat.is_file() else None


def _module_name(path: Path, source_root: Path) -> str | None:
    """The dotted name a file is imported under, or None if it is outside the tree."""
    try:
        relative = path.resolve().relative_to(source_root.parent)
    except ValueError as exc:
        logger.info("json_structure: file is outside the resolved source root: %s", exc)
        return None
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) if parts else None


@lru_cache(maxsize=8)
def _bootstrap_chain(source_root_str: str) -> frozenset:
    """Every module the logging substrate imports, transitively.

    Seeded from the system logger and every branch's json_handler, the two things this standard tells a
    module to import: anything they reach cannot import them back without a cycle. Ancestor packages are
    deliberately absent (walking them exempted helpers that have a working logger). Statically walked, so a
    dynamic importlib hop leaves the set SHORT, the safe direction: an over-long set would hand out exemptions.
    """
    source_root = Path(source_root_str)
    branches = [d.name for d in source_root.iterdir() if (d / "apps").is_dir()]
    queue = ["aipass.prax.apps.modules.logger"]
    queue += [f"aipass.{name}.apps.handlers.json.json_handler" for name in branches]
    # Branch-owned operation-logging seams are substrate too: what a seam imports is beneath it.
    for name in branches:
        for seam_file in _seam_files(source_root / name):
            seam_module = _module_name(seam_file, source_root)
            if seam_module is not None:
                queue.append(seam_module)

    seen: set = set()
    while queue and len(seen) < _BOOTSTRAP_WALK_CAP:
        module_name = queue.pop()
        if module_name in seen:
            continue
        module_file = _module_file(module_name, source_root)
        if module_file is None:
            continue
        seen.add(module_name)
        # The importing module's PACKAGE, so its relative imports resolve (a package __init__ is its own).
        package = module_name if module_file.name == "__init__.py" else module_name.rsplit(".", 1)[0]
        try:
            queue.extend(_aipass_imports(module_file.read_text(encoding="utf-8", errors="ignore"), package))
        except OSError as exc:
            logger.info("json_structure: unreadable module in the bootstrap walk: %s", exc)
    return frozenset(seen)


def _is_prelogging_bootstrap(path: Path, content: str) -> bool:
    """True for a module that sits BENEATH the logging system it would have to call.

    Two clauses, both measured: (1) the module holds no aipass import of any kind, and (2) the logging
    substrate's own imports reach it. Either alone exempts too much; the pair names modules where wiring
    log_operation() would put a file write on every branch's import path, firing during pytest COLLECTION.
    """
    try:
        ast.parse(content)
    except (SyntaxError, ValueError) as exc:
        # An unreadable file is not a bootstrap module: [] from _aipass_imports() would buy the exemption.
        logger.info("json_structure: unparseable, so not eligible for the bootstrap exemption: %s", exc)
        return False
    if _aipass_imports(content):
        return False
    source_root = _aipass_source_root(path)
    if source_root is None:
        return False
    module_name = _module_name(path, source_root)
    return module_name is not None and module_name in _bootstrap_chain(str(source_root))


def _branch_root(path: Path) -> Path | None:
    """The branch directory a module lives in, or None if it is outside one."""
    source_root = _aipass_source_root(path)
    if source_root is None:
        return None
    try:
        relative = path.resolve().relative_to(source_root)
    except ValueError:
        return None
    return source_root / relative.parts[0] if relative.parts else None


@lru_cache(maxsize=64)
def _operation_log_seams(branch_root: str) -> frozenset[str]:
    """Modules in this branch that ARE a branch-owned operation-logging seam.

    The json shim is byte-identical fleet-wide, so a branch with a different audit-trail shape owns it in a
    module of its own. Recognised, narrowly: the file DEFINES ``log_operation`` AND builds it on a logging
    primitive imported from ``aipass.prax``; the branch's own shim is excluded (check 2 already accepts it).
    """
    return frozenset(f.stem for f in _seam_files(Path(branch_root)))


def _seam_files(branch_root: Path) -> list[Path]:
    """Every file in this branch that qualifies as an operation-logging seam."""
    apps = branch_root / "apps"
    if not apps.is_dir():
        return []
    found: list[Path] = []
    for candidate in sorted(apps.rglob("*.py")):
        if candidate.name == "json_handler.py":
            continue
        try:
            source = candidate.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            logger.info("json_structure: unreadable while scanning for log seams: %s", exc)
            continue
        if _is_operation_log_seam(source):
            found.append(candidate)
    return found


def _is_operation_log_seam(content: str) -> bool:
    """True when this file IS a branch-owned operation-logging seam.

    The seam is the substrate, not a consumer: asking it to call ``log_operation`` is asking it to log through
    itself. Same two conditions as ``_operation_log_seams``, so a file cannot be a seam for one check only.
    """
    if "def log_operation(" not in content:
        return False
    return bool(re.search(r"from\s+aipass\.prax\s+import\s+[^\n]*(?:append_jsonl|json_handler)", content))


def _seam_logging(path: Path, content: str) -> str | None:
    """The branch-owned seam this module logs its operations through, if any."""
    root = _branch_root(path)
    if root is None:
        return None
    for seam in sorted(_operation_log_seams(str(root))):
        calls = f"{seam}.log_operation(" in content
        imported = re.search(rf"import\s+[^\n]*\b{re.escape(seam)}\b", content)
        if calls and imported:
            return seam
    return None


def _json_handler_wiring(content: str) -> tuple[bool, bool]:
    """(imports json_handler, calls json_handler.log_operation), read from code: a docstring naming either is prose."""
    tree = parse(content, tag="json_structure")
    if tree is None:
        return False, False
    imports = any(
        isinstance(node, (ast.Import, ast.ImportFrom))
        and any((alias.asname or alias.name).split(".")[-1] == "json_handler" for alias in node.names)
        for node in ast.walk(tree)
    )
    calls = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "log_operation"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "json_handler"
        for node in ast.walk(tree)
    )
    return imports, calls


def _check_code_wiring(_path: Path, content: str) -> List[Dict]:
    """Check that a module/handler file imports json_handler and calls log_operation(); two check dicts."""
    if _is_operation_log_seam(content):
        return [
            {
                "name": "json_handler import",
                "passed": True,
                "message": "This module IS the branch's operation-logging seam (built on aipass.prax)",
            },
            {
                "name": "log_operation call",
                "passed": True,
                "message": "Defines log_operation — the substrate does not log through itself",
            },
        ]

    checks: List[Dict] = []

    # A module that logs through a branch-owned seam imports the SEAM, not the shim: the two checks are one
    # requirement (this module's operations reach a log), so they answer together.
    seam = _seam_logging(_path, content)
    imports_shim, calls_log = _json_handler_wiring(content)
    has_import = seam is not None or imports_shim
    if seam is not None:
        import_message = f"Imports this branch's {seam} logging seam"
    elif has_import:
        import_message = "Imports json_handler"
    else:
        import_message = (
            "Missing json_handler import — add: from aipass.<branch>.apps.handlers.json import json_handler"
        )
    checks.append(
        {
            "name": "json_handler import",
            "passed": has_import,
            "message": import_message,
        }
    )

    # The requirement is that operations ARE logged, never that they are logged in one spelling.
    has_log_operation = calls_log or seam is not None
    seam = None if calls_log else seam
    if seam is not None:
        log_message = f"Logs operations through this branch's {seam} seam (built on aipass.prax)"
    elif has_log_operation:
        log_message = "Calls json_handler.log_operation()"
    else:
        log_message = "Missing json_handler.log_operation() call — every module/handler must log operations"
    checks.append(
        {
            "name": "log_operation call",
            "passed": has_log_operation,
            "message": log_message,
        }
    )

    return checks


def _check_json_handler_config(_handler_path: Path, content: str, _bypass_rules: list | None = None) -> List[Dict]:
    """Check json_handler.py: no Path.home(), relative resolution, no json_templates, no load_template()."""
    checks: List[Dict] = []

    has_path_home = bool(re.search(r"Path\.home\(\)", content))
    # Only a _ROOT built on Path.home() is flagged; _ROOT = Path(__file__).resolve()... is pip-safe.
    has_branch_root = False
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if re.search(r"\w+_ROOT\s*=", stripped) and "Path.home()" in stripped:
            has_branch_root = True
            break

    if has_path_home or has_branch_root:
        issues = []
        if has_path_home:
            issues.append("Path.home()")
        if has_branch_root:
            issues.append("hardcoded _ROOT constant")
        checks.append(
            {
                "name": "No absolute paths",
                "passed": False,
                "message": f"Found {', '.join(issues)} — pip packages should use relative paths",
            }
        )
    else:
        checks.append(
            {
                "name": "No absolute paths",
                "passed": True,
                "message": "No hardcoded absolute paths (correct for pip packages)",
            }
        )

    # A shim that binds the fleet json service resolves nothing itself: the service derives the branch root
    # from the shim's own __file__ (deliberately WITHOUT resolve()), so the canonical shim passes by hash.
    binds_the_json_service = _is_canonical_shim(content)
    resolves_here = bool(
        re.search(r"Path\(__file__\)", content)
        or re.search(r"\.resolve\(\)", content)
        or re.search(r"\.parent", content)
    )
    has_relative = binds_the_json_service or resolves_here

    if binds_the_json_service:
        resolution_message = "Delegates path resolution to the one json service (no absolute path can enter)"
    elif resolves_here:
        resolution_message = "Uses relative path resolution (Path(__file__).parent)"
    else:
        resolution_message = "Missing relative path resolution — should use Path(__file__).resolve().parent"

    checks.append(
        {
            "name": "Relative path resolution",
            "passed": has_relative,
            "message": resolution_message,
        }
    )

    # The standard: "The CODE PATTERN is the template -- no json_templates/ directory".
    has_template_dir = False
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "json_templates" in stripped:
            has_template_dir = True
            break

    checks.append(
        {
            "name": "No template directory",
            "passed": not has_template_dir,
            "message": "No json_templates/ references (correct — code is the template)"
            if not has_template_dir
            else "References json_templates/ directory — use auto-create from code defaults, not file templates",
        }
    )

    # A load_template() that reads from files violates the auto-create principle.
    has_load_template = bool(re.search(r"def\s+load_template\s*\(", content))

    checks.append(
        {
            "name": "No file-based templates",
            "passed": not has_load_template,
            "message": "No load_template() function (correct — uses inline code defaults)"
            if not has_load_template
            else "Has load_template() function — standard requires inline code defaults, not file-based templates",
        }
    )

    return checks


def _find_json_dir(branch_path: str) -> Path | None:
    """Locate {branch}_json/ under a branch root."""
    bp = Path(branch_path)
    json_dir = bp / f"{bp.name}_json"
    return json_dir if json_dir.is_dir() else None


def _check_json_dir_structure(branch_path: str, bypass_rules: list | None = None) -> list[dict]:
    """Validate {branch}_json/ has no unsanctioned subdirectories.

    Allowed: custom_config/ (operator-editable config).
    Hidden dirs (starting with '.') are ignored (e.g. .archive).
    Bypassed subdirs (via .seedgo/bypass.json) are also allowed.
    """
    json_dir = _find_json_dir(branch_path)
    if json_dir is None:
        return []

    bp = Path(branch_path)
    violations = []
    for child in sorted(json_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue
        if child.name in ALLOWED_JSON_SUBDIRS:
            continue
        relative = f"{bp.name}_json/{child.name}"
        if is_bypassed(relative, "json_structure", bypass_rules=bypass_rules):
            continue
        violations.append(
            {
                "file": child.name,
                "path": str(child),
                "score": 0,
                "issues": [f"Unsanctioned subdir '{child.name}/' under {json_dir.name}/ — only custom_config/ allowed"],
                "message": (
                    f"Unsanctioned subdir '{child.name}/' under {json_dir.name}/ — only custom_config/ allowed"
                ),
            }
        )
    return violations


def check_branch_post(branch_path: str, bypass_rules: list | None = None) -> tuple[list, list]:
    """Post-audit check: validate {branch}_json/ directory structure."""
    # No json dir is nothing to score: a 100 here would lift the branch average for free.
    if _find_json_dir(branch_path) is None:
        return [], []
    violations = _check_json_dir_structure(branch_path, bypass_rules=bypass_rules)
    scores = [0] if violations else [100]
    return violations, scores


def _custom_config_files(branch_path: str) -> list[str]:
    """Filenames the operator put in {branch}_json/custom_config/ (README excluded)."""
    json_dir = _find_json_dir(branch_path)
    if json_dir is None:
        return []
    custom_config = json_dir / CUSTOM_CONFIG_DIR
    if not custom_config.is_dir():
        return []
    return sorted(p.name for p in custom_config.iterdir() if p.is_file() and p.name not in CUSTOM_CONFIG_SKIP_FILES)


def check_branch_info(branch_path: str) -> list[str]:
    """Non-scored signpost lines for the json_structure standard.

    custom_config/ is operator-owned: seedgo never reads its contents, only lists filenames on the info
    channel, so a live override is visible and can never reach a score.
    """
    files = _custom_config_files(branch_path)
    if not files:
        return []
    noun = "file" if len(files) == 1 else "files"
    return [
        f"{Path(branch_path).name}_json/{CUSTOM_CONFIG_DIR}/: {len(files)} operator {noun} "
        f"({', '.join(files)}) — content not audited. {CUSTOM_CONFIG_GUIDE}"
    ]
