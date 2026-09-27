# =================== AIPass ====================
# Name: test_module_registry.py
# Description: module_registry orchestrator - handle_command routing
# Version: 1.0.1
# Created: 2026-04-05
# Modified: 2026-09-27
# =============================================

"""Tests for apps/modules/module_registry.py and apps/handlers/module_registry_handler.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — importlib loading an adapter from its dotted path

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import aipass.drone.apps.handlers.module_registry_handler as mrh
from aipass.drone.apps.handlers.module_registry_handler import ModuleInfo, _ExternalModuleConfig
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

    def test_routes_external_module_via_capture(self) -> None:
        """External modules route through capture_main."""
        original_ext = dict(mrh._EXTERNAL_MODULES)
        mrh._EXTERNAL_MODULES["testext"] = _ExternalModuleConfig("testext", "fake.entry", "Test external", "1.0")
        try:
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
        finally:
            mrh._EXTERNAL_MODULES = original_ext

    def test_routes_internal_module_via_import(self) -> None:
        """Internal modules route through importlib + handle_command."""
        original_int = dict(mrh._INTERNAL_MODULES)
        mrh._INTERNAL_MODULES["fakeint"] = "fake.internal.mod"
        try:
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
        finally:
            mrh._INTERNAL_MODULES = original_int

    def test_internal_bool_true_converted_to_dict(self) -> None:
        """Internal module returning True converts to dict with exit_code 0."""
        original_int = dict(mrh._INTERNAL_MODULES)
        mrh._INTERNAL_MODULES["boolmod"] = "fake.bool.mod"
        try:
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
        finally:
            mrh._INTERNAL_MODULES = original_int

    def test_internal_bool_false_converted_to_exit_code_1(self) -> None:
        """Internal module returning False gets exit_code 1."""
        original_int = dict(mrh._INTERNAL_MODULES)
        mrh._INTERNAL_MODULES["failmod"] = "fake.fail.mod"
        try:
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
        finally:
            mrh._INTERNAL_MODULES = original_int

    def test_logs_operation_for_external(self) -> None:
        """External module routing logs via json_handler."""
        original_ext = dict(mrh._EXTERNAL_MODULES)
        mrh._EXTERNAL_MODULES["logext"] = _ExternalModuleConfig("logext", "fake.entry", "Log test", "1.0")
        try:
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
            mock_jh.log_operation.assert_called_once_with(
                "route_module_command", {"module": "logext", "command": "ping"}
            )
        finally:
            mrh._EXTERNAL_MODULES = original_ext


# ===========================================================================
# 9. get_module_help (handler-level)
# ===========================================================================


class TestGetModuleHelp:
    """get_module_help() retrieves help text from modules."""

    def test_external_module_help_no_command(self) -> None:
        """External module help without command captures --help output."""
        original_ext = dict(mrh._EXTERNAL_MODULES)
        mrh._EXTERNAL_MODULES["helpext"] = _ExternalModuleConfig("helpext", "fake.entry", "Help test", "1.0")
        try:
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
        finally:
            mrh._EXTERNAL_MODULES = original_ext

    def test_external_module_help_with_command(self) -> None:
        """External module help with command passes command + --help."""
        original_ext = dict(mrh._EXTERNAL_MODULES)
        mrh._EXTERNAL_MODULES["helpext2"] = _ExternalModuleConfig("helpext2", "fake.entry", "Help test", "1.0")
        try:
            with patch(
                f"{_HANDLER}.capture_main",
                return_value={"stdout": "Sub help", "stderr": ""},
            ) as mock_cap:
                result = mrh.get_module_help("helpext2", "subcmd")
            assert result == "Sub help"
            mock_cap.assert_called_once_with("fake.entry", "helpext2", "subcmd", ["--help"])
        finally:
            mrh._EXTERNAL_MODULES = original_ext

    def test_internal_module_help(self) -> None:
        """Internal module help calls get_help() on the module."""
        original_int = dict(mrh._INTERNAL_MODULES)
        mrh._INTERNAL_MODULES["helpint"] = "fake.help.mod"
        try:
            mock_mod = MagicMock()
            mock_mod.get_help.return_value = "Internal help text"
            with patch(
                f"{_HANDLER}.importlib.import_module",
                return_value=mock_mod,
            ):
                result = mrh.get_module_help("helpint", "status")
            assert result == "Internal help text"
            mock_mod.get_help.assert_called_once_with("status")
        finally:
            mrh._INTERNAL_MODULES = original_int

    def test_internal_module_without_get_help(self) -> None:
        """Internal module without get_help() returns empty string."""
        original_int = dict(mrh._INTERNAL_MODULES)
        mrh._INTERNAL_MODULES["nohelp"] = "fake.nohelp.mod"
        try:
            mock_mod = MagicMock(spec=[])
            with patch(
                f"{_HANDLER}.importlib.import_module",
                return_value=mock_mod,
            ):
                result = mrh.get_module_help("nohelp")
            assert result == ""
        finally:
            mrh._INTERNAL_MODULES = original_int

    def test_unknown_module_returns_empty(self) -> None:
        """Unknown module name returns empty string."""
        result = mrh.get_module_help("nonexistent_mod_xyz")
        assert result == ""

    def test_import_error_returns_empty(self) -> None:
        """ImportError during internal module load returns empty string."""
        original_int = dict(mrh._INTERNAL_MODULES)
        mrh._INTERNAL_MODULES["broken"] = "fake.broken.mod"
        try:
            with patch(
                f"{_HANDLER}.importlib.import_module",
                side_effect=ImportError("nope"),
            ):
                result = mrh.get_module_help("broken")
            assert result == ""
        finally:
            mrh._INTERNAL_MODULES = original_int
