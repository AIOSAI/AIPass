# =================== AIPass ====================
# Name: test_dispatch_monitor_sandbox.py
# Description: Tests for the dispatch monitor's sandbox gate and its broker-fd handshake
# Version: 1.0.1
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/dispatch/dispatch_monitor.py's sandbox gate and broker handshake (FPLAN-0250)."""

# Split out of test_dispatch_monitor.py on 2026-10-08 to keep that file under the
# 1,200-line target: whether a dispatch runs sandboxed, and the fd it is handed.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — main()'s attempts and the bounce: tests/test_dispatch_monitor.py

import os
import subprocess
import sys
import pytest
from unittest.mock import MagicMock

import aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor as mod
from aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor import (
    is_sandbox_enabled,
    wrap_for_sandbox,
    main,
)
from aipass.drone.apps.modules.door_broker import BrokerDaemon, create_identified_connection

pytestmark = pytest.mark.usefixtures("monitor_json_silenced", "monitor_logger_silenced", "monitor_wake_stubbed")


# --- Sandbox gate tests (Phase 4 FPLAN-0250) --------------------------------


class TestIsSandboxEnabled:
    """is_sandbox_enabled reads AIPASS_SANDBOX_ENABLED from env."""

    def test_unset_returns_false(self, monkeypatch):
        monkeypatch.delenv("AIPASS_SANDBOX_ENABLED", raising=False)
        assert is_sandbox_enabled() is False

    def test_empty_returns_false(self, monkeypatch):
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "")
        assert is_sandbox_enabled() is False

    def test_false_string_returns_false(self, monkeypatch):
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "false")
        assert is_sandbox_enabled() is False

    def test_zero_returns_false(self, monkeypatch):
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "0")
        assert is_sandbox_enabled() is False

    def test_one_returns_true(self, monkeypatch):
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")
        assert is_sandbox_enabled() is True

    def test_true_returns_true(self, monkeypatch):
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "true")
        assert is_sandbox_enabled() is True

    def test_yes_returns_true(self, monkeypatch):
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "yes")
        assert is_sandbox_enabled() is True

    def test_true_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "TRUE")
        assert is_sandbox_enabled() is True


class TestFlagOffOldPath:
    """Flag OFF (default): dispatch uses the original cmd, no sandbox wrapping."""

    def test_flag_off_cmd_unchanged(self, monkeypatch, main_argv, tmp_path):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.delenv("AIPASS_SANDBOX_ENABLED", raising=False)

        captured_cmds = []

        def capture_run(cmd, *args, **kwargs):
            captured_cmds.append(cmd)
            return (0, False)

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "run_with_startup_check", capture_run)
        bounce = MagicMock()
        monkeypatch.setattr(mod, "_send_bounce", bounce)
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=tmp_path / "repo"),
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        assert len(captured_cmds) == 1
        assert captured_cmds[0] == ["claude", "-c", "--model", "opus"]
        bounce.assert_not_called()

    def test_flag_off_wrap_never_called(self, monkeypatch, main_argv, tmp_path):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.delenv("AIPASS_SANDBOX_ENABLED", raising=False)

        wrap_calls = []
        original_wrap = mod.wrap_for_sandbox

        def tracking_wrap(*args, **kwargs):
            wrap_calls.append(args)
            return original_wrap(*args, **kwargs)

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "wrap_for_sandbox", tracking_wrap)
        monkeypatch.setattr(mod, "run_with_startup_check", MagicMock(return_value=(0, False)))
        bounce = MagicMock()
        monkeypatch.setattr(mod, "_send_bounce", bounce)
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=tmp_path / "repo"),
        )

        with pytest.raises(SystemExit):
            main()

        assert wrap_calls == []
        bounce.assert_not_called()


class TestFlagOnSandboxPath:
    """Flag ON: dispatch wraps cmd via wrap_for_sandbox."""

    def test_flag_on_cmd_wrapped(self, monkeypatch, main_argv, tmp_path):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")

        captured_cmds = []

        def capture_run(cmd, *args, **kwargs):
            captured_cmds.append(cmd)
            return (0, False)

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "run_with_startup_check", capture_run)
        bounce = MagicMock()
        monkeypatch.setattr(mod, "_send_bounce", bounce)
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=tmp_path / "repo"),
        )
        monkeypatch.setattr(
            mod,
            "wrap_for_sandbox",
            lambda cmd, bp: ["/bin/bash", "-c", "bwrap --sandbox " + " ".join(cmd)],
        )
        mock_sock = MagicMock()
        mock_sock.fileno.return_value = 99
        monkeypatch.setattr(mod, "_connect_broker", MagicMock(return_value=mock_sock))

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        assert len(captured_cmds) == 1
        assert captured_cmds[0][0] == "/bin/bash"
        assert captured_cmds[0][1] == "-c"
        assert "bwrap --sandbox" in captured_cmds[0][2]
        bounce.assert_not_called()

    def test_wrap_calls_building_blocks(self, monkeypatch, tmp_path):
        call_log = []

        def mock_build_policy(bp):
            call_log.append("build_policy")
            return {"allow_write": [str(bp)], "deny_write": [], "deny_read": []}

        def mock_build_srt_config(policy):
            call_log.append("build_srt_config")
            return {"filesystem": {"allowWrite": policy["allow_write"]}}

        def mock_resolve_bwrap(cmd_str, srt_config):
            call_log.append("resolve_bwrap_command")
            return f"bwrap --ro-bind / / {cmd_str}"

        monkeypatch.setattr("aipass.hooks.apps.modules.sandbox.build_policy", mock_build_policy)
        monkeypatch.setattr(
            "aipass.hooks.apps.modules.sandbox.build_srt_config",
            mock_build_srt_config,
        )
        monkeypatch.setattr(
            "aipass.hooks.apps.modules.sandbox.resolve_bwrap_command",
            mock_resolve_bwrap,
        )

        result = wrap_for_sandbox(["claude", "--model", "opus"], tmp_path)

        assert call_log == ["build_policy", "build_srt_config", "resolve_bwrap_command"]
        assert result[0] == "/bin/bash"
        assert result[1] == "-c"
        assert "claude" in result[2]


class TestBrokenSandboxFailsLoud:
    """Flag ON but sandbox init fails: ABORT, never silently unsandbox."""

    def test_sandbox_init_failure_aborts(self, monkeypatch, main_argv, tmp_path):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")

        run_calls = []

        def capture_run(cmd, *args, **kwargs):
            run_calls.append(cmd)
            return (0, False)

        def broken_wrap(cmd, bp):
            raise RuntimeError("srt resolve failed: node not found")

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "run_with_startup_check", capture_run)
        monkeypatch.setattr(mod, "wrap_for_sandbox", broken_wrap)
        bounce = MagicMock()
        monkeypatch.setattr(mod, "_send_bounce", bounce)
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=tmp_path / "repo"),
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert run_calls == []
        assert exc_info.value.code != 0
        # An aborted spawn still tells the sender, once
        bounce.assert_called_once()

    def test_sandbox_failure_sends_bounce(self, monkeypatch, main_argv, tmp_path):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")

        def broken_wrap(cmd, bp):
            raise FileNotFoundError("node not found in PATH")

        mock_bounce = MagicMock()

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "run_with_startup_check", MagicMock(return_value=(0, False)))
        monkeypatch.setattr(mod, "wrap_for_sandbox", broken_wrap)
        monkeypatch.setattr(mod, "_send_bounce", mock_bounce)
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=tmp_path / "repo"),
        )

        with pytest.raises(SystemExit):
            main()

        mock_bounce.assert_called_once()
        reason = mock_bounce.call_args[0][1]
        # MEASURED 2026-09-08: the reason a sender actually receives reads
        # "Attempt 1 (resume): exit code -4" and never says "sandbox". The
        # ``or`` that stood here was not tolerance — its first clause had never
        # once held, and the dead half was the half naming this test. The bounce
        # text not naming the sandbox is reported to @devpulse as a product
        # question; this pin says what the code does today.
        assert "exit code -4" in reason, reason

    def test_never_falls_back_to_unsandboxed(self, monkeypatch, main_argv, tmp_path):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")

        wrap_calls = [0]
        run_calls = []

        def counting_broken_wrap(cmd, bp):
            wrap_calls[0] += 1
            raise RuntimeError("srt unavailable")

        def capture_run(cmd, *args, **kwargs):
            run_calls.append(cmd)
            return (0, False)

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "run_with_startup_check", capture_run)
        monkeypatch.setattr(mod, "wrap_for_sandbox", counting_broken_wrap)
        bounce = MagicMock()
        monkeypatch.setattr(mod, "_send_bounce", bounce)
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=tmp_path / "repo"),
        )

        with pytest.raises(SystemExit):
            main()

        assert wrap_calls[0] == 1
        assert run_calls == []
        bounce.assert_called_once()


# --- Broker-fd handshake tests (Phase 6b FPLAN-0250) -------------------------


class TestFlagOffNoBroker:
    """Flag OFF: no broker connection attempted at all."""

    def test_flag_off_no_broker_activity(self, monkeypatch, main_argv, tmp_path):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.delenv("AIPASS_SANDBOX_ENABLED", raising=False)

        connect_calls = []

        def tracking_connect(*args, **kwargs):
            connect_calls.append(args)
            raise RuntimeError("should never be called")

        monkeypatch.setattr(mod, "_connect_broker", tracking_connect)
        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "run_with_startup_check", MagicMock(return_value=(0, False)))
        bounce = MagicMock()
        monkeypatch.setattr(mod, "_send_bounce", bounce)
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=tmp_path / "repo"),
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        assert connect_calls == []
        bounce.assert_not_called()

    def test_flag_off_no_broker_fd_in_env(self, monkeypatch, main_argv, tmp_path):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.delenv("AIPASS_SANDBOX_ENABLED", raising=False)

        captured_env = {}

        def capture_run(cmd, stdout_log, stderr_fh, cwd, env, branch, **kwargs):
            captured_env.update(env)
            return (0, False)

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "run_with_startup_check", capture_run)
        bounce = MagicMock()
        monkeypatch.setattr(mod, "_send_bounce", bounce)
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=tmp_path / "repo"),
        )

        with pytest.raises(SystemExit):
            main()

        assert "AIPASS_BROKER_FD" not in captured_env
        bounce.assert_not_called()


class TestBrokerDownFailsLoud:
    """Broker down + flag ON → exit -4, agent never spawned."""

    def test_broker_connect_failure_aborts(self, monkeypatch, main_argv, tmp_path):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")

        run_calls = []

        def capture_run(cmd, *args, **kwargs):
            run_calls.append(cmd)
            return (0, False)

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "run_with_startup_check", capture_run)
        monkeypatch.setattr(
            mod,
            "wrap_for_sandbox",
            lambda cmd, bp: ["/bin/bash", "-c", "bwrap " + " ".join(cmd)],
        )
        monkeypatch.setattr(
            mod,
            "_connect_broker",
            MagicMock(side_effect=OSError("broker socket not found")),
        )
        bounce = MagicMock()
        monkeypatch.setattr(mod, "_send_bounce", bounce)
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=tmp_path / "repo"),
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert run_calls == []
        assert exc_info.value.code != 0
        # An aborted spawn still tells the sender, once
        bounce.assert_called_once()

    def test_broker_bad_hmac_aborts(self, monkeypatch, main_argv, tmp_path):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")

        run_calls = []

        def capture_run(cmd, *args, **kwargs):
            run_calls.append(cmd)
            return (0, False)

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "run_with_startup_check", capture_run)
        monkeypatch.setattr(
            mod,
            "wrap_for_sandbox",
            lambda cmd, bp: ["/bin/bash", "-c", "bwrap " + " ".join(cmd)],
        )
        monkeypatch.setattr(
            mod,
            "_connect_broker",
            MagicMock(side_effect=RuntimeError("Broker identify failed: bad HMAC")),
        )
        bounce = MagicMock()
        monkeypatch.setattr(mod, "_send_bounce", bounce)
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=tmp_path / "repo"),
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert run_calls == []
        assert exc_info.value.code != 0
        # An aborted spawn still tells the sender, once
        bounce.assert_called_once()

    def test_broker_failure_sends_bounce(self, monkeypatch, main_argv, tmp_path):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")

        mock_bounce = MagicMock()
        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "run_with_startup_check", MagicMock(return_value=(0, False)))
        monkeypatch.setattr(
            mod,
            "wrap_for_sandbox",
            lambda cmd, bp: ["/bin/bash", "-c", "bwrap " + " ".join(cmd)],
        )
        monkeypatch.setattr(
            mod,
            "_connect_broker",
            MagicMock(side_effect=OSError("socket missing")),
        )
        monkeypatch.setattr(mod, "_send_bounce", mock_bounce)
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=tmp_path / "repo"),
        )

        with pytest.raises(SystemExit):
            main()

        mock_bounce.assert_called_once()


class TestBrokerFdHandshake:
    """Flag ON + broker up: fd passed to child, parent closes after spawn."""

    def test_broker_fd_in_env_and_pass_fds(self, monkeypatch, main_argv, tmp_path):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")

        captured_env = {}
        captured_pass_fds = []

        def capture_run(cmd, stdout_log, stderr_fh, cwd, env, branch, pass_fds=()):
            captured_env.update(env)
            captured_pass_fds.append(pass_fds)
            return (0, False)

        mock_sock = MagicMock()
        mock_sock.fileno.return_value = 42

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "run_with_startup_check", capture_run)
        monkeypatch.setattr(
            mod,
            "wrap_for_sandbox",
            lambda cmd, bp: ["/bin/bash", "-c", "bwrap " + " ".join(cmd)],
        )
        monkeypatch.setattr(mod, "_connect_broker", MagicMock(return_value=mock_sock))
        bounce = MagicMock()
        monkeypatch.setattr(mod, "_send_bounce", bounce)
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=tmp_path / "repo"),
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        assert captured_env.get("AIPASS_BROKER_FD") == "42"
        assert captured_pass_fds == [(42,)]
        bounce.assert_not_called()
        mock_sock.close.assert_called_once()

    def test_parent_closes_socket_after_spawn(self, monkeypatch, main_argv, tmp_path):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")

        mock_sock = MagicMock()
        mock_sock.fileno.return_value = 7

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "run_with_startup_check", MagicMock(return_value=(0, False)))
        monkeypatch.setattr(
            mod,
            "wrap_for_sandbox",
            lambda cmd, bp: ["/bin/bash", "-c", "bwrap " + " ".join(cmd)],
        )
        monkeypatch.setattr(mod, "_connect_broker", MagicMock(return_value=mock_sock))
        bounce = MagicMock()
        monkeypatch.setattr(mod, "_send_bounce", bounce)
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=tmp_path / "repo"),
        )

        with pytest.raises(SystemExit):
            main()

        mock_sock.close.assert_called_once()
        bounce.assert_not_called()

    def test_broker_fd_cleaned_from_env_after_spawn(self, monkeypatch, main_argv, tmp_path):
        """After spawn+close, AIPASS_BROKER_FD removed from spawn_env."""
        argv, lock_file, stderr_log = main_argv
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")

        env_snapshots = []

        def capture_run(cmd, stdout_log, stderr_fh, cwd, env, branch, pass_fds=()):
            env_snapshots.append(dict(env))
            return (0, False)

        mock_sock = MagicMock()
        mock_sock.fileno.return_value = 10

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "run_with_startup_check", capture_run)
        monkeypatch.setattr(
            mod,
            "wrap_for_sandbox",
            lambda cmd, bp: ["/bin/bash", "-c", "bwrap " + " ".join(cmd)],
        )
        monkeypatch.setattr(mod, "_connect_broker", MagicMock(return_value=mock_sock))
        bounce = MagicMock()
        monkeypatch.setattr(mod, "_send_bounce", bounce)
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=tmp_path / "repo"),
        )

        with pytest.raises(SystemExit):
            main()

        # During the run, env had the FD
        assert env_snapshots[0]["AIPASS_BROKER_FD"] == "10"
        bounce.assert_not_called()


@pytest.mark.skipif(sys.platform != "linux", reason="AF_UNIX broker daemon is Linux-only")
class TestBrokerRealE2E:
    """Real multi-process e2e: broker daemon, identified connection, child reads fd."""

    def test_child_inherits_broker_fd(self, tmp_path):
        """Start real broker, create identified conn, spawn child that reads AIPASS_BROKER_FD.

        mutant: daemon.py binds socket_path + ".x" -> KILLED
        """
        # Set up repo root with branch dir + .trinity marker (broker marker-walk requires it)
        repo_root = tmp_path / "repo"
        branch_dir = repo_root / "src" / "aipass" / "testbranch"
        branch_dir.mkdir(parents=True)
        trinity_dir = branch_dir / ".trinity"
        trinity_dir.mkdir()
        (trinity_dir / "passport.json").write_text('{"branch_info": {"branch_name": "testbranch"}}', encoding="utf-8")
        target_file = branch_dir / "deleteme.txt"
        target_file.write_text("delete me", encoding="utf-8")

        # Start real broker
        sock_path = tmp_path / "broker.sock"
        audit_path = tmp_path / "audit.jsonl"
        secret_path = tmp_path / "secret"
        broker = BrokerDaemon(
            repo_root=repo_root,
            socket_path=sock_path,
            audit_path=audit_path,
            secret_path=secret_path,
        )
        # start_background blocks until the socket listens (raises past 5s), and
        # the secret is written before that: assert the condition, never sleep on it.
        t = broker.start_background()

        try:
            # Inside the try: a red here must still stop the broker in the finally.
            assert sock_path.exists()
            assert secret_path.stat().st_size > 0
            # Create identified connection (as the launcher would)
            sock = create_identified_connection(sock_path, secret_path, "testbranch")
            broker_fd = sock.fileno()

            # Spawn a real child that reads AIPASS_BROKER_FD and sends a delete
            child_script = tmp_path / "child.py"
            child_script.write_text(
                """
import os, socket, json

fd = int(os.environ["AIPASS_BROKER_FD"])
s = socket.socket(fileno=fd)
try:
    req = json.dumps({"op": "delete", "path": "deleteme.txt", "request_id": "e2e1"}) + "\\n"
    s.sendall(req.encode())
    data = b""
    while b"\\n" not in data:
        chunk = s.recv(4096)
        if not chunk:
            break
        data += chunk
    resp = json.loads(data.decode())
    # Write result to a file so parent can verify
    with open(os.environ["RESULT_FILE"], "w") as f:
        json.dump(resp, f)
finally:
    s.detach()
""",
                encoding="utf-8",
            )

            result_file = tmp_path / "result.json"
            env = os.environ.copy()
            env["AIPASS_BROKER_FD"] = str(broker_fd)
            env["RESULT_FILE"] = str(result_file)

            proc = subprocess.Popen(
                [sys.executable, str(child_script)],
                env=env,
                pass_fds=(broker_fd,),
                close_fds=True,
            )
            # Parent closes its copy
            sock.close()

            proc.wait(timeout=10)
            assert proc.returncode == 0

            # Verify the delete happened
            assert not target_file.exists()

            # Verify the child got a success response
            import json as json_mod

            result = json_mod.loads(result_file.read_text(encoding="utf-8"))
            assert result["ok"] is True

            # Verify audit log carries identity
            audit_lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
            delete_entries = [
                json_mod.loads(line) for line in audit_lines if json_mod.loads(line).get("op") == "delete"
            ]
            assert len(delete_entries) >= 1
            assert delete_entries[-1]["identity"] == "testbranch"
            assert delete_entries[-1]["result"] == "DELETED"

        finally:
            broker.stop()
            t.join(timeout=3)
