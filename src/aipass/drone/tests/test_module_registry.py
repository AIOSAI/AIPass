"""Tests for the module_registry orchestrator — handle_command routing."""

from __future__ import annotations

from unittest.mock import patch


# ---------------------------------------------------------------------------
# Module path prefix for patching
# ---------------------------------------------------------------------------
_MOD = "aipass.drone.apps.modules.module_registry"


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
