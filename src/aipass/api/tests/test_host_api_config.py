# =================== AIPass ====================
# Name: test_host_api_config.py
# Description: Tests for the host API's config, face dir, baud binary and tokens — the bind gate and the store
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/host/config.py (bind gate, face dir, baud binary) and apps/handlers/host/tokens.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — hashlib.sha256 and secrets.token_urlsafe themselves, behind issue_token()
# seedgo: no-test-needed(windows_compat) — the 0o600 token file mode on Windows; the POSIX tests carry a skipif

import json
import os
import stat
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host import tokens as host_tokens
from aipass.api.tests.support_host_api import TAILNET_SHAPED, UNHELD_ADDRESS, _baud_binary, _face_bundle

# Kept local, not imported from the support module: seedgo's discarded_patch
# rule judges a target imported from this package, and this silences on purpose.
PATCH_CONFIG_LOGGER = "aipass.api.apps.handlers.host.config.logger"


class TestValidateBind:
    """The bind rule: bind what was configured, or refuse. Never widen."""

    def test_wildcard_ipv4_refused(self) -> None:
        """0.0.0.0 binds fine on every machine — that is exactly why it is refused."""
        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BindRefused) as exc:
            host_config.validate_bind("0.0.0.0", 8787)

        assert "wildcard" in str(exc.value).lower()

    def test_wildcard_ipv6_refused(self) -> None:
        """:: is the same hazard in IPv6 clothing."""
        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BindRefused):
            host_config.validate_bind("::", 8787)

    def test_hostname_refused(self) -> None:
        """A name is ambiguous, and an ambiguous bind is how private becomes public."""
        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BindRefused) as exc:
            host_config.validate_bind("localhost", 8787)

        assert "hostname" in str(exc.value).lower()

    def test_empty_address_refused(self) -> None:
        """No configured address must never mean 'pick something'."""
        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BindRefused):
            host_config.validate_bind("", 8787)

    def test_address_not_held_by_machine_refused(self) -> None:
        """The address the config names is the address we bind, or we stop."""
        with patch(PATCH_CONFIG_LOGGER), patch.object(host_config, "LOOPBACK_ONLY", False):
            with pytest.raises(host_config.BindRefused) as exc:
                host_config.validate_bind(UNHELD_ADDRESS, 8787)

        assert "not available" in str(exc.value).lower()

    def test_the_loopback_gate_is_open(self) -> None:
        """The loopback-only gate is open: LOOPBACK_ONLY is False."""
        assert host_config.LOOPBACK_ONLY is False

    def test_closing_the_gate_still_refuses_non_loopback(self) -> None:
        """
        The refusal path survives the flip and can be switched back on.

        A gate that is deleted the moment it opens cannot be closed again if the
        review's conditions ever stop holding.
        """
        with patch.object(host_config, "LOOPBACK_ONLY", True):
            with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BindRefused) as exc:
                host_config.validate_bind(TAILNET_SHAPED, 8787)

        assert "loopback-only" in str(exc.value).lower()
        assert "security review" in str(exc.value).lower()

    def test_opening_the_gate_did_not_open_the_wildcard(self) -> None:
        """
        THE test that matters after the flip, and the ratified NO-GO in code.

        LOOPBACK_ONLY governs one refusal; the wildcard check is unconditional.
        """
        for wildcard in ("0.0.0.0", "::"):
            with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BindRefused) as exc:
                host_config.validate_bind(wildcard, 8787)

            assert "every" in str(exc.value).lower()

    def test_opening_the_gate_did_not_open_hostnames(self) -> None:
        """An ambiguous bind is still refused — the flip changed one rule only."""
        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BindRefused) as exc:
            host_config.validate_bind("localhost", 8787)

        assert "literal ip" in str(exc.value).lower()

    def test_opening_the_gate_did_not_open_unheld_addresses(self) -> None:
        """Still probe-bound: an address this machine does not hold is refused."""
        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BindRefused) as exc:
            host_config.validate_bind(UNHELD_ADDRESS, 8787)

        assert "not available" in str(exc.value).lower()

    def test_loopback_accepted(self) -> None:
        """
        127.0.0.1 is the Phase 1 target and must pass cleanly.

        The gate returns None, so the oracle is the contrast with a refused address.
        """
        with patch(PATCH_CONFIG_LOGGER):
            assert host_config.validate_bind("127.0.0.1", 8787) is None

            with pytest.raises(host_config.BindRefused):
                host_config.validate_bind(TAILNET_SHAPED, 8787)

    def test_tailnet_shaped_address_still_refused_when_gate_lifted_but_absent(self) -> None:
        """Lifting the gate does not lower the standard: the machine must hold it."""
        with patch(PATCH_CONFIG_LOGGER), patch.object(host_config, "LOOPBACK_ONLY", False):
            with pytest.raises(host_config.BindRefused) as exc:
                host_config.validate_bind(TAILNET_SHAPED, 8787)

        assert "not available" in str(exc.value).lower()

    @pytest.mark.parametrize("port", [0, -1, 65536, 99999])
    def test_port_out_of_range_refused(self, port: int) -> None:
        """Ports outside 1-65535 are refused before anything touches a socket."""
        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BindRefused):
            host_config.validate_bind("127.0.0.1", port)

    def test_non_integer_port_refused(self) -> None:
        """A string port is a config error, not something to coerce."""
        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BindRefused):
            host_config.validate_bind("127.0.0.1", "8787")  # type: ignore[arg-type]

    def test_bool_port_refused(self) -> None:
        """True is an int in Python. It is not a port."""
        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BindRefused):
            host_config.validate_bind("127.0.0.1", True)  # type: ignore[arg-type]


class TestConfig:
    """Config load/save behaviour."""

    def test_defaults_when_store_absent(self, store: Path) -> None:
        """A missing config yields loopback defaults — safe, not silent."""
        with patch(PATCH_CONFIG_LOGGER):
            config = host_config.load_config()

        assert config["host"] == host_config.DEFAULT_HOST
        assert config["port"] == host_config.DEFAULT_PORT

    def test_stored_values_merge_over_defaults(self, store: Path) -> None:
        """A config carrying only a port still gets the loopback host."""
        with patch(PATCH_CONFIG_LOGGER):
            host_config.save_config({"port": 9999})
            config = host_config.load_config()

        assert config["port"] == 9999
        assert config["host"] == host_config.DEFAULT_HOST

    def test_non_dict_store_falls_back_to_defaults(self, store: Path) -> None:
        """A corrupted config must not produce a half-applied bind."""
        provider_dir = store / host_config.CONFIG_PROVIDER
        provider_dir.mkdir(parents=True, exist_ok=True)
        (provider_dir / f"{host_config.CONFIG_SLUG}.json").write_text('"not-an-object"', encoding="utf-8")

        with patch(PATCH_CONFIG_LOGGER):
            config = host_config.load_config()

        assert config["host"] == host_config.DEFAULT_HOST

    def test_save_config_round_trips(self, store: Path) -> None:
        """What was saved is what loads back."""
        with patch(PATCH_CONFIG_LOGGER):
            host_config.save_config({"host": "127.0.0.1", "port": 8080})
            config = host_config.load_config()

        assert config == {"host": "127.0.0.1", "port": 8080}


class TestFaceDir:
    """
    FPLAN-0587 row 1: where the phone face is served from, stored beside the bind.

    A value that would not serve is refused at write time, and nothing is stored.
    """

    def test_unset_by_default(self, store: Path) -> None:
        """No face_dir stored is None — the checkout default is face.py's call."""
        assert host_config.face_dir() is None

    def test_a_built_bundle_is_stored_and_read_back(self, store: Path, tmp_path: Path) -> None:
        """Stored as a plain string in the existing config, returned as a Path."""
        bundle = _face_bundle(tmp_path / "face")

        with patch(PATCH_CONFIG_LOGGER):
            stored = host_config.set_face_dir(bundle)

        assert stored == bundle
        assert host_config.face_dir() == bundle
        assert host_config.load_config()["face_dir"] == str(bundle)

    def test_a_relative_path_is_refused(self, store: Path) -> None:
        """Relative to what? The server's working directory is nobody's decision."""
        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.FaceDirRefused, match="absolute"):
            host_config.set_face_dir(Path("projects") / "baud" / "app" / "dist-phone")

        assert host_config.face_dir() is None

    def test_a_missing_directory_is_refused(self, store: Path, tmp_path: Path) -> None:
        """A path that does not exist yet stores nothing — no config file at all."""
        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.FaceDirRefused, match="not a directory"):
            host_config.set_face_dir(tmp_path / "never-built")

        assert not (store / host_config.CONFIG_PROVIDER / f"{host_config.CONFIG_SLUG}.json").exists()

    def test_the_entry_file_itself_is_refused(self, store: Path, tmp_path: Path) -> None:
        """Naming phone.html instead of the directory holding it is an easy slip."""
        bundle = _face_bundle(tmp_path / "face")

        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.FaceDirRefused, match="not a directory"):
            host_config.set_face_dir(bundle / host_config.FACE_ENTRY)

        assert host_config.face_dir() is None

    def test_a_directory_without_phone_html_is_refused(self, store: Path, tmp_path: Path) -> None:
        """An unbuilt or wrong directory would answer every navigation with a 503."""
        empty = tmp_path / "empty"
        empty.mkdir()

        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.FaceDirRefused, match="phone.html"):
            host_config.set_face_dir(empty)

        assert host_config.face_dir() is None

    def test_the_refusal_is_a_value_error(self) -> None:
        """Callers outside this branch (@aipass's installer) may catch ValueError."""
        assert issubclass(host_config.FaceDirRefused, ValueError)

    def test_a_refusal_leaves_the_stored_dir_alone(self, store: Path, tmp_path: Path) -> None:
        """Refused means nothing was written — not that the old value was dropped."""
        bundle = _face_bundle(tmp_path / "face")

        with patch(PATCH_CONFIG_LOGGER):
            host_config.set_face_dir(bundle)
            with pytest.raises(host_config.FaceDirRefused):
                host_config.set_face_dir(tmp_path / "never-built")

        assert host_config.face_dir() == bundle

    def test_clearing_removes_the_key(self, store: Path, tmp_path: Path) -> None:
        """None clears: the key is gone, not stored as null."""
        with patch(PATCH_CONFIG_LOGGER):
            host_config.set_face_dir(_face_bundle(tmp_path / "face"))
            cleared = host_config.set_face_dir(None)

        assert cleared is None
        assert host_config.face_dir() is None
        assert "face_dir" not in host_config.load_config()

    def test_clearing_when_unset_writes_nothing(self, store: Path) -> None:
        """A clear with nothing to clear must not create a config file nobody asked for."""
        with patch(PATCH_CONFIG_LOGGER):
            assert host_config.set_face_dir(None) is None

        assert not (store / host_config.CONFIG_PROVIDER / f"{host_config.CONFIG_SLUG}.json").exists()

    def test_the_bind_survives_a_face_dir_write(self, store: Path, tmp_path: Path) -> None:
        """One store, two settings: writing one keeps the other."""
        bundle = _face_bundle(tmp_path / "face")

        with patch(PATCH_CONFIG_LOGGER):
            host_config.save_config({"host": "127.0.0.1", "port": 9100})
            host_config.set_face_dir(bundle)
            config = host_config.load_config()

        assert config == {"host": "127.0.0.1", "port": 9100, "face_dir": str(bundle)}


posix_permissions = pytest.mark.skipif(sys.platform == "win32", reason="os.access X_OK is always true on Windows")


class TestBaudBin:
    """The baud binary the host lanes exec, stored beside face_dir."""

    def test_unset_by_default(self, store: Path) -> None:
        """No baud_bin stored is None — the automatic lookup is fleet.py's call."""
        assert host_config.baud_bin() is None

    def test_an_executable_file_is_stored_and_read_back(self, store: Path, tmp_path: Path) -> None:
        """Stored as a plain string in the existing config, returned as a Path."""
        binary = _baud_binary(tmp_path / "bin" / "baud-cli")

        with patch(PATCH_CONFIG_LOGGER):
            stored = host_config.set_baud_bin(binary)

        assert stored == binary
        assert host_config.baud_bin() == binary
        assert host_config.load_config()["baud_bin"] == str(binary)

    def test_a_relative_path_is_refused(self, store: Path) -> None:
        """Leg one: relative to the server's working directory is nobody's decision."""
        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BaudBinRefused, match="absolute"):
            host_config.set_baud_bin(Path("bin") / "baud-cli")

        assert host_config.baud_bin() is None

    def test_a_missing_file_is_refused(self, store: Path, tmp_path: Path) -> None:
        """Leg two: nothing is there — and no config file is created either."""
        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BaudBinRefused, match="does not exist"):
            host_config.set_baud_bin(tmp_path / "never-installed")

        assert not (store / host_config.CONFIG_PROVIDER / f"{host_config.CONFIG_SLUG}.json").exists()

    def test_a_directory_is_refused(self, store: Path, tmp_path: Path) -> None:
        """Leg three: a directory exists and carries the x bit, and is still not a binary."""
        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BaudBinRefused, match="not a regular file"):
            host_config.set_baud_bin(tmp_path)

        assert host_config.baud_bin() is None

    @posix_permissions
    def test_a_file_without_the_executable_bit_is_refused(self, store: Path, tmp_path: Path) -> None:
        """Leg four: a download nobody chmodded would fail at every exec instead."""
        binary = _baud_binary(tmp_path / "baud-cli", mode=0o644)

        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BaudBinRefused, match="not executable"):
            host_config.set_baud_bin(binary)

        assert host_config.baud_bin() is None

    def test_the_refusal_is_a_value_error(self) -> None:
        """@aipass's installer may catch ValueError, as it does for the face dir."""
        assert issubclass(host_config.BaudBinRefused, ValueError)

    def test_a_refusal_leaves_the_stored_binary_alone(self, store: Path, tmp_path: Path) -> None:
        """Refused means nothing was written — not that the old value was dropped."""
        binary = _baud_binary(tmp_path / "baud-cli")

        with patch(PATCH_CONFIG_LOGGER):
            host_config.set_baud_bin(binary)
            with pytest.raises(host_config.BaudBinRefused):
                host_config.set_baud_bin(tmp_path / "never-installed")

        assert host_config.baud_bin() == binary

    def test_clearing_removes_the_key(self, store: Path, tmp_path: Path) -> None:
        """None clears: the key is gone, not stored as null."""
        with patch(PATCH_CONFIG_LOGGER):
            host_config.set_baud_bin(_baud_binary(tmp_path / "baud-cli"))
            cleared = host_config.set_baud_bin(None)

        assert cleared is None
        assert host_config.baud_bin() is None
        assert "baud_bin" not in host_config.load_config()

    def test_clearing_when_unset_writes_nothing(self, store: Path) -> None:
        """A clear with nothing to clear must not create a config file nobody asked for."""
        with patch(PATCH_CONFIG_LOGGER):
            assert host_config.set_baud_bin(None) is None

        assert not (store / host_config.CONFIG_PROVIDER / f"{host_config.CONFIG_SLUG}.json").exists()

    def test_the_face_dir_survives_a_baud_bin_write_and_clear(self, store: Path, tmp_path: Path) -> None:
        """One store, three settings: writing or clearing one keeps the others."""
        bundle = _face_bundle(tmp_path / "face")

        with patch(PATCH_CONFIG_LOGGER):
            host_config.set_face_dir(bundle)
            host_config.set_baud_bin(_baud_binary(tmp_path / "baud-cli"))
            host_config.set_baud_bin(None)
            config = host_config.load_config()

        assert config["face_dir"] == str(bundle)
        assert "baud_bin" not in config


class TestIssueToken:
    """Minting: the raw value exists once and is never stored."""

    def test_raw_value_is_not_in_the_store(self, store: Path) -> None:
        """A reader of the token file must not be able to authenticate with it."""
        _, raw = host_tokens.issue_token("pixel-8")

        stored = (store / host_tokens.TOKEN_PROVIDER / f"{host_tokens.TOKEN_SLUG}.json").read_text(encoding="utf-8")
        assert raw not in stored

    def test_store_holds_a_sha256_hash(self, store: Path) -> None:
        """The stored digest is the sha256 of the raw value, nothing reversible."""
        import hashlib

        _, raw = host_tokens.issue_token("pixel-8")
        records = host_tokens.load_tokens()

        assert records[0]["hash"] == hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def test_record_carries_expected_fields(self, store: Path) -> None:
        """The record shape the CLI and the auth layer both rely on."""
        record, _ = host_tokens.issue_token("pixel-8", "operate")

        assert record["label"] == "pixel-8"
        assert record["scope"] == "operate"
        assert record["revoked"] is False
        assert record["id"]
        assert record["created"]

    def test_last_used_is_never_written_in_phase_1(self, store: Path) -> None:
        """Reservation, not a feature: a per-request write needs Phase 5 locking."""
        record, raw = host_tokens.issue_token("pixel-8")
        host_tokens.verify_token(raw)

        assert host_tokens.load_tokens()[0]["last_used"] is None
        assert record["last_used"] is None

    def test_empty_label_refused(self, store: Path) -> None:
        """An unlabelled token cannot be revoked with confidence."""
        with pytest.raises(host_tokens.TokenError):
            host_tokens.issue_token("   ")

    def test_unknown_scope_refused(self, store: Path) -> None:
        """Scope is enumerated; a typo must not silently become read."""
        with pytest.raises(host_tokens.TokenError) as exc:
            host_tokens.issue_token("pixel-8", "admin")

        assert "scope" in str(exc.value).lower()

    def test_two_tokens_are_distinct_and_both_verify(self, store: Path) -> None:
        """Issuing a second device must not disturb the first."""
        _, first = host_tokens.issue_token("pixel-8")
        _, second = host_tokens.issue_token("ipad")

        assert first != second
        assert host_tokens.verify_token(first) is not None
        assert host_tokens.verify_token(second) is not None

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
    def test_token_file_is_0600(self, store: Path) -> None:
        """The store sits at 0600 like every other secret this branch writes."""
        host_tokens.issue_token("pixel-8")
        path = store / host_tokens.TOKEN_PROVIDER / f"{host_tokens.TOKEN_SLUG}.json"

        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


class TestSaveTokens:
    """The store envelope, written directly."""

    def test_writes_versioned_envelope(self, store: Path) -> None:
        """Records live under a version key so a later reader need not guess."""
        host_tokens.save_tokens([{"id": "abc", "label": "x", "scope": "read", "hash": "h", "revoked": False}])

        raw = (store / host_tokens.TOKEN_PROVIDER / f"{host_tokens.TOKEN_SLUG}.json").read_text(encoding="utf-8")
        envelope = json.loads(raw)

        assert envelope["version"] == host_tokens.STORE_VERSION
        assert envelope["tokens"][0]["id"] == "abc"

    def test_round_trips_through_load(self, store: Path) -> None:
        """What save writes, load reads back."""
        records = [{"id": "abc", "label": "x", "scope": "read", "hash": "h", "revoked": False}]
        host_tokens.save_tokens(records)

        assert host_tokens.load_tokens() == records

    def test_overwrites_rather_than_appends(self, store: Path) -> None:
        """A full-list write replaces the store — no ghost records survive."""
        host_tokens.save_tokens([{"id": "one"}, {"id": "two"}])
        host_tokens.save_tokens([{"id": "three"}])

        assert [record["id"] for record in host_tokens.load_tokens()] == ["three"]


class TestVerifyToken:
    """Verification, and the revocation property the phone lane depends on."""

    def test_accepts_the_issued_value(self, store: Path) -> None:
        """The happy path: the value we handed out resolves to its record."""
        record, raw = host_tokens.issue_token("pixel-8")

        assert host_tokens.verify_token(raw)["id"] == record["id"]  # type: ignore[index]

    def test_rejects_unknown_value(self, store: Path) -> None:
        """A value we never issued authenticates nothing."""
        host_tokens.issue_token("pixel-8")

        assert host_tokens.verify_token("not-a-real-token") is None

    @pytest.mark.parametrize("value", ["", None, 12345, b"bytes"])
    def test_rejects_empty_and_non_string(self, store: Path, value: Any) -> None:
        """Junk input is denied, never crashed on."""
        host_tokens.issue_token("pixel-8")

        assert host_tokens.verify_token(value) is None

    def test_revoked_token_rejected_without_restart(self, store: Path) -> None:
        """THE property: revocation lands on the next verification, no restart."""
        record, raw = host_tokens.issue_token("pixel-8")
        assert host_tokens.verify_token(raw) == record

        host_tokens.revoke_token(record["id"])

        assert host_tokens.verify_token(raw) is None

    def test_malformed_store_denies_everything(self, store: Path) -> None:
        """A broken store must fail closed — deny all, never admit one."""
        _, raw = host_tokens.issue_token("pixel-8")

        path = store / host_tokens.TOKEN_PROVIDER / f"{host_tokens.TOKEN_SLUG}.json"
        path.write_text(json.dumps(["not", "an", "envelope"]), encoding="utf-8")

        assert host_tokens.verify_token(raw) is None


class TestRevokeToken:
    """Revocation bookkeeping."""

    def test_unknown_id_returns_false(self, store: Path) -> None:
        """Revoking something that does not exist is a no-op, reported honestly."""
        host_tokens.issue_token("pixel-8")

        assert host_tokens.revoke_token("does-not-exist") is False

    def test_already_revoked_returns_false(self, store: Path) -> None:
        """A second revoke changes nothing and says so."""
        record, _ = host_tokens.issue_token("pixel-8")
        host_tokens.revoke_token(record["id"])

        assert host_tokens.revoke_token(record["id"]) is False

    def test_list_tokens_never_exposes_the_hash(self, store: Path) -> None:
        """Display records carry no material an attacker could work from."""
        host_tokens.issue_token("pixel-8")

        assert all("hash" not in record for record in host_tokens.list_tokens())


class TestScopes:
    """operate implies read; nothing implies operate but operate."""

    def test_operate_implies_read(self) -> None:
        """An operate token can perform read actions."""
        assert host_tokens.scope_allows("operate", "read") is True

    def test_read_does_not_imply_operate(self) -> None:
        """A read token must never reach a destructive verb."""
        assert host_tokens.scope_allows("read", "operate") is False

    def test_unknown_scope_allows_nothing(self) -> None:
        """A corrupted scope field denies rather than defaults."""
        assert host_tokens.scope_allows("wizard", "read") is False
