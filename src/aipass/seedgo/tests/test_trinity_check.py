# =================== AIPass ====================
# Name: test_trinity_check.py
# Description: Unit tests for trinity_check - trinity memory file standards checker
# Version: 1.0.0
# Created: 2026-08-25
# Modified: 2026-08-25
# =============================================

"""Tests for trinity_check -- the trinity memory file standards checker.

The contract under test is devpulse ``dropbox/trinity_pattern.md``. The drift
classes exercised by the regression suite are devpulse
``dropbox/trinity_audit/MASTER_LIST.md`` D1-D16, each named in its own test so
a future blindness fails BY NAME rather than as an anonymous score drop.

THE ONE LAW, and the reason this standard exists at all: a field the checker
cannot measure is a VIOLATION, never a silent pass. The old gate measured an
unparseable shape as zero chars and passed it fleet-wide for months.
``TestTheOneLaw`` exists so that cannot come back.

Fixtures are synthetic: config and gold templates are pinned onto the module so
a config edit on @memory's branch can never turn these tests red. The single
exception is the fleet acceptance bar in ``TestFleetAcceptanceBar``, which is
deliberately coupled to live branch state -- see its docstring.
"""

import copy
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# @memory's renderer is resolved and imported at module scope, BEFORE the
# autouse infrastructure mock swaps aipass.prax in sys.modules -- it reaches
# into the real prax package at import time and cannot load through a
# MagicMock. Presence is decided by looking for the file rather than by
# catching an ImportError, so a genuine breakage in that module is never
# swallowed as "unavailable".
_RENDERER_RELATIVE = ("src", "aipass", "memory", "apps", "handlers", "tracking", "tab_renderer.py")
_compose_meta = None
_COMPOSE_META_IMPORT_ERROR = "@memory tab_renderer.py is not on disk"

for _parent in Path(__file__).resolve().parents:
    if _parent.joinpath(*_RENDERER_RELATIVE).is_file():
        from aipass.memory.apps.handlers.tracking.tab_renderer import compose_meta as _compose_meta

        _COMPOSE_META_IMPORT_ERROR = ""
        break


# ---------------------------------------------------------------------------
# Pinned fixture data -- the gold source, held here so the tests are hermetic
# ---------------------------------------------------------------------------

_BRANCH = "testbranch"

_LOCAL_USAGE = "Gold LOCAL usage text -- owned by the template, copied by nobody."
_OBSERVATIONS_USAGE = "Gold OBSERVATIONS usage text -- owned by the template, copied by nobody."

_PROSE = {
    "todos": "Sticky notes -- capture the note, stay on task.",
    "key_learnings": "Transferable technical lessons.",
    "sessions": "The chronicle -- what happened and how it ended.",
    "observations": "Patterns live for weeks.",
}

# The three pinned tab formats, byte-for-byte, at the pinned config numbers.
_TABS = {
    "todos": "⟦ rollover OFF — operational, never trimmed · cap ~10 entries · task ≤150 chars ⟧",
    "key_learnings": ("⟦ rollover ON → oldest archived to @memory · keep 15 · value ≤200 chars ⟧"),
    "sessions": ("⟦ rollover ON → oldest archived to @memory · keep 15 · summary ≤300 chars ⟧"),
    "observations": ("⟦ rollover ON → oldest archived to @memory · keep 15 · note ≤300 chars ⟧"),
}

_NO_COUNT_TAB = "⟦ rollover ON → no entry limit configured · summary ≤300 chars ⟧"

_GROUP_NAMES = (
    "Entry shapes",
    "Top-level keys",
    "Ordering & numbering",
    "Char caps",
    "File set",
    "Meta lines & _usage",
    "Receipt",
    "Todos hygiene",
    "Freshness",
)

_CONFIG = {
    "entry_limits": {
        "enabled": True,
        "enforce": True,
        "entry_types": {
            "key_learnings": {
                "file": "local.json",
                "container": "key_learnings",
                "kind": "list",
                "field": "value",
                "max_chars": 200,
            },
            "sessions": {
                "file": "local.json",
                "container": "sessions",
                "kind": "list",
                "field": "summary",
                "max_chars": 300,
            },
            "todos": {
                "file": "local.json",
                "container": "todos",
                "kind": "list",
                "field": "task",
                "max_chars": 150,
            },
            "observations": {
                "file": "observations.json",
                "container": "observations",
                "kind": "list",
                "field": "note",
                "max_chars": 300,
            },
        },
        "per_branch": {},
    },
    "rollover": {
        "defaults": {
            "local": {
                "sessions": {"count": 15, "auto_compact_cap": 3},
                "key_learnings": {"count": 15},
            },
            "observations": {"observations": {"count": 15}},
        },
        "per_branch": {},
    },
}

_TEMPLATES = {
    "local": {
        "document_metadata": {
            "document_type": "session_history",
            "document_name": "{{BRANCHNAME}}.LOCAL",
            "version": "2.0.0",
            "schema_version": "3.0.0",
            "created": "{{DATE}}",
            "last_updated": "{{DATE}}",
            "managed_by": "{{BRANCHNAME}}",
            "tags": [],
            "_usage": _LOCAL_USAGE,
        },
        "todos_meta": "{{TODOS_META}} " + _PROSE["todos"],
        "todos": [],
        "key_learnings_meta": "{{KEY_LEARNINGS_META}} " + _PROSE["key_learnings"],
        "key_learnings": [],
        "sessions_meta": "{{SESSIONS_META}} " + _PROSE["sessions"],
        "sessions": [],
    },
    "observations": {
        "document_metadata": {
            "document_type": "collaboration_patterns",
            "document_name": "{{BRANCHNAME}}.OBSERVATIONS",
            "version": "1.0.0",
            "schema_version": "3.0.0",
            "created": "{{DATE}}",
            "last_updated": "{{DATE}}",
            "managed_by": "{{BRANCHNAME}}",
            "tags": [],
            "_usage": _OBSERVATIONS_USAGE,
        },
        "guidelines": {"purpose": "gold", "chronological_order": "Newest at TOP"},
        "observations_meta": "{{OBSERVATIONS_META}} " + _PROSE["observations"],
        "observations": [],
    },
}

# Fleet acceptance bar -- see TestFleetAcceptanceBar for why this is coupled
# to live state and what to do when a branch is migrated.
_CANONICAL_OBSERVATION_BRANCHES = frozenset(
    {
        "ai_mail",
        "aipass",
        "api",
        "backup",
        "canary",
        "cli",
        "commons",
        "daemon",
        "devpulse",
        "drone",
        "flow",
        "hooks",
        "memory",
        "prax",
        "seedgo",
        "skills",
        "spawn",
        "trigger",
    }
)

_UNSET = object()


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _meta_line(section: str) -> str:
    """The full canonical *_meta value: rendered tab, then template prose."""
    return f"{_TABS[section]} {_PROSE[section]}"


def _canonical_local() -> dict:
    """A local.json that satisfies every rule in the contract."""
    return {
        "document_metadata": {
            "document_type": "session_history",
            "document_name": f"{_BRANCH}.LOCAL",
            "version": "2.0.0",
            "schema_version": "3.0.0",
            "created": "2026-01-01",
            "last_updated": "2026-08-25",
            "managed_by": _BRANCH,
            "tags": ["session_tracking", "work_log"],
            "_usage": _LOCAL_USAGE,
        },
        "todos_meta": _meta_line("todos"),
        "todos": [
            {
                "number": 2,
                "date": "2026-08-24",
                "task": "ask about the receipt lane",
                "priority": "medium",
                "status": "open",
            },
            {
                "number": 1,
                "date": "2026-08-20",
                "task": "read the trinity contract",
                "priority": "low",
                "status": "open",
            },
        ],
        "key_learnings_meta": _meta_line("key_learnings"),
        "key_learnings": [
            {
                "number": 2,
                "date": "2026-08-24",
                "key": "Fail loud",
                "value": "A field the checker cannot measure is a violation, never a silent pass.",
            },
            {
                "number": 1,
                "date": "2026-08-20",
                "key": "One source",
                "value": "Numbers come from config, prose comes from the template, nothing carries a copy.",
            },
        ],
        "sessions_meta": _meta_line("sessions"),
        "sessions": [
            {
                "number": 2,
                "date": "2026-08-25",
                "summary": "Wrote the trinity checker suite.",
                "status": "completed",
                "tags": ["trinity"],
            },
            {
                "number": 1,
                "date": "2026-08-20",
                "summary": "Read the contract end to end.",
                "status": "completed",
            },
        ],
    }


def _canonical_observations() -> dict:
    """An observations.json that satisfies every rule in the contract."""
    return {
        "document_metadata": {
            "document_type": "collaboration_patterns",
            "document_name": f"{_BRANCH}.OBSERVATIONS",
            "version": "1.0.0",
            "schema_version": "3.0.0",
            "created": "2026-01-01",
            "last_updated": "2026-08-25",
            "managed_by": _BRANCH,
            "tags": ["collaboration", "patterns"],
            "_usage": _OBSERVATIONS_USAGE,
        },
        "guidelines": {"purpose": "gold", "chronological_order": "Newest at TOP"},
        "observations_meta": _meta_line("observations"),
        "observations": [
            {
                "number": 2,
                "date": "2026-08-25",
                "note": "User wants initial tests run before handover.",
                "tags": ["verification"],
            },
            {
                "number": 1,
                "date": "2026-08-20",
                "note": "User steers by measured numbers, never by claims.",
                "tags": [],
            },
        ],
    }


def _canonical_receipt() -> dict:
    """A .template_version.json matching the pinned gold schema versions."""
    return {
        "template_versions": {"local": "3.0.0", "observations": "3.0.0"},
        "stamped": "2026-08-25T21:00:00",
        "stamped_by": "memory push",
        "config_rendered": "2026-08-25T21:00:00",
    }


def _write_doc(path: Path, payload) -> None:
    """Write one fixture document.

    ``None`` leaves the file absent (missing-file cases) and a ``str`` payload
    is written raw, which is how the malformed-JSON cases are built.
    """
    if payload is None:
        return
    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")


def _write_branch(root: Path, local=_UNSET, observations=_UNSET, receipt=_UNSET, name: str = _BRANCH) -> Path:
    """Build a branch directory with a .trinity/ holding the five canonicals."""
    branch = root / name
    trinity = branch / ".trinity"
    trinity.mkdir(parents=True, exist_ok=True)
    (trinity / "passport.json").write_text("{}\n", encoding="utf-8")
    (trinity / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    _write_doc(trinity / "local.json", _canonical_local() if local is _UNSET else local)
    _write_doc(trinity / "observations.json", _canonical_observations() if observations is _UNSET else observations)
    _write_doc(trinity / ".template_version.json", _canonical_receipt() if receipt is _UNSET else receipt)
    return branch


def _group(result: dict, name: str) -> dict:
    """Pull one named group out of a check_branch result."""
    found = [check for check in result["checks"] if check["name"] == name]
    assert found, f"no group named {name!r} in {[check['name'] for check in result['checks']]}"
    return found[0]


def _assert_failed(check: dict, *fragments: str) -> None:
    """Assert a group failed AND that its message says why."""
    assert check["passed"] is False, f"{check['name']} passed: {check['message']}"
    assert check["score"] < 100, f"{check['name']} scored {check['score']}: {check['message']}"
    lowered = check["message"].lower()
    for fragment in fragments:
        assert fragment.lower() in lowered, f"{fragment!r} missing from {check['message']!r}"


def _repo_root() -> Path | None:
    """Walk up from this file to the repo root -- the dir holding src/aipass."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "src" / "aipass").is_dir():
            return parent
    return None


def _fleet_dir() -> Path | None:
    """The directory holding the 18 citizens, or None outside this repo."""
    root = _repo_root()
    return None if root is None else root / "src" / "aipass"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports and force a fresh checker import."""
    mock_logger = MagicMock()
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json", json_pkg)

    monkeypatch.delitem(
        sys.modules,
        "aipass.seedgo.apps.handlers.aipass_standards.trinity_check",
        raising=False,
    )
    return {"logger": mock_logger, "json_handler": mock_json_handler}


@pytest.fixture
def checker(_mock_infrastructure):
    """The freshly imported trinity_check module, infrastructure mocked."""
    from aipass.seedgo.apps.handlers.aipass_standards import trinity_check

    return trinity_check


@pytest.fixture
def trinity(checker, monkeypatch):
    """trinity_check with the pinned config and gold templates in place."""
    monkeypatch.setattr(checker, "load_memory_config", lambda: copy.deepcopy(_CONFIG))
    monkeypatch.setattr(checker, "_load_templates", lambda: copy.deepcopy(_TEMPLATES))
    return checker


# ===========================================================================
# A. THE ONE LAW -- fail loud, never silent-pass
# ===========================================================================


class TestTheOneLaw:
    """Nothing unmeasurable may ever produce a passing group."""

    def test_missing_trinity_dir_fails_every_group(self, trinity, tmp_path):
        # The registry marks this a LIVE installation. Without it the tree is
        # indistinguishable from a fresh clone, where an absent .trinity is an
        # environment fact rather than a violation -- see
        # TestACleanCheckoutIsNotAViolatingFleet.
        (tmp_path / "AIPASS_REGISTRY.json").write_text("{}\n", encoding="utf-8")
        branch = tmp_path / "nobody"
        branch.mkdir()

        result = trinity.check_branch(str(branch))

        assert result["passed"] is False
        assert result["score"] == 0
        for check in result["checks"]:
            assert check["passed"] is False, f"{check['name']} passed with no .trinity/ at all"
            assert check["score"] == 0, f"{check['name']} scored {check['score']} with no .trinity/"
            assert check["message"], f"{check['name']} failed without saying why"

    def test_missing_trinity_dir_names_the_missing_directory(self, trinity, tmp_path):
        (tmp_path / "AIPASS_REGISTRY.json").write_text("{}\n", encoding="utf-8")
        branch = tmp_path / "nobody"
        branch.mkdir()

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "File set"), ".trinity", "not found")

    def test_corrupt_local_json_fails_and_never_passes_a_group_that_reads_it(self, trinity, tmp_path):
        branch = _write_branch(tmp_path, local='{"document_metadata": {,,, malformed')

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Top-level keys"), "local.json", "not valid json")
        _assert_failed(_group(result, "Entry shapes"), "local.json")
        _assert_failed(_group(result, "Char caps"), "local.json")
        _assert_failed(_group(result, "Freshness"), "local.json")
        _assert_failed(_group(result, "Todos hygiene"), "local.json")
        _assert_failed(_group(result, "Meta lines & _usage"), "local.json")

    def test_corrupt_observations_json_fails_and_never_passes(self, trinity, tmp_path):
        branch = _write_branch(tmp_path, observations="not json at all")

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Top-level keys"), "observations.json", "not valid json")
        _assert_failed(_group(result, "Entry shapes"), "observations.json")
        _assert_failed(_group(result, "Char caps"), "observations.json")
        _assert_failed(_group(result, "Freshness"), "observations.json")

    def test_empty_file_is_not_valid_json_and_fails_loud(self, trinity, tmp_path):
        branch = _write_branch(tmp_path, local="")

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Top-level keys"), "local.json", "not valid json")

    def test_top_level_list_is_a_violation_not_an_empty_object(self, trinity, tmp_path):
        branch = _write_branch(tmp_path, local="[]")

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Top-level keys"), "top level must be an object", "list")
        _assert_failed(_group(result, "Entry shapes"), "local.json")

    def test_observations_top_level_list_is_a_violation(self, trinity, tmp_path):
        branch = _write_branch(tmp_path, observations='[{"number": 1}]')

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Top-level keys"), "top level must be an object", "list")

    def test_missing_local_file_fails_every_group_that_reads_it(self, trinity, tmp_path):
        branch = _write_branch(tmp_path, local=None)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Top-level keys"), "local.json", "not found")
        _assert_failed(_group(result, "Entry shapes"), "local.json")
        _assert_failed(_group(result, "File set"), "missing local.json")

    def test_list_note_is_a_type_violation_in_entry_shapes(self, trinity, tmp_path):
        observations = _canonical_observations()
        observations["observations"][0]["note"] = [{"title": "a", "detail": "b"}]
        branch = _write_branch(tmp_path, observations=observations)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Entry shapes"), "note must be str", "list")

    def test_list_note_is_unmeasurable_in_char_caps_not_zero_chars(self, trinity, tmp_path):
        """The original sin: a list note len()-ed to 0 and waved through."""
        observations = _canonical_observations()
        observations["observations"][0]["note"] = [{"title": "a", "detail": "b"}]
        branch = _write_branch(tmp_path, observations=observations)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Char caps"), "note", "unmeasurable", "found list")

    def test_renamed_cap_field_is_flagged_not_read_as_empty_string(self, trinity, tmp_path):
        local = _canonical_local()
        local["key_learnings"][0] = {
            "number": 2,
            "date": "2026-08-24",
            "learning": "merged key+value into one blob",
        }
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Entry shapes"), "unexpected field 'learning'")
        _assert_failed(_group(result, "Char caps"), "value", "unmeasurable", "absent")

    def test_entry_without_number_is_flagged_by_ordering_not_skipped(self, trinity, tmp_path):
        local = _canonical_local()
        local["todos"] = [{"date": "2026-08-24", "task": "x", "priority": "low", "status": "open"}]
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Ordering & numbering"), "no usable 'number'", "absent")

    def test_entry_that_is_not_a_dict_is_flagged_by_every_entry_group(self, trinity, tmp_path):
        local = _canonical_local()
        local["todos"] = ["just a string"]
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Entry shapes"), "entry must be an object", "str")
        _assert_failed(_group(result, "Ordering & numbering"), "no usable number")
        _assert_failed(_group(result, "Char caps"), "entry must be an object")
        _assert_failed(_group(result, "Todos hygiene"), "entry must be an object")

    def test_container_that_is_not_a_list_is_flagged(self, trinity, tmp_path):
        local = _canonical_local()
        local["sessions"] = {"1": {"summary": "a dict of sessions"}}
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Entry shapes"), "'sessions' must be a list", "dict")
        _assert_failed(_group(result, "Ordering & numbering"), "must be a list")
        _assert_failed(_group(result, "Char caps"), "must be a list")

    def test_missing_container_is_flagged_not_skipped(self, trinity, tmp_path):
        local = _canonical_local()
        del local["key_learnings"]
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Entry shapes"), "'key_learnings' section missing")

    def test_unreadable_config_fails_char_caps_rather_than_assuming_numbers(self, trinity, tmp_path, monkeypatch):
        monkeypatch.setattr(trinity, "load_memory_config", lambda: None)
        branch = _write_branch(tmp_path)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Char caps"), "memory.config.json", "never assumed")
        assert _group(result, "Char caps")["score"] == 0

    def test_unreadable_config_fails_meta_lines_rather_than_assuming_numbers(self, trinity, tmp_path, monkeypatch):
        monkeypatch.setattr(trinity, "load_memory_config", lambda: None)
        branch = _write_branch(tmp_path)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Meta lines & _usage"), "memory.config.json", "never assumed")
        assert _group(result, "Meta lines & _usage")["score"] == 0

    def test_unreadable_templates_fail_meta_lines_rather_than_assuming_prose(self, trinity, tmp_path, monkeypatch):
        monkeypatch.setattr(trinity, "_load_templates", lambda: None)
        branch = _write_branch(tmp_path)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Meta lines & _usage"), "template", "prose is never assumed")
        assert _group(result, "Meta lines & _usage")["score"] == 0

    def test_template_without_placeholder_prose_fails_loud(self, trinity, tmp_path, monkeypatch):
        broken = copy.deepcopy(_TEMPLATES)
        broken["local"]["sessions_meta"] = "no placeholder token here"
        monkeypatch.setattr(trinity, "_load_templates", lambda: copy.deepcopy(broken))
        branch = _write_branch(tmp_path)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Meta lines & _usage"), "template")

    def test_unreadable_templates_fail_the_receipt_version_check(self, trinity, tmp_path, monkeypatch):
        monkeypatch.setattr(trinity, "_load_templates", lambda: None)
        branch = _write_branch(tmp_path)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Receipt"), "gold templates unreadable")

    def test_validate_entry_shape_refuses_an_unknown_section(self, trinity):
        problems = trinity.validate_entry_shape("nonexistent", {"number": 1})

        assert problems
        assert "no canonical shape" in problems[0]

    def test_validate_entry_shape_refuses_a_non_dict_entry(self, trinity):
        assert trinity.validate_entry_shape("observations", ["a", "list"]) == ["entry must be an object, found list"]

    def test_validate_entry_shape_rejects_bool_masquerading_as_number(self, trinity):
        problems = trinity.validate_entry_shape(
            "observations", {"number": True, "date": "2026-08-25", "note": "x", "tags": []}
        )

        assert any("number must be int" in problem for problem in problems)


# ===========================================================================
# B. Per-drift-class regression tests (MASTER_LIST D1-D16)
# ===========================================================================


class TestDriftClassRegressions:
    """One test per drift class the fleet audit found, named for that class."""

    def test_d1_note_as_list_of_title_detail(self, trinity, tmp_path):
        """D1 -- 9 branches pack list[{title,detail}] into note."""
        observations = _canonical_observations()
        observations["observations"][0]["note"] = [
            {"title": "first", "detail": "a"},
            {"title": "second", "detail": "b"},
        ]
        branch = _write_branch(tmp_path, observations=observations)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Entry shapes"), "note must be str, found list")
        _assert_failed(_group(result, "Char caps"), "unmeasurable")

    @pytest.mark.parametrize(
        ("field", "value"),
        [("session", 12), ("category", "collaboration"), ("type", "preference")],
    )
    def test_d2_fourth_observation_field_renamed(self, trinity, tmp_path, field, value):
        """D2 -- tags renamed to session:int / category:str / type:str."""
        observations = _canonical_observations()
        entry = observations["observations"][0]
        del entry["tags"]
        entry[field] = value
        branch = _write_branch(tmp_path, observations=observations)

        result = trinity.check_branch(str(branch))

        _assert_failed(
            _group(result, "Entry shapes"),
            "missing required field 'tags'",
            f"unexpected field '{field}'",
        )

    def test_d3_observation_note_over_cap_measured_against_config(self, trinity, tmp_path):
        """D3 -- over-cap notes, measured against the CONFIG number."""
        observations = _canonical_observations()
        observations["observations"][0]["note"] = "x" * 301
        branch = _write_branch(tmp_path, observations=observations)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Char caps"), "'note' is 301 chars", "cap 300")

    def test_d3_cap_number_comes_from_config_not_from_a_constant(self, trinity, tmp_path, monkeypatch):
        """A config edit must move the cap the checker enforces."""
        tightened = copy.deepcopy(_CONFIG)
        tightened["entry_limits"]["entry_types"]["observations"]["max_chars"] = 50
        monkeypatch.setattr(trinity, "load_memory_config", lambda: copy.deepcopy(tightened))
        observations = _canonical_observations()
        observations["observations"][0]["note"] = "x" * 60
        branch = _write_branch(tmp_path, observations=observations)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Char caps"), "'note' is 60 chars", "cap 50")

    def test_d3_cap_field_name_comes_from_config(self, trinity, tmp_path, monkeypatch):
        """The measured FIELD is config's too -- not a hardcoded name."""
        renamed = copy.deepcopy(_CONFIG)
        renamed["entry_limits"]["entry_types"]["observations"]["field"] = "summary"
        monkeypatch.setattr(trinity, "load_memory_config", lambda: copy.deepcopy(renamed))
        branch = _write_branch(tmp_path)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Char caps"), "'summary' unmeasurable", "absent")

    def test_d3_per_branch_cap_override_is_honoured(self, trinity, tmp_path, monkeypatch):
        """Per-branch config overrides are part of the one source (contract)."""
        overridden = copy.deepcopy(_CONFIG)
        overridden["entry_limits"]["per_branch"] = {_BRANCH: {"observations": {"max_chars": 40}}}
        monkeypatch.setattr(trinity, "load_memory_config", lambda: copy.deepcopy(overridden))
        observations = _canonical_observations()
        observations["observations"][0]["note"] = "y" * 45
        branch = _write_branch(tmp_path, observations=observations)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Char caps"), "'note' is 45 chars", "cap 40")

    def test_d4_key_learnings_merged_learning_field(self, trinity, tmp_path):
        """D4 -- api / hooks / ai_mail merged key+value into `learning`."""
        local = _canonical_local()
        local["key_learnings"] = [
            {"number": 2, "date": "2026-08-24", "learning": "one 600-char blob"},
            {
                "number": 1,
                "date": "2026-08-20",
                "key": "One source",
                "value": "kept canonical, so the array is shape-mixed",
            },
        ]
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(
            _group(result, "Entry shapes"),
            "missing required field 'key'",
            "unexpected field 'learning'",
        )

    def test_d4_canary_value_plus_tags_without_key(self, trinity, tmp_path):
        """D4 -- canary's key_learnings carry value+tags and no key."""
        local = _canonical_local()
        local["key_learnings"] = [
            {"number": 2, "date": "2026-08-24", "value": "no key here", "tags": ["seedgo"]},
        ]
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(
            _group(result, "Entry shapes"),
            "missing required field 'key'",
            "unexpected field 'tags'",
        )

    def test_d5_legacy_todos_without_number_or_date(self, trinity, tmp_path):
        """D5 -- ai_mail / drone / spawn / hooks legacy todos."""
        local = _canonical_local()
        local["todos"] = [
            {"added": "2026-03-02", "task": "legacy sticky note", "priority": "high", "status": "open"},
        ]
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(
            _group(result, "Entry shapes"),
            "missing required field 'number'",
            "missing required field 'date'",
            "unexpected field 'added'",
        )
        _assert_failed(_group(result, "Ordering & numbering"), "no usable 'number'")

    def test_d6_sessions_with_extra_findings_and_verification_fields(self, trinity, tmp_path):
        """D6 -- seedgo alone adds findings / verification / costing."""
        local = _canonical_local()
        local["sessions"][0]["findings"] = ["a", "b"]
        local["sessions"][0]["verification"] = "34/34 files"
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(
            _group(result, "Entry shapes"),
            "unexpected field 'findings'",
            "unexpected field 'verification'",
        )

    def test_d6_session_tags_must_be_a_list_of_strings_when_present(self, trinity, tmp_path):
        local = _canonical_local()
        local["sessions"][0]["tags"] = "trinity"
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Entry shapes"), "tags must be list[str]", "found str")

    @pytest.mark.parametrize("section", ["active_tasks", "user", "recently_completed"])
    def test_d7_stray_top_level_sections(self, trinity, tmp_path, section):
        """D7 -- active_tasks x3, aipass `user`, skills' shadow session log."""
        local = _canonical_local()
        local[section] = []
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Top-level keys"), "stray top-level section", section)

    def test_d7_duplicate_top_level_key_is_flagged(self, trinity, tmp_path):
        """D7 -- ai_mail's stale duplicate last_updated; later value wins silently."""
        raw = json.dumps(_canonical_local(), indent=2, ensure_ascii=False)
        raw = raw.replace('"todos_meta"', '"todos": [],\n  "todos_meta"', 1)
        branch = _write_branch(tmp_path, local=raw)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Top-level keys"), "duplicate json key", "todos")

    def test_d8_session_summary_over_cap(self, trinity, tmp_path):
        """D8 -- summary >300 in 8/18 branches (api 5.4x, trigger 4.9x)."""
        local = _canonical_local()
        local["sessions"][0]["summary"] = "s" * 400
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Char caps"), "'summary' is 400 chars", "cap 300")

    def test_d8_key_learning_value_over_cap(self, trinity, tmp_path):
        local = _canonical_local()
        local["key_learnings"][0]["value"] = "v" * 201
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Char caps"), "'value' is 201 chars", "cap 200")

    def test_d8_todo_task_over_cap(self, trinity, tmp_path):
        local = _canonical_local()
        local["todos"][0]["task"] = "t" * 151
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Char caps"), "'task' is 151 chars", "cap 150")

    def test_d13_managed_by_casing_disagreement_across_a_branch_own_files(self, trinity, tmp_path):
        """D13 -- managed_by casing disagrees in 5 branches."""
        observations = _canonical_observations()
        observations["document_metadata"]["managed_by"] = _BRANCH.upper()
        branch = _write_branch(tmp_path, observations=observations)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Top-level keys"), "managed_by")

    def test_d14_stray_file_in_trinity_is_flagged(self, trinity, tmp_path):
        """D14 -- seedgo's STATUS.local.md and friends."""
        branch = _write_branch(tmp_path)
        (branch / ".trinity" / "STATUS.local.md").write_text("status\n", encoding="utf-8")

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "File set"), "stray STATUS.local.md")

    def test_d14_stray_directory_in_trinity_is_flagged_with_a_slash(self, trinity, tmp_path):
        """D14 -- daemon's .recovery/, memory's .backup/, devpulse's watchdog state."""
        branch = _write_branch(tmp_path)
        (branch / ".trinity" / ".recovery").mkdir()

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "File set"), "stray .recovery/")

    def test_d14_missing_readme_is_flagged(self, trinity, tmp_path):
        """D14 -- README.md missing from devpulse and prax."""
        branch = _write_branch(tmp_path)
        (branch / ".trinity" / "README.md").unlink()

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "File set"), "missing README.md")

    def test_d14_check_branch_info_reports_every_stray_by_name(self, trinity, tmp_path):
        branch = _write_branch(tmp_path)
        (branch / ".trinity" / "STATUS.local.md").write_text("status\n", encoding="utf-8")
        (branch / ".trinity" / ".recovery").mkdir()

        lines = trinity.check_branch_info(str(branch))

        assert lines == [
            "trinity: stray .trinity/.recovery/",
            "trinity: stray .trinity/STATUS.local.md",
        ]

    def test_d14_check_branch_info_is_empty_on_a_clean_branch(self, trinity, tmp_path):
        branch = _write_branch(tmp_path)

        assert trinity.check_branch_info(str(branch)) == []


# ===========================================================================
# CI. A clean checkout is an environment fact, not 18 simultaneous violations
# ===========================================================================


class TestACleanCheckoutIsNotAViolatingFleet:
    """CI ran seedgo-audit on a GitHub runner and every one of the 18 branches
    came back trinity 0 / FAILED. Nothing was wrong with the fleet: .trinity/
    and AIPASS_REGISTRY.json are BOTH gitignored by design -- memories never
    ship -- so a fresh clone has no memory files at all and the checker refused
    every group, which branch_audit turned into a score of 0.

    THE ONE LAW says unmeasurable is REFUSED, never zeroed, and a whole SPECIES
    missing on a tree that also has no registry is an environment fact. So the
    standard reports itself not-applicable for the run and is left out of the
    gating average entirely -- not scored 0 (a lie about the branch) and not
    scored 100 (a lie about the measurement).

    The discrimination is deliberately conservative: BOTH signals must be
    absent. A live installation missing .trinity on one branch still has the
    registry, so that stays exactly the violation it always was.
    """

    @staticmethod
    def _ci_tree(root: Path, name: str = _BRANCH) -> Path:
        """A branch as a fresh clone has it: code, no memories, no registry."""
        branch = root / name
        (branch / "apps").mkdir(parents=True)
        return branch

    def test_a_clean_checkout_is_not_applicable_rather_than_zero(self, trinity, tmp_path):
        result = trinity.check_branch(str(self._ci_tree(tmp_path)))

        assert result["not_applicable"] is True
        assert result["score"] != 0

    def test_a_clean_checkout_does_not_report_a_failure(self, trinity, tmp_path):
        """FAILED on a clean clone is what turned CI red."""
        assert trinity.check_branch(str(self._ci_tree(tmp_path)))["passed"] is not False

    def test_the_skip_announces_itself_loudly(self, trinity, tmp_path):
        """A silent skip is how a broken standard hides. Say why, by name."""
        lines = trinity.check_branch_info(str(self._ci_tree(tmp_path)))

        assert any("not measured" in line.lower() for line in lines)
        assert any("checkout" in line.lower() for line in lines)

    def test_a_live_installation_missing_trinity_is_still_a_violation(self, trinity, tmp_path):
        """The whole point of the discrimination -- a registry means a real
        install, so an absent .trinity there is a real finding.
        """
        (tmp_path / "AIPASS_REGISTRY.json").write_text("{}\n", encoding="utf-8")
        result = trinity.check_branch(str(self._ci_tree(tmp_path)))

        assert result.get("not_applicable") is not True
        assert result["passed"] is False

    def test_a_sibling_with_memories_also_means_a_live_installation(self, trinity, tmp_path):
        """Registry absent but the fleet clearly has citizens -- not a clone."""
        _write_branch(tmp_path, name="othercitizen")
        result = trinity.check_branch(str(self._ci_tree(tmp_path)))

        assert result.get("not_applicable") is not True
        assert result["passed"] is False

    def test_a_populated_branch_is_scored_normally(self, trinity, tmp_path):
        """Over-refusal guard: the escape hatch must not swallow real runs."""
        result = trinity.check_branch(str(_write_branch(tmp_path)))

        assert result.get("not_applicable") is not True
        assert result["score"] == 100

    def test_the_spawn_template_trinity_does_not_look_like_a_citizen(self, trinity, tmp_path):
        """The ONE .trinity that DOES ship: spawn/templates/*/.trinity is
        un-ignored in .gitignore. It sits two levels down, not at
        <fleet>/<branch>/.trinity, so it must not make a clone look live.
        """
        template = tmp_path / "spawn" / "templates" / "aipass_framework" / ".trinity"
        template.mkdir(parents=True)
        (template / "local.json").write_text("{}\n", encoding="utf-8")

        assert trinity.check_branch(str(self._ci_tree(tmp_path)))["not_applicable"] is True

    def test_a_not_applicable_result_still_names_the_standard(self, trinity, tmp_path):
        """Downstream readers key on it; a bare dict would break them."""
        result = trinity.check_branch(str(self._ci_tree(tmp_path)))

        assert result["standard"] == "TRINITY"
        assert isinstance(result.get("checks"), list)


# ===========================================================================
# Marker 7. The gate, pinned so it cannot be downgraded by accident
# ===========================================================================


class TestTrinityIsAGateNotAReport:
    """Marker 7 asked for a REPORT -> GATE flip. Measured first: trinity was
    already a gate and has been since it shipped. In this standards family a
    gate is expressed by three things together, and trinity has all three --
    so there was nothing to flip, and these tests exist so it stays that way.

    The family's own vocabulary:
      * ``ADVISORY = True`` marks a standard that never gates (ruff, template).
        trinity does not set it, so it counts in the gating average.
      * ``passed`` is the block signal. trinity requires a PERFECT 100, which
        is stricter than every other branch_level standard -- json_handler,
        the precedent named in the brief, passes at 75.
      * failing groups surface in ``checks[]``, which the audit lifts into
        ``failed_checks``.

    Each is pinned separately because each could be lost on its own.
    """

    def test_trinity_is_not_advisory(self, checker):
        """ADVISORY = True would silently drop trinity out of the average."""
        assert getattr(checker, "ADVISORY", False) is False

    def test_advisory_is_how_this_family_says_non_gating(self, checker):
        """The pin is only meaningful if ADVISORY still means what it means."""
        from aipass.seedgo.apps.handlers.aipass_standards import ruff_check, template_check

        assert ruff_check.ADVISORY is True
        assert template_check.ADVISORY is True

    def test_a_gating_standard_is_counted_in_the_average(self, checker):
        """The audit computes its average over non-ADVISORY standards only."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        source = Path(branch_audit.__file__).read_text(encoding="utf-8")
        assert 'getattr(mod, "ADVISORY", False) is True' in source
        assert "gating_scores = {k: v for k, v in scores.items() if k not in advisory_standards}" in source

    def test_anything_short_of_perfect_fails(self, trinity, tmp_path):
        """Not a threshold: 99 blocks. The push proved 100 is reachable."""
        local = _canonical_local()
        local["document_metadata"]["limits"] = {}
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        assert 0 < result["score"] < 100
        assert result["passed"] is False

    def test_a_fully_canonical_branch_passes(self, trinity, tmp_path):
        """The gate must be satisfiable, or it is a wall."""
        result = trinity.check_branch(str(_write_branch(tmp_path)))

        assert result["score"] == 100
        assert result["passed"] is True

    def test_failing_groups_reach_the_audits_failed_checks_channel(self, trinity, tmp_path):
        """What the audit lifts into failed_checks is checks[] with passed False."""
        branch = _write_branch(tmp_path, local={"document_metadata": {}})

        result = trinity.check_branch(str(branch))

        assert [c for c in result["checks"] if not c["passed"]]


# ===========================================================================
# D17. document_metadata is a CLOSED set (ruling 4, due after the fleet reset)
# ===========================================================================


class TestDocumentMetadataIsAClosedSet:
    """Ruling 4: ``document_metadata`` is a closed set, and the push executed
    it fleet-wide. The build deliberately deferred this -- the contract named
    the required fields and deleted ``status`` but did not declare the block
    closed, so extras were unflagged. The ruling closed it.

    Live population today is ZERO: the push cured every branch, so nothing on
    disk proves this rule can see. The real deviant corpus is the PRE-PUSH
    state still sitting in ``*.pre_v3_backup`` -- 34 files carrying ``limits``
    and ``status``. ``limits`` is the field this rule newly catches.
    """

    @pytest.mark.parametrize("file_key", ["local", "observations"])
    def test_an_extra_metadata_field_is_flagged(self, trinity, tmp_path, file_key):
        docs = {"local": _canonical_local(), "observations": _canonical_observations()}
        docs[file_key]["document_metadata"]["limits"] = {"sessions": 15}
        branch = _write_branch(tmp_path, local=docs["local"], observations=docs["observations"])

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Top-level keys"), "limits")

    def test_the_violation_names_every_extra_field_not_just_the_first(self, trinity, tmp_path):
        local = _canonical_local()
        local["document_metadata"]["limits"] = {}
        local["document_metadata"]["owner"] = "someone"
        branch = _write_branch(tmp_path, local=local)

        message = _group(trinity.check_branch(str(branch)), "Top-level keys")["message"]

        assert "limits" in message and "owner" in message

    def test_status_keeps_its_own_diagnostic_rather_than_folding_into_extras(self, trinity, tmp_path):
        """``status`` was already deleted by name and says WHY -- health is
        computed, never stored. A generic 'unexpected field' would lose that.
        """
        local = _canonical_local()
        local["document_metadata"]["status"] = {"health": "green"}
        branch = _write_branch(tmp_path, local=local)

        message = _group(trinity.check_branch(str(branch)), "Top-level keys")["message"]

        assert "computed at run time" in message
        assert "unexpected field(s) status" not in message

    def test_the_canonical_nine_fields_are_all_still_accepted(self, trinity, tmp_path):
        """Over-refusal guard: closing the set must not reject the set."""
        branch = _write_branch(tmp_path)

        assert _group(trinity.check_branch(str(branch)), "Top-level keys")["passed"] is True

    def test_the_real_pre_push_drift_is_seen(self, trinity, tmp_path):
        """The exact shape found in 34 live *.pre_v3_backup files."""
        local = _canonical_local()
        local["document_metadata"]["limits"] = {"sessions": {"count": 15}}
        local["document_metadata"]["status"] = {"current_session": 90}
        branch = _write_branch(tmp_path, local=local)

        _assert_failed(_group(trinity.check_branch(str(branch)), "Top-level keys"), "limits")


# ===========================================================================
# D18. guidelines content is scored (ruling 3, template-verbatim)
# ===========================================================================


class TestGuidelinesContentIsScored:
    """Ruling 3 landed template-verbatim and the push rewrote every branch to
    it, so the contract ambiguity the build flagged is resolved: the
    ``guidelines`` block's CONTENT is now scored, not just its presence.

    Pre-push corpus: 17 branches carried the right two KEYS with different
    VALUES -- which is precisely why presence-only scoring saw nothing.
    """

    def test_a_divergent_purpose_value_is_flagged(self, trinity, tmp_path):
        """The real pre-push shape: right keys, wrong text."""
        observations = _canonical_observations()
        observations["guidelines"]["purpose"] = "Capture collaboration patterns over time"
        branch = _write_branch(tmp_path, observations=observations)

        _assert_failed(_group(trinity.check_branch(str(branch)), "Meta lines & _usage"), "guidelines")

    def test_a_missing_guidelines_key_is_flagged(self, trinity, tmp_path):
        observations = _canonical_observations()
        del observations["guidelines"]["chronological_order"]
        branch = _write_branch(tmp_path, observations=observations)

        _assert_failed(_group(trinity.check_branch(str(branch)), "Meta lines & _usage"), "guidelines")

    def test_an_extra_guidelines_key_is_flagged(self, trinity, tmp_path):
        observations = _canonical_observations()
        observations["guidelines"]["extra"] = "invented"
        branch = _write_branch(tmp_path, observations=observations)

        _assert_failed(_group(trinity.check_branch(str(branch)), "Meta lines & _usage"), "guidelines")

    def test_a_non_dict_guidelines_is_flagged_by_type(self, trinity, tmp_path):
        observations = _canonical_observations()
        observations["guidelines"] = "Newest at TOP"
        branch = _write_branch(tmp_path, observations=observations)

        _assert_failed(
            _group(trinity.check_branch(str(branch)), "Meta lines & _usage"),
            "guidelines must be an object",
            "found str",
        )

    def test_the_template_verbatim_block_passes(self, trinity, tmp_path):
        """Over-refusal guard: the gold text itself must score clean."""
        branch = _write_branch(tmp_path)

        assert _group(trinity.check_branch(str(branch)), "Meta lines & _usage")["passed"] is True

    def test_unreadable_templates_refuse_rather_than_score_guidelines_zero(self, trinity, tmp_path, monkeypatch):
        """THE ONE LAW: a field that cannot be measured is refused, never
        scored. Same rule the meta lines already follow.
        """
        monkeypatch.setattr(trinity, "_load_templates", lambda: None)
        branch = _write_branch(tmp_path)

        _assert_failed(_group(trinity.check_branch(str(branch)), "Meta lines & _usage"), "never assumed")

    @pytest.mark.parametrize("bad", [None, "a string", 42])
    def test_a_gold_template_missing_its_guidelines_block_refuses(self, trinity, tmp_path, monkeypatch, bad):
        """The refusal path that the all-templates-None case cannot reach.

        When every template is unreadable the prose/usage guard fires one line
        earlier, so nulling _load_templates never exercises THIS guard. A
        template that parses but carries no usable guidelines block does --
        and mutation testing is what surfaced the difference.
        """
        templates = copy.deepcopy(_TEMPLATES)
        if bad is None:
            del templates["observations"]["guidelines"]
        else:
            templates["observations"]["guidelines"] = bad
        monkeypatch.setattr(trinity, "_load_templates", lambda: templates)
        branch = _write_branch(tmp_path)

        _assert_failed(_group(trinity.check_branch(str(branch)), "Meta lines & _usage"), "guidelines", "never assumed")


# ===========================================================================
# D14b. Versioned backups are LEGAL residents (Patrick's File set ruling)
# ===========================================================================


class TestVersionedBackupsAreLegalResidents:
    """The ruling: renaming the current file as a version left in place while
    the new file is created IS the house convention, so those old versions are
    expected residents of .trinity/ -- not strays.

    The rule is a SHAPE, deliberately not a list of today's two suffixes: a
    canonical filename, then ``.pre``, then a separator, then a version token.
    The next migration mints its own token and passes without a code change.

    The opposite error is the one that matters for a checker: a rule loose
    enough to admit ``local.json.tmp`` would make torn-write staging files
    invisible in the one directory whose whole job is durable memory. Every
    guard below is a live species -- seedgo found a 4.3MB truncated .tmp
    staging file in a json dir in session 90.
    """

    # -- the ruling: these must STOP flagging ------------------------------

    @pytest.mark.parametrize(
        "name",
        [
            "local.json.pre_v3_backup",
            "observations.json.pre_v3_backup",
            "local.json.pre-aipl",
            "observations.json.pre-aipl",
        ],
    )
    def test_todays_live_versioned_backups_are_not_strays(self, trinity, tmp_path, name):
        """The four shapes actually on disk across the fleet today."""
        branch = _write_branch(tmp_path)
        (branch / ".trinity" / name).write_text("{}\n", encoding="utf-8")

        result = trinity.check_branch(str(branch))

        assert _group(result, "File set")["passed"] is True, _group(result, "File set")["message"]
        assert trinity.check_branch_info(str(branch)) == []

    @pytest.mark.parametrize(
        "name",
        [
            "local.json.pre_v4_backup",
            "passport.json.pre-trinity",
            "README.md.pre_v9",
            ".template_version.json.pre-whatever2",
        ],
    )
    def test_a_suffix_no_one_has_minted_yet_is_admitted_by_shape(self, trinity, tmp_path, name):
        """The point of a shape rule: the NEXT migration needs no code change."""
        branch = _write_branch(tmp_path)
        (branch / ".trinity" / name).write_text("{}\n", encoding="utf-8")

        assert _group(trinity.check_branch(str(branch)), "File set")["passed"] is True

    def test_a_branch_of_canonicals_plus_backups_scores_file_set_100(self, trinity, tmp_path):
        """devpulse's real .trinity shape: five canonicals + two generations."""
        branch = _write_branch(tmp_path)
        for name in (
            "local.json.pre_v3_backup",
            "local.json.pre-aipl",
            "observations.json.pre_v3_backup",
            "observations.json.pre-aipl",
        ):
            (branch / ".trinity" / name).write_text("{}\n", encoding="utf-8")

        assert _group(trinity.check_branch(str(branch)), "File set")["score"] == 100

    # -- over-refusal guards: these must STILL flag ------------------------

    @pytest.mark.parametrize(
        "name",
        [
            "local.json.tmp",  # torn-write staging -- the species seedgo found live
            "local.json.bak",
            "local.json.swp",
            "local.json.orig",
            "observations.json.lock",
            "tmp2ay2d070.tmp",
        ],
    )
    def test_machine_artifacts_are_still_strays(self, trinity, tmp_path, name):
        """A backup rule that swallows temp files hides torn writes."""
        branch = _write_branch(tmp_path)
        (branch / ".trinity" / name).write_text("x\n", encoding="utf-8")

        _assert_failed(_group(trinity.check_branch(str(branch)), "File set"), f"stray {name}")

    @pytest.mark.parametrize(
        "name",
        [
            "STATUS.local.md",  # seedgo's own, still mine to relocate or defend
            "watchdog_active.json",  # devpulse's, banked as their todo
            "watchdog_active.json.lock",
        ],
    )
    def test_the_deliberately_flagged_operational_files_still_flag(self, trinity, tmp_path, name):
        """The ruling kept these violations on purpose -- owners relocate."""
        branch = _write_branch(tmp_path)
        (branch / ".trinity" / name).write_text("x\n", encoding="utf-8")

        _assert_failed(_group(trinity.check_branch(str(branch)), "File set"), f"stray {name}")

    def test_a_backup_of_a_non_canonical_base_is_still_a_stray(self, trinity, tmp_path):
        """Versioning a stray does not launder it into a resident."""
        branch = _write_branch(tmp_path)
        (branch / ".trinity" / "STATUS.local.md.pre_v3_backup").write_text("x\n", encoding="utf-8")

        _assert_failed(_group(trinity.check_branch(str(branch)), "File set"), "stray STATUS.local.md.pre_v3_backup")

    @pytest.mark.parametrize(
        "name",
        [
            "local.json.pre",  # no separator, no token -- ambiguous
            "local.json.pre_",  # token must start alphanumeric
            "local.json.pre-",
            "local.json.pre_v3_backup.tmp",  # a temp file wearing a backup's name
            "local.jsonpre_v3",  # no dot before the marker
            "local.json.post_v3",  # 'pre' is the anchor the convention uses
        ],
    )
    def test_near_misses_of_the_pattern_are_still_strays(self, trinity, tmp_path, name):
        branch = _write_branch(tmp_path)
        (branch / ".trinity" / name).write_text("x\n", encoding="utf-8")

        _assert_failed(_group(trinity.check_branch(str(branch)), "File set"), f"stray {name}")

    def test_a_directory_named_like_a_backup_is_still_a_stray(self, trinity, tmp_path):
        """The convention renames a FILE. A directory of junk is not a version."""
        branch = _write_branch(tmp_path)
        (branch / ".trinity" / "local.json.pre_v3_backup").mkdir()

        _assert_failed(_group(trinity.check_branch(str(branch)), "File set"), "stray local.json.pre_v3_backup/")

    # -- the two lanes must agree -----------------------------------------

    def test_both_lanes_agree_on_what_a_stray_is(self, trinity, tmp_path):
        """seedgo S88/S90 lesson: a shared rule fixed in one lane and not the
        other is this branch's own recurring defect. The scored group and the
        info channel read the same helper -- pinned so they cannot diverge.
        """
        branch = _write_branch(tmp_path)
        (branch / ".trinity" / "local.json.pre_v3_backup").write_text("{}\n", encoding="utf-8")
        (branch / ".trinity" / "STATUS.local.md").write_text("x\n", encoding="utf-8")

        result = trinity.check_branch(str(branch))
        info = trinity.check_branch_info(str(branch))

        assert info == ["trinity: stray .trinity/STATUS.local.md"]
        _assert_failed(_group(result, "File set"), "stray STATUS.local.md")
        assert "pre_v3_backup" not in _group(result, "File set")["message"]

    # -- the predicate itself, directly ------------------------------------

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("local.json.pre_v3_backup", True),
            ("observations.json.pre-aipl", True),
            ("passport.json.pre_v4", True),
            ("README.md.pre-anything", True),
            (".template_version.json.pre_v2_backup", True),
            ("local.json", False),  # a canonical file is not a backup of one
            ("local.json.tmp", False),
            ("local.json.pre", False),
            ("local.json.pre_", False),
            ("local.json.pre_v3_backup.tmp", False),
            ("STATUS.local.md.pre_v3_backup", False),
            ("local.json.PRE_V3", False),  # convention is lowercase
            ("pre_v3_backup", False),  # no base at all
            ("", False),
        ],
    )
    def test_the_predicate_reads_names_only(self, trinity, name, expected):
        """Pure name predicate -- no filesystem, so the caller owns the
        directory rule. Called directly because it is public API and seedgo's
        own test_map scores public functions on having a direct test.
        """
        assert trinity.is_versioned_backup(name) is expected

    def test_d14_check_branch_info_is_empty_when_trinity_is_absent(self, trinity, tmp_path):
        # Registry present: a LIVE installation whose branch has no .trinity.
        # On a fresh clone the same shape announces itself instead of staying
        # silent -- see TestACleanCheckoutIsNotAViolatingFleet.
        (tmp_path / "AIPASS_REGISTRY.json").write_text("{}\n", encoding="utf-8")
        branch = tmp_path / "nobody"
        branch.mkdir()

        assert trinity.check_branch_info(str(branch)) == []

    def test_d15_last_updated_older_than_newest_entry(self, trinity, tmp_path):
        """D15 -- 12/18 branches carry a stamp 100-170 days stale."""
        local = _canonical_local()
        local["document_metadata"]["last_updated"] = "2026-03-01"
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Freshness"), "last_updated 2026-03-01", "2026-08-25")

    def test_d15_last_updated_of_the_wrong_type_is_unmeasurable(self, trinity, tmp_path):
        local = _canonical_local()
        local["document_metadata"]["last_updated"] = 20260825
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Freshness"), "last_updated is not a yyyy-mm-dd date", "int")

    def test_d15_entry_date_that_is_not_a_date_is_unmeasurable(self, trinity, tmp_path):
        local = _canonical_local()
        local["sessions"][0]["date"] = "last tuesday"
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Freshness"), "unmeasurable")

    def test_d16_observations_missing_created_is_flagged(self, trinity, tmp_path):
        """D16 -- devpulse's observations.json alone drops created."""
        observations = _canonical_observations()
        del observations["document_metadata"]["created"]
        branch = _write_branch(tmp_path, observations=observations)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Top-level keys"), "document_metadata missing created")

    def test_todos_kept_as_done_are_flagged(self, trinity, tmp_path):
        """Contract: delete a finished todo, never keep it as a trophy."""
        local = _canonical_local()
        local["todos"][0]["status"] = "Done"
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Todos hygiene"), "status done", "delete it")


# ===========================================================================
# C. Contract rules that are 100% compliant today -- regression guards
# ===========================================================================


class TestCompliantRulesStayCompliant:
    """These pass fleet-wide today. They must never start passing by accident."""

    def test_canonical_branch_scores_one_hundred(self, trinity, tmp_path):
        branch = _write_branch(tmp_path)

        result = trinity.check_branch(str(branch))

        failing = [(check["name"], check["message"]) for check in result["checks"] if not check["passed"]]
        assert failing == []
        assert result["score"] == 100
        assert result["passed"] is True

    def test_newest_first_ordering_passes(self, trinity, tmp_path):
        branch = _write_branch(tmp_path)

        result = trinity.check_branch(str(branch))

        assert _group(result, "Ordering & numbering")["passed"] is True

    def test_oldest_first_ordering_is_flagged(self, trinity, tmp_path):
        local = _canonical_local()
        local["sessions"].reverse()
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Ordering & numbering"), "not below the entry above it", "newest-first")

    def test_duplicate_number_reuse_is_flagged(self, trinity, tmp_path):
        local = _canonical_local()
        local["sessions"][1]["number"] = 2
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Ordering & numbering"), "number 2 reused")

    def test_canonical_top_level_key_set_passes(self, trinity, tmp_path):
        branch = _write_branch(tmp_path)

        result = trinity.check_branch(str(branch))

        assert _group(result, "Top-level keys")["passed"] is True

    def test_out_of_order_top_level_keys_are_flagged(self, trinity, tmp_path):
        local = _canonical_local()
        reordered = {"todos_meta": local["todos_meta"]}
        reordered.update({key: value for key, value in local.items() if key != "todos_meta"})
        branch = _write_branch(tmp_path, local=reordered)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Top-level keys"), "top-level key order")

    def test_missing_guidelines_block_is_flagged(self, trinity, tmp_path):
        observations = _canonical_observations()
        del observations["guidelines"]
        branch = _write_branch(tmp_path, observations=observations)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Top-level keys"), "missing guidelines")

    def test_status_block_in_document_metadata_is_a_violation(self, trinity, tmp_path):
        """The contract DELETED document_metadata.status -- health is computed."""
        local = _canonical_local()
        local["document_metadata"]["status"] = {"health": "healthy"}
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Top-level keys"), "status is deleted by the standard")

    def test_status_string_in_document_metadata_is_also_a_violation(self, trinity, tmp_path):
        observations = _canonical_observations()
        observations["document_metadata"]["status"] = "healthy"
        branch = _write_branch(tmp_path, observations=observations)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Top-level keys"), "status is deleted by the standard")

    def test_document_name_must_name_this_branch(self, trinity, tmp_path):
        local = _canonical_local()
        local["document_metadata"]["document_name"] = "someoneelse.LOCAL"
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Top-level keys"), "does not name branch")

    def test_document_name_must_carry_the_file_suffix(self, trinity, tmp_path):
        observations = _canonical_observations()
        observations["document_metadata"]["document_name"] = f"{_BRANCH}.LOCAL"
        branch = _write_branch(tmp_path, observations=observations)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Top-level keys"), "must end with .observations")

    def test_managed_by_must_equal_the_branch_directory_name(self, trinity, tmp_path):
        local = _canonical_local()
        observations = _canonical_observations()
        local["document_metadata"]["managed_by"] = "TestBranch"
        observations["document_metadata"]["managed_by"] = "TestBranch"
        branch = _write_branch(tmp_path, local=local, observations=observations)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Top-level keys"), "branch directory name")

    def test_receipt_present_and_matching_gold_passes(self, trinity, tmp_path):
        branch = _write_branch(tmp_path)

        result = trinity.check_branch(str(branch))

        assert _group(result, "Receipt")["passed"] is True

    def test_missing_receipt_scores_zero(self, trinity, tmp_path):
        branch = _write_branch(tmp_path, receipt=None)

        result = trinity.check_branch(str(branch))

        check = _group(result, "Receipt")
        _assert_failed(check, ".template_version.json", "not found")
        assert check["score"] == 0

    def test_receipt_version_that_disagrees_with_gold_is_flagged(self, trinity, tmp_path):
        receipt = _canonical_receipt()
        receipt["template_versions"]["local"] = "2.0.0"
        branch = _write_branch(tmp_path, receipt=receipt)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Receipt"), "local 2.0.0 != gold 3.0.0")

    def test_receipt_versions_of_the_wrong_shape_are_flagged(self, trinity, tmp_path):
        receipt = _canonical_receipt()
        receipt["template_versions"] = ["3.0.0", "3.0.0"]
        branch = _write_branch(tmp_path, receipt=receipt)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Receipt"), "template_versions must be an object", "list")

    @pytest.mark.parametrize("field", ["stamped", "stamped_by", "config_rendered"])
    def test_receipt_timestamp_and_actor_strings_are_required(self, trinity, tmp_path, field):
        receipt = _canonical_receipt()
        del receipt[field]
        branch = _write_branch(tmp_path, receipt=receipt)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Receipt"), f"{field} must be str", "absent")

    def test_usage_that_drifts_from_the_gold_template_is_flagged(self, trinity, tmp_path):
        local = _canonical_local()
        local["document_metadata"]["_usage"] = "a hand-edited copy of the usage text"
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Meta lines & _usage"), "_usage does not byte-match")

    def test_meta_line_carrying_only_the_tab_is_flagged(self, trinity, tmp_path):
        """Today's whole fleet: tab with the template prose stripped off."""
        local = _canonical_local()
        local["sessions_meta"] = _TABS["sessions"]
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Meta lines & _usage"), "sessions_meta does not byte-match")

    def test_meta_line_of_the_wrong_type_is_flagged(self, trinity, tmp_path):
        observations = _canonical_observations()
        observations["observations_meta"] = {"tab": "x"}
        branch = _write_branch(tmp_path, observations=observations)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Meta lines & _usage"), "observations_meta must be str", "dict")


# ===========================================================================
# D. The fleet acceptance bar -- the red-first proof, as a test
# ===========================================================================


class TestFleetAcceptanceBar:
    """The build brief's blindness guard, read off the LIVE fleet.

    INTENTIONALLY COUPLED TO LIVE STATE. Exactly 6 of the 18 citizens are
    fully canonical on OBSERVATIONS entry shape today; if more than six come
    back clean the checker has gone blind somewhere, and if fewer do a branch
    regressed. When a branch is migrated this expectation is UPDATED to the new
    clean set -- never deleted and never loosened, because the day it stops
    being an exact equality is the day it stops proving anything.
    """

    @staticmethod
    def _observation_problems(trinity, path: Path) -> list[str]:
        """Every entry-shape violation in one live observations.json.

        Reading goes through the checker's own reader, which reports a bad
        file rather than raising -- so an unparseable branch counts as
        drifted instead of blowing up the guard.
        """
        result = trinity._read_json_file(path)
        if result["error"] is not None:
            return [f"{path.name}: {result['error']}"]
        entries = result["data"].get("observations")
        if not isinstance(entries, list):
            return [f"{path.name} observations is {type(entries).__name__}, not a list"]
        problems: list[str] = []
        for entry in entries:
            problems.extend(trinity.validate_entry_shape("observations", entry))
        return problems

    def test_exactly_six_citizens_are_canonical_on_observations(self, trinity):
        fleet = _fleet_dir()
        if fleet is None or not fleet.is_dir():
            pytest.skip("fleet directory src/aipass/ not present -- live-state guard skipped")

        clean: set[str] = set()
        audited: set[str] = set()
        for branch_dir in sorted(fleet.iterdir()):
            path = branch_dir / ".trinity" / "observations.json"
            if not path.is_file():
                continue
            audited.add(branch_dir.name)
            if not self._observation_problems(trinity, path):
                clean.add(branch_dir.name)

        if not audited:
            pytest.skip("no live .trinity/observations.json found -- live-state guard skipped")

        assert clean == set(_CANONICAL_OBSERVATION_BRANCHES), (
            "the clean set moved: update _CANONICAL_OBSERVATION_BRANCHES to the "
            "new migrated set, or find out why the checker stopped seeing drift"
        )

    def test_the_drifted_citizens_are_still_seen_as_drifted(self, trinity):
        fleet = _fleet_dir()
        if fleet is None or not fleet.is_dir():
            pytest.skip("fleet directory src/aipass/ not present -- live-state guard skipped")

        drifted = {}
        for branch_dir in sorted(fleet.iterdir()):
            path = branch_dir / ".trinity" / "observations.json"
            if not path.is_file() or branch_dir.name in _CANONICAL_OBSERVATION_BRANCHES:
                continue
            drifted[branch_dir.name] = self._observation_problems(trinity, path)

        if not drifted:
            pytest.skip("no drifted citizens on disk -- live-state guard skipped")

        blind = [name for name, problems in drifted.items() if not problems]
        assert blind == [], f"the checker went blind on {blind}"


# ===========================================================================
# E. Scoring mechanics
# ===========================================================================


class TestScoringMechanics:
    """Weights, group set, and the weighted mean."""

    def test_audit_scope_is_branch_level(self, trinity):
        assert trinity.AUDIT_SCOPE == "branch_level"

    def test_group_weights_sum_to_one_hundred(self, trinity):
        assert sum(trinity.GROUP_WEIGHTS.values()) == 100

    def test_group_weights_hold_the_nine_pinned_names(self, trinity):
        assert set(trinity.GROUP_WEIGHTS) == set(_GROUP_NAMES)

    def test_group_weights_are_the_pinned_numbers(self, trinity):
        assert trinity.GROUP_WEIGHTS == {
            "Entry shapes": 25,
            "Top-level keys": 15,
            "Ordering & numbering": 12,
            "Char caps": 12,
            "File set": 10,
            "Meta lines & _usage": 10,
            "Receipt": 8,
            "Todos hygiene": 5,
            "Freshness": 3,
        }

    def test_shape_weighs_heaviest_and_freshness_lightest(self, trinity):
        weights = trinity.GROUP_WEIGHTS
        assert weights["Entry shapes"] == max(weights.values())
        assert weights["Freshness"] == min(weights.values())

    def test_check_branch_returns_the_pinned_result_shape(self, trinity, tmp_path):
        branch = _write_branch(tmp_path)

        result = trinity.check_branch(str(branch))

        assert isinstance(result, dict)
        assert result["standard"] == "TRINITY"
        assert isinstance(result["score"], int)
        assert isinstance(result["passed"], bool)
        assert isinstance(result["checks"], list)

    def test_check_branch_returns_exactly_nine_named_checks(self, trinity, tmp_path):
        branch = _write_branch(tmp_path)

        result = trinity.check_branch(str(branch))

        assert len(result["checks"]) == 9
        assert [check["name"] for check in result["checks"]] == list(_GROUP_NAMES)

    def test_every_check_carries_the_four_pinned_keys(self, trinity, tmp_path):
        branch = _write_branch(tmp_path, local="{ broken")

        result = trinity.check_branch(str(branch))

        for check in result["checks"]:
            assert set(check) == {"name", "passed", "message", "score"}
            assert isinstance(check["score"], int)
            assert 0 <= check["score"] <= 100

    def test_overall_score_is_the_weighted_sum_of_group_subscores(self, trinity, tmp_path):
        local = _canonical_local()
        local["sessions"][0]["summary"] = "s" * 400
        local["document_metadata"]["last_updated"] = "2026-01-02"
        branch = _write_branch(tmp_path, local=local, receipt=None)

        result = trinity.check_branch(str(branch))

        weights = trinity.GROUP_WEIGHTS
        expected = round(sum(check["score"] * weights[check["name"]] for check in result["checks"]) / 100)
        assert result["score"] == expected

    def test_passed_is_true_only_at_one_hundred(self, trinity, tmp_path):
        clean_root = tmp_path / "clean"
        dirty_root = tmp_path / "dirty"
        local = _canonical_local()
        local["todos"][0]["status"] = "done"
        clean = trinity.check_branch(str(_write_branch(clean_root)))
        dirty = trinity.check_branch(str(_write_branch(dirty_root, local=local)))

        assert clean["score"] == 100 and clean["passed"] is True
        assert dirty["passed"] is False
        assert dirty["score"] < 100

    def test_a_single_bad_entry_in_a_hundred_never_rounds_up_to_a_pass(self, trinity, tmp_path):
        """99.75 must not become 100 -- a failure is never rounded into a pass."""
        observations = _canonical_observations()
        observations["observations"] = [
            {
                "number": number,
                "date": "2026-08-20",
                "note": f"observation {number}",
                "tags": [],
            }
            for number in range(100, 0, -1)
        ]
        observations["observations"][0]["session"] = 12
        del observations["observations"][0]["tags"]
        branch = _write_branch(tmp_path, observations=observations)

        result = trinity.check_branch(str(branch))

        assert _group(result, "Entry shapes")["score"] == 99
        assert result["score"] == 99
        assert result["passed"] is False

    def test_a_failing_group_never_scores_one_hundred(self, trinity, tmp_path):
        branch = _write_branch(tmp_path, local="{ broken")

        result = trinity.check_branch(str(branch))

        for check in result["checks"]:
            if not check["passed"]:
                assert check["score"] < 100


# ===========================================================================
# F. Meta composition -- the two implementations must never drift apart
# ===========================================================================


class TestMetaComposition:
    """expected_meta_line reproduces the renderer, byte for byte."""

    def test_todos_tab_format_is_pinned(self, trinity):
        line = trinity.expected_meta_line("todos", _BRANCH, _CONFIG, _PROSE["todos"])

        assert line == (
            "⟦ rollover OFF — operational, never trimmed · cap ~10 entries · task ≤150 chars ⟧ " + _PROSE["todos"]
        )

    def test_rollover_tab_with_a_count_is_pinned(self, trinity):
        line = trinity.expected_meta_line("sessions", _BRANCH, _CONFIG, _PROSE["sessions"])

        assert line == (
            "⟦ rollover ON → oldest archived to @memory · keep 15 · summary ≤300 chars ⟧ " + _PROSE["sessions"]
        )

    def test_rollover_tab_without_a_count_is_pinned(self, trinity):
        countless = copy.deepcopy(_CONFIG)
        countless["rollover"]["defaults"] = {}

        line = trinity.expected_meta_line("sessions", _BRANCH, countless, _PROSE["sessions"])

        assert line == f"{_NO_COUNT_TAB} {_PROSE['sessions']}"

    def test_the_tab_carries_the_config_number_not_a_constant(self, trinity):
        tightened = copy.deepcopy(_CONFIG)
        tightened["entry_limits"]["entry_types"]["sessions"]["max_chars"] = 275
        tightened["rollover"]["defaults"]["local"]["sessions"]["count"] = 9

        line = trinity.expected_meta_line("sessions", _BRANCH, tightened, _PROSE["sessions"])

        assert "keep 9" in line
        assert "≤275 chars" in line

    def test_the_tab_carries_the_config_field_name(self, trinity):
        renamed = copy.deepcopy(_CONFIG)
        renamed["entry_limits"]["entry_types"]["observations"]["field"] = "note_text"

        line = trinity.expected_meta_line("observations", _BRANCH, renamed, _PROSE["observations"])

        assert "note_text ≤300 chars" in line

    def test_per_branch_rollover_count_is_resolved_per_file_key(self, trinity):
        overridden = copy.deepcopy(_CONFIG)
        overridden["rollover"]["per_branch"] = {_BRANCH: {"local": {"sessions": {"count": 5}}}}

        line = trinity.expected_meta_line("sessions", _BRANCH, overridden, _PROSE["sessions"])

        assert "keep 5" in line

    def test_a_per_branch_file_key_shadows_the_defaults_for_that_file(self, trinity):
        """The engine's rule: a per_branch `local` block hides defaults.local."""
        overridden = copy.deepcopy(_CONFIG)
        overridden["rollover"]["per_branch"] = {_BRANCH: {"local": {"sessions": {"count": 5}}}}

        line = trinity.expected_meta_line("key_learnings", _BRANCH, overridden, _PROSE["key_learnings"])

        assert "no entry limit configured" in line

    def test_prose_comes_from_the_caller_not_from_the_module(self, trinity):
        line = trinity.expected_meta_line("observations", _BRANCH, _CONFIG, "SOME OTHER PROSE")

        assert line.endswith(" SOME OTHER PROSE")

    def test_load_template_prose_returns_the_four_sections(self, trinity):
        prose = trinity.load_template_prose()

        assert prose == _PROSE

    def test_load_template_prose_returns_none_when_templates_are_unreadable(self, trinity, monkeypatch):
        monkeypatch.setattr(trinity, "_load_templates", lambda: None)

        assert trinity.load_template_prose() is None

    def test_load_memory_config_returns_none_outside_a_repo(self, checker, monkeypatch):
        monkeypatch.setattr(checker, "_memory_dir", lambda: None)

        assert checker.load_memory_config() is None

    @pytest.mark.parametrize("branch_name", ["memory", "MEMORY", "Memory", "seedgo"])
    @pytest.mark.parametrize("section", ["todos", "key_learnings", "sessions", "observations"])
    def test_expected_meta_line_is_byte_identical_to_the_renderer(self, checker, branch_name, section):
        """The cross-implementation guard: two composers, one string.

        @memory's tab_renderer.compose_meta writes these lines; this checker
        decides whether what it finds is right. If the two ever disagree the
        fleet fails a group forever with nobody able to fix it.
        """
        if _compose_meta is None:
            pytest.skip(f"@memory tab_renderer unavailable: {_COMPOSE_META_IMPORT_ERROR}")
        config = checker.load_memory_config()
        prose = checker.load_template_prose()
        if config is None or prose is None:
            pytest.skip("live memory.config.json or gold templates unavailable")

        mine = checker.expected_meta_line(section, branch_name, config, prose[section])
        theirs = _compose_meta(section, config.get("rollover", {}), config.get("entry_limits", {}), branch_name)

        assert mine == theirs

    def test_per_branch_char_cap_override_survives_the_renderer(self, checker):
        if _compose_meta is None:
            pytest.skip(f"@memory tab_renderer unavailable: {_COMPOSE_META_IMPORT_ERROR}")
        config = checker.load_memory_config()
        prose = checker.load_template_prose()
        if config is None or prose is None:
            pytest.skip("live memory.config.json or gold templates unavailable")
        overridden = copy.deepcopy(config)
        overridden.setdefault("entry_limits", {}).setdefault("per_branch", {})["seedgo"] = {
            "observations": {"max_chars": 120}
        }

        mine = checker.expected_meta_line("observations", "seedgo", overridden, prose["observations"])
        theirs = _compose_meta(
            "observations",
            overridden.get("rollover", {}),
            overridden.get("entry_limits", {}),
            "seedgo",
        )

        assert mine == theirs


# ===========================================================================
# G. Bypass is deliberately absent
# ===========================================================================


class TestBypassIsDeliberatelyAbsent:
    """The contract: "None for shape rules, by design."

    A bypassable memory standard recreates the drift it exists to end. These
    tests pin the design decision so nobody "fixes" it into existence later.
    """

    _RULES = [
        {"file": ".trinity/local.json", "standard": "trinity", "reason": "would suppress the standard"},
        {"file": ".trinity/observations.json", "standard": "trinity", "reason": "would suppress the standard"},
        {"file": "", "standard": "trinity", "reason": "branch-wide suppression attempt"},
        {"standard": "trinity", "reason": "standard-level suppression attempt"},
    ]

    def test_bypass_rules_do_not_raise_a_failing_score(self, trinity, tmp_path):
        local = _canonical_local()
        local["key_learnings"][0] = {"number": 2, "date": "2026-08-24", "learning": "merged blob"}
        branch = _write_branch(tmp_path, local=local)

        without = trinity.check_branch(str(branch))
        with_rules = trinity.check_branch(str(branch), bypass_rules=self._RULES)

        assert with_rules == without
        assert with_rules["passed"] is False

    def test_bypass_rules_leave_every_group_untouched(self, trinity, tmp_path):
        branch = _write_branch(tmp_path, local="{ broken", receipt=None)

        without = trinity.check_branch(str(branch))
        with_rules = trinity.check_branch(str(branch), bypass_rules=self._RULES)

        assert with_rules["checks"] == without["checks"]
        assert with_rules["score"] == without["score"]

    def test_a_clean_branch_is_unaffected_by_bypass_rules(self, trinity, tmp_path):
        branch = _write_branch(tmp_path)

        assert trinity.check_branch(str(branch), bypass_rules=self._RULES) == trinity.check_branch(str(branch))

    def test_an_empty_bypass_list_and_none_agree(self, trinity, tmp_path):
        branch = _write_branch(tmp_path, receipt=None)

        assert trinity.check_branch(str(branch), bypass_rules=[]) == trinity.check_branch(
            str(branch), bypass_rules=None
        )

    def test_the_checker_never_imports_the_bypass_helper(self, trinity):
        """No bypass import, and no call to one -- only the prose that says why."""
        source = Path(trinity.__file__).read_text(encoding="utf-8")
        imports = [line.strip() for line in source.splitlines() if line.startswith(("import ", "from "))]

        assert not any("bypass" in line for line in imports), imports
        assert not hasattr(trinity, "is_bypassed")
        assert "trinity contract" in trinity.check_branch.__doc__.lower()


# ===========================================================================
# H. The silent-pass hole this checker was almost born with -- regression guard
# ===========================================================================


class TestKnownSilentPassHole:
    """The checker's own violation of THE ONE LAW, found by test and closed.

    Shipped state of _records_check dropped its violation records whenever the
    entry denominator came out clean, and _cap_probe's config-has-no-spec
    record contributes nothing to that denominator when the container is empty.
    Char caps answered 'All 0 entries are within their configured caps',
    passed=True, score=100 -- a silent pass of something the checker had just
    said it could not measure, inside the standard written to end exactly that.
    Fixed in _records_check: records decide whether, the denominator only
    decides how bad. This test is the guard, not a bug report.
    """

    def test_char_caps_must_not_pass_when_the_config_has_no_spec(self, trinity, tmp_path, monkeypatch):
        specless = copy.deepcopy(_CONFIG)
        specless["entry_limits"]["entry_types"] = {}
        local = _canonical_local()
        observations = _canonical_observations()
        for section in ("todos", "key_learnings", "sessions"):
            local[section] = []
        observations["observations"] = []
        branch = _write_branch(tmp_path, local=local, observations=observations)

        monkeypatch.setattr(trinity, "load_memory_config", lambda: copy.deepcopy(specless))

        result = trinity.check_branch(str(branch))

        check = _group(result, "Char caps")
        assert check["passed"] is False, f"silent pass: {check['message']}"
        assert check["score"] < 100


# ===========================================================================
# A RELATIVE BRANCH PATH NAMES THE SAME BRANCH AN ABSOLUTE ONE DOES
# ===========================================================================


class TestARelativeBranchPathStillNamesTheBranch:
    """Found while verifying my own memories after a write: running the checker
    on "." reported score 93 with 'document_name seedgo.LOCAL does not name
    branch ' and 'managed_by seedgo != branch directory name ' -- note the
    empty branch in both messages. The same tree on an absolute path scored
    100.

    Cause: _build_context took branch_path.name verbatim, and Path(".").name
    is the empty string. Every relative invocation -- a caller standing in the
    branch, a test helper, anything shelling out with cwd -- silently measured
    Top-level keys against a branch called "". The failure is worse than a
    crash because it looks like real drift and names files that are correct.

    Fix: resolve the path before deriving the name. These tests pin that a
    relative and an absolute path answer identically.
    """

    def test_a_relative_path_scores_the_same_as_an_absolute_one(self, trinity, tmp_path, monkeypatch):
        branch = _write_branch(tmp_path)

        absolute = trinity.check_branch(str(branch))
        monkeypatch.chdir(branch)
        relative = trinity.check_branch(".")

        assert relative["score"] == absolute["score"]
        assert relative["passed"] == absolute["passed"]

    def test_dot_does_not_invent_an_empty_branch_name(self, trinity, tmp_path, monkeypatch):
        branch = _write_branch(tmp_path)
        monkeypatch.chdir(branch)

        result = trinity.check_branch(".")

        top = _group(result, "Top-level keys")
        assert "branch " not in top["message"], f"empty branch name leaked: {top['message']}"
        assert top["passed"] is True

    def test_a_trailing_dot_segment_resolves_to_the_branch(self, trinity, tmp_path):
        """Green before the fix as well as after, and kept deliberately: it
        pins WHY the bug was only ever a bare "." -- pathlib drops interior and
        trailing "." segments when it parses, so "<branch>/." already carried
        the name. Without this the reader would reasonably assume every dotted
        form was broken.
        """
        branch = _write_branch(tmp_path)

        result = trinity.check_branch(f"{branch}/.")

        assert result["score"] == 100


# ===========================================================================
# THE SPLIT: trinity_groups holds the nine, trinity_check holds the engine
# ===========================================================================


class TestTheGroupSplitKeepsTheNine:
    """trinity_check.py crossed the 1500-line architecture cap during the
    marker-7 work, so the group checkers moved to trinity_groups.py on
    2026-08-27. A relocation, not a redesign -- but the one regression a split
    invites is a group quietly going missing, and a missing group does not
    fail loudly: the weighted mean simply divides by less and the branch scores
    HIGHER. That is the exact shape of a silent pass this standard exists to
    end, so it gets pinned rather than assumed.
    """

    def test_all_groups_returns_every_weighted_group_in_reporting_order(self, trinity, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards import trinity_groups

        branch = _write_branch(tmp_path)
        ctx = trinity._build_context(branch)

        names = [check["name"] for check in trinity_groups.all_groups(ctx)]

        assert names == [
            "Entry shapes",
            "Top-level keys",
            "Ordering & numbering",
            "Char caps",
            "File set",
            "Meta lines & _usage",
            "Receipt",
            "Todos hygiene",
            "Freshness",
        ]
        assert set(names) == set(trinity.GROUP_WEIGHTS), "a group is weighted but never run, or run but never weighted"

    def test_check_branch_reports_the_same_nine(self, trinity, tmp_path):
        branch = _write_branch(tmp_path)

        result = trinity.check_branch(str(branch))

        assert [c["name"] for c in result["checks"]] == list(trinity.GROUP_WEIGHTS)

    def test_the_engine_does_not_reach_past_the_public_entry_point(self, trinity):
        """The nine used to be imported by name into the engine, which is how a
        forgotten group becomes possible. Pin that the engine holds one handle.
        """
        source = Path(trinity.__file__).read_text(encoding="utf-8")

        assert "all_groups(ctx)" in source
        assert "_group_entry_shapes" not in source, "engine reaches past all_groups again"
