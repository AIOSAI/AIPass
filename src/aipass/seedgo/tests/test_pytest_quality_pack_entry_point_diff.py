# =================== AIPass ====================
# Name: test_pytest_quality_pack_entry_point_diff.py
# Description: pytest_quality pack, entry_point_diff checker pins (split from test_pytest_quality_pack.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/entry_point_diff_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, pytest_quality_standards/entry_point_diff_content.py

from pathlib import Path

from aipass.seedgo.apps.handlers.pytest_quality_standards import entry_point_diff_check
from aipass.seedgo.tests.support_pytest_quality_pack import _write

# =============================================================================
# ENTRY POINT DIFF - THE VERB THE SUITE HAS NEVER ONCE SAID OUT LOUD
# =============================================================================


def _entry_point_project(root: Path) -> Path:
    """A project declaring five readable entry points, two of which are named.

    Both mentions live inside the SAME single test function on purpose, so that
    narrowing the corpus read to one node still finds them - which leaves the
    whole-file read to be pinned by its own test rather than by this fixture.
    """
    _write(
        root,
        "apps/cli.py",
        """
        COMMANDS = ("install-timer", "status", "purge-all")


        def handle(command):
            return command
        """,
    )
    _write(
        root,
        "apps/web.py",
        """
        @app.route("/admin/purge")
        def purge():
            return 204


        @app.get("/health")
        def health():
            return 200
        """,
    )
    _write(
        root,
        "tests/test_cli.py",
        """
        def test_the_cli_verb_and_the_admin_route_a_reader_expects():
            assert handle("status") == "status"
            assert client.post("/admin/purge").status == 403
        """,
    )
    return root


class TestEntryPointDiffReading:
    """What production declares and what the corpus names - every row rests here.

    Each test names the one-line mutation of `entry_point_diff_check` it was
    confirmed RED against, so a future reader can check the pin still bites
    rather than trusting that it once did.
    """

    def test_a_declared_verb_no_test_names_is_flagged_and_a_named_one_is_not(self, tmp_path):
        """The diff itself: the acquittal and the conviction in one project.

        Mutation caught: `if entry_point in mentioned: continue` inverted to
        `not in`. The negative controls are constructed, not borrowed - the two
        acquitted entry points are named by a literal in the corpus and by
        nothing else, so an inverted comparison cannot look plausible.
        """
        result = entry_point_diff_check.check_branch(str(_entry_point_project(tmp_path)))

        assert [row["entry_point"] for row in result["violations"]] == [
            "/health",
            "install-timer",
            "purge-all",
        ]

    def test_a_route_string_on_a_decorator_is_read_as_a_declaration(self, tmp_path):
        """A decorated route is a declaration, not just a constant tuple.

        Mutation caught: deleting the `elif isinstance(node, (ast.FunctionDef,
        ast.AsyncFunctionDef))` arm of `_declared_in`. Pinned on a project whose
        ONLY declaration is a route, so losing the arm turns a scored result
        into `not_applicable` instead of quietly shrinking a denominator.
        """
        _write(
            tmp_path,
            "apps/web.py",
            """
            @app.route("/admin/purge")
            def purge():
                return 204
            """,
        )
        _write(tmp_path, "tests/test_web.py", "def test_the_app_boots():\n    assert app is not None")

        result = entry_point_diff_check.check_branch(str(tmp_path))

        assert [row["entry_point"] for row in result["violations"]] == ["/admin/purge"]
        assert result["score"] == 0

    def test_a_decorator_that_is_not_a_call_is_stepped_over_rather_than_read(self, tmp_path):
        """A bare decorator has no `.args`, and reading one crashes the walk.

        Mutation caught: deleting `not isinstance(decorator, ast.Call) or` from
        the guard in `_from_route_decorators`, which raises AttributeError on
        the `@login_required` above the route. A static reader that dies on an
        ordinary decorator reports nothing about the whole project.
        """
        _write(
            tmp_path,
            "apps/web.py",
            """
            @login_required
            @app.route("/admin/purge")
            def purge():
                return 204
            """,
        )
        _write(tmp_path, "tests/test_web.py", "def test_the_app_boots():\n    assert app is not None")

        result = entry_point_diff_check.check_branch(str(tmp_path))

        assert [row["entry_point"] for row in result["violations"]] == ["/admin/purge"]

    def test_a_verb_named_only_outside_a_test_body_still_acquits(self, tmp_path):
        """The corpus is read WHOLE-FILE, because a suite names things at module level.

        A parametrize table, a fixture list or a shared constant is the suite
        naming a verb, and attributing the mention to one unit would manufacture
        findings out of file layout. Mutation caught: narrowing the read from
        the whole file to one node - `corpus.string_constants(parsed.tree)`
        becomes `corpus.string_constants(parsed.tree.body[-1])` - which loses
        every literal outside the last test function.
        """
        _write(tmp_path, "apps/cli.py", 'COMMANDS = ("purge-all",)')
        _write(
            tmp_path,
            "tests/test_cli.py",
            """
            VERBS_UNDER_TEST = ["purge-all"]


            def test_the_handler_echoes_an_unknown_command():
                assert handle("noop") == "noop"
            """,
        )

        result = entry_point_diff_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_verb_buried_in_prose_does_not_acquit_it(self, tmp_path):
        """THE V4 DEFECT, REFUSED AT THE ONE LINE THAT COULD REINTRODUCE IT.

        The standard this pack replaces matched pattern substrings over raw
        source, so comments and docstrings counted and a file of strings with no
        code scored 94 percent. A substring comparison here would rebuild that
        exactly: any branch could clear this rule by writing its verbs into a
        comment. The verb below is named in a module docstring and in a comment
        and nowhere else, and it must still be flagged. Mutation caught:
        `if entry_point in mentioned:` becoming
        `if any(entry_point in text for text in mentioned):`.
        """
        _write(tmp_path, "apps/cli.py", 'COMMANDS = ("purge-all",)')
        _write(
            tmp_path,
            "tests/test_cli.py",
            """
            '''This suite covers purge-all end to end.'''


            def test_the_handler_echoes_an_unknown_command():
                # purge-all is exercised by the integration lane
                assert handle("noop") == "noop"
            """,
        )

        result = entry_point_diff_check.check_branch(str(tmp_path))

        assert [row["entry_point"] for row in result["violations"]] == ["purge-all"]

    def test_a_verb_shorter_than_the_minimum_is_not_measured_at_all(self, tmp_path):
        """A short verb is left OUT OF THE DENOMINATOR, not scored as clean.

        A literal match on a two-character string is not evidence of anything,
        so `go` is not measured rather than measured badly. Mutation caught:
        deleting the `if len(entry_point) >= MINIMUM_VERB_LENGTH` filter from
        `measurable_entry_points`, which both flags `go` and inflates the
        denominator to 2 - the message assertion catches the second half even
        if a future exemption ever acquits the first.
        """
        _write(tmp_path, "apps/cli.py", 'COMMANDS = ("go", "status")')
        _write(tmp_path, "tests/test_cli.py", 'def test_status_is_routed():\n    assert handle("status")')

        result = entry_point_diff_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert "1/1 declared entry point(s)" in result["checks"][0]["message"]

    def test_one_verb_declared_in_two_modules_costs_the_project_once(self, tmp_path):
        """A re-export is one thing a test can name, not two - and the site is fixed.

        Mutation caught: `declared.setdefault(entry_point, site)` becomes
        `declared[entry_point] = site`, so the reader is sent to whichever
        module happened to be walked last. The row count catches a rewrite that
        stops deduping; the file name catches the last-wins flip, which is
        invisible to a count.
        """
        _write(tmp_path, "apps/a_first.py", 'COMMANDS = ("purge-all",)')
        _write(tmp_path, "apps/z_second.py", 'COMMANDS = ("purge-all",)')
        _write(tmp_path, "tests/test_x.py", "def test_the_app_boots():\n    assert app is not None")

        result = entry_point_diff_check.check_branch(str(tmp_path))

        assert len(result["violations"]) == 1
        assert result["violations"][0]["file"] == "apps/a_first.py"

    def test_the_declaring_name_reported_is_the_constant_that_matched(self, tmp_path):
        """The reason shown must be the reason the rule actually used.

        Mutation caught: `_declaring_constant` returning the FIRST target
        instead of the matching one - the spelling the nominator this was
        ported from shipped, which told a reader `CLI = COMMANDS = (...)` was
        "declared in CLI", a name that is not in COMMAND_CONSTANTS and is not
        why the verb was found.
        """
        _write(tmp_path, "apps/cli.py", 'CLI = COMMANDS = ("purge-all",)')
        _write(tmp_path, "tests/test_x.py", "def test_the_app_boots():\n    assert app is not None")

        result = entry_point_diff_check.check_branch(str(tmp_path))

        assert result["violations"][0]["declared"] == "declared in COMMANDS"

    def test_a_declaration_with_no_literal_list_behind_it_declares_nothing(self, tmp_path):
        """A runtime-assembled verb list and a bare annotation are BLIND SPOTS.

        `COMMANDS = load_commands()` and `HANDLED_COMMANDS: tuple` are named as
        unreadable in the module docstring, and this pins that they are silent
        rather than fatal - the second is also the behaviour the nominator's
        dead `node.value is None` guard appeared to protect, kept after the
        guard was deleted for never firing. Mutation caught: deleting the
        `isinstance(node, (ast.Tuple, ast.List, ast.Set))` guard from
        `_constant_strings`, which raises AttributeError on both.
        """
        _write(
            tmp_path,
            "apps/cli.py",
            """
            COMMANDS = load_commands()
            HANDLED_COMMANDS: tuple
            VERBS = ("purge-all",)
            """,
        )
        _write(tmp_path, "tests/test_x.py", "def test_the_app_boots():\n    assert app is not None")

        result = entry_point_diff_check.check_branch(str(tmp_path))

        assert [row["entry_point"] for row in result["violations"]] == ["purge-all"]


class TestEntryPointDiffBranchCheck:
    """The scoring API for entry_point_diff: what it reports and what it refuses."""

    def test_the_score_is_the_share_of_declared_entry_points_the_suite_names(self, tmp_path):
        """The number is entry-points-that-are-NAMED over declared, not the inverse.

        An inverted score still moves plausibly with the tree, so nothing about
        a live run would look wrong - a project would simply be told it is bad
        at exactly the rate it is good. Mutation caught: the numerator becoming
        `len(flagged)`, which reports 60 where the honest answer is 40.
        """
        result = entry_point_diff_check.check_branch(str(_entry_point_project(tmp_path)))

        assert result["score"] == 40

    def test_a_project_declaring_nothing_readable_is_not_applicable_not_a_number(self, tmp_path):
        """NOTHING MEASURED IS NOT NOTHING FOUND - and the alternative is a crash.

        Most projects declare no entry point in a shape this rule can read, so
        this is the commonest path it takes on a live fleet. Mutation caught:
        deleting the `if not declared:` early return, which divides by zero on
        every such project.
        """
        _write(tmp_path, "apps/helper.py", "def helper():\n    return 1")
        _write(tmp_path, "tests/test_x.py", "def test_the_helper_returns_one():\n    assert helper() == 1")

        result = entry_point_diff_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no entry point was declared" in result["checks"][0]["message"]
        assert "violations" not in result

    def test_the_production_files_it_could_not_read_are_named_beside_the_score(self, tmp_path):
        """THE MOST IMPORTANT LINE THIS CHECK EMITS, and the easiest to delete.

        The claim is "production declares X and no test names it", which is only
        honest beside a count of the production files that could not be read: an
        unreadable file declares nothing, so every entry point inside it is a
        finding that never happens, and the bias runs toward CLEAN. Mutation
        caught: deleting the `if production_limit:` block from `_limit_checks` -
        the score stays 40 and nothing else in the result changes, which is
        exactly why it needs its own pin.
        """
        _entry_point_project(tmp_path)
        _write(tmp_path, "apps/broken.py", "def handle(:\n    pass")

        result = entry_point_diff_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Production readable"]

        assert result["score"] == 40
        assert len(named) == 1
        assert "apps/broken.py" in named[0]["message"]
        assert "FEWER findings" in named[0]["message"]

    def test_the_production_limit_survives_onto_the_path_with_no_tests(self, tmp_path):
        """The unread count must not vanish on the path that scores nothing.

        A project with no tests still had production read, and the reader still
        needs to know the reading was incomplete. Mutation caught: dropping
        `+ unreadable` from the `total == 0` early return, which silently
        returns a bare not_applicable over a tree the rule could not finish.
        """
        _write(tmp_path, "apps/cli.py", 'COMMANDS = ("purge-all",)')
        _write(tmp_path, "apps/broken.py", "def handle(:\n    pass")

        result = entry_point_diff_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Production readable"]

        assert result["not_applicable"] is True
        assert len(named) == 1
        assert "apps/broken.py" in named[0]["message"]

    def test_the_result_passes_and_stays_advisory_even_when_entry_points_are_flagged(self, tmp_path):
        """SHADOW MODE GATES NOTHING - this rule scores before it is calibrated.

        Top-level `passed` must stay True while flags exist and `advisory` must
        stay True, so a caller can tell a report from a verdict. Mutation
        caught: `"passed": True` becoming `"passed": not flagged` in the scored
        return, which turns an uncalibrated advisory into a board failure.
        """
        result = entry_point_diff_check.check_branch(str(_entry_point_project(tmp_path)))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "ENTRY_POINT_DIFF"
        assert result["checks"][0]["passed"] is False
        assert "named by no test" in result["checks"][0]["message"]

    def test_a_project_with_no_tests_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND.

        A 0 blames a project for a fact about its layout; a 100 claims a
        measurement that never happened. Each check in this pack carries its own
        copy of the early return, so each one has to be pinned. Mutation caught:
        deleting `"not_applicable": True` from the `total == 0` return, which
        publishes a hard 0 into a branch average.
        """
        _write(tmp_path, "apps/cli.py", 'COMMANDS = ("purge-all",)')
        _write(tmp_path, "tests/helpers.py", "def build_row():\n    return {}")

        result = entry_point_diff_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A broken file must never read as an absent one - the ordering pin.

        An unparseable file contributes no units, so it cannot lower a score,
        and silence about it reads as a clean result. Mutation caught: replacing
        the `measured` ternary with the bare "no test files found" string, which
        makes a project with one broken test file indistinguishable from a
        project that has never written a test.
        """
        _write(tmp_path, "apps/cli.py", 'COMMANDS = ("purge-all",)')
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = entry_point_diff_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_broken.py" in check["message"] for check in result["checks"])

    def test_an_unparseable_test_file_is_named_beside_a_scored_result(self, tmp_path):
        """The unreadable line must also survive onto the path that DOES score.

        The early-return path carries it by construction; the scored path has to
        append it deliberately. Mutation caught: deleting `checks.extend(
        unreadable)`, which leaves a branch with a healthy number and no hint
        that a file was never read at all.
        """
        _entry_point_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = entry_point_diff_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["score"] == 40
        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]
