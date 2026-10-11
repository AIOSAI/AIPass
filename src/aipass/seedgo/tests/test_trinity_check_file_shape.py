# =================== AIPass ====================
# Name: test_trinity_check_file_shape.py
# Description: trinity_check file shape: metadata, guidelines, file set, receipt (split from test_trinity_check.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
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
# D14b. Versioned backups are LEGAL residents (the owner's File set ruling)
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
        """A backup rule that swallows temp files hides torn writes.

        The same body held two more claims, folded in here with every case
        (compass 443; seedgo, fleet green leg 8): the deliberately flagged
        operational files still flag, because the ruling kept them on purpose
        and their owners relocate; and the near misses of the backup pattern
        are still strays.
        """
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
# TDPLAN-0017. citizenship.seed -- the mint stamp is not a violation here
# ===========================================================================


class TestTheMintStampIsNotAViolation:
    """Passport seeds (TDPLAN-0017) add one optional field to LIVE passports:
    ``citizenship.seed = {"version", "sha256"}``, written by spawn's mint so a
    later update can tell "changed by the agent" from "changed by the shipped
    seed" -- dpkg's MD5 pattern. Schema stays 2.0.0; the field is additive and
    canonical.

    MEASURED BEFORE WRITING, the marker-7 way: nothing here flags it, and not
    because citizenship happens to be spelled outside a closed set -- there is
    no rule over passport CONTENT at all. The closed set ruling 4 executes over
    ``document_metadata`` in local.json and observations.json; the passport is
    reached only as a NAME in ``_CANONICAL_FILES``, counted present or missing
    by the File set group, never opened. So nothing was changed for this lane.

    These three pin the tolerance and its cause separately, because they can be
    lost separately: someone adding a real passport-content rule later would
    keep the docstring true and still break the stamp, and someone deleting the
    contract sentence would leave the behaviour undefended.
    """

    _SEED_STAMP = {"version": "1.0.0", "sha256": "0" * 64}

    @staticmethod
    def _write_passport(branch: Path, *, stamp: bool) -> None:
        """Replace the fixture's placeholder passport with a real 2.0 one.

        ``_write_branch`` writes ``{}`` because existence is all trinity has
        ever asked of this file -- these tests need the live shape to make the
        comparison mean something.
        """
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
        """Not just "still 100" -- the whole result, group by group, identical.
        A future rule that scored the stamp anywhere would move one subscore and
        this comparison would see it even if the weighted mean rounded back.
        """
        plain_branch = _write_branch(tmp_path / "plain")
        self._write_passport(plain_branch, stamp=False)
        stamped_branch = _write_branch(tmp_path / "stamped")
        self._write_passport(stamped_branch, stamp=True)

        plain = trinity.check_branch(str(plain_branch))
        stamped = trinity.check_branch(str(stamped_branch))

        assert stamped == plain
        assert stamped["score"] == 100, stamped["checks"]

    def test_the_tolerance_is_structural_the_passport_is_never_opened(self, trinity, tmp_path):
        """WHY the stamp is free: not JSON this checker parses. A passport that
        is not even valid JSON still scores 100, because the File set group asks
        the directory for the name and stops there. Pinning the cause means a
        future reader can tell an intended tolerance from a lucky one.
        """
        branch = _write_branch(tmp_path)
        _write_doc(branch / ".trinity" / "passport.json", "not json at all {{")

        result = trinity.check_branch(str(branch))

        assert result["score"] == 100
        assert _group(result, "File set")["passed"] is True

    def test_the_contract_still_says_passports_are_existence_only(self, trinity):
        """The sentence that makes the tolerance deliberate. If a passport rule
        is ever added here, this fails first and whoever adds it has to decide
        about the stamp on purpose.
        """
        assert "EXISTENCE only" in trinity.__doc__
        assert "nothing inside a passport is read or judged" in trinity.__doc__
