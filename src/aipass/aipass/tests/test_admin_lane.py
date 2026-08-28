# =================== AIPass ====================
# Name: test_admin_lane.py
# Description: Tests for the admin-lane doctor row (DPLAN-0319 train)
# Version: 1.0.0
# Created: 2026-08-28
# Modified: 2026-08-28
# =============================================

"""Tests for admin-lane state reporting.

The rules this file exists to hold: the row NEVER errors (a dark lane is a
valid install), it NEVER names a ceremony command when the lane is dark (doctor
must not push), and it reports PRESENCE only — it must never grow into a second
implementation of @devpulse's five-leg contract.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest  # pyright: ignore[reportMissingImports]

from aipass.aipass.apps.handlers import admin_lane
from aipass.aipass.apps.handlers.admin_lane import (
    ADMIN_HOLDER,
    admin_lane_state,
    check_admin_lane,
)
from aipass.aipass.apps.handlers.ui.progress import GLYPH_FAIL, GLYPH_PASS, GLYPH_WARN


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def build_world(
    root: Path,
    *,
    key: bool = True,
    granted: bool = True,
    signed: bool = True,
    registry_flag: bool = True,
    cert_present: bool = True,
) -> Path:
    """Lay out a registry + devpulse cert, one knob per observable fact.

    Declarative and re-callable: each call fully restates the world, so a test
    may build several states in a row from one tmp_path.
    """
    holder_dir = root / "src" / "aipass" / ADMIN_HOLDER
    holder_dir.mkdir(parents=True, exist_ok=True)

    entry: dict[str, object] = {"name": ADMIN_HOLDER, "path": str(holder_dir)}
    if registry_flag:
        entry["admin"] = True
    registry = root / "AIPASS_REGISTRY.json"
    registry.write_text(
        json.dumps({"metadata": {"id": "test"}, "branches": [entry, {"name": "aipass"}]}),
        encoding="utf-8",
    )

    artifacts = holder_dir / "artifacts"
    artifacts.mkdir(exist_ok=True)
    cert_path = artifacts / "birth_certificate.json"
    if cert_present:
        cert: dict[str, object] = {"owner": ADMIN_HOLDER, "type": "birth_certificate"}
        if granted:
            cert["privileges"] = {"admin": True, "granted_by": "patrick"}
        if signed:
            cert["signature"] = "deadbeef"
        cert_path.write_text(json.dumps(cert), encoding="utf-8")
    else:
        cert_path.unlink(missing_ok=True)

    keyfile = root / "fake_home" / ".aipass" / "admin_grant.key"
    keyfile.parent.mkdir(parents=True, exist_ok=True)
    if key:
        keyfile.write_text("0" * 64, encoding="utf-8")
    else:
        keyfile.unlink(missing_ok=True)

    return registry


@pytest.fixture()
def world(tmp_path, monkeypatch):
    """Point admin_lane at a temp registry + temp key path."""

    def _build(**kwargs):
        registry = build_world(tmp_path, **kwargs)
        monkeypatch.setattr(admin_lane, "KEY_PATH", tmp_path / "fake_home" / ".aipass" / "admin_grant.key")
        monkeypatch.setattr(admin_lane, "_registry_path", lambda: registry)
        return registry

    return _build


# ---------------------------------------------------------------------------
# State observation
# ---------------------------------------------------------------------------


def test_all_four_facts_present_reads_lit(world):
    """The fully-run ceremony reports lit."""
    world()

    status = admin_lane_state()

    assert status["state"] == "lit"
    assert (status["key"], status["granted"], status["signed"], status["registry_flag"]) == (
        True,
        True,
        True,
        True,
    )


def test_fresh_install_reads_dark(world):
    """No key, no grant, no signature, no flag — the ordinary starting state."""
    world(key=False, granted=False, signed=False, registry_flag=False, cert_present=True)

    assert admin_lane_state()["state"] == "dark"


def test_plain_cert_with_no_privileges_block_is_dark(world):
    """Citizens are born with a plain cert — that alone must not read as granted."""
    world(key=False, granted=False, signed=False, registry_flag=False)

    status = admin_lane_state()

    assert status["granted"] is False
    assert status["signed"] is False
    assert status["state"] == "dark"


@pytest.mark.parametrize(
    "knob",
    ["key", "granted", "signed", "registry_flag"],
)
def test_any_single_missing_fact_reads_partial(world, knob):
    """A half-run ceremony is named, not rounded to lit or dark.

    Parameterized across every leg because rounding a partial lane UP to lit is
    the dangerous direction — it would tell a human they are done when the
    real verify still refuses.
    """
    world(**{knob: False})

    status = admin_lane_state()

    assert status["state"] == "partial"
    assert status[knob] is False


def test_missing_cert_file_is_not_a_crash(world):
    """A citizen with no birth certificate reports dark, never raises."""
    world(key=False, registry_flag=False, cert_present=False)

    assert admin_lane_state()["state"] == "dark"


def test_unreadable_registry_is_not_a_crash(tmp_path, monkeypatch):
    """Corrupt registry degrades to dark rather than taking doctor down."""
    bad = tmp_path / "AIPASS_REGISTRY.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(admin_lane, "KEY_PATH", tmp_path / "nokey")
    monkeypatch.setattr(admin_lane, "_registry_path", lambda: bad)

    assert admin_lane_state()["state"] == "dark"


def test_no_registry_anywhere_is_not_a_crash(tmp_path, monkeypatch):
    """Outside an installation the lane reads dark, not an exception."""
    monkeypatch.setattr(admin_lane, "KEY_PATH", tmp_path / "nokey")
    monkeypatch.setattr(admin_lane, "_registry_path", lambda: None)

    assert admin_lane_state()["state"] == "dark"


def test_admin_flag_on_another_citizen_is_ignored(world, tmp_path):
    """Only the holder's entry counts — admin is single-seat by ruling."""
    registry = world(registry_flag=False)
    data = json.loads(registry.read_text(encoding="utf-8"))
    for entry in data["branches"]:
        if entry["name"] == "aipass":
            entry["admin"] = True
    registry.write_text(json.dumps(data), encoding="utf-8")

    assert admin_lane_state()["registry_flag"] is False


# ---------------------------------------------------------------------------
# The doctor row — informational, never a nag
# ---------------------------------------------------------------------------


def test_row_never_errors_in_any_state(world):
    """THE rule: a dark or partial lane is not a doctor error, ever.

    _print_doctor_groups counts any glyph that is neither PASS nor WARN as an
    error, so a wrong glyph here would turn a valid install red.
    """
    for kwargs in (
        {},
        {"key": False, "granted": False, "signed": False, "registry_flag": False},
        {"signed": False},
    ):
        world(**kwargs)
        (_label, glyph, _detail, _remediation) = check_admin_lane()[0]
        assert glyph == GLYPH_PASS
        assert glyph not in (GLYPH_FAIL, GLYPH_WARN)


def test_dark_row_names_the_doc_and_no_ceremony_command(world):
    """Doctor points at the doc. It must not push the ceremony."""
    world(key=False, granted=False, signed=False, registry_flag=False)

    (_label, _glyph, detail, remediation) = check_admin_lane()[0]

    assert "dark" in detail
    assert "admin_setup.md" in remediation
    for verb in ("keygen", "mint", "grant-admin"):
        assert verb not in remediation
        assert verb not in detail


def test_lit_row_points_at_the_authoritative_verifier(world):
    """Doctor observes; it says who adjudicates."""
    world()

    (_label, _glyph, detail, remediation) = check_admin_lane()[0]

    assert "lit" in detail
    assert "admin_grant verify" in remediation


def test_partial_row_names_the_missing_legs(world):
    """A half-run ceremony says which piece is absent, in ceremony order."""
    world(signed=False, registry_flag=False)

    (_label, _glyph, detail, remediation) = check_admin_lane()[0]

    assert "partial" in detail
    assert "signature" in detail and "registry flag" in detail
    assert "admin_setup.md" in remediation


def test_row_shape_matches_doctor_contract(world):
    """One 4-tuple — doctor builds CheckResult(*tup) straight from it."""
    world()

    rows = check_admin_lane()

    assert len(rows) == 1
    assert len(rows[0]) == 4
    assert rows[0][0] == "admin lane"


# ---------------------------------------------------------------------------
# Boundaries — this module observes, it does not adjudicate
# ---------------------------------------------------------------------------


def test_never_reimplements_the_signature_check():
    """No HMAC here. The contract has one home (@devpulse) and must keep it.

    A doctor that recomputed the signature would be a second implementation of
    a security contract, free to drift from the real one.
    """
    source = Path(admin_lane.__file__).read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.strip().startswith("#"))

    for banned in ("hmac", "hashlib", "compare_digest"):
        assert banned not in code.lower().replace("hmac-sha256", "")


def test_never_reads_key_material(world, tmp_path):
    """Presence only — the key file's CONTENT is never opened."""
    world()
    key_path = tmp_path / "fake_home" / ".aipass" / "admin_grant.key"
    real_read = Path.read_text

    def guard(self, *args, **kwargs):
        assert self != key_path, "admin_lane must never read key material"
        return real_read(self, *args, **kwargs)

    with patch.object(Path, "read_text", guard):
        assert admin_lane_state()["key"] is True


def test_does_not_import_devpulses_module():
    """No cross-branch import: devpulse owns the ceremony module."""
    source = Path(admin_lane.__file__).read_text(encoding="utf-8")
    import_lines = [ln for ln in source.splitlines() if ln.startswith(("import ", "from "))]

    assert not any("devpulse" in ln for ln in import_lines)
