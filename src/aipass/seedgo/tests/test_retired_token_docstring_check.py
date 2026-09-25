# =================== META ====================
# Name: test_retired_token_docstring_check.py
# Description: retired_token_docstring_check — the retired v4 auditor's keywords left in test docstrings
# Version: 1.1.0
# Created: 2026-09-25
# Modified: 2026-09-25
# =============================================

"""Tests for apps/handlers/aipass_standards/retired_token_docstring_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import retired_token_docstring_check as checker

#: The model file for the whole per-item series.
MODEL = Path(__file__).resolve().parent / "test_readme_update.py"

#: @backup's test docstrings at commit 7cbe39e5: (text, shape, terms the finding names).
SPECIMENS = [
    ("Test unknown_command / invalid_command / unrecognized handling.", "T2", "unknown_command, invalid_command"),
    ("unknown_command / invalid_command returns False -- unrecognized.", "T2", "unknown_command, invalid_command"),
    ("Test output capture -- capsys, capfd, StringIO tokens.", "T1+T2", "capsys, capfd, StringIO"),
    ("StringIO can capture output -- output_capture token.", "T1", "output_capture"),
    ("Test directory walking -- creates_files, .exists() tokens.", "T1+T2", "creates_files, .exists()"),
    (
        "Test project setup -- creates_files, .exists(), mkdir, makedirs tokens.",
        "T1+T2",
        "creates_files, .exists(), mkdir, makedirs",
    ),
    ("create_backup_dir creates .backup/ -- mkdir, .exists().", "T2", "mkdir, .exists()"),
    ("Second call doesn't fail -- no_overwrite, already_exists.", "T2", "no_overwrite, already_exists"),
    (
        "Test config loading -- returns_dict, isinstance(result, dict), json_type tokens.",
        "T1+T2",
        "returns_dict, isinstance(result, dict), json_type",
    ),
]

#: @api's tests/test_init_provisioning.py module docstring, verbatim: returns_dict is a 7cd59aa4^ item.
API_PROVISIONING = """
Init/Provisioning Tests for API branch.

Covers 4 tests:
  - creates_files, auto_creates_dir, no_overwrite, returns_dict
"""

#: @seedgo's tests/test_json_handler_contract.py, verbatim: a real signature quoted as code.
QUOTED_SIGNATURE = """Skip branches whose handler addresses documents by filesystem path.

    Two calling conventions exist in the fleet. Sixteen-plus branches take
    ``(module_name, json_type)`` and resolve the path themselves; ``backup``
    takes a path and owns none of that resolution.
    """


def _planted(tmp_path, *docstrings, body="    pass\n"):
    """A test file whose functions carry the given docstrings, one function each."""
    source = '"""Tests for a planted module."""\n'
    for number, text in enumerate(docstrings):
        source += f'\n\ndef test_case_{number}():\n    """{text}"""\n{body}'
    path = tmp_path / "test_specimen.py"
    path.write_text(source, encoding="utf-8")
    return path


def _verdict(path):
    """(score, the one check's message) for a planted file."""
    result = checker.check_module(str(path))
    return result["score"], result["checks"][0]["message"]


class TestTheModelFilePasses:
    """The template's own model is the floor: if it fails, the rule is wrong."""

    def test_the_model_file_scores_100(self):
        assert checker.check_module(str(MODEL))["score"] == 100


class TestThePlantedSpecimens:
    @pytest.mark.parametrize(("text", "shape", "terms"), SPECIMENS)
    def test_each_backup_specimen_is_convicted_with_its_shape_and_terms(self, tmp_path, text, shape, terms):
        score, message = _verdict(_planted(tmp_path, text))
        assert score == 0
        assert f"test_specimen.py:5 docstring carries v4 cargo [{shape}] {terms} - " in message
        assert message.endswith("drop the retired v4 keywords; say what the test proves")

    def test_a_list_that_is_not_v4_vocabulary_passes(self, tmp_path):
        path = _planted(tmp_path, "Test filtering -- patterns, whitelist.")
        assert _verdict(path) == (100, "No docstring carries the retired v4 keywords")


class TestWhatIsNeverConvicted:
    def test_plain_english_v4_patterns_are_prose(self, tmp_path):
        path = _planted(tmp_path, "The fixture must yield a corrupt, malformed or nonexistent file, then teardown.")
        assert _verdict(path)[0] == 100

    def test_the_word_tokens_without_a_v4_term_passes(self, tmp_path):
        path = _planted(tmp_path, "Revoked tokens are refused and fresh tokens accepted.")
        assert _verdict(path)[0] == 100

    def test_a_token_that_is_not_labelling_the_terms_passes(self, tmp_path):
        path = _planted(tmp_path, "A stray token before --help must not turn help into a live fire.")
        assert _verdict(path)[0] == 100

    def test_bait_in_a_comment_or_a_plain_string_passes(self, tmp_path):
        body = '    # capsys, capfd, StringIO tokens\n    label = "no_overwrite, already_exists"\n    assert label\n'
        path = _planted(tmp_path, "Checks the label.", body=body)
        assert _verdict(path)[0] == 100

    def test_the_fleet_cli_contract_functions_alone_do_not_make_a_list(self, tmp_path):
        path = _planted(tmp_path, "Tests for print_introspection and print_help.")
        assert _verdict(path)[0] == 100

    def test_cleanup_is_english_and_never_makes_a_bait_list(self, tmp_path):
        path = _planted(tmp_path, "Checks cleanup and rmtree ordering.")
        assert _verdict(path)[0] == 100

    def test_a_term_inside_a_longer_name_is_not_the_term(self, tmp_path):
        path = _planted(tmp_path, "Counts fake_capsys tokens and fake_capfd, fake_rmtree calls.")
        assert _verdict(path)[0] == 100

    def test_an_unparseable_file_is_left_to_ruff(self, tmp_path):
        path = tmp_path / "test_broken.py"
        path.write_text('def test_x(:\n    """capsys, capfd."""\n', encoding="utf-8")
        assert _verdict(path)[0] == 100


class TestWhereAndHowItReports:
    def test_contract_functions_still_lengthen_a_real_list(self, tmp_path):
        path = _planted(tmp_path, "Covers print_help, print_introspection, output_capture.")
        assert "[T2] print_help, print_introspection, output_capture - " in _verdict(path)[1]

    def test_module_and_class_docstrings_are_judged(self, tmp_path):
        source = '"""Covers missing_file, empty_file."""\n\n\nclass TestX:\n    """no_args or no_overwrite."""\n'
        path = tmp_path / "test_specimen.py"
        path.write_text(source, encoding="utf-8")
        message = _verdict(path)[1]
        assert "test_specimen.py:1 docstring carries v4 cargo [T2] missing_file, empty_file - " in message
        assert "test_specimen.py:5 docstring carries v4 cargo [T2] no_args, no_overwrite - " in message

    def test_every_hit_lands_on_one_check_one_line_per_docstring(self, tmp_path):
        path = _planted(tmp_path, SPECIMENS[0][0], "Plain prose.", SPECIMENS[7][0])
        result = checker.check_module(str(path))
        assert len(result["checks"]) == 1
        assert [line.split(" docstring")[0] for line in result["checks"][0]["message"].splitlines()] == [
            "test_specimen.py:5",
            "test_specimen.py:15",
        ]

    def test_a_missing_file_scores_zero(self, tmp_path):
        assert _verdict(tmp_path / "absent.py") == (0, f"File not found: {tmp_path / 'absent.py'}")


class TestTheVocabulary:
    def test_it_is_the_seven_categories_and_twenty_eight_items_of_v4(self):
        assert len(checker.V4_CATEGORIES) == 7
        assert sum(len(items) for items in checker.V4_CATEGORIES.values()) == 28
        assert checker.V4_CATEGORIES["cli_routing"]["output_capture"] == ("capsys", "capfd", "StringIO")

    @pytest.mark.parametrize(
        "term", ["StringIO", "FileNotFoundError", ".exists()", "pathlib.Path", "--help", "mkdir", "no_overwrite"]
    )
    def test_code_shaped_terms(self, term):
        assert checker.is_code_shaped(term)

    @pytest.mark.parametrize("term", ["yield", "corrupt", "overwrite", "is True", "autouse=True", "cleanup", "'help'"])
    def test_english_terms_are_not_code_shaped(self, term):
        assert not checker.is_code_shaped(term)


class TestTheItemsOnlyTheOlderAuditorCarried:
    """7cd59aa4^'s STANDARD_CATEGORIES held 20 items c1e0eeed^ no longer had; their bait is convicted too."""

    def test_the_api_provisioning_module_docstring_names_returns_dict(self, tmp_path):
        path = tmp_path / "test_specimen.py"
        path.write_text(f'"""{API_PROVISIONING}"""\n', encoding="utf-8")
        assert "[T2] creates_files, auto_creates_dir, no_overwrite, returns_dict - " in _verdict(path)[1]

    def test_the_older_exception_contract_terms_make_a_list(self, tmp_path):
        path = _planted(tmp_path, "Exception contracts: _create_default / ValueError for unknown types.")
        assert "[T2] _create_default, ValueError - " in _verdict(path)[1]

    def test_the_vocabulary_is_the_union_of_both_commits(self):
        assert len(checker.V4_VOCABULARY) == 10
        assert sum(len(items) for items in checker.V4_VOCABULARY.values()) == 48
        assert checker.V4_RETIRED_EARLIER["init_provisioning"]["returns_dict"] == (
            "isinstance(result, dict)",
            "json_type",
        )
        assert checker.V4_VOCABULARY["init_provisioning"]["no_overwrite"] == (
            "overwrite",
            "no_clobber",
            "already_exists",
        )
        assert checker.V4_VOCABULARY["infrastructure_mocking"]["reimport_after_mock"] == ("importlib.reload", "reload(")

    @pytest.mark.parametrize(
        "term", ["returns_dict", "json_type", "isinstance(result, dict)", "sys.modules", "save_json"]
    )
    def test_the_new_terms_count_for_a_bait_list(self, term):
        assert term in checker.T2_TERMS

    def test_the_plain_english_older_patterns_do_not(self):
        assert "operation" not in checker.T1_TERMS


class TestQuotedCodeAndEnglishNames:
    def test_a_signature_quoted_in_backticks_is_not_a_list(self, tmp_path):
        assert _verdict(_planted(tmp_path, QUOTED_SIGNATURE))[0] == 100

    def test_the_same_terms_unquoted_are_convicted(self, tmp_path):
        path = _planted(tmp_path, "Branches take module_name, json_type and resolve the path.")
        assert "[T2] module_name, json_type - " in _verdict(path)[1]

    def test_single_backticks_quote_code_as_double_ones_do(self, tmp_path):
        path = _planted(tmp_path, "Calls `save_json(module_name, json_type, data)` like the fleet does.")
        assert _verdict(path)[0] == 100

    def test_english_item_names_alone_are_not_a_token_label(self, tmp_path):
        path = _planted(tmp_path, "We validate tokens on login and save tokens on refresh.")
        assert _verdict(path)[0] == 100

    def test_an_english_name_beside_a_code_shaped_one_is(self, tmp_path):
        path = _planted(tmp_path, "Loading works -- load, load_json tokens.")
        assert "[T1] load, load_json - " in _verdict(path)[1]
