# =================== AIPass ====================
# Name: test_json_handler_contract_identity.py
# Description: json_handler contract, identity clause: a migrated shim IS the one service (split 2026-10-08)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
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


# ---------------------------------------------------------------------------
# IDENTITY: a migrated shim IS the one service, it does not merely behave like it
# ---------------------------------------------------------------------------
#
# Every other contract in this file asks what a handler DOES. Behaviour cannot
# catch the one failure the migration makes possible: a branch that quietly
# keeps its own implementation behind a compatible signature stays green on all
# of them. ``is`` catches it, and nothing else does.
#
# It also catches the hazard measured on 2026-09-03 and put in the DPLAN: the
# service resolves the calling module at ``sys._getframe(2)``, so a shim that
# WRAPS (``def log_operation(...): return _h.log_operation(...)``) instead of
# BINDING (``log_operation = _h.log_operation``) adds exactly one frame and
# silently sends every log in that branch into ``json_handler_log.json``. A
# wrapper is a plain function with no ``__func__``, so it fails here loudly, on
# the branch that wrote it, instead of appearing weeks later as an orphan
# document with no config or data sibling.
#
# Skips are per branch and named: the sweep lands branch by branch, and a
# handler that has not migrated yet is not a shim to be judged.


def json_service_or_skip() -> Any:
    """Return the one json service, or skip when prax has not published it.

    Returns:
        The ``aipass.prax.json_handler`` service module.
    """
    service = getattr(aipass.prax, "json_handler", None)
    if service is None:
        pytest.skip(
            "aipass.prax exposes no json_handler attribute yet — the one service "
            "(DPLAN-0325) has not landed, so there is no identity to assert"
        )
    return service


def shim_or_skip(branch: str) -> Any:
    """Return *branch*'s handler when it has migrated, else skip naming it.

    The discriminator is the file, not the module: a handler that does not
    import the service has not migrated and asserting identity against it would
    report the sweep's progress as a defect. A handler that DOES import it is
    judged strictly, wrapper included — that is the whole point of the axis.

    Args:
        branch: Branch to load.

    Returns:
        The branch's imported json_handler module.
    """
    source = handler_path(branch).read_text(encoding="utf-8")
    if SERVICE_IMPORT_MARKER not in source:
        pytest.skip(f"{branch} has not migrated to the one service yet — its handler does not import it")
    return implementation(branch)


@pytest.mark.parametrize("branch", parametrized())
def test_every_public_name_in_a_migrated_shim_is_the_services_own_function(branch: str):
    """Each bound name IS ``JsonHandle``'s method, not a copy that behaves like it.

    ``__func__`` is the discriminator that survives everything a compatible
    re-implementation can do: a fork with the same signature, the same return
    type and the same measured behaviour still fails, because it is a different
    object. A ``def`` wrapper fails on the same line for a different reason —
    it has no ``__func__`` at all.
    """
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
    """All nine names share one handle, and its root is the shim's own branch.

    Two properties in one assertion because they are one mistake: a shim that
    builds a handle per name, or binds a handle rooted somewhere else, writes
    another branch's documents while passing every behavioural contract above.
    The root is checked against ``parents[3]`` of the shim's own path, which is
    what ``for_module(__file__)`` is specified to compute.
    """
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
    """Setting the env var AFTER import redirects the NEXT call.

    The property that makes the whole fleet's test isolation work, and the one
    three of the four pre-migration shims did not have: they built the handler
    at module scope, so the directory was captured at import and nothing that
    ran later could move it. Measured cost of that shape elsewhere in the fleet
    — writes into live document directories during a suite run — is why this is
    pinned per branch rather than once on the service.

    The answer is checked for the branch's OWN name under the new root, so a
    service that honoured the seam but composed the wrong directory fails too.
    """
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
    """One file, one hash, eighteen copies — asserted here, not only by the audit.

    The ``json_handler`` standard refuses any handler whose sha256 is not
    ``CANONICAL_SHIM_SHA256`` (DPLAN-0325 section 3, B4), so the fleet audit
    already convicts drift. That is a checker run, not a test run: a branch
    could edit its shim and stay green in the suite all the way to CI. This
    pins the same fact where the rest of the shim contracts live.

    It is also the pin that four of the six per-branch shim tests retired
    against on 2026-09-07 (FPLAN-0491) — see the retirement record below. A
    byte-identical file cannot carry a name the canonical does not carry, and
    cannot fail to carry one it does; those claims are the hash, restated.
    """
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
    """``InvalidDocument`` and ``WriteFailed`` ARE the service's classes.

    The nine bound names are covered by identity above; the two exception names
    are not, and they are the half of the surface a caller reaches for in an
    ``except`` clause. A shim that re-declared either — even with the same name
    and the same bases — would make ``except branch.InvalidDocument`` miss the
    error the service actually raises, and every behavioural contract in this
    file would still pass.

    Folded here 2026-09-07 (FPLAN-0491) from
    ``test_the_exceptions_are_the_services_own``, which was stamped into 15
    branches; this is the one copy, over every branch.
    """
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


# ---------------------------------------------------------------------------
# RETIRED 2026-09-07 (FPLAN-0491): the six per-branch shim-pin twins
# ---------------------------------------------------------------------------
#
# Six identities were stamped into the branches' own tests/test_json_handler.py
# during the DPLAN-0325 sweep — 89 instances across 16 files, measured tonight.
# All six are now carried once, here, over every discovered branch. Nothing was
# dropped; each claim is named with where it now lives.
#
# Retired against the hash pin above (a byte-identical file cannot differ):
#   test_the_shim_carries_nothing_else (15 copies) — asserted the public name
#     set equals __all__ plus the module alias. The canonical shim's bytes fix
#     that set; a copy that added a name would fail the sha256 first.
#   test_shim_reexports_every_documented_name (13 copies) — asserted the nine
#     names plus the two exceptions are present. Presence of the nine is
#     reported by name in the identity test above ("<name>: absent"); presence
#     of the two exceptions is reported by the exceptions test above.
#
# Subsumed by a contract that was already here, and is stricter:
#   test_every_public_name_is_a_bound_method_of_the_service (14 copies) ->
#     test_every_public_name_in_a_migrated_shim_is_the_services_own_function.
#     The branch copy asserted __func__ identity for the nine; the contract
#     asserts the same and additionally names a plain-function WRAPPER as the
#     specific failure, which is the frame-depth hazard the DPLAN measured.
#   test_the_shim_is_bound_to_this_branch (13 copies) ->
#     test_a_migrated_shim_binds_one_handle_rooted_at_its_own_branch. The
#     branch copy compared branch_root.name to a hardcoded string; the contract
#     compares branch_root to parents[3] of the shim's real path AND pins that
#     all nine names share ONE handle, which the branch copy never checked.
#   test_get_path_returns_path_under_branch_json_dir (13 copies) ->
#     test_a_migrated_shim_reads_the_redirect_seam_after_import_not_at_import.
#     The branch copy asserted the answer's parent equals the fixture sandbox;
#     the contract sets the seam AFTER import and asserts the whole composed
#     path, so a shim that captured its directory at import fails there and
#     passed here.
#
# Folded into a new single contract:
#   test_the_exceptions_are_the_services_own (15 copies) ->
#     test_a_migrated_shims_exceptions_are_the_services_own, directly above.
#     This one was NOT already covered: SHIM_PUBLIC_NAMES holds the nine bound
#     methods and neither exception is among them.


# ===========================================================================
# The audit trail names who it can, and says so when it cannot
# ===========================================================================
#
# INHERITED 2026-09-04, DPLAN-0325 pair 6. These two claims lived in
# api/tests/test_host_perf.py and nowhere else in the fleet — measured before
# api swept. They were written against api's own ``_get_caller_module_name``;
# there is one implementation now, so they belong here, run once, against it.
#
# The three cases that did NOT come with them compared a ``sys._getframe(2)``
# fetch against an ``inspect.stack()`` walk. The service has no walk — it never
# had two implementations — so those had no subject to test and are archived
# with the record in api's tree, not silently dropped.
#
# Depth and pseudo-frames are already pinned upstream in
# prax/tests/test_repo_root.py and are deliberately not duplicated here.


class TestTheAuditTrailNamesWhoItCan:
    """``_get_caller_module_name`` answers "unknown" rather than guessing or dying."""

    def test_an_underscore_private_caller_is_not_named(self, monkeypatch: pytest.MonkeyPatch):
        """A module whose name starts with ``_`` is somebody's implementation detail.

        The log records who did the work so a human can go and read them. A
        private module is not an answer to that question, so the honest value
        is "unknown" — and a log that names one asserts a caller that no
        importer of this system is allowed to reach for.
        """
        service = json_service_or_skip()
        frame = SimpleNamespace(f_code=SimpleNamespace(co_filename=str(Path(tempfile.gettempdir()) / "_private.py")))

        monkeypatch.setattr(service, "sys", SimpleNamespace(_getframe=lambda _depth: frame))
        assert service._get_caller_module_name() == "unknown", (
            "the operations log named an underscore-private module as the caller"
        )

    def test_a_frame_that_cannot_be_fetched_is_unknown_and_not_a_crash(self, monkeypatch: pytest.MonkeyPatch):
        """The audit trail must never be the reason an operation fails.

        ``log_operation`` runs on the write path of every branch in the fleet.
        If naming the caller can raise, then a saved document depends on the
        interpreter's willingness to hand back a frame — which is exactly
        backwards. Anything the frame fetch throws is an "unknown", logged.
        """
        service = json_service_or_skip()

        def _no_such_frame(_depth: int):
            raise ValueError("no such frame")

        monkeypatch.setattr(service, "sys", SimpleNamespace(_getframe=_no_such_frame))
        assert service._get_caller_module_name() == "unknown", (
            "a frame fetch that raised took the operation down with it"
        )
