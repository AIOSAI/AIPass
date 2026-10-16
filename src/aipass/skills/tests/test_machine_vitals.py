# =================== AIPass ====================
# Name: test_machine_vitals.py
# Description: The machine_vitals() contract
# Version: 1.4.0
# Created: 2026-09-12
# Modified: 2026-10-16
# Category: skills/tests
# =============================================

"""Tests for lib/system_status/handler.py's machine_vitals() contract (FPLAN-0561 row 1)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the skill's handler module parses and imports

import os
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psutil
import pytest

from aipass.skills.apps.handlers import switch_handler
from aipass.skills.lib.system_status import handler as status

GIB = 1024**3

_CpuTimes = namedtuple(
    "scputimes",
    ["user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal", "guest", "guest_nice"],
)
# Windows' cpu_times fields: no guest, no iowait.
_WinCpuTimes = namedtuple("scputimes", ["user", "system", "idle", "interrupt", "dpc"])
_Freq = namedtuple("scpufreq", ["current", "min", "max"])
_NetIO = namedtuple(
    "snetio",
    ["bytes_sent", "bytes_recv", "packets_sent", "packets_recv", "errin", "errout", "dropin", "dropout"],
)
_Virtual = namedtuple("svmem", ["total", "available", "percent", "used", "free"])
_Swap = namedtuple("sswap", ["total", "used", "free", "percent", "sin", "sout"])
_Temp = namedtuple("shwtemp", ["label", "current", "high", "critical"])
_Fan = namedtuple("sfan", ["label", "current"])
_Battery = namedtuple("sbattery", ["percent", "secsleft", "power_plugged"])

# psutil's two time sentinels, by their real values.
POWER_TIME_UNKNOWN = -1
POWER_TIME_UNLIMITED = -2

# The host API relays this dict verbatim and BAUD's phone draws it, so what is
# pinned here is the shape a consumer reads.
# The contract, written out rather than read back from the handler - a pin that
# mirrors the module's own table can never disagree with it.
BASE_KEYS = ["available", "reason", "sentence", "detail"]
SECTION_KEYS = {
    "cpu": ["percent", "window_s", "cores", "logical", "physical", "mhz", "mhz_max"],
    "load": ["one", "five", "fifteen"],
    "memory": ["total_bytes", "used_bytes", "available_bytes", "percent"],
    "swap": ["total_bytes", "used_bytes", "free_bytes", "percent"],
    "temp": ["chip", "label", "celsius", "high", "critical", "seen"],
    "fan": ["label", "current", "range", "percent_of_range", "fans", "seen"],
    "network": ["sent_bytes_per_s", "recv_bytes_per_s", "window_s"],
    "processes": ["count"],
    "battery": ["percent", "plugged", "state", "seconds_left", "low", "critical"],
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
# The owner's laptop on 2026-10-12, as psutil reported it: on mains, full.
LAPTOP_BATTERY = _Battery(percent=100.0, secsleft=POWER_TIME_UNLIMITED, power_plugged=True)
ON_MAINS = "seconds_left is None: psutil answered POWER_TIME_UNLIMITED, the host is on mains."
NO_BATTERY = "psutil.sensors_battery() answered None: this host reports no battery."

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

# The laptop FPLAN-0586 was measured on: 4 threads on 2 cores, 800-3300 MHz.
# Each logical CPU is busy from 0 on the clock until its own second here, idle
# after it.
CORE_BUSY_UNTIL = (1.5, 2.0, 0.0, 0.5)
LAPTOP_FREQ = _Freq(current=1612.53, min=800.0, max=3300.0)
CPU_FACTS = {"logical": 4, "physical": 2, "mhz": 1612.5, "mhz_max": 3300.0}
CORES_OVER_0_TO_2 = [75.0, 100.0, 0.0, 25.0]

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
    """psutil as a Mac has it: every portable call, and of sensors_* only the battery.

    Four logical CPUs, each busy until its CORE_BUSY_UNTIL second and idle after,
    so a window over [0, 2] reads 75, 100, 0 and 25 per core and 50% in total, and
    a window over [1, 2] reads 37.5% in total. guest time is inside user, as on
    Linux, so a reader that forgets to take it back out of the total reads 60,
    not 50. CPU 2 spends half its idle time in iowait, so a reader that counts
    iowait as busy reads that core at 50, not 0.
    """

    POWER_TIME_UNKNOWN = POWER_TIME_UNKNOWN
    POWER_TIME_UNLIMITED = POWER_TIME_UNLIMITED

    def __init__(self, clock):
        self._clock = clock
        self.busy_until = list(CORE_BUSY_UNTIL)
        self.net_offset = 0
        self.cpu_percent_calls = 0
        self.cpu_times_calls = []
        self.logical = 4
        self.physical = 2
        self.freq = LAPTOP_FREQ
        self.battery = LAPTOP_BATTERY
        # psutil seeds its shared cpu_percent baseline at import.
        self._percent_last = self._aggregate()

    def _per_cpu(self):
        now = self._clock()
        cpus = []
        for index, until in enumerate(self.busy_until):
            user = min(now, until)
            idle = max(now - until, 0.0)
            iowait = idle / 2 if index == 2 else 0.0
            cpus.append(
                _CpuTimes(
                    user=user,
                    nice=0.0,
                    system=0.0,
                    idle=idle - iowait,
                    iowait=iowait,
                    irq=0.0,
                    softirq=0.0,
                    steal=0.0,
                    guest=user / 2,
                    guest_nice=0.0,
                )
            )
        return cpus

    def _aggregate(self):
        """The aggregate tuple, as psutil sums it from the per-CPU lines."""
        return _CpuTimes(*(sum(field) for field in zip(*self._per_cpu())))

    def cpu_times(self, percpu=False):
        self.cpu_times_calls.append(percpu)
        return self._per_cpu() if percpu else self._aggregate()

    def cpu_percent(self, interval=None):
        """psutil's shape: the window is since whoever called last on this thread."""
        self.cpu_percent_calls += 1
        last, now = self._percent_last, self._aggregate()
        self._percent_last = now
        busy = now.user - last.user
        total = busy + (now.idle - last.idle) + (now.iowait - last.iowait)
        return round(busy / total * 100, 1) if total else 0.0

    def cpu_count(self, logical=True):
        return self.logical if logical else self.physical

    def cpu_freq(self, percpu=False):
        return self.freq

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

    def sensors_battery(self):
        return self.battery

    def boot_time(self):
        return 0.0


class _OpenBSDMachine(_Machine):
    """psutil as OpenBSD has it: no sensors_battery at all."""

    def __getattribute__(self, name):
        if name == "sensors_battery":
            raise AttributeError(name)
        return super().__getattribute__(name)


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


# Nothing here asks the live machine for a reading. psutil is a stand-in with
# numbers this host does not have, the clock is one the test moves, and the
# sysfs tree is built in tmp_path - so the suite is green on a host with no
# sensor chips at all, and a case can only pass if the handler asked the stand-in.
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
    _no_battery_files(monkeypatch, tmp_path)
    monkeypatch.setattr(status, "_host_platform", lambda: "linux")
    return root


def _no_battery_files(monkeypatch, tmp_path):
    """Point the battery's sysfs root and UPower file at paths that do not exist yet."""
    monkeypatch.setattr(status, "POWER_SUPPLY_ROOT", tmp_path / "power_supply")
    monkeypatch.setattr(status, "UPOWER_CONF", tmp_path / "UPower.conf")


def _lay_battery_status(tmp_path, word, name="BAT0"):
    """Write a kernel status word for one battery under the redirected sysfs root."""
    folder = tmp_path / "power_supply" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "status").write_text(f"{word}\n", encoding="utf-8")


def _lay_upower(tmp_path, text):
    """Write a UPower.conf at the redirected path."""
    (tmp_path / "UPower.conf").write_text(text, encoding="utf-8")


@pytest.fixture()
def machine(monkeypatch, clock, sysfs):
    stand_in = _LinuxMachine(clock)
    monkeypatch.setattr(status, "psutil", stand_in)
    return stand_in


@pytest.fixture()
def guarded_sysfs(sysfs, audit_guard):
    """Record every open under the sysfs tree; a fan control file or a write mode raises.

    The interpreter's "open" audit event covers builtins.open, io.open, os.open
    and pathlib alike (pathlib reaches files through io.open, and on Python
    3.10 through os.open as well), so no route escapes and no name is replaced.
    The event carries the mode for open() and None for os.open(), whose flags
    are recorded instead.
    """
    root = os.fspath(sysfs)
    opened = []
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

    def _guard(event, args):
        if event != "open" or not isinstance(args[0], (str, os.PathLike)):
            return
        path, mode, flags = args
        if not os.fspath(path).startswith(root):
            return
        relative = Path(os.fspath(path)).relative_to(sysfs).as_posix()
        opened.append((relative, mode if mode is not None else flags))
        if Path(relative).name in FAN_CONTROL_FILES:
            raise PermissionError(13, "a fan control file was opened", os.fspath(path))
        if flags & write_flags:
            raise PermissionError(13, "sysfs was opened for writing", os.fspath(path))

    audit_guard(_guard)
    return opened


def _manufacture(monkeypatch, clock, tmp_path, platform):
    """A host with no sensor functions at all, naming itself as platform."""
    monkeypatch.setattr(status, "_host_platform", lambda: platform)
    monkeypatch.setattr(status, "HWMON_ROOT", tmp_path / "no_sysfs_here")
    _no_battery_files(monkeypatch, tmp_path)
    stand_in = _Machine(clock)
    monkeypatch.setattr(status, "psutil", stand_in)
    return stand_in


class TestTheContract:
    """Pin 1: the section set and the closed reason-code set, a sentence per code."""

    def test_the_section_set_is_the_nine_the_route_relays_battery_last(self):
        assert status.SECTIONS == (
            "cpu",
            "load",
            "memory",
            "swap",
            "temp",
            "fan",
            "network",
            "processes",
            "battery",
        )

    def test_a_whole_answer_carries_every_section_with_its_full_key_set(self, machine):
        result = status.machine_vitals()
        assert set(result) == {"ok", "schema", "sampled_at", *SECTION_KEYS}
        assert result["ok"] is True
        # The battery section is a schema change: 1 had eight sections, 2 has nine.
        assert result["schema"] == 2
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
            ("sensors_battery", "battery"),
        ],
    )
    def test_one_failed_reading_costs_only_its_own_section(self, machine, monkeypatch, call, section):
        def _raise(*args, **kwargs):
            raise OSError(f"{call} went away")

        monkeypatch.setattr(machine, call, _raise)
        result = status.machine_vitals()

        assert result["ok"] is True
        assert result[section] == _expected(
            section, "read_failed", detail=f"The {section} reading failed (OSError); the error is in the host log."
        )
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
        assert result["detail"] == (
            f"The switch state {switch_handler.STATE_FILENAME} could not be read (SwitchStateUnreadable), "
            f"so this skill counts as switched OFF; the error is in the host log."
        )
        assert untouchable.touched == []
        assert state_path.read_text(encoding="utf-8") == document

    @pytest.mark.parametrize(
        ("document", "complaint"),
        [
            ("{not json", "not valid JSON"),
            ('{"skills": []}', "no 'skills' map"),
        ],
    )
    def test_the_exception_words_go_to_the_host_log_never_to_the_handset(self, monkeypatch, document, complaint):
        """detail rides verbatim to the handset (CodeQL py/stack-trace-exposure, 2026-10-10):
        the switch handler's own complaint is logged with its traceback, not published."""
        logged = []
        monkeypatch.setattr(status.logger, "error", lambda msg, *a, **k: logged.append((msg, a, k)))
        monkeypatch.setattr(status, "psutil", _UntouchableMachine())
        state_path = switch_handler.get_state_path()
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(document, encoding="utf-8")

        result = status.machine_vitals()

        assert complaint not in result["detail"]
        assert len(logged) == 1
        _msg, args, kwargs = logged[0]
        assert complaint in str(args[0])
        assert kwargs == {"exc_info": True}


class TestTheSkillOwnsItsBaseline:
    """Pin 4: first call warming, then a number and its window, immune to cpu_percent callers."""

    def test_the_first_call_in_a_process_is_warming(self, machine):
        result = status.machine_vitals()
        assert result["cpu"] == _expected("cpu", "warming", **CPU_FACTS)
        assert result["network"] == _expected("network", "warming")

    def test_the_second_call_carries_the_number_and_its_window(self, machine, clock):
        status.machine_vitals()
        clock.now = 2.0
        result = status.machine_vitals()
        assert result["cpu"] == _expected("cpu", percent=50.0, window_s=2.0, cores=CORES_OVER_0_TO_2, **CPU_FACTS)
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
        # through it, the same instant answers 37.5, not 50.0.
        assert machine.cpu_percent(interval=None) == 37.5

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
        monkeypatch.setattr(status, "_host_platform", lambda: "freebsd14")
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


def _two_reads(clock):
    """Warm the baseline at 0 on the clock, then read over the window [0, 2]."""
    status.machine_vitals()
    clock.now = 2.0
    return status.machine_vitals()


class TestTheCores:
    """Pin 9: one percpu sample feeds the cores and the headline; counts and MHz are None, never zero."""

    def test_one_percpu_sample_per_read_feeds_the_cores_and_the_headline(self, machine, clock):
        cpu = _two_reads(clock)["cpu"]
        assert machine.cpu_times_calls == [True, True]
        assert cpu["cores"] == CORES_OVER_0_TO_2
        assert cpu["percent"] == 50.0

    def test_the_headline_is_summed_from_the_core_deltas_not_averaged(self, machine, clock, monkeypatch):
        idle = _CpuTimes(*[0.0] * len(_CpuTimes._fields))
        samples = iter(
            [
                [idle, idle],
                # CPU 0 ticked 4 s, 3 of them busy; CPU 1 ticked 1 s, all idle.
                [idle._replace(user=3.0, idle=1.0), idle._replace(idle=1.0)],
            ]
        )
        monkeypatch.setattr(machine, "cpu_times", lambda percpu=False: next(samples))
        cpu = _two_reads(clock)["cpu"]
        assert cpu["cores"] == [75.0, 0.0]
        # 3 busy of 5 ticked seconds. The mean of the two bars would say 37.5.
        assert cpu["percent"] == 60.0

    def test_a_change_in_the_cpu_count_between_samples_is_warming_not_a_crash(self, machine, clock):
        status.machine_vitals()
        clock.now = 2.0
        # CPU 3 went offline between the two samples.
        machine.busy_until = [3.0, 4.0, 0.0]
        unplugged = status.machine_vitals()
        clock.now = 4.0
        after = status.machine_vitals()

        assert unplugged["ok"] is True
        assert unplugged["cpu"] == _expected("cpu", "warming", **CPU_FACTS)
        assert after["cpu"] == _expected("cpu", percent=50.0, window_s=2.0, cores=[50.0, 100.0, 0.0], **CPU_FACTS)

    def test_a_cpu_with_no_tick_between_the_samples_is_warming(self, machine, clock, monkeypatch):
        idle = _CpuTimes(*[0.0] * len(_CpuTimes._fields))
        samples = iter([[idle, idle], [idle._replace(user=1.0, idle=1.0), idle]])
        monkeypatch.setattr(machine, "cpu_times", lambda percpu=False: next(samples))
        assert _two_reads(clock)["cpu"] == _expected("cpu", "warming", **CPU_FACTS)

    def test_a_zero_second_window_is_warming_even_when_the_counters_moved(self, machine, monkeypatch):
        idle = _CpuTimes(*[0.0] * len(_CpuTimes._fields))
        samples = iter([[idle], [idle._replace(user=1.0, idle=1.0)]])
        monkeypatch.setattr(machine, "cpu_times", lambda percpu=False: next(samples))
        status.machine_vitals()
        # The clock never moved: a window of 0 s is no window, whatever the counters say.
        assert status.machine_vitals()["cpu"] == _expected("cpu", "warming", **CPU_FACTS)

    @pytest.mark.parametrize(
        ("freq", "mhz", "mhz_max"),
        [
            # No cpufreq at all (some VMs): psutil answers None.
            (None, None, None),
            # psutil's /proc/cpuinfo fallback: a current, and 0.0 for a ceiling it does not know.
            (_Freq(2704.96325, 0.0, 0.0), 2705.0, None),
            # An offline policy psutil zeroes.
            (_Freq(0.0, 0.0, 0.0), None, None),
        ],
    )
    def test_a_frequency_the_host_does_not_give_is_none_never_zero(self, machine, clock, freq, mhz, mhz_max):
        machine.freq = freq
        cpu = _two_reads(clock)["cpu"]
        assert cpu == _expected(
            "cpu", percent=50.0, window_s=2.0, cores=CORES_OVER_0_TO_2, logical=4, physical=2, mhz=mhz, mhz_max=mhz_max
        )

    @pytest.mark.parametrize(
        "error",
        [
            NotImplementedError("can't find current frequency file"),
            FileNotFoundError(2, "No such file or directory"),
        ],
    )
    def test_a_frequency_read_that_raises_costs_only_the_frequency(self, machine, clock, monkeypatch, error):
        def _raise(percpu=False):
            raise error

        monkeypatch.setattr(machine, "cpu_freq", _raise)
        cpu = _two_reads(clock)["cpu"]
        assert cpu == _expected(
            "cpu",
            detail=f"cpu_freq read failed ({type(error).__name__}); the error is in the host log.",
            percent=50.0,
            window_s=2.0,
            cores=CORES_OVER_0_TO_2,
            logical=4,
            physical=2,
        )

    def test_a_host_that_cannot_count_cores_or_has_no_cpu_freq_publishes_none(self, machine, monkeypatch):
        machine.physical = None
        monkeypatch.delattr(_Machine, "cpu_freq")
        assert hasattr(machine, "cpu_freq") is False
        assert status.machine_vitals()["cpu"] == _expected("cpu", "warming", logical=4, physical=None)

    def test_windows_cpu_times_carry_no_guest_or_iowait_and_still_read(self, monkeypatch, clock, tmp_path):
        stand_in = _manufacture(monkeypatch, clock, tmp_path, "win32")

        def _windows_times(percpu=False):
            now = clock()
            cpus = [
                _WinCpuTimes(user=min(now, 1.0), system=0.0, idle=max(now - 1.0, 0.0), interrupt=0.0, dpc=0.0),
                _WinCpuTimes(user=0.0, system=now / 8, idle=now * 3 / 4, interrupt=now / 8, dpc=0.0),
            ]
            return cpus if percpu else _WinCpuTimes(*(sum(field) for field in zip(*cpus)))

        monkeypatch.setattr(stand_in, "cpu_times", _windows_times)
        result = _two_reads(clock)
        assert result["cpu"] == _expected("cpu", percent=37.5, window_s=2.0, cores=[50.0, 25.0], **CPU_FACTS)
        assert result["load"] == _expected("load", "platform")


class TestTheBattery:
    """Pin 10: charge, mains, state and time left as psutil gives them; absence named; lines only when published."""

    def test_the_laptop_on_mains_and_full_reads_clean(self, machine):
        assert status.machine_vitals()["battery"] == _expected(
            "battery", detail=ON_MAINS, percent=100.0, plugged=True, state="full"
        )

    def test_discharging_carries_its_seconds(self, machine):
        machine.battery = _Battery(percent=57.25, secsleft=5400, power_plugged=False)
        assert status.machine_vitals()["battery"] == _expected(
            "battery", percent=57.2, plugged=False, state="discharging", seconds_left=5400
        )

    def test_a_host_with_no_battery_is_no_sensor_naming_psutils_answer(self, machine):
        machine.battery = None
        assert status.machine_vitals()["battery"] == _expected("battery", "no_sensor", detail=NO_BATTERY)

    def test_a_psutil_with_no_battery_function_is_platform(self, monkeypatch, clock, tmp_path):
        _manufacture(monkeypatch, clock, tmp_path, "openbsd7")
        monkeypatch.setattr(status, "psutil", _OpenBSDMachine(clock))
        assert status.machine_vitals()["battery"] == _expected("battery", "platform")

    @pytest.mark.parametrize(
        ("secsleft", "plugged", "named"),
        [(POWER_TIME_UNLIMITED, True, "POWER_TIME_UNLIMITED"), (POWER_TIME_UNKNOWN, False, "POWER_TIME_UNKNOWN")],
    )
    def test_both_time_sentinels_publish_none_and_detail_names_which(self, machine, secsleft, plugged, named):
        machine.battery = _Battery(percent=80.0, secsleft=secsleft, power_plugged=plugged)
        battery = status.machine_vitals()["battery"]
        assert battery["seconds_left"] is None
        assert battery["available"] is True
        assert named in battery["detail"]

    def test_a_charge_above_100_is_clamped(self, machine):
        machine.battery = _Battery(percent=104.6, secsleft=POWER_TIME_UNLIMITED, power_plugged=True)
        assert status.machine_vitals()["battery"]["percent"] == 100.0

    @pytest.mark.parametrize(
        ("percent", "secsleft", "plugged", "state"),
        [
            (80.0, 3600, False, "discharging"),
            (100.0, 3600, False, "discharging"),
            (100.0, POWER_TIME_UNLIMITED, True, "full"),
            (99.9, POWER_TIME_UNLIMITED, True, "charging"),
            (80.0, POWER_TIME_UNKNOWN, True, "charging"),
            (80.0, 3600, None, "discharging"),
            (100.0, POWER_TIME_UNLIMITED, None, "full"),
            (80.0, POWER_TIME_UNKNOWN, None, "unknown"),
            (None, POWER_TIME_UNLIMITED, True, "unknown"),
        ],
    )
    def test_with_no_kernel_word_the_state_is_derived(self, machine, percent, secsleft, plugged, state):
        machine.battery = _Battery(percent=percent, secsleft=secsleft, power_plugged=plugged)
        assert status.machine_vitals()["battery"]["state"] == state

    @pytest.mark.parametrize(("word", "state"), [("Charging", "charging"), ("Discharging", "discharging")])
    def test_the_kernels_word_wins_over_the_derivation(self, machine, tmp_path, word, state):
        _lay_battery_status(tmp_path, word)
        battery = status.machine_vitals()["battery"]
        assert battery["state"] == state
        assert battery["detail"] == ON_MAINS

    def test_a_kernel_word_outside_the_three_is_unknown_and_named(self, machine, tmp_path):
        _lay_battery_status(tmp_path, "Not charging")
        battery = status.machine_vitals()["battery"]
        assert battery["state"] == "unknown"
        assert "'Not charging'" in battery["detail"]

    def test_off_linux_the_kernel_word_is_never_read(self, monkeypatch, clock, tmp_path):
        stand_in = _manufacture(monkeypatch, clock, tmp_path, "darwin")
        stand_in.battery = _Battery(percent=80.0, secsleft=POWER_TIME_UNLIMITED, power_plugged=True)
        _lay_battery_status(tmp_path, "Discharging")
        assert status.machine_vitals()["battery"]["state"] == "charging"

    def test_the_published_upower_lines_are_read(self, machine, tmp_path):
        _lay_upower(tmp_path, "[UPower]\n# the owner's lines\nPercentageLow=15\nPercentageCritical=3.5\n")
        battery = status.machine_vitals()["battery"]
        assert (battery["low"], battery["critical"]) == (15.0, 3.5)

    def test_a_upower_file_without_the_keys_publishes_upowers_defaults(self, machine, tmp_path):
        _lay_upower(tmp_path, "[UPower]\nUsePercentageForPolicy=true\n")
        battery = status.machine_vitals()["battery"]
        assert (battery["low"], battery["critical"]) == (20.0, 5.0)

    def test_no_upower_file_publishes_no_lines(self, machine):
        battery = status.machine_vitals()["battery"]
        assert (battery["low"], battery["critical"]) == (None, None)

    def test_a_time_policy_publishes_no_percent_lines(self, machine, tmp_path):
        _lay_upower(tmp_path, "[UPower]\nUsePercentageForPolicy=false\nPercentageLow=15\n")
        battery = status.machine_vitals()["battery"]
        assert (battery["low"], battery["critical"]) == (None, None)
        assert "UsePercentageForPolicy=false" in battery["detail"]

    def test_an_unparsable_line_publishes_none_and_names_the_class(self, machine, tmp_path):
        _lay_upower(tmp_path, "[UPower]\nPercentageLow=twenty\n")
        battery = status.machine_vitals()["battery"]
        assert (battery["low"], battery["critical"]) == (None, None)
        assert "could not be parsed (ValueError)" in battery["detail"]
        assert "twenty" not in battery["detail"]

    def test_off_linux_upower_is_never_read(self, monkeypatch, clock, tmp_path):
        _manufacture(monkeypatch, clock, tmp_path, "darwin")
        _lay_upower(tmp_path, "[UPower]\nPercentageLow=15\n")
        battery = status.machine_vitals()["battery"]
        assert (battery["low"], battery["critical"]) == (None, None)


class TestTheBatteryAction:
    """Pin 11: the text action and the summary carry the battery; no battery is an answer, not a failure."""

    def test_the_action_prints_the_reading(self, machine, tmp_path):
        _lay_upower(tmp_path, "[UPower]\n")
        result = status.run("battery")
        assert result == {
            "success": True,
            "output": (
                "Battery\n  Charge:    100.0%\n  Power:     on mains\n  State:     full\n"
                "  Time left: none, on mains\n  Low line:  20%, critical 5%"
            ),
            "error": None,
        }

    def test_seconds_print_as_hours_and_minutes(self, machine):
        machine.battery = _Battery(percent=57.0, secsleft=5460, power_plugged=False)
        assert "  Time left: 1h 31m" in status.run("battery")["output"]

    @pytest.mark.parametrize(
        ("stand_in", "line"),
        [(None, "Battery: none on this host"), ("openbsd", "Battery: not readable on this platform")],
    )
    def test_a_host_without_a_reading_still_answers(self, machine, clock, monkeypatch, stand_in, line):
        if stand_in is None:
            machine.battery = None
        else:
            monkeypatch.setattr(status, "psutil", _OpenBSDMachine(clock))
        assert status.run("battery") == {"success": True, "output": line, "error": None}

    def test_the_summary_carries_the_battery_last(self, machine):
        result = status.run("summary")
        assert result["success"] is True
        assert result["output"].split("\n---\n")[-1].startswith("Battery\n")
        assert "battery" in status.get_actions()


MIB = 1024**2


class _Proc:
    """One psutil.Process: the first cpu_percent is the cold zero, the second its real load.

    Any attribute it does not define - cmdline, environ, cwd - is recorded and
    refused, so the list can only be built from the name and the five numbers.
    """

    def __init__(self, pid, name, load, mem_pct, rss, user="patrick", state="running", fails=None):
        self.pid = pid
        self._name = name
        self._load = load
        self._mem_pct = mem_pct
        self._rss = rss
        self._user = user
        self._state = state
        self._fails = fails or {}
        self._cpu_reads = 0
        self.touched = []

    def _maybe_fail(self, call):
        if call in self._fails:
            raise self._fails[call](self.pid)

    def cpu_percent(self, interval=None):
        self._cpu_reads += 1
        if self._cpu_reads > 1:
            self._maybe_fail("second_cpu_read")
            return self._load
        return 0.0

    def name(self):
        self._maybe_fail("name")
        return self._name

    def memory_percent(self):
        return self._mem_pct

    def memory_info(self):
        self._maybe_fail("memory_info")
        return _Mem(rss=self._rss, vms=self._rss * 2)

    def username(self):
        if self._user is None:
            raise psutil.AccessDenied(self.pid)
        return self._user

    def status(self):
        return self._state

    def __getattr__(self, name):
        self.__dict__.setdefault("touched", []).append(name)
        raise AssertionError(f"Process.{name} was reached - the list reads the name only")


_Mem = namedtuple("pmem", ["rss", "vms"])


class _BusyMachine(_LinuxMachine):
    """The Linux stand-in with a process table: pids() and Process(pid) read it."""

    NoSuchProcess = psutil.NoSuchProcess
    AccessDenied = psutil.AccessDenied
    ZombieProcess = psutil.ZombieProcess

    def __init__(self, clock, table=(), gone=()):
        super().__init__(clock)
        self.table = {proc.pid: proc for proc in table}
        self.gone = set(gone)
        # psutil spells its constructor Process; bound here so no method breaks snake_case.
        self.Process = self._open

    def pids(self):
        return sorted(set(self.table) | self.gone)

    def _open(self, pid):
        if pid in self.gone:
            raise psutil.NoSuchProcess(pid)
        return self.table[pid]


@pytest.fixture()
def naps(monkeypatch, clock):
    """The sample's sleep, recorded and spent on the test's clock instead of the wall's."""
    taken = []

    def nap(seconds):
        taken.append(seconds)
        clock.now += seconds

    monkeypatch.setattr(status, "_sleep", nap)
    return taken


def _busy(monkeypatch, clock, table=(), gone=()):
    stand_in = _BusyMachine(clock, table, gone)
    monkeypatch.setattr(status, "psutil", stand_in)
    return stand_in


class TestTheProcessList:
    """machine_processes(limit) - contract C-B (DPLAN-0414 theme 3)."""

    def test_the_list_is_top_by_sampled_cpu_normalised_to_the_machine_with_name_only(
        self, monkeypatch, clock, sysfs, naps
    ):
        table = [
            _Proc(1, "systemd", load=0.4, mem_pct=0.24, rss=12 * MIB + 7, user="root", state="sleeping"),
            _Proc(42, "chrome", load=170.0, mem_pct=3.14, rss=512 * MIB),
            _Proc(4242, "fan_spinner", load=170.0, mem_pct=9.0, rss=2048 * MIB, user=None),
        ]
        _busy(monkeypatch, clock, table)

        result = status.machine_processes()

        sampled_at = datetime.fromisoformat(result.pop("sampled_at"))
        assert sampled_at.utcoffset() == timedelta(0)
        assert result == {
            "window_ms": 500,
            "total": 3,
            "sort": "cpu",
            "processes": [
                {
                    "pid": 4242,
                    "name": "fan_spinner",
                    "cpu_pct": 42.5,
                    "mem_pct": 9.0,
                    "mem_mb": 2048,
                    "user": None,
                    "state": "running",
                },
                {
                    "pid": 42,
                    "name": "chrome",
                    "cpu_pct": 42.5,
                    "mem_pct": 3.1,
                    "mem_mb": 512,
                    "user": "patrick",
                    "state": "running",
                },
                {
                    "pid": 1,
                    "name": "systemd",
                    "cpu_pct": 0.1,
                    "mem_pct": 0.2,
                    "mem_mb": 12,
                    "user": "root",
                    "state": "sleeping",
                },
            ],
        }
        assert naps == [0.5]
        assert [proc.touched for proc in table] == [[], [], []]

    @pytest.mark.parametrize(("limit", "listed"), [(-5, 1), (0, 1), (1, 1), (3, 3), (100, 100), (101, 100), (250, 100)])
    def test_limit_clamps_to_one_through_a_hundred(self, monkeypatch, clock, sysfs, naps, limit, listed):
        table = [_Proc(pid, f"worker{pid}", load=float(pid), mem_pct=0.1, rss=MIB) for pid in range(1, 121)]
        _busy(monkeypatch, clock, table)

        result = status.machine_processes(limit)

        assert result["total"] == 120
        assert [proc["pid"] for proc in result["processes"]] == list(range(120, 120 - listed, -1))

    def test_a_process_that_vanishes_mid_sample_is_skipped_not_an_error(self, monkeypatch, clock, sysfs, naps):
        table = [
            _Proc(42, "short_lived", load=300.0, mem_pct=1.0, rss=MIB, fails={"second_cpu_read": psutil.NoSuchProcess}),
            _Proc(9, "zombie", load=200.0, mem_pct=1.0, rss=MIB, fails={"name": psutil.ZombieProcess}),
            _Proc(10, "guarded", load=100.0, mem_pct=1.0, rss=MIB, fails={"memory_info": psutil.AccessDenied}),
            _Proc(11, "steady", load=8.0, mem_pct=1.0, rss=MIB),
        ]
        _busy(monkeypatch, clock, table, gone={7})

        result = status.machine_processes()

        assert result["total"] == 5
        assert [(proc["pid"], proc["name"]) for proc in result["processes"]] == [(11, "steady")]

    def test_a_switched_off_skill_answers_the_vitals_refusal_and_reads_no_process(self, monkeypatch, naps):
        untouchable = _UntouchableMachine()
        monkeypatch.setattr(status, "psutil", untouchable)
        assert switch_handler.set_enabled("system_status", False) is True

        assert status.machine_processes() == status.machine_vitals()
        assert status.machine_processes()["reason"] == "switched_off"
        assert untouchable.touched == []
        assert naps == []
