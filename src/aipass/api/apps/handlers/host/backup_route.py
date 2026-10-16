# =================== AIPass ====================
# Name: backup_route.py
# Description: Host API Backup Routes — the backup door's three routes, hung on the app
# Version: 1.0.0
# Created: 2026-10-16
# Modified: 2026-10-16
# =============================================
# pyright: reportMissingImports=false, reportInvalidTypeForm=false, reportOptionalCall=false
# The suppressions cover the optional-dependency placeholders, as in server.py:
# without the [host] extra these names are None, and register() is only ever
# called from create_app(), which refuses first when the extra is missing.

"""
Host API Backup Routes

The backup door (DPLAN-0411): POST /v1/backup/run, GET /v1/backup/job and GET
/v1/backup/status. The answers are backup.py's; this file is the glue that hangs
them on the app. Here and not in server.py, which sits at its 1500-line cap.

The run is operate scope and answers 202 with the job; the two reads are read
scope. Every refusal leaves through the server's one envelope.

Functions:
    register() - Add the three backup routes to an app
"""

from typing import Any, Callable, Dict, Tuple

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import backup as host_backup

try:
    from fastapi import Body, Depends, Query
except ImportError as e:
    # server.py warns about the missing extra; register() is never reached.
    logger.debug("[host_api] backup route libraries not available: %s", e)
    Body = None  # type: ignore[assignment, misc]
    Depends = None  # type: ignore[assignment, misc]
    Query = None  # type: ignore[assignment, misc]


def register(app: Any, deny: Callable[..., Any], require_scope: Callable[[str], Any]) -> None:
    """
    Add the three backup routes to *app*.

    Args:
        app: The FastAPI app.
        deny: server._deny, so every refusal leaves through the one envelope.
        require_scope: server.require_scope, the bearer dependency at a scope.
    """

    def _answered(outcome: Tuple[int, Dict[str, Any]]) -> Dict[str, Any]:
        status, body = outcome
        if status != 200:
            raise deny(status, body.pop("code"), body.pop("message"), **body)
        return body

    # def, not async: the run resolves the project (a census exec for a foreign
    # one) and the job table is guarded by a threading lock, not by the loop.
    @app.post("/v1/backup/run", status_code=202)
    def backup_run(
        payload: dict = Body(default={}),
        record: dict = Depends(require_scope("operate")),
    ) -> dict:
        """Start one lane for one project. 202 with the running job."""
        project = str(payload.get("project") or "")
        lane = str(payload.get("lane") or "")
        return _answered(host_backup.answer(host_backup.start_run, project, lane))

    @app.get("/v1/backup/job")
    def backup_job(
        job_id: str = Query(default="", alias="id"),
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """One job: running, done or failed. 404 job_unknown once it is forgotten."""
        return _answered(host_backup.answer(host_backup.read_job, job_id))

    @app.get("/v1/backup/status")
    def backup_status(
        project: str = "",
        sizes: bool = False,
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """@backup's status for a project, plus this server's running jobs for it."""
        return _answered(host_backup.answer(host_backup.read_status, project, sizes))

    json_handler.log_operation("host_api_backup_routes_registered", {"lanes": list(host_backup.LANES)})
