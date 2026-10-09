# =================== AIPass ====================
# Name: test_pytest_quality_pack_platform_oracle.py
# Description: pytest_quality pack, platform_oracle checker pins (split from test_pytest_quality_pack.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/platform_oracle_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, pytest_quality_standards/platform_oracle_content.py

from pathlib import Path

from aipass.seedgo.apps.handlers.pytest_quality_standards import platform_oracle_check
from aipass.seedgo.tests.support_pytest_quality_pack import _write

# =============================================================================
# PLATFORM ORACLE - IS THE VERDICT ABOUT THE CODE, OR ABOUT THE HOST
# =============================================================================

# NOTHING IN THIS SECTION ASKS THIS MACHINE ANYTHING, and the rule under test is
# the reason that has to be written down rather than assumed. A pin for a checker
# about listing order, mode bits, TEMP short names and `Path.cwd` is the one place
# in this file where a real `rglob` over the repo, a real `chmod`, a real
# `/dev/null` write or a real `os.getcwd()` would read as ordinary setup. There is
# none: every project below is source TEXT written into tmp_path, and every
# assertion is about what the CHECKER reported over that text. No `os.name`, no
# `sys.platform`, no separator and no directory order read from the running host,
# on any line - a pin for THIS rule that broke this rule would be the joke telling
# itself, and it would also be the first thing to go red on the Windows leg.

#: The two rows the rule was written for, transcribed from platform_oracle.md.
#: @skills sorting Paths off an rglob, and @hooks asking the kernel for an
#: ENOTDIR by using /dev/null as a DIRECTORY. Both score.
_ORACLE_SCORED_UNITS = """
def test_the_two_files_are_laid_down(tmp_path):
    files = sorted(p for p in tmp_path.rglob("*") if p.is_file())
    assert [f.name for f in files] == ["SKILL.md", "handler.py"]


def test_the_unwritable_log_is_reported():
    impossible = Path("/dev/null/impossible/log.jsonl")
    with patch(LOGGER_PATCH) as mock_logger:
        _write_delivery_log(impossible)
    assert mock_logger.warning.call_count == 1
"""

#: One row per nominate-only species, each transcribed from the branch the
#: dossier measured it on - @drone's subprocess launch, @spawn's
#: TemporaryDirectory equality, @prax's sealed cwd behind a `_patch` alias.
#: NONE of these may move a number.
_ORACLE_NOMINATED_UNITS = """
def test_the_missing_executable_is_named():
    with pytest.raises(RuntimeError) as exc_info:
        run_executor("this_executable_does_not_exist_xyz")
    cause = exc_info.value.__cause__
    assert cause.filename == "this_executable_does_not_exist_xyz"


def test_the_agent_reports_where_it_landed():
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "init_test"
        landed = _spawn_agent(str(target))
        assert Path(landed["path"]) == target


def test_the_dashboard_names_the_branch(tmp_path, capsys):
    with _patch("pathlib.Path.cwd", return_value=tmp_path):
        mod._handle_refresh([])
    assert tmp_path.name.upper() in capsys.readouterr().out
"""

#: Three units that are clean for three DIFFERENT reasons - a sort with an
#: explicit key, a failure injected at a patched seam, a sandbox rebound through
#: a resolver. Written this way on purpose: a project whose clean units were
#: clean for the SAME reason would still score 100 with two of the three
#: acquittals deleted.
_ORACLE_CLEAN_UNITS = """
def test_the_listing_is_sorted_by_a_key(tmp_path):
    files = sorted((p for p in tmp_path.rglob("*") if p.is_file()), key=str)
    assert [f.name for f in files] == ["SKILL.md", "handler.py"]


def test_the_write_failure_is_injected_at_the_seam(tmp_path):
    target = tmp_path / "delivery.jsonl"
    with patch("apps.writer.Path.write_text", side_effect=OSError("no")):
        with patch(LOGGER_PATCH) as mock_logger:
            _write_delivery_log(target)
    assert mock_logger.warning.call_count == 1


def test_the_sandbox_is_resolved_before_it_is_compared(tmp_path):
    tmp_path = tmp_path.resolve()
    landed = _spawn_agent(str(tmp_path))
    assert Path(landed["path"]) == tmp_path / "init_test"
"""


def _platform_oracle_project(root: Path) -> Path:
    """Eight units: two that score, three that only nominate, three that are clean.

    ONE FILE RATHER THAN THREE, because the acquittals, the scored rows and the
    nominations have to survive in each other's company. The split this rule
    lives or dies by is a claim about a project holding all three kinds at once,
    and a per-species reader that only ever saw one kind of file would never be
    caught letting a nomination leak into the number.
    """
    _write(
        root,
        "tests/test_platform_shapes.py",
        _ORACLE_SCORED_UNITS + "\n\n" + _ORACLE_NOMINATED_UNITS + "\n\n" + _ORACLE_CLEAN_UNITS,
    )
    return root


def _oracle_nominations_only_project(root: Path) -> Path:
    """Three units, one per nominate-only species, and nothing that scores."""
    _write(root, "tests/test_platform_shapes.py", _ORACLE_NOMINATED_UNITS)
    return root


def _oracle_clean_project(root: Path) -> Path:
    """Three units, no finding of any species at all."""
    _write(root, "tests/test_platform_shapes.py", _ORACLE_CLEAN_UNITS)
    return root


class TestPlatformOracleDetection:
    """The five species, and the structural readings each one needs to see them.

    Each test names the one-line mutation of `platform_oracle_check` it was
    confirmed RED against, so a later reader can check the pin still bites rather
    than trusting that it once did.
    """

    def test_a_sorted_listing_compared_with_a_list_literal_is_flagged(self, tmp_path):
        """THE ROW THIS RULE WAS WRITTEN FOR - sorted() did not save it.

        `sorted()` over PATH objects uses `PurePath.__lt__`, which is
        case-SENSITIVE on POSIX and case-FOLDED under ntpath: POSIX puts
        `SKILL.md` first because `'S' < 'h'`, Windows folds the case and hands
        back the other order. Production laid down the same two files on both
        legs; the pin is what disagreed. The finding has to name the listing call
        or a reader cannot tell which side came from the filesystem. Mutation
        caught: `LISTING_CALLS: frozenset = frozenset({"iterdir", "listdir",
        "glob", "rglob", "scandir", "walk"})` becoming the same set without
        `"rglob"`, which acquits the exact shape the rule exists for.
        """
        _write(
            tmp_path,
            "tests/test_template.py",
            """
            def test_the_two_files_are_laid_down(tmp_path):
                files = sorted(p for p in tmp_path.rglob("*") if p.is_file())
                assert [f.name for f in files] == ["SKILL.md", "handler.py"]
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))
        row = result["violations"][0]

        assert [r["species"] for r in result["violations"]] == ["LISTING_ORDER"]
        assert row["nodeid"] == "tests/test_template.py::test_the_two_files_are_laid_down"
        assert "rglob" in row["detail"]
        assert "2-element list literal" in row["detail"]

    def test_a_listing_compared_without_a_binding_hop_is_read_directly(self, tmp_path):
        """THE HOP IS AN EXTENSION OF THE READING, NOT THE WHOLE OF IT.

        `_listing_names` exists because the fleet row binds `files` on one line
        and compares it on the next, and a reader built only for that shape would
        miss the same defect written in one line. Both readings have to be live
        or the arm is one refactor of the corpus away from silence. Mutation
        caught: `return _listing_call(node) or _inherited_listing(node, listing)`
        in `_listing_source` becoming `return _inherited_listing(node, listing)`,
        which keeps the hop and loses the direct read.
        """
        _write(
            tmp_path,
            "tests/test_template.py",
            """
            def test_the_two_files_are_laid_down(tmp_path):
                assert sorted(tmp_path.iterdir()) == [tmp_path / "SKILL.md", tmp_path / "handler.py"]
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert [r["species"] for r in result["violations"]] == ["LISTING_ORDER"]
        assert "iterdir" in result["violations"][0]["detail"]

    def test_a_listing_reached_only_through_a_bound_name_is_still_read(self, tmp_path):
        """ONE HOP, AND THE LISTING'S OWN SPELLING TRAVELS WITH THE NAME.

        The row walks its rglob result twice - `files = sorted(...)` and then
        `for f in files` - so a set-valued reading had two names to choose from
        and named the loop variable. A reader told the other side "came from f"
        has been told nothing, which is why `_listing_names` is a dict. Mutation
        caught: `for name in sorted(_names_under(value) & set(named)): return
        named[name]` in `_inherited_listing` becoming `return ""`, which drops
        the hop and leaves the fleet's only LISTING_ORDER row invisible.
        """
        _write(
            tmp_path,
            "tests/test_template.py",
            """
            def test_the_two_files_are_laid_down(tmp_path):
                files = sorted(p for p in tmp_path.rglob("*") if p.is_file())
                names = [f.name for f in files]
                assert names == ["SKILL.md", "handler.py"]
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert [r["species"] for r in result["violations"]] == ["LISTING_ORDER"]
        assert "rglob" in result["violations"][0]["detail"]

    def test_a_posix_device_path_used_as_an_injector_is_flagged(self, tmp_path):
        """MODE_INJECTOR, and the fleet row is purer than a chmod.

        `/dev/null/impossible/log.jsonl` is null used as a DIRECTORY, which is an
        ENOTDIR only POSIX has to give. Windows has no such semantics, so the
        write SUCCEEDS, nothing is reported, and the must-warn assertion sees
        ZERO calls while the code under test behaves perfectly - a claim that
        silently inverts rather than one that goes red. Mutation caught:
        `DEVICE_PATH_PREFIXES: tuple = ("/dev/null/", "/dev/full", "/dev/zero/",
        "/proc/", "/sys/")` becoming `DEVICE_PATH_PREFIXES: tuple = ()`.
        """
        _write(
            tmp_path,
            "tests/test_telegram_response.py",
            """
            def test_the_unwritable_log_is_reported():
                impossible = Path("/dev/null/impossible/log.jsonl")
                with patch(LOGGER_PATCH) as mock_logger:
                    _write_delivery_log(impossible)
                assert mock_logger.warning.call_count == 1
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))
        row = result["violations"][0]

        assert [r["species"] for r in result["violations"]] == ["MODE_INJECTOR"]
        assert "/dev/null/impossible/log.jsonl" in row["detail"]
        assert "patched seam" in row["detail"]

    def test_a_chmod_to_a_mode_with_no_owner_write_bit_is_flagged(self, tmp_path):
        """The other half of MODE_INJECTOR: the kernel is asked for a favour.

        Windows ignores POSIX mode bits for the owner, so `0o444` refuses nothing
        there and the `pytest.raises` under it fails on a runner where production
        is fine. The mode is read as the LAST positional argument, which covers
        `os.chmod(p, m)` and `p.chmod(m)` in one reading. Mutation caught:
        `return "" if node.value & OWNER_WRITE_BIT else oct(node.value)` in
        `_readonly_mode` becoming `return ""`, which makes every integer mode in
        the fleet writable and silences the arm's whole int branch.
        """
        _write(
            tmp_path,
            "tests/test_writer.py",
            """
            def test_a_read_only_target_is_reported(tmp_path):
                target = tmp_path / "log.jsonl"
                target.chmod(0o444)
                with pytest.raises(PermissionError):
                    _write_delivery_log(target)
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert [r["species"] for r in result["violations"]] == ["MODE_INJECTOR"]
        assert "chmod to 0o444" in result["violations"][0]["detail"]

    def test_a_stat_constant_carrying_no_write_name_is_flagged(self, tmp_path):
        """The mode arm's second reading: a symbolic mode, read by its NAMES.

        `S_IREAD | S_IRGRP` is `0o440` and a reader that only understood integer
        literals would call it clean - which is the spelling a careful author
        reaches for precisely because it says what it means. The names are read
        rather than evaluated, because this rule never asks the running machine
        anything. The dotted spelling has its own pin below, because for one
        afternoon it was a hole. Mutation caught: `_mode_spellings`'s
        `if name.startswith("S_I")` becoming `if name.startswith("S_X")`.
        """
        _write(
            tmp_path,
            "tests/test_writer.py",
            """
            def test_a_read_only_mode_is_reported(tmp_path):
                target = tmp_path / "log.jsonl"
                target.chmod(S_IREAD | S_IRGRP)
                with pytest.raises(PermissionError):
                    _write_delivery_log(target)
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert [r["species"] for r in result["violations"]] == ["MODE_INJECTOR"]
        assert "S_IREAD" in result["violations"][0]["detail"]

    def test_the_same_mode_written_with_its_module_prefix_is_flagged_the_same(self, tmp_path):
        """TWO SPELLINGS OF ONE MODE, AND THE DEFECT THIS PIN WAS BORN FROM.

        Found while pinning this arm, 2026-09-08: `_names_under` collects bare
        names and dotted CALL targets - which is what its seven other readers
        want - and no plain attribute, so `stat.S_IREAD | stat.S_IRGRP` reached
        the mode reading as the single name `stat` and came back clean. The two
        units below differ in NOTHING but that prefix; before the cure the bare
        one scored 0 and the dotted one scored 100, while `platform_oracle.md`
        printed the dotted form as the shape it flags. Cured with a reader of its
        own, `_mode_spellings`, so the other seven call sites did not move.
        Mutation caught: `_mode_spellings`'s `elif isinstance(child,
        ast.Attribute): found.add(child.attr)` deleted - the dotted unit goes
        clean again and this pin goes red while the bare pin above stays green.
        """
        _write(
            tmp_path,
            "tests/test_writer.py",
            """
            def test_a_read_only_mode_is_reported(tmp_path):
                target = tmp_path / "log.jsonl"
                target.chmod(stat.S_IREAD | stat.S_IRGRP)
                with pytest.raises(PermissionError):
                    _write_delivery_log(target)

            def test_a_mode_that_keeps_the_write_bit_is_not_reported(tmp_path):
                target = tmp_path / "other.jsonl"
                target.chmod(stat.S_IRUSR | stat.S_IWUSR)
                _write_delivery_log(target)
                assert target.read_text()
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert [r["species"] for r in result["violations"]] == ["MODE_INJECTOR"]
        assert result["violations"][0]["nodeid"].endswith("test_a_read_only_mode_is_reported")
        assert "S_IREAD" in result["violations"][0]["detail"]

    def test_an_assertion_on_an_os_filled_exception_attribute_is_nominated(self, tmp_path):
        """OSERROR_ATTRIBUTE, and the hop that reaches @drone's row.

        `cause = exc_info.value.__cause__` puts the OS-filled exception in a
        SECOND name and the assertion is written against that one, so a reader
        that only knew the `pytest.raises` capture would call it clean. The
        finding has to spell out what `.filename` does on the other leg -
        "it differs" is not something a reader can act on - and this row is
        NOMINATED, never scored. Mutation caught: `OSERROR_ATTRIBUTES: frozenset
        = frozenset({"filename", "filename2", "strerror", "errno", "winerror"})`
        becoming the same set without `"filename"`.
        """
        _write(
            tmp_path,
            "tests/test_executor.py",
            """
            def test_the_missing_executable_is_named():
                with pytest.raises(RuntimeError) as exc_info:
                    run_executor("this_executable_does_not_exist_xyz")
                cause = exc_info.value.__cause__
                assert cause.filename == "this_executable_does_not_exist_xyz"
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))
        row = result["nominations"][0]

        assert result["violations"] == []
        assert [r["species"] for r in result["nominations"]] == ["OSERROR_ATTRIBUTE"]
        assert row["nodeid"] == "tests/test_executor.py::test_the_missing_executable_is_named"
        assert "filename=None" in row["detail"]

    def test_an_unresolved_temp_path_equality_is_nominated(self, tmp_path):
        """UNRESOLVED_TMP_PATH, minted outside the pytest fixture.

        @spawn's row uses `tempfile.TemporaryDirectory()`, not `tmp_path`, and
        the hazard is identical: the Windows runner's TEMP is an 8.3 short name
        (`RUNNER~1`) until something resolves it, the code under test resolves
        what it hands back, and `Path == Path` compares TEXT. A reader seeded
        only with the pytest fixture names would call the row clean. Mutation
        caught: `TEMPDIR_MAKERS: frozenset = frozenset({...})` becoming
        `TEMPDIR_MAKERS: frozenset = frozenset()`.
        """
        _write(
            tmp_path,
            "tests/test_contracts.py",
            """
            def test_the_agent_reports_where_it_landed():
                with tempfile.TemporaryDirectory() as td:
                    target = Path(td) / "init_test"
                    landed = _spawn_agent(str(target))
                    assert Path(landed["path"]) == target
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert [r["species"] for r in result["nominations"]] == ["UNRESOLVED_TMP_PATH"]
        assert "8.3 short name" in result["nominations"][0]["detail"]

    def test_a_sealed_cwd_beside_a_rendered_name_is_nominated(self, tmp_path):
        """SHALLOW_SANDBOX: the seam is one level too shallow.

        Sealing `cwd` onto a temp directory does not seal what is ABOVE it. On
        Windows TEMP lives under the user profile, so a production walk upward
        can reach the profile directory and the rendered name comes back
        `RUNNERADMIN`; `/tmp` has no such ancestor, which is why the same unit is
        green here forever. It NOMINATES, because whether production walks up is
        a fact about production and this checker reads test units. Mutation
        caught: `CWD_SEAM_NEEDLES: tuple = ("Path.cwd", "os.getcwd", "getcwdb",
        "pathlib.Path.cwd")` becoming `CWD_SEAM_NEEDLES: tuple = ()`. The seal is
        the plain `patch`, so the alias test below pins `_patch` apart from it.
        Mutant: `"patch"` dropped from `_is_patching_call`'s tail set in
        apps/handlers/pytest_quality_standards/platform_oracle_check.py — killed.
        """
        _write(
            tmp_path,
            "tests/test_operations.py",
            """
            def test_the_dashboard_names_the_branch(tmp_path, capsys):
                with patch("pathlib.Path.cwd", return_value=tmp_path):
                    mod._handle_refresh([])
                assert tmp_path.name.upper() in capsys.readouterr().out
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert [r["species"] for r in result["nominations"]] == ["SHALLOW_SANDBOX"]
        assert "pathlib.Path.cwd" in result["nominations"][0]["detail"]

    def test_a_locally_aliased_patch_still_counts_as_a_seal(self, tmp_path):
        """SHALLOW_SANDBOX MEASURED ZERO BEFORE THIS, and the alias is why.

        The two rows this species exists for are written `from unittest.mock
        import patch as _patch`, because the units already take a `monkeypatch`
        fixture and the author wanted the two spellings to read apart. A reader
        keyed on the exact name `patch` saw no seal at all and called both rows
        clean - the arm reported 0 and looked healthy. Mutation caught: `return
        tail in {"patch", "object", "dict"} or tail.endswith("_patch")` in
        `_is_patching_call` becoming `return tail in {"patch", "object", "dict"}`,
        which takes the arm back to the zero it started at.
        """
        _write(
            tmp_path,
            "tests/test_operations.py",
            """
            def test_the_dashboard_names_the_branch(tmp_path, capsys):
                with _patch("pathlib.Path.cwd", return_value=tmp_path):
                    mod._handle_refresh([])
                assert tmp_path.name.upper() in capsys.readouterr().out
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert [r["species"] for r in result["nominations"]] == ["SHALLOW_SANDBOX"]

    def test_a_dispatch_call_is_not_read_as_a_patch(self, tmp_path):
        """THE ALIAS TEST IS `_patch`, NOT `patch`, AND THE DIFFERENCE IS `dispatch`.

        `endswith("patch")` is the obvious way to catch the alias and it also
        catches every `dispatch(...)` in the fleet - a verb this house uses for
        sending work, not for sealing a seam. The underscore is what tells the
        two apart, and it is one character wide, which is exactly the kind of
        detail a later edit tidies away. Mutation caught:
        `tail.endswith("_patch")` becoming `tail.endswith("patch")`, which turns
        this unit into a SHALLOW_SANDBOX nomination it has no business being.
        """
        _write(
            tmp_path,
            "tests/test_operations.py",
            """
            def test_the_refresh_is_dispatched(tmp_path, capsys):
                with dispatch("pathlib.Path.cwd", return_value=tmp_path):
                    mod._handle_refresh([])
                assert tmp_path.name.upper() in capsys.readouterr().out
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["nominations"] == []
        assert result["violations"] == []
        assert result["score"] == 100


class TestPlatformOracleTheSplit:
    """TWO SPECIES SCORE, THREE NOMINATE - the design this rule lives or dies by.

    Each of the three nominate-only arms, written as a convicting arm, flags
    correct code: an assertion on `.errno` is often right, an unresolved
    `tmp_path` comparison is usually right on the host that wrote it, and a
    sealed `cwd` is only a defect when production walks up. So they are reported
    in their own check line, with `passed: True`, and they move NO number. The
    first time a fleet watches its score drop for a test that was right, the
    score stops being read - and then the arms that ARE sound stop being read
    with it. Every pin in this class is a different angle on that one claim.
    """

    def test_a_project_whose_only_findings_are_nominations_scores_one_hundred(self, tmp_path):
        """THE SPLIT, PINNED HEAD ON: three nominations, three units, 100.

        All three nominate-only species are present and every one of them is a
        place to look rather than a charge. If any of them reached the
        arithmetic, this project would report 0 and three branches that wrote
        correct tests would watch their number collapse. Mutation caught:
        `SCORING_SPECIES: tuple = ("LISTING_ORDER", "MODE_INJECTOR")` becoming
        `("LISTING_ORDER", "MODE_INJECTOR", "UNRESOLVED_TMP_PATH")`, which is the
        single most plausible future edit to this file and reports 66.
        """
        result = platform_oracle_check.check_branch(str(_oracle_nominations_only_project(tmp_path)))

        assert result["score"] == 100
        assert result["violations"] == []
        assert len(result["nominations"]) == 3
        assert sorted(r["species"] for r in result["nominations"]) == [
            "OSERROR_ATTRIBUTE",
            "SHALLOW_SANDBOX",
            "UNRESOLVED_TMP_PATH",
        ]

    def test_the_nominations_have_their_own_check_line_and_that_line_passes(self, tmp_path):
        """A NOMINATION IS A PLACE TO LOOK, AND THE CHECK LINE HAS TO SAY SO.

        Reported in a line of its own, `passed: True`, and the message states in
        words that these rows are not scored and not counted as failing - because
        a reader who sees three findings in a check line and no explanation will
        read them as three failures whatever the number says. Mutation caught:
        `"passed": True,` in the non-empty branch of `_nomination_check` becoming
        `"passed": not nominated,`, which turns every nomination into a failing
        check line while the score stays honest - the worst of both.
        """
        result = platform_oracle_check.check_branch(str(_oracle_nominations_only_project(tmp_path)))
        line = result["checks"][1]

        assert line["name"] == "Platform nominations"
        assert line["passed"] is True
        assert "3/3 test units are NOMINATED" in line["message"]
        assert "not scored, not counted as failing" in line["message"]

    def test_the_scored_line_stays_true_when_only_nominations_were_found(self, tmp_path):
        """The SCORED line is about the scored species and about nothing else.

        A project whose only findings are nominations has to read as what it is -
        three units that decide on the code - because the first check line is the
        one a board renders. Letting a nomination fail it would move the verdict
        without moving the number, which is worse than either alone: the number
        would say 100 and the board would say red. Mutation caught: `"passed":
        not scored,` becoming `"passed": not scored and not nominated,`.
        """
        result = platform_oracle_check.check_branch(str(_oracle_nominations_only_project(tmp_path)))
        line = result["checks"][0]

        assert line["passed"] is True
        assert "3/3 test units decide on the code rather than on the host" in line["message"]

    def test_a_nomination_does_not_move_a_number_a_scored_row_already_set(self, tmp_path):
        """SAME DENOMINATOR, SAME NUMERATOR, SAME ANSWER - the arithmetic angle.

        Two two-unit projects, each with the SAME single scored row. The second
        one's other unit carries a nomination instead of being clean, and the
        score has to be identical: 50 both times. Holding the unit count fixed is
        what makes this pin about the split rather than about the denominator -
        a project that merely grew would move the number honestly. Mutation
        caught: `score = int(((total - len(scored)) / total) * 100)` becoming
        `score = int(((total - len(scored) - len(nominated)) / total) * 100)`,
        which reports 0 for the second project and 50 for the first.
        """
        clean_partner = tmp_path / "clean"
        nominating_partner = tmp_path / "nominating"
        _write(
            clean_partner,
            "tests/test_shapes.py",
            _ORACLE_SCORED_UNITS.split("def test_the_unwritable_log_is_reported")[0]
            + '\n\ndef test_a_clean_unit(tmp_path):\n    assert (tmp_path / "a").parent == tmp_path\n',
        )
        _write(
            nominating_partner,
            "tests/test_shapes.py",
            _ORACLE_SCORED_UNITS.split("def test_the_unwritable_log_is_reported")[0]
            + "\n\n"
            + _ORACLE_NOMINATED_UNITS.split("def test_the_agent_reports_where_it_landed")[0],
        )

        clean = platform_oracle_check.check_branch(str(clean_partner))
        nominating = platform_oracle_check.check_branch(str(nominating_partner))

        assert clean["score"] == 50
        assert nominating["score"] == 50
        assert len(nominating["nominations"]) == 1
        assert len(nominating["violations"]) == len(clean["violations"]) == 1

    def test_the_failing_count_and_the_score_are_computed_from_the_scored_species_alone(self, tmp_path):
        """Eight units, two scored, three nominated - and the number is 75, not 37.

        The whole project in one reading: the two scoring rows charge, the three
        nominations are named in their own line, and the three clean units hold
        three different acquittals up. Both sentences are pinned, because a
        reader gets the sentence before the number. Mutation caught: `scored =
        [r for r in rows if r["species"] in SCORING_SPECIES]` in `split_rows`
        becoming `scored = list(rows)`, which reports 37 and prints "5/8 test
        units would decide differently" over three tests that are right.
        """
        result = platform_oracle_check.check_branch(str(_platform_oracle_project(tmp_path)))

        assert result["score"] == 75
        assert len(result["violations"]) == 2
        assert len(result["nominations"]) == 3
        assert "2/8 test units would decide differently on another platform" in result["checks"][0]["message"]
        assert "3/8 test units are NOMINATED" in result["checks"][1]["message"]

    def test_a_unit_that_scores_and_nominates_appears_in_both_lines(self, tmp_path):
        """DEDUPED SEPARATELY, AND THAT IS THE POINT OF THE SPLIT.

        One unit sorts an rglob against a list literal AND compares an
        unresolved sandbox path with something production handed back. It is one
        unit to charge and two things to look at. Collapsing the nomination
        behind the scored row would lose the second, and the nomination line is
        not a penalty - it is the reason a reader knows to check the second line
        of the same test. Mutation caught: `nominated = [r for r in rows if
        r["species"] not in SCORING_SPECIES]` becoming `nominated = [r for r in
        rows if r["species"] not in SCORING_SPECIES and r["nodeid"] not in
        {s["nodeid"] for s in scored}]`, which is exactly the "tidy up the
        duplicate" edit this docstring exists to refuse.
        """
        _write(
            tmp_path,
            "tests/test_template.py",
            """
            def test_the_listing_and_the_landing_are_both_checked(tmp_path):
                files = sorted(p for p in tmp_path.rglob("*") if p.is_file())
                assert [f.name for f in files] == ["SKILL.md", "handler.py"]
                landed = _spawn_agent(str(tmp_path))
                assert Path(landed["path"]) == tmp_path / "init_test"
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))
        nodeid = "tests/test_template.py::test_the_listing_and_the_landing_are_both_checked"

        assert [r["nodeid"] for r in result["violations"]] == [nodeid]
        assert [r["nodeid"] for r in result["nominations"]] == [nodeid]
        assert result["score"] == 0

    def test_two_scoring_species_in_one_unit_are_one_row_and_not_two(self, tmp_path):
        """A SCORE THAT CAN GO NEGATIVE IS ONE NOBODY BELIEVES TWICE.

        One unit carrying both scoring species is one unit a reader has to go and
        look at, not two. Counting findings instead of units lets a single
        loop-heavy test drive a two-unit project below zero. Mutation caught: `if
        row["nodeid"] in seen: continue` in `_dedupe_by_unit` becoming `if False:
        continue`, which reports two rows for one unit and scores 0 where the
        honest answer is 50.
        """
        _write(
            tmp_path,
            "tests/test_template.py",
            """
            def test_the_listing_and_the_refusal_are_both_checked(tmp_path):
                files = sorted(p for p in tmp_path.rglob("*") if p.is_file())
                assert [f.name for f in files] == ["SKILL.md", "handler.py"]
                target = tmp_path / "log.jsonl"
                target.chmod(0o444)
                with pytest.raises(PermissionError):
                    _write_delivery_log(target)


            def test_a_clean_unit(tmp_path):
                assert (tmp_path / "a").parent == tmp_path
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert len(result["violations"]) == 1
        assert result["violations"][0]["species"] == "LISTING_ORDER"
        assert result["score"] == 50


class TestPlatformOracleAcquittals:
    """Every narrowing that cost a measured false positive, pinned by name.

    An arm that convicts correct code is how a standard gets switched off. Each
    test below is one of the narrowings the dossier paid for in rows - the
    LISTING_ORDER 5-to-1, the OSERROR_ATTRIBUTE 4-to-2, the UNRESOLVED_TMP_PATH
    84-to-83 - and losing any of them puts correct code back in the report.
    """

    def test_a_sorted_with_an_explicit_key_is_not_a_listing_order_row(self, tmp_path):
        """ANY key at all, and that is a statement about what a key DOES.

        Supplying one displaces `PurePath.__lt__` entirely, which is the whole
        hazard - the spellings that appear in real cures are `key=str` and
        `key=lambda p: p.name`, and a key that sorts by size is just as
        deterministic. This is the acquittal a flagged site is rewritten INTO, so
        convicting it would be teaching a rewrite into something the rule also
        flags. Mutation caught: `if any(kw.arg == "key" for kw in
        call.keywords):` in `_sort_is_neutral` becoming `if any(kw.arg == "cmp"
        for kw in call.keywords):`.
        """
        _write(
            tmp_path,
            "tests/test_template.py",
            """
            def test_the_two_files_are_laid_down(tmp_path):
                files = sorted((p for p in tmp_path.rglob("*") if p.is_file()), key=str)
                assert [f.name for f in files] == ["SKILL.md", "handler.py"]
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_sort_over_names_rather_than_paths_is_not_a_listing_order_row(self, tmp_path):
        """THE NARROWING THAT TOOK THIS ARM FROM FIVE ROWS TO ONE.

        `sorted(p.name for p in d.glob(...))` never touches `PurePath.__lt__` at
        all - it sorts STRINGS, which is byte order on every host. Four of the
        five rows measured before this narrowing were @memory sorting `.name` off
        a glob, and two of those four are that branch's own case-folding pins,
        which handle both hosts explicitly and are the most portable code in the
        corpus. Mutation caught: `STRING_VALUED_ATTRIBUTES: frozenset =
        frozenset({"name", "stem", "suffix"})` becoming `frozenset()`, which puts
        all four back.
        """
        _write(
            tmp_path,
            "tests/test_entries.py",
            """
            def test_the_two_files_are_laid_down(tmp_path):
                names = sorted(p.name for p in tmp_path.glob("*"))
                assert names == ["SKILL.md", "handler.py"]
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_set_comparison_carries_no_order_to_disagree_about(self, tmp_path):
        """The cheapest cure there is: compare the set.

        A set does not have an order and a Counter does not read one, so the
        filesystem's arbitrary order cannot reach the claim. It is the first cure
        the rule's own message recommends, which makes flagging it the one
        mistake this arm must never make. Mutation caught: `UNORDERED_WRAPPERS:
        frozenset = frozenset({"set", "frozenset", "Counter"})` becoming
        `frozenset()`.
        """
        _write(
            tmp_path,
            "tests/test_template.py",
            """
            def test_the_two_files_are_laid_down(tmp_path):
                files = sorted(p for p in tmp_path.rglob("*") if p.is_file())
                assert set(f.name for f in files) == ["SKILL.md", "handler.py"]
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_one_element_literal_cannot_disagree_about_order(self, tmp_path):
        """One element has no order, whatever the filesystem hands back.

        The floor is two, and it is not a heuristic: a single-element list is the
        same list in every dialect, so flagging it would be reporting a
        divergence that cannot happen. Mutation caught: `if literal is None or
        len(literal.elts) < 2:` becoming `... len(literal.elts) < 1:`, which
        flags every one-file listing assertion in the fleet.
        """
        _write(
            tmp_path,
            "tests/test_template.py",
            """
            def test_only_one_file_is_laid_down(tmp_path):
                files = sorted(p for p in tmp_path.rglob("*") if p.is_file())
                assert [f.name for f in files] == ["SKILL.md"]
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_ast_walk_is_not_a_directory_listing(self, tmp_path):
        """`walk` is in LISTING_CALLS and `ast.walk` lists no directory.

        Every checker in this pack calls `ast.walk`, and so does every test that
        reads one - so a rule keyed on the verb alone would flag its own author's
        code first and the fleet's AST tooling second. The root is read and
        refused by name. Mutation caught: `NOT_LISTING_ROOTS: frozenset =
        frozenset({"ast", "os.path", "json", "re"})` becoming `frozenset()`.
        """
        _write(
            tmp_path,
            "tests/test_reader.py",
            """
            def test_every_node_is_visited(tree):
                nodes = [n for n in ast.walk(tree)]
                assert [type(n).__name__ for n in nodes] == ["Module", "FunctionDef"]
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_patched_write_seam_named_by_its_target_is_never_a_mode_injector_row(self, tmp_path):
        """THE ONE ACQUITTAL THAT IS NOT NEGOTIABLE, read from the patch TARGET.

        Injecting at the seam is the cure this arm teaches, so an arm that could
        flag the cure would be teaching a rewrite into something it also flags -
        and a fleet that discovers that stops taking the rewrite. The unit here
        still holds everything the arm looks for on the failure side, chmod
        included; only the injection has moved onto a patched `write_text`, and
        the `side_effect` is assigned on a later line so that this pin rests on
        the TARGET reading alone. Mutation caught: `WRITE_SEAMS: frozenset =
        frozenset({... "write_text", "write_bytes", ...})` becoming the same set
        without `"write_text"`.
        """
        _write(
            tmp_path,
            "tests/test_writer.py",
            """
            def test_the_write_failure_is_reported(tmp_path):
                target = tmp_path / "log.jsonl"
                target.chmod(0o444)
                with patch("apps.writer.Path.write_text") as writer:
                    writer.side_effect = IOError("no")
                    with patch(LOGGER_PATCH) as mock_logger:
                        _write_delivery_log(target)
                assert mock_logger.warning.call_count == 1
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_an_os_error_side_effect_on_any_patch_is_never_a_mode_injector_row(self, tmp_path):
        """The second half of the same acquittal: the seam named by its side_effect.

        The cure is also written `patch(seam, side_effect=OSError(...))` on a
        seam this rule's WRITE_SEAMS list has never heard of - a module's own
        private store, a helper, a client. The failure is still portable, still
        raised on every host, and still nothing to do with the filesystem's mood.
        Read from the `side_effect=` keyword rather than from the target, which
        is why it needs its own pin: the target reading acquits this unit not at
        all. Mutation caught: `if keyword.arg == "side_effect" and
        _names_under(keyword.value) & OSERROR_TYPES:` in
        `_seam_injects_the_failure` becoming `if keyword.arg == "side_effects"
        and _names_under(keyword.value) & OSERROR_TYPES:`.
        """
        _write(
            tmp_path,
            "tests/test_writer.py",
            """
            def test_the_write_failure_is_reported(tmp_path):
                target = tmp_path / "log.jsonl"
                target.chmod(0o444)
                with patch("apps.writer._store", side_effect=OSError("no")):
                    with patch(LOGGER_PATCH) as mock_logger:
                        _write_delivery_log(target)
                assert mock_logger.warning.call_count == 1
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_chmod_whose_answer_the_test_asks_the_platform_for_is_not_a_mode_injector_row(self, tmp_path):
        """The platform asked, the decision inside the test (flow's lock shape, fleet green leg 20).

        After the chmod the unit makes the same kind of call with its own
        hands in a ``try`` (in its body, or in a helper of the same module whose
        body is that try) and branches on what came back. The controls keep
        the row: a chmod with no probe, and a probe whose answer no ``if``
        reads. Red first on the reader that saw only the chmod; its proof is
        also the mutants.
        """
        _write(
            tmp_path,
            "tests/test_lock.py",
            """
            def _unlink_answer(path):
                try:
                    path.unlink()
                except OSError as exc:
                    return exc
                return None


            def test_helper_probe(tmp_path):
                tmp_path.chmod(0o555)
                refusal = _unlink_answer(tmp_path / "probe")
                if refusal is not None:
                    with pytest.raises(OSError):
                        acquire(tmp_path / "lock")
                else:
                    assert acquire(tmp_path / "lock") is True


            def test_inline_probe(tmp_path):
                tmp_path.chmod(0o555)
                try:
                    (tmp_path / "probe").write_text("x")
                    refused = None
                except OSError as exc:
                    refused = exc
                if refused is not None:
                    with pytest.raises(OSError):
                        acquire(tmp_path / "lock")
                else:
                    assert acquire(tmp_path / "lock") is True


            def test_no_probe(tmp_path):
                tmp_path.chmod(0o000)
                with pytest.raises(PermissionError):
                    acquire(tmp_path / "lock")


            def test_probe_never_read(tmp_path):
                tmp_path.chmod(0o555)
                refusal = _unlink_answer(tmp_path / "probe")
                with pytest.raises(PermissionError):
                    acquire(tmp_path / "lock")
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert [row["nodeid"].split("::")[-1] for row in result["violations"]] == [
            "test_no_probe",
            "test_probe_never_read",
        ]

    def test_dev_null_exactly_is_a_sink_and_not_an_injector(self, tmp_path):
        """`/dev/null` is correct, common and portable through `os.devnull`.

        The trailing slash in the prefix is the whole distinction: it is
        `/dev/null/something` - null used as a DIRECTORY - that provokes the
        ENOTDIR this arm is about, and Windows has no such semantics to provoke.
        Writing TO the sink is ordinary code that works everywhere. Mutation
        caught: the first element of `DEVICE_PATH_PREFIXES` becoming
        `"/dev/null"` without its trailing slash, which flags every sink write in
        the fleet.
        """
        _write(
            tmp_path,
            "tests/test_writer.py",
            """
            def test_the_sink_swallows_the_output():
                with patch(LOGGER_PATCH) as mock_logger:
                    _write_delivery_log(Path("/dev/null"))
                assert mock_logger.warning.call_count == 1
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_mode_that_keeps_the_owner_write_bit_is_not_an_injector(self, tmp_path):
        """An ordinary chmod is not a platform oracle - only a read-only one is.

        `0o644` refuses nothing on either host, so nothing about the unit's
        verdict changes with the platform. The arm is about a mode that asks the
        kernel to fail, not about the verb `chmod`. Mutation caught: `return ""
        if node.value & OWNER_WRITE_BIT else oct(node.value)` becoming `return
        oct(node.value)`, which flags every chmod in the fleet including the
        ones that grant permission.
        """
        _write(
            tmp_path,
            "tests/test_writer.py",
            """
            def test_a_writable_target_is_still_reported(tmp_path):
                target = tmp_path / "log.jsonl"
                target.chmod(0o644)
                with pytest.raises(OSError):
                    _write_delivery_log(target)
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_stat_constant_carrying_a_write_name_is_not_an_injector(self, tmp_path):
        """Any name with a W in it is a write bit, and a writable mode refuses nothing.

        The symbolic half of the same acquittal the integer half gets: a mode
        that grants the owner a write bit provokes no OSError on any host, so
        nothing about the unit's verdict changes with the platform. Reading the
        W out of the NAME rather than evaluating the constant is what keeps this
        rule from importing `stat` and asking this interpreter for a number - a
        portability rule that consulted the host would report a different
        standard on every leg of the matrix. Mutation caught: `if any("W" in
        _tail(n) for n in spellings):` becoming `if any("Z" in _tail(n) for n in
        spellings):`.
        """
        _write(
            tmp_path,
            "tests/test_writer.py",
            """
            def test_a_writable_mode_is_still_reported(tmp_path):
                target = tmp_path / "log.jsonl"
                target.chmod(S_IREAD | S_IWUSR)
                with pytest.raises(PermissionError):
                    _write_delivery_log(target)
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_boolean_mode_is_refused_by_name_rather_than_read_as_mode_one(self, tmp_path):
        """`isinstance(True, int)` is True in Python, and mode 1 has no write bit.

        A boolean handed to a chmod-shaped call is a test doing something else
        entirely, and reading it as an integer mode makes it a read-only mode by
        accident - a finding manufactured out of Python's own numeric tower.
        Refused by name, before the bit test. Mutation caught: `if
        isinstance(node.value, bool) or not isinstance(node.value, int):`
        becoming `if not isinstance(node.value, int):`.
        """
        _write(
            tmp_path,
            "tests/test_writer.py",
            """
            def test_a_flag_is_not_a_mode(tmp_path):
                target = tmp_path / "log.jsonl"
                target.chmod(True)
                with pytest.raises(OSError):
                    _write_delivery_log(target)
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_an_injector_with_no_failure_oracle_is_not_a_row(self, tmp_path):
        """The species is a FAILURE injected by the filesystem's mood.

        A unit that makes a file read-only and then asserts on a VALUE is not
        claiming anything about an error, so there is nothing for the other
        platform to invert. Without this half the arm would flag every
        permissions fixture in the fleet on the strength of the verb alone.
        Mutation caught: `if not injectors or not _asserts_on_failure(unit):`
        becoming `if not injectors:`.
        """
        _write(
            tmp_path,
            "tests/test_writer.py",
            """
            def test_a_read_only_target_still_reads(tmp_path):
                target = tmp_path / "log.jsonl"
                target.chmod(0o444)
                assert target.read_text() == ""
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_unit_that_manufactures_its_own_os_error_is_not_nominated(self, tmp_path):
        """THE NARROWING THAT TOOK OSERROR_ATTRIBUTE FROM FOUR ROWS TO TWO.

        The attribute is only OS-filled when the OS filled it. A stand-in the
        unit installs and raises from puts the test's OWN literal in `.errno`,
        and a literal is the same number on every platform because the test wrote
        it down. Two of the four rows measured were exactly this shape - @spawn's
        and this branch's own atomic-write retry pins - and both are portable
        code. Mutation caught: `if not captured or
        _unit_manufactures_the_error(unit.node):` becoming `if not captured:`.
        """
        _write(
            tmp_path,
            "tests/test_atomic_write.py",
            """
            def test_the_retry_reports_the_cross_device_link(monkeypatch, tmp_path):
                def refuse(src, dst):
                    raise OSError(errno.EXDEV, "invalid cross-device link")

                monkeypatch.setattr(os, "replace", refuse)
                with pytest.raises(OSError) as exc_info:
                    atomic_write(tmp_path / "a.json", "{}")
                assert exc_info.value.errno == errno.EXDEV
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["nominations"] == []
        assert result["violations"] == []

    def test_a_sandbox_rebound_through_a_resolver_cures_every_comparison_below_it(self, tmp_path):
        """`tmp_path = tmp_path.resolve()` as the first line is the template's cure.

        After it, every later comparison in the unit is already resolved without
        saying so on its own line - so a reader that only looked at the
        comparison would flag the unit that TOOK the cure, and the cure is the
        one thing the finding tells a reader to do. Mutation caught: `if
        _sandbox_is_resolved_once(unit.node, sandbox):` in
        `unresolved_tmp_path_rows` becoming `if False:`.
        """
        _write(
            tmp_path,
            "tests/test_contracts.py",
            """
            def test_the_agent_reports_where_it_landed(tmp_path):
                tmp_path = tmp_path.resolve()
                target = tmp_path / "init_test"
                landed = _spawn_agent(str(target))
                assert Path(landed["path"]) == target
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["nominations"] == []
        assert result["score"] == 100

    def test_a_path_the_test_built_itself_is_not_nominated(self, tmp_path):
        """POSITIVE EVIDENCE, NOT THE ABSENCE OF IT - the 84-to-83 narrowing.

        The first version asked only "is this name NOT sandbox-derived", which is
        a different question and answers yes for anything the reader failed to
        recognise. Both sides here were built by the TEST, walking its own
        `parents` list; neither ever went through production's resolver, so both
        are the same unresolved text and an 8.3 short name cannot separate them.
        Mutation caught: `return _traces_to_the_subject(node, values, spies,
        set())` in `_came_out_of_the_subject` becoming `return True`, which is
        the first version's reading exactly.
        """
        _write(
            tmp_path,
            "tests/test_walk.py",
            """
            def test_the_walk_finds_its_own_parent(tmp_path):
                parent_dir = tmp_path / "a"
                found = None
                for candidate in [parent_dir, *parent_dir.parents]:
                    if candidate.name == "a":
                        found = candidate
                assert found == parent_dir
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["nominations"] == []
        assert result["score"] == 100

    def test_a_furnished_sandbox_is_not_a_shallow_sandbox_row(self, tmp_path):
        """A unit that lays its own marker down is not relying on an ancestor.

        An upward walk stops INSIDE a sandbox that holds what the walk is looking
        for, so the rendered name is the sandbox's own and no profile directory
        can reach it. It is also the cheapest cure available to a flagged site,
        which is the second reason it must never be the thing the arm flags.
        Mutation caught: `SANDBOX_MARKER_CALLS: frozenset = frozenset({"mkdir",
        "touch", "write_text", "write_bytes", "symlink_to", "makedirs"})`
        becoming `frozenset()`.
        """
        _write(
            tmp_path,
            "tests/test_operations.py",
            """
            def test_the_dashboard_names_the_branch(tmp_path, capsys):
                (tmp_path / "DASHBOARD.local.json").write_text("{}")
                with _patch("pathlib.Path.cwd", return_value=tmp_path):
                    mod._handle_refresh([])
                assert tmp_path.name.upper() in capsys.readouterr().out
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["nominations"] == []
        assert result["score"] == 100

    def test_a_cwd_seam_that_never_names_the_sandbox_is_not_a_seal(self, tmp_path):
        """The sandbox has to be NAMED by the seal, or it is a different test.

        `patch("pathlib.Path.cwd")` handed a Mock never puts the process anywhere
        real, so no ancestor walk can escape into a user profile - there is no
        walk and no profile, only a stand-in. Flagging it would nominate every
        unit in the fleet that stubs `Path.cwd` for any reason at all. Mutation
        caught: `if any(_is_sandbox_path(kw.value, sandbox) for kw in
        node.keywords) or _names_under(node) & sandbox:` in `_cwd_seam_sealed`
        becoming `if True:`.
        """
        _write(
            tmp_path,
            "tests/test_operations.py",
            """
            def test_the_dashboard_names_the_branch(tmp_path, capsys):
                with _patch("pathlib.Path.cwd", return_value=Mock()):
                    mod._handle_refresh([])
                assert tmp_path.name.upper() in capsys.readouterr().out
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["nominations"] == []
        assert result["score"] == 100


class TestPlatformOracleBranchCheck:
    """The scoring-API contract, and the two paths where silence reads as clean."""

    def test_a_project_with_nothing_to_find_scores_one_hundred_and_says_so(self, tmp_path):
        """Three clean units, three different acquittals, one honest number.

        The clean sentence is pinned beside the number because it is what a
        reader sees first, and the nominations line has to be present and empty
        rather than absent - a missing line reads as a rule that did not run.
        Mutation caught: `f"{total - len(scored)}/{total} test units decide on
        the code rather than on the host"` becoming `f"{len(scored)}/{total} ..."`,
        which prints 0/3 over a project where all three are right.
        """
        result = platform_oracle_check.check_branch(str(_oracle_clean_project(tmp_path)))

        assert result["score"] == 100
        assert result["violations"] == []
        assert result["nominations"] == []
        assert "3/3 test units decide on the code rather than on the host" in result["checks"][0]["message"]
        assert "0/3 test units carry a platform nomination" in result["checks"][1]["message"]

    def test_the_result_carries_the_scoring_api_shape_and_stays_advisory(self, tmp_path):
        """SHADOW MODE GATES NOTHING - this rule reports and a human decides.

        Top-level `passed` must stay True while flags exist and `advisory` must
        stay True, so a caller can tell a report from a verdict. The two extra
        keys this rule carries - `violations` AND `nominations` - are part of the
        contract too: a report lane that only read `violations` would print two
        rows and lose the three a reader was told to go and look at. Mutation
        caught: `"passed": True,` becoming `"passed": not scored,` in the scored
        return, which turns an uncalibrated advisory into a board failure.
        """
        result = platform_oracle_check.check_branch(str(_platform_oracle_project(tmp_path)))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "PLATFORM_ORACLE"
        assert result["checks"][0]["passed"] is False
        assert sorted(result) == [
            "advisory",
            "checks",
            "nominations",
            "passed",
            "score",
            "standard",
            "violations",
        ]

    def test_a_project_with_no_test_files_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND.

        A 0 blames a project for a fact about its layout and a 100 claims a
        measurement that never happened. Each check in this pack carries its own
        copy of the early return, so each one has to be pinned - and losing it
        here does not return a wrong number, it divides by zero and takes the
        caller with it. Mutation caught: `"not_applicable": True,` becoming
        `"not_applicable": False,` in the `total == 0` return.
        """
        _write(tmp_path, "apps/writer.py", "def write_log(path):\n    return path")

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert result["score"] == 0
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A broken file must never read as an absent one - the ordering pin.

        An unparseable file contributes no units, so it cannot lower a score, and
        silence about it reads as a clean result. This is the one path where
        nothing else can catch it: the message a caller sees must say the file
        was present and unreadable, not that the project has never written a
        test. Mutation caught: the `measured` ternary's `if not
        scanned.unparseable` becoming `if True`, which makes the two cases
        indistinguishable.
        """
        _write(tmp_path, "tests/test_unreadable_shapes.py", "def test_broken(:\n    assert True")

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_unreadable_shapes.py" in check["message"] for check in result["checks"])

    def test_an_unparseable_file_is_named_beside_a_scored_result(self, tmp_path):
        """AN UNREAD FILE FLAGS NOTHING, so for THIS rule silence biases toward clean.

        The early-return path carries the unreadable line by construction; the
        scored path has to append it deliberately, and dropping that one line
        leaves a branch with a healthy number and no hint that a file was never
        read at all. The message has to say NOT measured, not merely name the
        file. Mutation caught: `checks.extend(unreadable)` becoming
        `checks.extend([])`.
        """
        _platform_oracle_project(tmp_path)
        _write(tmp_path, "tests/test_unreadable_shapes.py", "def test_broken(:\n    assert True")

        result = platform_oracle_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["score"] == 75
        assert len(named) == 1
        assert "test_unreadable_shapes.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]

    def test_only_twelve_flagged_units_are_named_and_the_rest_are_counted(self, tmp_path):
        """A CHECK MESSAGE PRINTING HUNDREDS OF LINES IS ONE NOBODY READS.

        Fourteen flagged units, twelve named, and the remainder stated as a
        number rather than dropped - a truncation that did not say it had
        truncated would understate a branch's problem to every reader of the
        board while the score stayed honest. The violations list itself is never
        truncated, because the report artifact is where the full list lives.
        Mutation caught: `MAX_REPORTED: int = 12` becoming `MAX_REPORTED: int =
        24`, which names all fourteen and prints no remainder.
        """
        units = "\n\n\n".join(
            f"def test_row_{index:02d}(tmp_path):\n"
            f"    files = sorted(p for p in tmp_path.rglob('*') if p.is_file())\n"
            f'    assert [f.name for f in files] == ["SKILL.md", "row-{index:02d}.py"]'
            for index in range(14)
        )
        _write(tmp_path, "tests/test_many_listings.py", units)

        result = platform_oracle_check.check_branch(str(tmp_path))
        message = result["checks"][0]["message"]

        assert len(result["violations"]) == 14
        assert message.count("::test_row_") == 12
        assert message.endswith("(+2 more)")
