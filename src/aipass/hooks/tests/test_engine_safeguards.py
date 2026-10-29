# =================== AIPass ====================
# Name: test_engine_safeguards.py
# Description: The hook engine's safeguards: trust, timeouts, one document, the ledger, fail-closed gates, promote
# Version: 1.2.0
# Created: 2026-10-08
# Modified: 2026-10-28
# =============================================

"""Tests for apps/modules/engine.py: trust, timeouts, the ledger and the fail-closed gates."""

# Layer A trust enforcement, handler timeouts at the runner and at dispatch, the
# JSONL log, one document per event, the injection ledger, the fail-closed gates,
# the bridge that refuses when the engine cannot load, promote and mount. The
# dispatcher core is test_engine.py; contracts and resilience are
# test_engine_contracts.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that engine.py parses and imports, ruff and collection cover it

import importlib
import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.hooks.apps.modules import engine, injection_ledger, promote
from aipass.hooks.apps.modules.engine import dispatch
from aipass.hooks.apps.handlers.config.diagnostics import LOG_FILE
from aipass.hooks.apps.handlers.config.output_merge import CONTEXT_LIMIT
from aipass.hooks.apps.handlers.config.gates import FAIL_CLOSED
from aipass.hooks.apps.handlers.config import loader
from aipass.hooks.apps.handlers.config.loader import find_project_config
from aipass.hooks.apps.handlers.config.trust_registry import REGISTRY_ENV, enroll
from aipass.hooks.tests.support_engine import _GATE, _one

pytestmark = pytest.mark.usefixtures("_no_real_trust_banners")

_FAKE = "aipass.hooks.apps.handlers.fake.handle"


def _dispatch_handler(handle, handler: str = _FAKE, timeout: int | None = None):
    """Dispatch one handler hook whose module is `handle`; answer (result, logged entries, importer)."""
    hook = {"enabled": True, "handler": handler, "matcher": ""}
    if timeout is not None:
        hook["timeout"] = timeout
    module = MagicMock()
    module.handle = handle
    with (
        patch("aipass.hooks.apps.modules.engine._log") as log,
        patch("aipass.hooks.apps.modules.engine._import_handler_module", return_value=module) as importer,
        patch("aipass.hooks.apps.sound.speak"),
    ):
        result = dispatch("UserPromptSubmit", "{}", {"hooks_enabled": True, "UserPromptSubmit": {"h": hook}})
    return result, [c.args[0] for c in log.call_args_list], importer


def _hook_entry(entries: list) -> dict:
    (entry,) = [e for e in entries if e.get("hook") == "h"]
    return entry


class TestLayerATrustEnforcement:
    """DPLAN-0244 Layer A: engine refuses command-type from project config, enforces handler namespace."""

    def test_command_type_refused_from_project_config(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "_source": "project",
            "PreToolUse": {
                "evil_cmd": {
                    "enabled": True,
                    "command": "echo PWNED",
                    "matcher": "",
                }
            },
        }
        with patch("aipass.hooks.apps.modules.engine._log") as mock_log:
            with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
                result = dispatch("PreToolUse", '{"tool_name":"Edit"}', config)
        mock_run.assert_not_called()
        assert result == ("", 0)
        log_calls = [c[0][0] for c in mock_log.call_args_list]
        refused = [(e["event"], e["hook"]) for e in log_calls if e.get("action") == "refused_command_type"]
        assert refused == [("PreToolUse", "evil_cmd")]

    def test_a_named_hook_call_keeps_the_project_source(self, mock_logger):
        """claude.py Event:name cuts one hook out of the config: it is still the project's, still refused."""
        config = {
            "hooks_enabled": True,
            "_source": "project",
            "UserPromptSubmit": {"evil_cmd": {"enabled": True, "command": "echo PWNED", "matcher": ""}},
        }
        with (
            patch("aipass.hooks.apps.handlers.config.loader.resolve_config", return_value=config),
            patch("aipass.hooks.apps.modules.engine._log") as mock_log,
            patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run,
        ):
            engine.run_event("UserPromptSubmit:evil_cmd", "{}")
        mock_run.assert_not_called()
        actions = [c[0][0].get("action") for c in mock_log.call_args_list]
        assert "refused_command_type" in actions

    def test_a_named_hook_call_keeps_the_master_switch(self, mock_logger):
        config = {"hooks_enabled": False, "UserPromptSubmit": {"the_hook": {"enabled": True, "handler": "x.handle"}}}
        with (
            patch("aipass.hooks.apps.handlers.config.loader.resolve_config", return_value=config),
            patch("aipass.hooks.apps.modules.engine._log") as mock_log,
            patch("aipass.hooks.apps.modules.engine._run_handler") as mock_run,
        ):
            engine.run_event("UserPromptSubmit:the_hook", "{}")
        mock_run.assert_not_called()
        assert "hooks_disabled_gates_run" in [c[0][0].get("action") for c in mock_log.call_args_list]

    def test_handler_namespace_enforced_before_any_import(self, mock_logger):
        handle = MagicMock(return_value={"stdout": "PWNED"})
        result, entries, importer = _dispatch_handler(handle, handler="evil.payload.handle")
        assert result == ("", 0)
        importer.assert_not_called()
        entry = _hook_entry(entries)
        assert entry["exit_code"] == -1
        assert "namespace refused" in entry["stderr_preview"]

    def test_handler_aipass_namespace_allowed(self, mock_logger):
        handle = MagicMock(return_value={"exit_code": 0, "stdout": "ok"})
        result, entries, _ = _dispatch_handler(
            handle, handler="aipass.hooks.apps.handlers.notification.stop_sound.handle"
        )
        assert result == ("ok", 0)
        assert _hook_entry(entries)["exit_code"] == 0

    def test_command_type_allowed_from_default_config(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "_source": "default",
            "Stop": {
                "cmd_hook": {
                    "enabled": True,
                    "command": "echo allowed",
                    "matcher": "",
                }
            },
        }
        with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
            mock_run.return_value = {
                "exit_code": 0,
                "stdout": "allowed",
                "stderr": "",
                "elapsed_ms": 5,
            }
            result = dispatch("Stop", "{}", config)
        mock_run.assert_called_once()
        assert mock_run.call_args.args[:2] == ("echo allowed", "{}")
        assert "allowed" in result[0]

    def test_mixed_config_partial_refusal(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "_source": "project",
            "UserPromptSubmit": {
                "good_handler": {
                    "enabled": True,
                    "handler": "aipass.hooks.apps.handlers.notification.stop_sound.handle",
                    "matcher": "",
                },
                "evil_cmd": {
                    "enabled": True,
                    "command": "echo PWNED",
                    "matcher": "",
                },
            },
        }
        mock_handler_func = MagicMock(return_value={"exit_code": 0, "stdout": "handler_ok"})
        mock_module = MagicMock()
        mock_module.handle = mock_handler_func
        with patch("aipass.hooks.apps.modules.engine._import_handler_module", return_value=mock_module):
            with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
                result = dispatch("UserPromptSubmit", "{}", config)
        mock_run.assert_not_called()
        assert "handler_ok" in result[0]
        assert result[1] == 0

    def test_source_overwrite_not_merge(self, temp_test_dir, mock_logger):
        config_dir = temp_test_dir / ".aipass"
        config_dir.mkdir()
        hostile_config = {
            "hooks_enabled": True,
            "_source": "provider",
            "SessionStart": {
                "evil": {
                    "enabled": True,
                    "command": "echo PWNED",
                    "matcher": "",
                }
            },
        }
        (config_dir / "hooks.json").write_text(json.dumps(hostile_config), encoding="utf-8")
        reg_path = temp_test_dir / "registry.json"
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(temp_test_dir))
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch(
                "aipass.hooks.apps.handlers.config.loader._search_bounds",
                return_value=(temp_test_dir, temp_test_dir.parent),
            ),
        ):
            loaded = find_project_config()
        assert loaded is not None
        assert loaded["_source"] == "project"
        with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
            result = dispatch("SessionStart", "{}", loaded)
        mock_run.assert_not_called()
        assert result == ("", 0)

    def test_command_without_source_defaults_allowed(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "Stop": {
                "cmd_hook": {
                    "enabled": True,
                    "command": "echo ok",
                    "matcher": "",
                }
            },
        }
        with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
            mock_run.return_value = {
                "exit_code": 0,
                "stdout": "ok",
                "stderr": "",
                "elapsed_ms": 5,
            }
            result = dispatch("Stop", "{}", config)
        mock_run.assert_called_once()
        assert mock_run.call_args.args[:2] == ("echo ok", "{}")
        assert "ok" in result[0]


_NS = "fplan_ns_probe"


@pytest.fixture
def ns_project(temp_test_dir, monkeypatch):
    """A project outside AIPASS_HOME declaring handler_namespace, its package in src/, a fixture trust registry."""
    package = temp_test_dir / "src" / _NS
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "events.py").write_text(
        "def record(hook_data):\n    return {'exit_code': 0, 'stdout': 'from the project'}\n", encoding="utf-8"
    )
    hook = {"enabled": True, "handler": f"{_NS}.events.record", "matcher": ""}
    config = {"hooks_enabled": True, "handler_namespace": _NS, "Stop": {"record": hook}}
    (temp_test_dir / ".aipass").mkdir()
    (temp_test_dir / ".aipass" / "hooks.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv(REGISTRY_ENV, str(temp_test_dir / "registry.json"))
    monkeypatch.delitem(sys.modules, _NS, raising=False)
    monkeypatch.delitem(sys.modules, f"{_NS}.events", raising=False)
    with (
        patch.object(loader, "_search_bounds", return_value=(temp_test_dir, temp_test_dir.parent)),
        patch.object(loader, "aipass_home", return_value=None),
        patch.object(loader, "logger") as log,
    ):
        yield temp_test_dir, log


def _warned(log) -> str:
    return " ".join(c.args[0] % c.args[1:] for c in log.warning.call_args_list)


class TestTrustedHandlerNamespace:
    """A trusted project's own handler package: enrolled + hash match, src/ appended for the import only."""

    def test_accepted_when_enrolled_and_the_hash_matches(self, ns_project, mock_logger):
        project, _ = ns_project
        enroll(str(project))
        config = find_project_config()
        assert config["_handler_namespace"] == _NS
        assert config["_project_src"] == str(project / "src")
        with patch("aipass.hooks.apps.modules.engine._log") as log:
            assert dispatch("Stop", "{}", config) == ("from the project", 0)
        assert [e["exit_code"] for e in (c.args[0] for c in log.call_args_list) if e.get("hook") == "record"] == [0]
        assert str(project / "src") not in sys.path

    def test_refused_when_unenrolled_naming_the_cure(self, ns_project):
        project, log = ns_project
        assert find_project_config() is None
        assert f"aipass trust {project}" in _warned(log)

    def test_refused_when_the_hash_is_stale(self, ns_project):
        project, _ = ns_project
        enroll(str(project))
        hooks_json = project / ".aipass" / "hooks.json"
        hooks_json.write_text(hooks_json.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        assert find_project_config() is None

    def test_no_key_means_aipass_only(self, ns_project, mock_logger):
        project, _ = ns_project
        hooks_json = project / ".aipass" / "hooks.json"
        config = json.loads(hooks_json.read_text(encoding="utf-8"))
        del config["handler_namespace"]
        hooks_json.write_text(json.dumps(config), encoding="utf-8")
        enroll(str(project))
        loaded = find_project_config()
        assert "_handler_namespace" not in loaded
        result, entries, importer = _dispatch_handler(MagicMock(), handler=f"{_NS}.events.record")
        importer.assert_not_called()
        assert "namespace refused" in _hook_entry(entries)["stderr_preview"]

    def test_a_config_cannot_forge_the_stamps(self, ns_project):
        project, _ = ns_project
        hooks_json = project / ".aipass" / "hooks.json"
        config = json.loads(hooks_json.read_text(encoding="utf-8"))
        del config["handler_namespace"]
        config.update({"_handler_namespace": "evil", "_project_src": "/evil"})
        hooks_json.write_text(json.dumps(config), encoding="utf-8")
        enroll(str(project))
        loaded = find_project_config()
        assert "_handler_namespace" not in loaded and "_project_src" not in loaded

    @pytest.mark.parametrize("namespace", ["aipass", "a.b", "", 7])
    def test_a_namespace_that_could_shadow_is_refused(self, ns_project, namespace):
        project, log = ns_project
        hooks_json = project / ".aipass" / "hooks.json"
        config = json.loads(hooks_json.read_text(encoding="utf-8"))
        config["handler_namespace"] = namespace
        hooks_json.write_text(json.dumps(config), encoding="utf-8")
        enroll(str(project))
        assert "_handler_namespace" not in find_project_config()
        assert "refused" in _warned(log)

    def test_aipass_root_config_never_takes_a_namespace(self, ns_project):
        project, log = ns_project
        with patch.object(loader, "locate_config", return_value=(loader.AIPASS, project)):
            assert "_handler_namespace" not in find_project_config()
        assert "aipass.* only" in _warned(log)

    def test_src_is_appended_never_prepended(self, tmp_path, mock_logger):
        src = str(tmp_path / "src")
        seen = []
        module = MagicMock()
        module.record = MagicMock(return_value={"exit_code": 0, "stdout": "ok"})
        with patch.object(engine, "_import_handler_module", side_effect=lambda _: seen.append(sys.path[-1]) or module):
            result, _ = _dispatch_stamped(f"{_NS}.events.record", src)
        assert (result, seen) == ("ok", [src])
        assert src not in sys.path

    def test_another_namespace_is_refused(self, tmp_path, mock_logger):
        with patch.object(engine, "_import_handler_module") as importer:
            _, entries = _dispatch_stamped("other.events.record", str(tmp_path / "src"))
        importer.assert_not_called()
        assert "namespace refused" in _hook_entry(entries)["stderr_preview"]

    def test_command_rows_still_refused(self, tmp_path, mock_logger):
        row = {"enabled": True, "command": "echo PWNED", "matcher": ""}
        with patch.object(engine, "_run_hook") as run_hook:
            result, entries = _dispatch_stamped("", str(tmp_path / "src"), row=row)
        assert result == ""
        run_hook.assert_not_called()
        assert [e["action"] for e in entries if e.get("hook") == "h"] == ["refused_command_type"]


def _dispatch_stamped(handler: str, src: str, row: dict | None = None):
    """Dispatch one Stop row under a trusted project's stamps; answer (stdout, logged entries)."""
    config = {
        "hooks_enabled": True,
        "_source": "project",
        "_handler_namespace": _NS,
        "_project_src": src,
        "Stop": {"h": row or {"enabled": True, "handler": handler, "matcher": ""}},
    }
    with patch.object(engine, "_log") as log:
        result, _ = dispatch("Stop", "{}", config)
    return result, [c.args[0] for c in log.call_args_list]


class TestRunHandlerTimeout:
    """DPLAN-0256 backlog #1: handler-type hooks had no engine-side timeout — a hung
    handler could stall the whole event. _run_handler now runs the handler on a
    daemon thread and joins with a timeout instead of calling it inline."""

    def test_handler_completes_within_timeout(self, mock_logger):
        handle = MagicMock(return_value={"exit_code": 0, "stdout": "ok"})
        result, entries, _ = _dispatch_handler(handle, timeout=1)
        assert result == ("ok", 0)
        assert not [e for e in entries if e.get("action") == "timeout"]

    def test_handler_exceeding_timeout_returns_timeout_marker(self, mock_logger):
        import threading

        released = threading.Event()

        def _slow_handler(_data):
            released.wait(10)  # held until the test has its answer: past any timeout, without a sleep
            return {"exit_code": 0, "stdout": "too late"}

        result, entries, _ = _dispatch_handler(_slow_handler, timeout=1)
        released.set()
        assert result == ("", 0)
        assert [e["hook"] for e in entries if e.get("action") == "timeout"] == ["h"]

    def test_handler_timeout_does_not_block_caller(self, mock_logger):
        """Regression: the caller must return promptly even if the handler thread never finishes."""
        import threading
        import time as time_module

        released = threading.Event()

        def _hangs_much_longer_than_timeout(_data):
            released.wait(30)  # never finishes while the caller is measured
            return {"exit_code": 0, "stdout": "should never see this"}

        start = time_module.monotonic()
        result, entries, _ = _dispatch_handler(_hangs_much_longer_than_timeout, timeout=1)
        elapsed = time_module.monotonic() - start
        released.set()
        assert elapsed < 2.0
        assert result == ("", 0)
        assert [e["hook"] for e in entries if e.get("action") == "timeout"] == ["h"]

    def test_handler_exception_still_surfaces_as_error_not_timeout(self, mock_logger):
        def _boom(_data):
            raise RuntimeError("handler blew up")

        result, entries, _ = _dispatch_handler(_boom, timeout=1)
        assert result == ("", 0)
        entry = _hook_entry(entries)
        assert entry["exit_code"] == -1
        assert "handler blew up" in entry["stderr_preview"]
        assert not [e for e in entries if e.get("action") == "timeout"]


class TestDispatchHandlerTimeout:
    """Dispatch-level wiring for DPLAN-0256 backlog #1 — hooks.json timeout fields
    are honored for handler-type hooks, a sane default applies when absent, and a
    timeout fails loud (log + sound) without ever silently swallowing or stalling
    the rest of the event."""

    def test_handler_timeout_propagates_hook_def_value(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "UserPromptSubmit": {
                "slow_handler": {
                    "enabled": True,
                    "handler": "aipass.hooks.apps.handlers.fake.handle",
                    "matcher": "",
                    "timeout": 5,
                }
            },
        }
        with (
            patch("aipass.hooks.apps.modules.engine._run_handler") as mock_run,
        ):
            mock_run.return_value = {"exit_code": 0, "stdout": "ok", "stderr": "", "elapsed_ms": 5}
            dispatch("UserPromptSubmit", "{}", config)
        mock_run.assert_called_once_with("aipass.hooks.apps.handlers.fake.handle", {}, timeout_s=5)

    def test_handler_default_timeout_is_30_when_unset(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "UserPromptSubmit": {
                "no_timeout_handler": {
                    "enabled": True,
                    "handler": "aipass.hooks.apps.handlers.fake.handle",
                    "matcher": "",
                }
            },
        }
        with (
            patch("aipass.hooks.apps.modules.engine._run_handler") as mock_run,
        ):
            mock_run.return_value = {"exit_code": 0, "stdout": "ok", "stderr": "", "elapsed_ms": 5}
            dispatch("UserPromptSubmit", "{}", config)
        mock_run.assert_called_once_with("aipass.hooks.apps.handlers.fake.handle", {}, timeout_s=30)

    def test_inner_timeout_above_30_reaches_the_join(self, mock_logger):
        """A hooks.json value >30 must survive to worker.join, not be clamped.

        The 30s stopgap raise is worthless if anything downstream caps it — DPLAN-0285's
        "both knobs or it is theatre". This pins the inner half.
        """
        config = {
            "hooks_enabled": True,
            "UserPromptSubmit": {
                "slow_handler": {
                    "enabled": True,
                    "handler": "aipass.hooks.apps.handlers.fake.handle",
                    "matcher": "",
                    "timeout": 90,
                }
            },
        }
        with (
            patch("aipass.hooks.apps.modules.engine._run_handler") as mock_run,
        ):
            mock_run.return_value = {"exit_code": 0, "stdout": "ok", "stderr": "", "elapsed_ms": 5}
            dispatch("UserPromptSubmit", "{}", config)
        mock_run.assert_called_once_with("aipass.hooks.apps.handlers.fake.handle", {}, timeout_s=90)

    def test_timeout_logs_speaks_and_lets_dispatch_continue(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "UserPromptSubmit": {
                "hung_handler": {
                    "enabled": True,
                    "handler": "aipass.hooks.apps.handlers.fake.handle",
                    "matcher": "",
                },
                "next_handler": {
                    "enabled": True,
                    "handler": "aipass.hooks.apps.handlers.fake2.handle",
                    "matcher": "",
                },
            },
        }
        with (
            patch("aipass.hooks.apps.modules.engine._log") as mock_log,
            patch("aipass.hooks.apps.modules.engine._run_handler") as mock_run,
            patch("aipass.hooks.apps.sound.speak") as mock_speak,
        ):
            mock_run.side_effect = [
                {"exit_code": -1, "stdout": "", "stderr": "TIMEOUT", "elapsed_ms": 30000},
                {"exit_code": 0, "stdout": "survived", "stderr": "", "elapsed_ms": 5},
            ]
            result = dispatch("UserPromptSubmit", "{}", config)
        assert mock_run.call_count == 2
        assert "survived" in result[0]
        assert result[1] == 0
        mock_speak.assert_called_once()
        log_calls = [c[0][0] for c in mock_log.call_args_list]
        timed_out = [(e["event"], e["hook"]) for e in log_calls if e.get("action") == "timeout"]
        assert timed_out == [("UserPromptSubmit", "hung_handler")]

    def test_timed_out_handler_produces_no_output(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "UserPromptSubmit": {
                "hung_handler": {
                    "enabled": True,
                    "handler": "aipass.hooks.apps.handlers.fake.handle",
                    "matcher": "",
                },
            },
        }
        with (
            patch("aipass.hooks.apps.modules.engine._run_handler") as mock_run,
            patch("aipass.hooks.apps.sound.speak") as mock_speak,
        ):
            mock_run.return_value = {"exit_code": -1, "stdout": "", "stderr": "TIMEOUT", "elapsed_ms": 30000}
            result = dispatch("UserPromptSubmit", "{}", config)
        assert result == ("", 0)
        mock_speak.assert_called_once_with("hung handler timed out")

    def test_command_type_timeout_also_fails_loud(self, mock_logger):
        """The fail-loud path is shared by both hook types — command-type timeouts already
        existed (subprocess timeout=), but were silent past the generic per-hook log line."""
        config = {
            "hooks_enabled": True,
            "PreToolUse": {
                "slow_cmd": {"enabled": True, "command": "sleep 999", "matcher": ""},
            },
        }
        with (
            patch("aipass.hooks.apps.modules.engine._log") as mock_log,
            patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run,
            patch("aipass.hooks.apps.sound.speak") as mock_speak,
        ):
            mock_run.return_value = {"exit_code": -1, "stdout": "", "stderr": "TIMEOUT", "elapsed_ms": 30000}
            result = dispatch("PreToolUse", '{"tool_name":"Edit"}', config)
        assert result == ("", 0)
        mock_speak.assert_called_once()
        log_calls = [c[0][0] for c in mock_log.call_args_list]
        timed_out = [(e["event"], e["hook"]) for e in log_calls if e.get("action") == "timeout"]
        assert timed_out == [("PreToolUse", "slow_cmd")]


class TestJsonHandlerNotApplicable:
    """Hooks uses JSONL logging, not json_handler. These verify the log equivalent."""

    def test_log_default_factory(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "factory.jsonl"
        assert not log_file.exists()
        with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file):
            dispatch("factory_test", "{}", {})
        assert log_file.exists()

    def test_log_validate_json_output(self, temp_test_dir, mock_logger):
        """Two dispatches append two JSON lines, in call order, both readable.

        Was a loop of isinstance over however many lines happened to be there:
        an appender that dropped the second entry, or wrote nothing at all, left
        the loop with one line or zero and the test still green. The count is
        the floor and the event values are the oracle.
        """
        log_file = temp_test_dir / "validate.jsonl"
        with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file):
            dispatch("A", "{}", {})
            dispatch("B", "{}", {})
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert [json.loads(line)["event"] for line in lines] == ["A", "B"]

    def test_log_get_path(self):
        assert LOG_FILE.name == "engine.jsonl"
        assert "logs" in str(LOG_FILE)

    def test_log_ensure_exists(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "new_dir" / "ensure.jsonl"
        with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file):
            dispatch("Stop", "{}", {})
        assert log_file.parent.exists()

    def test_log_save_entry(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "save.jsonl"
        with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file):
            dispatch("Stop", "{}", {})
        entry = json.loads(log_file.read_text(encoding="utf-8").strip())
        assert entry["event"] == "Stop"
        assert entry["action"] == "no_hooks_configured"
        assert isinstance(entry["ts"], float)

    def test_log_load_entry(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "load.jsonl"
        log_file.write_text('{"loaded": true}\n', encoding="utf-8")
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        entry = json.loads(lines[0])
        assert entry["loaded"] is True

    def test_log_operation_recorded(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "ops.jsonl"
        with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file):
            dispatch("PreToolUse", "{}", {})
        entry = json.loads(log_file.read_text(encoding="utf-8").strip())
        assert entry["event"] == "PreToolUse"

    def test_a_hook_that_ran_is_logged_with_its_exit_and_then_the_completion(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "ran.jsonl"
        module = MagicMock()
        module.handle = MagicMock(return_value={"exit_code": 0, "stdout": "ok"})
        with (
            patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file),
            patch("aipass.hooks.apps.modules.engine._import_handler_module", return_value=module),
        ):
            dispatch("PreToolUse", "{}", _one(_FAKE))
        entries = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
        assert [(e.get("hook"), e.get("exit_code"), e.get("action")) for e in entries] == [
            ("the_hook", 0, None),
            (None, None, "complete"),
        ]


# =============================================================================
# One hook output, one document (#752 residue, devpulse bc1bcc45)
#
# Claude Code parses a hook's stdout as ONE document. The engine used to join
# fan-out outputs with a newline, and two JSON objects on two lines are a
# non-blocking hook error with neither applied: four post-compact re-grounds
# were lost that way in the transcripts (devpulse x3, trigger x1), each riding
# an Edit where auto_fix printed {"systemMessage": "[diagnostics] ok"}.
# =============================================================================

_MERGE = "aipass.hooks.apps.handlers.config.output_merge"
_REGROUP = "aipass.hooks.apps.handlers.lifecycle.post_compact_regrounding.handle"
_AUTO_FIX = "aipass.hooks.apps.handlers.lifecycle.auto_fix.handle"


def _post_tool_use(stdouts: dict, event: str = "PostToolUse") -> str:
    """Dispatch *event* through handlers whose stdout is given per handler, in order."""
    handlers = {"auto_fix_diagnostics": _AUTO_FIX, "post_compact_regrounding": _REGROUP, "regroup_renamed": _REGROUP}
    config = {"hooks_enabled": True, event: {}}
    for name in stdouts:
        config[event][name] = {"enabled": True, "handler": handlers[name], "matcher": ""}

    def run(handler, _data, timeout_s=30):
        name = next(n for n in stdouts if handlers[n] == handler)
        return {"exit_code": 0, "stdout": stdouts[name], "stderr": "", "elapsed_ms": 1}

    with (
        patch("aipass.hooks.apps.modules.engine._run_handler", side_effect=run),
    ):
        stdout, code = dispatch(event, '{"tool_name": "Edit"}', config)
    assert code == 0
    return stdout


def _context(text: str) -> str:
    return json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}})


class TestOneDocumentPerEvent:
    def test_two_json_handlers_become_one_object(self, mock_logger):
        """The transcript shape, both contexts delivered, in handler order."""
        outputs = {
            "auto_fix_diagnostics": json.dumps(
                {
                    "systemMessage": "[diagnostics] 1 issue",
                    "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "DIAG"},
                }
            ),
            "post_compact_regrounding": _context("RE-GROUND 1/3"),
        }
        with pytest.raises(json.JSONDecodeError):
            json.loads("\n".join(outputs.values()))  # the old join: what Claude Code could not parse
        doc = json.loads(_post_tool_use(outputs))
        assert doc["hookSpecificOutput"] == {
            "hookEventName": "PostToolUse",
            "additionalContext": "DIAG\n\nRE-GROUND 1/3",
        }
        assert doc["systemMessage"] == "[diagnostics] 1 issue"

    def test_over_the_limit_the_regroup_part_wins_and_the_drop_is_logged(self, mock_logger):
        """auto_fix runs FIRST, so handler order alone would have kept it and cut the re-ground."""
        regroup = "R" * 9000
        outputs = {"auto_fix_diagnostics": _context("D" * 2000), "post_compact_regrounding": _context(regroup)}
        with patch(f"{_MERGE}.logger") as log:
            doc = json.loads(_post_tool_use(outputs))
        context = doc["hookSpecificOutput"]["additionalContext"]
        assert context == regroup
        assert len(context.encode("utf-16-le")) // 2 <= CONTEXT_LIMIT == 10_000
        dropped = [c.args for c in log.warning.call_args_list if "DROPPED" in c.args[0]]
        assert len(dropped) == 1 and dropped[0][2] == "auto_fix_diagnostics" and dropped[0][3] == 2000

    def test_a_total_exactly_at_the_limit_still_lands_whole(self, mock_logger):
        """Claude Code keeps text inline while its length is <= the threshold."""
        outputs = {"auto_fix_diagnostics": _context("D" * 998), "post_compact_regrounding": _context("R" * 9000)}
        doc = json.loads(_post_tool_use(outputs))
        assert doc["hookSpecificOutput"]["additionalContext"] == "D" * 998 + "\n\n" + "R" * 9000

    def test_the_limit_counts_utf16_units(self, mock_logger):
        """An emoji is one Python character and two units to Claude Code."""
        outputs = {
            "auto_fix_diagnostics": _context("\U0001f600" * 600),
            "post_compact_regrounding": _context("R" * 9000),
        }
        doc = json.loads(_post_tool_use(outputs))
        assert doc["hookSpecificOutput"]["additionalContext"] == "R" * 9000

    def test_the_priority_follows_the_handler_not_the_entry_name(self, mock_logger):
        """A project config may name the entry anything; the handler path still identifies the re-ground."""
        regroup = "R" * 9000
        outputs = {"auto_fix_diagnostics": _context("D" * 2000), "regroup_renamed": _context(regroup)}
        assert json.loads(_post_tool_use(outputs))["hookSpecificOutput"]["additionalContext"] == regroup

    def test_a_single_output_passes_through_byte_identical(self, mock_logger):
        """Compact spacing on purpose: a re-serialised document would not match it."""
        raw = '{"systemMessage":"[diagnostics] ok"}\n'
        assert _post_tool_use({"auto_fix_diagnostics": raw}) == raw

    def test_plain_outputs_are_joined_as_before(self, mock_logger):
        assert _post_tool_use({"auto_fix_diagnostics": "A", "post_compact_regrounding": "B"}) == "A\nB"

    def test_plain_text_beside_json_keeps_its_audience(self, mock_logger):
        """Plain PostToolUse stdout is shown to the user, so it rides as systemMessage;
        plain UserPromptSubmit stdout is model context, so it rides as context."""
        doc = json.loads(_post_tool_use({"auto_fix_diagnostics": "note", "post_compact_regrounding": _context("R")}))
        assert doc["systemMessage"] == "note"
        assert doc["hookSpecificOutput"]["additionalContext"] == "R"
        ups = {"auto_fix_diagnostics": "branch prompt", "post_compact_regrounding": _context("R")}
        doc = json.loads(_post_tool_use(ups, event="UserPromptSubmit"))
        assert doc["hookSpecificOutput"] == {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "branch prompt\n\nR",
        }

    def test_a_conflicting_key_keeps_the_first_handlers_value_and_says_so(self, mock_logger):
        outputs = {
            "auto_fix_diagnostics": json.dumps({"decision": "block", "reason": "lint"}),
            "post_compact_regrounding": json.dumps({"decision": "approve", "reason": "other"}),
        }
        with patch(f"{_MERGE}.logger") as log:
            doc = json.loads(_post_tool_use(outputs))
        assert (doc["decision"], doc["reason"]) == ("block", "lint")
        assert sum("conflicts" in c.args[0] for c in log.warning.call_args_list) == 2


_LEDGER = "aipass.hooks.apps.modules.injection_ledger"
_STORE = "aipass.hooks.apps.handlers.config.ledger_store"


class TestInjectionLedger:
    """DPLAN-0347, hooks row 3: what a seat was told at turn N is a record, not a memory.

    Warn-only, so every pin here is about the record being TRUE — grouped by the
    token siblings share, carrying what the merge delivered — and about the
    ledger never costing a dispatch its output.
    """

    @pytest.fixture
    def ledger(self, tmp_path, monkeypatch):
        monkeypatch.setattr(injection_ledger.ledger_store, "_LEDGER_DIR", tmp_path)
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("x" * 321, encoding="utf-8")
        payload = {"session_id": "sess-1", "transcript_path": str(transcript)}
        return injection_ledger, payload

    def test_siblings_of_one_turn_fold_to_one_row_even_when_a_turn_number_lags(self, ledger):
        """temporal never consults cadence, so it can read the previous turn's number."""
        mod, payload = ledger
        for hook, lagging_turn in (("temporal", 4), ("tier0_kernel", 5), ("navmap", 5)):
            with patch("aipass.hooks.apps.modules.cadence.current_turn", return_value=lagging_turn):
                mod.record("UserPromptSubmit", [(hook, "h", f"{hook} text")], f"{hook} text", payload)

        rows = mod.ledger_store.read_turns("sess-1")
        assert len(rows) == 1
        assert rows[0]["token"] == 321 and rows[0]["turn"] == 5
        assert set(rows[0]["hooks"]) == {"temporal", "tier0_kernel", "navmap"}

    def test_a_new_token_is_a_new_row(self, ledger):
        mod, payload = ledger
        mod.record("UserPromptSubmit", [("temporal", "h", "t1")], "t1", payload)
        with open(payload["transcript_path"], "a", encoding="utf-8") as fh:
            fh.write("more")
        mod.record("UserPromptSubmit", [("temporal", "h", "t2")], "t2", payload)
        assert [row["token"] for row in mod.ledger_store.read_turns("sess-1")] == [321, 325]

    def test_plain_tool_event_stdout_is_not_recorded_as_context(self, ledger):
        """Plain PostToolUse stdout goes to the user, not the model."""
        mod, payload = ledger
        assert mod.record("PostToolUse", [("auto_fix", "h", "note")], "note", payload) is None
        assert mod.ledger_store.read_turns("sess-1") == []

    def test_the_record_keeps_what_the_merge_delivered_beside_what_was_produced(self, ledger):
        mod, payload = ledger
        outputs = [
            ("auto_fix_diagnostics", "h", _context("D" * 2000)),
            ("post_compact_regrounding", "h", _context("R" * 9000)),
        ]
        entry = mod.record("PostToolUse", outputs, _context("R" * 9000), payload)
        assert (entry["total"], entry["delivered"]) == (11000, 9000)

    def test_an_injection_over_the_persist_line_warns_and_is_still_recorded(self, ledger):
        mod, payload = ledger
        with patch(f"{_STORE}.logger") as log:
            entry = mod.record("UserPromptSubmit", [("big", "h", "X" * 10_001)], "X" * 10_001, payload)
        assert entry["hooks"]["big"]["chars"] == 10_001
        assert any("persist line" in c.args[0] for c in log.warning.call_args_list)

    def test_a_write_that_fails_warns_and_never_raises(self, ledger, tmp_path, monkeypatch):
        mod, payload = ledger
        monkeypatch.setattr(mod.ledger_store, "_LEDGER_DIR", tmp_path / "no" / "such" / "dir")
        with patch(f"{_STORE}.logger") as log:
            assert mod.record("UserPromptSubmit", [("temporal", "h", "t")], "t", payload) is None
        assert any("NOT written" in c.args[0] for c in log.warning.call_args_list)

    def test_a_session_id_that_is_not_a_filename_writes_nothing(self, ledger, tmp_path):
        """The id becomes a path. With a real directory to climb out of, an
        unchecked id would land a file OUTSIDE the ledger dir — so the pin
        builds that directory first, or it would pass on a failed open."""
        mod, payload = ledger
        (tmp_path / "aipass-ledger-x").mkdir()
        hostile = {**payload, "session_id": "x/../../escaped"}
        assert mod.record("UserPromptSubmit", [("temporal", "h", "t")], "t", hostile) is None
        assert not (tmp_path.parent / "escaped.jsonl").exists()

    def test_the_engine_records_a_dispatch_and_a_ledger_crash_never_costs_the_output(self, ledger, mock_logger):
        mod, payload = ledger
        config = {"hooks_enabled": True, "UserPromptSubmit": {"temporal": {"enabled": True, "handler": "x.handle"}}}
        ran = {"exit_code": 0, "stdout": "Temporal: now", "stderr": "", "elapsed_ms": 1}
        with (
            patch("aipass.hooks.apps.modules.engine._run_handler", return_value=ran),
            patch("aipass.hooks.apps.handlers.config.loader.trust_break_banner", return_value=None),
            patch("aipass.hooks.apps.handlers.config.loader.never_enrolled_banner", return_value=None),
        ):
            assert dispatch("UserPromptSubmit", json.dumps(payload), config) == ("Temporal: now", 0)
            assert mod.ledger_store.read_turns("sess-1")[0]["hooks"]["temporal"]["chars"] == len("Temporal: now")
            with patch(f"{_LEDGER}.record", side_effect=RuntimeError("boom")):
                assert dispatch("UserPromptSubmit", json.dumps(payload), config) == ("Temporal: now", 0)
        assert any("injection_ledger failed" in c.args[0] for c in mock_logger.warning.call_args_list)

    def test_the_verb_prints_one_line_per_turn(self, ledger, capsys):
        mod, payload = ledger
        mod.record("UserPromptSubmit", [("tier0_kernel", "h", "K" * 30)], "K" * 30, payload)
        mod.record("UserPromptSubmit", [("temporal", "h", "T" * 4)], "T" * 4, payload)
        with patch(f"{_LEDGER}.json_handler"):
            assert mod.handle_command("ledger", ["--session", "sess-1"]) is True
        out = capsys.readouterr().out
        assert "1 injection moment(s)" in out
        assert "total=34" in out and "tier0_kernel=30" in out and "temporal=4" in out

    def test_a_harness_wake_is_marked_so_an_audit_can_count_them(self, ledger, capsys):
        """DPLAN-0348: the 33 idle wakes of 09-16 were counted from transcripts. The row says it now."""
        mod, payload = ledger
        wake = {**payload, "prompt": "<task-notification>\n<task-id>b1</task-id>\n</task-notification>"}
        mod.record("UserPromptSubmit", [("temporal", "h", "T")], "T", wake)
        with open(payload["transcript_path"], "a", encoding="utf-8") as fh:
            fh.write("more")
        mod.record("UserPromptSubmit", [("temporal", "h", "T")], "T", {**payload, "prompt": "typed"})

        assert [row.get("automated") for row in mod.ledger_store.read_turns("sess-1")] == [True, False]
        with patch(f"{_LEDGER}.json_handler"):
            mod.handle_command("ledger", ["--session", "sess-1"])
        rows = [line for line in capsys.readouterr().out.splitlines() if "UserPromptSubmit" in line]
        assert "automated" in rows[0] and "automated" not in rows[1]

    def test_last_prints_only_the_newest_moments(self, ledger, capsys):
        """--last N keeps the newest N rows (flag_never_passed, leg 4). Green at once; proof: a mutant."""
        mod, payload = ledger
        mod.record("UserPromptSubmit", [("temporal", "h", "OLD")], "OLD", payload)
        with open(payload["transcript_path"], "a", encoding="utf-8") as fh:
            fh.write("more")
        mod.record("UserPromptSubmit", [("navmap", "h", "NEW")], "NEW", payload)
        with patch(f"{_LEDGER}.json_handler"):
            mod.handle_command("ledger", ["--session", "sess-1", "--last", "1"])
        rows = [line for line in capsys.readouterr().out.splitlines() if "UserPromptSubmit" in line]
        assert len(rows) == 1
        assert "navmap=3" in rows[0]

    def test_a_bare_read_is_the_callers_own_session_even_when_a_neighbour_wrote_last(self, ledger, capsys, monkeypatch):
        """Every citizen has a live session, so the newest ledger is usually someone else's."""
        import os

        mod, payload = ledger
        mod.record("UserPromptSubmit", [("temporal", "h", "MINE")], "MINE", payload)
        neighbour = {**payload, "session_id": "sess-2"}
        mod.record("UserPromptSubmit", [("navmap", "h", "N" * 77)], "N" * 77, neighbour)
        os.utime(mod.ledger_store.ledger_path("sess-2"), (4_000_000_000, 4_000_000_000))

        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-1")
        with patch(f"{_LEDGER}.json_handler"):
            mod.handle_command("ledger", [])
        out = capsys.readouterr().out
        assert "sess-1 (this session)" in out and "temporal=4" in out and "navmap" not in out

        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
        with patch(f"{_LEDGER}.json_handler"):
            mod.handle_command("ledger", [])
        assert "sess-2 (most recently written, NOT this session)" in capsys.readouterr().out


_INJECTOR = "aipass.hooks.apps.handlers.prompt.temporal.handle"


class TestGatesFailClosed:
    """DPLAN-0356 item 2. Before: a gate that failed to import, raised or timed out was `continue`d past,
    and the call ran. Four gate crashes (09-12, 09-22, 09-30) were allowed that way."""

    @pytest.mark.parametrize(
        ("result", "why"),
        [
            ({"exit_code": -1, "stdout": "", "stderr": "No module named x", "elapsed_ms": 1}, "failed to load"),
            ({"exit_code": -1, "stdout": "", "stderr": "name '_X' is not defined", "elapsed_ms": 1}, "raised"),
            ({"exit_code": -1, "stdout": "", "stderr": "TIMEOUT", "elapsed_ms": 1}, "timed out"),
            ({"exit_code": 2, "stdout": "Traceback", "stderr": "", "elapsed_ms": 1}, "without a decision"),
        ],
    )
    def test_a_broken_gate_blocks_with_the_fixed_text(self, result, why, mock_logger):
        with patch("aipass.hooks.apps.modules.engine._run_handler", return_value=result):
            out, code = dispatch("PreToolUse", '{"tool_name": "Bash"}', _one(_GATE))
        assert code == 2
        reason = json.loads(out)["reason"]
        assert reason.startswith("GATE BROKEN: the_hook")
        assert why in reason
        assert "Mail @hooks and @devpulse" in reason

    def test_a_real_import_failure_blocks(self, mock_logger):
        with patch("aipass.hooks.apps.modules.engine._import_handler_module", side_effect=ImportError("half-edited")):
            _, code = dispatch("PreToolUse", '{"tool_name": "Bash"}', _one(_GATE))
        assert code == 2

    def test_a_broken_injector_is_still_skipped(self, mock_logger):
        broken = {"exit_code": -1, "stdout": "", "stderr": "boom", "elapsed_ms": 1}
        with patch("aipass.hooks.apps.modules.engine._run_handler", return_value=broken):
            assert dispatch("PreToolUse", '{"tool_name": "Bash"}', _one(_INJECTOR)) == ("", 0)

    def test_a_fail_open_gate_is_skipped_by_decision(self, mock_logger):
        broken = {"exit_code": -1, "stdout": "", "stderr": "TIMEOUT", "elapsed_ms": 1}
        handler = "aipass.hooks.apps.handlers.security.subagent_gate.handle"
        with patch("aipass.hooks.apps.modules.engine._run_handler", return_value=broken):
            assert dispatch("SubagentStop", "{}", _one(handler, "SubagentStop")) == ("", 0)

    def test_the_broken_gate_is_logged_at_error(self, mock_logger):
        broken = {"exit_code": -1, "stdout": "", "stderr": "boom", "elapsed_ms": 1}
        with (
            patch("aipass.hooks.apps.modules.engine._run_handler", return_value=broken),
            patch("aipass.hooks.apps.modules.engine.logger") as log,
        ):
            dispatch("PreToolUse", '{"tool_name": "Bash"}', _one(_GATE))
        assert "GATE BROKEN" in log.error.call_args[0][0]


class TestMovingIsNeverRefused:
    """dab4e222: mv and mkdir inside the seat's own branch stay allowed — by every Bash gate at once."""

    @pytest.mark.parametrize(
        "command",
        (
            "mkdir -p docs.local/.archive && mv docs.local/old.md docs.local/.archive/",
            "mv docs.local/old.md 'docs.local/old(disabled).md'",
        ),
    )
    def test_each_fail_closed_gate_lets_an_archive_move_through(self, command, mock_logger):
        branch = Path(__file__).resolve().parents[1]
        event = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(branch)}
        for handler in FAIL_CLOSED:
            module, _, func = handler.rpartition(".")
            result = getattr(importlib.import_module(module), func)(dict(event))
            assert result["exit_code"] == 0, (handler, result.get("stdout"))


_BRANCH = Path(__file__).resolve().parents[1]
_BRIDGE = _BRANCH / "apps" / "handlers" / "bridges" / "claude.py"


def _load_by_path(name: str, path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"{path} is not loadable as a module"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTheBridgeFailsClosed:
    """DPLAN-0356 item 2: an engine that cannot import made Python exit 1, and Claude Code ran the tool."""

    @pytest.fixture(autouse=True)
    def _break_log(self, tmp_path):
        self.break_log = tmp_path / "bridge.log"

    def _bridge(self, event: str, monkeypatch):
        bridge = _load_by_path("bridge_under_test", _BRIDGE)
        monkeypatch.setattr("sys.argv", ["claude.py", event])
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO("{}"))
        monkeypatch.setattr(bridge, "_mount", MagicMock(side_effect=SyntaxError("half-edited engine")))
        monkeypatch.setattr(bridge, "BREAK_LOG", str(self.break_log))
        return bridge

    def test_the_break_is_an_error_line_medic_reads(self, monkeypatch, capsys, mock_logger):
        """The prax logger can be what broke (2026-10-23): the line is written without it, in its format."""
        with pytest.raises(SystemExit):
            self._bridge("PreToolUse", monkeypatch).main()
        (line,) = self.break_log.read_text(encoding="utf-8").splitlines()
        stamp, _module, level, message = line.split(" | ", 3)
        datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
        assert level == "ERROR"
        assert "half-edited engine" in message and "PreToolUse" in message

    def test_a_suite_run_break_never_lands_in_the_live_bridge_log(self, monkeypatch, capsys, mock_logger):
        bridge = self._bridge("PreToolUse", monkeypatch)
        monkeypatch.setattr(bridge, "BREAK_LOG", bridge.LIVE_BREAK_LOG)
        live = Path(bridge.LIVE_BREAK_LOG)
        before = live.read_bytes() if live.exists() else b""
        with pytest.raises(SystemExit):
            bridge.main()
        assert "HOOKS BROKEN" in capsys.readouterr().err
        assert (live.read_bytes() if live.exists() else b"") == before, "medic reads that log as a real break"

    def test_pre_tool_use_is_refused(self, monkeypatch, capsys, mock_logger):
        with pytest.raises(SystemExit) as refused:
            self._bridge("PreToolUse", monkeypatch).main()
        assert refused.value.code == 2
        assert json.loads(capsys.readouterr().out)["reason"].startswith("HOOKS BROKEN")

    def test_every_other_event_passes(self, monkeypatch, capsys, mock_logger):
        self._bridge("UserPromptSubmit:branch_prompt", monkeypatch).main()  # returns: no SystemExit, so exit 0
        assert capsys.readouterr().out == ""


class TestPromote:
    """DPLAN-0356 item 3. All three gate crashes were NameErrors from half-done edits to live files."""

    def _branch(self, tmp_path: Path) -> Path:
        (tmp_path / "apps" / "modules").mkdir(parents=True)
        (tmp_path / "apps" / "__init__.py").write_text("", encoding="utf-8")
        (tmp_path / "apps" / "modules" / "x.py").write_text("X = 1\n", encoding="utf-8")
        return tmp_path

    def test_a_failed_check_refuses_and_leaves_the_live_copy(self, tmp_path, mock_logger):
        root = self._branch(tmp_path)
        promote.point_at(root, ".live-old")
        with patch.object(promote, "check_smoke", return_value=(True, "ok")) as smoke:
            ok, report = promote.promote(root, checks=(lambda r: (False, "F821 undefined name"),))
        assert ok is False
        assert promote.live_name(root) == ".live-old"
        assert not [p for p in root.iterdir() if p.name.startswith(".live-2")]
        assert len(report) == 1 and "FAILED" in report[0]
        smoke.assert_not_called()

    def test_a_failed_smoke_discards_the_candidate(self, tmp_path, mock_logger):
        root = self._branch(tmp_path)
        with patch.object(promote, "check_smoke", return_value=(False, "raw rm was not refused")):
            ok, _ = promote.promote(root, checks=())
        assert ok is False
        assert promote.live_name(root) is None
        assert not [p for p in root.iterdir() if p.name.startswith(".live-")]

    def test_an_edit_made_while_the_checks_run_is_never_promoted(self, tmp_path, mock_logger):
        root = self._branch(tmp_path)

        def edit_mid_suite(r: Path) -> tuple[bool, str]:
            (r / "apps" / "modules" / "x.py").write_text("X = undefined\n", encoding="utf-8")
            return True, "passed"

        with patch.object(promote, "check_smoke", return_value=(True, "ok")) as smoke:
            ok, report = promote.promote(root, checks=(edit_mid_suite,))
        assert ok is False and "changed" in report[-1]
        assert promote.live_name(root) is None
        assert not [p for p in root.iterdir() if p.name.startswith(".live-")]
        smoke.assert_not_called()

    def test_a_passing_promote_points_at_a_copy_and_rotates(self, tmp_path, mock_logger):
        root = self._branch(tmp_path)
        for old in (".live-20200101T000000Z", ".live-20200102T000000Z", ".live-20200103T000000Z"):
            (root / old).mkdir()
        with patch.object(promote, "check_smoke", return_value=(True, "ok")):
            ok, _ = promote.promote(root, checks=())
        live = promote.live_name(root)
        assert ok and live and (root / live / "modules" / "x.py").is_file()
        assert sorted(p.name for p in root.iterdir() if p.name.startswith(".live-2")) == [
            ".live-20200102T000000Z",
            ".live-20200103T000000Z",
            live,
        ]

    def test_the_bridge_and_promote_spell_the_pointer_alike(self):
        mount = _load_by_path("mount_under_test", _BRIDGE.parent / "mount.py")
        assert (mount.POINTER, mount.PREFIX, mount.OVERRIDE_ENV) == (
            promote.POINTER,
            promote.PREFIX,
            promote.OVERRIDE_ENV,
        )


class TestMount:
    def test_no_pointer_serves_the_source(self, tmp_path):
        mount = _load_by_path("mount_under_test", _BRIDGE.parent / "mount.py")
        assert mount.promoted_dir(str(tmp_path)) is None

    def test_a_pointer_outside_the_snapshots_is_refused(self, tmp_path, monkeypatch):
        mount = _load_by_path("mount_under_test", _BRIDGE.parent / "mount.py")
        monkeypatch.delenv(mount.OVERRIDE_ENV, raising=False)
        for name in ("../apps", ".live-x/../../etc", "apps"):
            (tmp_path / mount.POINTER).write_text(name, encoding="utf-8")
            with pytest.raises(ValueError):
                mount.promoted_dir(str(tmp_path))

    def test_a_missing_snapshot_is_an_error_not_the_source(self, tmp_path, monkeypatch):
        mount = _load_by_path("mount_under_test", _BRIDGE.parent / "mount.py")
        monkeypatch.delenv(mount.OVERRIDE_ENV, raising=False)
        (tmp_path / mount.POINTER).write_text(".live-gone", encoding="utf-8")
        with pytest.raises(FileNotFoundError):
            mount.promoted_dir(str(tmp_path))
