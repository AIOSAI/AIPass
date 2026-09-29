# =================== AIPass ====================
# Name: test_module_registry.py
# Description: module_registry orchestrator - handle_command routing
# Version: 1.0.3
# Created: 2026-04-05
# Modified: 2026-09-28
# =============================================

"""Tests for apps/modules/module_registry.py and apps/handlers/module_registry_handler.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — importlib loading an adapter from its dotted path

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import aipass.drone.apps.handlers.module_registry_handler as mrh
from aipass.drone.apps.handlers.module_registry_handler import ModuleInfo
from aipass.drone.apps.modules.module_registry import handle_command


# ---------------------------------------------------------------------------
# Module path prefix for patching
# ---------------------------------------------------------------------------
_MOD = "aipass.drone.apps.modules.module_registry"
_HANDLER = "aipass.drone.apps.handlers.module_registry_handler"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_module_info(
    name: str = "testmod",
    version: str = "1.0.0",
    description: str = "A test module",
    adapter_path: str = "aipass.test.adapter",
) -> object:
    """Build a ModuleInfo for mocking."""
    return ModuleInfo(
        name=name,
        version=version,
        description=description,
        adapter_path=adapter_path,
    )


def _ext(name: str) -> SimpleNamespace:
    """An external-module entry as routing_config.json declares one: name, entry point, description, version."""
    return SimpleNamespace(name=name, entry_point="fake.entry", description=f"{name} test", version="1.0")


# ===========================================================================
# 1. No command (None) — introspection
# ===========================================================================


class TestHandleCommandNone:
    """When command is None and args is empty, print_introspection is called."""

    def test_none_command_calls_introspection(self) -> None:
        """handle_command(None) calls print_introspection and returns True."""
        with patch(f"{_MOD}.print_introspection") as mock_intro:
            result = handle_command(None)

        assert result is True
        mock_intro.assert_called_once()

    def test_none_command_no_args_calls_introspection(self) -> None:
        """handle_command(None, None) calls print_introspection."""
        with patch(f"{_MOD}.print_introspection") as mock_intro:
            result = handle_command(None, None)

        assert result is True
        mock_intro.assert_called_once()

    def test_none_command_empty_args_calls_introspection(self) -> None:
        """handle_command(None, []) triggers introspection (falsy args, None command)."""
        with patch(f"{_MOD}.print_introspection") as mock_intro:
            result = handle_command(None, [])

        assert result is True
        mock_intro.assert_called_once()


# ===========================================================================
# 2. Help routing (--help / -h)
# ===========================================================================


class TestHandleCommandHelp:
    """--help and -h as command or first arg route to print_help."""

    def test_help_long_flag_as_command(self) -> None:
        """handle_command('--help') calls print_help and returns True."""
        with patch(f"{_MOD}.print_help") as mock_help:
            result = handle_command("--help")

        assert result is True
        mock_help.assert_called_once()

    def test_help_short_flag_as_command(self) -> None:
        """handle_command('-h') calls print_help and returns True."""
        with patch(f"{_MOD}.print_help") as mock_help:
            result = handle_command("-h")

        assert result is True
        mock_help.assert_called_once()

    def test_help_flag_in_args(self) -> None:
        """handle_command('list', ['--help']) calls print_help."""
        with patch(f"{_MOD}.print_help") as mock_help:
            result = handle_command("list", ["--help"])

        assert result is True
        mock_help.assert_called_once()

    def test_short_help_flag_in_args(self) -> None:
        """handle_command('info', ['-h']) calls print_help."""
        with patch(f"{_MOD}.print_help") as mock_help:
            result = handle_command("info", ["-h"])

        assert result is True
        mock_help.assert_called_once()


# ===========================================================================
# 3. list command
# ===========================================================================


class TestHandleCommandList:
    """'list' command iterates modules and prints with/without info."""

    def test_list_with_module_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Modules with info print '@name description' (mutant: description dropped)."""
        info = _make_module_info(name="alpha", description="Alpha module")

        with (
            patch(f"{_MOD}.list_modules", return_value=["alpha"]),
            patch(f"{_MOD}.get_module_info", return_value=info),
            patch(f"{_MOD}.json_handler", autospec=True),
        ):
            result = handle_command("list")

        assert result is True
        printed = capsys.readouterr().out
        assert "@alpha" in printed
        assert "Alpha module" in printed

    def test_list_without_module_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Modules without info print '@name (not available)' (mutant: the marker dropped)."""
        with (
            patch(f"{_MOD}.list_modules", return_value=["broken"]),
            patch(f"{_MOD}.get_module_info", return_value=None),
            patch(f"{_MOD}.json_handler", autospec=True),
        ):
            result = handle_command("list")

        assert result is True
        printed = capsys.readouterr().out
        assert "@broken" in printed
        assert "(not available)" in printed

    def test_list_multiple_modules(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Each module prints its own line (mutant: description dropped from the line)."""
        info_a = _make_module_info(name="aaa", description="Module A")
        info_b = _make_module_info(name="bbb", description="Module B")

        def side_effect(name: str) -> object:
            return {"aaa": info_a, "bbb": info_b}.get(name)

        with (
            patch(f"{_MOD}.list_modules", return_value=["aaa", "bbb"]),
            patch(f"{_MOD}.get_module_info", side_effect=side_effect),
            patch(f"{_MOD}.json_handler", autospec=True),
        ):
            result = handle_command("list")

        assert result is True
        assert capsys.readouterr().out.splitlines() == [
            "  @aaa                Module A",
            "  @bbb                Module B",
        ]

    def test_list_empty_registry(self, capsys: pytest.CaptureFixture[str]) -> None:
        """An empty registry prints nothing (mutant: a header printed first)."""
        with (
            patch(f"{_MOD}.list_modules", return_value=[]),
            patch(f"{_MOD}.json_handler", autospec=True),
        ):
            result = handle_command("list")

        assert result is True
        assert capsys.readouterr().out == ""


# ===========================================================================
# 4. info command
# ===========================================================================


class TestHandleCommandInfo:
    """'info' command shows module metadata."""

    def test_info_without_args_returns_false(self) -> None:
        """'info' with no args logs a warning and returns False."""
        with (
            patch(f"{_MOD}.logger") as mock_logger,
            patch(f"{_MOD}.json_handler", autospec=True),
        ):
            result = handle_command("info")

        assert result is False
        mock_logger.warning.assert_called()

    def test_info_unknown_module_returns_false(self) -> None:
        """'info' for a non-existent module returns False."""
        with (
            patch(f"{_MOD}.get_module_info", return_value=None),
            patch(f"{_MOD}.logger") as mock_logger,
            patch(f"{_MOD}.json_handler", autospec=True),
        ):
            result = handle_command("info", ["nonexistent"])

        assert result is False
        mock_logger.warning.assert_called()

    def test_info_on_a_registered_module_that_cannot_load_says_so(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A registered module whose adapter cannot import is not "not found": info names it
        on stderr as registered but not loadable, and answers False.

        Red first: info logged "not found" for it. Mutant killed: the registered check removed."""
        monkeypatch.setattr(mrh, "_INTERNAL_MODULES", {"broken": "fake.broken.mod"})
        with patch(f"{_MOD}.json_handler", autospec=True):
            result = handle_command("info", ["broken"])
        assert result is False
        err = " ".join(capsys.readouterr().err.split())
        assert "module_registry: @broken is registered but could not load (see drone log)" in err

    def test_info_valid_module_returns_true(self, capsys: pytest.CaptureFixture[str]) -> None:
        """'info' prints name, version and description (mutant: version dropped)."""
        info = _make_module_info(
            name="seedgo",
            version="2.1.0",
            description="Seedgo audit system",
        )

        with (
            patch(f"{_MOD}.get_module_info", return_value=info),
            patch(f"{_MOD}.json_handler", autospec=True),
        ):
            result = handle_command("info", ["seedgo"])

        assert result is True
        printed = capsys.readouterr().out
        assert "seedgo" in printed
        assert "2.1.0" in printed
        assert "Seedgo audit system" in printed


# ===========================================================================
# 5. check command
# ===========================================================================


class TestHandleCommandCheck:
    """'check' command reports whether a module is registered."""

    def test_check_without_args_returns_false(self) -> None:
        """'check' with no args logs a warning and returns False."""
        with (
            patch(f"{_MOD}.logger") as mock_logger,
            patch(f"{_MOD}.json_handler", autospec=True),
        ):
            result = handle_command("check")

        assert result is False
        mock_logger.warning.assert_called()

    def test_check_registered_module(self, capsys: pytest.CaptureFixture[str]) -> None:
        """'check' prints the registered status (mutant: status hard-coded False)."""
        with (
            patch(f"{_MOD}.is_module", return_value=True),
            patch(f"{_MOD}.json_handler", autospec=True),
        ):
            result = handle_command("check", ["git"])

        assert result is True
        printed = capsys.readouterr().out
        assert "git" in printed
        assert "True" in printed

    def test_check_unregistered_module(self, capsys: pytest.CaptureFixture[str]) -> None:
        """'check' prints the unregistered status (mutant: status is bool(is_module))."""
        with (
            patch(f"{_MOD}.is_module", return_value=False),
            patch(f"{_MOD}.json_handler", autospec=True),
        ):
            result = handle_command("check", ["fakemod"])

        assert result is True
        printed = capsys.readouterr().out
        assert "fakemod" in printed
        assert "False" in printed


# ===========================================================================
# 6. Unknown command
# ===========================================================================


class TestHandleCommandUnknown:
    """Unrecognized commands log a warning and return False."""

    def test_unknown_command_returns_false(self) -> None:
        """An unrecognized command returns False."""
        with (
            patch(f"{_MOD}.logger") as mock_logger,
            patch(f"{_MOD}.json_handler", autospec=True),
        ):
            result = handle_command("foobar")

        assert result is False
        mock_logger.warning.assert_called()
        warning_msg = mock_logger.warning.call_args[0][0]
        assert "unknown command" in warning_msg.lower()


# ===========================================================================
# 7. The audit line — one claim, every verb
# ===========================================================================


class TestTheAuditLine:
    """Every verb is audited before it is dispatched."""

    @pytest.mark.parametrize("command", ["list", "info", "check", "bogus"])
    def test_the_verb_is_audited_before_it_is_dispatched(self, command: str) -> None:
        """log_operation names the verb it received, whatever the verb is.

        One test, four cases — it used to be four tests, one per verb, sitting
        in four different classes. There is only one call site: it sits ABOVE
        the verb branch in handle_command, so list / info / check / an unknown
        string are the same line of code reached four ways. Four copies read as
        four claims and all four die to the same edit.

        The verb still has to be parametrized rather than dropped to one case:
        the payload's ``command`` key comes from the argument, and a hardcoded
        ``"list"`` there is a real mutant that a single-verb test cannot see.
        The unknown verb is a case and not an afterthought — a command that is
        about to be REFUSED is the one most worth having written down.
        """
        with (
            patch(f"{_MOD}.list_modules", return_value=[]),
            patch(f"{_MOD}.get_module_info", return_value=None),
            patch(f"{_MOD}.is_module", return_value=False),
            patch(f"{_MOD}.logger"),
            patch(f"{_MOD}.json_handler", autospec=True) as mock_jh,
        ):
            handle_command(command, ["anything"])

        mock_jh.log_operation.assert_called_once_with(
            "handle_command", {"module": "module_registry", "command": command}
        )


# ===========================================================================
# 8. route_module_command (handler-level)
# ===========================================================================


class TestRouteModuleCommand:
    """route_module_command() routes to external or internal modules."""

    def test_routes_external_module_via_capture(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """External modules route through capture_main."""
        monkeypatch.setattr(mrh, "_EXTERNAL_MODULES", {"testext": _ext("testext")})
        with (
            patch(
                f"{_HANDLER}.capture_main",
                return_value={
                    "stdout": "ok",
                    "stderr": "",
                    "exit_code": 0,
                },
            ) as mock_cap,
            patch(f"{_HANDLER}.json_handler", autospec=True),
        ):
            result = mrh.route_module_command("testext", "run", ["--flag"])
        assert result["stdout"] == "ok"
        assert result["exit_code"] == 0
        mock_cap.assert_called_once_with("fake.entry", "testext", "run", ["--flag"])

    def test_routes_internal_module_via_import(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Internal modules route through importlib + handle_command."""
        monkeypatch.setattr(mrh, "_INTERNAL_MODULES", {"fakeint": "fake.internal.mod"})
        mock_mod = MagicMock()
        mock_mod.handle_command.return_value = {
            "stdout": "done",
            "stderr": "",
            "exit_code": 0,
        }
        with (
            # THE JSON PATCH GOES FIRST AND THAT IS LOAD-BEARING. `patch`
            # resolves a dotted target through `pkgutil.resolve_name`, which
            # calls `importlib.import_module` — so once the importlib patch
            # below is live, the next patch in the same block resolves
            # `_HANDLER` to `mock_mod` and lands its mock on THAT instead of
            # on the real handler module. Measured in the other order: the
            # module's `json_handler` was still the real module inside the
            # block, so this patch replaced nothing and the test wrote a real
            # log record. Entered first, it patches the module it names.
            patch(f"{_HANDLER}.json_handler", autospec=True),
            patch(
                f"{_HANDLER}.importlib.import_module",
                return_value=mock_mod,
            ),
        ):
            result = mrh.route_module_command("fakeint", "status")
        assert result["stdout"] == "done"
        mock_mod.handle_command.assert_called_once_with("status", None)

    def test_internal_bool_true_converted_to_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Internal module returning True converts to dict with exit_code 0."""
        monkeypatch.setattr(mrh, "_INTERNAL_MODULES", {"boolmod": "fake.bool.mod"})
        mock_mod = MagicMock()
        mock_mod.handle_command.return_value = True
        with (
            # json_handler FIRST — see test_routes_internal_module_via_import:
            # a live importlib patch makes the next patch resolve to mock_mod.
            patch(f"{_HANDLER}.json_handler", autospec=True),
            patch(
                f"{_HANDLER}.importlib.import_module",
                return_value=mock_mod,
            ),
        ):
            result = mrh.route_module_command("boolmod", "check")
        assert result["exit_code"] == 0

    def test_internal_bool_false_converted_to_exit_code_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Internal module returning False gets exit_code 1."""
        monkeypatch.setattr(mrh, "_INTERNAL_MODULES", {"failmod": "fake.fail.mod"})
        mock_mod = MagicMock()
        mock_mod.handle_command.return_value = False
        with (
            # json_handler FIRST — see test_routes_internal_module_via_import:
            # a live importlib patch makes the next patch resolve to mock_mod.
            patch(f"{_HANDLER}.json_handler", autospec=True),
            patch(
                f"{_HANDLER}.importlib.import_module",
                return_value=mock_mod,
            ),
        ):
            result = mrh.route_module_command("failmod", "broken")
        assert result["exit_code"] == 1

    def test_logs_operation_for_external(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """External module routing logs via json_handler."""
        monkeypatch.setattr(mrh, "_EXTERNAL_MODULES", {"logext": _ext("logext")})
        with (
            patch(
                f"{_HANDLER}.capture_main",
                return_value={
                    "stdout": "",
                    "stderr": "",
                    "exit_code": 0,
                },
            ),
            patch(f"{_HANDLER}.json_handler", autospec=True) as mock_jh,
        ):
            mrh.route_module_command("logext", "ping")
        mock_jh.log_operation.assert_called_once_with("route_module_command", {"module": "logext", "command": "ping"})


# ===========================================================================
# 9. get_module_help (handler-level)
# ===========================================================================


class TestGetModuleHelp:
    """get_module_help() retrieves help text from modules."""

    def test_external_module_help_no_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """External module help without command captures --help output."""
        monkeypatch.setattr(mrh, "_EXTERNAL_MODULES", {"helpext": _ext("helpext")})
        with patch(
            f"{_HANDLER}.capture_main",
            return_value={
                "stdout": "Usage: helpext",
                "stderr": "",
            },
        ) as mock_cap:
            result = mrh.get_module_help("helpext")
        assert result == "Usage: helpext"
        mock_cap.assert_called_once_with("fake.entry", "helpext", "--help")

    def test_external_module_help_with_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """External module help with command passes command + --help."""
        monkeypatch.setattr(mrh, "_EXTERNAL_MODULES", {"helpext2": _ext("helpext2")})
        with patch(
            f"{_HANDLER}.capture_main",
            return_value={"stdout": "Sub help", "stderr": ""},
        ) as mock_cap:
            result = mrh.get_module_help("helpext2", "subcmd")
        assert result == "Sub help"
        mock_cap.assert_called_once_with("fake.entry", "helpext2", "subcmd", ["--help"])

    def test_internal_module_help(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Internal module help calls get_help() on the module."""
        monkeypatch.setattr(mrh, "_INTERNAL_MODULES", {"helpint": "fake.help.mod"})
        mock_mod = MagicMock()
        mock_mod.get_help.return_value = "Internal help text"
        with patch(
            f"{_HANDLER}.importlib.import_module",
            return_value=mock_mod,
        ):
            result = mrh.get_module_help("helpint", "status")
        assert result == "Internal help text"
        mock_mod.get_help.assert_called_once_with("status")

    def test_internal_module_without_get_help(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Internal module without get_help() returns empty string."""
        monkeypatch.setattr(mrh, "_INTERNAL_MODULES", {"nohelp": "fake.nohelp.mod"})
        mock_mod = MagicMock(spec=[])
        with patch(
            f"{_HANDLER}.importlib.import_module",
            return_value=mock_mod,
        ):
            result = mrh.get_module_help("nohelp")
        assert result == ""

    def test_unknown_module_returns_empty(self) -> None:
        """Unknown module name returns empty string."""
        result = mrh.get_module_help("nonexistent_mod_xyz")
        assert result == ""

    def test_a_module_that_cannot_import_answers_none_not_empty_help(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A broken module is told apart from one with no help text (mutant: the except returns "").

        The dotted path names no module, so the real import raises ModuleNotFoundError."""
        monkeypatch.setattr(mrh, "_INTERNAL_MODULES", {"broken": "fake.broken.mod"})
        result = mrh.get_module_help("broken")
        assert result is None


class TestGetModuleIntrospective:
    """get_module_introspective() tells a module that cannot load from one with nothing to say."""

    def test_a_module_that_cannot_import_answers_none_not_empty_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mutant: the except returns "". The dotted path names no module: the real import raises."""
        monkeypatch.setattr(mrh, "_INTERNAL_MODULES", {"broken": "fake.broken.mod"})
        result = mrh.get_module_introspective("broken")
        assert result is None

    def test_a_module_with_nothing_to_say_answers_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The success-path empty answer stays "" so the two remain distinct (mutant: that return None).

        ``string`` imports for real and holds neither get_introspective nor get_help."""
        monkeypatch.setattr(mrh, "_INTERNAL_MODULES", {"quiet": "string"})
        result = mrh.get_module_introspective("quiet")
        assert result == ""


class TestTheExternalModuleConfig:
    """load_external_modules() hands back the reason with an empty set, so a lost config is told from none."""

    def test_an_unreadable_config_answers_empty_with_its_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Mutant: the except returns ({}, None). The config is a real file of broken JSON."""
        config = tmp_path / "routing_config.json"
        config.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(mrh, "_ROUTING_CONFIG_PATH", config)
        modules, error = mrh.load_external_modules()
        assert modules == {}
        assert error is not None
        assert error.startswith(f"failed to load {config}: ")
        assert "load_external_modules: failed to load config" in caplog.text

    def test_an_absent_config_answers_empty_with_its_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutant: the not-found branch returns ({}, None)."""
        config = tmp_path / "routing_config.json"
        monkeypatch.setattr(mrh, "_ROUTING_CONFIG_PATH", config)
        assert mrh.load_external_modules() == ({}, f"config not found at {config}")

    def test_a_config_that_loads_answers_no_reason(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mutant: the success return carries a reason. The success answer is the one with None."""
        config = tmp_path / "routing_config.json"
        config.write_text('{"modules": {"ext": {"entry_point": "a.b"}}}', encoding="utf-8")
        monkeypatch.setattr(mrh, "_ROUTING_CONFIG_PATH", config)
        modules, error = mrh.load_external_modules()
        assert error is None
        assert modules["ext"].entry_point == "a.b"
        assert modules["ext"].version == "unknown"

    def test_the_reason_is_read_at_call_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """external_modules_error() reads the module state, not a copy (mutant: it returns None)."""
        monkeypatch.setattr(mrh, "_EXTERNAL_MODULES_ERROR", "config not found at x")
        assert mrh.external_modules_error() == "config not found at x"
