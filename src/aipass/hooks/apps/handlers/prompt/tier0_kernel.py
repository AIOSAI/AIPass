# =================== AIPass ====================
# Name: tier0_kernel.py
# Version: 1.3.0
# Description: Tier 0 kernel — always-on minimal prompt injection (UserPromptSubmit)
# Branch: hooks
# Layer: apps/handlers/prompt
# Created: 2026-06-18
# Modified: 2026-10-17
# =============================================

"""Loads .aipass/tier0_kernel.md — tiny always-on identity + reflex block."""

from aipass.prax.apps.modules.logger import system_logger as logger


def _kernel_and_banner(hook_data: dict, cadence_down: str | None = None) -> tuple[str, str]:
    """The kernel, and the degraded banner when grounding this seat was promised did not load.

    Turn 0 logs WARNING, later beats info: one lasting hole is one warning per context.
    With cadence down the kernel fires alone every turn and the banner names the withheld loaders.
    """
    import importlib

    grounding_content = importlib.import_module("aipass.hooks.apps.modules.grounding_content")
    sections, failures = grounding_content.grounding_report(hook_data)
    loaded = dict(sections)
    carried = list(loaded)
    if cadence_down:
        carried = [label for label in carried if label == "kernel"]
        failures.append(
            "navmap, branch, identity: WITHHELD — cadence cannot count turns "
            f"({cadence_down}), so the kernel fires alone on every turn until that is cured"
        )
    banner = grounding_content.degraded_banner(failures, carried)
    if failures:
        loud = not cadence_down and _turn_or_none() in (0, None)
        log = logger.warning if loud else logger.info
        log(
            "[HOOKS] tier0_kernel DEGRADED: carried=%s missing=%s", ",".join(carried) or "nothing", " | ".join(failures)
        )
    return loaded.get("kernel", ""), banner


def _turn_or_none() -> int | None:
    """The current turn, or None when cadence cannot say — never a reason to drop the kernel.

    Only the log level depends on it; the kernel must still go out when cadence is broken.
    """
    import importlib

    try:
        return importlib.import_module("aipass.hooks.apps.modules.cadence").current_turn()
    except Exception as exc:  # an unreadable turn only raises the log level
        logger.info("[HOOKS] tier0_kernel: turn unreadable, degraded line logs at WARNING: %s", exc)
        return None


def handle(hook_data: dict) -> dict:
    """Load tier0 kernel — cadence-gated (period from cadence_config.json, default 5)."""
    cadence_down = None
    try:
        import importlib

        cadence = importlib.import_module("aipass.hooks.apps.modules.cadence")
        if not cadence.should_fire("tier0", hook_data):
            return {"stdout": "", "exit_code": 0}
        reason = cadence.degraded_reason()
        cadence_down = reason if isinstance(reason, str) else None
    except Exception as exc:
        logger.warning(
            "[HOOKS] tier0_kernel DEGRADED loader=tier0: cadence check raised, so the kernel fires alone EVERY "
            "turn until this is cured: %s",
            exc,
        )
        cadence_down = f"the cadence module raised {type(exc).__name__}: {exc}"

    try:
        content, banner = _kernel_and_banner(hook_data, cadence_down)
        if not content and not banner:
            return {"stdout": "", "exit_code": 0}
        stdout = "\n\n".join(part for part in (banner, content) if part)
        return {"stdout": stdout, "exit_code": 0, "sound": "tier0 kernel"}

    except Exception as exc:
        logger.info("[HOOKS] tier0_kernel: unexpected error: %s", exc)
        return {"stdout": "", "exit_code": 0}
