# ===================AIPASS====================
# META DATA HEADER
# Name: handler.py - System Status skill handler
# Date: 2026-03-07
# Version: 1.0.0
# Category: skills/catalog/system_status
# =============================================

"""
System Status skill handler.

Provides system health information: disk usage, memory, uptime, processes.
All data sourced from stdlib and /proc (Linux).

Called by: drone @skills run system_status <action>
"""

import os
import shutil


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


def _disk_usage():
    """Get disk usage for the root filesystem."""
    usage = shutil.disk_usage("/")
    total = _format_bytes(usage.total)
    used = _format_bytes(usage.used)
    free = _format_bytes(usage.free)
    percent = (usage.used / usage.total) * 100

    output = (
        f"Disk Usage (/)\n"
        f"  Total: {total}\n"
        f"  Used:  {used} ({percent:.1f}%)\n"
        f"  Free:  {free}"
    )
    return {"success": True, "output": output, "error": None}


def _memory_info():
    """Get memory info from /proc/meminfo (Linux)."""
    meminfo_path = "/proc/meminfo"
    if not os.path.exists(meminfo_path):
        return {
            "success": False,
            "output": "",
            "error": "/proc/meminfo not available (non-Linux system?)",
        }

    data = {}
    with open(meminfo_path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.split(":")
            if len(parts) == 2:
                key = parts[0].strip()
                # Value is in kB typically, e.g. "8045264 kB"
                val_str = parts[1].strip()
                # Extract numeric part
                val_parts = val_str.split()
                if val_parts:
                    try:
                        data[key] = int(val_parts[0])
                    except ValueError:
                        data[key] = val_str

    mem_total = data.get("MemTotal", 0)
    mem_free = data.get("MemFree", 0)
    mem_available = data.get("MemAvailable", 0)
    buffers = data.get("Buffers", 0)
    cached = data.get("Cached", 0)
    swap_total = data.get("SwapTotal", 0)
    swap_free = data.get("SwapFree", 0)

    # Values from /proc/meminfo are in kB
    mem_used = mem_total - mem_available
    mem_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
    swap_used = swap_total - swap_free
    swap_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0

    output = (
        f"Memory\n"
        f"  Total:     {_format_bytes(mem_total * 1024)}\n"
        f"  Used:      {_format_bytes(mem_used * 1024)} ({mem_percent:.1f}%)\n"
        f"  Available: {_format_bytes(mem_available * 1024)}\n"
        f"  Buffers:   {_format_bytes(buffers * 1024)}\n"
        f"  Cached:    {_format_bytes(cached * 1024)}\n"
        f"Swap\n"
        f"  Total:     {_format_bytes(swap_total * 1024)}\n"
        f"  Used:      {_format_bytes(swap_used * 1024)} ({swap_percent:.1f}%)\n"
        f"  Free:      {_format_bytes(swap_free * 1024)}"
    )
    return {"success": True, "output": output, "error": None}


def _system_uptime():
    """Get system uptime from /proc/uptime (Linux)."""
    uptime_path = "/proc/uptime"
    if not os.path.exists(uptime_path):
        return {
            "success": False,
            "output": "",
            "error": "/proc/uptime not available (non-Linux system?)",
        }

    with open(uptime_path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    parts = content.split()
    if not parts:
        return {
            "success": False,
            "output": "",
            "error": "Could not parse /proc/uptime",
        }

    uptime_seconds = float(parts[0])
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
    """Count running processes via /proc directory."""
    proc_path = "/proc"
    if not os.path.exists(proc_path):
        return {
            "success": False,
            "output": "",
            "error": "/proc not available (non-Linux system?)",
        }

    count = 0
    try:
        for entry in os.listdir(proc_path):
            # Process directories are numeric PIDs
            if entry.isdigit():
                count += 1
    except OSError as exc:
        return {
            "success": False,
            "output": "",
            "error": f"Failed to read /proc: {exc}",
        }

    output = f"Running processes: {count}"
    return {"success": True, "output": output, "error": None}


def _summary():
    """Combine all status checks into one report."""
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
        output += "\n---\nErrors:\n  " + "\n  ".join(errors)

    return {"success": True, "output": output, "error": None}
