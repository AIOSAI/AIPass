# =================== META ====================
# Name: test_passport_drift.py
# Description: DPLAN-0262 — live passport drift vs template contract (permanent canary)
# Version: 2.0.0
# Created: 2026-07-27
# Modified: 2026-08-28
# =============================================

"""Passport drift detection — DPLAN-0262, 2.0-only since the DPLAN-0319 fleet run.

Templates guarantee certain branch_info/identity fields via placeholder
substitution. `spawn update` auto-heals .trinity/passport.json against a narrow
allowlist (branch_info.email, branch_info.git_branch, identity.traits — see
update_ops._heal_passport); the live scan below is the permanent canary that
says when a real passport has fallen behind what its template promises.

This file was schema-tolerant during the DPLAN-0319 window (2.0 template on
disk, 1.x fleet awaiting the migration GO). The fleet migration ran 2026-08-28
(22/22, Patrick's GO), the marker test went red on cue, and the schema-1 lane
(frozen contract, class allowlist, drift helper, marker class and the 1.x-lane
hermetic test) was removed in the same working set — the canary now judges
every live passport against the live template's contract, and any passport
declaring a pre-2.0 schema is reported as drift.
"""

import json
from pathlib import Path

import pytest

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.spawn.apps.handlers.class_registry import (
    get_available_classes,
    get_template_dir,
    resolve_template_class,
)
from aipass.spawn.apps.handlers.registry import branches_as_list, find_registry, load_registry

_CONTRACT_SECTIONS = ("branch_info", "identity")

# --- SCHEMA 2.0 FLIP SWITCH — flipped 2026-08-28 with the fleet migration.
# True = every live passport must declare schema 2.0.0; anything else is drift.
REQUIRE_SCHEMA_2 = True

SCHEMA_2 = "2.0.0"


def _schema_version(passport: dict) -> str:
    """The schema a passport DECLARES. Missing/blank reads as pre-2.0."""
    return str(passport.get("document_metadata", {}).get("schema_version", "") or "1.0.0")


def _is_schema_2(passport: dict) -> bool:
    return _schema_version(passport).startswith("2.")


def _template_contract_keys(citizen_class: str) -> dict:
    """Key set per section that citizen_class's template guarantees (schema 2.0)."""
    passport = json.loads((get_template_dir(citizen_class) / ".trinity" / "passport.json").read_text())
    return {section: set(passport.get(section, {}).keys()) for section in _CONTRACT_SECTIONS}


def _passport_drift(passport: dict, contract: dict) -> dict:
    """Template-guaranteed keys missing per section from one live passport."""
    drift = {}
    for section, required_keys in contract.items():
        missing = required_keys - set(passport.get(section, {}).keys())
        if missing:
            drift[section] = sorted(missing)
    return drift


# =============================================================================
# HERMETIC — detector logic against synthetic data, no real filesystem/registry
# =============================================================================


class TestDriftDetectorHermetic:
    """The detector itself, proven against synthetic templates/passports."""

    def test_no_drift_when_all_contract_keys_present(self):
        contract = {"branch_info": {"email", "branch_name"}, "identity": {"traits", "role"}}
        passport = {
            "branch_info": {"email": "@x", "branch_name": "x"},
            "identity": {"traits": [], "role": "x"},
        }
        assert _passport_drift(passport, contract) == {}

    def test_reports_missing_key_per_section(self):
        contract = {"branch_info": {"email", "branch_name"}, "identity": {"traits"}}
        passport = {"branch_info": {"branch_name": "x"}, "identity": {}}
        assert _passport_drift(passport, contract) == {"branch_info": ["email"], "identity": ["traits"]}

    def test_ignores_extra_live_keys_not_in_contract(self):
        """Legacy top-level `traits` (devpulse/aipass predate the identity.traits schema) isn't flagged by itself."""
        contract = {"branch_info": {"email"}, "identity": set()}
        passport = {"branch_info": {"email": "@x"}, "traits": ["curious"]}
        assert _passport_drift(passport, contract) == {}

    def test_missing_section_entirely_reports_all_keys_missing(self):
        contract = {"branch_info": {"email"}, "identity": {"traits"}}
        assert _passport_drift({}, contract) == {"branch_info": ["email"], "identity": ["traits"]}

    @pytest.mark.parametrize("citizen_class", sorted(get_available_classes()))
    def test_template_contract_includes_email_and_traits(self, citizen_class):
        """Lock what the template currently guarantees — the live scan inherits this."""
        contract = _template_contract_keys(citizen_class)
        assert "email" in contract["branch_info"]
        assert "traits" in contract["identity"]

    def test_template_contract_is_the_2_0_shape(self):
        """R1/R7: principles moved INSIDE identity, and path replaced cwd."""
        contract = _template_contract_keys("specialist")
        assert "principles" in contract["identity"]
        assert "path" in contract["branch_info"]
        assert "cwd" not in contract["branch_info"]

    def test_the_seed_stamp_is_not_drift(self):
        """TDPLAN-0017: citizenship.seed is an ADDITIVE optional field.

        This canary asks one question — "are the template's guaranteed keys
        PRESENT" — so an extra key cannot make it fire. That tolerance is by
        design (see test_ignores_extra_live_keys_not_in_contract), but a passport
        minted from a seed is the first thing the fleet carries that relies on
        it, so the property gets a pin of its own rather than an assumption.
        """
        contract = _template_contract_keys("specialist")
        passport = json.loads((get_template_dir("specialist") / ".trinity" / "passport.json").read_text())
        passport["citizenship"]["seed"] = {"version": "2.0.0", "sha256": "a" * 64}

        assert _passport_drift(passport, contract) == {}

    def test_schema_version_reader_defaults_to_pre_2_0(self):
        assert _is_schema_2({"document_metadata": {"schema_version": SCHEMA_2}}) is True
        assert _is_schema_2({"document_metadata": {"schema_version": "1.0.0"}}) is False
        assert _is_schema_2({"document_metadata": {}}) is False
        assert _is_schema_2({}) is False


# =============================================================================
# LIVE — real AIPASS_REGISTRY.json + real .trinity/passport.json files.
#
# Both are gitignored (never shipped to a clone/CI checkout — see .gitignore
# lines 26-27), so this section skips where they don't exist.
# =============================================================================


def _live_registry_path() -> Path | None:
    reg = find_registry(Path(__file__).resolve())
    return reg if reg and reg.exists() else None


def _live_passports() -> list[tuple[str, dict]]:
    """(name, passport) for every registered branch with a readable passport.

    Raises nothing and skips nothing — the callers decide what a missing file
    means for them.
    """
    reg_path = _live_registry_path()
    if reg_path is None:
        return []

    found = []
    for branch in branches_as_list(load_registry(reg_path).get("branches", [])):
        branch_path = Path(branch.get("path", ""))
        if not branch_path.is_absolute():
            branch_path = reg_path.parent / branch_path
        passport_file = branch_path / ".trinity" / "passport.json"
        if passport_file.exists():
            found.append((branch.get("name", "?"), json.loads(passport_file.read_text())))
    return found


class TestLivePassportDrift:
    """DPLAN-0262: permanent canary against the real, currently-registered passports."""

    def test_all_registered_passports_match_template_contract(self):
        reg_path = _live_registry_path()
        if reg_path is None:
            pytest.skip("No live AIPASS_REGISTRY.json on this machine (gitignored — expected in CI)")

        registry = load_registry(reg_path)
        report = {}
        for branch in branches_as_list(registry.get("branches", [])):
            name = branch.get("name", "?")
            branch_path = Path(branch.get("path", ""))
            if not branch_path.is_absolute():
                branch_path = reg_path.parent / branch_path
            passport_file = branch_path / ".trinity" / "passport.json"
            if not passport_file.exists():
                report[name] = {"error": "no .trinity/passport.json"}
                continue

            passport = json.loads(passport_file.read_text())

            if _is_schema_2(passport):
                try:
                    citizen_class = resolve_template_class(passport.get("identity", {}))
                except ValueError as exc:
                    # Scanning, not asserting-per-item: every refusal is collected
                    # so one bad passport does not hide the next nine. It goes on
                    # the record as well as into the report — this canary reads the
                    # LIVE fleet, so "spawn could not resolve X's class" is a fact
                    # about the running system, not just a test detail.
                    logger.warning("[drift-canary] %s: %s", name, exc)
                    report[name] = {"error": str(exc)}
                    continue
                drift = _passport_drift(passport, _template_contract_keys(citizen_class))
            else:
                # REQUIRE_SCHEMA_2: the fleet migrated 2026-08-28 — a passport
                # declaring anything older is drift, reported not excused.
                report[name] = {"error": f"schema_version {_schema_version(passport)} — expected {SCHEMA_2}"}
                continue

            if drift:
                report[name] = drift

        assert not report, (
            f"{len(report)} live passport(s) drifted from their declared schema's contract "
            f"(DPLAN-0262 canary; DPLAN-0319 schema window — see this module's docstring):\n"
            f"{json.dumps(report, indent=2, sort_keys=True)}"
        )

    def test_no_live_passport_leaks_an_absolute_path(self):
        """R1/{{PATH}}: a passport is tracked and public — branch_info.path is RELATIVE.

        Holds on both schemas: 1.x passports already store a relative path, and
        {{CWD}} (which rendered absolute) is gone from the 2.0 engine.
        """
        passports = _live_passports()
        if not passports:
            pytest.skip("No live registry/passports on this machine (gitignored — expected in CI)")

        offenders = {
            name: passport["branch_info"]["path"]
            for name, passport in passports
            if str(passport.get("branch_info", {}).get("path", "")).startswith(("/", "~"))
        }
        assert offenders == {}, f"absolute paths in tracked passports: {offenders}"


class TestSchema2Only:
    """The fleet is 2.0-only as of the 2026-08-28 migration run.

    Any passport declaring an older schema is reported as drift by the live
    scan above — there is no accepted pre-2.0 lane any more.
    """

    def test_every_live_passport_declares_schema_2(self):
        passports = _live_passports()
        if not passports:
            pytest.skip("No live registry/passports on this machine (gitignored — expected in CI)")

        laggards = sorted(name for name, passport in passports if not _is_schema_2(passport))
        assert laggards == [], f"passports still declaring pre-2.0 schema: {laggards}"
