# =================== AIPass ====================
# Name: backfill.py
# Description: Backfill Handler: copy each citizen's own rows from the global store into its local .chroma
# Version: 1.0.0
# Created: 2026-11-23
# Modified: 2026-11-23
# =============================================

"""
Backfill Handler

For each branch in the write scope: its global ``<branch>_local`` and ``<branch>_observations``
collections and the ``flow_plans`` chunks it owns go into its local store, as stored (ids,
embeddings, documents, metadatas), never re-embedded. A present id is never touched, so a re-run adds nothing.
Reference: docs/rollover_pipeline.md
"""

from pathlib import Path
from typing import Any, Dict, List

from aipass.prax import logger
from aipass.memory.apps.handlers.cli import caller_gate
from aipass.memory.apps.handlers.json import config_loader, json_handler
from aipass.memory.apps.handlers.intake import plans_processor
from aipass.memory.apps.handlers.monitor import detector
from aipass.memory.apps.handlers.monitor.detector import RegistryUnreadable
from aipass.memory.apps.handlers.rollover import orchestrator
from aipass.memory.apps.handlers.storage import chroma_subprocess
from aipass.memory.apps.handlers.storage.lane import CHROMA_SUBPROCESS_SCRIPT, run_json

PLANS = "flow_plans"
VERB = "rollover backfill-local"
_TIMEOUT = 900  # the global flow_plans read carries every plan's embeddings


def _chroma(operation: str, **params: Any) -> Dict[str, Any]:
    """One chroma_subprocess call; chroma is imported only in the child."""
    payload = {"operation": operation, **params}
    return run_json(CHROMA_SUBPROCESS_SCRIPT, payload, timeout=_TIMEOUT, label=f"Backfill {operation}")


def _archive_line(archive: Path | None, source: str | None) -> str | None:
    """The Branch line of the archived plan file a chunk came from, or None."""
    if archive is None or not source or Path(source).name != source:
        return None
    path = archive / source
    return plans_processor.branch_line(path.read_text(encoding="utf-8")) if path.is_file() else None


def _plan_owners(plans: Dict[str, Any]) -> List[str | None]:
    """Per global plan chunk, the resolved path of the citizen that owns it, or None.

    The ``branch`` tag first, then a Branch line in any chunk of the same file, then the archived file,
    always resolved inside the chunk's ``project``. A chunk with no ``project`` tag has no owner.
    """
    root = plans_processor._find_repo_root()
    plans_dir = config_loader.section("plans").get("path", ".backup/processed_plans")
    archives = dict(plans_processor._archives(plans_dir, root))
    groups: Dict[tuple, List[int]] = {}
    for i, meta in enumerate(plans["metadatas"]):
        meta = meta or {}
        groups.setdefault((meta.get("project"), meta.get("source_file")), []).append(i)

    owners: List[str | None] = [None] * len(plans["ids"])
    resolved: Dict[tuple, str | None] = {}
    for (project, source), rows in groups.items():
        if not project:
            continue
        metas = [plans["metadatas"][i] or {} for i in rows]
        value = next((m["branch"] for m in metas if m.get("branch")), None)
        lines = (plans_processor.branch_line(plans["documents"][i] or "") for i in rows)
        value = value or next((line for line in lines if line), None)
        value = value or _archive_line(archives.get(project), source)
        if (value, project) not in resolved:
            row = plans_processor.plan_owner(value, project, root)
            resolved[(value, project)] = str(Path(row["path"]).resolve()) if row else None
        for i in rows:
            owners[i] = resolved[(value, project)]
    return owners


def _subset(rows: Dict[str, Any], picks: List[int]) -> Dict[str, Any]:
    """The picked rows of a read, every field kept as stored."""
    fields = ("ids", "embeddings", "documents", "metadatas")
    return {"success": True, "metadata": rows.get("metadata"), **{f: [rows[f][i] for i in picks] for f in fields}}


def _copy(collection: str, rows: Dict[str, Any], store: Path, apply: bool) -> Dict[str, Any]:
    """Copy (``apply``) or count what would be copied, against the ids the local store already holds."""
    if apply:
        fields = {f: rows[f] for f in ("ids", "embeddings", "documents", "metadatas")}
        reply = _chroma(
            "add_missing", collection_name=collection, metadata=rows.get("metadata"), db_path=str(store), **fields
        )
        return {"added": reply.get("added", 0), "present": reply.get("present", 0)} if reply.get("success") else reply
    if not rows["ids"] or not store.exists():
        return {"copy": len(rows["ids"]), "present": 0}
    local = _chroma("read_collection", collection_name=collection, db_path=str(store))
    if not local.get("success"):
        return local
    present = len(set(rows["ids"]) & set(local["ids"]))
    return {"copy": len(rows["ids"]) - present, "present": present}


def _backfill_branch(
    row: Dict[str, Any], plans: Dict[str, Any], owners: List[str | None], apply: bool
) -> Dict[str, Any]:
    """One branch's report: per collection, what is (or would be) copied and what is already present."""
    name = str(row.get("name", "")).lower()
    store, reason = orchestrator.local_store_lookup(name, create=apply)
    own = (Path(row["path"]) / ".chroma").resolve()
    if store is None or store.resolve() != own:
        why = reason or f"the lookup by name lands on {store}"
        return {"branch": name, "error": f"no local store of its own ({why})"}
    if own == chroma_subprocess._DEFAULT_DB_PATH.resolve():
        return {"branch": name, "store": str(store), "skipped": "its local store is the global store"}

    mine = str(Path(row["path"]).resolve())
    picks = [i for i, owner in enumerate(owners) if owner == mine]
    sources = {f"{name}_local": None, f"{name}_observations": None, PLANS: _subset(plans, picks)}
    collections: Dict[str, Any] = {}
    for collection, rows in sources.items():
        rows = rows or _chroma("read_collection", collection_name=collection)
        result = _copy(collection, rows, store, apply) if rows.get("success") else rows
        if not result.get("success", True):
            logger.error(f"[backfill] @{name} {collection} not backfilled: {result.get('error')}")
            error = f"{collection}: {result.get('error')}"
            return {"branch": name, "store": str(store), "collections": collections, "error": error}
        collections[collection] = result
    return {"branch": name, "store": str(store), "collections": collections}


def backfill_local(branch: str | None = None, apply: bool = False) -> Dict[str, Any]:
    """Backfill every write-scope branch (or the one named) from the global store; dry-run unless ``apply``.

    @memory's seat or the verified admin only: it reads every citizen's global rows.
    """
    what = "every citizen's global rows into its local store"
    refusal = caller_gate.other_branch_refusal(VERB, None, what, act="writes" if apply else "reads")
    if refusal:
        return {"success": False, "error": refusal}
    try:
        scope = detector.write_scope()
    except RegistryUnreadable as e:
        return {"success": False, "error": f"{VERB}: {e}"}
    if branch:
        wanted = branch.strip().lstrip("@").lower()
        scope = [row for row in scope if str(row.get("name", "")).lower() == wanted]
        if not scope:
            return {"success": False, "error": f"{VERB}: @{wanted} is not in the memory write scope"}

    plans = _chroma("read_collection", collection_name=PLANS)
    if not plans.get("success"):
        return {"success": False, "error": f"{VERB}: global {PLANS} unreadable: {plans.get('error')}"}
    try:
        owners = _plan_owners(plans)
    except RegistryUnreadable as e:
        return {"success": False, "error": f"{VERB}: {e}"}

    report = [_backfill_branch(row, plans, owners, apply) for row in scope]
    unowned = owners.count(None)
    failed = [r["branch"] for r in report if "error" in r]
    json_handler.log_operation(
        "backfill_local", {"apply": apply, "branches": len(report), "failed": len(failed), "plans_unowned": unowned}
    )
    lines = [f"backfill-local - {'applied' if apply else 'dry run, nothing written (--apply writes)'}"]
    lines += [_line(r, apply) for r in report]
    lines.append(f"{PLANS} chunks with no owner in the write scope, left global only: {unowned}")
    result = {"success": not failed, "apply": apply, "branches": report, "plans_unowned": unowned, "lines": lines}
    if failed:
        result["error"] = f"{VERB}: not backfilled: {', '.join('@' + name for name in failed)} (named above)"
    return result


def _line(row: Dict[str, Any], apply: bool) -> str:
    """One branch's report line: per collection the count copied (or to copy) and the count already present."""
    if row.get("skipped"):
        return f"@{row['branch']}: skipped - {row['skipped']}"
    verb = "added" if apply else "copy"
    parts = [f"{c} {verb} {n.get(verb, 0)}, present {n['present']}" for c, n in row.get("collections", {}).items()]
    if row.get("error"):
        parts.append(f"NOT backfilled - {row['error']}")
    return f"@{row['branch']}: " + "; ".join(parts)
