# =================== AIPass ====================
# Name: adopt_citizen_ops.py
# Description: adopt-citizen handler — plan and apply moving a citizen whole into another project
# Version: 1.0.0
# Created: 2026-11-08
# Modified: 2026-11-09
# =============================================

"""Move an existing citizen, memory and registry row with ids kept, into another project root.
Reference: docs/adopt_citizen.md
"""

import errno
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

from aipass.memory.apps.modules.fleet import declared_roots
from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.spawn.apps.handlers.atomic_write import atomic_write_text
from aipass.spawn.apps.handlers.json import json_handler
from aipass.spawn.apps.handlers.passport_migration import repo_root
from aipass.spawn.apps.handlers.registry import (
    branches_as_list,
    fleet_rows,
    load_registry,
    registry_lock,
    resolve_project_credential,
    save_registry,
)

CORE_REGISTRY = "AIPASS_REGISTRY.json"
LEFTOVER = "tracked AIPass leftover; untrack before --apply"


def _find_citizen(name, home):
    """(registry, row) for name among the citizens memory's door answers; (None, None) if absent."""
    for citizen in fleet_rows(home):
        registry = citizen["registry_path"]
        if citizen["name"].lower() != name or registry is None:
            continue
        for row in branches_as_list(load_registry(registry).get("branches", [])):
            if row.get("name", "").lower() == name:
                return registry, row
    return None, None


def _run_git(target, *args):
    """One read-only git call in target."""
    return subprocess.run(["git", "-C", str(target), *args], capture_output=True, text=True, check=False)


def _git_state(target):
    """(work tree, show-prefix, exclude path, tracked set) for target; read-only git."""
    head = _run_git(target, "rev-parse", "--is-inside-work-tree", "--show-prefix", "--git-path", "info/exclude")
    lines = head.stdout.splitlines()
    if head.returncode != 0 or not lines or lines[0] != "true":
        return False, "", None, set()
    prefix, exclude = (lines[1], lines[2]) if len(lines) == 3 else ("", lines[-1])
    tracked = set(_run_git(target, "ls-files", "-z").stdout.split("\0")) - {""}
    return True, prefix, (target / exclude).resolve(), tracked


def _open_dispatches(branch):
    """Ids of dispatches (auto_execute) in the citizen's inbox that are not closed."""
    inbox = branch / ".ai_mail.local" / "inbox.json"
    data = json_handler.read_json(inbox) if inbox.is_file() else None
    messages = data.get("messages", []) if isinstance(data, dict) else []
    return [m.get("id", "?") for m in messages if m.get("auto_execute") is True and m.get("status") != "closed"]


def _flow_rows(home, source_dir):
    """Plan ids whose file_path sits under the source dir, read from @flow's registries."""
    ids = []
    for reg in sorted((home / "src" / "aipass" / "flow" / "flow_json").glob("*plan_registry.json")):
        data = json_handler.read_json(reg) or {}
        prefix = reg.name.split("_")[0].upper()
        for number, plan in (data.get("plans") or {}).items():
            path = Path(plan.get("file_path") or "/")
            if path.is_relative_to(source_dir):
                ids.append(f"{prefix}-{number}")
    return ids


def _follow_ups(home, dest, source_dir, source_root, left_empty):
    """Records spawn does not write, by owner."""
    target = dest.parent
    out = [{"owner": "@flow", "what": f"re-point {p} file_path into {dest}"} for p in _flow_rows(home, source_dir)]
    if not target.is_relative_to(home) and target not in declared_roots(home):
        out.append({"owner": "@memory", "what": f"roots add {target} (drone resolves the name only after this)"})
    trust_file = Path.home() / ".aipass" / "trusted_projects.json"
    trusted = (json_handler.read_json(trust_file) or {}).get("projects", {}) if trust_file.is_file() else {}
    if str(target) not in trusted:
        out.append({"owner": "@hooks", "what": f"trust: enrol {target}"})
    if left_empty and str(source_root) in trusted:
        out.append({"owner": "@hooks", "what": f"trust: revoke {source_root} (no citizens left)"})
    if left_empty:
        out.append({"owner": "@devpulse", "what": f"archive {source_root} (no citizens left)"})
    return out


def plan_adoption(citizen, target_root):
    """Read everything, write nothing: the full adopt-citizen preview as a dict. Ready when blocked is empty."""
    name = citizen.lstrip("@").lower()
    home = repo_root().resolve()
    target = Path(target_root).expanduser().resolve()
    plan = {
        "citizen": name,
        "source_dir": None,
        "source_registry": None,
        "target_root": str(target),
        "dest_dir": str(target / name),
        "registry": {"path": None, "action": None},
        "class": {"from": None, "to": None},
        "paths": [],
        "follow_ups": [],
        "blocked": [],
        "applied": False,
        "proof": {},
    }
    blocked, paths = plan["blocked"], plan["paths"]

    src_reg, row = _find_citizen(name, home)
    if src_reg is None or row is None:
        blocked.append(f"'{name}' is not a citizen memory's door answers ({CORE_REGISTRY}, residents, declared roots)")
        return plan
    plan["source_registry"] = str(src_reg)
    if src_reg.name == CORE_REGISTRY:
        blocked.append(f"'{name}' is a core citizen ({CORE_REGISTRY}); a core citizen never leaves AIPass")
        return plan
    source_root = src_reg.resolve().parent
    source_dir = (source_root / row.get("path", "")).resolve()
    plan["source_dir"] = str(source_dir)
    passport_path = source_dir / ".trinity" / "passport.json"
    passport = json_handler.read_json(passport_path) if passport_path.is_file() else None
    if not isinstance(passport, dict):
        blocked.append(f"no readable passport at {passport_path}")
        return plan
    if passport.get("citizenship", {}).get("citizen_id") != row.get("registry_id"):
        blocked.append(f"the passport at {passport_path} is not the citizen of row '{row.get('name')}'")
    blocked.extend(f"open dispatch {mid} in {name}'s inbox; close it first" for mid in _open_dispatches(source_dir))

    if not target.is_dir():
        blocked.append(f"target root {target} does not exist or is not a directory")
        return plan
    if target.is_relative_to(source_root) or source_root.is_relative_to(target):
        blocked.append(f"target root {target} and source project {source_root} overlap")
        return plan
    dest = target / name

    existing = _registry_in_all(target)
    if len(existing) > 1:
        blocked.append(f"{target} holds {len(existing)} *_REGISTRY.json files; exactly one or none")
        return plan
    if existing:
        reg_path, reg_action = existing[0], "edit"
        reg_doc = load_registry(reg_path)
        rows = branches_as_list(reg_doc.get("branches", []))
        if any(r.get("name", "").lower() == name or r.get("registry_id") == row.get("registry_id") for r in rows):
            blocked.append(f"{reg_path.name} already has a row named {name} or with its registry_id")
        reg_id = reg_doc.get("metadata", {}).get("id", "")
    else:
        reg_path, reg_action = target / f"{re.sub(r'[^A-Za-z0-9]', '_', target.name).upper()}_REGISTRY.json", "create"
        rows, reg_id = [], resolve_project_credential(reg_path)
    lock = target / f".{reg_path.stem}.lock"
    plan["registry"] = {"path": reg_path.name, "action": reg_action}
    becomes_owner = not any(r.get("owner") is True for r in rows)
    old_class = passport.get("identity", {}).get("citizen_class")
    plan["class"] = {"from": old_class, "to": "manager" if becomes_owner else old_class}

    work_tree, prefix, exclude, tracked = _git_state(target)
    reasons = {reg_path.name: "registry", lock.name: "registry lock", f"{name}/": "destination"}
    for rel, what in reasons.items():
        if any(t == rel or t.startswith(rel) and rel.endswith("/") for t in tracked):
            paths.append({"action": "clash", "path": rel, "reason": f"tracked; spawn would write the {what}"})
    if any(t.startswith(".aipass/") for t in tracked):
        paths.append({"action": "clash", "path": ".aipass/", "reason": LEFTOVER})
    if "AGENTS.md" in tracked:
        paths.append({"action": "skip", "path": "AGENTS.md", "reason": "tracked client file, untouched"})
    if dest.exists():
        paths.append({"action": "clash", "path": f"{name}/", "reason": f"{dest} already exists"})

    noun = "new project registry, metadata.id minted" if reg_action == "create" else "row appended"
    paths.append({"action": reg_action, "path": reg_path.name, "reason": noun})
    if not lock.exists():
        paths.append({"action": "create", "path": lock.name, "reason": "registry lock"})
    paths.append({"action": "move", "path": f"{name}/", "reason": f"from {source_dir}, whole"})
    fields = "branch_info.path, citizenship.registry_path/registry_id/residency"
    fields += ", identity.citizen_class" if plan["class"]["to"] != old_class else ""
    paths.append({"action": "edit", "path": f"{name}/.trinity/passport.json", "reason": f"{fields}; ids kept"})
    lines = [f"/{prefix}{reg_path.name}", f"/{prefix}{lock.name}", f"/{prefix}{name}/"]
    if work_tree and exclude is not None:
        present = set(exclude.read_text(encoding="utf-8").splitlines()) if exclude.is_file() else set()
        lines = [x for x in lines if x not in present]
        rel_exclude = os.path.relpath(exclude, target).replace(os.sep, "/")
        if lines:
            paths.append({"action": "append", "path": rel_exclude, "reason": " ".join(lines)})
    else:
        lines = []
        paths.append({"action": "skip", "path": ".git/info/exclude", "reason": "target is not a git work tree"})
    paths.append({"action": "edit", "path": str(src_reg), "reason": f"row {row.get('name')} removed"})

    blocked.extend(f"clash: {p['path']} ({p['reason']})" for p in paths if p["action"] == "clash")
    left_empty = len(branches_as_list(load_registry(src_reg).get("branches", []))) == 1
    plan["follow_ups"] = _follow_ups(home, dest, source_dir, source_root, left_empty)
    plan["_apply"] = {
        "row": row,
        "reg_path": str(reg_path),
        "reg_id": reg_id,
        "lock": str(lock),
        "owner": becomes_owner,
        "exclude": str(exclude) if lines else None,
        "lines": lines,
        "residency": "resident" if target.is_relative_to(home) else "external",
    }
    return plan


def _registry_in_all(root):
    """Every *_REGISTRY.json directly in root, the suffix checked case-sensitively."""
    return sorted(p for p in root.glob("*_REGISTRY.json") if p.name.endswith("_REGISTRY.json"))


def _snapshot(paths):
    """Bytes of each path, None when absent — what a restore puts back."""
    return {p: (p.read_bytes() if p.is_file() else None) for p in paths}


def _put_back(snapshot):
    """Restore each file to its snapshot; a file that did not exist is removed again."""
    for path, data in snapshot.items():
        if data is None:
            path.unlink(missing_ok=True)
        else:
            atomic_write_text(path, data.decode("utf-8"))


def _rewrite_registry(reg_path, change):
    """Load, change, save one registry under its lock; OSError when the save fails."""
    with registry_lock(reg_path):
        doc = load_registry(reg_path)
        change(doc)
        doc.setdefault("metadata", {})["total_branches"] = len(branches_as_list(doc.get("branches", [])))
        if not save_registry(reg_path, doc):
            raise OSError(f"{reg_path} could not be written")


def apply_adoption(plan):
    """Execute a ready plan; on a failure after the move, everything goes back. Returns the plan, updated."""
    if plan["blocked"] or "_apply" not in plan:
        return plan
    a = plan["_apply"]
    name, source, dest = plan["citizen"], Path(plan["source_dir"]), Path(plan["dest_dir"])
    reg_path, src_reg = Path(a["reg_path"]), Path(plan["source_registry"])
    passport_text = (source / ".trinity" / "passport.json").read_text(encoding="utf-8")
    files = [reg_path, Path(a["lock"]), src_reg] + ([Path(a["exclude"])] if a["exclude"] else [])
    before = _snapshot(files)
    moved = False
    try:
        if plan["registry"]["action"] == "create":
            today = datetime.now().strftime("%Y-%m-%d")
            meta = {"id": a["reg_id"], "name": reg_path.stem.removesuffix("_REGISTRY"), "version": "1.0.0"}
            meta.update(created=today, last_updated=today, total_branches=0)
            with registry_lock(reg_path):
                if not save_registry(reg_path, {"metadata": meta, "branches": []}):
                    raise OSError(f"{reg_path} could not be created")
        try:
            os.rename(source, dest)
        except OSError as exc:
            if exc.errno == errno.EXDEV:
                raise OSError(f"{source} and {dest} are on different filesystems; no copy fallback") from exc
            raise
        moved = True
        passport_path = dest / ".trinity" / "passport.json"
        passport = json_handler.read_json(passport_path)
        if not isinstance(passport, dict):
            raise ValueError(f"passport at {passport_path} could not be read")
        passport.setdefault("branch_info", {})["path"] = name
        passport.setdefault("citizenship", {}).update(
            registry_path=reg_path.name, registry_id=a["reg_id"], residency=a["residency"]
        )
        passport.setdefault("identity", {})["citizen_class"] = plan["class"]["to"]
        if not json_handler.write_json(passport_path, passport):
            raise OSError(f"passport at {passport_path} could not be written")
        new_row = {**a["row"], "path": name}
        if a["owner"]:
            new_row["owner"] = True
        _rewrite_registry(reg_path, lambda d: d.setdefault("branches", []).append(new_row))
        key = a["row"].get("registry_id")
        _rewrite_registry(src_reg, lambda d: d.update(branches=_without(d.get("branches"), key)))
        if a["exclude"]:
            exclude = Path(a["exclude"])
            exclude.parent.mkdir(parents=True, exist_ok=True)
            current = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
            sep = "" if not current or current.endswith("\n") else "\n"
            atomic_write_text(exclude, current + sep + "\n".join(a["lines"]) + "\n")
    except (OSError, ValueError, AttributeError) as exc:
        if moved:
            os.rename(dest, source)
            atomic_write_text(source / ".trinity" / "passport.json", passport_text)
        _put_back(before)
        logger.error("[adopt-citizen] %s failed and was restored: %s", name, exc)
        plan["blocked"].append(f"apply failed and was restored: {exc}")
        return plan

    plan["applied"] = True
    plan["proof"] = _prove(name, dest, reg_path)
    plan["blocked"] += [f"proof failed: {k}" for k, v in plan["proof"].items() if v is False]
    logger.info("[adopt-citizen] Moved %s -> %s (%s)", source, dest, reg_path.name)
    json_handler.log_operation("citizen_adopted", data={"citizen": name, "dest": str(dest), "registry": reg_path.name})
    return plan


def _without(branches, registry_id):
    """The rows minus the one carrying registry_id."""
    return [r for r in branches_as_list(branches) if r.get("registry_id") != registry_id]


def _prove(name, dest, reg_path):
    """Re-read what was written: passport citizen_id == row registry_id, and the registry resolves the name."""
    passport = json_handler.read_json(dest / ".trinity" / "passport.json") or {}
    rows = branches_as_list(load_registry(reg_path).get("branches", []))
    row = next((r for r in rows if r.get("name", "").lower() == name), {})
    citizen_id = passport.get("citizenship", {}).get("citizen_id")
    return {
        "citizen_id_matches_row": bool(row) and citizen_id == row.get("registry_id"),
        "registry_resolves_dest": bool(row) and (reg_path.parent / row.get("path", "")).resolve() == dest.resolve(),
        "drone_resolution": "not proven here: drone finds the name once its root is declared (see follow-ups)",
    }
