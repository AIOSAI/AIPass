# =================== AIPass ====================
# Name: convert_registry_ops.py
# Description: Convert one registry to the stored shape: lowercase names, paths relative to its folder
# Version: 1.1.0
# Created: 2026-11-22
# Modified: 2026-11-22
# =============================================

"""Convert one *_REGISTRY.json in place: every row name lowercase, every path relative to the registry's folder.

Reference: docs/registry_and_repair.md
"""

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from aipass.prax import logger

from aipass.spawn.apps.handlers.atomic_write import atomic_write_text
from aipass.spawn.apps.handlers.json import json_handler
from aipass.spawn.apps.handlers.metadata import normalize_branch_name
from aipass.spawn.apps.handlers.registry import registry_lock

REBUILD_CURE = "drone @spawn sync-registry --rebuild"


def _plan_rows(branches, root: Path):
    """Each row's (key, row, old name, new name, old path, new path); a refusal string when one cannot convert."""
    items = list(branches.items()) if isinstance(branches, dict) else [(None, row) for row in branches]
    folded: dict[str, str] = {}
    plan = []
    for key, row in items:
        if not isinstance(row, dict):
            return f"row {key if key is not None else row!r} is not an object"
        old_name = str(row.get("name", key or ""))
        new_name = normalize_branch_name(old_name)
        if new_name in folded:
            return (
                f"rows '{folded[new_name]}' and '{old_name}' fold to one name '{new_name}'; "
                "choose which row lives, then run this again"
            )
        folded[new_name] = old_name
        old_path = str(row.get("path", ""))
        new_path = old_path
        if old_path:
            resolved = (root / old_path).resolve()
            if not resolved.is_relative_to(root):
                return f"row '{old_name}': path {old_path} is outside the registry's folder {root}"
            if Path(old_path).is_absolute():
                new_path = resolved.relative_to(root).as_posix()
        plan.append((key, row, old_name, new_name, old_path, new_path))
    return plan


def convert_registry(registry_path, confirm=False) -> dict:
    """Lowercase every row name and relativize every absolute path; a preview unless confirm.

    Each row's certificate owner and passport branch_name are lowercased in place too.
    Refused, nothing written: a missing or unreadable file, two rows folding to one name, a path outside
    the registry's folder, a signed certificate whose owner would change. Row order and every other key
    are kept; metadata gains only last_updated. With confirm a byte copy of the registry is written
    beside it first. Returns a receipt: refused, changes [{old_name, new_name, old_path, new_path}],
    files [{file, field, old, new}], skipped [{file, skipped}], copy, written."""
    registry_path = Path(registry_path)
    root = registry_path.resolve().parent
    receipt = {
        "registry": str(registry_path),
        "refused": None,
        "changes": [],
        "files": [],
        "skipped": [],
        "copy": None,
        "written": False,
    }

    def _refuse(reason):
        logger.error("[convert-registry] %s", reason)
        receipt["refused"] = f"{reason} - nothing written"
        return receipt

    with registry_lock(registry_path):
        if not registry_path.is_file():
            return _refuse(f"{registry_path} does not exist")
        try:
            document = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return _refuse(f"{registry_path.name} does not parse ({exc}); a corrupt one is rebuilt: {REBUILD_CURE}")
        branches = document.get("branches", []) if isinstance(document, dict) else None
        if not isinstance(branches, (list, dict)):
            return _refuse(f"{registry_path.name} has no branches list or object; {REBUILD_CURE}")

        plan = _plan_rows(branches, root)
        if isinstance(plan, str):
            return _refuse(plan)
        receipt["changes"] = [
            {"old_name": old_name, "new_name": new_name, "old_path": old_path, "new_path": new_path}
            for key, _row, old_name, new_name, old_path, new_path in plan
            if (old_name, old_path) != (new_name, new_path) or key not in (None, new_name)
        ]
        try:
            texts = _plan_citizen_files(plan, root, receipt)
        except _Refused as exc:
            return _refuse(str(exc))
        if not confirm or not (receipt["changes"] or texts):
            return receipt

        if receipt["changes"]:
            _write_registry(registry_path, document, branches, plan, receipt)
        for path, text in texts:
            atomic_write_text(path, text)
        receipt["written"] = True
        json_handler.log_operation(
            "registry_converted",
            data={"registry": str(registry_path), "rows": len(receipt["changes"]), "files": len(texts)},
        )
    return receipt


class _Refused(ValueError):
    """A citizen file the lane must not or cannot rewrite in place; the whole run writes nothing."""


# Each registered citizen's own copies of its name: (file under the seat, key path to the string).
CITIZEN_FIELDS = (
    (Path("artifacts") / "birth_certificate.json", ("owner",)),
    (Path(".trinity") / "passport.json", ("branch_info", "branch_name")),
)


def _plan_citizen_files(plan, root: Path, receipt: dict) -> list[tuple[Path, str]]:
    """Plan each row's certificate owner and passport branch_name; fills receipt files/skipped, returns new texts."""
    texts = []
    for _key, _row, _old, _new, _op, new_path in plan:
        if not new_path:
            continue
        for relative, keys in CITIZEN_FIELDS:
            path = root / new_path / relative
            planned = _plan_field(path, keys)
            if planned is None:
                continue
            if "skipped" in planned:
                receipt["skipped"].append(planned)
                continue
            texts.append((path, planned.pop("text")))
            receipt["files"].append(planned)
    return texts


def _plan_field(path: Path, keys: tuple[str, ...]):
    """The in-place rewrite of one name string: {file, field, old, new, text}; {file, skipped}; None when lowercase.

    Only that value's bytes change, so key order, indent and every other string stay as written."""
    field = ".".join(keys)
    if not path.is_file():
        return {"file": str(path), "skipped": "missing"}
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"file": str(path), "skipped": f"unreadable ({exc})"}
    value = data
    for key in keys:
        value = value.get(key) if isinstance(value, dict) else None
    if not isinstance(value, str):
        return {"file": str(path), "skipped": f"no {field}"}
    new = normalize_branch_name(value)
    if new == value:
        return None
    if isinstance(data, dict) and "signature" in data:
        raise _Refused(f"{path} is signed over its content; its {field} {value!r} is not rewritten")
    pattern = re.compile(rf'("{re.escape(keys[-1])}"\s*:\s*){re.escape(json.dumps(value, ensure_ascii=False))}')
    if len(pattern.findall(text)) != 1:
        raise _Refused(f"{path}: {field} {value!r} is not written once, so it cannot be rewritten in place")
    new_text = pattern.sub(lambda m: m.group(1) + json.dumps(new, ensure_ascii=False), text)
    return {"file": str(path), "field": field, "old": value, "new": new, "text": new_text}


def _write_registry(registry_path: Path, document: dict, branches, plan, receipt: dict) -> None:
    """Copy the registry byte for byte beside it, then write the converted rows atomically."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    copy = registry_path.with_name(f"{registry_path.name}.pre-convert-{stamp}")
    shutil.copy2(registry_path, copy)
    receipt["copy"] = str(copy)

    for _key, row, _old, new_name, _op, new_path in plan:
        if "name" in row:
            row["name"] = new_name
        if "path" in row:
            row["path"] = new_path
    if isinstance(branches, dict):
        document["branches"] = {new_name: row for _key, row, _old, new_name, _op, _np in plan}
    if isinstance(document.get("metadata"), dict):
        document["metadata"]["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    atomic_write_text(registry_path, json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    logger.info(
        "[convert-registry] Converted %d row(s) in %s; copy at %s", len(receipt["changes"]), registry_path, copy
    )
