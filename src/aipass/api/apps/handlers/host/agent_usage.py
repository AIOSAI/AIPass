# =================== AIPass ====================
# Name: agent_usage.py
# Description: Host API Agent Usage — one live agent's context window and its provider's plan limits
# Version: 1.0.0
# Created: 2026-11-05
# Modified: 2026-11-05
# =============================================

"""
Host API Agent Usage
Reference: docs/host_agent_chat.md. Ported as it is from Seed Dev's deck (ui/usage.py).
Claude: context from the transcript's last assistant usage row; plan limits from Anthropic's oauth/usage endpoint,
read with this machine's Claude Code sign-in (~/.claude/.credentials.json) and cached 60 s per token; a 429 backs
off (Retry-After, else 5 minutes doubling to 30). The token stays in this process: never answered, never logged,
the cache keyed by its sha256. Codex: both from the rollout's newest token_count rows, no network. OpenCode: not wired.
"""

import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import agent_chat
from aipass.api.apps.handlers.host import agent_transcript as transcript

CLAUDE_WINDOW = 350_000  # the deck's one context window; a transcript row does not name its own
CREDENTIALS = Path(".claude") / ".credentials.json"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
USAGE_BETA = "oauth-2025-04-20"
CACHE_SECONDS = 60.0
RATE_LIMIT_SECONDS = 300.0  # a 429 without Retry-After: retrying every minute only kept it rate limited
BACKOFF_CEILING_SECONDS = 1800.0  # doubling stops at 30 min so the ring still recovers within the half hour
TIMEOUT_SECONDS = 5
SEVERITIES = ("normal", "warning", "critical")
WINDOW_LABELS = {300: "5 hour", 10080: "Weekly"}
# good: (token hash, limits, local time read) of the last answer with limits, shown while a 429 holds
# backoff: the hold of the current 429 streak in seconds, 0 when the last answer was not a 429
_cache: Dict[str, Any] = {}


def reset_cache() -> None:
    """Forget the last plan-limits answer and any 429 streak."""
    _cache.clear()
    _cache.update(key=None, at=-CACHE_SECONDS, ttl=CACHE_SECONDS, answer=([], None), good=None, backoff=0.0)


reset_cache()


def _rows(path: Optional[Path], marker: bytes) -> List[dict]:
    """The transcript's rows holding *marker*, newest first; a bad line is logged and skipped."""
    if path is None or not path.exists():
        return []
    rows = []
    for _, chunk in reversed(transcript.tail_rows(path, transcript.MODEL_TAIL_BYTES)):
        if marker not in chunk:
            continue
        try:
            rows.append(json.loads(chunk))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.info("[host_api] usage skipped a bad transcript line in %s: %s", path.name, exc)
    return rows


def _context(used: int, total: int) -> dict:
    """{used, total, percent} of one context window."""
    return {"used": used, "total": total, "percent": round(100 * used / total, 1) if total else 0.0}


def _severity(percent: float) -> str:
    """normal, warning from 75%, critical from 90%."""
    return "critical" if percent >= 90 else "warning" if percent >= 75 else "normal"


def claude_context(path: Optional[Path]) -> Optional[dict]:
    """Input plus both cache counts of the last assistant reply (output is not context yet); None before a reply."""
    for row in _rows(path, b'"usage"'):
        message = row.get("message") or {}
        usage = message.get("usage")
        if row.get("type") != "assistant" or not isinstance(usage, dict) or message.get("model") == "<synthetic>":
            continue
        keys = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        return _context(sum(int(usage.get(k) or 0) for k in keys), CLAUDE_WINDOW)
    return None


def _claude_limit(item: dict) -> Optional[dict]:
    """One oauth/usage limit as a ring row; None for a kind the ring does not show."""
    kind = str(item.get("kind") or "")
    if kind == "weekly_all":
        label = "All models"
    elif kind == "weekly_scoped":
        label = f"{((item.get('scope') or {}).get('model') or {}).get('display_name') or 'One model'} only"
    elif kind.startswith("five_hour"):
        label = "5 hour"
    else:
        return None
    percent = float(item.get("percent") or 0)
    severity = item.get("severity") if item.get("severity") in SEVERITIES else _severity(percent)
    return {"label": label, "percent": percent, "severity": severity, "resets_at": item.get("resets_at")}


def _token() -> Tuple[Optional[str], Optional[str]]:
    """(this machine's Claude access token, None), or (None, why there is none)."""
    try:
        oauth = json.loads((Path.home() / CREDENTIALS).read_text(encoding="utf-8")).get("claudeAiOauth") or {}
    except FileNotFoundError:
        logger.info("[host_api] usage: no Claude credentials file")
        return None, "Claude plan limits unavailable: not signed in on this machine"
    except (OSError, ValueError, AttributeError) as exc:
        logger.warning("[host_api] usage: Claude credentials unreadable: %s", type(exc).__name__)
        return None, "Claude plan limits unavailable: the sign-in file could not be read"
    token, expires = oauth.get("accessToken"), oauth.get("expiresAt")
    if not token or not isinstance(token, str):
        return None, "Claude plan limits unavailable: not signed in on this machine"
    if isinstance(expires, (int, float)) and expires / 1000 < time.time():
        return None, "Claude plan limits unavailable: the sign-in on this machine has expired"
    return token, None


def _retry_after(value: Optional[str]) -> Optional[float]:
    """Seconds a 429's Retry-After asks for (delta seconds or an HTTP date); None when absent or unparseable."""
    if value and value.strip().isdigit():
        return float(value.strip())
    try:
        return max(0.0, (parsedate_to_datetime(value or "") - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


def claude_limits() -> Tuple[List[dict], Optional[str]]:
    """(limits, note) for this machine's Claude account, one call per 60 s per token; note says why when empty.

    A 429 holds for its Retry-After, else 5 minutes doubling per further 429 up to BACKOFF_CEILING_SECONDS, makes no
    call while it holds, logs once when the streak starts, and shows the last good limits with a note saying from when.
    """
    token, why = _token()
    if token is None:
        return [], why
    key = hashlib.sha256(token.encode()).hexdigest()
    if _cache["key"] == key and time.monotonic() - _cache["at"] < _cache["ttl"]:
        return _cache["answer"]
    request = urllib.request.Request(
        USAGE_URL, headers={"Authorization": f"Bearer {token}", "anthropic-beta": USAGE_BETA}
    )
    ttl, backoff = CACHE_SECONDS, 0.0
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as resp:
            items = json.loads(resp.read()).get("limits") or []
        limits = [lim for lim in (_claude_limit(i) for i in items if isinstance(i, dict)) if lim]
        answer: Tuple[List[dict], Optional[str]] = (limits, None if limits else "Claude reported no plan limits")
        if limits:
            _cache["good"] = (key, limits, datetime.now())
    # HTTPError is a URLError: caught first, or every 429 would read as unreachable.
    except urllib.error.HTTPError as exc:
        answer = ([], f"Claude plan limits unavailable: the usage endpoint answered {exc.code}")
        if exc.code != 429:
            logger.warning("[host_api] usage: oauth/usage answered %s", exc.code)
        else:
            wait = _retry_after(exc.headers.get("Retry-After") if exc.headers else None)
            if wait is None:
                wait = min(BACKOFF_CEILING_SECONDS, max(RATE_LIMIT_SECONDS, 2 * _cache["backoff"]))
            ttl = backoff = max(CACHE_SECONDS, wait)
            if not _cache["backoff"]:
                logger.warning("[host_api] usage: oauth/usage answered 429, backing off %.0f s", ttl)
            good = _cache["good"]
            if good and good[0] == key:
                answer = (good[1], f"Claude plan limits from {good[2]:%H:%M}: the usage endpoint is rate limited")
    # A connect timeout is a URLError over TimeoutError, a read timeout a bare TimeoutError (an OSError).
    except (urllib.error.URLError, OSError, ValueError, AttributeError) as exc:
        logger.warning("[host_api] usage: oauth/usage could not be read: %s", type(exc).__name__)
        answer = ([], "Claude plan limits unavailable: the usage endpoint could not be reached")
        backoff = _cache["backoff"]  # no answer is not a reset: a blip mid-streak keeps the streak's hold
    _cache.update(key=key, at=time.monotonic(), ttl=ttl, answer=answer, backoff=backoff)
    return answer


def _codex_limit(window: dict) -> dict:
    """One Codex rate-limit window as a ring row."""
    minutes = int(window.get("window_minutes") or 0)
    percent = float(window.get("used_percent") or 0)
    stamp = window.get("resets_at")
    resets = datetime.fromtimestamp(stamp, timezone.utc).isoformat() if isinstance(stamp, (int, float)) else None
    label = WINDOW_LABELS.get(minutes, f"{minutes / 60:g} hour")
    return {"label": label, "percent": percent, "severity": _severity(percent), "resets_at": resets}


def codex_usage(path: Optional[Path]) -> dict:
    """Context and rate limits from the rollout's newest token_count rows: the newest with info, the newest with
    rate limits (older Codex rows lack them)."""
    context, limits = None, None
    for row in _rows(path, b'"token_count"'):
        payload = row.get("payload") or {}
        if row.get("type") != "event_msg" or payload.get("type") != "token_count":
            continue
        info, rates = payload.get("info"), payload.get("rate_limits")
        if context is None and isinstance(info, dict):
            last = info.get("last_token_usage") or {}
            context = _context(int(last.get("total_tokens") or 0), int(info.get("model_context_window") or 0))
        if limits is None and isinstance(rates, dict) and rates.get("primary"):
            limits = [_codex_limit(rates[k]) for k in ("primary", "secondary") if isinstance(rates.get(k), dict)]
        if context is not None and limits is not None:
            break
    return {"context": context, "limits": limits or [], "note": None if context else "no turn yet"}


def read(project: str, name: str) -> Dict[str, Any]:
    """One live agent's {provider, context, limits, note}; agent_chat.AgentUnknown when it is not live."""
    row = agent_chat.find_agent(project, name)
    provider = row.get("provider") or "claude"  # no provider field: an older baud-cli, whose seats are Claude
    if provider == "codex":
        answer = codex_usage(transcript.transcript_path(row))
    elif provider == "claude":
        limits, note = claude_limits()
        context = claude_context(transcript.transcript_path(row))
        answer = {"context": context, "limits": limits, "note": note if context else note or "no reply yet"}
    else:
        label = {"opencode": "OpenCode"}.get(provider, provider)
        answer = {"context": None, "limits": [], "note": f"{label} usage is not wired yet"}
    json_handler.log_operation("host_api_agent_usage", {"agent": name, "project": project, "provider": provider})
    return {"provider": provider, **answer}
