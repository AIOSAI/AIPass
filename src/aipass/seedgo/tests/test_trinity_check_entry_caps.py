# =================== AIPass ====================
# Name: test_trinity_check_entry_caps.py
# Description: trinity_check entry shapes, caps and numbering: drift classes D1-D16 (split from test_trinity_check.py)
# Version: 1.1.0
# Created: 2026-10-08
# Modified: 2026-10-23
# =============================================

"""Tests for apps/handlers/aipass_standards/trinity_check.py and trinity_groups.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — json.loads() of a well-formed trinity file; only the malformed ones are the subject

import copy
import json
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import trinity_groups
from aipass.seedgo.tests.support_trinity_check import (
    _BRANCH,
    _CONFIG,
    _PROSE,
    _assert_failed,
    _canonical_local,
    _canonical_observations,
    _group,
    _write_branch,
)

pytestmark = pytest.mark.usefixtures("_mock_infrastructure")

# @memory's push reads the same entry_types.<type>.fields map; found by file, before the autouse mock swaps aipass.prax.
# limits comes through memory/apps/modules (its published door); the module is held, not the symbol, so drift raises AttributeError.
_PUSH_RELATIVE = ("src", "aipass", "memory", "apps", "modules", "door_trinity_push.py")
_entry_rules = None
_memory_limits = None
_MEMORY_SHAPE_IMPORT_ERROR = "@memory door_trinity_push.py is not on disk"

for _parent in Path(__file__).resolve().parents:
    if _parent.joinpath(*_PUSH_RELATIVE).is_file():
        from aipass.memory.apps.modules.door_trinity_push import entry_rules as _entry_rules
        from aipass.memory.apps.modules import limits as _memory_limits

        _MEMORY_SHAPE_IMPORT_ERROR = ""
        break


def _strings_in(value) -> set:
    """Every string reachable inside a constant, at any depth."""
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return set().union(*(_strings_in(k) | _strings_in(v) for k, v in value.items())) if value else set()
    if isinstance(value, (list, tuple, set, frozenset)):
        return set().union(*(_strings_in(item) for item in value)) if value else set()
    return set()


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
        """D3 -- over-cap notes, measured against the CONFIG number; 331 is one past the 10% band."""
        observations = _canonical_observations()
        observations["observations"][0]["note"] = "x" * 331
        branch = _write_branch(tmp_path, observations=observations)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Char caps"), "'note' is 331 chars", "cap 300")

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
        local["key_learnings"][0]["value"] = "v" * 221
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Char caps"), "'value' is 221 chars", "cap 200")

    def test_d8_todo_task_over_cap(self, trinity, tmp_path):
        local = _canonical_local()
        local["todos"][0]["task"] = "t" * 166
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Char caps"), "'task' is 166 chars", "cap 150")

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


# The entry shape is read from @memory, never remembered.


class TestTheToleranceBand:
    """@memory's gate accepts up to tolerance_percent over a cap; the Char caps group measures the same band."""

    @staticmethod
    def _note_result(trinity, tmp_path, monkeypatch, length, **limits):
        """Char caps over one observation note of *length*, under an entry_limits patched by *limits*."""
        config = copy.deepcopy(_CONFIG)
        config["entry_limits"].update(limits)
        monkeypatch.setattr(trinity, "load_memory_config", lambda: copy.deepcopy(config))
        observations = _canonical_observations()
        observations["observations"][0]["note"] = "n" * length
        return _group(trinity.check_branch(str(_write_branch(tmp_path, observations=observations))), "Char caps")

    def test_a_note_at_the_edge_of_the_band_passes(self, trinity, tmp_path, monkeypatch):
        assert self._note_result(trinity, tmp_path, monkeypatch, 330)["passed"] is True

    def test_one_char_past_the_band_fails_naming_the_plain_cap(self, trinity, tmp_path, monkeypatch):
        _assert_failed(self._note_result(trinity, tmp_path, monkeypatch, 331), "'note' is 331 chars", "cap 300")

    def test_the_band_comes_from_the_config(self, trinity, tmp_path, monkeypatch):
        result = self._note_result(trinity, tmp_path, monkeypatch, 301, tolerance_percent=0)
        _assert_failed(result, "'note' is 301 chars", "cap 300")

    @pytest.mark.parametrize("raw", [True, 101, -1, "10", None])
    def test_an_unusable_band_is_served_as_the_seed_of_10(self, trinity, tmp_path, monkeypatch, raw):
        assert self._note_result(trinity, tmp_path, monkeypatch, 330, tolerance_percent=raw)["passed"] is True
        _assert_failed(self._note_result(trinity, tmp_path, monkeypatch, 331, tolerance_percent=raw), "cap 300")

    def test_the_band_rounds_down_to_whole_characters(self, trinity, tmp_path, monkeypatch):
        """205 * 110 // 100 = 225: 225 passes, 226 fails."""
        per_branch = {_BRANCH: {"observations": {"max_chars": 205}}}
        assert self._note_result(trinity, tmp_path, monkeypatch, 225, per_branch=per_branch)["passed"] is True
        result = self._note_result(trinity, tmp_path, monkeypatch, 226, per_branch=per_branch)
        _assert_failed(result, "'note' is 226 chars", "cap 205")


class TestTheEntryShapeComesFromTheConfig:
    """The shape has one home and it is @memory's config, not this branch."""

    def test_a_new_required_field_in_the_config_is_required_here(self, trinity, tmp_path, monkeypatch):
        """Move the config, the shape moves. The canonical fixture now misses a field."""
        widened = copy.deepcopy(_CONFIG)
        widened["entry_limits"]["entry_types"]["observations"]["fields"]["mood"] = {
            "type": "str",
            "required": True,
        }
        branch = _write_branch(tmp_path)

        monkeypatch.setattr(trinity, "load_memory_config", lambda: copy.deepcopy(widened))
        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Entry shapes"), "missing required field 'mood'")

    def test_a_field_dropped_from_the_config_becomes_an_extra(self, trinity, tmp_path, monkeypatch):
        """The closed set closes from the config too -- `tags` is legal only while it is published."""
        narrowed = copy.deepcopy(_CONFIG)
        del narrowed["entry_limits"]["entry_types"]["observations"]["fields"]["tags"]
        branch = _write_branch(tmp_path)

        monkeypatch.setattr(trinity, "load_memory_config", lambda: copy.deepcopy(narrowed))
        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Entry shapes"), "unexpected field 'tags'")

    def test_flipping_required_in_the_config_flips_the_verdict(self, trinity, tmp_path, monkeypatch):
        """`priority` is optional today; the config alone decides that."""
        strict = copy.deepcopy(_CONFIG)
        strict["entry_limits"]["entry_types"]["todos"]["fields"]["priority"]["required"] = True
        branch = _write_branch(tmp_path)

        monkeypatch.setattr(trinity, "load_memory_config", lambda: copy.deepcopy(strict))
        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Entry shapes"), "missing required field 'priority'")

    def test_the_type_comes_from_the_config_not_from_a_remembered_spec(self, trinity, tmp_path, monkeypatch):
        """Retype `number` in the config and the int entries become violations against the new type."""
        retyped = copy.deepcopy(_CONFIG)
        retyped["entry_limits"]["entry_types"]["observations"]["fields"]["number"]["type"] = "list[str]"
        branch = _write_branch(tmp_path)

        monkeypatch.setattr(trinity, "load_memory_config", lambda: copy.deepcopy(retyped))
        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Entry shapes"), "number must be list[str], found int")

    def test_a_per_branch_override_moves_the_shape_for_that_branch(self, trinity, tmp_path, monkeypatch):
        """Same resolution the caps take: per_branch wins, case-insensitively."""
        overridden = copy.deepcopy(_CONFIG)
        overridden["entry_limits"]["per_branch"] = {
            _BRANCH.upper(): {
                "todos": {
                    "fields": {
                        "number": {"type": "int", "required": True},
                        "date": {"type": "str", "required": True},
                        "task": {"type": "str", "required": True},
                    }
                }
            }
        }
        branch = _write_branch(tmp_path)

        monkeypatch.setattr(trinity, "load_memory_config", lambda: copy.deepcopy(overridden))
        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Entry shapes"), "unexpected field 'priority'")

    @pytest.mark.parametrize(
        ("section", "mangle"),
        [
            pytest.param("observations", lambda d: d.pop("fields"), id="no-fields-key"),
            pytest.param("observations", lambda d: d.update(fields={}), id="empty-fields-map"),
            pytest.param("observations", lambda d: d.update(fields="a string"), id="fields-not-a-map"),
            pytest.param("todos", lambda d: d["fields"].update(task="str"), id="field-spec-not-a-map"),
            pytest.param("todos", lambda d: d["fields"]["task"].pop("type"), id="field-spec-without-a-type"),
        ],
    )
    def test_a_config_with_no_usable_fields_map_fails_closed_naming_the_key(
        self, trinity, tmp_path, section, mangle, monkeypatch
    ):
        """The Char caps contract, applied to the shape: it is never assumed."""
        broken = copy.deepcopy(_CONFIG)
        mangle(broken["entry_limits"]["entry_types"][section])
        branch = _write_branch(tmp_path)

        monkeypatch.setattr(trinity, "load_memory_config", lambda: copy.deepcopy(broken))
        result = trinity.check_branch(str(branch))

        check = _group(result, "Entry shapes")
        _assert_failed(check, f"cannot measure shapes for '{section}'", f"entry_types.{section}.fields")

    def test_an_empty_container_cannot_hide_the_refusal(self, trinity, tmp_path, monkeypatch):
        """The silent-pass hole Char caps had: no entries, so nothing to divide by."""
        broken = copy.deepcopy(_CONFIG)
        del broken["entry_limits"]["entry_types"]["observations"]["fields"]
        observations = _canonical_observations()
        observations["observations"] = []
        branch = _write_branch(tmp_path, observations=observations)

        monkeypatch.setattr(trinity, "load_memory_config", lambda: copy.deepcopy(broken))
        result = trinity.check_branch(str(branch))

        check = _group(result, "Entry shapes")
        assert check["passed"] is False, f"silent pass: {check['message']}"
        assert check["score"] < 100

    def test_an_unreadable_config_refuses_entry_shapes_rather_than_assuming_one(self, trinity, tmp_path, monkeypatch):
        """No config, no shape -- the same answer Char caps gives for its numbers."""
        branch = _write_branch(tmp_path)

        monkeypatch.setattr(trinity, "load_memory_config", lambda: None)
        result = trinity.check_branch(str(branch))

        _assert_failed(
            _group(result, "Entry shapes"),
            "cannot measure shapes",
            "memory.config.json unreadable",
            "never assumed",
        )

    def test_a_legal_entry_still_passes_and_an_illegal_field_still_fails(self, trinity, tmp_path):
        """The behaviour that must NOT move: canonical passes, an extra key fails."""
        clean = trinity.check_branch(str(_write_branch(tmp_path / "clean")))

        drifted_local = _canonical_local()
        drifted_local["sessions"][0]["findings"] = ["bolted on"]
        dirty = trinity.check_branch(str(_write_branch(tmp_path / "dirty", local=drifted_local)))

        assert _group(clean, "Entry shapes")["score"] == 100
        assert _group(clean, "Char caps")["score"] == 100
        assert clean["score"] == 100
        _assert_failed(_group(dirty, "Entry shapes"), "unexpected field 'findings'")
        assert _group(dirty, "Char caps")["score"] == 100, "a shape violation must not move the cap group"

    def test_the_module_carries_no_copy_of_the_shape(self, trinity):
        """The mirror is GONE, not merely unused -- an unused copy grows a caller."""
        carried: set = set()
        for name, value in vars(trinity_groups).items():
            if name.startswith("__") or callable(value):
                continue
            carried |= _strings_in(value)

        assert not hasattr(trinity_groups, "_ENTRY_RULES"), "the hand-kept shape mirror is back"
        # Four field names that belong to @memory's shape and to nothing else
        # this module legitimately names. A literal shape cannot come back
        # without at least one of them landing in a module constant.
        assert not ({"summary", "task", "note", "priority"} & carried), (
            f"entry field names are carried in a module constant again: "
            f"{sorted({'summary', 'task', 'note', 'priority'} & carried)}"
        )

    def test_the_derived_shape_is_byte_identical_to_what_memorys_push_derives(self, trinity):
        """The cross-implementation guard, for the shape."""
        assert _entry_rules is not None, (
            f"@memory's trinity_push is the OTHER side of this guard and it is unreachable "
            f"({_MEMORY_SHAPE_IMPORT_ERROR}) - the shape agreement cannot be checked, which is a "
            f"finding about the fleet and not a reason to pass"
        )
        live = trinity.load_memory_config()
        assert live is not None, "live memory.config.json is unreadable - the shape has no source"

        mine = trinity.entry_shapes(live, "memory")

        assert mine, "the live config publishes no closed shape at all"
        for section in ("todos", "key_learnings", "sessions", "observations"):
            assert mine.get(section) == _entry_rules(section), f"{section}: the two derivations disagree"

    @pytest.mark.parametrize("cap", [300, 200, 150, 77, 1])
    def test_the_draft_target_matches_memorys_own_answer_on_the_live_config(self, trinity, cap):
        """The tab's draft number agrees with @memory's, through @memory's door."""
        assert _memory_limits is not None, (
            f"@memory's limits gateway is the source of the draft number and it is unreachable "
            f"({_MEMORY_SHAPE_IMPORT_ERROR}) - the draft target has nothing to be checked against"
        )
        live = trinity.load_memory_config()
        assert live is not None, "live memory.config.json is unreadable - the draft percent has no source"
        capped = copy.deepcopy(live)
        capped["entry_limits"]["entry_types"]["sessions"]["max_chars"] = cap

        line = trinity.expected_meta_line("sessions", "memory", capped, _PROSE["sessions"])

        assert line.endswith(f"≤{cap} chars · draft to {_memory_limits.draft_target(cap)} ⟧ {_PROSE['sessions']}")
