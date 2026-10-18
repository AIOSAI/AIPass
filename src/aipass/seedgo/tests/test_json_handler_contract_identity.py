# =================== AIPass ====================
# Name: test_json_handler_contract_identity.py
# Description: json_handler contract, identity clause: a migrated shim IS the one service (split 2026-10-08)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for every branch's apps/handlers/json/json_handler.py shim against aipass.prax.json_handler."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that handlers/aipass_standards/json_handler_check.py parses and imports

import hashlib
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import aipass.prax
from aipass.seedgo.apps.handlers.aipass_standards.json_handler_check import CANONICAL_SHIM_SHA256
from aipass.seedgo.tests.support_json_handler_contract import (
    SERVICE_IMPORT_MARKER,
    SERVICE_REDIRECT_ENV,
    handler_path,
    implementation,
    parametrized,
)

pytestmark = pytest.mark.usefixtures("quarantined_document_directories")

#: The nine names the canonical shim binds, in the spec's order.
SHIM_PUBLIC_NAMES = (
    "read_json",
    "write_json",
    "validate_json_structure",
    "get_json_path",
    "ensure_json_exists",
    "ensure_module_jsons",
    "load_json",
    "save_json",
    "log_operation",
)


# IDENTITY: a migrated shim IS the one service. ``is`` catches a branch keeping its own implementation
# behind a compatible signature, and a shim that WRAPS instead of BINDING: the service resolves its caller
# at ``sys._getframe(2)``, so one extra frame sends every log into json_handler_log.json. Unmigrated
# handlers skip by name.


def json_service_or_skip() -> Any:
    """Return the one json service, or skip when prax has not published it."""
    service = getattr(aipass.prax, "json_handler", None)
    if service is None:
        pytest.skip(
            "aipass.prax exposes no json_handler attribute yet — the one service "
            "(DPLAN-0325) has not landed, so there is no identity to assert"
        )
    return service


def shim_or_skip(branch: str) -> Any:
    """Return *branch*'s handler when it has migrated, else skip naming it.

    The discriminator is the file: a handler that does not import the service has not migrated.
    """
    source = handler_path(branch).read_text(encoding="utf-8")
    if SERVICE_IMPORT_MARKER not in source:
        pytest.skip(f"{branch} has not migrated to the one service yet — its handler does not import it")
    return implementation(branch)


@pytest.mark.parametrize("branch", parametrized())
def test_every_public_name_in_a_migrated_shim_is_the_services_own_function(branch: str):
    """Each bound name IS ``JsonHandle``'s method, not a copy that behaves like it."""
    service = json_service_or_skip()
    module = shim_or_skip(branch)

    wrong = []
    for name in SHIM_PUBLIC_NAMES:
        bound = getattr(module, name, None)
        if bound is None:
            wrong.append(f"{name}: absent")
            continue
        own = getattr(bound, "__func__", None)
        if own is None:
            wrong.append(f"{name}: a plain function, so the shim WRAPS instead of binding (frame depth shifts)")
        elif own is not getattr(service.JsonHandle, name, None):
            wrong.append(f"{name}: bound to {own!r}, not the service's own method")
    assert not wrong, f"{branch}'s shim does not bind the one service: {wrong}"


@pytest.mark.parametrize("branch", parametrized())
def test_a_migrated_shim_binds_one_handle_rooted_at_its_own_branch(branch: str):
    """All nine names share one handle, and its root is the shim's own branch."""
    json_service_or_skip()
    module = shim_or_skip(branch)

    handles = {id(getattr(module, name).__self__) for name in SHIM_PUBLIC_NAMES if hasattr(module, name)}
    assert len(handles) == 1, f"{branch} binds {len(handles)} handles across its nine names, expected one"

    handle = getattr(module, "save_json").__self__
    expected_root = handler_path(branch).parents[3]
    assert handle.branch_root == expected_root, (
        f"{branch}'s handle is rooted at {handle.branch_root}, not at its own branch {expected_root}"
    )


@pytest.mark.parametrize("branch", parametrized())
def test_a_migrated_shim_reads_the_redirect_seam_after_import_not_at_import(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Setting the env var AFTER import redirects the NEXT call."""
    json_service_or_skip()
    module = shim_or_skip(branch)

    resolver = getattr(module, "get_json_path", None)
    assert resolver is not None, f"{branch}'s shim exposes no get_json_path"

    elsewhere = tmp_path / "redirected_after_import"
    monkeypatch.setenv(SERVICE_REDIRECT_ENV, str(elsewhere))
    answer = Path(str(resolver("identity_probe", "data")))

    expected = elsewhere / branch / f"{branch}_json" / "identity_probe_data.json"
    assert answer == expected, f"{branch}: the seam set after import answered {answer}, expected {expected}"


@pytest.mark.parametrize("branch", parametrized())
def test_every_shipped_shim_is_byte_identical_to_the_pinned_canonical(branch: str):
    """One file, one hash, eighteen copies — asserted here, not only by the audit."""
    content = handler_path(branch).read_text(encoding="utf-8")
    if SERVICE_IMPORT_MARKER not in content:
        pytest.skip(f"{branch} has not migrated to the one service yet — its handler does not import it")

    measured = hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert measured == CANONICAL_SHIM_SHA256, (
        f"{branch}'s shim hashes {measured}, not the pinned canonical "
        f"{CANONICAL_SHIM_SHA256} — it is no longer the fleet's one file"
    )


@pytest.mark.parametrize("branch", parametrized())
def test_a_migrated_shims_exceptions_are_the_services_own(branch: str):
    """``InvalidDocument`` and ``WriteFailed`` ARE the service's classes."""
    service = json_service_or_skip()
    module = shim_or_skip(branch)

    wrong = []
    for name in ("InvalidDocument", "WriteFailed"):
        theirs = getattr(module, name, None)
        ours = getattr(service, name, None)
        if theirs is None:
            wrong.append(f"{name}: absent from the shim")
        elif theirs is not ours:
            wrong.append(f"{name}: {theirs!r} is not the service's {ours!r}")
    assert not wrong, f"{branch}'s shim does not re-export the service's own exceptions: {wrong}"


# The audit trail names who it can, and says so when it cannot. Depth and pseudo-frames are pinned
# upstream in prax/tests/test_repo_root.py.


class TestTheAuditTrailNamesWhoItCan:
    """``_get_caller_module_name`` answers "unknown" rather than guessing or dying."""

    def test_an_underscore_private_caller_is_not_named(self, monkeypatch: pytest.MonkeyPatch):
        """A module whose name starts with ``_`` is somebody's implementation detail."""
        service = json_service_or_skip()
        frame = SimpleNamespace(f_code=SimpleNamespace(co_filename=str(Path(tempfile.gettempdir()) / "_private.py")))

        monkeypatch.setattr(service, "sys", SimpleNamespace(_getframe=lambda _depth: frame))
        assert service._get_caller_module_name() == "unknown", (
            "the operations log named an underscore-private module as the caller"
        )

    def test_a_frame_that_cannot_be_fetched_is_unknown_and_not_a_crash(self, monkeypatch: pytest.MonkeyPatch):
        """The audit trail must never be the reason an operation fails."""
        service = json_service_or_skip()

        def _no_such_frame(_depth: int):
            raise ValueError("no such frame")

        monkeypatch.setattr(service, "sys", SimpleNamespace(_getframe=_no_such_frame))
        assert service._get_caller_module_name() == "unknown", (
            "a frame fetch that raised took the operation down with it"
        )
