# =================== AIPass ====================
# Name: test_screen_lock.py
# Description: Tests for the screen_lock skill — lock paths, the lock-state read, honest failure, doctrine
# Version: 1.1.0
# Created: 2026-08-14
# Modified: 2026-09-13
# =============================================

"""
screen_lock skill tests.

Every test that reaches lock_screen() MUST patch subprocess.run — an unpatched
call locks the real machine mid-suite. Every test that reaches lock_state()
patches it too: a real loginctl answer is this laptop's, not the contract's.
"""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from aipass.skills.lib.screen_lock import handler as screen_lock

# The resolver matches sessions against our own uid, so build the fixtures from it
# rather than hard-coding 1000 — CI does not run as the owner. Windows has no
# os.getuid at all, so fall back to a fixed uid there and pin the resolver to it.
_UID = str(os.getuid()) if hasattr(os, "getuid") else "1000"


@pytest.fixture(autouse=True)
def _pin_getuid(monkeypatch):
    # The resolver calls os.getuid() only after the (mocked) loginctl succeeds,
    # so on Windows the mock walks it straight into a missing API.
    monkeypatch.setattr(os, "getuid", lambda: int(_UID), raising=False)


def _cpe(cmd, stderr: bytes | str = b""):
    return subprocess.CalledProcessError(1, cmd, stderr=stderr)


def _loginctl_stub(*, sessions="3 …\n", props=None, list_error=None, lock_error=None, dbus_error=None):
    """
    subprocess.run side_effect covering the whole lock command tree.

    Fakes `loginctl list-sessions`, per-session `show-session`, `lock-session`
    and the `gdbus` screensaver fallback, so a test can fail any one of them
    independently without the others going missing.
    """
    if props is None:
        props = {"3": {"Type": "wayland", "State": "active", "User": _UID}}

    def _run(cmd, **kwargs):
        if cmd[:2] == ["loginctl", "list-sessions"]:
            if list_error:
                raise list_error
            return MagicMock(stdout=sessions)
        if cmd[:2] == ["loginctl", "show-session"]:
            return MagicMock(stdout="".join(f"{k}={v}\n" for k, v in props.get(cmd[2], {}).items()))
        if cmd[:2] == ["loginctl", "lock-session"]:
            if lock_error:
                raise lock_error
            return MagicMock(returncode=0)
        if cmd[0] == "gdbus":
            if dbus_error:
                raise dbus_error
            return MagicMock(returncode=0)
        raise AssertionError(f"unexpected command in the lock path: {cmd}")

    return _run


# =============================================
# Session resolution — naming the session is what makes the verb work from a
# `systemd --user` context with no XDG_SESSION_ID
# =============================================


class TestSessionResolution:
    def test_resolves_the_graphical_session_and_locks_it_by_id(self):
        with patch("subprocess.run", side_effect=_loginctl_stub()) as mock_run:
            result = screen_lock.lock_screen()

        assert call(["loginctl", "lock-session", "3"], check=True, capture_output=True) in mock_run.call_args_list
        assert result["locked"] is True
        assert result["method"] == "loginctl"
        assert result["session"] == "3"
        assert result["error"] is None

    def test_picks_the_x11_session_too(self):
        stub = _loginctl_stub(props={"7": {"Type": "x11", "State": "active", "User": _UID}}, sessions="7 …\n")

        with patch("subprocess.run", side_effect=stub) as mock_run:
            result = screen_lock.lock_screen()

        assert call(["loginctl", "lock-session", "7"], check=True, capture_output=True) in mock_run.call_args_list
        assert result["session"] == "7"

    def test_skips_tty_and_inactive_sessions(self):
        """A headless tty login and a backgrounded graphical session must not win."""
        stub = _loginctl_stub(
            sessions="1 …\n2 …\n3 …\n",
            props={
                "1": {"Type": "tty", "State": "active", "User": _UID},
                "2": {"Type": "wayland", "State": "online", "User": _UID},
                "3": {"Type": "wayland", "State": "active", "User": _UID},
            },
        )

        with patch("subprocess.run", side_effect=stub) as mock_run:
            screen_lock.lock_screen()

        assert call(["loginctl", "lock-session", "3"], check=True, capture_output=True) in mock_run.call_args_list

    def test_ignores_another_users_graphical_session(self):
        """Never lock someone else's desktop — with no session of ours, fall back to the bare call."""
        other_uid = str(int(_UID) + 1)
        stub = _loginctl_stub(props={"3": {"Type": "wayland", "State": "active", "User": other_uid}})

        with patch("subprocess.run", side_effect=stub) as mock_run:
            result = screen_lock.lock_screen()

        assert call(["loginctl", "lock-session"], check=True, capture_output=True) in mock_run.call_args_list
        assert result["session"] is None
        for call_args in mock_run.call_args_list:
            assert "lock-session" not in call_args.args[0] or len(call_args.args[0]) == 2

    def test_falls_back_to_the_bare_call_when_listing_fails(self):
        stub = _loginctl_stub(list_error=_cpe(["loginctl"], stderr=b"boom"))

        with patch("subprocess.run", side_effect=stub) as mock_run:
            result = screen_lock.lock_screen()

        assert call(["loginctl", "lock-session"], check=True, capture_output=True) in mock_run.call_args_list
        assert result["locked"] is True

    def test_skips_a_session_it_cannot_inspect(self):
        """One unreadable session must not abort the walk — the next one can still be ours."""

        def _run(cmd, **kwargs):
            if cmd[:2] == ["loginctl", "list-sessions"]:
                return MagicMock(stdout="2 …\n3 …\n")
            if cmd[:2] == ["loginctl", "show-session"]:
                if cmd[2] == "2":
                    raise _cpe(["loginctl"], stderr=b"no such session")
                return MagicMock(stdout=f"Type=wayland\nState=active\nUser={_UID}\n")
            if cmd[:2] == ["loginctl", "lock-session"]:
                return MagicMock(returncode=0)
            raise AssertionError(f"unexpected command in the lock path: {cmd}")

        with patch("subprocess.run", side_effect=_run) as mock_run:
            result = screen_lock.lock_screen()

        assert call(["loginctl", "lock-session", "3"], check=True, capture_output=True) in mock_run.call_args_list
        assert result["session"] == "3"

    def test_survives_blank_lines_in_the_session_listing(self):
        with patch("subprocess.run", side_effect=_loginctl_stub(sessions="\n\n3 …\n\n")) as mock_run:
            screen_lock.lock_screen()

        assert call(["loginctl", "lock-session", "3"], check=True, capture_output=True) in mock_run.call_args_list

    def test_resolve_graphical_session_is_callable_on_its_own(self):
        """The host verb lane may want the session id without locking anything."""
        with patch("subprocess.run", side_effect=_loginctl_stub()) as mock_run:
            session = screen_lock.resolve_graphical_session()

        assert session == "3"
        assert not any("lock-session" in c.args[0] for c in mock_run.call_args_list)


# =============================================
# Fallback and honest failure
# =============================================


class TestFallbackAndFailure:
    def test_falls_back_to_dbus_when_loginctl_refuses(self):
        """Refusal from the service context is exactly the case the D-Bus path exists for."""
        stub = _loginctl_stub(lock_error=_cpe(["loginctl"], stderr=b"Interactive authentication required."))

        with patch("subprocess.run", side_effect=stub) as mock_run:
            result = screen_lock.lock_screen()

        dbus_calls = [c for c in mock_run.call_args_list if c.args[0][0] == "gdbus"]
        assert len(dbus_calls) == 1
        assert "org.gnome.ScreenSaver.Lock" in dbus_calls[0].args[0]
        assert result["locked"] is True
        assert result["method"] == "dbus"

    def test_falls_back_to_dbus_when_loginctl_is_missing(self):
        # loginctl absent entirely — both the listing and the lock raise.
        stub = _loginctl_stub(list_error=FileNotFoundError(), lock_error=FileNotFoundError())

        with patch("subprocess.run", side_effect=stub) as mock_run:
            result = screen_lock.lock_screen()

        assert any(c.args[0][0] == "gdbus" for c in mock_run.call_args_list)
        assert result["method"] == "dbus"

    def test_reports_honestly_when_both_paths_fail(self):
        """No silent success — a screen that never locked must not be reported as locked."""
        stub = _loginctl_stub(
            lock_error=_cpe(["loginctl"], stderr=b"refused"),
            dbus_error=_cpe(["gdbus"], stderr=b"no session bus"),
        )

        with patch("subprocess.run", side_effect=stub):
            result = screen_lock.lock_screen()

        assert result["locked"] is False
        assert result["method"] is None
        assert result["error"] == "Could not lock the screen — loginctl and the D-Bus fallback both failed."

    def test_needs_no_root_and_never_suspends(self):
        """No sudo, no rtcwake, no systemctl, nothing sleeps — that's the whole point of the verb."""
        with patch("subprocess.run", side_effect=_loginctl_stub()) as mock_run:
            screen_lock.lock_screen()

        for call_args in mock_run.call_args_list:
            assert call_args.args[0][0] not in ("sudo", "systemctl")
            assert "rtcwake" not in " ".join(call_args.args[0])
            assert "suspend" not in " ".join(call_args.args[0])


# =============================================
# Doctrine (DPLAN-0300): a destructive action never fires from a locked screen —
# lock is the exception that MUST work from anywhere. It is never gated.
# =============================================


class TestLockIsNeverGated:
    def test_never_asks_whether_the_screen_is_already_locked(self):
        with patch("subprocess.run", side_effect=_loginctl_stub()) as mock_run:
            screen_lock.lock_screen()

        issued = [" ".join(c.args[0]) for c in mock_run.call_args_list]
        assert not any("LockedHint" in cmd or "IsLocked" in cmd or "Active" in cmd for cmd in issued)


# =============================================
# The read beside the lock (FPLAN-0585): lock_state() says whether the screen IS
# locked. A read that answered carries True/False; one that cannot tell carries
# None and a reason — unknown is never drawn as unlocked. A read locks nothing.
# =============================================

_LOCKED_HINT = ["loginctl", "show-session", "3", "-p", "LockedHint"]
_GET_ACTIVE = [
    "gdbus",
    "call",
    "--session",
    "--dest",
    "org.gnome.ScreenSaver",
    "--object-path",
    "/org/gnome/ScreenSaver",
    "--method",
    "org.gnome.ScreenSaver.GetActive",
]
_READ_KWARGS = {"check": True, "capture_output": True, "text": True}


def _state_stub(
    *,
    sessions="3 …\n",
    props=None,
    list_error=None,
    hint="LockedHint=no\n",
    hint_error=None,
    active="(false,)\n",
    active_error=None,
):
    """
    subprocess.run side_effect covering the whole read tree.

    Fakes `loginctl list-sessions`, the resolver's per-session `show-session`,
    the LockedHint read and GNOME ScreenSaver's GetActive, each by its exact
    argv. Anything else — a lock-session, ScreenSaver.Lock, the freedesktop
    interface — raises, so every read test also proves the read locked nothing.
    """
    if props is None:
        props = {"3": {"Type": "wayland", "State": "active", "User": _UID}}

    def _run(cmd, **kwargs):
        if cmd == ["loginctl", "list-sessions", "--no-legend"]:
            if list_error:
                raise list_error
            return MagicMock(stdout=sessions)
        if cmd[:2] == ["loginctl", "show-session"] and cmd[3:] == ["-p", "Type", "-p", "State", "-p", "User"]:
            return MagicMock(stdout="".join(f"{k}={v}\n" for k, v in props.get(cmd[2], {}).items()))
        if cmd == _LOCKED_HINT:
            if hint_error:
                raise hint_error
            return MagicMock(stdout=hint)
        if cmd == _GET_ACTIVE:
            if active_error:
                raise active_error
            return MagicMock(stdout=active)
        raise AssertionError(f"unexpected command in the read path: {cmd}")

    return _run


class TestLockStateAnswers:
    @pytest.mark.parametrize(
        ("hint", "locked", "word"),
        [("LockedHint=yes\n", True, "locked"), ("LockedHint=no\n", False, "unlocked")],
    )
    def test_logind_answers_first_and_the_screensaver_is_never_asked(self, hint, locked, word):
        with patch("subprocess.run", side_effect=_state_stub(hint=hint)) as mock_run:
            result = screen_lock.lock_state()

        assert result == {
            "ok": True,
            "locked": locked,
            "method": "loginctl",
            "session": "3",
            "reason": None,
            "detail": f"The screen is {word}, per logind session 3.",
        }
        assert mock_run.call_args_list[-1] == call(_LOCKED_HINT, **_READ_KWARGS)
        assert call(_GET_ACTIVE, **_READ_KWARGS) not in mock_run.call_args_list

    @pytest.mark.parametrize(
        ("active", "locked", "word"),
        [("(true,)\n", True, "locked"), ("(false,)\n", False, "unlocked")],
    )
    def test_loginctl_missing_then_the_screensaver_answers(self, active, locked, word):
        stub = _state_stub(list_error=FileNotFoundError(), active=active)

        with patch("subprocess.run", side_effect=stub) as mock_run:
            result = screen_lock.lock_state()

        assert result == {
            "ok": True,
            "locked": locked,
            "method": "dbus",
            "session": None,
            "reason": None,
            "detail": f"The screen is {word}, per GNOME ScreenSaver.",
        }
        assert mock_run.call_args_list[-1] == call(_GET_ACTIVE, **_READ_KWARGS)

    def test_a_malformed_logind_answer_falls_back_to_the_screensaver(self):
        stub = _state_stub(hint="LockedHint=\n", active="(true,)\n")

        with patch("subprocess.run", side_effect=stub):
            result = screen_lock.lock_state()

        assert result == {
            "ok": True,
            "locked": True,
            "method": "dbus",
            "session": "3",
            "reason": None,
            "detail": "The screen is locked, per GNOME ScreenSaver.",
        }

    def test_an_unresolved_session_still_asks_the_screensaver(self):
        """The same pair the lock tries: no session of ours sends the read on to D-Bus, never a bare show-session."""
        with patch("subprocess.run", side_effect=_state_stub(sessions="", active="(true,)\n")) as mock_run:
            result = screen_lock.lock_state()

        assert (result["ok"], result["locked"], result["method"], result["session"]) == (True, True, "dbus", None)
        issued = [c.args[0] for c in mock_run.call_args_list]
        assert issued == [["loginctl", "list-sessions", "--no-legend"], _GET_ACTIVE]


class TestLockStateCannotTell:
    @pytest.mark.parametrize(
        ("active_error", "dbus_sentence"),
        [
            (FileNotFoundError(), "gdbus is not installed."),
            (
                _cpe(_GET_ACTIVE, stderr="Error: Cannot autolaunch D-Bus without X11 $DISPLAY\n"),
                "GNOME ScreenSaver did not answer (exit 1: Error: Cannot autolaunch D-Bus without X11 $DISPLAY).",
            ),
        ],
    )
    def test_no_graphical_session_is_no_session_never_unlocked(self, active_error, dbus_sentence):
        """A machine with no desktop of ours answers no_session, however the fallback fails."""
        with patch("subprocess.run", side_effect=_state_stub(sessions="", active_error=active_error)):
            result = screen_lock.lock_state()

        assert result == {
            "ok": False,
            "locked": None,
            "method": None,
            "session": None,
            "reason": "no_session",
            "detail": (
                "Cannot tell whether the screen is locked. "
                f"logind lists no active graphical session of this user. {dbus_sentence}"
            ),
        }

    def test_both_readers_missing_is_no_reader(self):
        stub = _state_stub(list_error=FileNotFoundError(), active_error=FileNotFoundError())

        with patch("subprocess.run", side_effect=stub):
            result = screen_lock.lock_state()

        assert result == {
            "ok": False,
            "locked": None,
            "method": None,
            "session": None,
            "reason": "no_reader",
            "detail": "Cannot tell whether the screen is locked. loginctl is not installed. gdbus is not installed.",
        }

    def test_malformed_answers_from_both_readers_is_read_failed(self):
        stub = _state_stub(hint="LockedHint=maybe\n", active="()\n")

        with patch("subprocess.run", side_effect=stub):
            result = screen_lock.lock_state()

        assert result == {
            "ok": False,
            "locked": None,
            "method": None,
            "session": "3",
            "reason": "read_failed",
            "detail": (
                "Cannot tell whether the screen is locked. "
                "loginctl answered 'LockedHint=maybe' for session 3, not LockedHint=yes or no. "
                "GNOME ScreenSaver answered '()', not (true,) or (false,)."
            ),
        }

    def test_a_refused_logind_read_outranks_a_missing_fallback(self):
        stub = _state_stub(
            hint_error=_cpe(_LOCKED_HINT, stderr="Failed to get path for session '3': No session '3' known\n"),
            active_error=FileNotFoundError(),
        )

        with patch("subprocess.run", side_effect=stub):
            result = screen_lock.lock_state()

        assert (result["ok"], result["locked"], result["reason"]) == (False, None, "read_failed")
        assert result["session"] == "3"
        assert result["detail"] == (
            "Cannot tell whether the screen is locked. loginctl could not read LockedHint of session 3 "
            "(exit 1: Failed to get path for session '3': No session '3' known). gdbus is not installed."
        )

    def test_logind_down_is_read_failed_not_no_session(self):
        """A listing that fails is not a listing that came back empty."""
        stub = _state_stub(
            list_error=_cpe(["loginctl"], stderr="System has not been booted with systemd as init system (PID 1).\n"),
            active_error=FileNotFoundError(),
        )

        with patch("subprocess.run", side_effect=stub):
            result = screen_lock.lock_state()

        assert (result["ok"], result["locked"], result["reason"]) == (False, None, "read_failed")
        assert result["session"] is None
        assert result["detail"] == (
            "Cannot tell whether the screen is locked. loginctl could not list sessions "
            "(exit 1: System has not been booted with systemd as init system (PID 1).). gdbus is not installed."
        )

    def test_loginctl_missing_and_the_screensaver_refusing_is_read_failed(self):
        stub = _state_stub(list_error=FileNotFoundError(), active_error=_cpe(_GET_ACTIVE))

        with patch("subprocess.run", side_effect=stub):
            result = screen_lock.lock_state()

        assert result == {
            "ok": False,
            "locked": None,
            "method": None,
            "session": None,
            "reason": "read_failed",
            "detail": (
                "Cannot tell whether the screen is locked. loginctl is not installed. "
                "GNOME ScreenSaver did not answer (exit 1)."
            ),
        }

    @pytest.mark.parametrize(
        "stub_kwargs",
        [
            {"list_error": PermissionError("loginctl: permission denied"), "active_error": FileNotFoundError()},
            {"hint_error": PermissionError("loginctl: permission denied"), "active_error": PermissionError("denied")},
            {"hint_error": subprocess.TimeoutExpired(_LOCKED_HINT, 5), "active_error": FileNotFoundError()},
        ],
    )
    def test_an_os_or_subprocess_error_is_answered_never_raised(self, stub_kwargs):
        with patch("subprocess.run", side_effect=_state_stub(**stub_kwargs)):
            result = screen_lock.lock_state()

        assert (result["ok"], result["locked"], result["method"], result["reason"]) == (
            False,
            None,
            None,
            "read_failed",
        )


class TestLockStateIsAReadOnly:
    def test_the_read_issues_exactly_the_four_reads_and_nothing_else(self):
        """Resolve, LockedHint, then GetActive — no lock-session, no ScreenSaver.Lock, no freedesktop interface."""
        stub = _state_stub(hint="LockedHint=\n", active="(false,)\n")

        with patch("subprocess.run", side_effect=stub) as mock_run:
            screen_lock.lock_state()

        assert mock_run.call_args_list == [
            call(["loginctl", "list-sessions", "--no-legend"], **_READ_KWARGS),
            call(["loginctl", "show-session", "3", "-p", "Type", "-p", "State", "-p", "User"], **_READ_KWARGS),
            call(_LOCKED_HINT, **_READ_KWARGS),
            call(_GET_ACTIVE, **_READ_KWARGS),
        ]

    def test_the_read_is_not_gated_on_the_skill_switch(self):
        """The lock is never gated, so its read is not either (api verbs.py doctrine)."""
        from aipass.skills.apps.handlers import switch_handler

        with (
            patch.object(switch_handler, "is_enabled", autospec=True, return_value=False) as gate,
            patch("subprocess.run", side_effect=_state_stub()),
        ):
            result = screen_lock.lock_state()

        assert (result["ok"], result["locked"], result["method"]) == (True, False, "loginctl")
        gate.assert_not_called()

    def test_fires_with_no_desktop_environment_at_all(self, monkeypatch):
        """Called from a headless service context — no DISPLAY, no session env, still locks."""
        for var in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_ID", "XDG_SESSION_TYPE"):
            monkeypatch.delenv(var, raising=False)

        with patch("subprocess.run", side_effect=_loginctl_stub()) as mock_run:
            result = screen_lock.lock_screen()

        assert result["locked"] is True
        assert call(["loginctl", "lock-session", "3"], check=True, capture_output=True) in mock_run.call_args_list

    def test_locks_even_when_no_graphical_session_can_be_resolved(self):
        """No session of ours in the listing is not a refusal — the bare call still tries."""
        with patch("subprocess.run", side_effect=_loginctl_stub(sessions="")) as mock_run:
            result = screen_lock.lock_screen()

        assert result["locked"] is True
        assert call(["loginctl", "lock-session"], check=True, capture_output=True) in mock_run.call_args_list


# =============================================
# Skill contract — what `drone @skills run screen_lock ...` and the future host
# verb lane see
# =============================================


class TestSkillContract:
    def test_get_actions_lists_lock_and_state(self):
        assert screen_lock.get_actions() == ["lock", "state"]

    def test_run_state_answers_in_the_envelope_and_locks_nothing(self):
        with patch("subprocess.run", side_effect=_state_stub(hint="LockedHint=yes\n")):
            result = screen_lock.run("state")

        assert result == {"success": True, "output": "The screen is locked, per logind session 3.", "error": None}

    def test_run_state_that_cannot_tell_is_a_failure_carrying_the_reason(self):
        stub = _state_stub(sessions="", active_error=FileNotFoundError())

        with patch("subprocess.run", side_effect=stub):
            result = screen_lock.run("state")

        assert result == {
            "success": False,
            "output": "",
            "error": (
                "Cannot tell whether the screen is locked. logind lists no active graphical session of this user. "
                "gdbus is not installed. (reason=no_session)"
            ),
        }

    def test_run_lock_returns_the_skill_envelope(self):
        with patch("subprocess.run", side_effect=_loginctl_stub()):
            result = screen_lock.run("lock")

        assert result["success"] is True
        assert result["error"] is None
        assert "loginctl" in result["output"]
        assert "3" in result["output"]

    def test_run_lock_reports_failure_in_the_envelope(self):
        stub = _loginctl_stub(
            lock_error=_cpe(["loginctl"], stderr=b"refused"),
            dbus_error=_cpe(["gdbus"], stderr=b"no session bus"),
        )

        with patch("subprocess.run", side_effect=stub):
            result = screen_lock.run("lock")

        assert result["success"] is False
        assert result["error"] == "Could not lock the screen — loginctl and the D-Bus fallback both failed."

    def test_unknown_action_names_what_is_available_and_locks_nothing(self):
        with patch("subprocess.run") as mock_run:
            result = screen_lock.run("unlock")

        assert result["success"] is False
        assert "lock" in result["error"]
        mock_run.assert_not_called()

    def test_no_action_locks_nothing(self):
        """A bare invocation must never fire the verb by default."""
        with patch("subprocess.run") as mock_run:
            result = screen_lock.run(None)

        assert result["success"] is False
        mock_run.assert_not_called()


# =============================================
# Self-containment — the reason the verb was extracted (DPLAN-0300)
# =============================================


class TestSelfContained:
    def test_importing_the_skill_does_not_drag_in_the_telegram_stack(self):
        """
        The whole point of the extraction: the host API's verb lane can invoke
        lock without importing the Telegram bot. A source-level grep would pass
        on a lazy import, so import it for real in a clean interpreter and look
        at what landed in sys.modules.
        """
        src_root = Path(__file__).resolve().parents[5]
        code = (
            "import sys\n"
            "from aipass.skills.lib.screen_lock import handler\n"
            "handler.get_actions()\n"
            "print(','.join(m for m in sys.modules if 'telegram' in m))\n"
        )
        env = {**os.environ, "PYTHONPATH": str(src_root)}

        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=str(src_root))

        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "", f"telegram modules imported: {proc.stdout.strip()}"

    def test_discoverable_through_the_skills_framework(self):
        """Listing actions goes through discovery + load and fires no lock."""
        from aipass.skills.apps.modules.runner import run_skill

        with patch("subprocess.run") as mock_run:
            result = run_skill("screen_lock")

        assert result["success"] is True
        assert "lock" in result["output"]
        mock_run.assert_not_called()
