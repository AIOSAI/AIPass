# =================== AIPass ====================
# Name: architecture_check.py
# Description: Architecture Standards Checker Handler
# Version: 1.1.0
# Created: 2026-03-05
# Modified: 2026-10-17
# =============================================

"""Architecture Standards Checker Handler

Checks 3-layer pattern, handler independence, file size, domain organization; for the
primary entry point, also the branch structure against spawn's template baseline.
"""

import json
from pathlib import Path, PurePath
from typing import Dict, List, Optional

from aipass.seedgo.apps.handlers.bypass.ignore_handler import get_template_ignore_patterns
from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

# Spawn's modules gateway is the ONLY source for the class->template question. No
# fallback on purpose: if this door moves, the checker must die at import with spawn's
# name in the traceback, not quietly score the fleet against a guess.
from aipass.spawn.apps.modules import get_template_dir, refuse_legacy_class
from aipass.seedgo.apps.handlers.module_root import module_file

AUDIT_SCOPE = "all_files"
# Applies to production source only: a test file has no apps/handlers/modules layering.
APPLIES_TO = "production"

PACK_ROOT = module_file(__file__).parent.parent.parent  # aipass_standards/ -> handlers/ -> apps/ -> seedgo/

# Spawn templates root. The SUBDIRECTORY under it is never guessed from citizen_class
# (the class does not name a directory); only spawn's gateway may answer it. The ROOT
# stays here as the seam tests/test_citizen_class_resolution.py points at a fixture tree.
_SRC_PKG_ROOT = PACK_ROOT.parent.parent  # apps/ -> seedgo/ -> src/aipass/
SPAWN_TEMPLATES_DIR = _SRC_PKG_ROOT / "spawn" / "templates"

# shared/ beside apps/ is a branch's pre-install library (it runs before prax can be
# imported); branch_audit reads it as product, so this checker names it a layer.
LIBRARY_LAYER = "Library layer (shared/, beside apps/)"

# Template subtrees that are local-only and therefore never scored — see _is_local_only()
LOCAL_ONLY_TEMPLATE_ROOTS = (".trinity",)


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check if module follows architecture standards"""
    checks = []
    path = Path(module_path)

    # Normalize to forward slashes so string matching works on Windows too
    module_path = Path(module_path).as_posix()

    if is_bypassed(module_path, "architecture", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "ARCHITECTURE",
        }

    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "ARCHITECTURE",
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
            "standard": "ARCHITECTURE",
        }

    is_entry_point = path.name.endswith(".py") and "apps/" in module_path and path.parent.name == "apps"
    is_module = "apps/modules/" in module_path
    is_handler = "apps/handlers/" in module_path
    is_init = path.name == "__init__.py"
    is_library = is_library_file(path)

    if not is_init:
        layer_check = check_layer_location(is_entry_point, is_module, is_handler, is_library)
        checks.append(layer_check)

    size_check = check_file_size(lines, module_path)
    checks.append(size_check)

    if is_handler:
        independence_check = check_handler_independence(lines, module_path)
        if independence_check:
            checks.append(independence_check)

    if is_handler:
        domain_check = check_domain_organization(module_path)
        if domain_check:
            checks.append(domain_check)

    # Check 5: Template baseline, primary entry point only ({branch}.py); secondary
    # entry points skip it to avoid duplicate branch-level template checks.
    if is_entry_point:
        branch_dir = path.parent.parent  # apps/ -> branch/
        if path.stem == branch_dir.name:
            baseline_checks = check_template_baseline(module_path, bypass_rules=bypass_rules)
            checks.extend(baseline_checks)

    passed_checks = sum(1 for check in checks if check["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0

    overall_passed = score >= 75

    json_handler.log_operation(
        "check_completed", {"file": str(module_path), "score": score, "standard": "architecture"}
    )
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "ARCHITECTURE"}


def is_library_file(path: Path) -> bool:
    """Whether a file sits under a ``shared/`` directory that has ``apps/`` beside it."""
    return any(parent.name == "shared" and (parent.parent / "apps").is_dir() for parent in path.parents)


def check_layer_location(is_entry_point: bool, is_module: bool, is_handler: bool, is_library: bool = False) -> Dict:
    """Check if file is in correct architectural layer; the caller decides it from the path."""
    if is_entry_point:
        return {"name": "3-layer pattern", "passed": True, "message": "Entry point layer (apps/branch.py)"}
    elif is_module:
        return {"name": "3-layer pattern", "passed": True, "message": "Module layer (apps/modules/)"}
    elif is_handler:
        return {"name": "3-layer pattern", "passed": True, "message": "Handler layer (apps/handlers/)"}
    elif is_library:
        return {"name": "3-layer pattern", "passed": True, "message": LIBRARY_LAYER}
    else:
        return {
            "name": "3-layer pattern",
            "passed": False,
            "message": "File not in standard 3-layer structure (apps/, apps/modules/, apps/handlers/)",
        }


def check_file_size(lines: List[str], module_path: str) -> Dict:
    """Check file size compliance."""
    line_count = len(lines)

    if line_count < 300:
        return {"name": "File size", "passed": True, "message": f"{line_count} lines (perfect - under 300)"}
    elif line_count < 500:
        return {"name": "File size", "passed": True, "message": f"{line_count} lines (good - under 500)"}
    elif line_count < 700:
        return {"name": "File size", "passed": True, "message": f"{line_count} lines (acceptable but getting heavy)"}
    elif line_count < 1500:
        return {
            "name": "File size",
            "passed": True,
            "message": f"{line_count} lines (advisory - consider splitting, recommended under 700)",
        }
    else:
        return {
            "name": "File size",
            "passed": False,
            "message": f"{line_count} lines (exceeds 1500 - must split)",
        }


def check_handler_independence(lines: List[str], module_path: str) -> Optional[Dict]:
    """Check that handlers don't import from parent branch modules (prax and cli services allowed)"""
    parent_branch = None
    if module_path:
        path_parts = Path(module_path).parts
        for i, part in enumerate(path_parts):
            if part == "apps" and i > 0:
                parent_branch = path_parts[i - 1]
                break

    in_docstring = False
    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        if stripped.startswith('"""') or stripped.startswith("'''"):
            quote_marker = '"""' if stripped.startswith('"""') else "'''"
            quote_count = stripped.count(quote_marker)
            if quote_count >= 2:
                continue  # Skip this line but don't toggle state
            else:
                in_docstring = not in_docstring

        if in_docstring or not stripped or stripped.startswith("#"):
            continue

        if ".apps.modules" in line and ("from " in line or "import " in line):
            if "#" in line:
                code_part = line.split("#")[0]
            else:
                code_part = line

            if ".apps.modules" in code_part:
                if "prax.apps.modules" in code_part or "cli.apps.modules" in code_part:
                    continue

                if parent_branch and f"{parent_branch}.apps.modules" in code_part:
                    return {
                        "name": "Handler independence",
                        "passed": False,
                        "message": f"Handler importing from parent module on line {i} (violates independence)",
                    }

                if not parent_branch:
                    return {
                        "name": "Handler independence",
                        "passed": False,
                        "message": f"Handler importing from branch module on line {i} (violates independence)",
                    }

    return {"name": "Handler independence", "passed": True, "message": "No forbidden module imports detected"}


def check_domain_organization(module_path: str) -> Optional[Dict]:
    """Check if handler is organized by domain (not technical role)"""
    path_parts = Path(module_path).parts

    handler_domain = None
    for i, part in enumerate(path_parts):
        if part == "handlers" and i + 1 < len(path_parts):
            handler_domain = path_parts[i + 1]
            break

    if not handler_domain:
        return {"name": "Domain organization", "passed": False, "message": "Could not detect handler domain from path"}

    technical_names = ["utils", "helpers", "operations", "common", "shared", "lib"]
    if handler_domain.lower() in technical_names:
        return {
            "name": "Domain organization",
            "passed": False,
            "message": f"Technical organization ({handler_domain}/) - use business domains instead",
        }

    return {"name": "Domain organization", "passed": True, "message": f"Domain-based organization ({handler_domain}/)"}


def _load_ignore_patterns(template_path: Path) -> Dict:
    """Load ignore patterns from .registry_ignore.json in the template's .spawn/ dir"""
    ignore_file = template_path / ".spawn" / ".registry_ignore.json"

    if not ignore_file.exists():
        return {"ignore_files": [], "ignore_patterns": []}

    try:
        with open(ignore_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {"ignore_files": data.get("ignore_files", []), "ignore_patterns": data.get("ignore_patterns", [])}
    except Exception:
        logger.info("Cannot read ignore config: %s", ignore_file)
        return {"ignore_files": [], "ignore_patterns": []}


def _should_ignore(item: Path, ignore_config: Dict) -> bool:
    """Check if a template item should be ignored during baseline check"""
    name = item.name

    if name in ignore_config["ignore_files"]:
        return True

    for pattern in ignore_config["ignore_patterns"]:
        if pattern.startswith("*"):
            if name.endswith(pattern[1:]):
                return True
        elif pattern.startswith(".") and "*" in pattern:
            prefix = pattern.rstrip("*")
            if name.startswith(prefix):
                return True
        else:
            if name == pattern or pattern in item.parts:
                return True

    return False


def check_branch_info(branch_path: str) -> list[str]:
    """Non-scored signpost lines for the architecture standard.

    The baseline needs the branch passport, which is gitignored, so in a clean checkout
    or CI it cannot run; announcing that on the info channel keeps a skipped check visible
    without ever reaching a score.
    """
    passport = Path(branch_path) / ".trinity" / "passport.json"
    if passport.exists():
        return []
    return [
        f"{Path(branch_path).name}: template baseline skipped — .trinity/passport.json absent "
        "(expected in a clean checkout / CI). Branch structure was not compared against its "
        "spawn template."
    ]


def _get_citizen_class(branch_path: Path) -> Optional[str]:
    """Read citizen_class from branch's .trinity/passport.json"""
    passport = branch_path / ".trinity" / "passport.json"
    if not passport.exists():
        return None
    try:
        with open(passport, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("identity", {}).get("citizen_class")
    except Exception:
        logger.info("Cannot read passport: %s", passport)
        return None


def _resolve_template_dir(citizen_class: str) -> tuple[Optional[str], str]:
    """Ask spawn's gateway which template directory a citizen_class mints from.

    ``refuse_legacy_class`` is asked FIRST and alone: a retired name is a passport waiting
    on the migration, not a typo. Everything else goes to ``get_template_dir``; spawn's
    refusal sentence is carried through verbatim. Nothing of spawn's class table is mirrored.
    """
    legacy = refuse_legacy_class(citizen_class)
    if legacy:
        return None, f'Legacy citizen_class "{citizen_class}" — passport not yet migrated to 2.0. {legacy}'

    try:
        return get_template_dir(citizen_class).name, ""
    except ValueError as exc:
        # Not swallowed: exc IS the refusal returned above and scored by the
        # caller. Logged as well so a bad passport leaves a prax trail even
        # when the reader only sees the branch score.
        logger.info("Template baseline: spawn refused citizen_class %r", citizen_class)
        return None, f'Unresolved citizen_class "{citizen_class}" — {exc}'


def _relative_spelling(item: PurePath, root: PurePath) -> str:
    """One template entry's path relative to the template root, spelled in posix.

    Always forward slashes on every platform: this string is the check name a branch reads
    and the text a bypass rule (written with forward slashes) is matched against.
    """
    return item.relative_to(root).as_posix()


def _scan_template(template_path: Path) -> Dict:
    """Scan spawn template directory and return expected structure."""
    ignore_config = _load_ignore_patterns(template_path)
    structure = {"directories": [], "files": []}

    for item in sorted(template_path.rglob("*")):
        if _should_ignore(item, ignore_config):
            continue

        relative = _relative_spelling(item, template_path)

        if item.is_dir():
            structure["directories"].append(relative)
        elif item.is_file():
            if item.name in get_template_ignore_patterns():
                continue
            structure["files"].append(relative)

    return structure


def _is_local_only(template_relative: str) -> bool:
    """True when a template path belongs to a gitignored, local-only subtree.

    The trinity directory is gitignored, local-only agent memory: scoring its contents would
    demand a branch commit what it must not, and "it exists" could never fail once the
    passport has been read.
    """
    parts = Path(template_relative).parts
    return bool(parts) and parts[0] in LOCAL_ONLY_TEMPLATE_ROOTS


def _transform_path(template_relative: str, branch_name: str) -> str:
    """Transform a template path for a specific branch."""
    branch_lower = branch_name.lower().replace("-", "_")
    entry_point_name = branch_name.lstrip(".").lower()

    # {{BRANCH}} in directory names uses lowercase (e.g., {{BRANCH}}_json → seedgo_json)
    result = template_relative.replace("{{BRANCH}}", branch_lower)

    FILE_RENAMES = {
        f"{branch_lower}.py": f"{entry_point_name}.py",  # already lowercase from placeholder
    }

    filename = Path(result).name
    if filename in FILE_RENAMES:
        result = (Path(result).parent / FILE_RENAMES[filename]).as_posix()

    return result


def check_template_baseline(module_path: str, bypass_rules: list | None = None) -> List[Dict]:
    """Verify branch structure against spawn template (live scan, class-aware)."""
    checks = []

    path = Path(module_path)
    branch_path = None
    current = path.parent
    while current != current.parent:
        if current.name == "apps" and current.parent:
            branch_path = current.parent
            break
        current = current.parent

    if not branch_path:
        return [
            {"name": "Template baseline", "passed": False, "message": "Could not detect branch path from module path"}
        ]

    branch_name = branch_path.name

    # The trinity directory is gitignored: skip the template baseline when the passport is absent.
    citizen_class = _get_citizen_class(branch_path)
    if not citizen_class:
        passport_path = branch_path / ".trinity" / "passport.json"
        if not passport_path.exists():
            return []
        return [
            {
                "name": "Template baseline",
                "passed": False,
                "message": f"No citizen_class in {branch_name}/.trinity/passport.json",
            }
        ]

    if not SPAWN_TEMPLATES_DIR.exists():
        return [
            {
                "name": "Template baseline",
                "passed": False,
                "message": f"Spawn templates directory not found: {SPAWN_TEMPLATES_DIR}",
            }
        ]

    # A refused class is a SCORED violation naming the value, so an un-migrated passport
    # reads as "migrate this" and never as a silent pass.
    template_dir_name, refusal = _resolve_template_dir(citizen_class)
    if not template_dir_name:
        logger.info("Template baseline: unusable citizen_class %r for %s", citizen_class, branch_name)
        return [
            {
                "name": "Template baseline",
                "passed": False,
                "message": f"{refusal} Read from {branch_name}/.trinity/passport.json",
            }
        ]

    template_path = SPAWN_TEMPLATES_DIR / template_dir_name
    if not template_path.exists():
        return [
            {
                "name": "Template baseline",
                "passed": False,
                "message": f'No template directory "{template_dir_name}" for citizen_class '
                f'"{citizen_class}" at {template_path}',
            }
        ]

    template_structure = _scan_template(template_path)

    for template_dir in template_structure["directories"]:
        if _is_local_only(template_dir):
            continue
        expected = _transform_path(template_dir, branch_name)
        full = branch_path / expected

        if full.exists():
            checks.append({"name": f"Dir: {expected}/", "passed": True, "message": "Template directory exists"})
        else:
            if is_bypassed(expected, "architecture", bypass_rules=bypass_rules):
                checks.append(
                    {"name": f"Dir: {expected}/", "passed": True, "message": "Template directory missing (bypassed)"}
                )
            else:
                checks.append(
                    {
                        "name": f"Dir: {expected}/",
                        "passed": False,
                        "message": f"Missing dir: {expected}/ (template: {template_dir_name})",
                    }
                )

    for template_file in template_structure["files"]:
        if _is_local_only(template_file):
            continue
        expected = _transform_path(template_file, branch_name)
        full = branch_path / expected

        if full.exists():
            checks.append({"name": f"File: {expected}", "passed": True, "message": "Template file exists"})
        else:
            file_name = Path(expected).name
            if is_bypassed(file_name, "architecture", bypass_rules=bypass_rules):
                checks.append(
                    {"name": f"File: {expected}", "passed": True, "message": "Template file missing (bypassed)"}
                )
            else:
                checks.append(
                    {
                        "name": f"File: {expected}",
                        "passed": False,
                        "message": f"Missing file: {expected} (template: {template_dir_name})",
                    }
                )

    missing_count = sum(1 for c in checks if not c["passed"])
    total_count = len(checks)
    checks.insert(
        0,
        {
            "name": f"Template baseline ({citizen_class})",
            "passed": missing_count == 0,
            "message": (
                f"{total_count} items checked from spawn/templates/{template_dir_name}/, {missing_count} missing"
            ),
        },
    )

    return checks
