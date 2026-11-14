# =================== META ====================
# Name: test_registry_case_sweep.py
# Description: Case-exact registry discovery and the lanes that delegate to it
# Version: 1.1.0
# Created: 2026-08-31
# Modified: 2026-11-02
# =============================================

"""Tests for apps/handlers/registry_scan.py and the lanes that delegate to it."""

# Registry discovery is case-exact: the SUFFIX is compared case-exactly, so a plan counter is never a registry.

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that handlers/registry_scan.py and the four delegating lanes parse and import
# sentry: no-test-needed(constant) — DEFAULT_REGISTRY_NAME's text, the name find_registry falls back to
# sentry: no-test-needed(stdlib) — os.environ.get's lookup; the tests only choose what AIPASS_CALLER_CWD holds

import json

import pytest

from aipass.sentry.apps.handlers import registry_scan
from aipass.sentry.apps.handlers.audit import discovery

REAL_ANCHOR = "AIPASS_REGISTRY.json"
COUNTER_DECOY = "flow_plan_registry.json"
DOT_DECOY = ".template_registry.json"


class TestTheNameCheckIsCaseExactWithoutAnyEmulation:
    """These need no filesystem trick: a checker that folds case fails them on Linux."""

    def test_a_lowercase_counter_is_not_a_registry(self, tmp_path):
        (tmp_path / COUNTER_DECOY).write_text("{}", encoding="utf-8")
        assert registry_scan.registries_in(tmp_path) == []

    def test_a_dotted_counter_is_not_a_registry(self, tmp_path):
        """pathlib's ``*`` matches dotfiles where the glob module does not."""
        (tmp_path / DOT_DECOY).write_text("{}", encoding="utf-8")
        assert registry_scan.registries_in(tmp_path) == []

    def test_an_external_projects_own_registry_survives(self, tmp_path):
        """The suffix is matched case-exact, never the stem: Vera-Studio_REGISTRY.json is a real registry."""
        target = tmp_path / "Vera-Studio_REGISTRY.json"
        target.write_text("{}", encoding="utf-8")
        assert registry_scan.registries_in(tmp_path) == [target]

    def test_a_lowercase_stem_still_survives(self, tmp_path):
        target = tmp_path / "vera-studio_REGISTRY.json"
        target.write_text("{}", encoding="utf-8")
        assert registry_scan.registries_in(tmp_path) == [target]

    def test_a_directory_wearing_the_name_is_not_a_registry(self, tmp_path):
        (tmp_path / f"folder{registry_scan.REGISTRY_SUFFIX}").mkdir()
        assert registry_scan.registries_in(tmp_path) == []

    def test_a_missing_directory_answers_empty_rather_than_raising(self, tmp_path):
        assert registry_scan.registries_in(tmp_path / "absent") == []

    def test_the_walk_answers_none_when_nothing_is_above(self, tmp_path):
        (tmp_path / COUNTER_DECOY).write_text("{}", encoding="utf-8")
        assert registry_scan.find_registry_upward(tmp_path) is None


class TestEveryLaneReadsTheSharedReader:
    """The four private walks are gone; each name now delegates."""

    @pytest.mark.parametrize(
        "module_path",
        [
            "aipass.sentry.apps.handlers.audit.discovery",
            "aipass.sentry.apps.handlers.bypass.bypass_handler",
            "aipass.sentry.apps.handlers.diagnostics.discovery",
            "aipass.sentry.apps.handlers.readme.readme_ops",
        ],
    )
    def test_the_lane_returns_what_the_shared_reader_returns(self, module_path, monkeypatch, tmp_path):
        import importlib

        module = importlib.import_module(module_path)
        sentinel = tmp_path / "SENTINEL_REGISTRY.json"
        monkeypatch.setattr(registry_scan, "find_registry", lambda: sentinel)
        assert module._find_registry() == sentinel

    def test_the_caller_lane_delegates_too(self, monkeypatch, tmp_path):
        """Mutant: _find_caller_registries answers [] in apps/handlers/audit/discovery.py — killed."""
        caller = tmp_path / "caller"
        (caller / "callerbranch" / "apps").mkdir(parents=True)
        (caller / "callerbranch" / "apps" / "callerbranch.py").write_text("", encoding="utf-8")
        sentinel = caller / "SENTINEL_REGISTRY.json"
        sentinel.write_text(
            json.dumps({"branches": [{"name": "callerbranch", "path": "callerbranch"}]}), encoding="utf-8"
        )
        monkeypatch.setattr(registry_scan, "find_registry", lambda: tmp_path / "absent" / REAL_ANCHOR)
        monkeypatch.setattr(registry_scan, "caller_registries", lambda: [sentinel])
        found = discovery.discover_branches(include_private=True)
        assert [b["name"] for b in found] == ["callerbranch"]
