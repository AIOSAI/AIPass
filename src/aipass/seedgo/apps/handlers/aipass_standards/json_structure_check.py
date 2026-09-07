# =================== AIPass ====================
# Name: json_structure_check.py
# Description: JSON Structure Standards Checker Handler
# Version: 3.3.0
# Created: 2026-03-05
# Modified: 2026-08-07
# =============================================

"""
JSON Structure Standards Checker Handler

Validates three-JSON code wiring in modules and handlers.

For every .py file in apps/modules/ and apps/handlers/:
  1. Must import json_handler from the branch's handlers/json package
  2. Must call json_handler.log_operation() at least once

For json_handler.py itself (in a json/ directory):
  - Validates handler config (relative paths, no hardcoded absolutes)

Entry points and other files outside modules/handlers are skipped.
"""

import ast
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

from aipass.prax import logger
from aipass.seedgo.apps.handlers.aipass_standards.json_handler_check import _is_canonical_shim
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

# Audit scope: scan every .py file, not just entry point
AUDIT_SCOPE = "all_files"

ALLOWED_JSON_SUBDIRS: frozenset[str] = frozenset({"custom_config"})

CUSTOM_CONFIG_DIR = "custom_config"

# The custom_config/ README is scaffolding, not an operator override.
CUSTOM_CONFIG_SKIP_FILES: frozenset[str] = frozenset({"README.md"})

CUSTOM_CONFIG_GUIDE = "Guide: drone @seedgo standard json_structure"


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check if module follows JSON structure standards.

    Routing:
      a. json_handler.py in a json/ dir  -> validate handler config
      b. File in apps/modules/           -> check code wiring
      c. File in apps/handlers/          -> check code wiring
      d. Everything else (entry points)  -> skip (not applicable)

    Args:
        module_path: Path to Python module to check
        bypass_rules: Optional bypass rules

    Returns:
        dict with passed, checks, score, standard keys
    """
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

    # Skip __init__.py files
    if path.name == "__init__.py":
        return {
            "passed": True,
            "checks": [{"name": "JSON structure check", "passed": True, "message": "__init__.py file (skipped)"}],
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

    # --- Case (a): json_handler.py in a json/ directory ---
    if "json_handler" in path.name and path.parent.name == "json":
        checks = _check_json_handler_config(path, content, bypass_rules)
        passed_count = sum(1 for c in checks if c["passed"])
        total = len(checks)
        score = int((passed_count / total * 100)) if total > 0 else 0
        return {"passed": score >= 75, "checks": checks, "score": score, "standard": "JSON STRUCTURE"}

    # --- Determine if the file is in modules/ or handlers/ ---
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
                }
            ],
            "score": 100,
            "standard": "JSON STRUCTURE",
        }

    # --- Cases (b) and (c): code wiring check ---
    if in_modules or in_handlers:
        checks = _check_code_wiring(path, content)
        passed_count = sum(1 for c in checks if c["passed"])
        total = len(checks)
        score = int((passed_count / total * 100)) if total > 0 else 0
        return {"passed": passed_count == total, "checks": checks, "score": score, "standard": "JSON STRUCTURE"}

    # --- Case (d): file outside modules/ and handlers/ (entry point, etc.) ---
    return {
        "passed": True,
        "checks": [
            {"name": "JSON structure check", "passed": True, "message": "Not in modules/ or handlers/ (not applicable)"}
        ],
        "score": 100,
        "standard": "JSON STRUCTURE",
    }


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _declares_no_callable_code(content: str) -> bool:
    """True when a module defines no function or method ANYWHERE.

    "Every module/handler must log operations" is a rule about modules that
    PERFORM operations. A file of pure exception or dataclass declarations
    performs none, so the check was asking a question the file cannot answer —
    and the only two ways to answer it were both worse than the violation
    (@drone, 2026-08-31): restore a module-level log_operation, which is the
    import-time-write defect that fires during pytest COLLECTION where no
    fixture can intercept it; or add a function to a file of class definitions
    solely so there is somewhere to call log_operation from.

    Deliberately keyed on callable code and nothing else. ONE method anywhere —
    including in a class body — puts the module back in scope, because a method
    is somewhere an operation can happen. Constants and dataclass fields do not
    buy the exemption back; data is still declarations.

    An unparseable file is NOT exempt: a syntax error is not evidence of purity,
    and answering "no callable code" for a file we could not read would hand out
    the exemption on ignorance.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        logger.info("json_structure: could not parse for the declarations-only test: %s", exc)
        return False
    return not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in ast.walk(tree))


#: How many modules the bootstrap walk will visit before it gives up. The whole
#: fleet's logging chain measures ~100; this is a runaway guard, not a budget.
_BOOTSTRAP_WALK_CAP = 2000


def _resolve_relative(module_name: str | None, level: int, package: str | None) -> str | None:
    """Absolute dotted name for a relative import, given the importer's package.

    ``from ..paths import module_file`` inside
    ``aipass.canary.apps.handlers.json.json_handler`` is
    ``aipass.canary.apps.handlers.paths`` — a perfectly static fact the walk was
    throwing away.

    Args:
        module_name: The ``module`` of an ImportFrom, or None for ``from . import x``.
        level: Number of leading dots.
        package: Dotted package the importing file lives in, or None if unknown.

    Returns:
        The absolute dotted name, or None when it cannot be resolved.
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

    Function-level imports count. A module that reaches aipass only from inside
    a function has still taken the dependency, and could take json_handler the
    same way.

    RELATIVE IMPORTS COUNT TOO, when the caller supplies ``package``. They did
    not until 2026-08-31, and the hole was exactly where it hurt: @canary's
    json_handler reaches its stdlib-only bootstrap helper by
    ``from ..paths import module_file``, so ``paths.py`` never entered the
    bootstrap chain, clause 2 of the exemption failed, and a module that IS
    beneath the logging system was told to import it. A relative import is a
    STATIC fact — unlike the importlib hops this walk deliberately cannot see —
    so resolving it moves the set toward correct in the direction the walk's own
    docstring already asks for.

    Args:
        content: File source.
        package: Dotted package of the importing file, for relative resolution.
            None keeps the old absolute-only behaviour, which is what the
            "holds no aipass import" clause wants for a file it cannot place.

    Returns:
        Dotted ``aipass.*`` names, absolute.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
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
            resolved = _resolve_relative(node.module, node.level, package)
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

    Seeded from the system logger and from every branch's json_handler, because
    those are the two things this standard tells a module to import. Anything
    they reach is BENEATH them in the import order and cannot import them back
    without a cycle.

    ANCESTOR PACKAGES ARE DELIBERATELY ABSENT, and the reason is measured rather
    than assumed. Importing aipass.flow.apps.handlers.json.json_handler runs
    aipass/flow/apps/handlers/__init__.py first — Python imports every parent
    package before the leaf, and no import statement says so, so the AST cannot
    see it (@flow's fence, 2026-08-31). Adding them is therefore FACTUALLY
    right about execution order and still wrong for this exemption: the wide
    form (walking each ancestor's own imports) carried the exemption out across
    every branch's public API via drone's re-exporting __init__ and exempted 4
    stdlib-only helpers that have a working logger; the narrow form (record the
    ancestor, do not walk it) changed 0 verdicts in 1040 files. A clause that
    grants exemptions nobody needs today is a waiver waiting for a file to drift
    into it. Execution order is not the property this exemption is for — being
    unable to reach the logger is — and every fence in the fleet already passes
    on its own.

    Statically walked, so a dynamic (importlib) hop inside the chain is invisible
    and the set comes out SHORT. That direction is deliberate: a missed member is
    measured by the ordinary rule and stays red, which is the state it is in
    today. An over-long set would hand out exemptions.
    """
    source_root = Path(source_root_str)
    branches = [d.name for d in source_root.iterdir() if (d / "apps").is_dir()]
    queue = ["aipass.prax.apps.modules.logger"]
    queue += [f"aipass.{name}.apps.handlers.json.json_handler" for name in branches]
    # Branch-owned operation-logging seams are substrate too (DPLAN-0325): what
    # a seam imports is beneath it in the import order, for the same reason. Left
    # out, a stdlib-only path helper that only the seam reaches stays red for an
    # import it must not carry — measured on @backup's module_paths.py.
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
        # The importing module's PACKAGE, so its relative imports resolve. A
        # package __init__ is its own package; a plain module's package is its
        # parent.
        package = module_name if module_file.name == "__init__.py" else module_name.rsplit(".", 1)[0]
        try:
            queue.extend(_aipass_imports(module_file.read_text(encoding="utf-8", errors="ignore"), package))
        except OSError as exc:
            logger.info("json_structure: unreadable module in the bootstrap walk: %s", exc)
    return frozenset(seen)


def _is_prelogging_bootstrap(path: Path, content: str) -> bool:
    """True for a module that sits BENEATH the logging system it would have to call.

    Two clauses, both measured here and neither declared by the branch:

    1. The module holds no aipass import of any kind. @prax pins exactly this
       property with an AST test, because a diagnostic that needs the logger it
       is being emitted from is a second crash wearing a diagnostic's clothes.
    2. The logging substrate's own imports reach it. This is what keeps the
       exemption from being free: 79 modules in the fleet import nothing from
       aipass, and 9 of them are in the chain.

    Clause 1 alone would exempt every stdlib-only helper in the fleet; clause 2
    alone would exempt ai_mail's whole dispatch stack, which the chain reaches
    THROUGH json_handler and which logs perfectly well. Only the pair names the
    class @prax reported (2026-08-31): log_operation() writes, so wiring it into
    a module the logger imports puts a file write on the import path of every
    branch — the ungateable write that fires during pytest COLLECTION.
    """
    try:
        ast.parse(content)
    except SyntaxError as exc:
        # An unreadable file is not a bootstrap module; it is a file we could not
        # read. _aipass_imports() answers [] for it, which would otherwise read as
        # "holds no aipass import" and buy the exemption on ignorance.
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

    DPLAN-0325 gave the fleet ONE json service and a byte-identical shim, and
    nothing branch-specific may go into that shim. A branch whose audit trail
    has a different record shape therefore has to own it in a module of its
    own — @backup's ``apps/handlers/audit/trail.py`` is the first, a JSONL
    stream built on ``aipass.prax.append_jsonl``. Check 2 below asked for the
    literal spelling ``json_handler.log_operation`` and so convicted 41 of
    backup's 43 files for following the spec.

    A seam is recognised, not bypassed, and the shape is narrow on purpose:
    the file must DEFINE ``log_operation`` itself AND build it on a logging
    primitive imported from ``aipass.prax``. A module that merely defines a
    function by that name buys nothing; the branch's own shim is excluded,
    since it is the default path check 2 already accepts.

    Args:
        branch_root: Branch directory, as a string so the cache can key on it.

    Returns:
        The seam module stems, e.g. ``frozenset({"trail"})``.
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

    The seam is the substrate, not a consumer of it: asking ``trail.py`` to
    call ``log_operation`` is asking it to log through itself. Same treatment
    the shim already gets, resting on the same two conditions
    ``_operation_log_seams`` uses, so a file cannot be a seam for one check
    and not for the other.
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


def _check_code_wiring(_path: Path, content: str) -> List[Dict]:
    """
    Check that a module/handler file has the three-JSON wiring:
      1. Imports json_handler
      2. Calls json_handler.log_operation()

    Returns a list of two check dicts.
    """
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

    # Check 1: imports json_handler
    # Matches patterns like:
    #   from aipass.seedgo.apps.handlers.json import json_handler
    #   from aipass.flow.apps.handlers.json import json_handler
    #   from ...handlers.json import json_handler
    # A module that logs through a branch-owned seam imports the SEAM, not the
    # shim — the two checks are one requirement (this module's operations reach
    # a log), so they answer together or the seam would satisfy check 2 and
    # still fail check 1 for an import it has no reason to carry.
    seam = _seam_logging(_path, content)
    has_import = seam is not None or bool(
        re.search(r"from\s+\S*\.json\s+import\s+json_handler", content)
        or re.search(r"from\s+\S*json\s+import\s+json_handler", content)
        or re.search(r"import\s+json_handler", content)
    )
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

    # Check 2: the module logs its operations — by the fleet default, or
    # through a branch-owned seam that is itself built on aipass.prax.
    # The requirement is that operations ARE logged, never that they are
    # logged in one spelling.
    has_log_operation = "json_handler.log_operation" in content or seam is not None
    seam = None if "json_handler.log_operation" in content else seam
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

    return checks  # noqa: RET504


def _check_json_handler_config(_handler_path: Path, content: str, _bypass_rules: list | None = None) -> List[Dict]:
    """
    Check json_handler.py for correct wiring per the json_structure standard.

    Validates:
    1. No hardcoded absolute paths (Path.home())
    2. Uses relative path resolution (Path(__file__))
    3. No template directory references (json_templates)
    4. Uses inline code defaults, not file-based templates (load_template)
    """
    checks: List[Dict] = []

    # Check 1: No hardcoded absolute paths
    has_path_home = bool(re.search(r"Path\.home\(\)", content))
    # Only flag _ROOT constants that use Path.home() (legacy pattern)
    # Allow _ROOT = Path(__file__).resolve()... (relative, pip-safe)
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

    # Check 2: Uses relative path resolution
    # A shim that binds the fleet json service (DPLAN-0325) resolves nothing
    # itself — the service derives this branch's root from the shim's own
    # __file__, deliberately WITHOUT resolve(), so a dead cwd on Windows
    # cannot poison it. Demanding the spelling here convicts the endpoint of
    # the migration: measured 2026-09-03, prax's shim, spawn's shim and the
    # citizen template each scored 75 on this check alone.
    # THE TEST MOVED WITH PART B, it was not deleted (2026-09-04, finding (a)).
    # This line used to read `SERVICE_IMPORT_MARKER in content`. Measured before
    # the change: removing the marker without substituting the hash test costs
    # EVERY migrated branch 25 points on its handler file — all eighteen, plus
    # the citizen template, 100 -> 75 on "Missing relative path resolution".
    # That is the endpoint of the migration convicted for being the endpoint.
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

    # Check 3: No template directory references
    # The standard says: "The CODE PATTERN is the template -- no json_templates/ directory"
    # Check for path constants or strings referencing json_templates
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

    # Check 4: No load_template() function
    # The correct pattern uses inline defaults (_create_default or similar).
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


# ------------------------------------------------------------------
# Branch-level post-check: {branch}_json/ directory structure
# ------------------------------------------------------------------


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
    violations = _check_json_dir_structure(branch_path, bypass_rules=bypass_rules)
    scores = [0] if violations else [100]
    return violations, scores


# ------------------------------------------------------------------
# Branch-level info channel: custom_config/ signpost (never scored)
# ------------------------------------------------------------------


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

    custom_config/ is operator-owned: seedgo never reads or judges its
    contents. This lists the filenames only, so a live operator override is
    visible in the audit instead of invisible. Returns plain strings on the
    audit's info channel — it can never reach a score by construction.
    """
    files = _custom_config_files(branch_path)
    if not files:
        return []
    noun = "file" if len(files) == 1 else "files"
    return [
        f"{Path(branch_path).name}_json/{CUSTOM_CONFIG_DIR}/: {len(files)} operator {noun} "
        f"({', '.join(files)}) — content not audited. {CUSTOM_CONFIG_GUIDE}"
    ]
