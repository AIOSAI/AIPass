# =================== AIPass ====================
# Name: test_pytest_quality_pack_platform_oracle.py
# Description: pytest_quality pack, platform_oracle checker pins (split from test_pytest_quality_pack.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/platform_oracle_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, pytest_quality_standards/platform_oracle_content.py

from pathlib import Path

from aipass.seedgo.apps.handlers.pytest_quality_standards import platform_oracle_check
from aipass.seedgo.tests.support_pytest_quality_pack import _write


# Every project here is source text in tmp_path: nothing reads the running host's os.name, platform, separator or directory order.

#: The two rows from platform_oracle.md: Paths sorted off an rglob, and /dev/null used as a directory for ENOTDIR. Both score.
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

#: One row per nominate-only species: a subprocess launch, TemporaryDirectory equality, a sealed cwd behind a `_patch` alias. None may move a number.
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

#: Three units clean for three different reasons: units clean for one shared reason would still score 100 with two acquittals deleted.
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
    """Eight units: two that score, three that only nominate, three that are clean."""
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
    """The five species, and the structural readings each one needs to see them."""

    def test_a_sorted_listing_compared_with_a_list_literal_is_flagged(self, tmp_path):
        """THE ROW THIS RULE WAS WRITTEN FOR - sorted() did not save it."""
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
        """THE HOP IS AN EXTENSION OF THE READING, NOT THE WHOLE OF IT."""
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
        """ONE HOP, AND THE LISTING'S OWN SPELLING TRAVELS WITH THE NAME."""
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
        """MODE_INJECTOR, and the fleet row is purer than a chmod."""
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
        """The other half of MODE_INJECTOR: the kernel is asked for a favour."""
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
        """The mode arm's second reading: a symbolic mode, read by its NAMES."""
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
        """TWO SPELLINGS OF ONE MODE, AND THE DEFECT THIS PIN WAS BORN FROM."""
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
        """OSERROR_ATTRIBUTE, and the hop that reaches @drone's row."""
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
        """UNRESOLVED_TMP_PATH, minted outside the pytest fixture."""
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
        """SHALLOW_SANDBOX: the seam is one level too shallow."""
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
        """SHALLOW_SANDBOX MEASURED ZERO BEFORE THIS, and the alias is why."""
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
        """THE ALIAS TEST IS `_patch`, NOT `patch`, AND THE DIFFERENCE IS `dispatch`."""
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
    """TWO SPECIES SCORE, THREE NOMINATE - the design this rule lives or dies by."""

    def test_a_project_whose_only_findings_are_nominations_scores_one_hundred(self, tmp_path):
        """THE SPLIT, PINNED HEAD ON: three nominations, three units, 100."""
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
        """A NOMINATION IS A PLACE TO LOOK, AND THE CHECK LINE HAS TO SAY SO."""
        result = platform_oracle_check.check_branch(str(_oracle_nominations_only_project(tmp_path)))
        line = result["checks"][1]

        assert line["name"] == "Platform nominations"
        assert line["passed"] is True
        assert "3/3 test units are NOMINATED" in line["message"]
        assert "not scored, not counted as failing" in line["message"]

    def test_the_scored_line_stays_true_when_only_nominations_were_found(self, tmp_path):
        """The SCORED line is about the scored species and about nothing else."""
        result = platform_oracle_check.check_branch(str(_oracle_nominations_only_project(tmp_path)))
        line = result["checks"][0]

        assert line["passed"] is True
        assert "3/3 test units decide on the code rather than on the host" in line["message"]

    def test_a_nomination_does_not_move_a_number_a_scored_row_already_set(self, tmp_path):
        """SAME DENOMINATOR, SAME NUMERATOR, SAME ANSWER - the arithmetic angle."""
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
        """Eight units, two scored, three nominated - and the number is 75, not 37."""
        result = platform_oracle_check.check_branch(str(_platform_oracle_project(tmp_path)))

        assert result["score"] == 75
        assert len(result["violations"]) == 2
        assert len(result["nominations"]) == 3
        assert "2/8 test units would decide differently on another platform" in result["checks"][0]["message"]
        assert "3/8 test units are NOMINATED" in result["checks"][1]["message"]

    def test_a_unit_that_scores_and_nominates_appears_in_both_lines(self, tmp_path):
        """DEDUPED SEPARATELY, AND THAT IS THE POINT OF THE SPLIT."""
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
        """A SCORE THAT CAN GO NEGATIVE IS ONE NOBODY BELIEVES TWICE."""
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
    """Every narrowing that cost a measured false positive, pinned by name."""

    def test_a_sorted_with_an_explicit_key_is_not_a_listing_order_row(self, tmp_path):
        """ANY key at all, and that is a statement about what a key DOES."""
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
        """THE NARROWING THAT TOOK THIS ARM FROM FIVE ROWS TO ONE."""
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
        """The cheapest cure there is: compare the set."""
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
        """One element has no order, whatever the filesystem hands back."""
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
        """`walk` is in LISTING_CALLS and `ast.walk` lists no directory."""
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
        """THE ONE ACQUITTAL THAT IS NOT NEGOTIABLE, read from the patch TARGET."""
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
        """The second half of the same acquittal: the seam named by its side_effect."""
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
        """The platform asked, the decision inside the test (flow's lock shape, fleet green leg 20)."""
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
        """`/dev/null` is correct, common and portable through `os.devnull`."""
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
        """An ordinary chmod is not a platform oracle - only a read-only one is."""
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
        """Any name with a W in it is a write bit, and a writable mode refuses nothing."""
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
        """`isinstance(True, int)` is True in Python, and mode 1 has no write bit."""
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
        """The species is a FAILURE injected by the filesystem's mood."""
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
        """THE NARROWING THAT TOOK OSERROR_ATTRIBUTE FROM FOUR ROWS TO TWO."""
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
        """`tmp_path = tmp_path.resolve()` as the first line is the template's cure."""
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
        """POSITIVE EVIDENCE, NOT THE ABSENCE OF IT - the 84-to-83 narrowing."""
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
        """A unit that lays its own marker down is not relying on an ancestor."""
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
        """The sandbox has to be NAMED by the seal, or it is a different test."""
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
        """Three clean units, three different acquittals, one honest number."""
        result = platform_oracle_check.check_branch(str(_oracle_clean_project(tmp_path)))

        assert result["score"] == 100
        assert result["violations"] == []
        assert result["nominations"] == []
        assert "3/3 test units decide on the code rather than on the host" in result["checks"][0]["message"]
        assert "0/3 test units carry a platform nomination" in result["checks"][1]["message"]

    def test_the_result_carries_the_scoring_api_shape_and_stays_advisory(self, tmp_path):
        """SHADOW MODE GATES NOTHING - this rule reports and a human decides."""
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
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND."""
        _write(tmp_path, "apps/writer.py", "def write_log(path):\n    return path")

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert result["score"] == 0
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A broken file must never read as an absent one - the ordering pin."""
        _write(tmp_path, "tests/test_unreadable_shapes.py", "def test_broken(:\n    assert True")

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_unreadable_shapes.py" in check["message"] for check in result["checks"])

    def test_an_unparseable_file_is_named_beside_a_scored_result(self, tmp_path):
        """AN UNREAD FILE FLAGS NOTHING, so for THIS rule silence biases toward clean."""
        _platform_oracle_project(tmp_path)
        _write(tmp_path, "tests/test_unreadable_shapes.py", "def test_broken(:\n    assert True")

        result = platform_oracle_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["score"] == 75
        assert len(named) == 1
        assert "test_unreadable_shapes.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]

    def test_only_twelve_flagged_units_are_named_and_the_rest_are_counted(self, tmp_path):
        """A CHECK MESSAGE PRINTING HUNDREDS OF LINES IS ONE NOBODY READS."""
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
