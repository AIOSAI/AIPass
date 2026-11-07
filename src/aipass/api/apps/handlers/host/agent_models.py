# =================== AIPass ====================
# Name: agent_models.py
# Description: Host API Agent Models — each provider's models, and the line that switches a live agent's model
# Version: 1.0.0
# Created: 2026-11-05
# Modified: 2026-11-05
# =============================================

"""
Host API Agent Models
Reference: docs/host_agent_chat.md. Ported from Seed Dev's deck (ui/models.py, the switch in ui/agents.py).
Claude takes `/model <alias>`; Codex takes `/model <slug> [--reasoning=<effort>]`. OpenCode's `/models` only opens
its picker, so its models are listed but never typed. A provider handoff types the seat's own switch command
(.claude/commands, .codex/skills, .opencode/commands), which preps its memories and respawns its pane.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import agent_chat
from aipass.api.apps.handlers.host.read_cache import ReadCache

CLAUDE_ALIASES = ("opus", "fable", "sonnet", "haiku")
PROVIDERS = ("claude", "codex", "opencode")
# (from, to) -> the seat's own switch command, and whether it takes a model word; Claude picks fable or opus itself.
SWITCHES = {
    ("claude", "codex"): ("/codex", True),
    ("claude", "opencode"): ("/opencode", True),
    ("codex", "claude"): ("$claude", False),
    ("codex", "opencode"): ("$opencode", True),
    ("opencode", "claude"): ("/claude", False),
    ("opencode", "codex"): ("/codex", False),
}
CODEX_CACHE = Path(".codex") / "models_cache.json"
OPENCODE_TTL_SECONDS = 60.0
OPENCODE_TIMEOUT_SECONDS = 20
# A failed listing raises inside the producer, so only a good one is kept for the minute.
OPENCODE_LISTING = ReadCache("opencode_models", OPENCODE_TTL_SECONDS)


class Refused(Exception):
    """A switch the agent's provider does not take; the words are built here from the catalog and the request."""


class OpenCodeUnlisted(Exception):
    """`opencode models` gave no listing; the words are the reason /v1/models shows."""


def _codex() -> Dict[str, Any]:
    """Codex's listed models from the account's cache, read-only: slug, display name, efforts."""
    path = Path.home() / CODEX_CACHE
    try:
        rows = json.loads(path.read_text(encoding="utf-8")).get("models") or []
    except FileNotFoundError:
        logger.info("[host_api] no Codex model cache at %s", path)
        return {"models": [], "reason": "no Codex model cache at ~/.codex/models_cache.json"}
    except (OSError, ValueError, AttributeError) as exc:
        logger.warning("[host_api] unreadable Codex model cache %s: %s", path, exc)
        return {"models": [], "reason": "the Codex model cache could not be read"}
    listed = [r for r in rows if isinstance(r, dict) and r.get("visibility") == "list" and r.get("slug")]
    return {
        "models": [
            {
                "name": r["slug"],
                "label": r.get("display_name") or r["slug"],
                "efforts": [e.get("effort") for e in r.get("supported_reasoning_levels") or [] if e.get("effort")],
            }
            for r in listed
        ]
    }


def _opencode_listing() -> Dict[str, Any]:
    """`opencode models`, each grouped by its provider prefix; OpenCodeUnlisted when there is no listing."""
    binary = shutil.which("opencode") or str(Path.home() / ".opencode" / "bin" / "opencode")
    if not Path(binary).is_file():
        raise OpenCodeUnlisted("opencode was not found")
    try:
        done = subprocess.run(
            [binary, "models"], capture_output=True, text=True, timeout=OPENCODE_TIMEOUT_SECONDS, check=False
        )
    except subprocess.TimeoutExpired as exc:
        logger.warning("[host_api] opencode models timed out: %s", exc)
        raise OpenCodeUnlisted(f"opencode models did not answer in {OPENCODE_TIMEOUT_SECONDS}s") from exc
    if done.returncode != 0:
        logger.warning("[host_api] opencode models failed: %s", done.stderr.strip())
        raise OpenCodeUnlisted(f"opencode models failed (exit {done.returncode})")
    names = [line.strip() for line in done.stdout.splitlines() if "/" in line.strip()]
    return {
        "models": [{"name": n, "group": n.split("/", 1)[0]} for n in names],
        "inline": False,
        "reason": "picker only",
    }


def _opencode_models() -> Dict[str, Any]:
    """OpenCode's listing, cached OPENCODE_TTL_SECONDS; a missing or failing opencode is a reason, not an error."""
    try:
        return OPENCODE_LISTING.get("models", _opencode_listing)
    except OpenCodeUnlisted as exc:
        return {"models": [], "inline": False, "reason": str(exc)}


def listing() -> Dict[str, Any]:
    """Every provider's models and `switch`: from -> to -> whether that seat's switch command takes a model."""
    answer = {
        "claude": {"models": [{"name": a} for a in CLAUDE_ALIASES]},
        "codex": _codex(),
        "opencode": _opencode_models(),
        "switch": {src: {dst: takes for (a, dst), (_, takes) in SWITCHES.items() if a == src} for src in PROVIDERS},
    }
    json_handler.log_operation("host_api_models_listed", {"codex": len(answer["codex"]["models"])})
    return answer


def _switch_command(source: str, target: str, model: Optional[str]) -> str:
    """The seat's own line that moves it from *source* to *target*, with *model* when that command takes one."""
    known = SWITCHES.get((source, target))
    if known is None:
        raise Refused(f"no switch from {source} to {target!r}")
    word, takes = known
    if model is not None:
        if not takes:
            raise Refused(f"{word} takes no model on a {source} seat; it opens the {target} default")
        listed = _codex() if target == "codex" else _opencode_models()
        if model not in [m["name"] for m in listed["models"]]:
            raise Refused(f"{model!r} is not a listed {target} model")
    return f"{word} {model}" if model is not None else word


def _command(provider: str, model: Optional[str], effort: Optional[str]) -> str:
    """The provider's own slash line that switches to *model*."""
    if provider == "claude":
        if model not in CLAUDE_ALIASES:
            raise Refused(f"model must be one of {', '.join(CLAUDE_ALIASES)}")
        return f"/model {model}"
    if provider == "codex":
        row = next((m for m in _codex()["models"] if m["name"] == model), None)
        if row is None:
            raise Refused(f"{model!r} is not a listed Codex model")
        if effort is None:
            return f"/model {model}"
        if effort not in row["efforts"]:
            raise Refused(f"{model} takes effort {', '.join(row['efforts'])}")
        # Codex 0.164 refuses a bare effort word: "Unexpected argument 'low'. Use '--reasoning=<level>'".
        return f"/model {model} --reasoning={effort}"
    if provider == "opencode":
        raise Refused("OpenCode's /models only opens its picker; switch it in the agent's own room")
    raise Refused(f"no model switch for provider {provider!r}")


def switch_line(
    row: Dict[str, Any], provider: Optional[str], model: Optional[str], effort: Optional[str]
) -> Tuple[Optional[str], Optional[str]]:
    """(the line to type, None) for one roster row, or (None, why the switch is refused).

    A dispatched agent keeps the model it was dispatched with. *provider* other than the row's is a handoff.
    """
    if row.get("dispatched"):
        return None, f"{row.get('name')} is dispatched: a dispatched agent keeps the model it was dispatched with"
    current = row.get("provider") or "claude"  # no provider field: an older baud-cli, whose seats are Claude
    try:
        if provider is None or provider == current:
            return _command(current, model, effort), None
        return _switch_command(current, provider, model), None
    except Refused as exc:
        return None, str(exc)


def busy_state(row: Dict[str, Any]) -> Optional[str]:
    """'working' or 'waiting' while a typed /model would only queue behind the turn; None when it can be typed."""
    state, _ = agent_chat.agent_state(row, agent_chat.engine_rows() or [])
    return state if state in (agent_chat.STATE_WORKING, agent_chat.STATE_WAITING) else None


def type_line(project: str, name: str, line: str) -> None:
    """Type *line* into the agent's room, then one more Enter; part A's refusals (AgentNoRoom, SendFailed) pass up.

    The first Enter only takes the slash menu's suggestion; the command runs on the next one (seen twice in a live
    room: /model ran when the next send pressed Enter, and that send's text was lost). On an empty prompt Enter
    does nothing. allow is the Enter key.
    """
    agent_chat.send(project, name, line)
    agent_chat.press(project, name, "allow")
    json_handler.log_operation("host_api_agent_model", {"agent": name, "project": project, "line": line})
