# =================== AIPass ====================
# Name: test_trinity_check_file_shape.py
# Description: trinity_check file shape: metadata, guidelines, file set, receipt (split from test_trinity_check.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/aipass_standards/trinity_check.py and trinity_groups.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — json.loads() of a well-formed trinity file; only the malformed ones are the subject

import copy
from pathlib import Path

import pytest

from aipass.seedgo.tests.support_trinity_check import (
    _BRANCH,
    _TABS,
    _TEMPLATES,
    _assert_failed,
    _canonical_local,
    _canonical_observations,
    _canonical_receipt,
    _group,
    _write_branch,
    _write_doc,
)

pytestmark = pytest.mark.usefixtures("_mock_infrastructure")


class TestDocumentMetadataIsAClosedSet:
    """``document_metadata`` is a closed set: an extra field such as ``limits`` is flagged."""

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
        """``status`` keeps its own diagnostic (health is computed, never stored), not a generic unexpected-field one."""
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


class TestGuidelinesContentIsScored:
    """The ``guidelines`` block's content is scored against the template, not just the presence of its keys."""

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
        """Unreadable templates refuse the guidelines group rather than score it zero: unmeasurable is refused, never scored."""
        monkeypatch.setattr(trinity, "_load_templates", lambda: None)
        branch = _write_branch(tmp_path)

        _assert_failed(_group(trinity.check_branch(str(branch)), "Meta lines & _usage"), "never assumed")

    @pytest.mark.parametrize("bad", [None, "a string", 42])
    def test_a_gold_template_missing_its_guidelines_block_refuses(self, trinity, tmp_path, monkeypatch, bad):
        """The refusal path that the all-templates-None case cannot reach."""
        templates = copy.deepcopy(_TEMPLATES)
        if bad is None:
            del templates["observations"]["guidelines"]
        else:
            templates["observations"]["guidelines"] = bad
        monkeypatch.setattr(trinity, "_load_templates", lambda: templates)
        branch = _write_branch(tmp_path)

        _assert_failed(_group(trinity.check_branch(str(branch)), "Meta lines & _usage"), "guidelines", "never assumed")


class TestVersionedBackupsAreLegalResidents:
    """Versioned backups (canonical name, ``.pre``, separator, version token) are legal residents; ``.tmp`` staging files are not."""

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

    @pytest.mark.parametrize(
        "name",
        [
            "local.json.tmp",  # torn-write staging -- the species seedgo found live
            "local.json.bak",
            "local.json.swp",
            "local.json.orig",
            "observations.json.lock",
            "tmp2ay2d070.tmp",
            "STATUS.local.md",  # seedgo's own, still mine to relocate or defend
            "watchdog_active.json",  # devpulse's, banked as their todo
            "watchdog_active.json.lock",
            "local.json.pre",  # no separator, no token -- ambiguous
            "local.json.pre_",  # token must start alphanumeric
            "local.json.pre-",
            "local.json.pre_v3_backup.tmp",  # a temp file wearing a backup's name
            "local.jsonpre_v3",  # no dot before the marker
            "local.json.post_v3",  # 'pre' is the anchor the convention uses
        ],
    )
    def test_machine_artifacts_are_still_strays(self, trinity, tmp_path, name):
        """A backup rule that swallows temp files hides torn writes."""
        branch = _write_branch(tmp_path)
        (branch / ".trinity" / name).write_text("x\n", encoding="utf-8")

        _assert_failed(_group(trinity.check_branch(str(branch)), "File set"), f"stray {name}")

    def test_a_backup_of_a_non_canonical_base_is_still_a_stray(self, trinity, tmp_path):
        """Versioning a stray does not launder it into a resident."""
        branch = _write_branch(tmp_path)
        (branch / ".trinity" / "STATUS.local.md.pre_v3_backup").write_text("x\n", encoding="utf-8")

        _assert_failed(_group(trinity.check_branch(str(branch)), "File set"), "stray STATUS.local.md.pre_v3_backup")

    def test_a_directory_named_like_a_backup_is_still_a_stray(self, trinity, tmp_path):
        """The convention renames a FILE. A directory of junk is not a version."""
        branch = _write_branch(tmp_path)
        (branch / ".trinity" / "local.json.pre_v3_backup").mkdir()

        _assert_failed(_group(trinity.check_branch(str(branch)), "File set"), "stray local.json.pre_v3_backup/")

    def test_both_lanes_agree_on_what_a_stray_is(self, trinity, tmp_path):
        """The scored group and the info channel read the same helper, so they cannot diverge on what a stray is."""
        branch = _write_branch(tmp_path)
        (branch / ".trinity" / "local.json.pre_v3_backup").write_text("{}\n", encoding="utf-8")
        (branch / ".trinity" / "STATUS.local.md").write_text("x\n", encoding="utf-8")

        result = trinity.check_branch(str(branch))
        info = trinity.check_branch_info(str(branch))

        assert info == ["trinity: stray .trinity/STATUS.local.md"]
        _assert_failed(_group(result, "File set"), "stray STATUS.local.md")
        assert "pre_v3_backup" not in _group(result, "File set")["message"]

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
        """The predicate reads names only, with no filesystem: the caller owns the directory rule."""
        assert trinity.is_versioned_backup(name) is expected

    def test_d14_check_branch_info_is_empty_when_trinity_is_absent(self, trinity, tmp_path):
        # Registry present: a live installation. On a fresh clone the same shape announces itself instead.
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

    def test_a_todo_carrying_status_is_flagged_by_entry_shapes(self, trinity, tmp_path):
        """DPLAN-0345: todos have no status -- done means deleted, and the key is outside the closed shape."""
        local = _canonical_local()
        local["todos"][0]["status"] = "Done"
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Entry shapes"), "unexpected field 'status'")

    def test_a_todo_without_priority_is_canonical(self, trinity, tmp_path):
        """priority is optional in the v2 shape; number, date and task are the whole requirement."""
        local = _canonical_local()
        local["todos"] = [{"number": 1, "date": "2026-08-20", "task": "fix drone help"}]
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        assert _group(result, "Entry shapes")["passed"] is True, _group(result, "Entry shapes")["message"]

    def test_a_todo_priority_of_the_wrong_type_is_flagged(self, trinity, tmp_path):
        local = _canonical_local()
        local["todos"][0]["priority"] = 1
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Entry shapes"), "priority must be str, found int")

    def test_a_todo_missing_its_task_is_flagged(self, trinity, tmp_path):
        local = _canonical_local()
        del local["todos"][1]["task"]
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Entry shapes"), "missing required field 'task'")


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


class TestTheMintStampIsNotAViolation:
    """Passport seeds (TDPLAN-0017) add one optional field to LIVE passports:"""

    _SEED_STAMP = {"version": "1.0.0", "sha256": "0" * 64}

    @staticmethod
    def _write_passport(branch: Path, *, stamp: bool) -> None:
        """Replace the fixture's placeholder passport with a real 2.0 one."""
        citizenship = {
            "registered": True,
            "residency": "core",
            "registry_id": "7087bb93-570f-4b9a-b035-4fd7f570200e",
            "citizen_id": "a41235f5-1ca9-489f-8191-b106d398c0fa",
            "registry_path": ".aipass/registry.json",
            "communications": True,
            "memory": True,
        }
        if stamp:
            citizenship["seed"] = dict(TestTheMintStampIsNotAViolation._SEED_STAMP)
        payload = {
            "document_metadata": {
                "document_type": "branch_identity",
                "document_name": f"{_BRANCH}.PASSPORT",
                "version": "2.0.0",
                "schema_version": "2.0.0",
                "created": "2026-01-01",
                "last_updated": "2026-08-28",
                "managed_by": _BRANCH,
                "tags": ["identity", "passport", "branch_profile"],
            },
            "branch_info": {
                "branch_name": _BRANCH,
                "alias": "",
                "path": f"src/aipass/{_BRANCH}",
                "module": f"aipass.{_BRANCH}",
                "email": f"@{_BRANCH}",
                "created": "2026-01-01",
                "git_branch": "dev",
            },
            "citizenship": citizenship,
            "identity": {
                "citizen_class": "specialist",
                "role": "fixture",
                "purpose": "Stand in for a live passport.",
                "what_i_do": [],
                "what_i_dont_do": [],
                "traits": [],
                "principles": [],
            },
        }
        _write_doc(branch / ".trinity" / "passport.json", payload)

    def test_a_stamped_passport_scores_exactly_what_an_unstamped_one_scores(self, trinity, tmp_path):
        """Not just "still 100" -- the whole result, group by group, identical."""
        plain_branch = _write_branch(tmp_path / "plain")
        self._write_passport(plain_branch, stamp=False)
        stamped_branch = _write_branch(tmp_path / "stamped")
        self._write_passport(stamped_branch, stamp=True)

        plain = trinity.check_branch(str(plain_branch))
        stamped = trinity.check_branch(str(stamped_branch))

        assert stamped == plain
        assert stamped["score"] == 100, stamped["checks"]

    def test_the_tolerance_is_structural_the_passport_is_never_opened(self, trinity, tmp_path):
        """The passport is never opened: invalid JSON still scores 100, because File set only asks the directory for the name."""
        branch = _write_branch(tmp_path)
        _write_doc(branch / ".trinity" / "passport.json", "not json at all {{")

        result = trinity.check_branch(str(branch))

        assert result["score"] == 100
        assert _group(result, "File set")["passed"] is True

    def test_the_contract_still_says_passports_are_existence_only(self, trinity):
        """The checker's docstring says passports are existence-only, so a new passport rule fails here first."""
        assert "EXISTENCE only" in trinity.__doc__
        assert "nothing inside a passport is read or judged" in trinity.__doc__
