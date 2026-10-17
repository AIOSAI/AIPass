# =================== AIPass ====================
# Name: machine_route.py
# Description: Host API Machine Process Route — GET /v1/machine/processes, hung on the app
# Version: 1.0.0
# Created: 2026-10-16
# Modified: 2026-10-16
# =============================================
# pyright: reportMissingImports=false, reportInvalidTypeForm=false, reportOptionalCall=false
# The suppressions cover the optional-dependency placeholders, as in server.py:
# without the [host] extra these names are None, and register() is only ever
# called from create_app(), which refuses first when the extra is missing.

"""
Host API Machine Process Route

GET /v1/machine/processes?limit=20 (DPLAN-0414 contract C-B): the busiest
processes, @skills' machine_processes() relayed verbatim by machine.py. This
file is the glue that hangs it on the app. Here and not in server.py, which
sits at its 1500-line cap.

Read scope, like /v1/machine, with the same refusal mapping. One read is a real
CPU sample of about half a second: a sheet asks for it on open, never a poll.
`limit` is the one parameter; a value that is not a whole number is a 400, and
any other parameter is refused rather than dropped.

Functions:
    register() - Add GET /v1/machine/processes to an app
"""

from typing import Any, Callable

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import machine as host_machine

try:
    from fastapi import Depends, Request
except ImportError as e:
    # server.py warns about the missing extra; register() is never reached.
    logger.debug("[host_api] machine route libraries not available: %s", e)
    Depends = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]

#: The contract's default list length.
DEFAULT_LIMIT = 20

#: The route's one parameter.
LIMIT_PARAM = "limit"


def register(
    app: Any,
    deny: Callable[..., Any],
    logged_denial: Callable[..., Any],
    require_scope: Callable[[str], Any],
) -> None:
    """
    Add GET /v1/machine/processes to *app*.

    Args:
        app: The FastAPI app.
        deny: server._deny, so every refusal leaves through the one envelope.
        logged_denial: server._logged_denial, for a refusal whose words go to the log.
        require_scope: server.require_scope, the bearer dependency at a scope.
    """

    # def, not async: the skill's sample sleeps about half a second.
    @app.get("/v1/machine/processes")
    def machine_processes(request: Request, record: dict = Depends(require_scope("read"))) -> dict:
        """
        The busiest processes — @skills' machine_processes(limit), relayed verbatim.

        A real CPU sample of about half a second per call, so never put it on
        the monitor row's poll cadence. 503 when the skill refused (its code in
        `reason`) or its door failed, exactly as /v1/machine.
        """
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
