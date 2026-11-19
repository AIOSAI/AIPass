# =================== AIPass ====================
# Name: json_handler_check.py
# Description: JSON Handler Integrity Standards Checker
# Version: 1.3.1
# Created: 2026-06-14
# Modified: 2026-11-18
# =============================================

"""JSON Handler Integrity Standards Checker. Reference: json_handler.md"""

import hashlib
import re
from pathlib import Path

from aipass.prax import logger
from aipass.sentry.apps.handlers.bypass.utils import is_bypassed
from aipass.sentry.apps.handlers.json import json_handler

# APPLIES_TO: the shim's sha256, a handler file.
APPLIES_TO = "production"
AUDIT_SCOPE = "branch_level"

# Triplets live in {branch}_json/, outside apps/. PRESENCE only: they include *_log.json written during
# the audit itself, so watching their content would mark every branch dirty every run.
BRANCH_INPUT_NAMES = ("{branch}_json/*.json",)

_TRIPLET_KINDS = ("config", "data", "log")

_TRIPLET_RE = re.compile(r"^(?P<stem>.+)_(?P<kind>config|data|log)\.json$")

# sha256 of the canonical shim: the bytes spawn's citizen template ships at apps/handlers/json/json_handler.py.
# Never taught by a branch copy, so a branch that drifts cannot teach the constant its own drift.
CANONICAL_SHIM_SHA256 = "237bc66d92337a188bcd85e515863fe2141a607df0b7534c820b9ead55ae50db"

# Guidance only: quoted in the refusal message, accepted by nothing. json_structure_check imports
# `is_shim_for` instead, so the two standards share the test, not a string.
SERVICE_IMPORT_MARKER = "from aipass.prax import json_handler"

# Branches whose shim binds by package name. Hooks' shim also runs from a promoted snapshot beside apps/
# (.live-<stamp>), where a depth counted from its own __file__ lands on the branch only by coincidence.
BY_NAME_CLAIMS = frozenset({"hooks"})

BY_FILE_LINE = "_h = json_handler.for_module(__file__)\n"
_BY_NAME_RE = re.compile(r'^_h = json_handler\.for_branch\("([^"\n]*)"\)\n', re.MULTILINE)

_TEMPLATE_HANDLER_PARTS = ("templates", "citizen", "apps", "handlers", "json", "json_handler.py")


def _read_handler(branch_path: Path) -> str | None:
    """The handler's text, or None when the branch has none.

    Raises:
        OSError, UnicodeDecodeError: the handler exists but cannot be read; never reported as missing.
    """
    handler = branch_path / "apps" / "handlers" / "json" / "json_handler.py"
    if not handler.exists():
        return None
    return handler.read_text(encoding="utf-8")


def _is_canonical_shim(content: str) -> bool:
    """Return True when *content* IS the canonical shim, byte for byte.

    Hashing the text is the whole check: a shim cannot drift by a character without saying so.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest() == CANONICAL_SHIM_SHA256


def by_name_line(branch_name: str) -> str:
    """The binding line a claimed branch writes in place of ``BY_FILE_LINE``."""
    return f'_h = json_handler.for_branch("{branch_name}")\n'


def _by_name_target(content: str) -> str | None:
    """The branch a by-name shim names, or None when *content* is not the canonical shim with only that line swapped.

    Proven by construction: swapping the by-name line back must give the canonical bytes, so no second hash is kept.
    """
    match = _BY_NAME_RE.search(content)
    if match is None or not _is_canonical_shim(content.replace(match.group(0), BY_FILE_LINE)):
        return None
    return match.group(1)


def _capability_verdict(content: str, branch_name: str) -> tuple[bool, str]:
    """Judge one handler file: the canonical shim, or for a claimed branch the shim binding by its own name.

    A hash, not substring evidence: the file either IS the one shim or it is not, and a branch that edits a
    byte goes red at once instead of falling through to a weaker path and looking migrated.
    """
    claimed = branch_name in BY_NAME_CLAIMS
    own_line = by_name_line(branch_name).strip()
    if _is_canonical_shim(content):
        if not claimed:
            return True, "Canonical shim — sha256 matches the pinned spec (DPLAN-0325 section 3)"
        return False, (
            f"{branch_name} holds a by-name claim but binds by file: its shim also runs from a snapshot beside "
            f"apps/, so write '{own_line}' in place of '{BY_FILE_LINE.strip()}', nothing else changed"
        )
    named = _by_name_target(content)
    if named is not None and not claimed:
        return False, (
            f"{branch_name} binds by name, a form claimed only by {', '.join(sorted(BY_NAME_CLAIMS))}: "
            f"write '{BY_FILE_LINE.strip()}', the canonical shim"
        )
    if named is not None and named != branch_name:
        return False, f"{branch_name}'s shim binds the branch named '{named}', not itself: write '{own_line}'"
    if named is not None:
        return True, f"Claimed by-name shim — the canonical shim with only its binding line naming {branch_name}"
    return False, (
        f"Not the canonical json shim — {branch_name}'s handler does not match the pinned "
        f"sha256 (DPLAN-0325 section 3). The fleet has ONE json implementation; a branch "
        f"handler is its byte-identical binding, {len(content.encode('utf-8'))} bytes here. "
        f"Replace the file with the spec's bytes: '{SERVICE_IMPORT_MARKER}' and the nine "
        f"bound names, nothing of its own" + (f", binding with '{own_line}'" if claimed else "")
    )


def is_shim_for(content: str, branch_name: str) -> bool:
    """True when *content* is the json shim *branch_name* must hold: the one test both json standards share."""
    return _capability_verdict(content, branch_name)[0]


def _check_template_handler(branch_path: Path, bypass_rules: list | None = None) -> dict | None:
    """Judge the citizen template's handler, when the branch ships one.

    None for a branch that ships no template, so the check appears only where there is something to judge.
    """
    template = branch_path.joinpath(*_TEMPLATE_HANDLER_PARTS)
    if not template.is_file():
        return None

    relative = "/".join(_TEMPLATE_HANDLER_PARTS)
    if is_bypassed(relative, "json_handler", bypass_rules=bypass_rules):
        return {
            "name": "Template handler capability",
            "passed": True,
            "message": f"{relative} bypassed via .sentry/bypass.json",
        }

    try:
        content = template.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("json_handler_check: cannot read citizen template: %s", exc)
        return {
            "name": "Template handler capability",
            "passed": False,
            "message": f"{relative} could not be read: {exc}",
        }

    # The template is UNRENDERED, so its branch token is the placeholder the
    # stamper substitutes, not a branch name.
    passed, message = _capability_verdict(content, "{{BRANCH}}")
    return {
        "name": "Template handler capability",
        "passed": passed,
        "message": f"{relative}: {message}",
    }


def _collect_triplet_members(json_dir: Path) -> dict[str, set[str]]:
    """Map each module stem to the triplet members on disk; any one member is evidence the module exists."""
    members: dict[str, set[str]] = {}
    for path in sorted(json_dir.glob("*.json")):
        match = _TRIPLET_RE.match(path.name)
        if match is None:
            continue
        members.setdefault(match.group("stem"), set()).add(match.group("kind"))
    return members


def _check_disk_triplets(branch_path: Path, bypass_rules: list | None = None) -> dict:
    branch_name = branch_path.name
    json_dir = branch_path / f"{branch_name}_json"

    if not json_dir.is_dir():
        return {
            "name": "Disk triplet completeness",
            "passed": True,
            "message": f"No {branch_name}_json/ directory (no JSON activity)",
        }

    members = _collect_triplet_members(json_dir)
    if not members:
        return {
            "name": "Disk triplet completeness",
            "passed": True,
            "message": f"{branch_name}_json/ exists but has no triplet files",
        }

    missing = []
    for stem, present in sorted(members.items()):
        absent = [
            kind
            for kind in _TRIPLET_KINDS
            if kind not in present
            and not is_bypassed(f"{branch_name}_json/{stem}_{kind}.json", "json_handler", bypass_rules=bypass_rules)
        ]
        if absent:
            missing.append(f"{stem} (missing {', '.join(absent)})")

    if not missing:
        return {
            "name": "Disk triplet completeness",
            "passed": True,
            "message": f"All {len(members)} modules have complete triplets",
        }

    return {
        "name": "Disk triplet completeness",
        "passed": False,
        "message": (
            f"{len(missing)}/{len(members)} modules missing triplet files: "
            + "; ".join(missing[:5])
            + ("..." if len(missing) > 5 else "")
        ),
    }


def check_branch(branch_path: str, bypass_rules: list | None = None) -> dict:
    """Check that a branch's json_handler.py is canonical."""
    bp = Path(branch_path)

    if is_bypassed(branch_path, "json_handler", bypass_rules=bypass_rules):
        result = {
            "passed": True,
            "checks": [
                {
                    "name": "Bypassed",
                    "passed": True,
                    "message": "Standard bypassed via .sentry/bypass.json",
                }
            ],
            "score": 100,
            "standard": "JSON_HANDLER",
        }
        json_handler.log_operation(
            "check_completed",
            {"branch": branch_path, "score": 100, "standard": "json_handler"},
        )
        return result

    checks = []
    content = _read_handler(bp)

    if content is None:
        checks.append(
            {
                "name": "Handler exists",
                "passed": False,
                "message": ("apps/handlers/json/json_handler.py not found — branch has no JSON handler"),
            }
        )
    else:
        checks.append(
            {
                "name": "Handler exists",
                "passed": True,
                "message": "apps/handlers/json/json_handler.py present",
            }
        )

        capable, capability_message = _capability_verdict(content, bp.name)
        checks.append(
            {
                "name": "Handler capability",
                "passed": capable,
                "message": capability_message,
            }
        )

    template_check = _check_template_handler(bp, bypass_rules=bypass_rules)
    if template_check is not None:
        checks.append(template_check)

    checks.append(_check_disk_triplets(bp, bypass_rules=bypass_rules))

    passed_count = sum(1 for c in checks if c["passed"])
    total = len(checks)
    score = int(passed_count / total * 100) if total else 0

    result = {
        "passed": score >= 75,
        "checks": checks,
        "score": score,
        "standard": "JSON_HANDLER",
    }

    json_handler.log_operation(
        "check_completed",
        {
            "branch": branch_path,
            "score": score,
            "standard": "json_handler",
        },
    )
    return result
