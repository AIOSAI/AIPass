# =================== AIPass ====================
# Name: test_watchdog_module.py
# Description: Tests for the watchdog module router
# Version: 1.0.0
# Created: 2026-04-14
# Modified: 2026-04-14
# =============================================

"""Tests for the watchdog module router (Phase 1, FPLAN-0186)."""

import sys
from unittest.mock import patch

import pytest

from aipass.devpulse.apps.modules import watchdog as wd_mod


@pytest.fixture
def real_owner_gate():
    """Opt OUT of the autouse bypass below — for tests whose subject IS the gate.

    Requested as a fixture rather than declared as a marker so no pytest.ini
    registration is needed and the opt-out is visible in the test signature.
    """
    return True


@pytest.fixture(autouse=True)
def _bypass_caller_guard(request):
    """Force _guard_caller to always pass so tests don't depend on cwd.

    Skipped for tests that request ``real_owner_gate``: bypassing the guard
    everywhere is exactly why the gate's own defects (help refused, refusal
    exiting 0) had no test to fail.
    """
    if "real_owner_gate" in request.fixturenames:
        yield
        return
    with patch.object(wd_mod, "_guard_caller", return_value=True):
        yield


def test_handle_command_rejects_unrelated_command():
    """Router returns False for commands that aren't 'watchdog'."""
    assert wd_mod.handle_command("feedback", []) is False


def test_handle_command_no_args_shows_introspection(capsys):
    """No args -> module introspection (mentions 'watchdog')."""
    result = wd_mod.handle_command("watchdog", [])
    assert result is True
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "watchdog" in combined.lower()


def test_handle_command_help_flag(capsys):
    """--help prints HELP_TEXT."""
    result = wd_mod.handle_command("watchdog", ["--help"])
    assert result is True
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "Usage" in combined or "usage" in combined.lower()


def test_handle_command_unknown_subcommand(capsys):
    """Unknown subcommand returns clean error message."""
    result = wd_mod.handle_command("watchdog", ["bogus"])
    assert result is True
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "bogus" in combined.lower() or "unknown" in combined.lower()


# --------------------------------------------------------------------------
# The owner gate — @canary's three findings from a non-owner seat, 2026-08-22
#
# These deliberately do NOT use the autouse bypass: the gate is the subject.
# --------------------------------------------------------------------------


def _deny_owner(monkeypatch):
    """Make the shared owner guard refuse, as it does for a non-owner seat."""
    import aipass.devpulse.apps.handlers.owner.guard as owner_guard

    monkeypatch.setattr(owner_guard, "guard_owner_caller", lambda _name: False)


def test_help_survives_the_owner_gate(capsys, monkeypatch, real_owner_gate):
    """--help must work from a seat that owns nothing.

    The gate used to run first, so a non-owner asking for help got
    'refusing non-owner call' — the module refused to explain itself to exactly
    the person who did not know whose it was. That is how a gate teaches people
    to route around it.
    """
    _deny_owner(monkeypatch)
    assert wd_mod.handle_command("watchdog", ["--help"]) is True
    text = capsys.readouterr()
    combined = text.out + text.err
    assert "usage" in combined.lower()
    assert "owner-only" not in combined.lower()


def test_introspection_survives_the_owner_gate(capsys, monkeypatch, real_owner_gate):
    """Bare 'watchdog' is the same class as help — explain, never execute."""
    _deny_owner(monkeypatch)
    assert wd_mod.handle_command("watchdog", []) is True
    text = capsys.readouterr()
    assert "owner-only" not in (text.out + text.err).lower()


def test_a_privileged_subcommand_is_still_refused(capsys, monkeypatch, real_owner_gate):
    """Letting help through must not let anything else through with it."""
    _deny_owner(monkeypatch)
    assert wd_mod.handle_command("watchdog", ["baseline"]) is True
    text = capsys.readouterr()
    assert "owner-only" in (text.out + text.err).lower()


def test_the_owner_refusal_flips_the_exit_code(monkeypatch, real_owner_gate):
    """A refusal that exits 0 is a lie to every non-human caller.

    This used ``warning``, which does not call ``mark_command_failed``, so
    ``watchdog baseline && <next step>`` ran the next step believing the wire
    was armed. @canary proved it specific, not drone-wide: unknown subcommand
    exits 2, this exited 0. The human-facing text was a legibility problem;
    this one was silent.

    Asserts the FAILURE MARK, not the wording — wording is cosmetic and this
    is the half that talks to scripts.
    """
    from aipass.cli.apps.modules import display as cli_display

    _deny_owner(monkeypatch)
    marks: list[int] = []
    monkeypatch.setattr(cli_display, "mark_command_failed", lambda: marks.append(1))

    assert wd_mod._guard_caller() is False
    assert marks, "the refusal must mark the command failed, or it exits 0"


def test_the_owner_refusal_names_the_owner(capsys, monkeypatch, real_owner_gate):
    """'Owner-only' tells a stranger they are in the wrong place, not where the
    right place is. A refusal with no next step dead-ends."""
    _deny_owner(monkeypatch)
    monkeypatch.setattr(wd_mod, "_owner_address", lambda: "@vera")

    assert wd_mod._guard_caller() is False
    text = capsys.readouterr()
    assert "@vera" in (text.out + text.err)


def test_the_refusal_still_refuses_when_the_owner_cannot_be_named(capsys, monkeypatch, real_owner_gate):
    """Building a nicer message must never be able to break the refusal itself.

    The owner lookup reads a registry, and a registry read can fail. If that
    failure escaped, an unreadable registry would turn a refusal into a
    traceback — and a traceback is not a refusal, it is a crash someone
    retries.
    """
    import aipass.spawn.apps.handlers.registry as spawn_registry

    _deny_owner(monkeypatch)

    def explode(*_args, **_kwargs):
        raise RuntimeError("registry unreadable")

    monkeypatch.setattr(spawn_registry, "get_owner", explode)

    assert wd_mod._guard_caller() is False
    text = capsys.readouterr()
    combined = (text.out + text.err).lower()
    assert "owner-only" in combined
    assert "no owner is sealed" in combined


def _fake_registry_module(active=None, kill_result=None, kill_all_result=None):
    """Build a fake watchdog.registry module for router-level tests."""
    fake = type(sys)("fake_registry_mod")
    fake.calls = []

    def list_active(storage_path=None, prune_stale=True):
        """Fake registry list_active — returns the preset active list."""
        fake.calls.append(("list_active", prune_stale))
        return list(active or [])

    def kill_watch(handle, storage_path=None):
        """Fake registry kill_watch — returns the preset result."""
        fake.calls.append(("kill_watch", handle))
        return kill_result or {
            "handle": handle,
            "killed": True,
            "was_alive": True,
            "reason": "fake kill",
        }

    def kill_all(storage_path=None):
        """Fake registry kill_all — returns the preset result list."""
        fake.calls.append(("kill_all",))
        return list(kill_all_result or [])

    fake.list_active = list_active
    fake.kill_watch = kill_watch
    fake.kill_all = kill_all
    return fake


def _fake_timer_module_with_format():
    """Minimal fake timer module exposing ``format_human``."""
    fake = type(sys)("fake_timer_mod_fmt")
    fake.format_human = lambda seconds: f"{seconds}s"
    return fake


def _patch_registry_imports(fake_registry, fake_timer=None):
    """Patch importlib.import_module to return the right fake per module path."""
    timer = fake_timer or _fake_timer_module_with_format()

    def fake_import(name):
        """Patched ``importlib.import_module`` — routes to fake registry/timer."""
        if name.endswith(".registry"):
            return fake_registry
        if name.endswith(".timer"):
            return timer
        if name.endswith(".dispatches"):
            # status prints the dispatch line off the REGISTER now (r4 deleted
            # the events-file lag line with the daemon). A fake that reports an
            # unavailable register keeps the line quiet without reaching the
            # real one — and asserts nothing about a machine's live state.
            fake_dispatches = type(sys)("fake_dispatches")

            class RegisterUnavailable(RuntimeError):
                pass

            def _unavailable(*_a, **_kw):
                raise RegisterUnavailable("no register in this test")

            fake_dispatches.RegisterUnavailable = RegisterUnavailable
            fake_dispatches.outstanding = _unavailable
            fake_dispatches.overdue = _unavailable
            return fake_dispatches
        raise ImportError(f"unexpected import in test: {name}")

    return patch("importlib.import_module", side_effect=fake_import)


def test_cancel_requires_handle(capsys):
    """`cancel` with no args prints usage."""
    result = wd_mod.handle_command("watchdog", ["cancel"])
    assert result is True
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "usage" in combined.lower() or "cancel" in combined.lower()


def test_cancel_handle_routes_to_registry(capsys):
    """`cancel <handle>` calls registry.kill_watch and prints the result."""
    fake = _fake_registry_module(
        kill_result={
            "handle": "agent-abc123",
            "killed": True,
            "was_alive": True,
            "reason": "SIGTERM — pid 1234 exited in 0.1s",
        }
    )
    with _patch_registry_imports(fake):
        result = wd_mod.handle_command("watchdog", ["cancel", "agent-abc123"])
    assert result is True
    assert ("kill_watch", "agent-abc123") in fake.calls
    combined = capsys.readouterr().out
    assert "agent-abc123" in combined
    assert "KILLED" in combined


def test_cancel_all_routes_to_registry(capsys):
    """`cancel --all` calls registry.kill_all and prints every result line."""
    fake = _fake_registry_module(
        kill_all_result=[
            {"handle": "timer-111111", "killed": True, "was_alive": True, "reason": "ok"},
            {"handle": "schedule-222222", "killed": True, "was_alive": True, "reason": "ok"},
        ]
    )
    with _patch_registry_imports(fake):
        result = wd_mod.handle_command("watchdog", ["cancel", "--all"])
    assert result is True
    assert ("kill_all",) in fake.calls
    out = capsys.readouterr().out
    assert "timer-111111" in out
    assert "schedule-222222" in out


def test_cancel_all_empty(capsys):
    """`cancel --all` with nothing active reports 'no active watches to cancel'."""
    fake = _fake_registry_module(kill_all_result=[])
    with _patch_registry_imports(fake):
        wd_mod.handle_command("watchdog", ["cancel", "--all"])
    out = capsys.readouterr().out.lower()
    assert "no active watches" in out


def test_status_reports_no_active_watches(capsys):
    """status reports 'no active watches' when the registry is empty."""
    fake = _fake_registry_module(active=[])
    with _patch_registry_imports(fake):
        result = wd_mod.handle_command("watchdog", ["status"])
    assert result is True
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "no active watches" in combined.lower()


def test_status_prints_active_watches(capsys):
    """status prints every active watch with handle + type + pid."""
    active = [
        {
            "handle": "agent-abc123",
            "type": "agent",
            "pid": 4321,
            "started_epoch": 1000.0,
            "elapsed_seconds": 134,
            "metadata": {"agent_id": "@drone", "timeout_seconds": 1800},
        },
        {
            "handle": "schedule-def456",
            "type": "schedule",
            "pid": 4322,
            "started_epoch": 2000.0,
            "elapsed_seconds": 45,
            "metadata": {"scheduled_for": "02:00:00", "command": "drone @git status"},
        },
    ]
    fake = _fake_registry_module(active=active)
    with _patch_registry_imports(fake):
        result = wd_mod.handle_command("watchdog", ["status"])
    assert result is True
    out = capsys.readouterr().out
    assert "agent-abc123" in out
    assert "schedule-def456" in out
    assert "@drone" in out
    assert "2 active" in out or "2 active watch" in out


def test_the_wire_row_does_not_report_a_daemon_that_cannot_exist(capsys):
    """r4 has no daemon, so the wire row must not print ``daemon_pid``.

    The field survived the daemon by two hours. It rendered as a permanent
    ``daemon_pid=?`` on the one row an operator checks when they suspect the
    watchdog is broken — a phantom fault on the health display of the thing
    whose whole job is not to lie about its own health.
    """
    active = [
        {
            "handle": "wire-001",
            "type": "baseline_wire",
            "pid": 5150,
            "started_epoch": 1000.0,
            "elapsed_seconds": 90,
            "metadata": {"session": "sess-abc", "wrapper": "monitor", "stdout": "socket:[123]"},
        },
    ]
    fake = _fake_registry_module(active=active)
    with _patch_registry_imports(fake):
        assert wd_mod.handle_command("watchdog", ["status"]) is True
    out = capsys.readouterr().out
    assert "daemon" not in out.lower()
    assert "sess-abc" in out


def test_the_wire_row_says_which_wrapper_is_carrying_it(capsys):
    """``via`` must show a real value on the HEALTHY path, not a permanent ?.

    This row replaced two fields that read ``?`` whenever the watchdog was
    working — first ``daemon_pid``, then ``tasks_dir`` (a Monitor child's
    stdout is a socket and has no tasks dir). A field that says ``?`` on the
    happy path trains the operator to skip the row, which is the opposite of
    what a health display is for.
    """
    active = [
        {
            "handle": "wire-003",
            "type": "baseline_wire",
            "pid": 5153,
            "started_epoch": 1000.0,
            "elapsed_seconds": 10,
            "metadata": {"session": "sess-abc", "wrapper": "background", "stdout": "/x/tasks/y.output"},
        },
    ]
    fake = _fake_registry_module(active=active)
    with _patch_registry_imports(fake):
        assert wd_mod.handle_command("watchdog", ["status"]) is True
    out = capsys.readouterr().out
    assert "via=background" in out
    assert "?" not in out.split("wire-003")[1].split("\n")[0]


def test_a_foreground_wire_is_named_as_having_no_listener(capsys):
    """No session means nothing is reading stdout — the 2026-08-19 12:34 failure.

    It must read as NONE and not as a blank field, because a blank column looks
    like a rendering gap and a rendering gap gets scrolled past.
    """
    active = [
        {
            "handle": "wire-002",
            "type": "baseline_wire",
            "pid": 5151,
            "started_epoch": 1000.0,
            "elapsed_seconds": 5,
            "metadata": {"session": None, "tasks_dir": None, "stdout": None},
        },
    ]
    fake = _fake_registry_module(active=active)
    with _patch_registry_imports(fake):
        assert wd_mod.handle_command("watchdog", ["status"]) is True
    assert "NONE (fg)" in capsys.readouterr().out


def test_an_unknown_watch_type_still_renders_its_row(capsys):
    """A watch nobody can see is a watch nobody retires.

    The tail table replaced an if/elif chain; a table lookup that misses must
    fall back to raw metadata rather than dropping or crashing the row.
    """
    active = [
        {
            "handle": "mystery-01",
            "type": "from_the_future",
            "pid": 5152,
            "started_epoch": 1000.0,
            "elapsed_seconds": 5,
            "metadata": {"invented_field": "cassiopeia"},
        },
    ]
    fake = _fake_registry_module(active=active)
    with _patch_registry_imports(fake):
        assert wd_mod.handle_command("watchdog", ["status"]) is True
    out = capsys.readouterr().out
    assert "mystery-01" in out
    assert "cassiopeia" in out


def test_list_routes_to_status(capsys):
    """`list` is an alias — same output as `status`."""
    fake = _fake_registry_module(active=[])
    with _patch_registry_imports(fake):
        result = wd_mod.handle_command("watchdog", ["list"])
    assert result is True
    out = capsys.readouterr().out.lower()
    assert "watchdog status" in out or "no active watches" in out


def test_agent_subcommand_requires_id(capsys):
    """`agent` with no id prints usage."""
    result = wd_mod.handle_command("watchdog", ["agent"])
    assert result is True
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "usage" in combined.lower() or "watchdog agent" in combined.lower()


def test_agent_subcommand_invokes_handler(capsys):
    """`agent <id>` lazily imports and invokes watch_agent."""
    fake_result = {
        "woke": True,
        "reason": "fake clean exit",
        "elapsed": 5,
        "agent_state": "completed",
        "exit_code": 0,
        "agent_id": "@drone",
    }
    fake_module = type(sys)("fake_agent_mod")
    fake_module.watch_agent = lambda agent_id, timeout_seconds=1800: fake_result

    with patch("importlib.import_module", return_value=fake_module):
        result = wd_mod.handle_command("watchdog", ["agent", "@drone"])

    assert result is True
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "completed" in combined
    assert "@drone" in combined


def test_agent_subcommand_parses_timeout_flag():
    """--timeout flag is parsed and passed to the handler."""
    captured_args = {}

    def fake_watch_agent(agent_id, timeout_seconds=1800):
        """Fake agent watcher that records its arguments."""
        captured_args["agent_id"] = agent_id
        captured_args["timeout"] = timeout_seconds
        return {
            "woke": True,
            "reason": "fake",
            "elapsed": 1,
            "agent_state": "completed",
            "exit_code": 0,
            "agent_id": agent_id,
        }

    fake_module = type(sys)("fake_agent_mod")
    fake_module.watch_agent = fake_watch_agent

    with patch("importlib.import_module", return_value=fake_module):
        wd_mod.handle_command("watchdog", ["agent", "@flow", "--timeout", "60"])

    assert captured_args == {"agent_id": "@flow", "timeout": 60}


def test_agent_subcommand_invalid_timeout(capsys):
    """Invalid --timeout value reports a clean error."""
    result = wd_mod.handle_command("watchdog", ["agent", "@flow", "--timeout", "notanumber"])
    assert result is True
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "invalid" in combined.lower() or "--timeout" in combined.lower()


def test_agent_subcommand_default_timeout_is_600():
    """Without an explicit --timeout, the module passes 600s (FPLAN-0189)."""
    captured_args = {}

    def fake_watch_agent(agent_id, timeout_seconds=9999):
        """Fake watcher — records the timeout the module passed in."""
        captured_args["timeout"] = timeout_seconds
        return {
            "woke": True,
            "reason": "fake",
            "elapsed": 1,
            "agent_state": "completed",
            "exit_code": 0,
            "agent_id": agent_id,
        }

    fake_module = type(sys)("fake_agent_mod")
    fake_module.watch_agent = fake_watch_agent

    with patch("importlib.import_module", return_value=fake_module):
        wd_mod.handle_command("watchdog", ["agent", "@flow"])

    assert captured_args["timeout"] == 600


def test_agent_subcommand_emits_next_action_breadcrumb(capsys):
    """On exit, the CLI prints a 'Next: drone @ai_mail dispatch' breadcrumb (FPLAN-0189)."""
    fake_result = {
        "woke": True,
        "reason": "fake clean exit",
        "elapsed": 5,
        "agent_state": "completed",
        "exit_code": 0,
        "agent_id": "@drone",
    }
    fake_module = type(sys)("fake_agent_mod")
    fake_module.watch_agent = lambda agent_id, timeout_seconds=600: fake_result

    with patch("importlib.import_module", return_value=fake_module):
        wd_mod.handle_command("watchdog", ["agent", "@drone"])

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    # Normalize whitespace: Rich console output may wrap differently across
    # terminal widths (especially on Windows CI where width is narrower).
    normalized = " ".join(combined.split())
    assert "Next: drone @ai_mail dispatch @drone" in normalized
    assert "state=completed" in normalized


# ─────────────────────────────────────────────────────────────────────────────
# baseline subcommand (DPLAN-0308)
# ─────────────────────────────────────────────────────────────────────────────


def _fake_baseline_module(result=None, recorder=None):
    """Minimal fake handler module for router-level tests.

    Serves BOTH doors the router lazily imports: ``arm_wire`` (the default,
    wire.py) and ``watch_baseline`` (the ``--daemon`` detection role).
    """
    fake = type(sys)("fake_baseline_mod")

    def arm_wire(once=False):
        """Fake wire door — records its arguments, returns a preset result."""
        if recorder is not None:
            recorder["once"] = once
        return result or {"state": "stopped", "replayed": 0, "delivered": 0, "ticks": 1, "session": "s"}

    def watch_baseline(once=False, daemon=False):
        """Fake daemon door — records the daemon flag."""
        if recorder is not None:
            recorder["daemon"] = daemon
        return result or {"state": "stopped", "handle": "baseline-abc123", "completions": 0, "ticks": 1, "elapsed": 0}

    fake.arm_wire = arm_wire
    fake.watch_baseline = watch_baseline
    return fake


def test_baseline_is_a_known_subcommand():
    """`baseline` routes instead of falling through to the unknown-subcommand error."""
    assert "baseline" in wd_mod._VALID_SUBCOMMANDS
    assert "baseline" in wd_mod.HELP_TEXT


def test_baseline_subcommand_invokes_handler(capsys):
    """Bare `baseline` lazily imports and invokes the wire arm door."""
    recorder = {}
    fake_module = _fake_baseline_module(
        result={"state": "stopped", "handle": "baseline-abc123", "completions": 2, "ticks": 9, "elapsed": 18},
        recorder=recorder,
    )

    with patch("importlib.import_module", return_value=fake_module):
        result = wd_mod.handle_command("watchdog", ["baseline"])

    assert result is True
    assert recorder == {"once": False}
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "baseline" in combined.lower()


def test_baseline_once_flag_is_parsed():
    """--once reaches the handler."""
    recorder = {}
    fake_module = _fake_baseline_module(recorder=recorder)

    with patch("importlib.import_module", return_value=fake_module):
        wd_mod.handle_command("watchdog", ["baseline", "--once"])

    assert recorder == {"once": True}


def test_baseline_rejects_unknown_flag(capsys):
    """An unknown flag is a clean error — and never starts a watch."""
    fake_module = _fake_baseline_module(recorder={})

    with patch("importlib.import_module", return_value=fake_module) as imported:
        result = wd_mod.handle_command("watchdog", ["baseline", "--forever"])

    assert result is True
    imported.assert_not_called()
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "--forever" in combined or "unknown" in combined.lower()


def test_baseline_daemon_flag_is_refused_by_name(capsys):
    """r4 deleted the detection daemon. --daemon must say THAT, not "unknown flag".

    An operator or a stale script passing it deserves to be told the lane
    changed rather than that they made a typo — and the refusal happens before
    any import, so nothing is armed on the way to the error.
    """
    fake_module = _fake_baseline_module(recorder={})

    with patch("importlib.import_module", return_value=fake_module) as imported:
        result = wd_mod.handle_command("watchdog", ["baseline", "--daemon"])

    assert result is True
    imported.assert_not_called()
    combined = capsys.readouterr()
    text = combined.out + combined.err
    assert "removed in watchdog r4" in text
    assert "no detection daemon" in text


def test_baseline_daemon_is_still_refused_alongside_once(capsys):
    """The flag is dead in every combination, not just alone."""
    fake_module = _fake_baseline_module(recorder={})

    with patch("importlib.import_module", return_value=fake_module) as imported:
        result = wd_mod.handle_command("watchdog", ["baseline", "--once", "--daemon"])

    assert result is True
    imported.assert_not_called()
    combined = capsys.readouterr()
    assert "removed in watchdog r4" in combined.out + combined.err
