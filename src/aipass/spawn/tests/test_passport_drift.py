# =================== META ====================
# Name: test_passport_drift.py
# Description: DPLAN-0262 — live passport drift vs template contract (permanent canary)
# Version: 2.0.0
# Created: 2026-07-27
# Modified: 2026-08-28
# =============================================

"""Passport drift detection — DPLAN-0262, schema-tolerant for DPLAN-0319.

Templates guarantee certain branch_info/identity fields via placeholder
substitution. `spawn update` auto-heals .trinity/passport.json against a narrow
allowlist (branch_info.email, branch_info.git_branch, identity.traits — see
update_ops._heal_passport); the live scan below is the permanent canary that
says when a real passport has fallen behind what its template promises.

WHY THIS FILE ACCEPTS TWO SCHEMAS RIGHT NOW
-------------------------------------------
Passport 2.0 (DPLAN-0319) landed the new template and the new class names, but
the FLEET MIGRATION HAS NOT BEEN RUN — that live run is Patrick's own GO and
devpulse fires it (``drone @spawn migrate-passports --confirm``). Measured
2026-08-28: all 18 registered core passports still report
``document_metadata.schema_version == "1.0.0"``, 17 of them still claim the
retired class ``aipass_framework``, and every one of them still keeps
``principles`` at the TOP LEVEL instead of inside ``identity``.

So for exactly this window the template on disk is 2.0 and every live passport
is 1.x. A canary that pinned only 2.0 would be red for a reason that is not
drift — it would be red because the migration it is waiting for has not been
authorised yet. It therefore checks each passport against the contract for the
schema THAT PASSPORT DECLARES, and keeps full coverage on both.

.. _flip-to-2-0:

TO MAKE THIS FILE 2.0-ONLY AFTER THE FLEET RUN, do exactly this and nothing else
    1. set ``REQUIRE_SCHEMA_2 = True`` (the constant right below)
    2. delete ``_SCHEMA_1_CONTRACT``, ``_SCHEMA_1_CLASSES`` and ``_schema_1_drift``
    3. delete ``TestSchemaMigrationMarker``

The 2.0 lane already reads its contract off the live template, so nothing else
in here is schema-1 specific. ``test_fleet_schema_marker`` fails the moment the
whole fleet reports 2.0.0, which is the reminder to come back and do the above.
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

# --- SCHEMA 2.0 FLIP SWITCH -- see "TO MAKE THIS FILE 2.0-ONLY" in the docstring.
# False = accept schema 1.x passports as well (the pre-migration fleet).
REQUIRE_SCHEMA_2 = False

SCHEMA_2 = "2.0.0"

# The schema-1 contract, FROZEN as a literal. It is history: no template on disk
# describes it any more (the class-named template dirs retired to
# templates/.archive/), and reading it back out of an archived tree would make a
# retired directory load-bearing. Measured against all 18 live core passports on
# 2026-08-28 — every one satisfies it.
_SCHEMA_1_CONTRACT = {
    "branch_info": {"branch_name", "alias", "path", "module", "email", "created", "git_branch"},
    "identity": {"citizen_class", "role", "purpose", "what_i_do", "what_i_dont_do", "traits"},
}

# Class values a schema-1 passport is allowed to claim. These are the names the
# 2.0 rework RETIRED, so class_registry refuses them by design — a 1.x passport
# carrying one is correct-for-its-schema, not drift. "manager" appears in both
# eras (devpulse), "specialist" is accepted so a passport migrated ahead of the
# fleet run is not punished for it.
_SCHEMA_1_CLASSES = frozenset({"aipass_framework", "builder", "project_agent", "manager", "specialist"})


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


def _schema_1_drift(passport: dict) -> dict:
    """Drift for a passport still on the pre-2.0 schema.

    Same section check against the frozen 1.x key set, plus the one structural
    fact 1.x owns: ``principles`` lives at the TOP LEVEL there (R1 moves it into
    identity). Checking it keeps the field covered on both sides of the migration
    instead of going blind to it for the duration of the window.
    """
    drift = _passport_drift(passport, _SCHEMA_1_CONTRACT)
    if "principles" not in passport:
        drift["<top-level>"] = ["principles"]
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

    def test_schema_version_reader_defaults_to_pre_2_0(self):
        assert _is_schema_2({"document_metadata": {"schema_version": SCHEMA_2}}) is True
        assert _is_schema_2({"document_metadata": {"schema_version": "1.0.0"}}) is False
        assert _is_schema_2({"document_metadata": {}}) is False
        assert _is_schema_2({}) is False

    def test_schema_1_lane_still_requires_top_level_principles(self):
        """The 1.x lane is real coverage, not a hole to wait in."""
        complete = {section: dict.fromkeys(keys, "x") for section, keys in _SCHEMA_1_CONTRACT.items()}
        assert _schema_1_drift({**complete, "principles": ["p"]}) == {}
        assert _schema_1_drift(complete) == {"<top-level>": ["principles"]}


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
            elif REQUIRE_SCHEMA_2:
                report[name] = {"error": f"schema_version {_schema_version(passport)} — expected {SCHEMA_2}"}
                continue
            else:
                # Pre-migration lane: judge the passport by the schema it declares.
                declared = passport.get("identity", {}).get("citizen_class")
                if declared not in _SCHEMA_1_CLASSES:
                    report[name] = {"error": f"unknown citizen_class {declared!r} on a schema-1 passport"}
                    continue
                drift = _schema_1_drift(passport)

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


class TestSchemaMigrationMarker:
    """The flip reminder. DELETE THIS CLASS when you set REQUIRE_SCHEMA_2 = True.

    See "TO MAKE THIS FILE 2.0-ONLY" in the module docstring.
    """

    def test_fleet_schema_marker(self):
        """Fails once the whole fleet reports 2.0.0 — that is the cue to flip.

        Not an xfail and not a skip: both of those are quiet, and a silent
        reminder is a reminder nobody gets. This asserts the CURRENT, measured
        state of the world, so it goes red exactly when the world changes.
        """
        passports = _live_passports()
        if not passports:
            pytest.skip("No live registry/passports on this machine (gitignored — expected in CI)")

        laggards = sorted(name for name, passport in passports if not _is_schema_2(passport))

        assert laggards, (
            "Every live passport now reports schema_version 2.0.0 — the fleet migration has run. "
            "Make this canary 2.0-only: set REQUIRE_SCHEMA_2 = True, delete _SCHEMA_1_CONTRACT, "
            "_SCHEMA_1_CLASSES and _schema_1_drift, and delete this class. "
            "(Full instructions in the module docstring.)"
        )

    def test_the_flip_switch_matches_the_lane_actually_in_use(self):
        """REQUIRE_SCHEMA_2 and the schema-1 helpers flip together, or not at all."""
        if REQUIRE_SCHEMA_2:
            pytest.fail(
                "REQUIRE_SCHEMA_2 is True but the schema-1 lane is still here — "
                "finish the flip: delete _SCHEMA_1_CONTRACT, _SCHEMA_1_CLASSES, "
                "_schema_1_drift and TestSchemaMigrationMarker."
            )
        assert _SCHEMA_1_CONTRACT and _SCHEMA_1_CLASSES
