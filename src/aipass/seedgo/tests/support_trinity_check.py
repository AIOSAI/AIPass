# =================== AIPass ====================
# Name: support_trinity_check.py
# Description: Shared gold data and builders for the trinity_check test files (split from test_trinity_check.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Shared helpers for the tests of apps/handlers/aipass_standards/trinity_check.py (not test_: never collected)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import json
from pathlib import Path

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
    # DPLAN-0345: the pad tab. The fixture branch directory is _BRANCH and its
    # pad holds numbers 2 and 1, so a render with branch context writes next #3.
    "todos": (
        "⟦ pad of 10 · oldest roll to .backup/todo/testbranch/backlog.json · task ≤150 chars · draft to 120 · next #3 ⟧"
    ),
    "key_learnings": ("⟦ rollover ON → oldest archived to @memory · keep 15 · value ≤200 chars · draft to 160 ⟧"),
    "sessions": ("⟦ rollover ON → oldest archived to @memory · keep 15 · summary ≤300 chars · draft to 240 ⟧"),
    "observations": ("⟦ rollover ON → oldest archived to @memory · keep 15 · note ≤300 chars · draft to 240 ⟧"),
}

_CONFIG = {
    "entry_limits": {
        "enabled": True,
        "enforce": True,
        # @memory's key since 2026-09-16, and the ONLY source of the "draft to
        # N" half of every tab. A fixture without it renders the unpublished
        # marker, which is the behaviour TestTheDraftPercentIsRead pins.
        "draft_percent": 80,
        "entry_types": {
            "key_learnings": {
                "file": "local.json",
                "container": "key_learnings",
                "kind": "list",
                "field": "value",
                "max_chars": 200,
                "fields": {
                    "number": {"type": "int", "required": True},
                    "date": {"type": "str", "required": True, "max_chars": 10},
                    "key": {"type": "str", "required": True, "max_chars": 80},
                    "value": {"type": "str", "required": True, "max_chars": 200},
                },
            },
            "sessions": {
                "file": "local.json",
                "container": "sessions",
                "kind": "list",
                "field": "summary",
                "max_chars": 300,
                "fields": {
                    "number": {"type": "int", "required": True},
                    "date": {"type": "str", "required": True, "max_chars": 10},
                    "summary": {"type": "str", "required": True, "max_chars": 300},
                    "status": {"type": "str", "required": True, "max_chars": 40},
                    "tags": {"type": "list[str]", "required": False, "max_items": 10, "max_chars": 120},
                },
            },
            "todos": {
                "file": "local.json",
                "container": "todos",
                "kind": "list",
                "field": "task",
                "max_chars": 150,
                "fields": {
                    "number": {"type": "int", "required": True},
                    "date": {"type": "str", "required": True, "max_chars": 10},
                    "task": {"type": "str", "required": True, "max_chars": 150},
                    "priority": {"type": "str", "required": False, "max_chars": 10},
                },
            },
            "observations": {
                "file": "observations.json",
                "container": "observations",
                "kind": "list",
                "field": "note",
                "max_chars": 300,
                "fields": {
                    "number": {"type": "int", "required": True},
                    "date": {"type": "str", "required": True, "max_chars": 10},
                    "note": {"type": "str", "required": True, "max_chars": 300},
                    "tags": {"type": "list[str]", "required": True, "max_items": 10, "max_chars": 120},
                },
            },
        },
        "per_branch": {},
    },
    "rollover": {
        "defaults": {
            "local": {
                "sessions": {"count": 15, "auto_compact_cap": 3},
                "key_learnings": {"count": 15},
                "todos": {"count": 10},
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
            },
            {
                "number": 1,
                "date": "2026-08-20",
                "task": "read the trinity contract",
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
