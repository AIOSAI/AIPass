# =================== AIPass ====================
# Name: smoke.py
# Version: 1.0.1
# Description: Smoke: one isolated live turn per provider; pass only when a hook's own nonce ack is read back
# Branch: hooks
# Layer: apps/handlers/parity
# Created: 2026-10-28
# Modified: 2026-10-28
# =============================================

"""One isolated live turn per provider: did a hook's own output reach the provider in that session.

The prompt asks for "ok" and carries aipass-smoke:<nonce>; the temporal row, wired on every provider,
answers smoke-ack:<nonce>, a string the prompt does not carry. The ack is read back from the provider's
own record of the hook in the session it printed, never from the model's reply: Claude's transcript
attachment row, Codex's rollout developer message, OpenCode's stored user message (its plugin appends
the hook context there). The turn runs no tool and writes nothing; the branch files a turn moves are
restored byte for byte, and AIPASS_HOOK_PROBE keeps it from starting @memory's archive of the branch.
"""

import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from aipass.hooks.apps.handlers.config.opencode_paths import opencode_db_path, opencode_plugin_path, opencode_store
from aipass.hooks.apps.handlers.json import json_handler
from aipass.hooks.apps.handlers.parity import runner
from aipass.prax.apps.modules.logger import system_logger as logger

PASS, FAIL, SKIP = "pass", "fail", "skip"
TIMEOUT = 180
HOST_STATE = (Path(".ai_mail.local") / "session.json", Path(".ai_mail.local") / "grounding.json")
PROMPT = (
    "This is an authorized AIPass hooks smoke test. Reply with the word ok and nothing else. "
    "Run no tools and do not run your startup protocol. aipass-smoke:{nonce}"
)
_NO_LOGIN = (
    "not logged in",
    "/login",
    "invalid api key",
    "unauthorized",
    "authentication",
    "providermodelnotfound",
    "model not found",
)
_LIMITED = ("rate limit", "rate_limit", "usage limit", "quota")


@dataclass(frozen=True)
class SmokeResult:
    provider: str
    status: str  # pass | fail | skip
    why: str
    session_id: str = ""
    elapsed_ms: int = 0


def _claude_ack(session_id: str, ack: str) -> bool | None:
    """The transcript's UserPromptSubmit hook attachment carries the ack; None when no transcript names the session."""
    # launch_env drops CLAUDE_CONFIG_DIR with every CLAUDE* key, so the child writes under the default home.
    found = sorted((Path.home() / ".claude" / "projects").glob(f"*/{session_id}.jsonl"))
    if not found:
        return None
    for line in found[0].read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.debug("[HOOKS] smoke: torn transcript line: %s", exc)
            continue
        attachment = record.get("attachment") if isinstance(record, dict) else None
        if record.get("type") == "attachment" and isinstance(attachment, dict):
            if attachment.get("hookEvent") == "UserPromptSubmit" and ack in str(attachment.get("content", "")):
                return True
    return False


def _codex_ack(session_id: str, ack: str) -> bool | None:
    """The rollout's developer message (hooks.additional_context) carries the ack; None when no rollout is found."""
    found = sorted((Path.home() / ".codex" / "sessions").glob(f"*/*/*/rollout-*{session_id}.jsonl"))
    if not found:
        return None
    for line in found[0].read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.debug("[HOOKS] smoke: torn rollout line: %s", exc)
            continue
        payload = record.get("payload") if isinstance(record, dict) else None
        if record.get("type") == "response_item" and isinstance(payload, dict) and payload.get("role") == "developer":
            if ack in json.dumps(payload.get("content")):
                return True
    return False


def _opencode_ack(session_id: str, ack: str) -> bool | None:
    """A stored user message of the session carries the ack; None when the store is absent."""
    if not opencode_db_path().is_file():
        return None
    query = "SELECT data FROM session_message WHERE session_id = ? AND type = 'user'"
    with closing(opencode_store()) as conn:
        rows = conn.execute(query, (session_id,)).fetchall()
    return any(ack in row[0] for row in rows)


ACK_READERS = {"claude": _claude_ack, "codex": _codex_ack, "opencode": _opencode_ack}


def _plugin_wired() -> bool:
    """OpenCode loads aipass.ts from OPENCODE_CONFIG_DIR's plugins/, or the user-level config's."""
    extra = os.environ.get("OPENCODE_CONFIG_DIR")
    return opencode_plugin_path().is_file() or bool(extra and (Path(extra) / "plugins" / "aipass.ts").is_file())


def _snapshot(branch: Path) -> dict[Path, bytes | None]:
    state = {}
    for rel in HOST_STATE:
        try:
            state[branch / rel] = (branch / rel).read_bytes()
        except FileNotFoundError:
            logger.debug("[HOOKS] smoke: %s absent before the turn", rel)
            state[branch / rel] = None
    return state


def _restore(state: dict[Path, bytes | None]) -> None:
    for path, before in state.items():
        try:
            if before is None:
                path.unlink(missing_ok=True)
            elif not path.is_file() or path.read_bytes() != before:
                path.write_bytes(before)
        except OSError as exc:
            logger.error("[HOOKS] smoke: host state %s not restored: %s", path, exc)


def _turn(provider: str, branch: Path, model: str, prompt: str) -> tuple[SmokeResult | None, str, int]:
    """Launch once (OpenCode with no model: each free model once); a result now, or the stdout to read."""
    models = (model,) if model or provider != "opencode" else runner.OPENCODE_MODELS
    env = runner.launch_env(branch)
    # auto_process and rollover read it: the turn must not start @memory's archive of the branch's .trinity.
    env["AIPASS_HOOK_PROBE"] = "1"
    start = time.monotonic()
    for name in models:
        try:
            done = subprocess.run(
                runner.launch_argv(provider, name),
                input=prompt,
                cwd=str(branch),
                env=env,
                capture_output=True,
                text=True,
                timeout=TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            logger.warning("[HOOKS] smoke: %s timed out: %s", provider, exc)
            return SmokeResult(provider, FAIL, f"the launch did not finish in {TIMEOUT} s"), "", 0
        except OSError as exc:
            logger.warning("[HOOKS] smoke: %s did not launch: %s", provider, exc)
            return SmokeResult(provider, FAIL, "the launch did not start"), "", 0
        if not (provider == "opencode" and runner.free_limited(done.stdout)):
            break
        logger.warning("[HOOKS] smoke: %s answered the free limit (429)", name)
    else:
        return SmokeResult(provider, SKIP, "free limit reached on every free model"), "", 0
    elapsed = int((time.monotonic() - start) * 1000)
    session_id = runner.session_id_of(provider, done.stdout)
    if session_id:
        return None, session_id, elapsed
    said = (done.stdout + done.stderr).lower()
    if any(mark in said for mark in _LIMITED):
        return SmokeResult(provider, SKIP, "rate or usage limit", elapsed_ms=elapsed), "", elapsed
    if any(mark in said for mark in _NO_LOGIN):
        return (
            SmokeResult(provider, SKIP, "not logged in, or no provider for the model", elapsed_ms=elapsed),
            "",
            elapsed,
        )
    return SmokeResult(provider, FAIL, f"no session id (exit {done.returncode})", elapsed_ms=elapsed), "", elapsed


def smoke(provider: str, branch: Path, model: str = "") -> SmokeResult:
    """One "say ok" turn on *branch*: pass when the temporal row's nonce ack is in the provider's record of it."""
    if provider not in ACK_READERS:
        raise ValueError(f"unknown provider {provider}")
    if not shutil.which(runner.launch_argv(provider, model)[0]):
        return SmokeResult(provider, SKIP, f"{provider} is not installed")
    if provider == "opencode" and not _plugin_wired():
        return SmokeResult(provider, SKIP, "the AIPass plugin is not installed for OpenCode")
    nonce = secrets.token_hex(8)
    state = _snapshot(branch)
    try:
        result, session_id, elapsed = _turn(provider, branch, model, PROMPT.format(nonce=nonce))
    finally:
        _restore(state)
    if result is None:
        try:
            seen = ACK_READERS[provider](session_id, f"smoke-ack:{nonce}")
        except (OSError, UnicodeDecodeError, sqlite3.Error) as exc:
            logger.warning("[HOOKS] smoke: %s record unreadable: %s", provider, exc)
            seen = None
        if seen is None:
            result = SmokeResult(provider, SKIP, "no readback: the provider's record of the session is not found")
        elif seen:
            result = SmokeResult(provider, PASS, "the temporal hook's nonce ack is in the session's record")
        else:
            result = SmokeResult(provider, FAIL, "the session ran but its record carries no hook nonce ack")
        result = SmokeResult(provider, result.status, result.why, session_id, elapsed)
    json_handler.log_operation("smoke", {**result.__dict__, "model": model})
    logger.info("[HOOKS] smoke: %s %s (%s)", provider, result.status, result.why)
    return result
