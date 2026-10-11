# =================== AIPass ====================
# Name: test_pytest_quality_pack_posix_literal.py
# Description: pytest_quality pack, posix_literal checker pins (split from test_pytest_quality_pack.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/posix_literal_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, pytest_quality_standards/posix_literal_content.py

from pathlib import Path

from aipass.seedgo.apps.handlers.pytest_quality_standards import posix_literal_check
from aipass.seedgo.tests.support_pytest_quality_pack import _write

# =============================================================================
# POSIX LITERAL - A ROOTED PATH LITERAL PUT THROUGH A RESOLVER
# =============================================================================

# NOTHING IN THIS SECTION ASKS THE MACHINE ANYTHING. The rule under test is about
# path separators, which makes it the one rule in the pack whose pins could most
# easily become a report on the host that ran them - an `os.sep` here, a
# `Path("/srv/data").resolve()` there, and the suite starts asserting what THIS
# interpreter does with a root instead of what the CHECKER says about a literal.
# Every project below is source TEXT written into tmp_path, and every assertion is
# about what the checker reported. No `os.name`, no `sys.platform`, no separator
# read from the running host, on any line.


def _posix_project(root: Path) -> Path:
    """A six-unit project where exactly two units resolve a rooted literal.

    The four clean units are clean for four DIFFERENT reasons - a resolver that
    is not pathlib's, a relative literal, a resolver name on something that is
    not a path module, and a derived path - so no single acquittal carries the
    whole 66.
    """
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
        """The subject of the rule: a root written down and then resolved.

        `Path("/srv/data").resolve()` is `/srv/data` on POSIX and a drive-relative
        `D:\\tmp` under ntpath. Losing this arm leaves the rule with nothing but
        the os.path spelling, which the measurement found four times fewer.
        """
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
        """THE ACQUITTAL THAT DECIDED THE SHAPE - keyed on receiver, not name.

        Six of the ten sites the name-keyed rule found fleet-wide were
        `target.resolve("@canary", {...})`: a branch-name lookup holding a rooted
        literal in an argument it never resolves. A rule that nominates those six
        forever is one a fleet learns to ignore inside a week.
        """
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
        """A relative fragment means the same thing in both dialects.

        `Path("logs")` is a name, not a root; resolving it is a claim about the
        working directory and about nothing else. Flagging it would put every
        `Path("x").resolve()` in the fleet into the report and bury the four
        sites that are actually about a root.
        """
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
        """The drive arm is the other half of the same defect, mirrored.

        A test that writes `C:\\tmp` has made the opposite platform assumption:
        posixpath reads it as a RELATIVE name, so the same line means something
        else on the other half of the matrix. Losing the drive arm leaves the
        rule catching only authors who guessed POSIX.
        """
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
        """The second arm: `os.path.realpath("/etc")` normalises against the host.

        Both spellings are named because they are one shape - `realpath` and
        `abspath` differ in symlink handling and not at all in the assumption
        they carry. Dropping either leaves half the arm live and the other half
        silently unmeasured.
        """
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
        """`helper.abspath(...)` is somebody else's method that shares a name.

        The module gate is the same idea as the receiver gate one arm over: the
        rule is about pathlib and os.path, and a name is not evidence of either.
        Without the gate every object in the fleet with an `abspath` method
        becomes a finding.
        """
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
        """`ntpath.abspath("/x")` is the CURE this rule sends people to.

        PACK DEFECT, found by the rule convicting its own hazard demonstration
        (seedgo, 2026-09-07). The premise in this checker's own docstring is that
        `os.path` MEANS a different module per host, so the line means two
        things. `ntpath` and `posixpath` are the opposite: the module names the
        dialect, the answer is fixed on every leg of the matrix, and a nominated
        site gets rewritten INTO this shape. Convicting it convicted the fix.

        Measured across 22 branches before the change: 5 rows fleet-wide, this
        acquits 2, and no other branch moves.
        """
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
        """Negative control, and the reason the acquittal above is not a hole.

        A gate spelled "any module ending in path" would take `os.path` with it
        and delete the whole second arm of the rule. Both spellings sit in one
        file so the two readings come from the same corpus in one pass: exactly
        the os.path line is convicted, and it is named.
        """
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
        """`Path().resolve()` is legal Python and the reader must survive it.

        A static reader that raises on a legal construct does not report a
        finding - it takes the whole branch's score down with it, and the caller
        sees a crash where a number should be. The argument guard is the only
        thing between this rule and an IndexError on a one-line test.
        """
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
        """A reader gets sent to the line to look at, not to the def above it.

        A unit can be forty lines long and hold one rooted literal. Reporting the
        unit's own line makes every finding in a long test point at the same
        place, and the reader has to search for the thing the rule already found.
        """
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
        """The rule walks TEST UNITS, and the denominator has to agree with it.

        A module-level constant and a fixture are not units, so a literal
        resolved in either has no unit to charge and no line a reader would be
        sent to. Widening the walk to the whole file finds them and then has to
        invent an owner - which is how a rule starts reporting findings that
        cannot be acted on.
        """
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
        """A unit resolving three roots is ONE unit a reader has to go and read.

        Counting findings instead of units lets a single loop-heavy test drive a
        two-unit project to -50, and a score that can go negative is one nobody
        believes twice. The violations list still carries all three, because the
        reader wants every line.
        """
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
        """The constructed negative control: four acquittals, four reasons.

        Two units of the six are the real thing. The other four are clean for
        four different reasons, so a mutation that collapses any single
        acquittal - the receiver gate, the rooted test, the module gate - moves
        this number and cannot hide behind the other three.
        """
        _posix_project(tmp_path)

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["score"] == 66
        assert len(result["violations"]) == 2
        assert "2/6 test units put a rooted path literal through a resolver" in result["checks"][0]["message"]


class TestPosixLiteralBranchCheck:
    """The scoring-API contract, and the two paths where silence reads as clean."""

    def test_the_result_carries_the_scoring_api_shape(self, tmp_path):
        """The pack is advisory in shadow mode and every result has to say so.

        A caller reading `passed` gates on it. A standard that starts failing
        boards it has never been measured against is the mistake this pack was
        built to correct, so `passed` is True and `advisory` is True even on a
        project this rule has findings about.
        """
        _posix_project(tmp_path)

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "POSIX_LITERAL"
        assert result["checks"][0]["passed"] is False

    def test_a_project_with_no_test_files_is_not_applicable(self, tmp_path):
        """Zero tests measured is not zero quality found.

        A 0 blames a project for a fact about its layout and a 100 claims a
        measurement that never happened. Losing the early return does not return
        a wrong number either - it divides by zero and takes the caller with it.
        """
        _write(tmp_path, "src/thing.py", "def thing():\n    return 1")

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A broken file must never read as an absent one - the ordering pin.

        An unparseable file contributes no units, so it cannot lower a score, and
        silence about it reads as a clean result. This is the one path where
        nothing else can catch it: the message a caller sees must say the file
        was present and unreadable, not that the project has no tests.
        """
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_broken.py" in check["message"] for check in result["checks"])

    def test_an_unparseable_file_is_named_beside_a_scored_result(self, tmp_path):
        """The unreadable line must also survive onto the path that DOES score.

        The early-return path carries it by construction; the scored path has to
        append it deliberately, and dropping that one line leaves a branch with a
        healthy number and no hint that a file was never read at all.
        """
        _posix_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = posix_literal_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["score"] == 66
        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]


class TestPosixLiteralRenderedAndReturnedPaths:
    """Arms 3 and 4 - the REVERSE shape, and the split that keeps arm 3 honest.

    Arms 1 and 2 are about a rooted literal put through a resolver. These two are
    the mirror image: a Path rendered to TEXT and compared with a literal that
    spells the separator forward. Four rows went red on the first Linux/Windows
    matrix run and not one of them held a rooted literal or a resolver.

    THE SPLIT IS THE HEART OF ARM 3, and it is measured rather than argued. The
    first fleet run of the undivided arm returned 64 rows, 27 of them on this
    branch, and most of this branch's are correct portable code: `corpus._relpath`
    (corpus.py:202) returns `path.relative_to(root).as_posix()`, so every test
    asserting on a relpath it produced is reading a string that is posix on every
    host, forever, on purpose. That fact is off-screen from any AST reader of the
    TEST - which is why a value the code under test RETURNED only nominates, while
    a rendering the test wrote down on the line the reader is looking at scores.

    Each test names the one-line mutation of `posix_literal_check` it was confirmed
    RED against.
    """

    def test_a_path_the_test_rendered_itself_is_scored(self, tmp_path):
        """RENDERED-PATH: the TEST chose the dialect, on the line under the reader's eye.

        `str()` of a Path spells the separator the HOST's way - `pkg/gamma.py`
        here, `pkg\\gamma.py` there - so nothing off-screen can make this literal
        right and the row moves the number. This half found ZERO rows fleet-wide,
        which the dossier says out loud rather than hiding: nobody here writes
        `str(p) == "a/b.py"` in a test yet. It is kept because it is the shape the
        cure turns INTO if the cure is done wrong. Mutation caught:
        `RENDER_BUILTINS: frozenset = frozenset({"str", "repr", "format",
        "ascii"})` becoming the same set without `"str"`.
        """
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
        """An f-string calls `__format__`, which for a Path is the host's dialect.

        `f"{p}"` and `str(p)` produce the same string and the same defect, and a
        rule that read only the builtin would teach the fleet to spell the bug in
        the shorter form. The species has to stay RENDERED-PATH - the test still
        wrote the rendering down. Mutation caught: `return "f-string" if
        pathish_expression(node) else ""` in `_written_rendering` becoming
        `return ""`, which drops the f-string half of the scoring arm and leaves
        `str()` looking healthy.
        """
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
        """REPR-HAYSTACK: the haystack is not the argument, it is a rendering of it.

        `str(mock.call_args)` runs every argument through `repr()`, and `repr()`
        of a Windows path DOUBLES the separator - so even a needle built
        correctly, `str(logs_dir / "app.log")`, cannot be found in there. Both
        scored rows the first fleet run produced were this species. Mutation
        caught: `MOCK_CALL_RECORDS: frozenset = frozenset({"call_args",
        "call_args_list", "mock_calls", "await_args", "await_args_list",
        "method_calls"})` becoming the same set without `"call_args"`.
        """
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
        """ONE HOP, FIRST BINDING ONLY - and it is the shape every fleet site uses.

        `reported = str(warned.call_args)` on one line and the assertion on the
        next is how all four of the CI rows are written; a reader that only saw
        the rendering inside the comparison would call every one of them clean.
        Following further would mean tracking flow, and a name rebound later
        keeps its first reading, which is the direction that under-reports.
        Mutation caught: `if isinstance(node, ast.Name) and node.id in bindings:
        return _renders_a_call_record(bindings[node.id])` in `_rendered_record`
        becoming `return ""`.
        """
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
        """A rendering inside a join is still a rendering - Windows CI red 34882199024.

        `" ".join(str(call) for call in m.call_args_list)` puts every call through
        `repr()` one at a time, which doubles a backslash exactly as
        `str(m.call_args)` does. Until 2026-09-14 the arm asked only the outermost
        expression, saw a join, and read both red rows clean. The cure names an
        index, because the list itself has no `.args`. Mutations caught: `for
        render in ast.walk(node)` in `_renders_a_call_record` becoming `for render
        in [node]`; `_iterated_records` returning `{}`; `index = "[i]" if ... else
        ""` in `_haystack_finding` becoming `index = ""`.
        """
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
        """`str(bundle)` names no path; `bundle = _face_bundle(tmp_path / "face")` does.

        The first red row's needle. The haystack already got one hop through a
        local name and the needle got none, so a path held in a variable called
        `bundle` read as not-a-path. Mutation caught: `return node.id in bindings
        and pathish_expression(bindings[node.id])` in `_names_a_path` becoming
        `return False`.
        """
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
        """`str(host_face.face_root())` - the call's own name is the evidence.

        The second red row's needle: nothing in `host_face.face_root()` is a Path
        constructor, a join or a fixture, and the old reading never read a call's
        name. Mutation caught: `return _is_pathish_name(...)` in `_names_a_path`
        becoming `return False`.
        """
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
        """The cure api landed: the haystack is built from `call.args`, not from calls.

        `str(arg)` of a Path argument spells ONE backslash on Windows, so a needle
        built with `str()` is found in it. A rule that convicted this would
        convict the fix. Mutation caught: the `sub.iter` test in
        `_iterated_records` becoming `True`, which binds every comprehension
        variable whatever it iterates.
        """
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
        """The widened haystack reads 112 fleet comparisons; the needle keeps them clean.

        api's own list of the join shape searches for a verb, a count and a loop
        variable over plain strings - text no host spells differently, which
        `repr()` leaves alone. A local bound to a plain string is not a path
        either. Mutations caught: `_pathish_needle` returning `True`; the Name
        branch of `_names_a_path` dropping `pathish_expression(bindings[node.id])`.
        """
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
        """RETURNED-PATH: reported in its own line, `passed: True`, never scored.

        The comparison came BACK from the code under test - a dict subscript -
        and whether the producer normalised the separator is off-screen. This is
        the SAME AST SHAPE as the rows that broke CI; what separates them lives
        in production, which this pack does not read for this rule. Sixty-eight
        of the 70 fleet rows are this species, so letting it score would have
        dropped eight branches' numbers over code that is mostly right. Mutation
        caught: `SCORING_SPECIES: tuple = (SPECIES_POSIX_LITERAL,
        SPECIES_RENDERED_PATH, SPECIES_REPR_HAYSTACK)` becoming the same tuple
        with `SPECIES_RETURNED_PATH` appended.
        """
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
        """THE SPLIT, PINNED AS ARITHMETIC: same denominator, same answer.

        Two two-unit projects with the SAME single RENDERED-PATH row. The
        second's other unit is a RETURNED-PATH nomination instead of a clean
        unit, and the score has to be identical - 50 both times - or the
        nomination is a penalty wearing a report's name. Mutation caught: `scored
        = [row for row in rows if row["species"] in SCORING_SPECIES]` in
        `split_rows` becoming `scored = list(rows)`, which reports 0 for the
        second project.
        """
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
        """THE 27-ROW FALSE-POSITIVE FAMILY, AND IT IS THIS FILE'S OWN TESTS.

        `corpus._relpath` (corpus.py:202) returns
        `path.relative_to(root).as_posix()`. Every nodeid and every relpath this
        pack reports is therefore POSIX on every host, forever, on purpose - so
        `"tests/test_x.py" in named[0]["message"]` is correct, portable code that
        cannot go red on any runner. The first fleet run of the undivided arm
        returned 64 rows and 27 were on this branch, sixteen of them in this very
        file. They are the SAME AST SHAPE as the rows that broke CI; the
        difference is that prax's `scanner.py:57` renders with `str()` and
        seedgo's `corpus.py:202` renders with `.as_posix()`, and no AST reader of
        the TEST can see either. So the row nominates and the number does not
        move - which is the only reason this pack can score its own test file at
        100. Mutation caught: `SCORING_SPECIES` gaining `SPECIES_RETURNED_PATH`,
        which drops this branch's own pins to 0 for being right.
        """
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
        """`.as_posix()` says "posix on purpose", and it is the cure this arm teaches.

        A site rewritten into `.as_posix()` on both sides is exactly what the
        finding asks for, so convicting it would convict the fix - the same
        reasoning that acquits `ntpath` and `posixpath` in arm 2. `os.sep`,
        `os.path.join` and `os.fspath` are acquitted with it: each of them NAMES
        the separator instead of assuming one. Mutation caught:
        `POSIX_SPELLING_METHOD: str = "as_posix"` becoming `"as_posix_"`, which
        matches nothing and puts every cured site back in the report.
        """
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
        """THE WEAKEST EVIDENCE THIS RULE USES, AND IT IS USED ON PURPOSE.

        A subscript into a result dict cannot prove its value ever was a Path, so
        when the key is not path-ish the arm falls back to asking whether the
        unit works with paths AT ALL. It is circumstantial, it is written down as
        circumstantial, and it is the second reason this half does not score.
        Without it `payload["body"] == "a/b.txt"` in a unit that never touches
        the filesystem is a nomination, and the arm reports the fleet's message
        bodies. Mutation caught: `return "subscript" if builds_path or
        _pathish_subscript(node) else ""` in `_returned_value` becoming `return
        "subscript"`.
        """
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
        """497 of the 501 rooted literals measured fleet-wide are DATA.

        A rooted literal is arms 1-2's subject - a root put through a resolver -
        and reading it here as well would put five hundred sites into arm 3's
        report to catch four that arms 1-2 already hold. Arm 4 is the one place
        the root is allowed, because inside a rendered repr the root is not the
        hazard and the separator is. Mutation caught: `return path_run(text,
        allow_rooted=False)` in `relative_path_run` becoming `allow_rooted=True`.
        """
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
        """THE SENTENCE FOLLOWS THE SPECIES, or it describes a finding that is not there.

        A project flagged only by arms 1-2 keeps the resolver sentence it has
        always had. The moment a rendering row joins the list, "put a rooted path
        literal through a resolver" would be describing a finding that is neither
        rooted nor resolved, and a reader sent looking for a resolver finds
        nothing. Mutation caught: `if species == {SPECIES_POSIX_LITERAL}:` in
        `_flagged_message` becoming `if True:`, which prints the resolver
        sentence over a REPR-HAYSTACK row.
        """
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
