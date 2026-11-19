# =================== AIPass ====================
# Name: stdlib_only_check.py
# Description: Stdlib Only Standards Checker - a listed file's stdlib-only, no-I/O claim, proven statically
# Version: 1.0.0
# Created: 2026-11-17
# Modified: 2026-11-17
# =============================================

"""Stdlib Only Standards Checker

Reference: stdlib_only.md. A branch file that other branches import before any aipass service runs cannot import
the json shim or log. Its branch asks for an entry in CLAIMS; this check then proves the claim for every entry:
imports from the standard library only, no relative or aipass import, and no call that touches the disk, the
environment or a process. A proven entry is not subject to json_structure's wiring; an unlisted file gets no
relief, however clean.
"""

import ast
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from aipass.sentry.apps.handlers.aipass_standards.check_support import tail_name
from aipass.sentry.apps.handlers.bypass.utils import is_bypassed
from aipass.sentry.apps.handlers.json import json_handler

APPLIES_TO = "production"
AUDIT_SCOPE = "branch_level"

STANDARD = "STDLIB_ONLY"
STANDARD_KEY = "stdlib_only"

#: The claims, as paths under src/aipass. A branch asks; sentry adds the entry. A claim is not a pass.
CLAIMS: Tuple[str, ...] = ("drone/apps/handlers/registry_name.py",)

#: Standard-library modules whose use is I/O: importing one breaks the promise before any call is read.
_IO_MODULES = frozenset({"subprocess", "shutil", "socket", "tempfile", "glob", "multiprocessing", "pty", "fileinput"})
#: Calls that open, read, list or write the disk, read the environment, run a process, or import at run time.
_IO_CALLS = frozenset(
    {
        "open",
        "input",
        "iterdir",
        "listdir",
        "scandir",
        "walk",
        "glob",
        "rglob",
        "stat",
        "lstat",
        "exists",
        "is_file",
        "is_dir",
        "touch",
        "mkdir",
        "makedirs",
        "rmdir",
        "unlink",
        "remove",
        "rename",
        "chmod",
        "symlink_to",
        "getenv",
        "putenv",
        "unsetenv",
        "system",
        "popen",
        "fork",
        "exec",
        "eval",
        "__import__",
        "import_module",
    }
)
#: The environment, read as an attribute or imported by name.
_ENV_NAMES = frozenset({"environ", "environb"})
#: Name families: Path.read_*/write_*, and os.exec*/spawn* (execvp, spawnlpe).
_IO_FAMILY = re.compile(r"^(read_|write_)|^(exec|spawn)[lv]p?e?$")


def _io_name(name: str) -> bool:
    return name in _IO_CALLS or name in _ENV_NAMES or bool(_IO_FAMILY.search(name))


def _import_breaks(node: ast.AST) -> List[Tuple[int, str]]:
    """The promise an import statement breaks, if any."""
    if isinstance(node, ast.ImportFrom) and node.level:
        return [(node.lineno, "relative import")]
    if isinstance(node, ast.Import):
        roots = [alias.name for alias in node.names]
    elif isinstance(node, ast.ImportFrom):
        roots = [node.module or ""]
    else:
        return []
    found = []
    for name in roots:
        root = name.split(".")[0]
        if root == "aipass":
            found.append((node.lineno, f"aipass import {name!r}"))
        elif root not in sys.stdlib_module_names:
            found.append((node.lineno, f"import {name!r} is not in the standard library"))
        elif root in _IO_MODULES:
            found.append((node.lineno, f"import {name!r} does I/O"))
    if isinstance(node, ast.ImportFrom):
        found += [(node.lineno, f"imports {a.name!r}, which does I/O") for a in node.names if _io_name(a.name)]
    return found


def breaks(source: str) -> List[Tuple[int, str]]:
    """(line, what breaks the stdlib-only promise) for one source; one entry when Python cannot parse it."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        return [(getattr(exc, "lineno", 0) or 0, f"cannot be read as Python ({type(exc).__name__}), so unproven")]
    found: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        found += _import_breaks(node)
        if isinstance(node, ast.Call) and _io_name(tail_name(node.func)):
            found.append((node.lineno, f"calls {tail_name(node.func)}(), which does I/O"))
        elif isinstance(node, ast.Attribute) and node.attr in _ENV_NAMES:
            found.append((node.lineno, f"reads {node.attr}"))
    return sorted(set(found))


def claim_of(path: Path) -> Optional[str]:
    """The claim a file holds (its path under src/aipass), or None when it is not listed."""
    parts = path.resolve().parts
    for index in range(len(parts) - 2, -1, -1):
        if parts[index : index + 2] == ("src", "aipass"):
            rel = "/".join(parts[index + 2 :])
            return rel if rel in CLAIMS else None
    return None


def proven_claim(path: Path) -> bool:
    """True for a listed file whose claim the check proves; json_structure stands down for it alone."""
    if claim_of(path) is None or not path.is_file():
        return False
    return not breaks(path.read_text(encoding="utf-8"))


def _not_applicable(branch: str) -> Dict:
    """No claim in this branch: the row measures nothing, so it holds its slot without a score."""
    message = f"No file in {branch} claims stdlib_only (a claim is listed in CLAIMS by sentry on request)"
    return {
        "passed": True,
        "score": 0,
        "not_applicable": True,
        "checks": [{"name": "Claims", "passed": True, "message": message}],
        "standard": STANDARD,
    }


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Prove every claim this branch holds; a missing or broken claim fails the row."""
    branch = Path(branch_path)
    if is_bypassed(branch_path, STANDARD_KEY, bypass_rules=bypass_rules):
        message = "Standard bypassed via .sentry/bypass.json"
        return {"passed": True, "checks": [{"name": "Bypassed", "passed": True, "message": message}], "score": 100}
    claims = [claim for claim in CLAIMS if claim.split("/")[0] == branch.name]
    if not claims:
        return _not_applicable(branch.name)
    checks = []
    for claim in claims:
        target = branch.parent / claim
        if not target.is_file():
            checks.append({"name": "Claim proven", "passed": False, "message": f"{claim} is listed but does not exist"})
            continue
        sites = [{"file": claim, "name": why, "line": line} for line, why in breaks(target.read_text(encoding="utf-8"))]
        message = (
            f"{claim}: " + "; ".join(f"L{s['line']} {s['name']}" for s in sites)
            if sites
            else f"{claim}: standard library only, no disk, environment or process access"
        )
        checks.append({"name": "Claim proven", "passed": not sites, "message": message, "sites": sites})
    passed = all(check["passed"] for check in checks)
    json_handler.log_operation("check_completed", {"branch": branch.name, "standard": STANDARD_KEY, "passed": passed})
    return {"passed": passed, "checks": checks, "score": 100 if passed else 0, "standard": STANDARD}
