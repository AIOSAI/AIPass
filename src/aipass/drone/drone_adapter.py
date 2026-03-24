"""
Drone self-routing adapter — bridges drone routing to itself.

Drone discovers this module via aipass.drone.apps.modules.module_registry
and routes `drone @drone <command> [args]` here.
"""

import sys
from io import StringIO

from aipass.prax import logger

DRONE_MODULE = {
    "name": "drone",
    "version": "1.0.0",
    "description": "Command routing and module discovery",
}


def handle_command(command: str, args: list[str] | None = None) -> dict:
    """Route a drone command to drone's own entry point.

    Captures stdout/stderr and returns as dict for drone CLI to print.
    """
    if args is None:
        args = []

    original_argv = sys.argv
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    captured_out = StringIO()
    captured_err = StringIO()

    try:
        sys.argv = ["drone", command] + args
        sys.stdout = captured_out
        sys.stderr = captured_err

        from aipass.drone.apps.drone import main
        exit_code = main()
    except SystemExit as e:
        exit_code = e.code if e.code is not None else 0
    except Exception as e:
        logger.warning("handle_command failed: %s", e)
        captured_err.write(str(e))
        exit_code = 1
    finally:
        sys.argv = original_argv
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    return {
        "stdout": captured_out.getvalue(),
        "stderr": captured_err.getvalue(),
        "exit_code": exit_code if isinstance(exit_code, int) else 1,
    }


def get_help(command: str | None = None) -> str:
    """Return help text for drone."""
    if command:
        result = handle_command(command, ["--help"])
        return result.get("stdout", "") or result.get("stderr", "")

    return (
        "drone — Command routing and module discovery\n"
        "\n"
        "Commands:\n"
        "  systems                 List registered branches and modules\n"
        "  @target command [args]  Route command to branch or module\n"
        "  @target --help          Show help for branch or module\n"
        "\n"
        "Usage via drone:\n"
        "  drone systems\n"
        "  drone @seedgo audit aipass\n"
        "  drone @seedgo list\n"
    )


def get_introspective() -> str:
    """Discovery mode: show what drone has connected."""
    try:
        from aipass.drone.apps.modules.module_registry import list_modules
        from aipass.drone.apps.modules.resolver import list_branches

        modules = list_modules()
        branches = list_branches()
        return (
            f"@drone — Command routing and module discovery\n"
            f"  Internal modules: {len(modules)} ({', '.join(modules)})\n"
            f"  Registered branches: {len(branches)}\n"
            f"  Run 'drone @drone --help' for usage\n"
        )
    except Exception as exc:
        logger.warning("get_introspective: failed to load module list or branch list: %s", exc)
        return "@drone — Command routing and module discovery (run 'drone --help' for usage)\n"
