# =================== AIPass ====================
# Name: plugin_integrity.py
# Description: Verify core audit modules don't hardcode standard names
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-03-22
# =============================================

"""Plugin Integrity Proof -- Verify plugin architecture stays clean.

The plugin architecture depends on dynamic discovery (glob + importlib).
Core audit modules should never reference specific standard names in code
logic.  This handler scans target modules with AST + regex and reports
any hardcoded standard-name references.

Interface:
    scan(pack_dir: Path) -> dict
    Returns: {"passed": bool, "issues": list, "summary": str, ...}

Note: audit_display.py cosmetic refs are a known upgrade target (DPLAN-0047).

Reference: tools/plugin_integrity_scanner.py (original prototype)
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler


# =============================================================================
# CONFIGURATION
# =============================================================================

# Modules whose hardcoded refs are cosmetic (display layer, not routing).
COSMETIC_MODULES: set[str] = {"audit_display.py"}

# Standard names that double as common infrastructure/English words.
# These appear as directory names, import paths, variable names, Rich markup
# labels, etc. -- not as hardcoded standard routing.  Never flag bare AST
# string literals for these; only the regex patterns catch truly suspicious use.
AMBIGUOUS_NAMES: set[str] = {
    "architecture",
    "cli",
    "cli_flags",
    "documentation",
    "encapsulation",
    "error_handling",
    "handlers",
    "imports",
    "introspection",
    "meta",
    "modules",
    "naming",
    "readme",
    "testing",
    "trigger",
    "shebang",
    "permission_flags",
}


# =============================================================================
# TARGET MODULE RESOLUTION
# =============================================================================


def _resolve_target_modules(
    pack_dir: Path,
) -> list[dict[str, Path | str | bool]]:
    """Build the list of core modules to scan, resolved from pack_dir.

    Path layout (from pack_dir = .../apps/handlers/aipass_standards/):
        seedgo_root  = pack_dir.parent.parent.parent   (.../seedgo/)
        modules_dir  = seedgo_root / "apps" / "modules"
        audit_dir    = pack_dir.parent / "audit"        (sibling handler dir)
        entry_point  = seedgo_root / "apps" / "seedgo.py"
    """
    seedgo_root = pack_dir.parent.parent.parent
    modules_dir = seedgo_root / "apps" / "modules"
    audit_dir = pack_dir.parent / "audit"
    entry_point = seedgo_root / "apps" / "seedgo.py"

    return [
        {
            "path": modules_dir / "standards_audit.py",
            "label": "standards_audit.py",
            "cosmetic": False,
        },
        {
            "path": audit_dir / "branch_audit.py",
            "label": "branch_audit.py",
            "cosmetic": False,
        },
        {
            "path": audit_dir / "audit_display.py",
            "label": "audit_display.py",
            "cosmetic": True,
        },
        {
            "path": modules_dir / "standards_query.py",
            "label": "standards_query.py",
            "cosmetic": False,
        },
        {
            "path": entry_point,
            "label": "seedgo.py",
            "cosmetic": False,
        },
    ]


# =============================================================================
# STANDARD NAME DISCOVERY
# =============================================================================


def _discover_standard_names(pack_dir: Path) -> list[str]:
    """Discover standard names from *_check.py files in the pack directory.

    Returns:
        Sorted list of standard names (e.g. ["architecture", "cli", ...]).
    """
    if not pack_dir.is_dir():
        return []
    names: list[str] = []
    for check_file in sorted(pack_dir.glob("*_check.py")):
        name = check_file.stem.removesuffix("_check")
        names.append(name)
    return names


# =============================================================================
# AST HELPERS
# =============================================================================


def _enclosing_context(node: ast.AST, parents: dict[int, ast.AST]) -> str:
    """Walk up the parent chain to find the enclosing function/class name."""
    parts: list[str] = []
    current = node
    while id(current) in parents:
        current = parents[id(current)]
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef):
            parts.append(f"def {current.name}()")
        elif isinstance(current, ast.ClassDef):
            parts.append(f"class {current.name}")
    if parts:
        return " > ".join(reversed(parts))
    return "<module level>"


def _is_docstring(node: ast.Constant, tree: ast.Module) -> bool:
    """Check if a string constant is a docstring."""
    for parent in ast.walk(tree):
        body = getattr(parent, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and first.value is node:
            return True
    return False


def _is_display_string(
    node: ast.Constant,
    parents: dict[int, ast.AST],
) -> bool:
    """Check if a string constant is used in a display/print context.

    Strings passed to console.print(), header(), logger.*, error(), warning()
    or used inside f-strings are display text, not hardcoded routing.
    """
    parent = parents.get(id(node))
    if parent is None:
        return False

    # Inside an f-string -> display formatting
    if isinstance(parent, ast.JoinedStr):
        return True

    # Direct argument to a display/logging call
    if isinstance(parent, ast.Call):
        func = parent.func
        if isinstance(func, ast.Attribute) and func.attr in (
            "print",
            "info",
            "error",
            "warning",
            "debug",
        ):
            return True
        if isinstance(func, ast.Name) and func.id in (
            "header",
            "error",
            "warning",
        ):
            return True

    # Keyword arg inside a display call
    grandparent = parents.get(id(parent))
    if isinstance(grandparent, ast.Call):
        func = grandparent.func
        if isinstance(func, ast.Attribute) and func.attr in (
            "print",
            "log_operation",
        ):
            return True
        if isinstance(func, ast.Name) and func.id in (
            "header",
            "error",
            "warning",
        ):
            return True

    return False


def _is_dict_key_access(
    node: ast.Constant,
    parents: dict[int, ast.AST],
) -> bool:
    """Check if a string is a dict key inside generic data-structure access.

    Patterns like result.get('key') or result['key'] when iterating over
    dynamic data are not hardcoded routing.
    """
    parent = parents.get(id(node))
    if parent is None:
        return False

    # .get('key', default)
    if isinstance(parent, ast.Call):
        func = parent.func
        if isinstance(func, ast.Attribute) and func.attr == "get":
            return True

    # ['key'] subscript
    if isinstance(parent, ast.Subscript):
        return True

    return False


# =============================================================================
# AST SCANNER
# =============================================================================


def _scan_file_ast(
    file_path: Path,
    standard_names: list[str],
) -> list[dict[str, str | int]]:
    """Parse a file with AST and find string literals matching standard names.

    Filters out docstrings, display strings, dict-key access, and
    ambiguous names.  Only flags string literals that look like hardcoded
    routing.
    """
    source = file_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        logger.info("Skipped %s: SyntaxError during parse", file_path.name)
        return []

    # Build child -> parent map
    parents: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent

    name_set = set(standard_names)
    findings: list[dict[str, str | int]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue
        if not isinstance(node.value, str):
            continue

        value = node.value

        if _is_docstring(node, tree):
            continue
        if _is_display_string(node, parents):
            continue
        if _is_dict_key_access(node, parents):
            continue
        if value not in name_set:
            continue
        if value in AMBIGUOUS_NAMES:
            continue

        context = _enclosing_context(node, parents)
        findings.append(
            {
                "line": getattr(node, "lineno", 0),
                "name": value,
                "context": context,
                "value": value,
                "kind": "ast_string_literal",
            }
        )

    return findings


# =============================================================================
# REGEX SCANNER
# =============================================================================


def _scan_file_regex(
    file_path: Path,
    standard_names: list[str],
) -> list[dict[str, str | int]]:
    """Regex scan for standard names used as hardcoded identifiers.

    Patterns detected:
        - check_<standard>( -- direct checker function call
        - <standard>_violations -- hardcoded violation key construction
        - == '<standard>' -- hardcoded branching
    """
    source = file_path.read_text(encoding="utf-8")
    lines = source.splitlines()

    findings: list[dict[str, str | int]] = []
    in_docstring = False
    docstring_delim: str | None = None

    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()

        # Track triple-quoted docstrings (simple heuristic)
        for delim in ('"""', "'''"):
            count = stripped.count(delim)
            if in_docstring:
                if delim == docstring_delim and count >= 1:
                    in_docstring = False
                    docstring_delim = None
                continue
            if count == 1:
                in_docstring = True
                docstring_delim = delim
                break

        if in_docstring:
            continue

        # Skip pure comment lines
        if stripped.startswith("#"):
            continue

        # Extract code portion (before inline comment)
        code_part = line.split("#")[0] if "#" in line else line

        for sn in standard_names:
            # Pattern 1: check_<standard>( -- direct checker call
            fn_pat = rf"\bcheck_{re.escape(sn)}\s*\("
            if re.search(fn_pat, code_part):
                findings.append(
                    {
                        "line": lineno,
                        "name": sn,
                        "context": stripped[:80],
                        "value": stripped[:80],
                        "kind": "hardcoded_function_call",
                    }
                )

            # Pattern 2: <standard>_violations -- hardcoded violation key
            viol_pat = rf"\b{re.escape(sn)}_violations\b"
            if re.search(viol_pat, code_part):
                findings.append(
                    {
                        "line": lineno,
                        "name": sn,
                        "context": stripped[:80],
                        "value": stripped[:80],
                        "kind": "hardcoded_violation_key",
                    }
                )

            # Pattern 3: == '<standard>' -- hardcoded branching
            branch_pat = rf"""==\s*['"]{re.escape(sn)}['"]"""
            if re.search(branch_pat, code_part):
                findings.append(
                    {
                        "line": lineno,
                        "name": sn,
                        "context": stripped[:80],
                        "value": stripped[:80],
                        "kind": "hardcoded_branch",
                    }
                )

    return findings


# =============================================================================
# PUBLIC SCAN INTERFACE
# =============================================================================


def scan(pack_dir: Path) -> dict:
    """Run the full plugin integrity scan.

    Args:
        pack_dir: Path to the standards pack directory
                  (e.g. handlers/aipass_standards/).

    Returns:
        Dict with keys:
            passed: True if flagged_count == 0 (cosmetic modules don't fail)
            standard_names: list of discovered standard names
            modules: list of per-module result dicts
            clean_count: number of clean modules
            flagged_count: modules with unexpected hardcoded references
            cosmetic_count: modules with only cosmetic references
            missing_count: modules whose file was not found
            issues: list of human-readable issue strings
            summary: one-line summary string
    """
    logger.info("plugin_integrity: scanning pack_dir=%s", pack_dir)

    standard_names = _discover_standard_names(pack_dir)
    target_modules = _resolve_target_modules(pack_dir)

    module_results: list[dict] = []
    issues: list[str] = []

    for module_info in target_modules:
        file_path = Path(str(module_info["path"]))
        label = str(module_info["label"])
        is_cosmetic = bool(module_info.get("cosmetic", False)) or label in COSMETIC_MODULES

        result: dict = {
            "label": label,
            "path": str(file_path),
            "exists": file_path.is_file(),
            "cosmetic_module": is_cosmetic,
            "findings": [],
            "status": "clean",
        }

        if not file_path.is_file():
            result["status"] = "missing"
            issues.append(f"{label}: file not found at {file_path}")
            module_results.append(result)
            continue

        # Run both AST and regex scans
        ast_findings = _scan_file_ast(file_path, standard_names)
        regex_findings = _scan_file_regex(file_path, standard_names)

        # Deduplicate by (line, name, kind) -- AST findings take priority
        seen: set[tuple[int, str, str]] = set()
        combined: list[dict] = []
        for finding in ast_findings:
            key = (int(finding["line"]), str(finding["name"]), str(finding["kind"]))
            if key not in seen:
                seen.add(key)
                combined.append(finding)
        for finding in regex_findings:
            key = (int(finding["line"]), str(finding["name"]), str(finding["kind"]))
            if key not in seen:
                seen.add(key)
                combined.append(finding)

        # Sort by line number
        combined.sort(key=lambda x: int(x["line"]))

        result["findings"] = combined

        if combined:
            if is_cosmetic:
                result["status"] = "cosmetic"
            else:
                result["status"] = "flagged"
                # Build issue strings for flagged (non-cosmetic) modules
                for finding in combined:
                    kind_label = {
                        "ast_string_literal": "string literal",
                        "hardcoded_function_call": "function call",
                        "hardcoded_violation_key": "violation key",
                        "hardcoded_branch": "branch condition",
                    }.get(str(finding["kind"]), str(finding["kind"]))
                    issues.append(
                        f"{label} L{finding['line']}: hardcoded {kind_label} referencing standard '{finding['name']}'"
                    )
        else:
            result["status"] = "clean"

        module_results.append(result)

    clean_count = sum(1 for m in module_results if m["status"] == "clean")
    flagged_count = sum(1 for m in module_results if m["status"] == "flagged")
    cosmetic_count = sum(1 for m in module_results if m["status"] == "cosmetic")
    missing_count = sum(1 for m in module_results if m["status"] == "missing")

    passed = flagged_count == 0

    # Build summary
    total = len(module_results)
    parts: list[str] = [f"{clean_count}/{total} clean"]
    if cosmetic_count:
        parts.append(f"{cosmetic_count} cosmetic")
    if flagged_count:
        parts.append(f"{flagged_count} FLAGGED")
    if missing_count:
        parts.append(f"{missing_count} missing")

    if passed:
        summary = f"Plugin integrity clean: {', '.join(parts)}"
    else:
        summary = f"Plugin integrity FAILED: {', '.join(parts)}"

    logger.info("plugin_integrity: passed=%s, summary=%s", passed, summary)

    json_handler.log_operation("proof_scan", {"proof": "plugin_integrity", "passed": passed})

    return {
        "passed": passed,
        "standard_names": standard_names,
        "modules": module_results,
        "clean_count": clean_count,
        "flagged_count": flagged_count,
        "cosmetic_count": cosmetic_count,
        "missing_count": missing_count,
        "issues": issues,
        "summary": summary,
    }
