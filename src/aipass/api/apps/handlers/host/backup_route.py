# =================== AIPass ====================
# Name: backup_route.py
# Description: Host API Backup Routes — the backup door's four routes, hung on the app
# Version: 1.1.1
# Created: 2026-10-16
# Modified: 2026-10-17
# =============================================
# pyright: reportMissingImports=false, reportInvalidTypeForm=false, reportOptionalCall=false
# The suppressions cover the optional-dependency placeholders, as in server.py:
# without the [host] extra these names are None, and register() is only ever
# called from create_app(), which refuses first when the extra is missing.

"""
Host API Backup Routes
Here and not in server.py, which sits at its 1500-line cap. Reference: docs/host_surfaces.md"""

from typing import Any, Callable, Dict, Tuple

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import backup as host_backup

try:
    from fastapi import Body, Depends, Query
except ImportError as e:
    logger.debug("[host_api] backup route libraries not available: %s", e)
    Body = None  # type: ignore[assignment, misc]
    Depends = None  # type: ignore[assignment, misc]
    Query = None  # type: ignore[assignment, misc]


def register(app: Any, deny: Callable[..., Any], require_scope: Callable[[str], Any]) -> None:
    """Add the four backup routes to *app*."""

    def _answered(outcome: Tuple[int, Dict[str, Any]]) -> Dict[str, Any]:
        status, body = outcome
        if status != 200:
            raise deny(status, body.pop("code"), body.pop("message"), **body)
        return body

    # def, not async: a foreign project costs a census exec; the job table holds a threading lock.
    @app.post("/v1/backup/run", status_code=202)
    def backup_run(
        payload: dict = Body(default={}),
        record: dict = Depends(require_scope("operate")),
    ) -> dict:
        """Start one lane for one project. 202 with the running job."""
        project = str(payload.get("project") or "")
        lane = str(payload.get("lane") or "")
        return _answered(host_backup.answer(host_backup.start_run, project, lane))

    # def, not async: @backup's stop can wait 30 s for the lane to go.
    @app.post("/v1/backup/cancel")
    def backup_cancel(
        payload: dict = Body(default={}),
        record: dict = Depends(require_scope("operate")),
    ) -> dict:
        """Stop one lane for one project through @backup. 200 with its line; 404 not_running."""
        project = str(payload.get("project") or "")
        lane = str(payload.get("lane") or "")
        return _answered(host_backup.answer(host_backup.stop_run, project, lane))

    @app.get("/v1/backup/job")
    def backup_job(
        job_id: str = Query(default="", alias="id"),
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """One job: running, done, stopped or failed. 404 job_unknown once it is forgotten."""
        return _answered(host_backup.answer(host_backup.read_job, job_id))

    @app.get("/v1/backup/status")
    def backup_status(
        project: str = "",
        sizes: bool = False,
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """@backup's status for a project, its running list with this server's job ids."""
        return _answered(host_backup.answer(host_backup.read_status, project, sizes))

    json_handler.log_operation("host_api_backup_routes_registered", {"lanes": list(host_backup.LANES)})
