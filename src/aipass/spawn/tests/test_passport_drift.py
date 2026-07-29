# =================== META ====================
# Name: test_passport_drift.py
# Description: DPLAN-0262 — live passport drift vs template contract (permanent canary)
# Version: 1.1.0
# Created: 2026-07-27
# Modified: 2026-07-27
# =============================================

"""Passport drift detection — DPLAN-0262.

Templates guarantee certain branch_info/identity fields via placeholder
substitution (e.g. {{EMAIL}}, {{TRAITS}}, added in PR#710). `spawn update`
now auto-heals .trinity/passport.json against a narrow allowlist
(branch_info.email, branch_info.git_branch, identity.traits — see
update_ops._heal_passport), but the fix-phase GO left the real fleet
untouched deliberately (heal rollout on the real fleet is a separate GO
after review). This file stays RED until that rollout runs, then goes green
and stays as the permanent canary against future drift.
"""

import json
from pathlib import Path

import pytest

from aipass.spawn.apps.handlers.class_registry import get_template_dir, resolve_template_class
from aipass.spawn.apps.handlers.registry import branches_as_list, find_registry, load_registry

_CONTRACT_SECTIONS = ("branch_info", "identity")


def _template_contract_keys(citizen_class: str) -> dict:
    """Key set per section that citizen_class's template guarantees."""
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
            "identity": {"traits": "", "role": "x"},
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

    @pytest.mark.parametrize("citizen_class", ["aipass_framework", "project_agent"])
    def test_template_contract_includes_email_and_traits(self, citizen_class):
        """Lock what the template currently guarantees — the live scan below inherits this automatically."""
        contract = _template_contract_keys(citizen_class)
        assert "email" in contract["branch_info"]
        assert "traits" in contract["identity"]


# =============================================================================
# LIVE — real AIPASS_REGISTRY.json + real .trinity/passport.json files.
#
# Both are gitignored (never shipped to a clone/CI checkout — see .gitignore
# lines 26-27), so this section skips where they don't exist and is RED where
# they do (every machine with real registered branches, e.g. this one today).
# =============================================================================


def _live_registry_path() -> Path | None:
    reg = find_registry(Path(__file__).resolve())
    return reg if reg and reg.exists() else None


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
            try:
                citizen_class = resolve_template_class(passport.get("identity", {}))
            except ValueError as exc:
                report[name] = {"error": str(exc)}
                continue

            drift = _passport_drift(passport, _template_contract_keys(citizen_class))
            if drift:
                report[name] = drift

        assert not report, (
            f"{len(report)} live passport(s) drifted from template contract "
            f"(DPLAN-0262 — auto-heal exists in update_ops._heal_passport but hasn't "
            f"been run against the real fleet yet, pending a separate rollout GO):\n"
            f"{json.dumps(report, indent=2, sort_keys=True)}"
        )
