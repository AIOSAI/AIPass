# =================== AIPass ====================
# Name: handler.py
# Description: System Status skill handler - disk, memory, uptime, processes, machine_vitals()
# Version: 2.1.0
# Created: 2026-03-07
# Modified: 2026-09-12
# =============================================

"""
System Status skill handler.

Provides system health information: disk usage, memory, uptime, processes -
as text actions for the runner, and as one published dict, machine_vitals(),
for in-process callers (the host API's /v1/machine route, FPLAN-0561).

Disk comes from `shutil.disk_usage`, which is portable on its own. The other
three used to read /proc directly, which made them Linux-only: on the macOS
runner every one of them answered success=False and `summary` reported
success=True over the wreckage (FPLAN-0554). They now ask psutil - a declared
dependency of this project (psutil>=5.9) - which answers the same three
questions on Linux, macOS and Windows. When psutil cannot be imported the
actions refuse by name and give the install recipe; they never answer a
partial.

Called by: drone @skills run system_status <action>
Published: machine_vitals() - from aipass.skills.lib.system_status import handler
"""

import shutil
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic as _monotonic

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


# ---------------------------------------------------------------------------
# Published: machine_vitals() - the in-process door (FPLAN-0561 row 1)
#
# The host API proxies this dict verbatim on /v1/machine and BAUD's phone
# draws it. The meaning lives here and only here: which sensor is the CPU,
# which rows are nonsense, what an absence is called and what sentence says so.
# ---------------------------------------------------------------------------

SKILL_NAME = "system_status"
VITALS_SCHEMA = 1

# Every section's values, beside the available/reason/sentence/detail every
# section carries. A value the host cannot give is None, never a zero.
_SECTION_VALUES = {
    "cpu": ("percent", "window_s"),
    "load": ("one", "five", "fifteen"),
    "memory": ("total_bytes", "used_bytes", "available_bytes", "percent"),
    "swap": ("total_bytes", "used_bytes", "free_bytes", "percent"),
    "temp": ("chip", "label", "celsius", "high", "critical", "seen"),
    "fan": ("label", "current", "range", "percent_of_range", "fans", "seen"),
    "network": ("sent_bytes_per_s", "recv_bytes_per_s", "window_s"),
    "processes": ("count",),
}

SECTIONS = tuple(_SECTION_VALUES)

# The closed set of reason codes, one sentence each. The route relays the
# sentence and the face prints it, so neither has to guess what an absence is.
REASONS = {
    "platform": "This operating system does not expose this reading at all, so no host running it ever answers.",
    "no_sensor": "This host exposes the reading but reported no sensor or device to take it from.",
    "no_allowlisted_sensor": (
        "This host has sensors, but none of them is on the skill's allowlist yet - seen lists the chips it reported."
    ),
    "read_failed": "The reading was attempted and failed - detail carries the error.",
    "warming": (
        "A rate needs two samples and this process holds only one so far - the next reading carries a number "
        "and its window."
    ),
    "no_range": (
        "The fan speed is real but its range is not known on this host, so there is no scale to draw it against."
    ),
    "switched_off": (
        "The system_status skill is switched off, or its switch state cannot be read, so it takes no readings."
    ),
    "psutil_missing": (
        "psutil is not importable on this host, so no reading can be taken - detail carries the install recipe."
    ),
}

# Allowlists are data, keyed by chip AND label - never by a row's position,
# which moves between hosts, and never by a value threshold: on the MacBook this
# was measured on, applesmc carries five rows reading -127 and a pair that
# drifted from -34.25 to -30.0 inside twenty minutes (DPLAN-0341). BAT0 is a
# battery, not a CPU. Growing a list is a change here, never on a face.
#
# chip -> the headline label, then the label family ("Core " + an integer)
# whose hottest member stands in when the headline row is absent.
TEMP_ALLOWLIST = {
    "coretemp": {"headline": "Package id 0", "family": "Core "},
}

# Chips whose fans are published. Every fan on a listed chip is read.
FAN_ALLOWLIST = ("applesmc",)

# Where Linux publishes hwmon chips. A chip is found by the name file beside its
# fan input, never by the hwmonN index - that numbering is boot order.
HWMON_ROOT = Path("/sys/class/hwmon")

# Held samples, one per rate. Owned here rather than borrowed from
# psutil.cpu_percent(interval=None), whose baseline is a psutil module global
# keyed by thread id: any other caller in the process silently moves its window
# (37.5 then 21.9 in a fresh process, DPLAN-0341).
_BASELINES = {}
_BASELINE_LOCK = threading.Lock()


def machine_vitals():
    """Read the machine's vitals as one dict. Never raises for a reading.

    Returns:
        dict: {"ok": True, "schema": 1, "sampled_at": ISO-8601 UTC, and one entry
            per SECTIONS}, each section carrying available, reason, sentence and
            detail beside its values. Or a whole-function refusal
            {"ok": False, "reason": "switched_off" | "psutil_missing", "detail": str}.
    """
    # The runner gates on the switch before it imports a handler (DPLAN-0306).
    # This door is imported directly, so it has to ask for itself - otherwise an
    # in-process caller reads a skill an operator switched off. Imported here so
    # the text actions, and every importer that never calls this door, stay
    # stdlib + psutil + prax.
    from aipass.skills.apps.handlers.switch_handler import SwitchStateUnreadable, is_enabled

    try:
        enabled = is_enabled(SKILL_NAME)
    except SwitchStateUnreadable as exc:
        # Cannot tell whether it is off, so it is off - the runner's answer.
        logger.error("Refusing machine_vitals - switch state unreadable: %s", exc)
        return _refusal("switched_off", str(exc))

    if not enabled:
        return _refusal(
            "switched_off",
            f"Skill '{SKILL_NAME}' is switched OFF and takes no readings. "
            f"Turn it back on with: drone @skills on {SKILL_NAME}",
        )

    if psutil is None:
        return _refusal("psutil_missing", PSUTIL_RECIPE)

    readers = {
        "cpu": _read_cpu,
        "load": _read_load,
        "memory": _read_memory,
        "swap": _read_swap,
        "temp": _read_temp,
        "fan": _read_fan,
        "network": _read_network,
        "processes": _read_processes,
    }

    vitals = {
        "ok": True,
        "schema": VITALS_SCHEMA,
        "sampled_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    }
    for name in SECTIONS:
        try:
            vitals[name] = readers[name](psutil)
        except Exception as exc:
            # One failed reading costs its own section, never its siblings.
            logger.warning("machine_vitals: the %s reading failed: %s", name, exc)
            vitals[name] = _section(name, "read_failed", detail=_describe(exc))
    return vitals


def _refusal(reason, detail):
    """The whole-function refusal: machine-readable, never partial."""
    return {"ok": False, "reason": reason, "detail": detail}


def _section(name, reason=None, detail=None, available=None, **values):
    """Build one section with its full, stable key set.

    Args:
        name: Section name, a key of _SECTION_VALUES.
        reason: Reason code from REASONS, or None for a clean reading.
        detail: Error text or explanation beside the code, if any.
        available: Override for a section that answers WITH a reason (a fan
            whose speed is real but whose range is not). Defaults to reason is None.
        **values: The section's values; anything not given is None.

    Returns:
        dict: available, reason, sentence, detail, then every value key.
    """
    unknown = set(values) - set(_SECTION_VALUES[name])
    if unknown:
        raise KeyError(f"section {name!r} has no value named {sorted(unknown)}")

    section = {
        "available": (reason is None) if available is None else available,
        "reason": reason,
        "sentence": REASONS[reason] if reason else None,
        "detail": detail,
    }
    for key in _SECTION_VALUES[name]:
        section[key] = values.get(key)
    return section


def _describe(exc):
    """Name an exception the way detail carries it."""
    return f"{type(exc).__name__}: {exc}"


def _clamp_percent(value):
    """Clamp a computed percentage into 0-100, one decimal."""
    return round(min(max(value, 0.0), 100.0), 1)


def _swap_baseline(key, sample):
    """Hold this sample as the rate's baseline and hand back the one it replaces.

    Args:
        key: Which rate ("cpu" or "network").
        sample: The sample just taken.

    Returns:
        tuple: (previous sample, seconds since it was taken), or (None, 0.0) on
            the first call in this process.
    """
    taken_at = _monotonic()
    with _BASELINE_LOCK:
        previous = _BASELINES.get(key)
        _BASELINES[key] = (taken_at, sample)

    if previous is None:
        return None, 0.0
    return previous[1], taken_at - previous[0]


def _cpu_busy_and_total(times):
    """Split a cpu_times() sample into busy and total seconds.

    Guest time is already counted inside user and nice on Linux, so it comes
    back out of the total; iowait is idle. The same accounting psutil's own
    cpu_percent uses, applied to samples this skill holds.
    """
    total = sum(times) - getattr(times, "guest", 0.0) - getattr(times, "guest_nice", 0.0)
    idle = times.idle + getattr(times, "iowait", 0.0)
    return total - idle, total


def _read_cpu(ps):
    """CPU busy percent over the window since this skill's last sample."""
    sample = ps.cpu_times()
    previous, window_s = _swap_baseline("cpu", sample)
    if previous is None:
        return _section("cpu", "warming")

    busy_now, total_now = _cpu_busy_and_total(sample)
    busy_then, total_then = _cpu_busy_and_total(previous)
    total_delta = total_now - total_then
    if total_delta <= 0 or window_s <= 0:
        # No clock tick between the two samples - there is no window to divide by.
        return _section("cpu", "warming")

    percent = (busy_now - busy_then) / total_delta * 100
    return _section("cpu", percent=_clamp_percent(percent), window_s=round(window_s, 3))


def _read_network(ps):
    """Bytes per second sent and received since this skill's last sample."""
    counters = ps.net_io_counters()
    if counters is None:
        return _section("network", "no_sensor")

    previous, window_s = _swap_baseline("network", counters)
    if previous is None or window_s <= 0:
        return _section("network", "warming")

    sent = counters.bytes_sent - previous.bytes_sent
    recv = counters.bytes_recv - previous.bytes_recv
    if sent < 0 or recv < 0:
        # A counter that went backwards was reset (an interface came and went).
        # The held sample measures nothing now, and this one has replaced it.
        return _section("network", "warming")

    return _section(
        "network",
        sent_bytes_per_s=round(sent / window_s, 1),
        recv_bytes_per_s=round(recv / window_s, 1),
        window_s=round(window_s, 3),
    )


def _read_load(ps):
    """1, 5 and 15 minute load averages."""
    # On Windows psutil emulates load with a sampler thread that reads 0 until
    # it warms. That 0 is not a measurement, so the platform is named instead.
    if sys.platform == "win32" or not hasattr(ps, "getloadavg"):
        return _section("load", "platform")

    one, five, fifteen = ps.getloadavg()
    return _section("load", one=round(one, 2), five=round(five, 2), fifteen=round(fifteen, 2))


def _read_memory(ps):
    """Memory in bytes; used = total - available, as the memory action reports it."""
    virtual = ps.virtual_memory()
    used = virtual.total - virtual.available
    percent = _clamp_percent(used / virtual.total * 100) if virtual.total > 0 else None
    return _section(
        "memory",
        total_bytes=virtual.total,
        used_bytes=used,
        available_bytes=virtual.available,
        percent=percent,
    )


def _read_swap(ps):
    """Swap in bytes. A host with no swap has total 0 and no percent."""
    swap = ps.swap_memory()
    percent = _clamp_percent(swap.used / swap.total * 100) if swap.total > 0 else None
    return _section("swap", total_bytes=swap.total, used_bytes=swap.used, free_bytes=swap.free, percent=percent)


def _read_processes(ps):
    """How many processes the pid census holds."""
    return _section("processes", count=len(ps.pids()))


def _in_family(label, stem):
    """True for a label that is the stem followed by an integer ("Core 1")."""
    return label.startswith(stem) and label[len(stem) :].isdigit()


def _read_temp(ps):
    """The CPU temperature headline, from allowlisted chip and label only."""
    # Off Linux and FreeBSD psutil does not define the function at all - calling
    # it would raise AttributeError, not return an empty dict.
    if not hasattr(ps, "sensors_temperatures"):
        return _section("temp", "platform")

    chips = ps.sensors_temperatures()
    if not chips:
        return _section("temp", "no_sensor", seen=[])

    for chip, rule in TEMP_ALLOWLIST.items():
        rows = chips.get(chip) or []
        headline = next((row for row in rows if row.label == rule["headline"]), None)
        if headline is None:
            family = [row for row in rows if _in_family(row.label, rule["family"])]
            headline = max(family, key=lambda row: row.current, default=None)
        if headline is not None:
            return _section(
                "temp",
                chip=chip,
                label=headline.label,
                celsius=headline.current,
                high=headline.high,
                critical=headline.critical,
            )

    return _section("temp", "no_allowlisted_sensor", seen=sorted(chips))


def _read_fan(ps):
    """Allowlisted fans: psutil's current, each against its sysfs range."""
    # psutil defines sensors_fans on Linux only.
    if not hasattr(ps, "sensors_fans"):
        return _section("fan", "platform")

    chips = ps.sensors_fans()
    if not chips:
        return _section("fan", "no_sensor", seen=[])

    fans = [_fan_entry(chip, fan) for chip in FAN_ALLOWLIST for fan in chips.get(chip) or []]
    if not fans:
        listed_but_empty = any(chip in chips for chip in FAN_ALLOWLIST)
        return _section("fan", "no_sensor" if listed_but_empty else "no_allowlisted_sensor", seen=sorted(chips))

    # The headline is the fan working hardest against its own range. A fan with
    # no range can only be ranked by rpm, and never above one that has a scale.
    headline = max(
        fans,
        key=lambda fan: (fan["percent_of_range"] is not None, fan["percent_of_range"] or 0.0, fan["current"]),
    )
    return _section(
        "fan",
        headline["reason"],
        detail=headline["detail"],
        available=True,
        label=headline["label"],
        current=headline["current"],
        range=headline["range"],
        percent_of_range=headline["percent_of_range"],
        fans=fans,
    )


def _fan_entry(chip, fan):
    """One fan: its current rpm, its range when there is one, and the percent."""
    fan_range, detail = _fan_range(chip, fan.label)
    entry = {
        "chip": chip,
        "label": fan.label,
        "current": fan.current,
        "range": fan_range,
        "percent_of_range": None,
        "reason": None,
        "sentence": None,
        "detail": detail,
    }
    if fan_range is None:
        # The rpm is still real. Carrying the range separately is what keeps a
        # fan at its floor (0%) distinguishable from a fan with no scale at all.
        entry["reason"] = "no_range"
        entry["sentence"] = REASONS["no_range"]
    else:
        span = fan_range["max"] - fan_range["min"]
        entry["percent_of_range"] = _clamp_percent((fan.current - fan_range["min"]) / span * 100)
    return entry


def _fan_range(chip, label):
    """Read one fan's min and max from Linux sysfs - read-only, and only those two.

    fanN_manual and fanN_output sit in the same directory and are root-writable
    on the host this was built on. Nothing here opens them, and nothing here
    opens any file for writing (pinned in tests/test_machine_vitals.py).

    Args:
        chip: Chip name psutil reported the fan under.
        label: The fan's label as psutil reported it.

    Returns:
        tuple: ({"min": int, "max": int}, None), or (None, why) when there is no
            usable range - off Linux, not found, missing, unreadable, or min not
            below max.
    """
    if sys.platform != "linux":
        return None, "The fan range is read from Linux sysfs, and this host is not Linux."

    try:
        folder, stem = _locate_fan(chip, label)
    except LookupError as exc:
        return None, str(exc)
    except (OSError, ValueError) as exc:
        return None, _describe(exc)

    try:
        low = int(_read_sysfs(folder / f"{stem}_min"))
        high = int(_read_sysfs(folder / f"{stem}_max"))
    except (OSError, ValueError) as exc:
        return None, _describe(exc)

    if low >= high:
        return None, f"{stem}_min {low} is not below {stem}_max {high}."
    return {"min": low, "max": high}, None


def _locate_fan(chip, label):
    """Find the sysfs directory and fanN stem for a chip's labelled fan.

    Walks the way psutil's own sensors_fans does - the hwmon directories first,
    their device/ subdirectories only when those hold no fan files at all - so
    the files read here are the ones psutil's current came from. On the MacBook
    this was built on, hwmon2 has no name file and the chip's name lives at
    hwmon2/device/name.

    Raises:
        LookupError: No input, or more than one, carries this chip and label.
    """
    entries = sorted(HWMON_ROOT.glob("hwmon*/fan*_*")) or sorted(HWMON_ROOT.glob("hwmon*/device/fan*_*"))

    names = {}
    matches = []
    for fan_input in entries:
        if not fan_input.name.endswith("_input"):
            continue
        folder = fan_input.parent
        if folder not in names:
            names[folder] = _read_sysfs_or(folder / "name", None)
        if names[folder] != chip:
            continue
        stem = fan_input.name[: -len("_input")]
        if _read_sysfs_or(folder / f"{stem}_label", "") != label:
            continue
        matches.append((folder, stem))

    if len(matches) != 1:
        raise LookupError(
            f"{len(matches)} sysfs fan inputs on chip {chip!r} carry the label {label!r}, "
            f"so no range can be attributed to that fan."
        )
    return matches[0]


def _read_sysfs(path):
    """Read one sysfs attribute as stripped text. Always opens read-only.

    Raises:
        OSError: The attribute is missing or unreadable.
    """
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read().strip()


def _read_sysfs_or(path, fallback):
    """Read one sysfs attribute, or answer fallback when the file does not exist."""
    try:
        return _read_sysfs(path)
    except FileNotFoundError:
        return fallback
