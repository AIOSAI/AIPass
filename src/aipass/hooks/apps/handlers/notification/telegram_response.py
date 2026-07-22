# =================== AIPass ====================
# Name: telegram_response.py
# Version: 2.0.0
# Description: Telegram response delivery on Stop event (ported from Dev-Pass)
# Branch: hooks
# Layer: apps/handlers/notification
# Created: 2026-06-15
# Modified: 2026-06-29
# =============================================

"""Telegram response delivery on Stop event.

Fires on every Claude Code Stop event. Uses 3-layer defense to ensure only
the correct response (to Patrick's Telegram message) is delivered:

Layer 1: SubagentStop filter — rejects subagent/sidechain Stop events at the gate
Layer 2: isSidechain filter — skips sidechain entries during transcript extraction
Layer 3: Transcript position — only extracts text after the recorded injection point
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from aipass.prax import append_jsonl
from aipass.prax.apps.modules.logger import system_logger as logger

PENDING_DIR = Path.home() / ".aipass" / "telegram_pending"
MIRROR_DIR = Path.home() / ".aipass" / "telegram_bots"
PENDING_TTL = 3600
TELEGRAM_CHAR_LIMIT = 4096
_PROD_DELIVERY_LOG = Path(__file__).resolve().parent.parent.parent.parent / "logs" / "telegram_delivery.jsonl"


def _get_delivery_log() -> Path:
    """Resolve delivery log path — temp dir during pytest, prod path otherwise."""
    if "_pytest" in sys.modules:
        p = Path(tempfile.gettempdir()) / "aipass_test_logs" / "hooks"
        p.mkdir(parents=True, exist_ok=True)
        return p / "telegram_delivery.jsonl"
    return _PROD_DELIVERY_LOG


_DELIVERY_LOG = _PROD_DELIVERY_LOG


def _is_expired(data: dict) -> bool:
    """Check if pending file is expired (1-hour TTL + tmux-alive check)."""
    if data.get("mirror"):
        return False
    timestamp = data.get("timestamp", 0)
    if isinstance(timestamp, str):
        try:
            timestamp = float(timestamp)
        except ValueError:
            logger.info("[HOOKS] telegram: invalid timestamp string, treating as 0")
            timestamp = 0
    age = time.time() - timestamp
    if age > PENDING_TTL:
        session_name = data.get("session_name", "")
        if session_name:
            try:
                result = subprocess.run(
                    ["tmux", "has-session", "-t", session_name],
                    capture_output=True,
                )
                if result.returncode == 0:
                    return False
            except OSError:
                logger.info("[HOOKS] telegram: tmux not available for expiry check")
        return True
    return False


def _try_load_pending(path: Path) -> dict | None:
    """Load and validate a pending file. Returns data dict or None if missing/expired/corrupt."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not _is_expired(data):
            return data
    except (json.JSONDecodeError, OSError):
        logger.info("[HOOKS] telegram: could not load pending %s", path.name)
    return None


def _in_mirror_dir(path: Path) -> bool:
    """Check if a path is inside the persistent mirror mapping directory."""
    try:
        path.relative_to(MIRROR_DIR)
        return True
    except ValueError:
        logger.info("[HOOKS] telegram: %s is not in mirror dir", path.name)
        return False


def find_pending_file(session_id: str) -> Path | None:  # noqa: ARG001
    """Find pending file matching current context via multi-bot matching.

    Priority 1: AIPASS_BOT_ID env var -> bot-{bot_id}.json (mirror dir first, then pending)
    Priority 2: CWD relative_to work_dir -> bot-*.json (both dirs)
    """
    cwd = Path.cwd()
    env_bot_id = os.environ.get("AIPASS_BOT_ID")

    if env_bot_id:
        for search_dir in [MIRROR_DIR, PENDING_DIR]:
            path = search_dir / f"bot-{env_bot_id}.json"
            if _try_load_pending(path) is not None:
                logger.info("[HOOKS] telegram: match bot_id env -> %s", path)
                return path

    for search_dir in [PENDING_DIR, MIRROR_DIR]:
        if not search_dir.exists():
            continue
        for pending_path in sorted(search_dir.glob("bot-*.json")):
            data = _try_load_pending(pending_path)
            if data is None:
                continue
            work_dir = data.get("work_dir")
            if not work_dir:
                continue
            try:
                cwd.relative_to(Path(work_dir))
                logger.info("[HOOKS] telegram: match cwd -> %s", pending_path)
                return pending_path
            except ValueError:
                logger.info("[HOOKS] telegram: cwd not relative to %s, skipping", pending_path.name)
                continue

    return None


def extract_assistant_response(transcript_path: str, start_line: int = 0) -> str | None:
    """Extract the last assistant response from a JSONL transcript file.

    Uses position-aware extraction (Layer 3) and sidechain filtering (Layer 2).
    """
    path = Path(transcript_path)
    if not path.exists():
        logger.warning("[HOOKS] telegram: transcript not found: %s", transcript_path)
        return None

    try:
        all_lines = path.read_text(encoding="utf-8").strip().split("\n")
    except OSError as e:
        logger.error("[HOOKS] telegram: failed to read transcript: %s", e)
        return None

    if not all_lines:
        return None

    lines = all_lines[start_line:] if start_line > 0 else all_lines

    last_user_idx = _find_last_real_user_message(lines)

    if last_user_idx == -1:
        logger.warning("[HOOKS] telegram: no user message found (start_line=%d)", start_line)
        return None

    text_parts = _collect_assistant_text(lines[last_user_idx + 1 :])

    if not text_parts:
        logger.info("[HOOKS] telegram: no assistant text after last user msg (start_line=%d)", start_line)
        return None

    result = "\n\n".join(text_parts).strip()
    return result if result else None


def _find_last_real_user_message(lines: list[str]) -> int:
    """Find the index of the last non-sidechain, non-tool-result user message."""
    last_user_idx = -1
    for i, line in enumerate(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            logger.info("[HOOKS] telegram: skipping malformed JSONL line %d", i)
            continue
        if entry.get("isSidechain", False):
            continue
        if entry.get("type") != "user":
            continue
        message = entry.get("message", {})
        content = message.get("content", [])
        if isinstance(content, list) and all(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content if isinstance(b, dict)
        ):
            continue
        last_user_idx = i
    return last_user_idx


def _collect_assistant_text(lines: list[str]) -> list[str]:
    """Collect assistant text blocks from JSONL lines, skipping sidechain entries."""
    text_parts = []
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            logger.info("[HOOKS] telegram: skipping malformed JSONL line in assistant collection")
            continue
        if entry.get("isSidechain", False):
            continue
        if entry.get("type") != "assistant":
            continue
        message = entry.get("message", {})
        content = message.get("content", [])
        for block in content:
            if block.get("type") == "text":
                text = block.get("text", "").strip()
                if text:
                    text_parts.append(text)
    return text_parts


def _extract_user_text(content: list | str) -> str | None:
    """Extract text from user message content, returning None for tool-result-only messages."""
    if isinstance(content, str):
        return content.strip() or None
    if not isinstance(content, list):
        return None
    texts: list[str] = []
    has_non_tool = False
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text = block.get("text", "").strip()
            if text:
                texts.append(text)
            has_non_tool = True
        elif block.get("type") != "tool_result":
            has_non_tool = True
    if not has_non_tool:
        return None
    return " ".join(texts) if texts else None


def _text_from_content(content: list) -> list[str]:
    """Extract text strings from a message content block list."""
    if not isinstance(content, list):
        return []
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "").strip()
            if text:
                parts.append(text)
    return parts


def _collect_mirror_entries(lines: list[str]) -> list[tuple[str | None, list[str]]]:
    """Collect user+assistant turn pairs from JSONL lines for mirror delivery."""
    turns: list[tuple[str | None, list[str]]] = []
    current_user: str | None = None
    current_assistant: list[str] = []

    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            logger.info("[HOOKS] telegram: skipping malformed JSONL line in mirror collection")
            continue
        if entry.get("isSidechain", False):
            continue

        entry_type = entry.get("type")
        message = entry.get("message", {})
        content = message.get("content", [])

        if entry_type == "user":
            user_text = _extract_user_text(content)
            if user_text is None:
                continue
            if current_user is not None or current_assistant:
                turns.append((current_user, current_assistant))
            current_user = user_text
            current_assistant = []

        elif entry_type == "assistant":
            current_assistant.extend(_text_from_content(content))

    if current_user is not None or current_assistant:
        turns.append((current_user, current_assistant))

    return turns


def extract_mirror_turn(transcript_path: str, start_line: int = 0) -> str | None:
    """Extract all new turns (user input + assistant response) for mirror delivery."""
    path = Path(transcript_path)
    if not path.exists():
        logger.warning("[HOOKS] telegram: mirror transcript not found: %s", transcript_path)
        return None

    try:
        all_lines = path.read_text(encoding="utf-8").strip().split("\n")
    except OSError as e:
        logger.error("[HOOKS] telegram: failed to read mirror transcript: %s", e)
        return None

    if not all_lines:
        return None

    lines = all_lines[start_line:] if start_line > 0 else all_lines
    if not lines and start_line > len(all_lines):
        logger.warning(
            "[HOOKS] telegram: cursor ahead of transcript (%d > %d) — clamping to deliver latest",
            start_line,
            len(all_lines),
        )
        clamped = _find_last_real_user_message(all_lines)
        lines = all_lines[max(0, clamped) :]
    if not lines:
        return None

    turns = _collect_mirror_entries(lines)
    if not turns:
        return None

    formatted = []
    for user_text, assistant_parts in turns:
        parts: list[str] = []
        if user_text:
            parts.append(f"You: {user_text}")
        if assistant_parts:
            parts.append("\n\n".join(assistant_parts))
        if parts:
            formatted.append("\n\n".join(parts))

    if not formatted:
        return None

    result = "\n\n---\n\n".join(formatted).strip()
    return result if result else None


def chunk_text(text: str, limit: int = TELEGRAM_CHAR_LIMIT) -> list[str]:
    """Split text into chunks for Telegram's message limit."""
    if len(text) <= limit:
        return [text]

    chunks = []
    remaining = text

    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        chunk = remaining[:limit]
        best_break = _find_best_break(chunk, limit)
        chunks.append(remaining[:best_break].rstrip())
        remaining = remaining[best_break:].lstrip()

    return chunks


def _find_best_break(chunk: str, limit: int) -> int:
    """Find the best break position in a chunk of text."""
    for i in range(len(chunk) - 1, max(0, len(chunk) - 500), -1):
        if chunk[i] in ".!?" and (i + 1 >= len(chunk) or chunk[i + 1] in " \n"):
            return i + 1

    pos = chunk.rfind("\n\n")
    if pos > limit // 2:
        return pos + 2

    pos = chunk.rfind("\n")
    if pos > limit // 2:
        return pos + 1

    pos = chunk.rfind(" ")
    if pos > limit // 2:
        return pos + 1

    return limit


def _escape_html(s: str) -> str:
    """Escape HTML entities for Telegram's HTML parse mode."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def markdown_to_telegram_html(text: str) -> str:
    """Convert markdown to Telegram-compatible HTML.

    Uses placeholder protection so markdown inside code blocks is preserved.
    """
    blocks: list[tuple[str, str]] = []
    inlines: list[str] = []

    text = re.sub(
        r"```(\w*)\n?(.*?)```",
        lambda m: (blocks.append((m.group(1) or "", m.group(2))), f"\x00B{len(blocks) - 1}\x00")[1],
        text,
        flags=re.DOTALL,
    )

    text = re.sub(
        r"`([^`\n]+)`",
        lambda m: (inlines.append(m.group(1)), f"\x00I{len(inlines) - 1}\x00")[1],
        text,
    )

    text = _escape_html(text)

    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)

    for i, (lang, code) in enumerate(blocks):
        if lang:
            tag = f'<pre><code class="language-{lang}">{_escape_html(code.strip())}</code></pre>'
        else:
            tag = f"<pre>{_escape_html(code.strip())}</pre>"
        text = text.replace(f"\x00B{i}\x00", tag)

    for i, code in enumerate(inlines):
        text = text.replace(f"\x00I{i}\x00", f"<code>{_escape_html(code)}</code>")

    return text


def _parse_api_message(api_result: dict) -> dict:
    """Extract message_id and text from a Telegram API response."""
    msg = api_result.get("result", {})
    return {"ok": True, "message_id": msg.get("message_id"), "text": msg.get("text", "")}


def send_to_telegram(bot_token: str, chat_id: int, text: str, message_id: int | None = None) -> dict:
    """Send a message to Telegram via Bot API. Returns dict with ok, message_id, text."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    try:
        html_text = markdown_to_telegram_html(text)
        html_payload: dict = {"chat_id": chat_id, "text": html_text, "parse_mode": "HTML"}
        if message_id:
            html_payload["reply_to_message_id"] = message_id
        data = json.dumps(html_payload).encode("utf-8")
        req = Request(url, data=data, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=15) as resp:
            api_result = json.loads(resp.read())
            if api_result.get("ok"):
                return _parse_api_message(api_result)
        logger.warning("[HOOKS] telegram: HTML send failed: %s", api_result.get("description"))
    except Exception as e:
        logger.warning("[HOOKS] telegram: HTML send error: %s, plain text fallback", e)

    payload: dict = {"chat_id": chat_id, "text": text}
    if message_id:
        payload["reply_to_message_id"] = message_id

    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json"})

    try:
        with urlopen(req, timeout=15) as resp:
            api_result = json.loads(resp.read())
            if api_result.get("ok"):
                return _parse_api_message(api_result)
            logger.error("[HOOKS] telegram: API error: %s", api_result.get("description"))
            return {"ok": False}
    except HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
            description = body.get("description", "unknown")
            logger.error("[HOOKS] telegram: HTTP %d: %s (len=%d)", e.code, description, len(text))
        except Exception:
            logger.error("[HOOKS] telegram: HTTP %d: %s (len=%d)", e.code, e.reason, len(text))
        return {"ok": False}
    except URLError as e:
        logger.error("[HOOKS] telegram: send failed: %s", e)
        return {"ok": False}
    except Exception as e:
        logger.error("[HOOKS] telegram: unexpected send error: %s", e)
        return {"ok": False}


def edit_telegram_message(bot_token: str, chat_id: int, message_id: int, text: str) -> dict:
    """Edit an existing Telegram message via Bot API. Returns dict with ok, message_id, text."""
    url = f"https://api.telegram.org/bot{bot_token}/editMessageText"

    try:
        html_text = markdown_to_telegram_html(text)
        html_payload = {"chat_id": chat_id, "message_id": message_id, "text": html_text, "parse_mode": "HTML"}
        data = json.dumps(html_payload).encode("utf-8")
        req = Request(url, data=data, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=15) as resp:
            api_result = json.loads(resp.read())
            if api_result.get("ok", False):
                return _parse_api_message(api_result)
        logger.warning("[HOOKS] telegram: HTML edit failed, plain text fallback")
    except Exception as e:
        logger.warning("[HOOKS] telegram: HTML edit error: %s, plain text fallback", e)

    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json"})

    try:
        with urlopen(req, timeout=15) as resp:
            api_result = json.loads(resp.read())
            if api_result.get("ok", False):
                return _parse_api_message(api_result)
            return {"ok": False}
    except Exception as e:
        logger.warning("[HOOKS] telegram: edit failed: %s", e)
        return {"ok": False}


def _send_with_retry(bot_token: str, chat_id: int, text: str, retries: int = 3) -> dict:
    """Send with retry and exponential backoff. Returns dict with ok, message_id, text."""
    for attempt in range(retries):
        result = send_to_telegram(bot_token, chat_id, text)
        if result["ok"]:
            return result
        if attempt < retries - 1:
            delay = 1.0 * (2**attempt)
            logger.info("[HOOKS] telegram: send retry %d/%d after %.0fs", attempt + 2, retries, delay)
            time.sleep(delay)
    return {"ok": False}


def handle(hook_data: dict) -> dict:
    """Handle Stop event — deliver Telegram response if pending."""
    hook_event = hook_data.get("hook_event_name", "")
    if hook_event == "SubagentStop":
        return {"stdout": "", "exit_code": 0}

    session_id = hook_data.get("session_id", "")
    transcript_path = hook_data.get("transcript_path", "")

    if transcript_path and "/subagents/" in transcript_path:
        return {"stdout": "", "exit_code": 0}

    if not session_id:
        return {"stdout": "", "exit_code": 0}

    pending_file = find_pending_file(session_id)
    if not pending_file:
        return {"stdout": "", "exit_code": 0}

    logger.info("[HOOKS] telegram: processing response for session %s", session_id[:8])

    try:
        pending_data = json.loads(pending_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.error("[HOOKS] telegram: failed to read pending: %s", e)
        if not _in_mirror_dir(pending_file):
            pending_file.unlink(missing_ok=True)
        return {"stdout": "", "exit_code": 0}

    is_mirror = pending_data.get("mirror", False)
    chat_id = pending_data.get("chat_id")
    bot_token = pending_data.get("bot_token")
    processing_message_id = pending_data.get("processing_message_id")

    if not chat_id or not bot_token:
        logger.error("[HOOKS] telegram: missing chat_id or bot_token in pending")
        if not is_mirror:
            pending_file.unlink(missing_ok=True)
        return {"stdout": "", "exit_code": 0}

    response_text = _extract_response(hook_data, transcript_path, pending_data)
    if not response_text:
        logger.warning("[HOOKS] telegram: no text from JSONL or fallback — keeping pending")
        return {"stdout": "", "exit_code": 0}

    response_text = _prepend_branch_prefix(response_text)
    logs_were_active = _check_log_streamer_active()
    streaming = bool(pending_data.get("streaming", False))

    chunks = chunk_text(response_text)
    logger.info(
        "[HOOKS] telegram: sending %d chunk(s) (logs_active=%s, streaming=%s)",
        len(chunks),
        logs_were_active,
        streaming,
    )

    all_sent, chunk_results = _deliver_chunks(
        chunks, bot_token, chat_id, processing_message_id, logs_were_active, streaming
    )

    _write_delivery_log(response_text, chunks, chunk_results, session_id)

    if all_sent:
        _advance_pending(pending_file, pending_data, transcript_path)
    else:
        logger.error("[HOOKS] telegram: delivery failed — keeping pending for retry")

    return {"stdout": "", "exit_code": 0, "sound": "telegram response"}


def _extract_response(hook_data: dict, transcript_path: str, pending_data: dict) -> str | None:
    """Try JSONL transcript extraction with retries, fall back to last_assistant_message."""
    if pending_data.get("mirror"):
        return _extract_mirror_response(transcript_path, pending_data)

    response_text = None

    if transcript_path:
        start_line = pending_data.get("transcript_line_after", 0)
        for attempt in range(3):
            response_text = extract_assistant_response(transcript_path, start_line=start_line)
            if response_text:
                logger.info(
                    "[HOOKS] telegram: JSONL extraction: %d chars (attempt %d)", len(response_text), attempt + 1
                )
                break
            if attempt < 2:
                delay = [0.2, 0.5][attempt]
                logger.info("[HOOKS] telegram: JSONL retry %.1fs (attempt %d/3)", delay, attempt + 1)
                time.sleep(delay)

    if not response_text and not pending_data.get("delivered"):
        response_text = (hook_data.get("last_assistant_message") or "").strip()
        if response_text:
            logger.info("[HOOKS] telegram: using last_assistant_message fallback (%d chars)", len(response_text))

    return response_text or None


def _extract_mirror_response(transcript_path: str, pending_data: dict) -> str | None:
    """Extract all new turns for mirror delivery with retries."""
    if not transcript_path:
        return None
    start_line = pending_data.get("transcript_line_after", 0)
    for attempt in range(3):
        result = extract_mirror_turn(transcript_path, start_line)
        if result:
            logger.info("[HOOKS] telegram: mirror extraction: %d chars (attempt %d)", len(result), attempt + 1)
            return result
        if attempt < 2:
            delay = [0.2, 0.5][attempt]
            logger.info("[HOOKS] telegram: mirror retry %.1fs (attempt %d/3)", delay, attempt + 1)
            time.sleep(delay)
    return None


def _prepend_branch_prefix(text: str) -> str:
    """Prepend @branch identifier so user knows which branch responded."""
    try:
        branch_name = Path.cwd().name
        return f"@{branch_name}\n\n{text}"
    except OSError:
        logger.info("[HOOKS] telegram: could not resolve CWD for branch prefix")
        return text


def _check_log_streamer_active() -> bool:
    """Check if agent activity logs were recently streaming; wait for flush if so."""
    if not os.environ.get("AIPASS_BOT_ID"):
        return False
    try:
        branch_dir = Path.cwd().name
        agent_log = Path.home() / "system_logs" / f"{branch_dir}_agent.log"
        if agent_log.exists() and (time.time() - agent_log.stat().st_mtime) < 30:
            logger.info("[HOOKS] telegram: waiting for log_streamer flush")
            time.sleep(7)
            return True
    except OSError:
        logger.info("[HOOKS] telegram: could not check log_streamer status")
    return False


def _deliver_chunks(
    chunks: list[str],
    bot_token: str,
    chat_id: int,
    processing_message_id: int | None,
    logs_were_active: bool,
    streaming: bool = False,
) -> tuple[bool, list[dict]]:
    """Send all response chunks to Telegram. Returns (all_sent, per-chunk results)."""
    chunk_results: list[dict] = []
    all_sent = True
    single = len(chunks) == 1

    for i, chunk in enumerate(chunks):
        if i == 0 and processing_message_id:
            should_reconcile = streaming or (single and not logs_were_active)
            if should_reconcile:
                result = edit_telegram_message(bot_token, chat_id, processing_message_id, chunk)
                if result["ok"]:
                    chunk_results.append({"idx": i, "method": "edit", **result})
                    continue
                result = _send_with_retry(bot_token, chat_id, chunk)
                chunk_results.append({"idx": i, "method": "send", **result})
                if not result["ok"]:
                    all_sent = False
                continue
            edit_telegram_message(bot_token, chat_id, processing_message_id, "Done.")

        prefix = f"[{i + 1}/{len(chunks)}]\n" if not single else ""
        result = _send_with_retry(bot_token, chat_id, prefix + chunk)
        chunk_results.append({"idx": i, "method": "send", **result})
        if not result["ok"]:
            all_sent = False

    return all_sent, chunk_results


def _advance_pending(pending_file: Path, pending_data: dict, transcript_path: str) -> None:
    """Advance transcript cursor so later Stops can deliver new text."""
    is_mirror = pending_data.get("mirror", False)
    if not transcript_path:
        if not is_mirror:
            pending_file.unlink(missing_ok=True)
        logger.info("[HOOKS] telegram: no transcript — pending %s", "kept (mirror)" if is_mirror else "removed")
        return
    try:
        line_count = 0
        with open(transcript_path, encoding="utf-8") as f:
            for _ in f:
                line_count += 1
        pending_data["transcript_line_after"] = line_count
        pending_data["delivered"] = True
        pending_data["processing_message_id"] = None
        pending_file.write_text(json.dumps(pending_data, indent=2), encoding="utf-8")
        logger.info("[HOOKS] telegram: cursor advanced to line %d", line_count)
    except OSError as e:
        logger.warning("[HOOKS] telegram: cursor advance failed: %s", e)
        if not is_mirror:
            pending_file.unlink(missing_ok=True)


def _write_delivery_log(intended_text: str, chunks: list[str], chunk_results: list[dict], session_id: str) -> None:
    """Write JSONL record documenting what was delivered to Telegram."""
    intended_sha = hashlib.sha256(intended_text.encode("utf-8")).hexdigest()[:16]

    delivered_parts = []
    for cr in chunk_results:
        text = cr.get("text") or ""
        text = re.sub(r"^\[\d+/\d+\]\n", "", text)
        delivered_parts.append(text)
    delivered_concat = "\n\n".join(delivered_parts)
    delivered_sha = hashlib.sha256(delivered_concat.encode("utf-8")).hexdigest()[:16]

    all_ok = all(cr.get("ok") for cr in chunk_results)
    match = all_ok and intended_sha == delivered_sha

    culprit = None
    if not match:
        failed = [cr["idx"] for cr in chunk_results if not cr.get("ok")]
        if failed:
            culprit = f"delivery_failed: chunks {failed}"
        elif abs(len(intended_text) - len(delivered_concat)) > max(len(intended_text) * 0.1, 20):
            culprit = f"length_mismatch: intended={len(intended_text)} delivered={len(delivered_concat)}"
        else:
            culprit = "formatting_conversion"

    record = {
        "ts": time.time(),
        "session": session_id[:8] if session_id else "",
        "intended_text": intended_text,
        "intended_sha256": intended_sha,
        "intended_len": len(intended_text),
        "chunks": [
            {
                "idx": cr.get("idx"),
                "method": cr.get("method"),
                "message_id": cr.get("message_id"),
                "ok": cr.get("ok"),
                "returned_len": len(cr.get("text") or ""),
            }
            for cr in chunk_results
        ],
        "delivered_concat": delivered_concat,
        "delivered_sha256": delivered_sha,
        "delivered_len": len(delivered_concat),
        "match": match,
    }
    if culprit:
        record["culprit"] = culprit

    try:
        append_jsonl(_get_delivery_log(), record)
    except OSError as e:
        logger.warning("[HOOKS] telegram: delivery log write failed: %s", e)
