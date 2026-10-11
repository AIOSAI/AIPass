# =================== AIPass ====================
# Name: support_host_api.py
# Description: Shared helpers for the host API's test files (test_host_api*.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Helpers shared by test_host_api.py and test_host_api_config.py.

No test_ prefix and no Test class, so pytest never collects it. Moved here
whole from test_host_api.py when the file split along the unit under test
(api, the oversize split leg, 2026-10-08): the two addresses the bind gate is
asked about, the built face bundle and the stand-in baud binary, each used by
the config tests and the command tests alike. The patch-target strings stay
each file's own constants: seedgo's discarded_patch rule judges a target
imported from this branch's package, and those patches silence loggers on
purpose.
"""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

from pathlib import Path

from aipass.api.apps.handlers.host import config as host_config

# An address in TEST-NET-3 (RFC 5737). Guaranteed not to be a real interface.
UNHELD_ADDRESS = "203.0.113.7"
# Shaped like the tailnet address Stage 0 is ultimately aimed at.
TAILNET_SHAPED = "100.64.0.1"


def _face_bundle(directory: Path) -> Path:
    """A directory shaped like @baud's built phone bundle: phone.html at its root."""
    directory.mkdir(parents=True)
    (directory / host_config.FACE_ENTRY).write_text("<!doctype html>", encoding="utf-8")
    return directory


def _baud_binary(path: Path, mode: int = 0o755) -> Path:
    """A stand-in baud binary: a regular file with the given mode."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(mode)
    return path
