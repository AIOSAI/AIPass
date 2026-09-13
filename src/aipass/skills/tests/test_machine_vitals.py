# ===================AIPASS====================
# META DATA HEADER
# Name: test_machine_vitals.py - The machine_vitals() contract
# Date: 2026-09-12
# Version: 1.0.0
# Category: skills/tests
# =============================================

"""The machine_vitals() contract on the system_status skill (FPLAN-0561 row 1).

The host API relays this dict verbatim and BAUD's phone draws it, so what is
pinned here is the shape a consumer reads: the section set, the closed reason
codes and their sentences, per-section absence, the whole-function refusal, the
baseline the skill owns, the sensor allowlist, the read-only sysfs range read,
a manufactured macOS, and the no_range branch.

Nothing here asks the live machine for a reading. psutil is a stand-in with
numbers this host does not have, the clock is one the test moves, and the sysfs
tree is built in tmp_path - so the suite is green on a host with no sensor chips
at all, and a case can only pass if the handler asked the stand-in.
"""

import builtins
import io
import os
import sys
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aipass.skills.apps.handlers import switch_handler
from aipass.skills.lib.system_status import handler as status

GIB = 1024**3

_CpuTimes = namedtuple(
    "scputimes",
    ["user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal", "guest", "guest_nice"],
)
_NetIO = namedtuple(
    "snetio",
    ["bytes_sent", "bytes_recv", "packets_sent", "packets_recv", "errin", "errout", "dropin", "dropout"],
)
_Virtual = namedtuple("svmem", ["total", "available", "percent", "used", "free"])
_Swap = namedtuple("sswap", ["total", "used", "free", "percent", "sin", "sout"])
_Temp = namedtuple("shwtemp", ["label", "current", "high", "critical"])
_Fan = namedtuple("sfan", ["label", "current"])

# The contract, written out rather than read back from the handler - a pin that
# mirrors the module's own table can never disagree with it.
BASE_KEYS = ["available", "reason", "sentence", "detail"]
SECTION_KEYS = {
    "cpu": ["percent", "window_s"],
    "load": ["one", "five", "fifteen"],
    "memory": ["total_bytes", "used_bytes", "available_bytes", "percent"],
    "swap": ["total_bytes", "used_bytes", "free_bytes", "percent"],
    "temp": ["chip", "label", "celsius", "high", "critical", "seen"],
    "fan": ["label", "current", "range", "percent_of_range", "fans", "seen"],
    "network": ["sent_bytes_per_s", "recv_bytes_per_s", "window_s"],
    "processes": ["count"],
}
REASON_CODES = {
    "platform",
    "no_sensor",
    "no_allowlisted_sensor",
    "read_failed",
    "warming",
    "no_range",
    "switched_off",
    "psutil_missing",
}

# The MacBook this was built on, as psutil reported it (DPLAN-0341). The rows
# are ordered so that every wrong rule picks something: BAT0 is the first chip,
# TC0F is the hottest row anywhere, Core 0 is hotter than the package, and the
# package row is not first in its own chip.
SENTINEL_ROWS = ("TH0C", "TH0c", "THSP", "TMLB", "TW0P")
MACBOOK_TEMPERATURES = {
    "BAT0": [_Temp("temp", 31.5, None, None)],
    "applesmc": [
        *[_Temp(label, -127.0, None, None) for label in SENTINEL_ROWS],
        _Temp("TH0F", -30.0, None, None),
        _Temp("TH0R", -30.25, None, None),
        _Temp("TC0F", 81.5, None, None),
        _Temp("TC0P", 66.25, None, None),
    ],
    "coretemp": [
        _Temp("Core 0", 74.0, 100.0, 100.0),
        _Temp("Package id 0", 72.0, 100.0, 100.0),
        _Temp("Core 1", 71.0, 100.0, 100.0),
    ],
}
MACBOOK_FANS = {"applesmc": [_Fan("Right Side", 1290)]}

# applesmc's device directory. hwmonN/name does not exist for this chip; its
# name lives one level down, beside the fan files. The two control files are
# laid down too, so a read that reaches for them has something to reach.
APPLESMC_DEVICE = {
    "name": "applesmc\n",
    "fan1_input": "1290\n",
    "fan1_label": "Right Side  \n",
    "fan1_min": "1299\n",
    "fan1_max": "6199\n",
    "fan1_manual": "0\n",
    "fan1_output": "1299\n",
    "fan1_safe": "0\n",
}
# A second fan chip whose fan carries the same label and a different range.
DECOY_DEVICE = {
    "name": "nct6775\n",
    "fan1_input": "800\n",
    "fan1_label": "Right Side\n",
    "fan1_min": "0\n",
    "fan1_max": "2000\n",
}
FAN_CONTROL_FILES = {"fan1_manual", "fan1_output"}

RIGHT_SIDE_AT_ITS_FLOOR = {
    "chip": "applesmc",
    "label": "Right Side",
    "current": 1290,
    "range": {"min": 1299, "max": 6199},
    "percent_of_range": 0.0,
    "reason": None,
    "sentence": None,
    "detail": None,
}


def _expected(section, reason=None, available=None, detail=None, **values):
    """A section as the contract spells it, every value key present."""
    body = {
        "available": (reason is None) if available is None else available,
        "reason": reason,
        "sentence": status.REASONS[reason] if reason else None,
        "detail": detail,
    }
    for key in SECTION_KEYS[section]:
        body[key] = values.get(key)
    return body


class _Clock:
    """A monotonic clock that moves only when the test moves it."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class _Machine:
    """psutil as a Mac has it: every portable call, and no sensors_* at all.

    CPU is busy for the first second on the clock and idle after it, so a window
    over [0, 2] is 50% busy and a window over [1, 2] is 0%. guest time is inside
    user, as on Linux, so a reader that forgets to take it back out of the total
    reads 60, not 50.
    """

    def __init__(self, clock):
        self._clock = clock
        self.net_offset = 0
        self.cpu_percent_calls = 0
        # psutil seeds its shared cpu_percent baseline at import.
        self._percent_last = self.cpu_times()

    def cpu_times(self):
        now = self._clock()
        user = min(now, 1.0)
        return _CpuTimes(
            user=user,
            nice=0.0,
            system=0.0,
            idle=max(now - 1.0, 0.0),
            iowait=0.0,
            irq=0.0,
            softirq=0.0,
            steal=0.0,
            guest=user / 2,
            guest_nice=0.0,
        )

    def cpu_percent(self, interval=None):
        """psutil's shape: the window is since whoever called last on this thread."""
        self.cpu_percent_calls += 1
        last, now = self._percent_last, self.cpu_times()
        self._percent_last = now
        busy = now.user - last.user
        total = busy + (now.idle - last.idle)
        return round(busy / total * 100, 1) if total else 0.0

    def net_io_counters(self):
        now = self._clock()
        return _NetIO(
            bytes_sent=self.net_offset + int(1000 * now),
            bytes_recv=self.net_offset + int(4000 * now),
            packets_sent=0,
            packets_recv=0,
            errin=0,
            errout=0,
            dropin=0,
            dropout=0,
        )

    def getloadavg(self):
        return (0.52, 1.0, 2.37)

    def virtual_memory(self):
        return _Virtual(total=8 * GIB, available=2 * GIB, percent=75.0, used=5 * GIB, free=1 * GIB)

    def swap_memory(self):
        return _Swap(total=4 * GIB, used=1 * GIB, free=3 * GIB, percent=25.0, sin=0, sout=0)

    def pids(self):
        return [1, 42, 4242]


class _LinuxMachine(_Machine):
    """psutil as Linux has it: the portable calls plus both sensor functions."""

    def __init__(self, clock):
        super().__init__(clock)
        self.temperatures = MACBOOK_TEMPERATURES
        self.fans = MACBOOK_FANS

    def sensors_temperatures(self):
        return self.temperatures

    def sensors_fans(self):
        return self.fans


class _UntouchableMachine:
    """A psutil that records every reach. A refused call takes no reading."""

    def __init__(self):
        self.touched = []

    def __getattr__(self, name):
        self.touched.append(name)
        raise AssertionError(f"psutil.{name} was reached through a refusal")


def _build_hwmon(root, applesmc_index=2, overrides=None, omit=(), decoy_index=None):
    """Lay down the MacBook's hwmon tree under root."""
    files = {
        "hwmon0/name": "ADP1\n",
        "hwmon1/name": "BAT0\n",
        "hwmon3/name": "coretemp\n",
    }
    applesmc = {**APPLESMC_DEVICE, **(overrides or {})}
    for name, text in applesmc.items():
        if name not in omit:
            files[f"hwmon{applesmc_index}/device/{name}"] = text
    if decoy_index is not None:
        for name, text in DECOY_DEVICE.items():
            files[f"hwmon{decoy_index}/device/{name}"] = text

    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def fresh_process(monkeypatch):
    """Every case starts as a process that has taken no samples yet."""
    monkeypatch.setattr(status, "_BASELINES", {})


@pytest.fixture()
def clock(monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(status, "_monotonic", fake)
    return fake


@pytest.fixture()
def sysfs(tmp_path, monkeypatch):
    """A Linux host whose hwmon tree is the MacBook's, built in tmp_path."""
    root = _build_hwmon(tmp_path / "hwmon")
    monkeypatch.setattr(status, "HWMON_ROOT", root)
    monkeypatch.setattr(sys, "platform", "linux")
    return root


@pytest.fixture()
def machine(monkeypatch, clock, sysfs):
    stand_in = _LinuxMachine(clock)
    monkeypatch.setattr(status, "psutil", stand_in)
    return stand_in


@pytest.fixture()
def guarded_sysfs(sysfs, monkeypatch):
    """Record every open under the sysfs tree; a fan control file or a write mode raises.

    builtins.open, io.open and os.open are all covered - pathlib reaches files
    through io.open, and on Python 3.10 through os.open as well.
    """
    real_open = builtins.open
    real_os_open = os.open
    root = os.fspath(sysfs)
    opened = []
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

    def _relative(file):
        if isinstance(file, (str, os.PathLike)) and os.fspath(file).startswith(root):
            return Path(os.fspath(file)).relative_to(sysfs).as_posix()
        return None

    def _open(file, mode="r", *args, **kwargs):
        relative = _relative(file)
        if relative is not None:
            opened.append((relative, mode))
            if Path(relative).name in FAN_CONTROL_FILES:
                raise PermissionError(13, "a fan control file was opened", os.fspath(file))
            if set(mode) & set("wax+"):
                raise PermissionError(13, "sysfs was opened for writing", os.fspath(file))
        return real_open(file, mode, *args, **kwargs)

    def _os_open(path, flags, *args, **kwargs):
        relative = _relative(path)
        if relative is not None:
            opened.append((relative, flags))
            if Path(relative).name in FAN_CONTROL_FILES or flags & write_flags:
                raise PermissionError(13, "sysfs was opened for writing", os.fspath(path))
        return real_os_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _open)
    monkeypatch.setattr(io, "open", _open)
    monkeypatch.setattr(os, "open", _os_open)
    return opened


def _manufacture(monkeypatch, clock, tmp_path, platform):
    """A host with no sensor functions at all, naming itself as platform."""
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(status, "HWMON_ROOT", tmp_path / "no_sysfs_here")
    stand_in = _Machine(clock)
    monkeypatch.setattr(status, "psutil", stand_in)
    return stand_in


class TestTheContract:
    """Pin 1: the section set and the closed reason-code set, a sentence per code."""

    def test_the_section_set_is_the_eight_the_route_relays(self):
        assert status.SECTIONS == ("cpu", "load", "memory", "swap", "temp", "fan", "network", "processes")

    def test_a_whole_answer_carries_every_section_with_its_full_key_set(self, machine):
        result = status.machine_vitals()
        assert set(result) == {"ok", "schema", "sampled_at", *SECTION_KEYS}
        assert result["ok"] is True
        assert result["schema"] == 1
        for name, keys in SECTION_KEYS.items():
            assert list(result[name]) == BASE_KEYS + keys
            assert isinstance(result[name]["available"], bool)

    def test_the_reason_codes_are_a_closed_set_with_one_sentence_each(self):
        assert set(status.REASONS) == REASON_CODES
        for code, sentence in status.REASONS.items():
            assert isinstance(sentence, str), code
            assert sentence.endswith("."), code
            assert ". " not in sentence, code
            assert len(sentence) > 40, code

    def test_every_reason_a_section_names_is_in_the_set_and_carries_its_sentence(self, machine):
        machine.temperatures = {"k10temp": [_Temp("Tctl", 55.0, None, None)]}
        machine.fans = {}
        result = status.machine_vitals()
        named = {}
        for name in status.SECTIONS:
            reason = result[name]["reason"]
            if reason is not None:
                named[name] = reason
                assert reason in REASON_CODES
                assert result[name]["sentence"] == status.REASONS[reason]
            else:
                assert result[name]["sentence"] is None
        assert named == {
            "cpu": "warming",
            "network": "warming",
            "temp": "no_allowlisted_sensor",
            "fan": "no_sensor",
        }

    def test_sampled_at_is_an_aware_utc_timestamp_taken_now(self, machine):
        sampled = datetime.fromisoformat(status.machine_vitals()["sampled_at"])
        assert sampled.utcoffset() == timedelta(0)
        assert abs(datetime.now(timezone.utc) - sampled) < timedelta(seconds=60)


class TestAbsenceIsPerSection:
    """Pin 2: one section can be absent while its siblings carry values."""

    @pytest.mark.parametrize(
        ("call", "section"),
        [
            ("sensors_temperatures", "temp"),
            ("sensors_fans", "fan"),
            ("virtual_memory", "memory"),
            ("pids", "processes"),
        ],
    )
    def test_one_failed_reading_costs_only_its_own_section(self, machine, monkeypatch, call, section):
        def _raise(*args, **kwargs):
            raise OSError(f"{call} went away")

        monkeypatch.setattr(machine, call, _raise)
        result = status.machine_vitals()

        assert result["ok"] is True
        assert result[section] == _expected(section, "read_failed", detail=f"OSError: {call} went away")
        assert [name for name in status.SECTIONS if result[name]["reason"] == "read_failed"] == [section]
        assert result["swap"] == _expected(
            "swap", total_bytes=4 * GIB, used_bytes=1 * GIB, free_bytes=3 * GIB, percent=25.0
        )

    def test_the_siblings_of_an_absent_section_carry_the_stand_ins_numbers(self, machine):
        machine.temperatures = {}
        result = status.machine_vitals()
        assert result["temp"] == _expected("temp", "no_sensor", seen=[])
        assert result["memory"] == _expected(
            "memory", total_bytes=8 * GIB, used_bytes=6 * GIB, available_bytes=2 * GIB, percent=75.0
        )
        assert result["load"] == _expected("load", one=0.52, five=1.0, fifteen=2.37)
        assert result["processes"] == _expected("processes", count=3)


class TestTheWholeFunctionRefusal:
    """Pin 3: {ok, reason, detail} for psutil_missing and switched_off, failing closed."""

    def test_no_psutil_refuses_with_the_install_recipe(self, monkeypatch):
        monkeypatch.setattr(status, "psutil", None)
        result = status.machine_vitals()
        assert result == {"ok": False, "reason": "psutil_missing", "detail": status.PSUTIL_RECIPE}
        assert "pip install 'psutil>=5.9'" in result["detail"]

    def test_a_switched_off_skill_refuses_and_takes_no_reading(self, monkeypatch):
        untouchable = _UntouchableMachine()
        monkeypatch.setattr(status, "psutil", untouchable)
        assert switch_handler.set_enabled("system_status", False) is True

        result = status.machine_vitals()

        assert list(result) == ["ok", "reason", "detail"]
        assert result["ok"] is False
        assert result["reason"] == "switched_off"
        assert "drone @skills on system_status" in result["detail"]
        assert untouchable.touched == []

    def test_switching_it_back_on_is_what_lifts_the_refusal(self, machine):
        assert switch_handler.set_enabled("system_status", False) is True
        assert status.machine_vitals()["reason"] == "switched_off"
        assert switch_handler.set_enabled("system_status", True) is True
        assert status.machine_vitals()["ok"] is True

    @pytest.mark.parametrize(
        ("document", "complaint"),
        [
            ("{not json", "not valid JSON"),
            ('{"skills": []}', "no 'skills' map"),
        ],
    )
    def test_an_unreadable_switch_state_fails_closed(self, monkeypatch, document, complaint):
        untouchable = _UntouchableMachine()
        monkeypatch.setattr(status, "psutil", untouchable)
        state_path = switch_handler.get_state_path()
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(document, encoding="utf-8")

        result = status.machine_vitals()

        assert list(result) == ["ok", "reason", "detail"]
        assert result["ok"] is False
        assert result["reason"] == "switched_off"
        assert complaint in result["detail"]
        assert switch_handler.STATE_FILENAME in result["detail"]
        assert untouchable.touched == []
        assert state_path.read_text(encoding="utf-8") == document


class TestTheSkillOwnsItsBaseline:
    """Pin 4: first call warming, then a number and its window, immune to cpu_percent callers."""

    def test_the_first_call_in_a_process_is_warming(self, machine):
        result = status.machine_vitals()
        assert result["cpu"] == _expected("cpu", "warming")
        assert result["network"] == _expected("network", "warming")

    def test_the_second_call_carries_the_number_and_its_window(self, machine, clock):
        status.machine_vitals()
        clock.now = 2.0
        result = status.machine_vitals()
        assert result["cpu"] == _expected("cpu", percent=50.0, window_s=2.0)
        assert result["network"] == _expected("network", sent_bytes_per_s=1000.0, recv_bytes_per_s=4000.0, window_s=2.0)

    def test_a_cpu_percent_caller_between_the_reads_does_not_move_the_number(self, machine, clock):
        status.machine_vitals()
        clock.now = 1.0
        machine.cpu_percent(interval=None)
        clock.now = 2.0

        result = status.machine_vitals()

        assert result["cpu"]["percent"] == 50.0
        assert result["cpu"]["window_s"] == 2.0
        assert machine.cpu_percent_calls == 1
        # Control: the shared window the stand-in keeps really was moved - read
        # through it, the same instant answers 0.0, not 50.0.
        assert machine.cpu_percent(interval=None) == 0.0

    def test_a_network_counter_that_went_backwards_restarts_the_window(self, machine, clock):
        machine.net_offset = 10**9
        status.machine_vitals()
        clock.now = 2.0
        machine.net_offset = 0

        reset = status.machine_vitals()
        clock.now = 4.0
        after = status.machine_vitals()

        assert reset["network"] == _expected("network", "warming")
        assert reset["cpu"]["percent"] == 50.0
        assert after["network"] == _expected("network", sent_bytes_per_s=1000.0, recv_bytes_per_s=4000.0, window_s=2.0)


class TestTheSensorAllowlist:
    """Pin 5: chip AND label, never position, never a threshold."""

    def test_the_macbook_answers_exactly_the_coretemp_package_row(self, machine):
        assert status.machine_vitals()["temp"] == _expected(
            "temp", chip="coretemp", label="Package id 0", celsius=72.0, high=100.0, critical=100.0
        )

    def test_with_no_package_row_the_hottest_core_stands_in(self, machine):
        machine.temperatures = {
            "applesmc": [_Temp("TC0F", 81.5, None, None)],
            "coretemp": [_Temp("Core 0", 71.0, 100.0, 100.0), _Temp("Core 1", 74.0, 100.0, 105.0)],
        }
        assert status.machine_vitals()["temp"] == _expected(
            "temp", chip="coretemp", label="Core 1", celsius=74.0, high=100.0, critical=105.0
        )

    def test_an_unlisted_chip_is_named_in_seen_not_drawn(self, machine):
        machine.temperatures = {
            "k10temp": [_Temp("Tctl", 55.0, None, None)],
            "BAT0": [_Temp("temp", 31.5, None, None)],
        }
        assert status.machine_vitals()["temp"] == _expected("temp", "no_allowlisted_sensor", seen=["BAT0", "k10temp"])

    def test_a_host_with_no_chips_is_no_sensor(self, machine):
        machine.temperatures = {}
        assert status.machine_vitals()["temp"] == _expected("temp", "no_sensor", seen=[])

    def test_an_unlisted_fan_chip_is_named_in_seen_not_drawn(self, machine):
        machine.fans = {"nct6775": [_Fan("fan2", 900)]}
        assert status.machine_vitals()["fan"] == _expected("fan", "no_allowlisted_sensor", seen=["nct6775"])

    def test_a_host_with_no_fans_is_no_sensor(self, machine):
        machine.fans = {}
        assert status.machine_vitals()["fan"] == _expected("fan", "no_sensor", seen=[])


class TestTheFanRangeReadIsReadOnly:
    """Pin 6: name, label, min and max - opened to read - and nothing else."""

    def test_the_guard_refuses_the_control_files_and_every_write(self, guarded_sysfs, sysfs):
        """Control: the stand-in open is armed, and can still say yes."""
        device = sysfs / "hwmon2" / "device"
        for name in sorted(FAN_CONTROL_FILES):
            with pytest.raises(PermissionError):
                open(device / name, encoding="utf-8")
        with pytest.raises(PermissionError):
            open(device / "fan1_min", "w", encoding="utf-8")
        with pytest.raises(PermissionError):
            os.open(device / "fan1_min", os.O_WRONLY)
        with open(device / "fan1_min", encoding="utf-8") as handle:
            assert handle.read() == "1299\n"

    def test_the_range_read_opens_name_label_min_and_max_and_only_to_read(self, machine, guarded_sysfs):
        result = status.machine_vitals()

        assert result["fan"] == _expected(
            "fan",
            label="Right Side",
            current=1290,
            range={"min": 1299, "max": 6199},
            percent_of_range=0.0,
            fans=[RIGHT_SIDE_AT_ITS_FLOOR],
        )
        assert guarded_sysfs == [
            ("hwmon2/device/name", "r"),
            ("hwmon2/device/fan1_label", "r"),
            ("hwmon2/device/fan1_min", "r"),
            ("hwmon2/device/fan1_max", "r"),
        ]

    @pytest.mark.parametrize(("applesmc_index", "decoy_index"), [(2, 5), (7, 5)])
    def test_the_chip_is_found_by_its_name_file_not_its_hwmon_index(
        self, machine, tmp_path, monkeypatch, applesmc_index, decoy_index
    ):
        root = _build_hwmon(tmp_path / "reordered", applesmc_index=applesmc_index, decoy_index=decoy_index)
        monkeypatch.setattr(status, "HWMON_ROOT", root)
        assert status.machine_vitals()["fan"]["fans"] == [RIGHT_SIDE_AT_ITS_FLOOR]

    def test_off_linux_the_range_is_never_read(self, machine, guarded_sysfs, monkeypatch):
        monkeypatch.setattr(sys, "platform", "freebsd14")
        fan = status.machine_vitals()["fan"]
        assert fan["reason"] == "no_range"
        assert fan["current"] == 1290
        assert fan["range"] is None
        assert "not Linux" in fan["detail"]
        assert guarded_sysfs == []


class TestManufacturedMacOSAndWindows:
    """Pin 7: a missing sensor function reads as platform, never AttributeError."""

    @pytest.mark.parametrize("platform", ["darwin", "win32"])
    def test_the_world_has_no_sensor_functions(self, monkeypatch, clock, tmp_path, platform):
        """Control: the stand-in really lacks them, the way psutil does there."""
        stand_in = _manufacture(monkeypatch, clock, tmp_path, platform)
        assert hasattr(stand_in, "sensors_temperatures") is False
        assert hasattr(stand_in, "sensors_fans") is False

    @pytest.mark.parametrize("platform", ["darwin", "win32"])
    def test_temp_and_fan_answer_platform_while_the_rest_answer(self, monkeypatch, clock, tmp_path, platform):
        _manufacture(monkeypatch, clock, tmp_path, platform)
        result = status.machine_vitals()
        assert result["ok"] is True
        assert result["temp"] == _expected("temp", "platform")
        assert result["fan"] == _expected("fan", "platform")
        assert result["memory"]["total_bytes"] == 8 * GIB
        assert result["processes"]["count"] == 3

    def test_windows_load_is_named_as_platform_not_drawn_as_its_emulated_zero(self, monkeypatch, clock, tmp_path):
        stand_in = _manufacture(monkeypatch, clock, tmp_path, "win32")
        monkeypatch.setattr(stand_in, "getloadavg", lambda: (0.0, 0.0, 0.0))
        assert status.machine_vitals()["load"] == _expected("load", "platform")

    def test_macos_load_is_read(self, monkeypatch, clock, tmp_path):
        """Control: the same stand-in answers load when the host is not Windows."""
        _manufacture(monkeypatch, clock, tmp_path, "darwin")
        assert status.machine_vitals()["load"] == _expected("load", one=0.52, five=1.0, fifteen=2.37)


class TestNoRange:
    """Pin 8: the rpm is still published when the range is missing or not a range."""

    @pytest.mark.parametrize("missing", ["fan1_min", "fan1_max"])
    def test_a_missing_bound_is_no_range(self, machine, tmp_path, monkeypatch, missing):
        root = _build_hwmon(tmp_path / "partial", omit=(missing,))
        monkeypatch.setattr(status, "HWMON_ROOT", root)
        fan = status.machine_vitals()["fan"]
        assert fan["available"] is True
        assert fan["reason"] == "no_range"
        assert fan["sentence"] == status.REASONS["no_range"]
        assert fan["current"] == 1290
        assert fan["range"] is None
        assert fan["percent_of_range"] is None
        assert missing in fan["detail"]

    @pytest.mark.parametrize(("low", "high"), [("6199\n", "1299\n"), ("1299\n", "1299\n")])
    def test_a_min_not_below_max_is_no_range(self, machine, tmp_path, monkeypatch, low, high):
        root = _build_hwmon(tmp_path / "inverted", overrides={"fan1_min": low, "fan1_max": high})
        monkeypatch.setattr(status, "HWMON_ROOT", root)
        fan = status.machine_vitals()["fan"]
        assert fan["available"] is True
        assert fan["reason"] == "no_range"
        assert fan["current"] == 1290
        assert fan["range"] is None
        assert fan["percent_of_range"] is None
        assert "is not below" in fan["detail"]

    @pytest.mark.parametrize(
        ("rpm", "percent"),
        [(1290, 0.0), (1299, 0.0), (3749, 50.0), (6199, 100.0), (7000, 100.0)],
    )
    def test_percent_of_range_is_measured_against_the_range_and_clamped(self, machine, rpm, percent):
        machine.fans = {"applesmc": [_Fan("Right Side", rpm)]}
        fan = status.machine_vitals()["fan"]
        assert fan["reason"] is None
        assert fan["current"] == rpm
        assert fan["range"] == {"min": 1299, "max": 6199}
        assert fan["percent_of_range"] == percent
