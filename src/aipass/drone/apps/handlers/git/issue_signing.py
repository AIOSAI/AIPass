# =================== AIPass ====================
# Name: issue_signing.py
# Description: Signs an upstream issue or comment with the seat and project it came from
# Version: 1.0.0
# Created: 2026-10-30
# Modified: 2026-10-30
# =============================================

"""Signs an issue or comment filed upstream from any seat, so it says where it came from."""

from __future__ import annotations

from pathlib import Path

from aipass.drone.apps.handlers.json import json_handler

# A body gh reads from a file, an editor or the browser never passes through drone to be signed.
UNSIGNABLE_BODY_FLAGS = ("-F", "--body-file", "-e", "--editor", "-w", "--web")
REFUSE_UNSIGNABLE = (
    "An issue or comment filed upstream from any seat is signed with its seat and project, "
    "so give the text with --body; --body-file, --editor and --web are not signed here."
)
SIGNATURE = "Filed through drone @git by @{caller}, project {project}."


def signed_contribution(args: list[str], caller: str, project_root: Path) -> tuple[list[str], str]:
    """The gh args with the body signed, and '' ; or [] and the refusal when the body cannot be signed."""
    if any(arg in UNSIGNABLE_BODY_FLAGS or arg.startswith("--body-file=") for arg in args):
        return [], REFUSE_UNSIGNABLE
    signature = SIGNATURE.format(caller=caller, project=project_root.name)
    json_handler.log_operation("issue_contribution_signed", {"caller": caller, "project": project_root.name})
    signed = list(args)
    for index, arg in enumerate(signed):
        if arg in ("-b", "--body") and index + 1 < len(signed):
            signed[index + 1] = f"{signed[index + 1]}\n\n{signature}"
            return signed, ""
        if arg.startswith("--body="):
            signed[index] = f"{arg}\n\n{signature}"
            return signed, ""
    return [*signed, "--body", signature], ""
