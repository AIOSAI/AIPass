# =================== AIPass ====================
# Name: new_project_route.py
# Description: Host API New-Project Route — POST /v1/verbs/new-project, hung on the app
# Version: 1.0.0
# Created: 2026-10-16
# Modified: 2026-10-16
# =============================================
# pyright: reportMissingImports=false, reportInvalidTypeForm=false, reportOptionalCall=false
# The suppressions cover the optional-dependency placeholders, as in machine_route.py.

"""
Host API New-Project Route

POST /v1/verbs/new-project (FPLAN-0649): the phone's "+ new project". The logic
is verbs.new_project(); this file hangs it on the app, here and not in server.py,
which sits at its 1500-line cap.

Operate scope. A plain def, so the few seconds of git and spawn run in the
threadpool. Body {name, template?}; template defaults to empty. A refusal whose
sentence is this server's or the door's own exists sentence is said; any other
error answers its code's fixed sentence and a ref into this host's log.

Functions:
    register() - Add POST /v1/verbs/new-project to an app
"""

from typing import Any, Callable

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import verbs as host_verbs

try:
    from fastapi import Body, Depends
except ImportError as e:
    logger.debug("[host_api] new-project route libraries not available: %s", e)
    Body = None  # type: ignore[assignment, misc]
    Depends = None  # type: ignore[assignment, misc]


def register(
    app: Any,
    deny: Callable[..., Any],
    logged_denial: Callable[..., Any],
    require_scope: Callable[[str], Any],
) -> None:
    """
    Add POST /v1/verbs/new-project to *app*.

    Args:
        app: The FastAPI app.
        deny: server._deny, so every refusal leaves through the one envelope.
        logged_denial: server._logged_denial, for a refusal whose words go to the log.
        require_scope: server.require_scope, the bearer dependency at a scope.
    """

    @app.post("/v1/verbs/new-project")
    def verb_new_project(payload: dict = Body(default={}), record: dict = Depends(require_scope("operate"))) -> dict:
        """Create a project and its manager agent through @aipass's create_project."""
        try:
            return host_verbs.new_project(
                name=str(payload.get("name") or ""),
                template=str(payload.get("template") or "empty"),
            )
        except host_verbs.ProjectRefused as e:
            if not e.spoken:
                raise logged_denial(e, e.status, e.code) from e
            raise deny(e.status, e.code, str(e)) from e
        except host_verbs.ProjectDoorFailed as e:
            raise logged_denial(e, e.status, e.code) from e

    json_handler.log_operation("host_api_new_project_route_registered", {"path": "/v1/verbs/new-project"})
