# =================== AIPass ====================
# Name: roots_file.py
# Description: Template lifecycle for AIPASS_ROOTS.json — init, add, remove, list, heal
# Version: 1.0.0
# Created: 2026-08-30
# Modified: 2026-10-17
# =============================================

"""The WRITE half of the fleet anchor. ``registry_scope`` reads; this writes.

Reference: docs/rollover_pipeline.md
"""

import json
import re
from datetime import date
from pathlib import Path

from aipass.prax import logger

from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.monitor.registry_scope import (
    DECLARED_ROOTS,
    find_repo_root,
    overlaps_home,
)
from aipass.memory.apps.handlers.repo_root import module_file

# Imported from the reader, never re-spelled: the write side refuses exactly what it refuses.
ROOTS_FILE = DECLARED_ROOTS

ROOTS_SCHEMA_VERSION = "1.0.0"
TEMPLATE_NAME = "AIPASS_ROOTS.template.json"
CORRUPT_SUFFIX_NAME = f"{DECLARED_ROOTS}.corrupt"

_BRANCH_ROOT = module_file(__file__).parent.parent.parent.parent

# Salvage is for a human to read; nothing it finds is ever written back as a declaration.
_SALVAGE = re.compile(r'"path"\s*:\s*"([^"]+)"')


def template_path() -> Path:
    """The gold-source template, beside the other @memory templates."""
    return _BRANCH_ROOT / "templates" / TEMPLATE_NAME


def _today() -> str:
    return date.today().isoformat()


def render_scaffold(today: str | None = None) -> dict:
    """The default document: current metadata, and NOBODY DECLARED (examples would declare for you)."""
    stamp = today or _today()
    document = json.loads(template_path().read_text(encoding="utf-8"))
    document["metadata"]["last_updated"] = stamp
    document["metadata"]["version"] = ROOTS_SCHEMA_VERSION
    document["roots"] = []
    return document


def _path_of(repo_root: Path | None) -> Path:
    root = Path(repo_root) if repo_root is not None else find_repo_root()
    return root / ROOTS_FILE


def _load(repo_root: Path | None) -> tuple[dict | None, str]:
    """The document, or ``(None, why-not)``. Never raises, never repairs."""
    anchor = _path_of(repo_root)
    try:
        data = json.loads(anchor.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.debug(f"[roots_file] No {ROOTS_FILE} at {anchor} — nothing declared yet")
        return None, f"{ROOTS_FILE} does not exist — run 'roots init' to create it from the template"
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.error(f"[roots_file] Unreadable {anchor}: {exc}")
        return None, f"{ROOTS_FILE} is unreadable ({exc}) — run 'roots heal' to rebuild the scaffold"
    if not isinstance(data, dict) or not isinstance(data.get("roots"), list):
        return None, f"{ROOTS_FILE} is not a roots document — run 'roots heal' to rebuild the scaffold"
    return data, ""


def _write(repo_root: Path | None, document: dict, today: str | None) -> None:
    document["metadata"]["last_updated"] = today or _today()
    anchor = _path_of(repo_root)
    anchor.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _resolve(repo_root: Path | None, raw: str) -> Path:
    """A declared spelling, as the reader would resolve it."""
    root = Path(repo_root) if repo_root is not None else find_repo_root()
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return candidate.resolve()
    except OSError as exc:
        logger.warning(f"[roots_file] Cannot resolve {candidate} ({exc}) — using it unresolved")
        return candidate


def _spell(repo_root: Path | None, resolved: Path) -> str:
    """Relative to home when it fits, absolute when it does not — POSIX-spelled either way.

    Forward slashes are the contract: the only spelling both platforms read as a path.
    """
    root = (Path(repo_root) if repo_root is not None else find_repo_root()).resolve()
    try:
        return (Path("..") / resolved.relative_to(root.parent)).as_posix()
    except ValueError:
        logger.debug(f"[roots_file] {resolved} is not a sibling of {root} — declaring it absolute")
        return resolved.as_posix()


def init_roots(repo_root: Path | None = None, today: str | None = None) -> tuple[bool, str]:
    """Render the scaffold, never over an existing file: unreadable is not absent (that is ``heal``)."""
    anchor = _path_of(repo_root)
    if anchor.exists():
        return False, f"{ROOTS_FILE} already exists at {anchor} — refusing to overwrite declarations"
    document = render_scaffold(today)
    anchor.parent.mkdir(parents=True, exist_ok=True)
    _write(repo_root, document, today)
    logger.info(f"[roots_file] Rendered {ROOTS_FILE} from template at {anchor} — no roots declared")
    json_handler.log_operation("roots_init", {"path": str(anchor)})
    return True, f"created {anchor} from {template_path().name} — no roots declared yet"


def add_root(
    repo_root: Path | None = None,
    raw_path: str = "",
    label: str = "",
    today: str | None = None,
) -> tuple[bool, str]:
    """Declare a root, refusing at WRITE time what the reader refuses at READ time."""
    document, problem = _load(repo_root)
    if document is None:
        return False, problem

    if not raw_path:
        return False, "no path given"
    resolved = _resolve(repo_root, raw_path)
    home = (Path(repo_root) if repo_root is not None else find_repo_root()).resolve()

    if not resolved.exists():
        return False, f"{raw_path} does not exist on this machine ({resolved})"
    if not resolved.is_dir():
        return False, f"{raw_path} is not a directory ({resolved})"
    if overlaps_home(resolved, home):
        return False, (f"{raw_path} overlaps AIPass home ({home}) — core and resident citizens would be counted twice")
    for row in document["roots"]:
        if isinstance(row, dict) and _resolve(repo_root, str(row.get("path", ""))) == resolved:
            return False, f"{resolved} is already declared as {row.get('path')!r}"

    document["roots"].append({"path": _spell(repo_root, resolved), "label": label or resolved.name, "status": "active"})
    _write(repo_root, document, today)
    logger.info(f"[roots_file] Declared root {resolved}")
    json_handler.log_operation("roots_add", {"root": str(resolved)})
    return True, f"declared {resolved}"


def remove_root(repo_root: Path | None = None, raw_path: str = "", today: str | None = None) -> tuple[bool, str]:
    """Retire a declaration by resolved path; the directory need not still exist."""
    document, problem = _load(repo_root)
    if document is None:
        return False, problem

    resolved = _resolve(repo_root, raw_path)
    kept = [
        row
        for row in document["roots"]
        if not (isinstance(row, dict) and _resolve(repo_root, str(row.get("path", ""))) == resolved)
    ]
    if len(kept) == len(document["roots"]):
        return False, f"{raw_path} is not declared in {ROOTS_FILE}"

    document["roots"] = kept
    _write(repo_root, document, today)
    logger.info(f"[roots_file] Retired root {resolved}")
    json_handler.log_operation("roots_remove", {"root": str(resolved)})
    return True, f"retired {resolved}"


def list_roots(repo_root: Path | None = None) -> list[dict]:
    """Every declared row plus what it resolves to; ``reachable`` shows a row the reader will drop."""
    document, _ = _load(repo_root)
    if document is None:
        return []
    rows = []
    for row in document["roots"]:
        if not isinstance(row, dict):
            rows.append({"path": repr(row), "label": "", "status": "", "resolves": None, "reachable": False})
            continue
        raw = str(row.get("path", ""))
        resolved = _resolve(repo_root, raw) if raw else None
        rows.append(
            {
                "path": raw,
                "label": row.get("label", ""),
                "status": row.get("status", ""),
                "resolves": resolved,
                "reachable": bool(resolved and resolved.is_dir() and row.get("status") == "active"),
            }
        )
    return rows


def heal(repo_root: Path | None = None, today: str | None = None) -> tuple[bool, str, list[str]]:
    """Rebuild a broken anchor as an EMPTY scaffold, loudly, on purpose.

    Never automatic: zero roots is legal, so a read-triggered rebuild would silently
    maintain nothing. Salvaged paths are returned, never re-declared; the broken
    file is preserved, not deleted.
    """
    anchor = _path_of(repo_root)
    if not anchor.exists():
        return False, f"{ROOTS_FILE} does not exist — 'roots init' creates it; heal repairs", []

    document, problem = _load(repo_root)
    if document is not None:
        return False, f"nothing to heal: {anchor} parses and carries {len(document['roots'])} row(s)", []

    raw = anchor.read_text(encoding="utf-8", errors="replace")
    salvaged = _SALVAGE.findall(raw)
    preserved = anchor.parent / CORRUPT_SUFFIX_NAME
    preserved.write_text(raw, encoding="utf-8")
    _write(repo_root, render_scaffold(today), today)

    logger.error(
        f"[roots_file] REBUILT {anchor} as an EMPTY scaffold ({problem}). "
        f"Original preserved at {preserved}. Declarations NOT restored: {salvaged or 'none found'} — "
        "re-declare them with 'roots add', because a rebuild that repopulates has re-declared for you"
    )
    json_handler.log_operation("roots_heal", {"path": str(anchor), "salvaged": salvaged})
    return True, f"rebuilt {anchor} empty; original preserved at {preserved}", salvaged
