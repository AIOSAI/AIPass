# =================== AIPass ====================
# Name: engine.py
# Version: 1.3.0
# Description: Hook engine — unified dispatcher for all hook events
# Branch: hooks
# Layer: apps/modules
# Created: 2026-05-18
# Modified: 2026-08-16
# =============================================

"""Hook engine — dispatches hook events to handlers, logs via prax + JSONL."""

import importlib
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import err_console
from aipass.hooks.apps.handlers.cli.help_flags import wants_help
from aipass.hooks.apps.handlers.config.diagnostics import log_entry as _log, tail_log
from aipass.hooks.apps.handlers.module_root import module_file

CONSOLE = err_console
BRANCH_ROOT = module_file(__file__).parent.parent.parent

HELP_COMMANDS = [
    ("log", "Tail recent hook activity (last 20 entries)"),
]

VERBOSE_LOG_ENV = "AIPASS_HOOKS_VERBOSE_LOG"


def _log_detail(message: str, *args) -> None:
    """Per-hook narration — DEBUG-tier detail, suppressed by default.

    Every hook execution is already recorded in full (agent, exit code, timing,
    stderr, cwd) in logs/engine.jsonl, which is the source of truth for hook
    diagnostics. These lines are the human-readable echo of that, and at ~3 per
    tool call they dominated system_logs/hooks_engine.log — enough to trip
    prax's runaway detector on ordinary multi-agent operation.

    prax's SystemLogger exposes only info/warning/error, so there is no DEBUG
    level to demote to; the switch lives here instead. Set
    AIPASS_HOOKS_VERBOSE_LOG=1 to restore them. Read per call so tests and live
    sessions can toggle it without re-importing.
    """
    if os.environ.get(VERBOSE_LOG_ENV) == "1":
        logger.info(message, *args)


def _run_hook(hook_cmd: str, stdin_data: str, timeout_s: int = 30) -> dict:
    """Run a single hook subprocess, capture output and timing."""
    env = os.environ.copy()
    start = time.monotonic()
    try:
        result = subprocess.run(
            hook_cmd,
            shell=True,
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
        )
        elapsed_ms = (time.monotonic() - start) * 1000
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "elapsed_ms": round(elapsed_ms, 1),
        }
    except subprocess.TimeoutExpired:
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.error("[HOOKS] timeout after %ds: %s", timeout_s, hook_cmd)
        return {"exit_code": -1, "stdout": "", "stderr": "TIMEOUT", "elapsed_ms": round(elapsed_ms, 1)}
    except OSError as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.error("[HOOKS] exec error: %s: %s", hook_cmd, exc)
        return {"exit_code": -1, "stdout": "", "stderr": str(exc), "elapsed_ms": round(elapsed_ms, 1)}


def _run_handler(handler_path: str, hook_data: dict, timeout_s: int = 30) -> dict:
    """Call a handler function directly (no subprocess). Module imports handler.

    Runs the handler on a daemon thread and joins with a timeout so a hung
    handler can never stall the event — the calling thread returns control
    on expiry instead of blocking forever. The orphaned thread (if any) is
    left to die with the process; it never blocks interpreter exit.
    """
    start = time.monotonic()
    try:
        module_path, func_name = handler_path.rsplit(".", 1)
        if not module_path.startswith("aipass."):
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.warning(
                "[HOOKS] handler path refused (not in aipass.* namespace): %s",
                handler_path,
            )
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"handler namespace refused: {handler_path}",
                "elapsed_ms": round(elapsed_ms, 1),
            }
        module = importlib.import_module(module_path)
        handler_func = getattr(module, func_name)

        outcome = {}

        def _call():
            try:
                outcome["result"] = handler_func(hook_data)
            except Exception as exc:
                logger.info("[HOOKS] handler %s raised on worker thread: %s", handler_path, exc)
                outcome["error"] = exc  # re-raised on the calling thread below

        worker = threading.Thread(target=_call, daemon=True)
        worker.start()
        worker.join(timeout_s)

        if worker.is_alive():
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.error("[HOOKS] handler timeout after %ds: %s", timeout_s, handler_path)
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": "TIMEOUT",
                "elapsed_ms": round(elapsed_ms, 1),
            }

        if "error" in outcome:
            raise outcome["error"]

        result = outcome["result"]
        elapsed_ms = (time.monotonic() - start) * 1000
        return {
            "exit_code": result.get("exit_code", 0),
            "stdout": result.get("stdout", ""),
            "sound": result.get("sound", ""),
            "stderr": "",
            "elapsed_ms": round(elapsed_ms, 1),
        }
    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.error("[HOOKS] handler error %s: %s", handler_path, exc)
        return {"exit_code": -1, "stdout": "", "stderr": str(exc), "elapsed_ms": round(elapsed_ms, 1)}


def _matches(matcher: str, value: str) -> bool:
    """Check if a hook's matcher string matches the given value. Empty matcher = always match."""
    if not matcher:
        return True
    return value in matcher.split("|")


_BUDGET_KEYS = ("max_per_session", "min_spacing_turns", "cooldown_seconds")


def _budget_state_path(session_id: str = "") -> Path | None:
    if not session_id:
        session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not session_id:
        return None
    return Path(tempfile.gettempdir()) / f"aipass-handler-budget-{session_id}.json"


def _load_budget_state(session_id: str = "") -> dict:
    path = _budget_state_path(session_id)
    if path is None or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.info("[HOOKS] budget: state read failed: %s", exc)
        return {}


def _save_budget_state(state: dict, session_id: str = "") -> None:
    path = _budget_state_path(session_id)
    if path is None:
        return
    try:
        path.write_text(json.dumps(state), encoding="utf-8")
    except OSError as exc:
        logger.info("[HOOKS] budget: state write failed: %s", exc)


def _check_budget(hook_name: str, budget_cfg: dict, budget_state: dict) -> tuple[bool, str]:
    """Check if handler is within its per-session budget."""
    hs = budget_state.get(hook_name, {})
    fire_count = hs.get("fire_count", 0)

    max_fires = budget_cfg.get("max_per_session")
    if max_fires is not None and fire_count >= max_fires:
        return False, f"budget exhausted ({fire_count}/{max_fires})"

    if fire_count > 0:
        min_spacing = budget_cfg.get("min_spacing_turns")
        if min_spacing is not None:
            turns_since = hs.get("turns_since_fire", 0)
            if turns_since < min_spacing:
                return False, f"spacing ({turns_since}/{min_spacing})"

        cooldown = budget_cfg.get("cooldown_seconds")
        if cooldown is not None:
            elapsed = time.time() - hs.get("last_fire_time", 0.0)
            if elapsed < cooldown:
                return False, f"cooldown ({int(cooldown - elapsed)}s)"

    return True, "ok"


def dispatch(event_type: str, stdin_data: str, config: dict) -> tuple[str, int]:
    """Core dispatch — run hooks for event, return (merged_stdout, exit_code)."""
    if not config.get("hooks_enabled", True):
        logger.info("[HOOKS] all hooks disabled")
        _log({"ts": time.time(), "event": event_type, "action": "all_hooks_disabled"})
        return "", 0

    event_hooks = config.get(event_type, {})

    match_value = ""
    parsed = {}
    try:
        parsed = json.loads(stdin_data) if stdin_data.strip() else {}
        match_value = parsed.get("tool_name", "") or parsed.get("compact_type", "") or parsed.get("type", "")
    except json.JSONDecodeError as exc:
        logger.warning("[HOOKS] stdin parse error: %s", exc)
    payload_session_id = parsed.get("session_id", "")

    if event_type == "UserPromptSubmit":
        from aipass.hooks.apps.handlers.config.loader import never_enrolled_banner, trust_break_banner

        banner = trust_break_banner()
        if banner:
            logger.error("[HOOKS] trust break detected — emitting loud banner")
            _log({"ts": time.time(), "event": event_type, "action": "trust_break_banner"})
            return banner, 0

        nudge = never_enrolled_banner(payload_session_id)
        if nudge:
            logger.warning("[HOOKS] never-enrolled project — emitting one-time nudge")
            _log({"ts": time.time(), "event": event_type, "action": "never_enrolled_banner"})
            return nudge, 0

    if not event_hooks:
        _log({"ts": time.time(), "event": event_type, "action": "no_hooks_configured"})
        return "", 0

    outputs = []
    ran = 0  # hooks that actually executed — outputs only counts those that wrote stdout
    total_start = time.monotonic()
    budget_state = None
    budget_dirty = False

    for hook_name, hook_def in event_hooks.items():
        if not hook_def.get("enabled", True):
            _log_detail("[HOOKS] %s.%s skipped (disabled)", event_type, hook_name)
            _log({"ts": time.time(), "event": event_type, "hook": hook_name, "action": "skipped_disabled"})
            continue

        handler = hook_def.get("handler", "")
        command = hook_def.get("command", "")
        matcher = hook_def.get("matcher", "")
        if not handler and not command:
            continue

        if matcher and not _matches(matcher, match_value):
            _log(
                {
                    "ts": time.time(),
                    "event": event_type,
                    "hook": hook_name,
                    "action": "skipped_no_match",
                    "matcher": matcher,
                    "value": match_value,
                }
            )
            continue

        if command and not handler and config.get("_source") == "project":
            logger.warning(
                "[HOOKS] %s.%s REFUSED: command-type not allowed in per-project config",
                event_type,
                hook_name,
            )
            _log(
                {
                    "ts": time.time(),
                    "event": event_type,
                    "hook": hook_name,
                    "action": "refused_command_type",
                }
            )
            continue

        budget_cfg = {k: hook_def[k] for k in _BUDGET_KEYS if k in hook_def}
        if budget_cfg:
            if budget_state is None:
                budget_state = _load_budget_state(payload_session_id)
            hs = budget_state.setdefault(hook_name, {})
            hs["turns_since_fire"] = hs.get("turns_since_fire", 0) + 1
            budget_dirty = True
            allowed, reason = _check_budget(hook_name, budget_cfg, budget_state)
            if not allowed:
                _log_detail("[HOOKS] %s.%s budget: %s", event_type, hook_name, reason)
                _log(
                    {
                        "ts": time.time(),
                        "event": event_type,
                        "hook": hook_name,
                        "action": "budget_suppressed",
                        "reason": reason,
                    }
                )
                continue

        hook_timeout = hook_def.get("timeout", 30)
        if handler:
            result = _run_handler(handler, parsed, timeout_s=hook_timeout)
        else:
            result = _run_hook(command, stdin_data, timeout_s=hook_timeout)

        if result.get("stderr") == "TIMEOUT":
            logger.error(
                "[HOOKS] %s.%s TIMED OUT after %ds — never silently swallowed",
                event_type,
                hook_name,
                hook_timeout,
            )
            _log(
                {
                    "ts": time.time(),
                    "event": event_type,
                    "hook": hook_name,
                    "action": "timeout",
                    "timeout_s": hook_timeout,
                    "elapsed_ms": result["elapsed_ms"],
                }
            )
            try:
                from aipass.hooks.apps.sound import speak

                speak(f"{hook_name.replace('_', ' ')} timed out")
            except Exception as exc:
                logger.info("[HOOKS] sound playback failed for timeout %s.%s: %s", event_type, hook_name, exc)
            continue

        ran += 1
        _log_detail(
            "[HOOKS] %s.%s agent=%s exit=%d out=%db %dms",
            event_type,
            hook_name,
            parsed.get("agent_type", "") or "main",
            result["exit_code"],
            len(result["stdout"]),
            result["elapsed_ms"],
        )
        _log(
            {
                "ts": time.time(),
                "event": event_type,
                "hook": hook_name,
                "agent_type": parsed.get("agent_type", ""),
                "agent_id": parsed.get("agent_id", ""),
                "exit_code": result["exit_code"],
                "elapsed_ms": result["elapsed_ms"],
                "stdout_len": len(result["stdout"]),
                "stderr_preview": result["stderr"][:200] if result["stderr"] else "",
                "cwd": str(Path.cwd()),
            }
        )

        if result.get("sound"):
            try:
                from aipass.hooks.apps.sound import speak

                speak(result["sound"])
            except Exception as exc:
                logger.info("[HOOKS] sound playback failed for %s.%s: %s", event_type, hook_name, exc)

        # Exit code 2: crash vs intentional block
        if result["exit_code"] == 2:
            is_intentional_block = False
            decision: dict = {}
            try:
                decision = json.loads(result["stdout"]) if result["stdout"].strip() else {}
                is_intentional_block = decision.get("decision") == "block"
            except (json.JSONDecodeError, AttributeError):
                logger.info("[HOOKS] %s.%s exit=2 stdout not JSON, treating as crash", event_type, hook_name)

            if is_intentional_block:
                total_ms = (time.monotonic() - total_start) * 1000
                # INFO, not WARNING: a gate that blocks is the gate WORKING — the branch
                # above is literally is_intentional_block, and the crash case below is the
                # one that signals something wrong. Measured before reclassing: 373 blocks
                # spread over all 10 logged days, every working day, not one stuck session.
                # INFO still lands in the log file, so the record survives; it just stops
                # escalating into @trigger digests. The reason rides along because neither
                # severity is diagnostic without knowing WHAT was blocked.
                #
                # "dispatch", not "gate": total_start is set before the whole hook loop, so
                # this is every PreToolUse hook that ran up to the block, summed — NOT this
                # gate's cost. Measured: pre_edit_gate's own elapsed_ms is median 4ms / p90
                # 123ms, while total here is median 1076ms / p90 4045ms. The old wording
                # read as gate latency and sent a 3305ms sample to the wrong owner.
                block_reason = str(decision.get("reason", "")).strip().splitlines()
                logger.info(
                    "[HOOKS] %s blocked by %s (%dms dispatch): %s",
                    event_type,
                    hook_name,
                    total_ms,
                    block_reason[0][:160] if block_reason else "no reason given",
                )
                _log(
                    {
                        "ts": time.time(),
                        "event": event_type,
                        "action": "blocked",
                        "hook": hook_name,
                        "total_ms": round(total_ms, 1),
                    }
                )
                return result["stdout"], 2

            logger.error(
                "[HOOKS] %s.%s CRASHED exit=2: %s",
                event_type,
                hook_name,
                result["stderr"][:200],
            )
            _log(
                {
                    "ts": time.time(),
                    "event": event_type,
                    "hook": hook_name,
                    "action": "crashed",
                    "stderr": result["stderr"][:200],
                }
            )

        if result["stdout"]:
            outputs.append(result["stdout"])
            if budget_cfg and budget_state is not None:
                hs = budget_state.setdefault(hook_name, {})
                hs["fire_count"] = hs.get("fire_count", 0) + 1
                hs["last_fire_time"] = time.time()
                hs["turns_since_fire"] = 0
                budget_dirty = True

    if budget_dirty and budget_state is not None:
        _save_budget_state(budget_state, payload_session_id)

    total_ms = (time.monotonic() - total_start) * 1000
    _log_detail("[HOOKS] %s complete: %d hooks %dms", event_type, ran, total_ms)
    _log(
        {
            "ts": time.time(),
            "event": event_type,
            "action": "complete",
            "hooks_run": ran,
            "hooks_with_output": len(outputs),
            "total_ms": round(total_ms, 1),
        }
    )

    return "\n".join(outputs), 0


# =============================================================================
# MODULE INTERFACE (drone @hooks routing)
# =============================================================================


def print_introspection():
    """Print module structure — connected handlers."""
    CONSOLE.print("[bold cyan]engine[/bold cyan] Module")
    CONSOLE.print("  Connected Handlers:")
    handlers_root = BRANCH_ROOT / "apps" / "handlers"
    for category_dir in sorted(handlers_root.iterdir()):
        if not category_dir.is_dir() or category_dir.name.startswith("_"):
            continue
        handler_files = [f.name for f in sorted(category_dir.glob("*.py")) if not f.name.startswith("_")]
        if handler_files:
            CONSOLE.print(f"    handlers/{category_dir.name}/ — {', '.join(handler_files)}")


def handle_command(command: str, args: list) -> bool:
    """Route engine commands from drone @hooks."""
    if command in ("engine", ""):
        if not args:
            print_introspection()
            return True

    if command in ("--help", "-h", "help"):
        CONSOLE.print("[bold cyan]engine[/bold cyan] — Hook dispatch engine")
        CONSOLE.print()
        CONSOLE.print("  drone @hooks log       Tail recent hook activity")
        return True

    if command == "log":
        if wants_help(args):
            CONSOLE.print("[bold cyan]engine[/bold cyan] — Hook dispatch engine")
            CONSOLE.print()
            CONSOLE.print("  drone @hooks log       Tail recent hook activity")
            return True

        lines = tail_log(20)
        if not lines:
            CONSOLE.print("No engine log found")
        else:
            for line in lines:
                CONSOLE.print(line)
        return True

    return False
