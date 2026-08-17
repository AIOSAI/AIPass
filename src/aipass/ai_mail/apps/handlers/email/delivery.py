# =================== AIPass ====================
# Name: delivery.py
# Description: Email Delivery Handler
# Version: 3.3.0
# Created: 2025-12-02
# Modified: 2026-08-12
# =============================================

"""
Email Delivery Handler

Handles delivery of emails to branch inboxes.
Independent handler - no module dependencies.

Upsert delivery (``upsert_key``)
--------------------------------
A repeating signal — the same WARNING firing every poll — must occupy ONE
inbox slot, not one per repeat. Senders that repeat give the send a stable
``upsert_key``; delivery then rewrites the open message carrying that key
instead of stacking a new one, bumping an ``updates`` counter so the reader
can see how many times it fired.

The read status is the whole point: an update NEVER flips a message back to
new and never wakes anything. A repeat is not a fresh demand for attention —
it is the same demand, louder in the counter only. Closing the message
re-arms the signature: the next send starts a fresh message at ``updates: 1``.
"""

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Dict, Tuple, List, Optional, Callable

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.paths import find_repo_root, find_project_root
from aipass.ai_mail.apps.handlers.registry.read import get_all_branches

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")


_REPO_ROOT = find_repo_root()

# Lazy imports to avoid circular dependencies
_INBOX_LOCK = None


def _load_caller_project_branches(caller_cwd: str) -> Dict[str, str]:
    """Load branches from the caller's project registry.

    Delegates to registry.read.get_caller_project_branches — shared
    implementation used by both delivery and wake for cross-project resolution.
    """
    from aipass.ai_mail.apps.handlers.registry.read import get_caller_project_branches

    return get_caller_project_branches(caller_cwd)


def _auto_register_contact(email: str, branch_path: Path, inbox_file: Path) -> None:
    """Auto-register a recipient in the contacts address book after successful delivery.

    Non-critical: failures are logged and silently ignored.

    Args:
        email: Recipient email address (e.g., '@devpulse').
        branch_path: Resolved path to the branch root directory.
        inbox_file: Path to the branch's inbox.json file.
    """
    try:
        from aipass.ai_mail.apps.handlers.email.contacts import register_contact

        name_key = email.lstrip("@").lower()
        register_contact(name_key, "AIPass", str(inbox_file))
    except Exception as e:
        logger.warning("[delivery] _auto_register_contact(%s) failed: %s", email, e)


def _auto_register_sender(branch_name: str, caller_cwd: str) -> None:
    """Auto-register a sender in contacts when called from an external project.

    Walks up from caller_cwd to find .ai_mail.local/inbox.json.
    Non-critical: failures are logged and silently ignored.

    Args:
        branch_name: Sender branch name or email (e.g., 'vera' or '@vera').
        caller_cwd: Working directory of the calling project.
    """
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
    """
    Auto-migrate old inbox format to v2 schema.

    Old format: {"inbox": [...]}
    New format: {"mailbox": "inbox", "total_messages": N, "unread_count": N, "messages": [...]}

    Migrates in-place and persists to disk if changes were made.

    Args:
        inbox_data: Loaded inbox dict (may be old or new format)
        inbox_file: Path to inbox.json (for persisting migration)

    Returns:
        Migrated inbox data dict with v2 schema
    """
    migrated = False

    # Case 0: inbox_data is a list instead of a dict (corrupted/malformed inbox.json)
    if isinstance(inbox_data, list):
        inbox_data = {"messages": inbox_data}
        migrated = True

    # Case 1: Old format with "inbox" key instead of "messages"
    if "inbox" in inbox_data and "messages" not in inbox_data:
        old_messages = inbox_data.pop("inbox", [])
        inbox_data["messages"] = old_messages if isinstance(old_messages, list) else []
        migrated = True

    # Case 2: Missing "messages" key entirely
    if "messages" not in inbox_data:
        inbox_data["messages"] = []
        migrated = True

    # Ensure v2 metadata fields exist
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

    # Persist migration to disk
    if migrated:
        try:
            with open(inbox_file, "w", encoding="utf-8") as f:
                json.dump(inbox_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning("[delivery] _migrate_inbox_format() failed to persist migration for %s: %s", inbox_file, e)
            return inbox_data

    return inbox_data


def _is_private_branch_email(email: str) -> bool:
    """Check if email belongs to a private branch.

    Reads PRIVATE_BRANCH_REGISTRY.json to determine if the given
    email address is registered to a private (isolated) branch.

    Args:
        email: Email address to check (e.g., "@private_branch")

    Returns:
        True if email belongs to a private branch, False otherwise
    """
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
    """Detect the caller's ai_mail inbox path from AIPASS_CALLER_CWD env var.

    Used to store a reply_path on delivered messages so cross-project replies
    can bypass registry lookup and write directly to the sender's inbox.

    Returns the absolute path to the caller's inbox.json, or empty string if
    AIPASS_CALLER_CWD is not set or no inbox directory is found.
    """
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")
    if not caller_cwd:
        return ""
    # Check the CWD itself and up to 5 parent directories for .ai_mail.local/
    candidate = Path(caller_cwd)
    for path in [candidate] + list(candidate.parents)[:5]:
        inbox = path / ".ai_mail.local" / "inbox.json"
        if inbox.exists():
            return str(inbox)
    return ""


def _path_is_inside(candidate: Path, root: Path) -> bool:
    """True when candidate sits within root.

    Args:
        candidate: Path to test.
        root: Directory that must contain it.

    Returns:
        True if candidate is root or below it.
    """
    try:
        resolved_candidate = Path(candidate).resolve()
        resolved_root = Path(root).resolve()
    except OSError as exc:
        # Resolution itself failing is a real fault, unlike "simply not inside".
        logger.warning("[delivery] could not resolve %s against %s: %s", candidate, root, exc)
        return False

    return resolved_candidate.is_relative_to(resolved_root)


def _reply_proof_mailboxes(email_data: Optional[Dict], sender_root: Optional[Path]) -> List[Path]:
    """Where a reply's proof may live, most reliable source first.

    Two resolvers disagreed about which mailbox belongs to the sender, and that
    disagreement was the @baud outage (2026-08-16). ``handle_reply`` locates the
    original through ``_resolve_branch_path()`` — env, registry, fallback — so
    the reply is built and sent; the boundary then re-derived the mailbox by
    walking UP from ``AIPASS_CALLER_CWD``, which finds nothing unless the caller
    is standing in the mailbox directory or below it. @baud's seat is four
    levels below its project root, so a caller at the project root walked past
    the mailbox and out of the project. Original found, proof not found, reply
    refused.

    ``reply.py`` already stamps ``reply_path`` on every reply, derived from
    ``from_branch_path`` — the branch actually replying — precisely because the
    CWD guess "can name the wrong branch entirely". This reads it.

    The stamp travels with the message, so it is bounded: it only counts when it
    lands inside the sender's own project. That keeps the fence exactly where it
    was — a crafted ``reply_path`` cannot nominate a mailbox elsewhere on disk.

    Args:
        email_data: The outbound message, possibly carrying ``reply_path``.
        sender_root: The sender's project root, or None when unknown.

    Returns:
        Candidate inbox paths, in order of trust, without duplicates.
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

    The return path (FPLAN-0401 phase 5b). A reply is answering, not initiating:
    the referenced message sitting in the sender's OWN mailbox is the proof the
    channel was sanctioned. Initiation across projects stays admin-only.

    Accepts the referenced mail's ``from`` or its ``reply_to`` — reply.py routes
    to ``reply_to or from``, so an exemption matching only ``from`` would refuse
    the very replies it exists to allow. Neither field is chosen by the replier;
    only the original sender could have written them, so this is still the
    sanctioned channel and not a laundered new recipient.

    Args:
        email_data: The outbound message. A reply carries ``in_reply_to``.
        to_branch: Where the outbound message is addressed.

    Returns:
        True only if the referenced mail exists in the sender's mailbox AND
        named this recipient. False on anything unproven — fails closed.
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


def _check_cross_project_boundary(
    recipient_path: Path, sender_email: str, email_data: Optional[Dict] = None, to_branch: str = ""
) -> Tuple[bool, str]:
    """Refuse mail when sender and recipient are in different projects.

    Compares project roots (first *_REGISTRY.json found walking up) for the
    sender (from AIPASS_CALLER_CWD) and recipient (from resolved branch path).
    Same-project and host-to-host mail passes through unchanged.

    A VERIFIED admin caller is exempt — that is the cross-project bridge
    (FPLAN-0401 phase 5). The exemption is checked LAST, only once a refusal is
    otherwise certain, so ordinary same-project mail never touches the grant.

    Returns:
        (True, error_message) to refuse, (False, "") to allow.
    """
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")
    if not caller_cwd:
        return False, ""

    sender_root = find_project_root(Path(caller_cwd))
    if sender_root is None:
        return False, ""

    recipient_root = find_project_root(recipient_path)
    if recipient_root is None:
        return False, ""

    if sender_root == recipient_root:
        return False, ""

    # Everything below this line is a refusal — so this is where, and the only
    # place where, an exemption is worth the file reads. Both fail closed.
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
    """Name the ``projects/<name>`` directory a hosted branch path sits under.

    Args:
        branch_path: Absolute path to a branch inside the projects tree.

    Returns:
        The project directory name, or "unknown" if the path sits elsewhere.
    """
    try:
        rel = Path(branch_path).resolve().relative_to((_REPO_ROOT / "projects").resolve())
        return rel.parts[0]
    except (ValueError, OSError, IndexError) as exc:
        # It came out of a projects/*/ registry, so not sitting under projects/
        # means the registry's paths disagree with its own location.
        logger.warning("[delivery] hosted branch path %s is not under projects/: %s", branch_path, exc)
        return "unknown"


def _describe_unresolved_address(to_branch: str, known_count: int) -> str:
    """Explain why an address did not resolve, without widening resolution.

    An address can fail to resolve for two very different reasons, and saying
    "unknown" for both is a lie in one of them. @baud is a registered citizen of
    a hosted project; @devpulse reaches it through the admin lane. Telling @api
    it did not exist sent them debugging an addressing bug that was not there
    (2026-08-14), when the true answer is a policy: fleet-to-project initiation
    is walled, replies only (DPLAN-0288).

    This runs ONLY once delivery has already failed, so the extra registry read
    costs nothing on any successful send. It returns a **string** and nothing
    else — the caller's branch map is deliberately not updated, because the
    whole point is to describe the wall, not open it.

    Args:
        to_branch: The address that failed to resolve.
        known_count: How many branches were in scope for this caller.

    Returns:
        A refusal message stating the real reason.
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
        f"fleet ({known_count} branches in scope). Fleet-to-project mail is replies-only by "
        f"ruling (DPLAN-0288) — only @devpulse's verified-admin lane may initiate. Reply to an "
        f"existing message from {to_branch}, or use the feedback channel."
    )


def _coerce_updates(value) -> int:
    """Read a stored ``updates`` counter defensively, defaulting to 1.

    The counter lives in a hand-editable JSON file, so a string, None or
    garbage must not crash a delivery — an unreadable counter restarts at 1
    rather than taking the message down with it.
    """
    try:
        count = int(value)
    except (TypeError, ValueError):
        logger.warning("[delivery] unreadable updates counter %r — restarting at 1", value)
        return 1
    return count if count >= 1 else 1


def _find_upsert_target(messages: List[Dict], from_addr: str, upsert_key: str) -> Optional[Dict]:
    """Find the open message this upsert should rewrite.

    Match rule: same sender AND same upsert_key AND not closed. Messages are
    newest-first, so the first hit is the most recent open one.

    Args:
        messages: The inbox's message list.
        from_addr: Sender address of the incoming mail.
        upsert_key: Stable signature supplied by the sender.

    Returns:
        The matching message dict (live reference into *messages*), or None.
    """
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

    Preserves id, original timestamp and status — an update must never flip a
    message back to new or unread. auto_execute is forced off: an in-place
    update never wakes or dispatches anything, whatever the sender asked for.

    Args:
        existing: The matched message dict, mutated in place.
        email_data: The incoming email data (fresh subject/body/timestamp).

    Returns:
        The same dict, for convenience.
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
    """
    Deliver email to target branch's .ai_mail.local/inbox.json file.

    Appends message to inbox JSON messages array — unless an upsert_key is
    given and an open message from the same sender already carries it, in
    which case that message is rewritten in place (see module docstring).

    Args:
        to_branch: Target email address (e.g., "@admin")
        email_data: Email data dict with keys:
            - from: Sender email address
            - from_name: Sender display name
            - to: Recipient email address
            - subject: Email subject
            - message: Email body
            - timestamp: Email timestamp string
            - upsert_key: Optional, alternative to the keyword argument
        on_delivered: Optional callback(branch_path, new_count, opened_count, total)
            for post-delivery actions (dashboard updates, central sync, etc.)
        upsert_key: Optional stable signature for a repeating signal. None
            (the default) is plain delivery: every send is a new message.
            Takes precedence over email_data["upsert_key"].

    Returns:
        Tuple of (success: bool, error_message: str)
        error_message is empty string if successful

    Note:
        When an upsert_key is in play, the outcome is reported back through
        email_data["upsert_action"] = "created" | "updated" so the caller can
        tell a fresh message from a bumped counter without re-reading the inbox.
    """
    json_handler.log_operation("deliver_email", {"to": to_branch, "subject": email_data.get("subject", "")})

    # Handle path input from DRONE's @ resolution
    if to_branch.startswith("/") or Path(to_branch).is_absolute():
        branches_list = get_all_branches()
        path_to_email = {b["path"]: b["email"] for b in branches_list}
        if to_branch in path_to_email:
            to_branch = path_to_email[to_branch]
        else:
            # Stage 2: Longest-path-first prefix matching against registry
            sorted_branches = sorted(branches_list, key=lambda b: len(b["path"]), reverse=True)
            matched = False
            for b in sorted_branches:
                if to_branch.startswith(b["path"] + "/") or to_branch == b["path"]:
                    to_branch = b["email"]
                    matched = True
                    break
            if not matched:
                return False, f"Could not resolve path to email: {to_branch}"

    # Map email address to branch path (AIPass registry + caller's project registry)
    all_branches = get_all_branches()
    branches = {b["email"]: b["path"] for b in all_branches}

    if to_branch not in branches:
        # Check caller's project registry for local branches (e.g. @strategy in Vera Studio)
        caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")
        if caller_cwd:
            caller_branches = _load_caller_project_branches(caller_cwd)
            branches.update(caller_branches)

    if to_branch not in branches:
        # Hosted projects (verified-admin only — the cross-project bridge).
        # Last resort, and gated: an unverified caller's map never widens.
        from aipass.ai_mail.apps.handlers.users import verified_caller

        if verified_caller.is_verified_admin_caller():
            from aipass.ai_mail.apps.handlers.registry.read import get_project_tree_branches

            branches.update(get_project_tree_branches(_REPO_ROOT))

    if to_branch not in branches:
        # Refusal is correct here; the STATED REASON is what was wrong. Explain
        # the wall instead of denying the address — the map is not widened.
        return False, _describe_unresolved_address(to_branch, len(branches))

    # Private branch inbound blocking: reject delivery to private branches
    # Self-send is allowed (private branch can send to itself)
    sender_email = email_data.get("from", "")
    if _is_private_branch_email(to_branch) and sender_email != to_branch:
        return False, f"Cannot deliver to private branch: {to_branch}"

    raw_path = branches[to_branch]
    branch_path = Path(raw_path)
    if not branch_path.is_absolute():
        branch_path = (_REPO_ROOT / branch_path).resolve()

    # Cross-project boundary: refuse mail when sender and recipient are in different projects
    refused, refusal_msg = _check_cross_project_boundary(
        branch_path, sender_email, email_data=email_data, to_branch=to_branch
    )
    if refused:
        return False, refusal_msg

    # Find the branch's .ai_mail.local/inbox.json file
    if branch_path == Path("/") or branch_path == _REPO_ROOT:
        inbox_file = _REPO_ROOT / ".ai_mail.local" / "inbox.json"
    else:
        inbox_file = branch_path / ".ai_mail.local" / "inbox.json"

    if not inbox_file.exists():
        # Auto-provision inbox for new branches (self-healing)
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

    # Lock inbox.json for the entire read-modify-write cycle
    try:
        with _get_inbox_lock()(inbox_file):
            try:
                with open(inbox_file, "r", encoding="utf-8") as f:
                    inbox_data = json.load(f)
            except Exception as e:
                logger.warning("[delivery] failed to read inbox %s: %s", inbox_file, e)
                return False, f"Failed to read inbox: {e}"

            # Auto-migrate old inbox format {"inbox": []} -> v2 schema
            inbox_data = _migrate_inbox_format(inbox_data, inbox_file)

            # Upsert: rewrite the open message carrying this key instead of
            # stacking a second one. No key = plain delivery, unchanged.
            effective_key = upsert_key if upsert_key is not None else email_data.get("upsert_key")
            existing = None
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
                # Create message object (v2 schema: status instead of read)
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

                # The sender's own id for this message, kept as a back-reference.
                # The id above is minted fresh so it is unique in THIS mailbox;
                # without this field the recipient's copy and the sender's sent/
                # record share no identifier at all, and a delivered message
                # cannot be proven to have arrived. That untraceability was read
                # as a delivery outage on 2026-08-16 (@seedgo -> @devpulse).
                if email_data.get("id"):
                    message["sent_id"] = email_data["id"]

                if email_data.get("reply_to"):
                    message["reply_to"] = email_data["reply_to"]

                if email_data.get("dispatched_to"):
                    message["dispatched_to"] = email_data["dispatched_to"]

                # Store reply_path for cross-project replies.
                # Pass-through from email_data, or auto-detect from AIPASS_CALLER_CWD.
                reply_path = email_data.get("reply_path") or _resolve_reply_path()
                if reply_path:
                    message["reply_path"] = reply_path

                # Carry the key on the message so the NEXT send can find it
                if effective_key:
                    message["upsert_key"] = effective_key
                    message["updates"] = 1
                    email_data["upsert_action"] = "created"

                # Prepend message to inbox (newest first)
                inbox_data["messages"].insert(0, message)

            from aipass.ai_mail.apps.handlers.email.inbox_cleanup import _sweep_closed

            _sweep_closed(inbox_data, inbox_file.parent)

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

    # Auto-register recipient in contacts for future fast lookup
    _auto_register_contact(to_branch, branch_path, inbox_file)

    # Auto-register sender if external project called with AIPASS_CALLER_BRANCH
    caller_branch = os.environ.get("AIPASS_CALLER_BRANCH", "")
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")
    if caller_branch and caller_cwd:
        _auto_register_sender(caller_branch, caller_cwd)

    # Write a feed event for new email. An in-place update is the same signal
    # repeating, so it stays silent — one feed line per repeat is the stacking
    # problem again, just in the bell instead of in the inbox.
    if not updated_in_place:
        _emit_notification_event(email_data["from"], to_branch, email_data["subject"], email_data.get("message", ""))

    # Invoke post-delivery callback (dashboard updates, central sync, etc.)
    if on_delivered:
        try:
            on_delivered(branch_path, new_count, opened_count, inbox_data["total_messages"])
        except Exception as e:
            logger.warning("[delivery] on_delivered callback failed for %s: %s", to_branch, e)
            return True, ""

    return True, ""


def deliver_to_inbox_file(inbox_file: Path, email_data: Dict) -> Tuple[bool, str, str]:
    """Write *email_data* to an inbox.json file and fire a notification event.

    Single canonical path for direct-path delivery (used by cross-project
    reply.py to replace the raw-write backdoor).  Always writes to the feed.

    Args:
        inbox_file: Absolute path to the target inbox.json.
        email_data: Dict with at minimum ``from``, ``to``, ``subject``,
                    ``message``, ``timestamp``.  An ``id`` key is assigned
                    internally if absent.

    Returns:
        ``(success, error_msg, reply_id)`` — ``reply_id`` is the 8-char hex
        string assigned to the message (empty string on failure).
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
            # This lane keeps the sender's id AS the message id, so correlation
            # is already possible here. Stamp sent_id anyway: a reader must not
            # have to know which lane delivered a message to know how to trace
            # it. Both lanes answer "which sent record is this" the same way.
            if email_data.get("id"):
                email_data.setdefault("sent_id", email_data["id"])
            email_data.setdefault("id", reply_id)
            reply_id = email_data["id"]

            inbox_data.setdefault("messages", []).insert(0, email_data)

            from aipass.ai_mail.apps.handlers.email.inbox_cleanup import _sweep_closed

            _sweep_closed(inbox_data, inbox_file.parent)

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
    )
    return True, "", reply_id


_NOTIFICATION_TIMESTAMPS: Dict[str, List[float]] = {}

# Rate limit: max notifications per recipient within time window
_NOTIFICATION_MAX = 3
_NOTIFICATION_WINDOW = 30.0  # seconds


def _emit_notification_event(sender: str, recipient: str, subject: str, message: str = "") -> None:
    """
    Write a "mail" event to the notification feed for new email.

    Rate-limited: max 3 events per recipient within 30 seconds.
    Desktop toasts are retired — this appends to the shared feed BAUD reads.

    Args:
        sender: Email sender address (e.g., @devpulse)
        recipient: Email recipient address (e.g., @ai_mail)
        subject: Email subject line
        message: Email body (first ~100 chars shown in notification)
    """
    import time

    now = time.time()
    cutoff = now - _NOTIFICATION_WINDOW

    if recipient in _NOTIFICATION_TIMESTAMPS:
        _NOTIFICATION_TIMESTAMPS[recipient] = [t for t in _NOTIFICATION_TIMESTAMPS[recipient] if t > cutoff]
    else:
        _NOTIFICATION_TIMESTAMPS[recipient] = []

    if len(_NOTIFICATION_TIMESTAMPS[recipient]) >= _NOTIFICATION_MAX:
        return

    # Build informative notification
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

        send_notification(title, body, source=sender.replace("@", ""), kind="mail")
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
