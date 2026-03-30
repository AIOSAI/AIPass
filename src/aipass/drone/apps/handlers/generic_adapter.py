# =================== AIPass ====================
# Name: generic_adapter.py
# Description: Generic capture adapter for external branch modules
# Version: 1.0.0
# Created: 2026-03-29
# Modified: 2026-03-29
# =============================================

"""Generic capture adapter for external branch modules.

Replaces per-branch drone_adapter.py boilerplate with a single centralized
capture function.  Given a dotted import path to any branch's ``main()``,
captures stdout/stderr via StringIO and returns the standard drone result
dict (stdout, stderr, exit_code).
"""

from __future__ import annotations

import importlib
import sys
from io import StringIO

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler


def capture_main(
    entry_point_module: str,
    name: str,
    command: str | None = None,
    args: list[str] | None = None,
) -> dict:
    """Capture stdout/stderr from an external branch's ``main()`` function.

    Builds ``sys.argv`` as if the branch CLI was invoked directly, redirects
    stdout/stderr to StringIO buffers, calls ``main()``, then restores
    everything in a finally block.

    Args:
        entry_point_module: Dotted import path to the module containing
            ``main()`` (e.g. ``"aipass.seedgo.apps.seedgo"``).
        name: Program name for ``sys.argv[0]``.
        command: Optional subcommand (becomes ``sys.argv[1]``).
        args: Optional extra arguments appended after command.

    Returns:
        Dict with keys ``stdout``, ``stderr``, ``exit_code``.
    """
    if args is None:
        args = []

    argv_parts: list[str] = [name]
    if command is not None:
        argv_parts.append(command)
    argv_parts.extend(args)

    original_argv = sys.argv
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    captured_out = StringIO()
    captured_err = StringIO()

    try:
        sys.argv = argv_parts
        sys.stdout = captured_out
        sys.stderr = captured_err

        mod = importlib.import_module(entry_point_module)
        main_fn = getattr(mod, "main")
        exit_code = main_fn()
    except SystemExit as exc:
        exit_code = exc.code if exc.code is not None else 0
        logger.info("capture_main: SystemExit(%s) from '%s'", exit_code, entry_point_module)
    except Exception as exc:
        captured_err.write(str(exc))
        exit_code = 1
        logger.warning(
            "capture_main: exception from '%s': %s", entry_point_module, exc
        )
    finally:
        sys.argv = original_argv
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    result = {
        "stdout": captured_out.getvalue(),
        "stderr": captured_err.getvalue(),
        "exit_code": exit_code if isinstance(exit_code, int) else 1,
    }

    json_handler.log_operation(
        "generic_adapter.capture_main",
        {"entry_point": entry_point_module, "name": name, "command": command},
    )

    return result
