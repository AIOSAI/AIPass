"""Tests for the module_registry orchestrator — handle_command routing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


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
    from aipass.drone.apps.handlers.module_registry_handler import ModuleInfo

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
            from aipass.drone.apps.modules.module_registry import handle_command

            result = handle_command(None)

        assert result is True
        mock_intro.assert_called_once()

    def test_none_command_no_args_calls_introspection(self) -> None:
        """handle_command(None, None) calls print_introspection."""
        with patch(f"{_MOD}.print_introspection") as mock_intro:
            from aipass.drone.apps.modules.module_registry import handle_command

            result = handle_command(None, None)

        assert result is True
        mock_intro.assert_called_once()

    def test_none_command_empty_args_calls_introspection(self) -> None:
        """handle_command(None, []) triggers introspection (falsy args, None command)."""
        with patch(f"{_MOD}.print_introspection") as mock_intro:
            from aipass.drone.apps.modules.module_registry import handle_command

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
            from aipass.drone.apps.modules.module_registry import handle_command

            result = handle_command("--help")

        assert result is True
        mock_help.assert_called_once()

    def test_help_short_flag_as_command(self) -> None:
        """handle_command('-h') calls print_help and returns True."""
        with patch(f"{_MOD}.print_help") as mock_help:
            from aipass.drone.apps.modules.module_registry import handle_command

            result = handle_command("-h")

        assert result is True
        mock_help.assert_called_once()

    def test_help_flag_in_args(self) -> None:
        """handle_command('list', ['--help']) calls print_help."""
        with patch(f"{_MOD}.print_help") as mock_help:
            from aipass.drone.apps.modules.module_registry import handle_command

            result = handle_command("list", ["--help"])

        assert result is True
        mock_help.assert_called_once()

    def test_short_help_flag_in_args(self) -> None:
        """handle_command('info', ['-h']) calls print_help."""
        with patch(f"{_MOD}.print_help") as mock_help:
            from aipass.drone.apps.modules.module_registry import handle_command

            result = handle_command("info", ["-h"])

        assert result is True
        mock_help.assert_called_once()


# ===========================================================================
# 3. list command
# ===========================================================================


class TestHandleCommandList:
    """'list' command iterates modules and prints with/without info."""

    def test_list_with_module_info(self) -> None:
        """Modules with info are printed as '@name description'."""
        info = _make_module_info(name="alpha", description="Alpha module")

        with (
            patch(f"{_MOD}.list_modules", return_value=["alpha"]),
            patch(f"{_MOD}.get_module_info", return_value=info),
            patch(f"{_MOD}.console") as mock_console,
            patch(f"{_MOD}.json_handler"),
        ):
            from aipass.drone.apps.modules.module_registry import handle_command

            result = handle_command("list")

        assert result is True
        mock_console.print.assert_called()
        printed = mock_console.print.call_args[0][0]
        assert "@alpha" in printed
        assert "Alpha module" in printed

    def test_list_without_module_info(self) -> None:
        """Modules without info are printed as '@name (not available)'."""
        with (
            patch(f"{_MOD}.list_modules", return_value=["broken"]),
            patch(f"{_MOD}.get_module_info", return_value=None),
            patch(f"{_MOD}.console") as mock_console,
            patch(f"{_MOD}.json_handler"),
        ):
            from aipass.drone.apps.modules.module_registry import handle_command

            result = handle_command("list")

        assert result is True
        printed = mock_console.print.call_args[0][0]
        assert "@broken" in printed
        assert "(not available)" in printed

    def test_list_multiple_modules(self) -> None:
        """Multiple modules each get a print call."""
        info_a = _make_module_info(name="aaa", description="Module A")
        info_b = _make_module_info(name="bbb", description="Module B")

        def side_effect(name: str) -> object:
            return {"aaa": info_a, "bbb": info_b}.get(name)

        with (
            patch(f"{_MOD}.list_modules", return_value=["aaa", "bbb"]),
            patch(f"{_MOD}.get_module_info", side_effect=side_effect),
            patch(f"{_MOD}.console") as mock_console,
            patch(f"{_MOD}.json_handler"),
        ):
            from aipass.drone.apps.modules.module_registry import handle_command

            result = handle_command("list")

        assert result is True
        assert mock_console.print.call_count == 2

    def test_list_empty_registry(self) -> None:
        """Empty module list returns True with no print calls."""
        with (
            patch(f"{_MOD}.list_modules", return_value=[]),
            patch(f"{_MOD}.console") as mock_console,
            patch(f"{_MOD}.json_handler"),
        ):
            from aipass.drone.apps.modules.module_registry import handle_command

            result = handle_command("list")

        assert result is True
        mock_console.print.assert_not_called()

    def test_list_logs_operation(self) -> None:
        """'list' logs via json_handler before processing."""
        with (
            patch(f"{_MOD}.list_modules", return_value=[]),
            patch(f"{_MOD}.console"),
            patch(f"{_MOD}.json_handler") as mock_jh,
        ):
            from aipass.drone.apps.modules.module_registry import handle_command

            handle_command("list")

        mock_jh.log_operation.assert_called_once_with(
            "handle_command", {"module": "module_registry", "command": "list"}
        )


# ===========================================================================
# 4. info command
# ===========================================================================


class TestHandleCommandInfo:
    """'info' command shows module metadata."""

    def test_info_without_args_returns_false(self) -> None:
        """'info' with no args logs a warning and returns False."""
        with (
            patch(f"{_MOD}.logger") as mock_logger,
            patch(f"{_MOD}.json_handler"),
        ):
            from aipass.drone.apps.modules.module_registry import handle_command

            result = handle_command("info")

        assert result is False
        mock_logger.warning.assert_called()

    def test_info_unknown_module_returns_false(self) -> None:
        """'info' for a non-existent module returns False."""
        with (
            patch(f"{_MOD}.get_module_info", return_value=None),
            patch(f"{_MOD}.logger") as mock_logger,
            patch(f"{_MOD}.json_handler"),
        ):
            from aipass.drone.apps.modules.module_registry import handle_command

            result = handle_command("info", ["nonexistent"])

        assert result is False
        mock_logger.warning.assert_called()

    def test_info_valid_module_returns_true(self) -> None:
        """'info' for a valid module prints metadata and returns True."""
        info = _make_module_info(
            name="seedgo",
            version="2.1.0",
            description="Seedgo audit system",
        )

        with (
            patch(f"{_MOD}.get_module_info", return_value=info),
            patch(f"{_MOD}.console") as mock_console,
            patch(f"{_MOD}.json_handler"),
        ):
            from aipass.drone.apps.modules.module_registry import handle_command

            result = handle_command("info", ["seedgo"])

        assert result is True
        printed = mock_console.print.call_args[0][0]
        assert "seedgo" in printed
        assert "2.1.0" in printed
        assert "Seedgo audit system" in printed

    def test_info_logs_operation(self) -> None:
        """'info' logs via json_handler before processing."""
        with (
            patch(f"{_MOD}.get_module_info", return_value=None),
            patch(f"{_MOD}.logger"),
            patch(f"{_MOD}.json_handler") as mock_jh,
        ):
            from aipass.drone.apps.modules.module_registry import handle_command

            handle_command("info", ["anything"])

        mock_jh.log_operation.assert_called_once_with(
            "handle_command", {"module": "module_registry", "command": "info"}
        )


# ===========================================================================
# 5. check command
# ===========================================================================


class TestHandleCommandCheck:
    """'check' command reports whether a module is registered."""

    def test_check_without_args_returns_false(self) -> None:
        """'check' with no args logs a warning and returns False."""
        with (
            patch(f"{_MOD}.logger") as mock_logger,
            patch(f"{_MOD}.json_handler"),
        ):
            from aipass.drone.apps.modules.module_registry import handle_command

            result = handle_command("check")

        assert result is False
        mock_logger.warning.assert_called()

    def test_check_registered_module(self) -> None:
        """'check' for a registered module prints True status."""
        with (
            patch(f"{_MOD}.is_module", return_value=True),
            patch(f"{_MOD}.console") as mock_console,
            patch(f"{_MOD}.json_handler"),
        ):
            from aipass.drone.apps.modules.module_registry import handle_command

            result = handle_command("check", ["git"])

        assert result is True
        printed = mock_console.print.call_args[0][0]
        assert "git" in printed
        assert "True" in printed

    def test_check_unregistered_module(self) -> None:
        """'check' for an unregistered module prints False status."""
        with (
            patch(f"{_MOD}.is_module", return_value=False),
            patch(f"{_MOD}.console") as mock_console,
            patch(f"{_MOD}.json_handler"),
        ):
            from aipass.drone.apps.modules.module_registry import handle_command

            result = handle_command("check", ["fakemod"])

        assert result is True
        printed = mock_console.print.call_args[0][0]
        assert "fakemod" in printed
        assert "False" in printed

    def test_check_logs_operation(self) -> None:
        """'check' logs via json_handler before processing."""
        with (
            patch(f"{_MOD}.is_module", return_value=False),
            patch(f"{_MOD}.console"),
            patch(f"{_MOD}.json_handler") as mock_jh,
        ):
            from aipass.drone.apps.modules.module_registry import handle_command

            handle_command("check", ["anything"])

        mock_jh.log_operation.assert_called_once_with(
            "handle_command", {"module": "module_registry", "command": "check"}
        )


# ===========================================================================
# 6. Unknown command
# ===========================================================================


class TestHandleCommandUnknown:
    """Unrecognized commands log a warning and return False."""

    def test_unknown_command_returns_false(self) -> None:
        """An unrecognized command returns False."""
        with (
            patch(f"{_MOD}.logger") as mock_logger,
            patch(f"{_MOD}.json_handler"),
        ):
            from aipass.drone.apps.modules.module_registry import handle_command

            result = handle_command("foobar")

        assert result is False
        mock_logger.warning.assert_called()
        warning_msg = mock_logger.warning.call_args[0][0]
        assert "unknown command" in warning_msg.lower()

    def test_unknown_command_logs_operation(self) -> None:
        """Even unknown commands get logged via json_handler."""
        with (
            patch(f"{_MOD}.logger"),
            patch(f"{_MOD}.json_handler") as mock_jh,
        ):
            from aipass.drone.apps.modules.module_registry import handle_command

            handle_command("bogus")

        mock_jh.log_operation.assert_called_once_with(
            "handle_command", {"module": "module_registry", "command": "bogus"}
        )


# ===========================================================================
# 8. route_module_command (handler-level)
# ===========================================================================


class TestRouteModuleCommand:
    """route_module_command() routes to external or internal modules."""

    def test_routes_external_module_via_capture(self) -> None:
        """External modules route through capture_main."""
        import aipass.drone.apps.handlers.module_registry_handler as mrh
        from aipass.drone.apps.handlers.module_registry_handler import (
            _ExternalModuleConfig,
        )

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
                patch(f"{_HANDLER}.json_handler"),
            ):
                result = mrh.route_module_command("testext", "run", ["--flag"])
            assert result["stdout"] == "ok"
            assert result["exit_code"] == 0
            mock_cap.assert_called_once_with("fake.entry", "testext", "run", ["--flag"])
        finally:
            mrh._EXTERNAL_MODULES = original_ext

    def test_routes_internal_module_via_import(self) -> None:
        """Internal modules route through importlib + handle_command."""
        import aipass.drone.apps.handlers.module_registry_handler as mrh

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
                patch(
                    f"{_HANDLER}.importlib.import_module",
                    return_value=mock_mod,
                ),
                patch(f"{_HANDLER}.json_handler"),
            ):
                result = mrh.route_module_command("fakeint", "status")
            assert result["stdout"] == "done"
            mock_mod.handle_command.assert_called_once_with("status", None)
        finally:
            mrh._INTERNAL_MODULES = original_int

    def test_internal_bool_true_converted_to_dict(self) -> None:
        """Internal module returning True converts to dict with exit_code 0."""
        import aipass.drone.apps.handlers.module_registry_handler as mrh

        original_int = dict(mrh._INTERNAL_MODULES)
        mrh._INTERNAL_MODULES["boolmod"] = "fake.bool.mod"
        try:
            mock_mod = MagicMock()
            mock_mod.handle_command.return_value = True
            with (
                patch(
                    f"{_HANDLER}.importlib.import_module",
                    return_value=mock_mod,
                ),
                patch(f"{_HANDLER}.json_handler"),
            ):
                result = mrh.route_module_command("boolmod", "check")
            assert result["exit_code"] == 0
        finally:
            mrh._INTERNAL_MODULES = original_int

    def test_internal_bool_false_converted_to_exit_code_1(self) -> None:
        """Internal module returning False gets exit_code 1."""
        import aipass.drone.apps.handlers.module_registry_handler as mrh

        original_int = dict(mrh._INTERNAL_MODULES)
        mrh._INTERNAL_MODULES["failmod"] = "fake.fail.mod"
        try:
            mock_mod = MagicMock()
            mock_mod.handle_command.return_value = False
            with (
                patch(
                    f"{_HANDLER}.importlib.import_module",
                    return_value=mock_mod,
                ),
                patch(f"{_HANDLER}.json_handler"),
            ):
                result = mrh.route_module_command("failmod", "broken")
            assert result["exit_code"] == 1
        finally:
            mrh._INTERNAL_MODULES = original_int

    def test_logs_operation_for_external(self) -> None:
        """External module routing logs via json_handler."""
        import aipass.drone.apps.handlers.module_registry_handler as mrh
        from aipass.drone.apps.handlers.module_registry_handler import (
            _ExternalModuleConfig,
        )

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
                patch(f"{_HANDLER}.json_handler") as mock_jh,
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
        import aipass.drone.apps.handlers.module_registry_handler as mrh
        from aipass.drone.apps.handlers.module_registry_handler import (
            _ExternalModuleConfig,
        )

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
        import aipass.drone.apps.handlers.module_registry_handler as mrh
        from aipass.drone.apps.handlers.module_registry_handler import (
            _ExternalModuleConfig,
        )

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
        import aipass.drone.apps.handlers.module_registry_handler as mrh

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
        import aipass.drone.apps.handlers.module_registry_handler as mrh

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
        import aipass.drone.apps.handlers.module_registry_handler as mrh

        result = mrh.get_module_help("nonexistent_mod_xyz")
        assert result == ""

    def test_import_error_returns_empty(self) -> None:
        """ImportError during internal module load returns empty string."""
        import aipass.drone.apps.handlers.module_registry_handler as mrh

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
