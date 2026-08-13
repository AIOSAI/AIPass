# =================== AIPass ====================
# Name: test_admin_grant.py
# Description: Tests for the birth-cert admin grant handler (FPLAN-0401)
# Version: 1.0.0
# Created: 2026-08-12
# Modified: 2026-08-12
# =============================================

"""
Admin grant contract tests — keygen, mint, and the 5-leg verify.

Every leg must fail closed with a NAMED refusal; the tamper case is the
canary the whole design exists for.
"""

import json
import os
import stat

import pytest

from aipass.devpulse.apps.handlers.owner import admin_grant


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A miniature AIPass: repo root, devpulse home, cert, registry, key."""
    repo = tmp_path / "repo"
    home = repo / "src" / "aipass" / "devpulse"
    artifacts = home / "artifacts"
    artifacts.mkdir(parents=True)

    cert_path = artifacts / "birth_certificate.json"
    cert_path.write_text(
        json.dumps(
            {
                "id": "devpulse",
                "name": "devpulse Birth Certificate",
                "type": "birth_certificate",
                "creator": "SYSTEM",
                "owner": "devpulse",
                "rarity": "unique",
                "created_at": "2026-03-07",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    registry_path = repo / "AIPASS_REGISTRY.json"
    registry_path.write_text(
        json.dumps(
            {
                "metadata": {"id": "proj-cred"},
                "branches": [
                    {"name": "devpulse", "path": str(home), "email": "@devpulse", "owner": True, "admin": True},
                    {"name": "prax", "path": str(repo / "src" / "aipass" / "prax"), "email": "@prax"},
                ],
            }
        ),
        encoding="utf-8",
    )

    key_path = tmp_path / "keys" / "admin_grant.key"
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
    monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)

    return {
        "repo": repo,
        "home": home,
        "cert": cert_path,
        "registry": registry_path,
        "key": key_path,
    }


def _ceremony(world):
    """Run keygen + mint against the fixture world."""
    ok, msg = admin_grant.generate_key(key_path=world["key"])
    assert ok, msg
    ok, msg = admin_grant.mint_grant(cert_path=world["cert"], key_path=world["key"])
    assert ok, msg


# =============================================================================
# KEYGEN
# =============================================================================


def test_keygen_creates_600_hex_key(world):
    ok, msg = admin_grant.generate_key(key_path=world["key"])
    assert ok
    content = world["key"].read_text(encoding="utf-8").strip()
    assert len(content) == 64
    bytes.fromhex(content)  # valid hex or raises
    if os.name == "posix":
        # Windows chmod only drives the read-only bit — st_mode reads 0o666
        # there no matter what keygen asks for, so 600 is a POSIX-only promise.
        mode = stat.S_IMODE(world["key"].stat().st_mode)
        assert mode == 0o600
    assert content not in msg  # key material never surfaces in messages


def test_keygen_refuses_overwrite_without_force(world):
    ok, _ = admin_grant.generate_key(key_path=world["key"])
    assert ok
    first = world["key"].read_text(encoding="utf-8")
    ok, msg = admin_grant.generate_key(key_path=world["key"])
    assert not ok
    assert "refusing" in msg
    assert world["key"].read_text(encoding="utf-8") == first
    ok, _ = admin_grant.generate_key(key_path=world["key"], force=True)
    assert ok
    assert world["key"].read_text(encoding="utf-8") != first


# =============================================================================
# MINT
# =============================================================================


def test_mint_requires_key(world):
    ok, msg = admin_grant.mint_grant(cert_path=world["cert"], key_path=world["key"])
    assert not ok
    assert "keygen" in msg


def test_mint_signs_and_preserves_existing_fields(world):
    _ceremony(world)
    cert = json.loads(world["cert"].read_text(encoding="utf-8"))
    assert cert["privileges"]["admin"] is True
    assert cert["privileges"]["granted_by"] == "patrick"
    assert cert["signature"]["algo"] == "hmac-sha256"
    # Original SYSTEM-minted identity untouched
    assert cert["creator"] == "SYSTEM"
    assert cert["rarity"] == "unique"
    assert cert["created_at"] == "2026-03-07"


def test_mint_refuses_foreign_cert(world):
    admin_grant.generate_key(key_path=world["key"])
    cert = json.loads(world["cert"].read_text(encoding="utf-8"))
    cert["owner"] = "prax"
    world["cert"].write_text(json.dumps(cert), encoding="utf-8")
    ok, msg = admin_grant.mint_grant(cert_path=world["cert"], key_path=world["key"])
    assert not ok
    assert "refusing to mint" in msg


# =============================================================================
# VERIFY — the 5 legs
# =============================================================================


def _verify(world):
    return admin_grant.verify_admin_grant(key_path=world["key"], registry_path=world["registry"])


def test_verify_happy_path(world):
    _ceremony(world)
    ok, reason = _verify(world)
    assert ok, reason
    assert reason == "admin grant verified"


def test_leg1_refuses_wrong_caller(world, monkeypatch):
    _ceremony(world)
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", "prax")
    ok, reason = _verify(world)
    assert not ok
    assert reason.startswith("leg1")


def test_leg1_refuses_unverifiable_caller(world, monkeypatch):
    _ceremony(world)
    monkeypatch.delenv("AIPASS_CALLER_BRANCH", raising=False)
    monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
    ok, reason = _verify(world)
    assert not ok
    assert reason.startswith("leg1")


def test_leg1_accepts_passport_walk(world, monkeypatch):
    _ceremony(world)
    trinity = world["home"] / ".trinity"
    trinity.mkdir()
    (trinity / "passport.json").write_text(json.dumps({"branch_info": {"branch_name": "devpulse"}}), encoding="utf-8")
    monkeypatch.delenv("AIPASS_CALLER_BRANCH", raising=False)
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(world["home"]))
    ok, reason = _verify(world)
    assert ok, reason


def test_leg2_refuses_missing_cert_at_registry_home(world):
    _ceremony(world)
    world["cert"].unlink()
    ok, reason = _verify(world)
    assert not ok
    assert reason.startswith("leg2")


def test_leg3_refuses_unprivileged_cert(world):
    admin_grant.generate_key(key_path=world["key"])
    ok, reason = _verify(world)  # cert exists but never minted
    assert not ok
    assert reason.startswith("leg3")


def test_leg4_missing_key_means_lane_dark(world):
    _ceremony(world)
    world["key"].unlink()
    ok, reason = _verify(world)
    assert not ok
    assert reason.startswith("leg4")
    assert "lane dark" in reason


def test_leg4_tampered_cert_fails_signature(world):
    """THE canary: any post-signing edit must kill the signature."""
    _ceremony(world)
    cert = json.loads(world["cert"].read_text(encoding="utf-8"))
    cert["privileges"]["granted_by"] = "impostor"
    world["cert"].write_text(json.dumps(cert), encoding="utf-8")
    ok, reason = _verify(world)
    assert not ok
    assert reason.startswith("leg4")
    assert "tampered" in reason


def test_leg4_foreign_key_fails_signature(world, tmp_path):
    _ceremony(world)
    foreign = tmp_path / "foreign.key"
    admin_grant.generate_key(key_path=foreign)
    ok, reason = admin_grant.verify_admin_grant(key_path=foreign, registry_path=world["registry"])
    assert not ok
    assert reason.startswith("leg4")


def test_leg5_refuses_without_registry_flag(world):
    _ceremony(world)
    registry = json.loads(world["registry"].read_text(encoding="utf-8"))
    registry["branches"][0].pop("admin")
    world["registry"].write_text(json.dumps(registry), encoding="utf-8")
    ok, reason = _verify(world)
    assert not ok
    assert reason.startswith("leg5")
    assert "ceremony incomplete" in reason


def test_corrupt_key_file_fails_closed(world):
    _ceremony(world)
    world["key"].write_text("not-hex-at-all\n", encoding="utf-8")
    ok, reason = _verify(world)
    assert not ok
    assert reason.startswith("leg4")


# =============================================================================
# STATUS
# =============================================================================


def test_status_never_exposes_key_material(world):
    _ceremony(world)
    state = admin_grant.grant_status(cert_path=world["cert"], key_path=world["key"], registry_path=world["registry"])
    key_hex = world["key"].read_text(encoding="utf-8").strip()
    assert key_hex not in json.dumps(state)
    assert state["key_present"] is True
    assert state["signed"] is True
