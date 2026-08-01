"""
Tests for network-error backoff and routine-timeout log level in the poll loop.

Tests cover:
  - Exponential backoff on network errors (1s, 2s, 4s... capped at 60s)
  - Backoff resets on successful poll after network recovery
  - Log-once semantics: first failure logs error, subsequent suppressed
  - Periodic summary logged every 5 minutes while offline
  - Recovery log line with elapsed time and suppressed count
  - Routine read-timeout returns [] silently (not logged at ERROR)
  - Non-network URLError still logged at ERROR
  - ConnectionError/OSError raised as _NetworkPollError
  - _is_network_error classification
  - _is_routine_read_timeout classification
"""

import json
from http.client import HTTPMessage
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

from aipass.skills.lib.telegram.apps.handlers.base_bot import (
    BaseBot,
    _NetworkPollError,
    _is_network_error,
    _is_routine_read_timeout,
    NETWORK_LOG_INTERVAL,
    STARTUP_RETRY_CAP_SECONDS,
)


@pytest.fixture
def _patch_base_bot_deps(tmp_path):
    patches = [
        patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path),
        patch("aipass.skills.lib.telegram.apps.handlers.base_bot.signal.signal"),
        patch("aipass.skills.lib.telegram.apps.handlers.base_bot.atexit.register"),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


def _make_bot(tmp_path, _patch_base_bot_deps):
    workdir = tmp_path / "workdir"
    workdir.mkdir(exist_ok=True)
    bot = BaseBot(
        bot_id="test_bot",
        bot_token="123:FAKETOKEN",
        work_dir=workdir,
        bot_name="Test Bot",
    )
    bot.verify_connection = lambda timeout=15: True
    bot._set_command_menu = lambda: None
    bot._boot_monitor = lambda: None
    bot._check_lock = lambda: False
    bot._create_lock = lambda: None
    bot._remove_lock = lambda: None
    bot._load_offset = lambda: 0  # type: ignore[assignment]
    bot._save_offset = lambda o: None  # type: ignore[assignment]
    return bot


# =============================================
# 1. _is_network_error classification
# =============================================


class TestIsNetworkError:
    def test_dns_failure(self):
        exc = URLError(OSError("[Errno -2] Name or service not known"))
        assert _is_network_error(exc) is True

    def test_getaddrinfo_failure(self):
        exc = URLError(OSError("[Errno -3] getaddrinfo failed"))
        assert _is_network_error(exc) is True

    def test_connection_refused(self):
        exc = URLError(OSError("Connection refused"))
        assert _is_network_error(exc) is True

    def test_network_unreachable(self):
        exc = URLError(OSError("Network is unreachable"))
        assert _is_network_error(exc) is True

    def test_temporary_failure(self):
        exc = URLError(OSError("Temporary failure in name resolution"))
        assert _is_network_error(exc) is True

    def test_reason_is_oserror_instance(self):
        exc = URLError(OSError("any socket error"))
        assert _is_network_error(exc) is True

    def test_http_error_not_network(self):
        exc = URLError("HTTP Error 502")
        assert _is_network_error(exc) is False

    def test_generic_string_not_network(self):
        exc = URLError("some other error")
        assert _is_network_error(exc) is False


# =============================================
# 2. _is_routine_read_timeout classification
# =============================================


class TestIsRoutineReadTimeout:
    def test_read_timeout(self):
        exc = URLError(OSError("The read operation timed out"))
        assert _is_routine_read_timeout(exc) is True

    def test_connect_timeout_not_routine(self):
        exc = URLError(OSError("Connection timed out"))
        assert _is_routine_read_timeout(exc) is False

    def test_dns_failure_not_timeout(self):
        exc = URLError(OSError("Name or service not known"))
        assert _is_routine_read_timeout(exc) is False


# =============================================
# 3. poll_updates error classification
# =============================================


class TestPollUpdatesErrorClassification:
    def test_routine_read_timeout_returns_empty(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        exc = URLError(OSError("The read operation timed out"))
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen", side_effect=exc):
            result = bot.poll_updates(0)
        assert result == []

    def test_routine_read_timeout_no_error_log(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        exc = URLError(OSError("The read operation timed out"))
        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen", side_effect=exc),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.logger") as mock_logger,
        ):
            bot.poll_updates(0)
        mock_logger.error.assert_not_called()

    def test_dns_failure_raises_network_poll_error(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        exc = URLError(OSError("[Errno -2] Name or service not known"))
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen", side_effect=exc):
            with pytest.raises(_NetworkPollError):
                bot.poll_updates(0)

    def test_connection_error_raises_network_poll_error(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        exc = ConnectionResetError("Connection reset by peer")
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen", side_effect=exc):
            with pytest.raises(_NetworkPollError):
                bot.poll_updates(0)

    def test_os_error_raises_network_poll_error(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        exc = OSError("Socket error")
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen", side_effect=exc):
            with pytest.raises(_NetworkPollError):
                bot.poll_updates(0)

    def test_bare_socket_timeout_returns_empty(self, tmp_path, _patch_base_bot_deps):
        """socket.timeout (subclass of OSError) with 'read operation' should be silenced, not raised."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        import socket

        exc = socket.timeout("The read operation timed out")
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen", side_effect=exc):
            result = bot.poll_updates(0)
        assert result == []

    def test_bare_socket_timeout_no_error_log(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        import socket

        exc = socket.timeout("The read operation timed out")
        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen", side_effect=exc),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.logger") as mock_logger,
        ):
            bot.poll_updates(0)
        mock_logger.error.assert_not_called()

    def test_bare_connect_timeout_raises_network_error(self, tmp_path, _patch_base_bot_deps):
        """A connect timeout (not read) IS a network error."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        exc = TimeoutError("Connection timed out")
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen", side_effect=exc):
            with pytest.raises(_NetworkPollError):
                bot.poll_updates(0)

    def test_non_network_urlerror_logs_error(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        exc = URLError("HTTP Error 502")
        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen", side_effect=exc),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.logger") as mock_logger,
        ):
            result = bot.poll_updates(0)
        assert result == []
        mock_logger.error.assert_called_once()
        assert "Poll error" in str(mock_logger.error.call_args)

    def test_http_502_raises_network_poll_error(self, tmp_path, _patch_base_bot_deps):
        """HTTP 502 Bad Gateway should trigger network backoff, not rapid-fire retry."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        exc = HTTPError("https://api.telegram.org/...", 502, "Bad Gateway", HTTPMessage(), None)
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen", side_effect=exc):
            with pytest.raises(_NetworkPollError):
                bot.poll_updates(0)

    def test_http_503_raises_network_poll_error(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        exc = HTTPError("https://api.telegram.org/...", 503, "Service Unavailable", HTTPMessage(), None)
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen", side_effect=exc):
            with pytest.raises(_NetworkPollError):
                bot.poll_updates(0)

    def test_http_409_raises_network_poll_error(self, tmp_path, _patch_base_bot_deps):
        """HTTP 409 Conflict is a stale-session artifact after a connection reset, not a duplicate poller — backoff."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        exc = HTTPError("https://api.telegram.org/...", 409, "Conflict", HTTPMessage(), None)
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen", side_effect=exc):
            with pytest.raises(_NetworkPollError):
                bot.poll_updates(0)

    def test_http_429_backs_off_using_retry_after(self, tmp_path, _patch_base_bot_deps):
        """HTTP 429 must respect Telegram's retry_after, not rapid-fire retry (worsens the throttle)."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        body = json.dumps({"ok": False, "parameters": {"retry_after": 12}}).encode("utf-8")
        exc = HTTPError("https://api.telegram.org/...", 429, "Too Many Requests", HTTPMessage(), None)
        exc.read = MagicMock(return_value=body)
        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen", side_effect=exc),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep") as mock_sleep,
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.logger") as mock_logger,
        ):
            result = bot.poll_updates(0)
        assert result == []
        # time.sleep is a process-global patch target — a leaked background
        # thread (e.g. a watchdog observer) can hit the mock with float sleeps,
        # so count only this backoff's integer call instead of exactly-once.
        backoff_calls = [c.args[0] for c in mock_sleep.call_args_list if isinstance(c.args[0], int)]
        assert backoff_calls == [12]
        mock_logger.error.assert_not_called()
        mock_logger.warning.assert_called_once()

    def test_http_429_unparseable_body_defaults_to_30s(self, tmp_path, _patch_base_bot_deps):
        """No/garbled response body still backs off (default 30s), never falls through to a tight loop."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        exc = HTTPError("https://api.telegram.org/...", 429, "Too Many Requests", HTTPMessage(), None)
        exc.read = MagicMock(side_effect=OSError("no body"))
        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen", side_effect=exc),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep") as mock_sleep,
        ):
            result = bot.poll_updates(0)
        assert result == []
        # Same process-global patch-target caveat as above.
        backoff_calls = [c.args[0] for c in mock_sleep.call_args_list if isinstance(c.args[0], int)]
        assert backoff_calls == [30]

    def test_unexpected_exception_logs_error(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        exc = ValueError("something weird")
        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen", side_effect=exc),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.logger") as mock_logger,
        ):
            result = bot.poll_updates(0)
        assert result == []
        mock_logger.error.assert_called_once()
        assert "Unexpected poll error" in str(mock_logger.error.call_args)


# =============================================
# 4. Run loop network backoff
# =============================================


class TestRunLoopNetworkBackoff:
    def test_backoff_doubles_and_caps(self, tmp_path, _patch_base_bot_deps):
        """Backoff should go 1, 2, 4, 8, 16, 32, 60, 60..."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        call_count = 0
        sleep_values = []

        def failing_poll(offset):
            nonlocal call_count
            call_count += 1
            if call_count > 8:
                bot.state["running"] = False
                return []
            raise _NetworkPollError("DNS failure")

        bot.poll_updates = failing_poll
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep") as mock_sleep:
            bot.run()
            sleep_values = [c.args[0] for c in mock_sleep.call_args_list if c.args[0] >= 1]

        assert sleep_values == [1, 2, 4, 8, 16, 32, 60, 60]

    def test_backoff_resets_on_recovery(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        call_count = 0

        def poll_with_recovery(offset):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise _NetworkPollError("DNS failure")
            if call_count == 4:
                return []  # success — resets backoff
            if call_count == 5:
                raise _NetworkPollError("DNS failure again")
            bot.state["running"] = False
            return []

        bot.poll_updates = poll_with_recovery
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep") as mock_sleep:
            bot.run()
            sleep_values = [c.args[0] for c in mock_sleep.call_args_list if c.args[0] >= 1]

        # 1, 2, 4 (first storm), then reset, then 1 (second failure)
        assert sleep_values == [1, 2, 4, 1]


# =============================================
# 5. Log-once semantics
# =============================================


class TestLogOnceSemantics:
    def test_first_failure_logs_warning(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        call_count = 0

        def failing_poll(offset):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                bot.state["running"] = False
                return []
            raise _NetworkPollError("DNS failure")

        bot.poll_updates = failing_poll
        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep"),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.logger") as mock_logger,
        ):
            bot.run()

        warn_calls = [c for c in mock_logger.warning.call_args_list if "unreachable" in str(c)]
        assert len(warn_calls) == 1
        error_calls = [c for c in mock_logger.error.call_args_list if "unreachable" in str(c)]
        assert len(error_calls) == 0

    def test_subsequent_failures_suppressed(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        call_count = 0

        def failing_poll(offset):
            nonlocal call_count
            call_count += 1
            if call_count > 10:
                bot.state["running"] = False
                return []
            raise _NetworkPollError("DNS failure")

        bot.poll_updates = failing_poll
        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep"),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.logger") as mock_logger,
        ):
            bot.run()

        warn_calls = [c for c in mock_logger.warning.call_args_list if "unreachable" in str(c)]
        # Only one "unreachable" warning, not 10
        assert len(warn_calls) == 1

    def test_recovery_logs_info(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        call_count = 0

        def poll_with_recovery(offset):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise _NetworkPollError("DNS failure")
            bot.state["running"] = False
            return []

        bot.poll_updates = poll_with_recovery
        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep"),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.logger") as mock_logger,
        ):
            bot.run()

        recovery_calls = [c for c in mock_logger.info.call_args_list if "reachable again" in str(c)]
        assert len(recovery_calls) == 1

    def test_periodic_summary_during_offline(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        call_count = 0
        fake_time = [100.0]

        def failing_poll(offset):
            nonlocal call_count
            call_count += 1
            # Advance fake clock past NETWORK_LOG_INTERVAL each call
            fake_time[0] += NETWORK_LOG_INTERVAL + 1
            if call_count > 4:
                bot.state["running"] = False
                return []
            raise _NetworkPollError("DNS failure")

        bot.poll_updates = failing_poll

        def fake_time_fn():
            return fake_time[0]

        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep"),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.time", side_effect=fake_time_fn),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.logger") as mock_logger,
        ):
            bot.run()

        summary_calls = [c for c in mock_logger.warning.call_args_list if "Still offline" in str(c)]
        # Calls 2, 3, 4 should each trigger a summary (time jumped >5m each time)
        assert len(summary_calls) >= 2

    def test_health_errors_incremented(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        call_count = 0

        def failing_poll(offset):
            nonlocal call_count
            call_count += 1
            if call_count > 5:
                bot.state["running"] = False
                return []
            raise _NetworkPollError("DNS failure")

        bot.poll_updates = failing_poll
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep"):
            bot.run()

        assert bot._health["errors"] == 5


# =============================================
# 6. Startup health-check retry-with-backoff
# =============================================


class TestStartupVerifyConnectionRetry:
    def test_immediate_success_no_sleep(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot.verify_connection = lambda timeout=15: True

        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep") as mock_sleep:
            result = bot._verify_connection_with_retry()
            # time.sleep is a process-global patch target — filter to this backoff's
            # own (always-integer) values so an unrelated thread's real, unmocked
            # sleep() elsewhere in the process can't leak noise into the assertion.
            backoff_calls = [c.args[0] for c in mock_sleep.call_args_list if isinstance(c.args[0], int)]

        assert result is True
        assert backoff_calls == []

    def test_recovers_after_retries(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        call_count = 0

        def flaky_then_ok(timeout=15):
            nonlocal call_count
            call_count += 1
            return call_count >= 3

        bot.verify_connection = flaky_then_ok

        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep") as mock_sleep:
            result = bot._verify_connection_with_retry()
            sleep_values = [c.args[0] for c in mock_sleep.call_args_list if isinstance(c.args[0], int)]

        assert result is True
        assert sleep_values == [1, 2]

    def test_gives_up_after_cap_and_returns_false(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot.verify_connection = lambda timeout=15: False

        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep") as mock_sleep:
            result = bot._verify_connection_with_retry()
            sleep_values = [c.args[0] for c in mock_sleep.call_args_list if isinstance(c.args[0], int)]

        assert result is False
        assert sum(sleep_values) >= STARTUP_RETRY_CAP_SECONDS
        assert sleep_values == [1, 2, 4, 8, 16, 32, 60, 60]

    def test_retry_attempts_logged_at_warning_not_error(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot.verify_connection = lambda timeout=15: False

        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep"),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.logger") as mock_logger,
        ):
            bot._verify_connection_with_retry()

        assert mock_logger.error.call_count == 0
        assert mock_logger.warning.call_count >= 1

    def test_run_fails_loud_once_after_cap_exhausted(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot.verify_connection = lambda timeout=15: False

        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep"),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.logger") as mock_logger,
        ):
            result = bot.run()

        assert result == 1
        fail_calls = [c for c in mock_logger.error.call_args_list if "Startup health check FAILED" in str(c)]
        assert len(fail_calls) == 1
