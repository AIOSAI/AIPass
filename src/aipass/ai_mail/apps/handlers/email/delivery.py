# =================== AIPass ====================
# Name: delivery.py
# Description: Email Delivery Handler
# Version: 3.5.1
# Created: 2025-12-02
# Modified: 2026-10-17
# =============================================

"""
Email Delivery Handler

Reference: docs/sending_and_delivery.md
"""

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Dict, Tuple, List, Optional, Callable

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.paths import REGISTRY_SUFFIX, find_repo_root, find_project_root, registries_in
from aipass.ai_mail.apps.handlers.registry.read import get_all_branches

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")


_REPO_ROOT = find_repo_root()

_INBOX_LOCK = None


def _load_caller_project_branches(caller_cwd: str) -> Dict[str, str]:
    """Load branches from the caller's project registry."""
    from aipass.ai_mail.apps.handlers.registry.read import get_caller_project_branches

    return get_caller_project_branches(caller_cwd)


def _auto_register_contact(email: str, inbox_file: Path) -> None:
    """Auto-register a recipient in the contacts address book after successful delivery."""
    try:
        from aipass.ai_mail.apps.handlers.email.contacts import register_contact

        name_key = email.lstrip("@").lower()
        register_contact(name_key, "AIPass", str(inbox_file))
    except Exception as e:
        logger.warning("[delivery] _auto_register_contact(%s) failed: %s", email, e)


def _auto_register_sender(branch_name: str, caller_cwd: str) -> None:
    """Auto-register a sender in contacts when called from an external project."""
    try:
        candidate = Path(caller_cwd)
        for path in [candidate] + list(candidate.parents)[:5]:
            inbox_file = path / ".ai_mail.local" / "inbox.json"
            if inbox_file.exists():
                from aipass.ai_mail.apps.handlers.email.contacts import register_contact

                name_key = branch_name.lstrip("@").lower()
                register_contact(name_key, "", str(inbox_file))
                return
    except Exception as e:
        logger.warning("[delivery] _auto_register_sender(%s) failed: %s", branch_name, e)


def _get_inbox_lock():
    """Lazy import inbox_lock context manager."""
    global _INBOX_LOCK
    if _INBOX_LOCK is None:
        from aipass.ai_mail.apps.handlers.email.inbox_lock import inbox_lock

        _INBOX_LOCK = inbox_lock
    return _INBOX_LOCK


def _migrate_inbox_format(inbox_data: Dict, inbox_file: Path) -> Dict:
    """Auto-migrate old inbox format to v2 schema."""
    migrated = False

    if isinstance(inbox_data, list):
        inbox_data = {"messages": inbox_data}
        migrated = True

    if "inbox" in inbox_data and "messages" not in inbox_data:
        old_messages = inbox_data.pop("inbox", [])
        inbox_data["messages"] = old_messages if isinstance(old_messages, list) else []
        migrated = True

    if "messages" not in inbox_data:
        inbox_data["messages"] = []
        migrated = True

    if "mailbox" not in inbox_data:
        inbox_data["mailbox"] = "inbox"
        migrated = True

    if "total_messages" not in inbox_data:
        inbox_data["total_messages"] = len(inbox_data["messages"])
        migrated = True

    if "unread_count" not in inbox_data:
        inbox_data["unread_count"] = sum(
            1
            for msg in inbox_data["messages"]
            if msg.get("status") == "new" or (msg.get("status") is None and not msg.get("read", False))
        )
        migrated = True

    if migrated:
        try:
            with open(inbox_file, "w", encoding="utf-8") as f:
                json.dump(inbox_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning("[delivery] _migrate_inbox_format() failed to persist migration for %s: %s", inbox_file, e)
            return inbox_data

    return inbox_data


def _is_private_branch_email(email: str) -> bool:
    """Check if email belongs to a private branch."""
    registry_path = _REPO_ROOT / "PRIVATE_BRANCH_REGISTRY.json"
    if not registry_path.exists():
        return False
    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            registry = json.load(f)
        for branch in registry.get("branches", []):
            if branch.get("email", "") == email:
                return True
    except (json.JSONDecodeError, IOError) as e:
        logger.warning("[delivery] _is_private_branch_email(%s) failed: %s", email, e)
    return False


def _resolve_reply_path() -> str:
    """Detect the caller's ai_mail inbox path from AIPASS_CALLER_CWD env var."""
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")
    if not caller_cwd:
        return ""
    candidate = Path(caller_cwd)
    for path in [candidate] + list(candidate.parents)[:5]:
        inbox = path / ".ai_mail.local" / "inbox.json"
        if inbox.exists():
            return str(inbox)
    return ""


def _path_is_inside(candidate: Path, root: Path) -> bool:
    """True when candidate sits within root."""
    try:
        resolved_candidate = Path(candidate).resolve()
        resolved_root = Path(root).resolve()
    except OSError as exc:
        logger.warning("[delivery] could not resolve %s against %s: %s", candidate, root, exc)
        return False

    return resolved_candidate.is_relative_to(resolved_root)


def _reply_proof_mailboxes(email_data: Optional[Dict], sender_root: Optional[Path]) -> List[Path]:
    """Where a reply's proof may live, most reliable source first.

    reply.py's stamped reply_path first (the CWD walk misses a seat below the caller), and only
    when it lands inside the sender's own project, so a crafted one cannot nominate any mailbox.
    """
    candidates: List[Path] = []

    stamped = str((email_data or {}).get("reply_path", "")).strip()
    if stamped:
        try:
            resolved = Path(stamped).resolve()
        except (OSError, ValueError) as exc:
            logger.warning("[delivery] unusable reply_path %s: %s", stamped, exc)
            resolved = None
        if resolved is not None:
            if sender_root is None or _path_is_inside(resolved, sender_root):
                candidates.append(resolved)
            else:
                logger.warning(
                    "[delivery] reply_path %s sits outside the sender's project %s - not accepted as proof",
                    resolved,
                    sender_root,
                )

    derived = _resolve_reply_path()
    if derived:
        candidates.append(Path(derived))

    seen = set()
    ordered: List[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            ordered.append(candidate)
    return ordered


def _is_sanctioned_reply(email_data: Optional[Dict], to_branch: str, sender_root: Optional[Path] = None) -> bool:
    """True when this outbound mail is a reply to something the recipient sent us.

    Proof is the referenced mail in the sender's own mailbox naming the recipient in ``from`` or
    ``reply_to`` (reply.py routes to ``reply_to or from``). Fails closed on anything unproven.
    """
    in_reply_to = (email_data or {}).get("in_reply_to", "")
    if not in_reply_to or not to_branch:
        return False

    target = str(to_branch).strip().lower()
    for caller_inbox in _reply_proof_mailboxes(email_data, sender_root):
        try:
            with open(caller_inbox, "r", encoding="utf-8") as f:
                messages = json.load(f).get("messages", [])
        except Exception as exc:
            logger.warning("[delivery] reply proof unreadable at %s: %s", caller_inbox, exc)
            continue

        for msg in messages:
            if not isinstance(msg, dict) or msg.get("id") != in_reply_to:
                continue
            sanctioned = {str(msg.get("from", "")).strip().lower(), str(msg.get("reply_to") or "").strip().lower()}
            sanctioned.discard("")
            if target in sanctioned:
                return True
            logger.warning("[delivery] reply proof %s does not name %s - refused", in_reply_to, target)
            return False

    logger.warning("[delivery] reply proof not found: no message %s in the sender's mailbox(es)", in_reply_to)
    return False


def _refuse_unverified_external(recipient_path: Path, to_branch: str, caller_cwd: str) -> Tuple[bool, str]:
    """Fail closed for an external-tier recipient when the sender cannot be placed.

    No reply exemption here: with no sender project a stamped reply_path could name any mailbox.
    """
    from aipass.ai_mail.apps.handlers.users import verified_caller

    if verified_caller.is_verified_admin_caller():
        logger.info("[delivery] external tier exempted for verified admin with no sender project: %s", to_branch)
        return False, ""

    recipient_root = find_project_root(recipient_path)
    where = f"external root '{recipient_root.name}'" if recipient_root else "a declared external root"
    why = (
        f"AIPASS_CALLER_CWD {caller_cwd} sits in no project" if caller_cwd else "no AIPASS_CALLER_CWD reached delivery"
    )
    logger.warning("[delivery] external-tier mail refused, sender unverifiable (%s): %s", why, to_branch)
    return True, (
        f"Out of scope: {to_branch} is a citizen of {where}, outside the AIPass fleet, and this sender "
        f"cannot be verified ({why}), so there is no project to check it against. Unverified mail never "
        f"crosses into an external root (#754) — only @devpulse's verified-admin lane may initiate there. "
        f"From your own seat you may reply to an existing message from {to_branch}."
    )


def _check_cross_project_boundary(
    recipient_path: Path,
    sender_email: str,
    email_data: Optional[Dict] = None,
    to_branch: str = "",
    external_tier: bool = False,
) -> Tuple[bool, str]:
    """Refuse mail when sender and recipient are in different projects.

    A sender with no project passes (@trigger's in-process sends carry no caller cwd), except to an
    external-tier recipient, which fails closed: this is its last wall (#754).
    """
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")
    sender_root = find_project_root(Path(caller_cwd)) if caller_cwd else None
    if sender_root is None:
        if external_tier:
            return _refuse_unverified_external(recipient_path, to_branch, caller_cwd)
        return False, ""

    recipient_root = find_project_root(recipient_path)
    if recipient_root is None:
        return False, ""

    if sender_root == recipient_root:
        return False, ""

    # Everything below is a refusal, so only here are the exemptions worth their file reads.
    if _is_sanctioned_reply(email_data, to_branch, sender_root=sender_root):
        logger.info("[delivery] cross-project boundary exempted for reply: %s -> %s", sender_email, to_branch)
        return False, ""

    from aipass.ai_mail.apps.handlers.users import verified_caller

    if verified_caller.is_verified_admin_caller():
        logger.info(
            "[delivery] cross-project boundary exempted for verified admin: %s -> %s",
            sender_root,
            recipient_root,
        )
        return False, ""

    sender_name = sender_email or os.environ.get("AIPASS_CALLER_BRANCH", "unknown")
    logger.warning(
        "[delivery] cross-project mail refused: sender root %s != recipient root %s",
        sender_root,
        recipient_root,
    )
    return True, (
        f"Cross-project mail refused: {sender_name} (project: {sender_root.name}) "
        f"cannot send to this branch (project: {recipient_root.name}). "
        f"Use the feedback channel for cross-project communication."
    )


def _hosted_project_name(branch_path: str) -> str:
    """Name the ``projects/<name>`` directory a hosted branch path sits under."""
    try:
        rel = Path(branch_path).resolve().relative_to((_REPO_ROOT / "projects").resolve())
        return rel.parts[0]
    except (ValueError, OSError, IndexError) as exc:
        logger.warning("[delivery] hosted branch path %s is not under projects/: %s", branch_path, exc)
        return "unknown"


def _describe_unresolved_address(to_branch: str, known_count: int) -> str:
    """Explain why an address did not resolve, without widening resolution.

    Returns a string only: the caller's branch map is never updated, so the wall is described, not opened.
    """
    fallback = f"Unknown branch email: {to_branch} (available: {known_count} branches)"

    try:
        from aipass.ai_mail.apps.handlers.registry.read import get_project_tree_branches

        hosted = get_project_tree_branches(_REPO_ROOT)
    except Exception as exc:
        logger.warning("[delivery] could not read hosted project registries to explain refusal: %s", exc)
        return fallback

    hosted_path = hosted.get(to_branch)
    if not hosted_path:
        return fallback

    project = _hosted_project_name(hosted_path)
    logger.info("[delivery] out-of-scope address refused: %s (hosted project: %s)", to_branch, project)
    return (
        f"Out of scope: {to_branch} is a citizen of hosted project '{project}', not the AIPass "
        f"fleet ({known_count} branches in scope). Fleet-to-project mail is replies-only — "
        f"only @devpulse's verified-admin lane may initiate. Reply to an "
        f"existing message from {to_branch}, or use the feedback channel."
    )


def _coerce_updates(value) -> int:
    """Read a stored ``updates`` counter defensively, defaulting to 1."""
    try:
        count = int(value)
    except (TypeError, ValueError):
        logger.warning("[delivery] unreadable updates counter %r — restarting at 1", value)
        return 1
    return count if count >= 1 else 1


def _find_upsert_target(messages: List[Dict], from_addr: str, upsert_key: str) -> Optional[Dict]:
    """Find the open message this upsert should rewrite."""
    for msg in messages:
        if msg.get("upsert_key") != upsert_key:
            continue
        if msg.get("from") != from_addr:
            continue
        if msg.get("status") == "closed":
            continue
        return msg
    return None


def _apply_upsert_update(existing: Dict, email_data: Dict) -> Dict:
    """Rewrite *existing* in place with the fresh render and a bumped counter.

    Status is preserved and auto_execute forced off: an update never re-marks new or wakes anything.
    """
    existing["subject"] = email_data["subject"]
    existing["message"] = email_data["message"]
    existing["last_updated"] = email_data["timestamp"]
    existing["updates"] = _coerce_updates(existing.get("updates")) + 1
    existing["auto_execute"] = False
    return existing


def deliver_email_to_branch(
    to_branch: str, email_data: Dict, on_delivered: Optional[Callable] = None, upsert_key: Optional[str] = None
) -> Tuple[bool, str]:
    """Deliver email to target branch's .ai_mail.local/inbox.json file.

    on_delivered is called as (branch_path, new_count, opened_count, total). An upsert reports
    back through email_data["upsert_action"] ("created" or "updated").
    """
    json_handler.log_operation("deliver_email", {"to": to_branch, "subject": email_data.get("subject", "")})

    # drone's @ resolution may hand in a path instead of an address.
    if to_branch.startswith("/") or Path(to_branch).is_absolute():
        branches_list = get_all_branches()
        path_to_email = {b["path"]: b["email"] for b in branches_list}
        if to_branch in path_to_email:
            to_branch = path_to_email[to_branch]
        else:
            sorted_branches = sorted(branches_list, key=lambda b: len(b["path"]), reverse=True)
            matched = False
            for b in sorted_branches:
                if to_branch.startswith(b["path"] + "/") or to_branch == b["path"]:
                    to_branch = b["email"]
                    matched = True
                    break
            if not matched:
                return False, f"Could not resolve path to email: {to_branch}"

    all_branches = get_all_branches()
    branches = {b["email"]: b["path"] for b in all_branches}

    if to_branch not in branches:
        # get_all_branches answers [] for an unreadable registry too: before the map widens,
        # an AIPass name must not read as absent and be served to another root's namesake.
        from aipass.ai_mail.apps.handlers.registry.read import RegistryUnreadable, check_registry_readable

        try:
            check_registry_readable(_REPO_ROOT / "AIPASS_REGISTRY.json")
        except RegistryUnreadable as e:
            logger.warning("[delivery] AIPass registry unreadable for %s: %s", to_branch, e)
            return False, f"AIPass registry unreadable, {to_branch} not resolved: {e}"
        caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")
        if caller_cwd:
            try:
                caller_branches = _load_caller_project_branches(caller_cwd)
            except RegistryUnreadable as e:
                logger.warning("[delivery] caller's project registry unreadable for %s: %s", to_branch, e)
                return False, f"Caller's project registry unreadable, {to_branch} not resolved: {e}"
            branches.update(caller_branches)

    if to_branch not in branches:
        # Hosted projects: gated, an unverified caller's map never widens.
        from aipass.ai_mail.apps.handlers.users import verified_caller

        if verified_caller.is_verified_admin_caller():
            from aipass.ai_mail.apps.handlers.registry.read import RegistryUnreadable, get_project_tree_branches

            try:
                branches.update(get_project_tree_branches(_REPO_ROOT))
            except RegistryUnreadable as e:
                logger.warning("[delivery] hosted project registry unreadable for %s: %s", to_branch, e)
                return False, f"Hosted project registry unreadable, {to_branch} not resolved: {e}"

    via_external = False
    if to_branch not in branches:
        # External tier last, in wake.resolve_branch's order; ungated (declaration is the
        # credential), so the boundary check must be TOLD this tier answered (#754).
        from aipass.ai_mail.apps.handlers.registry.read import get_external_branches

        try:
            branches.update(get_external_branches(_REPO_ROOT))
        except Exception as e:
            # Caught at delivery's door so every caller keeps the (False, message) shape.
            logger.warning("[delivery] external citizen tier unavailable for %s: %s", to_branch, e)
            return False, f"External citizen tier unavailable, {to_branch} not resolved: {e}"
        via_external = to_branch in branches

    if to_branch not in branches:
        return False, _describe_unresolved_address(to_branch, len(branches))

    sender_email = email_data.get("from", "")
    if _is_private_branch_email(to_branch) and sender_email != to_branch:
        return False, f"Cannot deliver to private branch: {to_branch}"

    raw_path = branches[to_branch]
    branch_path = Path(raw_path)
    if not branch_path.is_absolute():
        branch_path = (_REPO_ROOT / branch_path).resolve()

    refused, refusal_msg = _check_cross_project_boundary(
        branch_path, sender_email, email_data=email_data, to_branch=to_branch, external_tier=via_external
    )
    if refused:
        return False, refusal_msg

    if branch_path == Path("/") or branch_path == _REPO_ROOT:
        inbox_file = _REPO_ROOT / ".ai_mail.local" / "inbox.json"
    else:
        inbox_file = branch_path / ".ai_mail.local" / "inbox.json"

    if not inbox_file.exists():
        try:
            mailbox_dir = inbox_file.parent
            mailbox_dir.mkdir(parents=True, exist_ok=True)
            (mailbox_dir / "sent").mkdir(exist_ok=True)
            inbox_data_init = {"mailbox": "inbox", "total_messages": 0, "unread_count": 0, "messages": []}
            with open(inbox_file, "w", encoding="utf-8") as f:
                json.dump(inbox_data_init, f, indent=2)
        except Exception as e:
            logger.warning("[delivery] auto-provision inbox failed for %s: %s", to_branch, e)
            return False, f"Failed to auto-provision inbox for {to_branch}: {e}"

    try:
        with _get_inbox_lock()(inbox_file):
            try:
                with open(inbox_file, "r", encoding="utf-8") as f:
                    inbox_data = json.load(f)
            except Exception as e:
                logger.warning("[delivery] failed to read inbox %s: %s", inbox_file, e)
                return False, f"Failed to read inbox: {e}"

            inbox_data = _migrate_inbox_format(inbox_data, inbox_file)

            effective_key = upsert_key if upsert_key is not None else email_data.get("upsert_key")
            existing = None
            delivered_id = ""
            if effective_key:
                existing = _find_upsert_target(inbox_data["messages"], email_data["from"], effective_key)

            if existing is not None:
                _apply_upsert_update(existing, email_data)
                email_data["upsert_action"] = "updated"
                updated_in_place = True
                logger.info(
                    "[delivery] upsert '%s' updated message %s for %s (updates=%s)",
                    effective_key,
                    existing.get("id"),
                    to_branch,
                    existing.get("updates"),
                )
            else:
                updated_in_place = False
                message = {
                    "id": str(uuid.uuid4())[:8],
                    "timestamp": email_data["timestamp"],
                    "from": email_data["from"],
                    "from_name": email_data["from_name"],
                    "subject": email_data["subject"],
                    "message": email_data["message"],
                    "status": "new",
                    "auto_execute": email_data.get("auto_execute", False),
                    "priority": email_data.get("priority", "normal"),
                }

                # sent_id links this copy to the sender's sent/ record; the id above is per-mailbox.
                if email_data.get("id"):
                    message["sent_id"] = email_data["id"]

                if email_data.get("reply_to"):
                    message["reply_to"] = email_data["reply_to"]

                if email_data.get("dispatched_to"):
                    message["dispatched_to"] = email_data["dispatched_to"]

                reply_path = email_data.get("reply_path") or _resolve_reply_path()
                if reply_path:
                    message["reply_path"] = reply_path

                if effective_key:
                    message["upsert_key"] = effective_key
                    message["updates"] = 1
                    email_data["upsert_action"] = "created"

                inbox_data["messages"].insert(0, message)
                delivered_id = message["id"]

            from aipass.ai_mail.apps.handlers.email.inbox_cleanup import sweep_closed

            sweep_closed(inbox_data, inbox_file.parent)

            inbox_data["total_messages"] = len(inbox_data["messages"])
            messages = inbox_data["messages"]
            new_count = sum(
                1
                for msg in messages
                if msg.get("status") == "new" or (msg.get("status") is None and not msg.get("read", False))
            )
            opened_count = sum(1 for msg in messages if msg.get("status") == "opened")
            inbox_data["unread_count"] = new_count

            try:
                with open(inbox_file, "w", encoding="utf-8") as f:
                    json.dump(inbox_data, f, indent=2, ensure_ascii=False)
            except Exception as e:
                logger.warning("[delivery] failed to write inbox %s: %s", inbox_file, e)
                return False, f"Failed to write inbox: {e}"

    except OSError as e:
        logger.warning("[delivery] failed to acquire inbox lock for %s: %s", to_branch, e)
        return False, f"Failed to acquire inbox lock: {e}"

    _auto_register_contact(to_branch, inbox_file)

    caller_branch = os.environ.get("AIPASS_CALLER_BRANCH", "")
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")
    if caller_branch and caller_cwd:
        _auto_register_sender(caller_branch, caller_cwd)

    # An in-place update stays silent: one feed line per repeat is the stacking problem again.
    if not updated_in_place:
        _emit_notification_event(
            email_data["from"],
            to_branch,
            email_data["subject"],
            email_data.get("message", ""),
            address=_mail_address(delivered_id, to_branch, branch_path),
        )

    if on_delivered:
        try:
            on_delivered(branch_path, new_count, opened_count, inbox_data["total_messages"])
        except Exception as e:
            logger.warning("[delivery] on_delivered callback failed for %s: %s", to_branch, e)
            return True, ""

    return True, ""


def deliver_to_inbox_file(inbox_file: Path, email_data: Dict) -> Tuple[bool, str, str]:
    """Write *email_data* to an inbox.json file and fire a notification event.

    The one direct-path delivery (reply.py's cross-project lane). Returns (success, error, message id).
    """
    if not inbox_file.exists():
        return False, f"inbox not found: {inbox_file}", ""

    try:
        with _get_inbox_lock()(inbox_file):
            try:
                with open(inbox_file, "r", encoding="utf-8") as fh:
                    inbox_data = json.load(fh)
            except Exception as exc:
                logger.warning("[delivery] deliver_to_inbox_file read failed %s: %s", inbox_file, exc)
                return False, f"Failed to read inbox: {exc}", ""

            inbox_data = _migrate_inbox_format(inbox_data, inbox_file)

            reply_id = str(uuid.uuid4())[:8]
            email_data = dict(email_data)
            # sent_id is stamped in both lanes, so tracing never depends on which lane delivered.
            if email_data.get("id"):
                email_data.setdefault("sent_id", email_data["id"])
            email_data.setdefault("id", reply_id)
            reply_id = email_data["id"]

            inbox_data.setdefault("messages", []).insert(0, email_data)

            from aipass.ai_mail.apps.handlers.email.inbox_cleanup import sweep_closed

            sweep_closed(inbox_data, inbox_file.parent)

            inbox_data["total_messages"] = len(inbox_data["messages"])
            inbox_data["unread_count"] = sum(
                1
                for m in inbox_data["messages"]
                if m.get("status") == "new" or (m.get("status") is None and not m.get("read", False))
            )

            try:
                with open(inbox_file, "w", encoding="utf-8") as fh:
                    json.dump(inbox_data, fh, indent=2, ensure_ascii=False)
            except Exception as exc:
                logger.warning("[delivery] deliver_to_inbox_file write failed %s: %s", inbox_file, exc)
                return False, f"Failed to write inbox: {exc}", ""

    except OSError as exc:
        logger.warning("[delivery] deliver_to_inbox_file lock failed %s: %s", inbox_file, exc)
        return False, f"Failed to acquire inbox lock: {exc}", ""

    _emit_notification_event(
        email_data.get("from", "@unknown"),
        email_data.get("to", str(inbox_file)),
        email_data.get("subject", ""),
        email_data.get("message", ""),
        address=_mail_address(
            reply_id, email_data.get("to") or inbox_file.parent.parent.name, inbox_file.parent.parent
        ),
    )
    return True, "", reply_id


def _project_name(branch_home: Path) -> str:
    """The project a branch is a citizen of, as its registry names it: BAUD_REGISTRY.json -> "baud".

    A root holding several registries is answered by the one named after the
    root's directory. No root, or no such registry, answers "unknown", named.
    """
    root = find_project_root(branch_home)
    stems = [r.name[: -len(REGISTRY_SUFFIX)] for r in registries_in(root)] if root is not None else []
    if root is not None and len(stems) > 1:
        stems = [st for st in stems if st.lower() == root.name.lower()]
    if len(stems) != 1:
        logger.warning(
            "[delivery] no project registry names %s's project (root %s): project 'unknown'", branch_home, root
        )
        return "unknown"
    return stems[0].lower()


def _mail_address(mail_id: str, recipient: str, branch_home: Path) -> Dict[str, str]:
    """Where the phone finds a delivered mail: its inbox id, the recipient branch, its project."""
    return {
        "mail_id": str(mail_id),
        "recipient": str(recipient).lstrip("@"),
        "project": _project_name(branch_home),
    }


_NOTIFICATION_TIMESTAMPS: Dict[str, List[float]] = {}

_NOTIFICATION_MAX = 3
_NOTIFICATION_WINDOW = 30.0  # seconds


def _emit_notification_event(
    sender: str, recipient: str, subject: str, message: str = "", address: Optional[Dict[str, str]] = None
) -> None:
    """Write a "mail" event to the notification feed for new email."""
    import time

    now = time.time()
    cutoff = now - _NOTIFICATION_WINDOW

    if recipient in _NOTIFICATION_TIMESTAMPS:
        _NOTIFICATION_TIMESTAMPS[recipient] = [t for t in _NOTIFICATION_TIMESTAMPS[recipient] if t > cutoff]
    else:
        _NOTIFICATION_TIMESTAMPS[recipient] = []

    if len(_NOTIFICATION_TIMESTAMPS[recipient]) >= _NOTIFICATION_MAX:
        return

    sender_name = sender.replace("@", "").upper()
    recipient_name = recipient.replace("@", "").upper()
    title = f"{sender_name} -> {recipient_name}"
    body = subject
    if message:
        preview = message[:100].replace("\n", " ").strip()
        if preview:
            body = f"{subject}\n{preview}"

    try:
        from aipass.ai_mail.apps.handlers.notify import send_notification

        send_notification(title, body, source=sender.replace("@", ""), kind="mail", extra=address)
        _NOTIFICATION_TIMESTAMPS[recipient].append(now)
    except Exception as e:
        logger.warning("[delivery] _emit_notification_event() failed for %s: %s", recipient, e)
        return


if __name__ == "__main__":
    from rich.console import Console

    console = Console()
    console.print("\n" + "=" * 70)
    console.print("EMAIL DELIVERY HANDLER")
    console.print("=" * 70)
    console.print("\nPURPOSE:")
    console.print("  Delivers emails to branch inboxes")
    console.print()
    console.print("FUNCTIONS PROVIDED:")
    console.print("  - get_all_branches() -> List[Dict]")
    console.print("  - deliver_email_to_branch(to_branch, email_data, on_delivered, upsert_key) -> Tuple\\[bool, str]")
    console.print("  - deliver_to_inbox_file(inbox_file, email_data) -> Tuple\\[bool, str, str]")
    console.print()
    console.print("HANDLER CHARACTERISTICS:")
    console.print("  - Independent - no module dependencies")
    console.print("  - Uses lazy imports for services")
    console.print("  - Pure business logic")
    console.print("  - CANNOT import parent modules")
    console.print()
    console.print("USAGE FROM MODULES:")
    console.print("  from aipass.ai_mail.apps.handlers.email.delivery import deliver_email_to_branch")
    console.print("  from aipass.ai_mail.apps.handlers.registry.read import get_all_branches")
    console.print()
    console.print("=" * 70 + "\n")
