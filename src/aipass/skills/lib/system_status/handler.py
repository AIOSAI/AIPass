# =================== AIPass ====================
# Name: handler.py
# Description: System Status skill handler - disk, memory, uptime, processes
# Version: 2.0.0
# Created: 2026-03-07
# Modified: 2026-09-12
# =============================================

"""
System Status skill handler.

Provides system health information: disk usage, memory, uptime, processes.

Disk comes from `shutil.disk_usage`, which is portable on its own. The other
three used to read /proc directly, which made them Linux-only: on the macOS
runner every one of them answered success=False and `summary` reported
success=True over the wreckage (FPLAN-0554). They now ask psutil - a declared
dependency of this project (psutil>=5.9) - which answers the same three
questions on Linux, macOS and Windows. When psutil cannot be imported the
actions refuse by name and give the install recipe; they never answer a
partial.

Called by: drone @skills run system_status <action>
"""

import shutil
import time

from aipass.prax import logger

# psutil is declared in pyproject (psutil>=5.9), so this import normally
# succeeds. A host that lacks it still gets disk usage; the three actions that
# need it refuse by name rather than answering a partial.
try:
    import psutil
except ImportError:
    psutil = None
    logger.warning("psutil not importable — system_status memory/uptime/processes will refuse")

# What to tell a caller whose host has no psutil. Naming the recipe is the
# point: "not available" sent the reader looking at their kernel.
PSUTIL_RECIPE = "psutil is not importable on this host - install it with: pip install 'psutil>=5.9'"


def run(action, args=None, config=None):
    """Execute a system status action.

    Args:
        action: One of: disk, memory, uptime, processes, summary
        args: Dict of action arguments (unused for this skill)
        config: Dict of resolved config values (unused for this skill)

    Returns:
        {"success": bool, "output": str, "error": str|None}
    """
    args = args or {}
    config = config or {}

    dispatch = {
        "disk": _disk_usage,
        "memory": _memory_info,
        "uptime": _system_uptime,
        "processes": _process_count,
        "summary": _summary,
    }

    handler_fn = dispatch.get(action)
    if handler_fn is None:
        available = ", ".join(dispatch.keys())
        return {
            "success": False,
            "output": "",
            "error": f"Unknown action: {action}. Available: {available}",
        }

    try:
        return handler_fn()
    except Exception as exc:
        logger.error("system_status action '%s' failed: %s", action, exc)
        return {
            "success": False,
            "output": "",
            "error": f"Action '{action}' failed: {exc}",
        }


def get_actions():
    """List available actions for this skill."""
    return ["disk", "memory", "uptime", "processes", "summary"]


# ---------------------------------------------------------------------------
# Action implementations
# ---------------------------------------------------------------------------


def _format_bytes(num_bytes):
    """Format bytes into human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"


def _no_psutil(what):
    """Refuse an action that needs psutil, naming what could not be measured."""
    return {
        "success": False,
        "output": "",
        "error": f"Cannot read {what}: {PSUTIL_RECIPE}",
    }


def _disk_usage():
    """Get disk usage for the root filesystem."""
    usage = shutil.disk_usage("/")
    total = _format_bytes(usage.total)
    used = _format_bytes(usage.used)
    free = _format_bytes(usage.free)
    percent = (usage.used / usage.total) * 100

    output = f"Disk Usage (/)\n  Total: {total}\n  Used:  {used} ({percent:.1f}%)\n  Free:  {free}"
    return {"success": True, "output": output, "error": None}


def _memory_info():
    """Get memory and swap usage from psutil (portable)."""
    if psutil is None:
        return _no_psutil("memory")

    virtual = psutil.virtual_memory()
    swap = psutil.swap_memory()

    # used = total - available, the same definition the /proc reader used, and
    # the one psutil's own `percent` is computed from.
    mem_used = virtual.total - virtual.available
    mem_percent = (mem_used / virtual.total * 100) if virtual.total > 0 else 0
    swap_percent = (swap.used / swap.total * 100) if swap.total > 0 else 0

    lines = [
        "Memory",
        f"  Total:     {_format_bytes(virtual.total)}",
        f"  Used:      {_format_bytes(mem_used)} ({mem_percent:.1f}%)",
        f"  Available: {_format_bytes(virtual.available)}",
    ]

    # buffers/cached exist on Linux and BSD, not on macOS or Windows. Report
    # them where the platform has them rather than printing a zero that reads
    # like a measurement.
    for label, field in (("Buffers", "buffers"), ("Cached", "cached")):
        value = getattr(virtual, field, None)
        if value is not None:
            lines.append(f"  {label + ':':<11}{_format_bytes(value)}")

    lines += [
        "Swap",
        f"  Total:     {_format_bytes(swap.total)}",
        f"  Used:      {_format_bytes(swap.used)} ({swap_percent:.1f}%)",
        f"  Free:      {_format_bytes(swap.free)}",
    ]

    return {"success": True, "output": "\n".join(lines), "error": None}


def _system_uptime():
    """Get system uptime from psutil's boot time (portable)."""
    if psutil is None:
        return _no_psutil("uptime")

    uptime_seconds = time.time() - psutil.boot_time()
    days = int(uptime_seconds // 86400)
    hours = int((uptime_seconds % 86400) // 3600)
    minutes = int((uptime_seconds % 3600) // 60)
    seconds = int(uptime_seconds % 60)

    parts_list = []
    if days > 0:
        parts_list.append(f"{days}d")
    if hours > 0:
        parts_list.append(f"{hours}h")
    if minutes > 0:
        parts_list.append(f"{minutes}m")
    parts_list.append(f"{seconds}s")

    formatted = " ".join(parts_list)

    output = f"Uptime: {formatted} ({uptime_seconds:.0f} seconds total)"
    return {"success": True, "output": output, "error": None}


def _process_count():
    """Count running processes via psutil's pid census (portable)."""
    if psutil is None:
        return _no_psutil("the process table")

    count = len(psutil.pids())

    output = f"Running processes: {count}"
    return {"success": True, "output": output, "error": None}


def _summary():
    """Combine all status checks into one report.

    A section that fails makes the whole summary a failure. The old version
    returned success=True with the failures printed in an Errors trailer, so on
    a host where three of the four sections were unreadable a caller that
    checks `success` read a good answer over a disk line and nothing else.
    """
    sections = []
    errors = []

    for action_name, action_fn in [
        ("disk", _disk_usage),
        ("memory", _memory_info),
        ("uptime", _system_uptime),
        ("processes", _process_count),
    ]:
        try:
            result = action_fn()
            if result["success"]:
                sections.append(result["output"])
            else:
                errors.append(f"{action_name}: {result['error']}")
        except Exception as exc:
            errors.append(f"{action_name}: {exc}")

    output = "\n---\n".join(sections)

    if errors:
        # The sections that did answer are still handed back - they are real -
        # but success says the report is incomplete, and error names which
        # sections are missing.
        return {
            "success": False,
            "output": output,
            "error": "Incomplete summary - " + "; ".join(errors),
        }

    return {"success": True, "output": output, "error": None}
