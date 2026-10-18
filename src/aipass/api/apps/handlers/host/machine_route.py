# =================== AIPass ====================
# Name: machine_route.py
# Description: Host API Machine Process Route — GET /v1/machine/processes, hung on the app
# Version: 1.0.0
# Created: 2026-10-16
# Modified: 2026-10-17
# =============================================
# pyright: reportMissingImports=false, reportInvalidTypeForm=false, reportOptionalCall=false
# The suppressions cover the optional-dependency placeholders, as in server.py:
# without the [host] extra these names are None, and register() is only ever
# called from create_app(), which refuses first when the extra is missing.

"""
Host API Machine Process Route
Here and not in server.py, which sits at its 1500-line cap. Reference: docs/host_api.md"""

from typing import Any, Callable

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import machine as host_machine

try:
    from fastapi import Depends, Request
except ImportError as e:
    logger.debug("[host_api] machine route libraries not available: %s", e)
    Depends = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]

DEFAULT_LIMIT = 20

LIMIT_PARAM = "limit"


def register(
    app: Any,
    deny: Callable[..., Any],
    logged_denial: Callable[..., Any],
    require_scope: Callable[[str], Any],
) -> None:
    """Add GET /v1/machine/processes to *app*."""

    # def, not async: the skill's sample sleeps about half a second; never put it on a poll.
    @app.get("/v1/machine/processes")
    def machine_processes(request: Request, record: dict = Depends(require_scope("read"))) -> dict:
        """The busiest processes — @skills' machine_processes(limit), relayed verbatim."""
        others = sorted(name for name in request.query_params.keys() if name != LIMIT_PARAM)
        if others:
            raise deny(
                400,
                "machine_parameters_refused",
                f"/v1/machine/processes takes only limit and drops nothing silently — received: {', '.join(others)}.",
            )

        raw = request.query_params.get(LIMIT_PARAM)
        try:
            limit = DEFAULT_LIMIT if raw is None else int(raw)
        except ValueError:
            raise deny(
                400,
                "machine_limit_refused",
                "limit must be a whole number of processes; @skills lists 1 to 100.",
            ) from None

        try:
            return host_machine.read_processes(limit)
        except host_machine.MachineRefused as e:
            raise logged_denial(e, 503, "machine_refused", reason=e.reason) from e
        except host_machine.MachineDoorFailed as e:
            # machine.py logged the particulars; the handset gets the fixed sentence.
            raise deny(503, "machine_door_failed", host_machine.PROCESSES_DOOR_FAILED) from e

    json_handler.log_operation("host_api_machine_route_registered", {"default_limit": DEFAULT_LIMIT})
