# =================== AIPass ====================
# Name: test_pytest_quality_pack_posix_literal.py
# Description: pytest_quality pack, posix_literal checker pins (split from test_pytest_quality_pack.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/posix_literal_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, pytest_quality_standards/posix_literal_content.py

from pathlib import Path

from aipass.seedgo.apps.handlers.pytest_quality_standards import posix_literal_check
from aipass.seedgo.tests.support_pytest_quality_pack import _write


# Every project here is source text in tmp_path: no `os.sep`, `os.name` or host resolve, so the pins judge the checker and not this interpreter.


def _posix_project(root: Path) -> Path:
    """A six-unit project where exactly two units resolve a rooted literal."""
    _write(
        root,
        "tests/test_roots.py",
        """
        def test_a_constructed_root_is_resolved():
            assert Path("/srv/data").resolve() in roster

        def test_a_module_resolver_is_handed_a_root():
            assert os.path.realpath("/etc/hosts").startswith("/etc")

        def test_a_branch_name_resolver_shares_the_verb(registry):
            assert registry.resolve("/canary", {}) is None

        def test_a_relative_fragment_carries_no_claim():
            assert Path("logs").resolve().name == "logs"

        def test_a_helper_owns_its_own_abspath(helper):
            assert helper.abspath("/etc") is None

        def test_a_derived_path_was_never_written_down(tmp_path):
            assert tmp_path.resolve().is_dir()
        """,
    )
    return root


class TestPosixLiteralDetection:
    """POSIX-LITERAL: which literals reach a resolver, and which look like they do."""

    def test_a_path_constructor_over_a_rooted_literal_is_flagged(self, tmp_path):
        """The subject of the rule: a root written down and then resolved."""
        _write(
            tmp_path,
            "tests/test_roster.py",
            """
            def test_the_root_is_in_the_roster():
                assert Path("/srv/data").resolve() in roster
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert [row["literal"] for row in result["violations"]] == ["/srv/data"]
        assert result["violations"][0]["species"] == "POSIX-LITERAL"
        assert result["violations"][0]["nodeid"] == "tests/test_roster.py::test_the_root_is_in_the_roster"

    def test_a_branch_name_resolver_sharing_the_verb_is_not_flagged(self, tmp_path):
        """THE ACQUITTAL THAT DECIDED THE SHAPE - keyed on receiver, not name."""
        _write(
            tmp_path,
            "tests/test_registry.py",
            """
            def test_the_branch_name_resolves(registry):
                assert registry.resolve("/canary", {"root": "/srv"}) is None
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_relative_literal_carries_no_platform_claim(self, tmp_path):
        """A relative fragment means the same thing in both dialects."""
        _write(
            tmp_path,
            "tests/test_relative.py",
            """
            def test_a_relative_fragment_resolves():
                assert Path("logs").resolve().name == "logs"
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["violations"] == []

    def test_a_drive_rooted_literal_is_flagged_in_both_spellings(self, tmp_path):
        """The drive arm is the other half of the same defect, mirrored."""
        _write(
            tmp_path,
            "tests/test_drive.py",
            r"""
            def test_a_backslash_drive_resolves():
                assert PureWindowsPath(r"C:\tmp").resolve()

            def test_a_forward_slash_drive_resolves():
                assert PureWindowsPath("D:/tmp").resolve()
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert sorted(row["literal"] for row in result["violations"]) == ["C:\\tmp", "D:/tmp"]

    def test_a_resolver_function_over_a_rooted_literal_is_flagged(self, tmp_path):
        """The second arm: `os.path.realpath("/etc")` normalises against the host."""
        _write(
            tmp_path,
            "tests/test_resolvers.py",
            """
            def test_realpath_normalises():
                assert os.path.realpath("/etc/hosts").startswith("/etc")

            def test_abspath_normalises():
                assert os.path.abspath("/etc") == "/etc"
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert sorted(row["literal"] for row in result["violations"]) == ["/etc", "/etc/hosts"]

    def test_a_resolver_name_on_something_that_is_not_a_path_module_is_not_flagged(self, tmp_path):
        """`helper.abspath(...)` is somebody else's method that shares a name."""
        _write(
            tmp_path,
            "tests/test_helper.py",
            """
            def test_the_helper_makes_it_absolute(helper):
                assert helper.abspath("/etc") is None
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["violations"] == []

    def test_a_module_that_names_its_dialect_out_loud_is_not_flagged(self, tmp_path):
        """`ntpath.abspath("/x")` is the CURE this rule sends people to."""
        _write(
            tmp_path,
            "tests/test_dialects.py",
            """
            def test_the_two_dialects_disagree():
                assert ntpath.abspath("D:/x/../tmp") == "D:\\tmp"
                assert posixpath.realpath("/x/../tmp") == "/tmp"
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_the_dialect_acquittal_does_not_reach_os_path(self, tmp_path):
        """Negative control, and the reason the acquittal above is not a hole."""
        _write(
            tmp_path,
            "tests/test_both.py",
            """
            def test_the_alias_is_still_read():
                assert os.path.abspath("/etc") == "/etc"

            def test_the_dialect_is_not():
                assert posixpath.abspath("/etc") == "/etc"
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert [row["nodeid"] for row in result["violations"]] == ["tests/test_both.py::test_the_alias_is_still_read"]

    def test_a_constructor_called_with_no_arguments_is_read_without_crashing(self, tmp_path):
        """`Path().resolve()` is legal Python and the reader must survive it."""
        _write(
            tmp_path,
            "tests/test_cwd.py",
            """
            def test_the_working_directory_resolves():
                assert Path().resolve().is_dir()
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_the_line_reported_is_the_resolving_call_and_not_the_unit(self, tmp_path):
        """A reader gets sent to the line to look at, not to the def above it."""
        _write(
            tmp_path,
            "tests/test_deep.py",
            """
            def test_the_root_is_reached_late():
                roster = build_roster()
                extra = decorate(roster)
                assert Path("/srv/data").resolve() in extra
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert [row["line"] for row in result["violations"]] == [4]

    def test_a_rooted_literal_resolved_outside_a_test_unit_is_not_counted(self, tmp_path):
        """The rule walks TEST UNITS, and the denominator has to agree with it."""
        _write(
            tmp_path,
            "tests/test_module_level.py",
            """
            ROOT = Path("/srv/data").resolve()

            @pytest.fixture
            def roster():
                return os.path.realpath("/etc")

            def test_the_roster_is_built(roster):
                assert roster
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100


class TestPosixLiteralScoring:
    """The number, and the one arithmetic mistake that would make it a lie."""

    def test_the_score_counts_units_and_not_findings(self, tmp_path):
        """A unit resolving three roots is ONE unit a reader has to go and read."""
        _write(
            tmp_path,
            "tests/test_many.py",
            """
            def test_three_roots_in_one_unit():
                assert Path("/srv/data").resolve()
                assert Path("/var").resolve()
                assert os.path.abspath("/etc")

            def test_one_clean_unit():
                assert Path("logs").resolve()
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert len(result["violations"]) == 3
        assert result["score"] == 50

    def test_a_project_with_four_kinds_of_clean_unit_scores_them_all_clean(self, tmp_path):
        """The constructed negative control: four acquittals, four reasons."""
        _posix_project(tmp_path)

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["score"] == 66
        assert len(result["violations"]) == 2
        assert "2/6 test units put a rooted path literal through a resolver" in result["checks"][0]["message"]


class TestPosixLiteralBranchCheck:
    """The scoring-API contract, and the two paths where silence reads as clean."""

    def test_the_result_carries_the_scoring_api_shape(self, tmp_path):
        """The pack is advisory in shadow mode and every result has to say so."""
        _posix_project(tmp_path)

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "POSIX_LITERAL"
        assert result["checks"][0]["passed"] is False

    def test_a_project_with_no_test_files_is_not_applicable(self, tmp_path):
        """Zero tests measured is not zero quality found."""
        _write(tmp_path, "src/thing.py", "def thing():\n    return 1")

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A broken file must never read as an absent one - the ordering pin."""
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_broken.py" in check["message"] for check in result["checks"])

    def test_an_unparseable_file_is_named_beside_a_scored_result(self, tmp_path):
        """The unreadable line must also survive onto the path that DOES score."""
        _posix_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = posix_literal_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["score"] == 66
        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]


class TestPosixLiteralRenderedAndReturnedPaths:
    """Arms 3 and 4 - the REVERSE shape, and the split that keeps arm 3 honest."""

    def test_a_path_the_test_rendered_itself_is_scored(self, tmp_path):
        """RENDERED-PATH: the TEST chose the dialect, on the line under the reader's eye."""
        _write(
            tmp_path,
            "tests/test_scanner.py",
            """
            def test_the_relative_path_is_reported(tmp_path):
                entry = collect(tmp_path)
                assert str(entry.path) == "pkg/gamma.py"
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))
        row = result["violations"][0]

        assert [r["species"] for r in result["violations"]] == ["RENDERED-PATH"]
        assert result["nominations"] == []
        assert result["score"] == 0
        assert row["literal"] == "pkg/gamma.py"
        assert row["rendering"] == "str()"
        assert "only right on the leg of the matrix it was written on" in row["reason"]

    def test_an_f_string_is_the_same_rendering_spelled_shorter(self, tmp_path):
        """An f-string calls `__format__`, which for a Path is the host's dialect."""
        _write(
            tmp_path,
            "tests/test_scanner.py",
            """
            def test_the_relative_path_is_reported(tmp_path):
                entry = collect(tmp_path)
                assert f"{entry.path}" == "pkg/gamma.py"
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert [r["species"] for r in result["violations"]] == ["RENDERED-PATH"]
        assert result["violations"][0]["rendering"] == "f-string"
        assert result["score"] == 0

    def test_a_path_searched_for_inside_a_rendered_call_record_is_scored(self, tmp_path):
        """REPR-HAYSTACK: the haystack is not the argument, it is a rendering of it."""
        _write(
            tmp_path,
            "tests/test_log_watcher.py",
            """
            def test_the_log_path_is_warned_about(logs_dir):
                with patch("apps.watcher.logger.warning") as warned:
                    run_it()
                assert str(logs_dir / "app.log") in str(warned.call_args)
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))
        row = result["violations"][0]

        assert [r["species"] for r in result["violations"]] == ["REPR-HAYSTACK"]
        assert result["score"] == 0
        assert row["record"] == "warned.call_args"
        assert "DOUBLES a backslash separator" in row["reason"]
        assert "warned.call_args.args[n]" in row["reason"]

    def test_a_rendered_record_is_followed_one_hop_through_a_local_name(self, tmp_path):
        """ONE HOP, FIRST BINDING ONLY - and it is the shape every fleet site uses."""
        _write(
            tmp_path,
            "tests/test_log_watcher.py",
            """
            def test_the_log_path_is_warned_about(logs_dir):
                with patch("apps.watcher.logger.warning") as warned:
                    run_it()
                reported = str(warned.call_args)
                assert str(logs_dir / "app.log") in reported
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert [r["species"] for r in result["violations"]] == ["REPR-HAYSTACK"]
        assert result["violations"][0]["record"] == "warned.call_args"

    def test_a_join_over_a_rendered_call_list_is_the_same_haystack(self, tmp_path):
        """A rendering inside a join is still a rendering - Windows CI red 34882199024."""
        _write(
            tmp_path,
            "tests/test_host_api.py",
            """
            def test_the_log_path_is_printed(console, logs_dir):
                run_it()
                printed = " ".join(str(call) for call in console.print.call_args_list)
                assert str(logs_dir / "app.log") in printed
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))
        row = result["violations"][0]

        assert [r["species"] for r in result["violations"]] == ["REPR-HAYSTACK"]
        assert result["score"] == 0
        assert row["record"] == "console.print.call_args_list"
        assert "console.print.call_args_list[i].args[n]" in row["reason"]

    def test_a_needle_bound_to_a_path_one_hop_back_is_read_as_a_path(self, tmp_path):
        """`str(bundle)` names no path; `bundle = _face_bundle(tmp_path / "face")` does."""
        _write(
            tmp_path,
            "tests/test_host_api.py",
            """
            def test_the_face_dir_is_shown(warned, tmp_path):
                bundle = _face_bundle(tmp_path / "face")
                run_it(bundle)
                assert str(bundle) in str(warned.call_args)
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert [r["species"] for r in result["violations"]] == ["REPR-HAYSTACK"]
        assert result["violations"][0]["literal"] == "str(bundle)"

    def test_a_needle_from_a_call_named_for_a_path_is_read_as_a_path(self, tmp_path):
        """`str(host_face.face_root())` - the call's own name is the evidence."""
        _write(
            tmp_path,
            "tests/test_host_api.py",
            """
            def test_the_checkout_default_is_named(warned):
                run_it()
                assert str(host_face.face_root()) in str(warned.call_args)
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert [r["species"] for r in result["violations"]] == ["REPR-HAYSTACK"]
        assert result["violations"][0]["literal"] == "str(host_face.face_root())"

    def test_joining_the_arguments_instead_of_the_calls_is_clean(self, tmp_path):
        """The cure api landed: the haystack is built from `call.args`, not from calls."""
        _write(
            tmp_path,
            "tests/test_host_api.py",
            """
            def test_the_face_dir_is_shown(console, tmp_path):
                bundle = _face_bundle(tmp_path / "face")
                run_it(bundle)
                printed = " ".join(str(arg) for call in console.print.call_args_list for arg in call.args)
                assert str(bundle) in printed
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_join_over_calls_searched_for_text_that_is_not_a_path_is_clean(self, tmp_path):
        """The widened haystack reads 112 fleet comparisons; the needle keeps them clean."""
        _write(
            tmp_path,
            "tests/test_cli_routing.py",
            """
            def test_the_help_names_its_verbs(console, report):
                run_it()
                verb = "get-key"
                printed = " ".join(str(call) for call in console.print.call_args_list)
                assert verb in printed
                assert "10 of 25" in printed
                for step in report["steps"]:
                    assert step in printed
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_value_the_code_under_test_returned_nominates_and_moves_no_number(self, tmp_path):
        """RETURNED-PATH: reported in its own line, `passed: True`, never scored."""
        _write(
            tmp_path,
            "tests/test_scanner.py",
            """
            def test_the_relative_path_is_reported(tmp_path):
                result = collect(tmp_path)
                assert result["relative_path"] == "pkg/gamma.py"
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))
        line = result["checks"][1]
        row = result["nominations"][0]

        assert result["violations"] == []
        assert result["score"] == 100
        assert result["checks"][0]["passed"] is True
        assert line["name"] == "Path provenance nominations"
        assert line["passed"] is True
        assert "reported only - not scored, not counted as failing" in line["message"]
        assert row["species"] == "RETURNED-PATH"
        assert row["rendering"] == "subscript"
        assert "NOMINATION ONLY, not scored" in row["reason"]

    def test_a_nomination_does_not_move_a_number_a_scored_row_already_set(self, tmp_path):
        """THE SPLIT, PINNED AS ARITHMETIC: same denominator, same answer."""
        rendered_unit = (
            "def test_the_relative_path_is_rendered(tmp_path):\n"
            "    entry = collect(tmp_path)\n"
            '    assert str(entry.path) == "pkg/gamma.py"\n'
        )
        clean_unit = 'def test_a_clean_unit(tmp_path):\n    assert (tmp_path / "a").parent == tmp_path\n'
        returned_unit = (
            "def test_the_relative_path_is_returned(tmp_path):\n"
            "    result = collect(tmp_path)\n"
            '    assert result["relative_path"] == "pkg/gamma.py"\n'
        )
        _write(tmp_path / "clean", "tests/test_scanner.py", rendered_unit + "\n\n" + clean_unit)
        _write(tmp_path / "nominating", "tests/test_scanner.py", rendered_unit + "\n\n" + returned_unit)

        clean = posix_literal_check.check_branch(str(tmp_path / "clean"))
        nominating = posix_literal_check.check_branch(str(tmp_path / "nominating"))

        assert clean["score"] == 50
        assert nominating["score"] == 50
        assert len(nominating["nominations"]) == 1
        assert len(nominating["violations"]) == len(clean["violations"]) == 1

    def test_a_pack_assertion_on_a_corpus_rendered_relpath_is_never_scored(self, tmp_path):
        """THE 27-ROW FALSE-POSITIVE FAMILY, AND IT IS THIS FILE'S OWN TESTS."""
        _write(
            tmp_path,
            "tests/test_pack_shapes.py",
            """
            def test_the_unreadable_file_is_named(tmp_path):
                result = check_branch(str(tmp_path))
                named = [c for c in result["checks"] if c["name"] == "Corpus readable"]
                assert "tests/test_broken.py" in named[0]["message"]
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["score"] == 100
        assert result["violations"] == []
        assert [r["species"] for r in result["nominations"]] == ["RETURNED-PATH"]
        assert result["nominations"][0]["literal"] == "tests/test_broken.py"

    def test_as_posix_inside_the_comparison_acquits_the_whole_site(self, tmp_path):
        """`.as_posix()` says "posix on purpose", and it is the cure this arm teaches."""
        _write(
            tmp_path,
            "tests/test_scanner.py",
            """
            def test_the_relative_path_is_reported(tmp_path):
                entry = collect(tmp_path)
                assert entry.path.as_posix() == "pkg/gamma.py"
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["nominations"] == []
        assert result["score"] == 100

    def test_a_returned_value_in_a_unit_that_never_touches_a_path_is_not_read(self, tmp_path):
        """THE WEAKEST EVIDENCE THIS RULE USES, AND IT IS USED ON PURPOSE."""
        _write(
            tmp_path,
            "tests/test_payloads.py",
            """
            def test_the_payload_body_is_echoed():
                assert payload["body"] == "a/b.txt"
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["nominations"] == []
        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_rooted_literal_belongs_to_arms_one_and_two_and_not_to_arm_three(self, tmp_path):
        """497 of the 501 rooted literals measured fleet-wide are DATA."""
        _write(
            tmp_path,
            "tests/test_scanner.py",
            """
            def test_the_absolute_path_is_reported(tmp_path):
                entry = collect(tmp_path)
                assert str(entry.path) == "/srv/pkg/gamma.py"
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["nominations"] == []
        assert result["score"] == 100

    def test_the_check_line_widens_when_a_rendering_row_is_in_the_list(self, tmp_path):
        """THE SENTENCE FOLLOWS THE SPECIES, or it describes a finding that is not there."""
        _write(
            tmp_path / "mixed",
            "tests/test_mixed.py",
            """
            def test_a_constructed_root_is_resolved():
                assert Path("/srv/data").resolve() in roster


            def test_the_relative_path_is_reported(tmp_path):
                entry = collect(tmp_path)
                assert str(entry.path) == "pkg/gamma.py"
            """,
        )
        _write(
            tmp_path / "resolver_only",
            "tests/test_roots.py",
            """
            def test_a_constructed_root_is_resolved():
                assert Path("/srv/data").resolve() in roster
            """,
        )

        mixed = posix_literal_check.check_branch(str(tmp_path / "mixed"))
        alone = posix_literal_check.check_branch(str(tmp_path / "resolver_only"))

        assert "2/2 test units spell a path in one platform's dialect" in mixed["checks"][0]["message"]
        assert "1/1 test units put a rooted path literal through a resolver" in alone["checks"][0]["message"]
