# =================== AIPass ====================
# Name: test_pytest_quality_pack_fresh_clone.py
# Description: pytest_quality pack, fresh_clone checker pins (split from test_pytest_quality_pack.py)
# Version: 1.1.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/fresh_clone_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, pytest_quality_standards/fresh_clone_content.py

from pathlib import Path

from aipass.seedgo.apps.handlers.pytest_quality_standards import fresh_clone_check
from aipass.seedgo.tests.support_pytest_quality_pack import _write


# Every project here is source text in tmp_path: a pin that read the live checkout would go red on the fresh clone it guards.

#: Six units clone-safe for six different reasons: units clean for one shared reason would still score 100 with five acquittals deleted.
_CLONE_SAFE_UNITS = """
BRANCH_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def hosted_baud(repo_root):
    return repo_root


@pytest.fixture
def repo_root(tmp_path):
    (tmp_path / "projects").mkdir()
    return tmp_path


def test_a_tree_with_no_projects_resolves_nothing(tmp_path):
    assert not (tmp_path / "projects" / "baud" / "registry.json").exists()


def test_the_registry_lists_what_the_fixture_built(hosted_baud):
    assert not (hosted_baud / "projects" / "baud" / "registry.json").exists()


def test_a_planted_passport_is_read_back(tmp_path):
    (tmp_path / ".trinity").mkdir()
    assert not (tmp_path / ".trinity" / "passport.json").exists()


def test_the_template_ships_its_passport():
    tpl = get_template_dir()
    assert (tpl / ".trinity" / "passport.json").is_file()


def test_the_local_file_is_a_document():
    local_file = BRANCH_ROOT / ".trinity" / "local.json"
    if not local_file.exists():
        pytest.skip("no live .trinity/local.json in this checkout")
    assert json.loads(local_file.read_text())["branch"] == "daemon"


def test_the_sample_document_parses():
    sample = Path(__file__).parent / "fixtures" / "sample.json"
    assert json.loads(sample.read_text()) == {"branch": "daemon"}
"""

#: The two species from fresh_clone.md: the ai_mail `if`/`else` and the daemon class-constant handed bare to production.
_HOST_DEPENDENT_UNITS = """
def test_the_live_fleet_still_resolves_its_four_residents():
    projects_tree = reg.find_repo_root() / reg.RESIDENT_PROJECTS_DIR
    live = reg.get_resident_branches()
    if projects_tree.is_dir():
        assert set(live) == {"@baud", "@earmark"}
    else:
        assert live == {}, "no projects/ tree on this machine"


def test_the_branch_reports_the_two_documents_it_holds():
    result = mh.get_memory_health_status(str(BRANCH_ROOT), "DAEMON")
    assert sorted(result["structure_checks"]) == [".trinity/local.json"]
"""


def _clone_safe_project(root: Path) -> Path:
    """Six units, every one of them green on a stranger's machine."""
    _write(root, "tests/test_fresh_clone_shapes.py", _CLONE_SAFE_UNITS)
    return root


def _fresh_clone_project(root: Path) -> Path:
    """The same six clean units with the two fleet rows appended - eight, two flagged."""
    _write(root, "tests/test_fresh_clone_shapes.py", _CLONE_SAFE_UNITS + "\n\n" + _HOST_DEPENDENT_UNITS)
    return root


class TestFreshCloneDetection:
    """The three species, and the structural readings each one needs to see them."""

    def test_a_path_the_repo_refuses_to_ship_and_the_unit_never_builds_is_flagged(self, tmp_path):
        """IGNORED_PATH, and this shape is a proof that EVAPORATES rather than one that breaks."""
        _write(
            tmp_path,
            "tests/test_migration.py",
            """
            def test_the_original_data_files_are_gone():
                daemon_root = Path(__file__).resolve().parents[1]
                assert not (daemon_root / "daemon_json" / "schedule.json").exists()
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))
        row = result["violations"][0]

        assert [r["species"] for r in result["violations"]] == ["IGNORED_PATH"]
        assert row["nodeid"] == "tests/test_migration.py::test_the_original_data_files_are_gone"
        assert "daemon_json" in row["detail"]
        assert ".gitignore" in row["detail"]

    def test_an_ignored_needle_is_read_segment_wise_and_never_as_a_substring(self, tmp_path):
        """`logs` is a directory, `catalogs.py` is a module, and one letter apart is not a rule."""
        _write(
            tmp_path,
            "tests/test_audit.py",
            """
            def test_the_audit_log_is_written():
                root = Path(__file__).resolve().parents[1]
                assert (root / "logs" / "audit.json").exists()


            def test_the_catalog_module_is_shipped():
                root = Path(__file__).resolve().parents[1]
                assert (root / "apps" / "catalogs.py").exists()
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert [row["nodeid"] for row in result["violations"]] == ["tests/test_audit.py::test_the_audit_log_is_written"]
        assert "'logs'" in result["violations"][0]["detail"]

    def test_an_oracle_that_is_a_runtime_if_on_the_machine_is_flagged(self, tmp_path):
        """BOTH_WORLDS: two assertions, two claims, and only one of them ever runs."""
        _write(
            tmp_path,
            "tests/test_handlers.py",
            """
            def test_the_handler_registry_matches_this_checkout():
                apps_tree = find_branch_root() / "apps"
                if apps_tree.is_dir():
                    assert sorted(handler_names()) == ["json_handler", "ruff_handler"]
                else:
                    assert handler_names() == []
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["BOTH_WORLDS"]
        assert (
            result["violations"][0]["nodeid"]
            == "tests/test_handlers.py::test_the_handler_registry_matches_this_checkout"
        )
        assert "asserts in both arms" in result["violations"][0]["detail"]

    def test_a_bare_machine_root_handed_to_production_under_a_written_expectation_is_flagged(self, tmp_path):
        """DERIVED_EXPECTED at its plainest: the host chose the value, the author typed it down."""
        _write(
            tmp_path,
            "tests/test_registry.py",
            """
            def test_the_registry_lists_the_three_branches():
                root = find_repo_root()
                assert collect_branches(root) == ["@daemon", "@devpulse", "@seedgo"]
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["DERIVED_EXPECTED"]
        assert "find_repo_root" in result["violations"][0]["detail"]
        assert "collect_branches" in result["violations"][0]["detail"]

    def test_a_machine_root_reached_through_a_module_level_constant_is_resolved_one_hop(self, tmp_path):
        """ONE HOP, MODULE HALF - a reader that only knew local names calls this clean."""
        _write(
            tmp_path,
            "tests/test_registry.py",
            """
            ROOT = Path(__file__).resolve().parents[1]


            def test_the_registry_lists_the_three_branches():
                assert collect_branches(ROOT) == ["@daemon", "@devpulse", "@seedgo"]
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["DERIVED_EXPECTED"]
        assert "Path(__file__).parents[...]" in result["violations"][0]["detail"]

    def test_a_directory_listed_for_its_contents_is_read_through_its_receiver(self, tmp_path):
        """A LISTING METHOD'S WORLD IS THE THING ON ITS LEFT, not something in its parentheses."""
        _write(
            tmp_path,
            "tests/test_tree.py",
            """
            def test_the_working_tree_holds_the_three_documents():
                assert sorted(p.name for p in Path.cwd().iterdir()) == ["a.json", "b.json", "c.json"]
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["DERIVED_EXPECTED"]
        assert "iterdir" in result["violations"][0]["detail"]


class TestFreshCloneTheTwoRowsCIWentRedOn:
    """The rule's own evidence, transcribed - and each red row beside its green sibling."""

    def test_row_one_the_live_fleet_resolver_is_flagged_and_its_tmp_path_sibling_is_not(self, tmp_path):
        """@ai_mail row 1, and the green sibling twelve lines above it in the real file."""
        _write(
            tmp_path,
            "tests/test_cross_project_bridge.py",
            """
            class TestTheResidentTree:
                def test_the_live_fleet_still_resolves_its_four_residents(self):
                    projects_tree = reg.find_repo_root() / reg.RESIDENT_PROJECTS_DIR
                    live = reg.get_resident_branches()
                    if projects_tree.is_dir():
                        assert set(live) == {"@baud", "@earmark", "@finch", "@aipass_site"}, sorted(live)
                    else:
                        assert live == {}, "no projects/ tree on this machine - nothing may resolve"

                def test_a_passport_cannot_add_a_branch_no_registry_lists(self, tmp_path):
                    stray = tmp_path / "projects" / "ghost" / "src" / "ghost" / ".trinity"
                    stray.mkdir(parents=True)
                    assert reg.get_resident_branches(tmp_path) == {}
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["BOTH_WORLDS"]
        assert result["violations"][0]["nodeid"] == (
            "tests/test_cross_project_bridge.py::TestTheResidentTree::"
            "test_the_live_fleet_still_resolves_its_four_residents"
        )
        assert result["score"] == 50

    def test_row_two_the_class_constant_root_is_flagged_and_its_skip_guarded_siblings_are_not(self, tmp_path):
        """@daemon row 2: BRANCH_ROOT is a CLASS attribute, and two green siblings prove the shape."""
        _write(
            tmp_path,
            "tests/test_memory_health.py",
            """
            class TestRealTrinityFiles:
                BRANCH_ROOT = Path(__file__).resolve().parents[1]

                def test_real_branch_reports_no_structure_issues(self):
                    result = mh.get_memory_health_status(str(self.BRANCH_ROOT), "DAEMON")
                    assert sorted(result["structure_checks"]) == [
                        ".trinity/local.json",
                        ".trinity/observations.json",
                    ]

                def test_the_local_file_is_a_document(self):
                    local_file = self.BRANCH_ROOT / ".trinity" / "local.json"
                    if not local_file.exists():
                        pytest.skip("no live .trinity/local.json in this checkout")
                    assert json.loads(local_file.read_text())["branch"] == "daemon"

                def test_the_observations_file_is_a_document(self):
                    observations = self.BRANCH_ROOT / ".trinity" / "observations.json"
                    if not observations.exists():
                        pytest.skip("no live .trinity/observations.json in this checkout")
                    assert json.loads(observations.read_text())["entries"] == []
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["DERIVED_EXPECTED"]
        assert result["violations"][0]["nodeid"] == (
            "tests/test_memory_health.py::TestRealTrinityFiles::test_real_branch_reports_no_structure_issues"
        )
        assert "get_memory_health_status" in result["violations"][0]["detail"]


class TestFreshCloneAcquittals:
    """The difference between a rule and a nuisance - each one a measured false positive."""

    def test_a_path_rooted_at_tmp_path_is_the_test_s_own_world(self, tmp_path):
        """NAMING AN IGNORED SPELLING ON PURPOSE IS THE CURE, so it must not be the finding."""
        _write(
            tmp_path,
            "tests/test_registry.py",
            """
            def test_a_stray_passport_resolves_nothing(tmp_path):
                assert not (tmp_path / "projects" / "ghost" / ".trinity" / "passport.json").exists()
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_tuple_unpack_of_a_sandbox_helper_binds_every_name_it_makes(self, tmp_path):
        """NINE ROWS, @spawn AND @memory, and every one of them this single line."""
        _write(
            tmp_path,
            "tests/test_spawn.py",
            """
            def test_the_minted_citizen_carries_no_archive(tmp_path):
                project, reg = _make_project(tmp_path, "ghost")
                assert not (project / ".trinity" / "passport.json").exists()
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_temp_test_dir_is_carried_by_name_because_the_fleet_template_roots_it_at_tmp_path(self, tmp_path):
        """A NAMED EXCEPTION WITH A REASON, and the reason is what has to survive an edit."""
        _write(
            tmp_path,
            "tests/test_drone.py",
            """
            def test_project_root_message_does_not_claim_a_passport(temp_test_dir):
                assert not (temp_test_dir / "projects" / "ghost" / ".trinity").is_dir()
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_nested_def_s_parameters_carry_the_sandbox_the_unit_already_built(self, tmp_path):
        """@memory's test_missing_file_skipped: the world is tmp_path all the way down."""
        _write(
            tmp_path,
            "tests/test_memory.py",
            """
            def test_missing_file_skipped(tmp_path):
                branch_dir = tmp_path / "src" / "aipass" / "empty_branch"
                branch_dir.mkdir(parents=True)
                mock_branches = [{"name": "empty_branch", "path": str(branch_dir)}]

                def mock_get_path(branch, mem_type):
                    p = Path(branch["path"]) / ".trinity" / "local.json"
                    return p if p.exists() else None

                assert collect(mock_branches, mock_get_path) == []
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_nested_def_in_a_unit_that_names_no_sandbox_is_still_a_row(self, tmp_path):
        """THE GATE IS THE POINT - the pin above is worthless without this one."""
        _write(
            tmp_path,
            "tests/test_memory.py",
            """
            def test_missing_file_skipped():
                mock_branches = [{"name": "daemon", "path": "/srv/aipass/src/aipass/daemon"}]

                def mock_get_path(branch, mem_type):
                    p = Path(branch["path"]) / ".trinity" / "local.json"
                    return p if p.exists() else None

                assert collect(mock_branches, mock_get_path) == []
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["IGNORED_PATH"]
        assert result["violations"][0]["nodeid"] == "tests/test_memory.py::test_missing_file_skipped"

    def test_a_spelling_the_unit_builds_itself_is_a_world_it_made(self, tmp_path):
        """THE CURE THE RULE TEACHES SECOND: build the tree, then read it."""
        _write(
            tmp_path,
            "tests/test_health.py",
            """
            def test_a_planted_observation_file_is_read_back():
                home = Path(__file__).resolve().parents[1] / "fixtures" / "branch"
                (home / ".trinity").mkdir(parents=True, exist_ok=True)
                assert not (home / ".trinity" / "observations.json").exists()
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_spelling_a_same_file_fixture_builds_acquits_the_units_that_request_it(self, tmp_path):
        """THE BUILD IS ROUTINELY ONE FRAME UP, which is where pytest users put it."""
        _write(
            tmp_path,
            "tests/test_planted.py",
            """
            @pytest.fixture
            def planted():
                home = Path(__file__).resolve().parents[1] / "fixtures"
                (home / ".trinity").mkdir(parents=True, exist_ok=True)
                return home


            def test_the_planted_tree_is_read_back(planted):
                assert not (planted / ".trinity" / "observations.json").exists()
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_sandbox_handed_out_through_a_chain_of_fixtures_is_followed_to_a_fixed_point(self, tmp_path):
        """SIX @ai_mail ROWS, and a single hop would still miss every one of them."""
        _write(
            tmp_path,
            "tests/test_cross_project_bridge.py",
            """
            @pytest.fixture
            def hosted_baud(repo_root):
                return repo_root


            @pytest.fixture
            def repo_root(tmp_path):
                return tmp_path


            def test_the_registry_lists_what_the_tree_holds(hosted_baud):
                assert not (hosted_baud / "projects" / "baud" / "registry.json").exists()
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_path_reached_through_a_negated_region_is_shipped_on_purpose(self, tmp_path):
        """FLAGGING A TEMPLATE PASSPORT IS EXACTLY BACKWARDS - the ignore file re-admits it."""
        _write(
            tmp_path,
            "tests/test_spawn.py",
            """
            def test_the_template_ships_its_passport():
                tpl = get_template_dir()
                assert (tpl / ".trinity" / "passport.json").is_file()
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_skip_guarded_unit_belongs_to_self_skip_and_is_left_alone_here(self, tmp_path):
        """ONE DEFECT MUST NOT PRODUCE TWO FINDINGS UNDER TWO STANDARDS."""
        _write(
            tmp_path,
            "tests/test_memory_health.py",
            """
            class TestRealTrinityFiles:
                BRANCH_ROOT = Path(__file__).resolve().parents[1]

                def test_the_local_file_is_a_document(self):
                    local_file = self.BRANCH_ROOT / ".trinity" / "local.json"
                    if not local_file.exists():
                        pytest.skip("no live .trinity/local.json in this checkout")
                    assert json.loads(local_file.read_text())["branch"] == "daemon"
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_machine_root_carrying_a_literal_segment_is_not_a_candidate_at_all(self, tmp_path):
        """BARE IS THE WHOLE NARROWING, and this is the half that keeps fixtures legal."""
        _write(
            tmp_path,
            "tests/test_fixtures.py",
            """
            def test_the_sample_document_parses():
                sample = Path(__file__).parent / "fixtures" / "sample.json"
                assert json.loads(sample.read_text()) == {"branch": "daemon"}
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_an_unclimbed_dunder_file_is_the_running_test_which_the_repo_ships(self, tmp_path):
        """SEVEN ROWS ACROSS @backup, @commons AND @devpulse, all of them correct code."""
        _write(
            tmp_path,
            "tests/test_backup.py",
            """
            def test_the_module_reader_names_the_handlers_it_was_given():
                assert sorted(declared_handlers(__file__)) == ["json_handler", "ruff_handler"]
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_property_assertion_is_not_an_expected_value_and_a_written_list_is(self, tmp_path):
        """FOUR FAMILIES CAME OFF THE FLEET FOR THIS ONE WORD, and it is what makes the species name true."""
        properties, written = tmp_path / "properties", tmp_path / "written"
        _write(
            properties,
            "tests/test_drone.py",
            """
            def test_the_two_readers_agree_on_this_checkout():
                root = find_repo_root()
                assert collect_branches(root) == collect_branches_v2(root)
            """,
        )
        _write(
            written,
            "tests/test_drone.py",
            """
            def test_the_two_readers_agree_on_this_checkout():
                root = find_repo_root()
                assert collect_branches(root) == ["@daemon", "@devpulse", "@seedgo"]
            """,
        )

        clean = fresh_clone_check.check_branch(str(properties))
        flagged = fresh_clone_check.check_branch(str(written))

        assert clean["violations"] == []
        assert [row["species"] for row in flagged["violations"]] == ["DERIVED_EXPECTED"]

    def test_a_spelling_handed_to_a_parser_is_a_string_and_not_a_directory_this_unit_opened(self, tmp_path):
        """ELEVEN CORRECT @ai_mail UNITS, convicted on the first run for a path they never reached."""
        _write(
            tmp_path,
            "tests/test_inbox.py",
            """
            def test_the_inbox_document_parses():
                document = parse_document(Path("/srv/aipass/branch/.ai_mail.local/inbox.json"))
                assert document["branch"] == "daemon"
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_an_existence_branch_that_asserts_in_only_one_arm_is_not_two_oracles(self, tmp_path):
        """BOTH arms have to assert, or the shape is an ordinary guard and not a second claim."""
        _write(
            tmp_path,
            "tests/test_bridge.py",
            """
            def test_the_apps_tree_resolves_what_it_holds():
                apps_tree = find_repo_root() / "apps"
                if apps_tree.is_dir():
                    assert set(handler_names()) == {"json_handler"}
                else:
                    pytest.fail("no apps tree on this machine")
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100


class TestFreshCloneBranchCheck:
    """The scoring-API contract, and the two paths where silence reads as clean."""

    def test_the_score_is_the_share_of_units_that_read_only_what_the_repo_ships(self, tmp_path):
        """The number is clean-over-total, counted per unit, and six acquittals hold it up."""
        result = fresh_clone_check.check_branch(str(_fresh_clone_project(tmp_path)))

        assert result["score"] == 75
        assert len(result["violations"]) == 2
        assert (
            "2/8 test units take their answer from state a fresh clone does not have" in result["checks"][0]["message"]
        )

    def test_a_project_whose_every_unit_builds_its_own_world_scores_one_hundred(self, tmp_path):
        """A CLEAN PROJECT HAS TO SAY SO IN ITS OWN WORDS, not merely produce no rows."""
        result = fresh_clone_check.check_branch(str(_clone_safe_project(tmp_path)))

        assert result["violations"] == []
        assert result["score"] == 100
        assert result["checks"][0]["passed"] is True
        assert result["checks"][0]["message"] == "6/6 test units read only what the repo ships"

    def test_a_unit_carrying_two_species_is_one_row_and_two_units_carrying_one_each_are_two(self, tmp_path):
        """A SCORE THAT CAN GO NEGATIVE IS ONE NOBODY BELIEVES TWICE."""
        together, apart = tmp_path / "together", tmp_path / "apart"
        _write(
            together,
            "tests/test_health.py",
            """
            def test_the_branch_reports_its_documents():
                root = find_repo_root()
                if (root / "apps").is_dir():
                    assert read_health(root) == ["ok"]
                else:
                    assert read_health(root) == []
            """,
        )
        _write(
            apart,
            "tests/test_health.py",
            """
            def test_the_branch_reports_what_this_checkout_holds():
                if find_repo_root().is_dir():
                    assert read_health() == ["ok"]
                else:
                    assert read_health() == []


            def test_the_health_reader_names_the_documents():
                assert read_health(find_repo_root()) == ["ok"]
            """,
        )

        one_unit = fresh_clone_check.check_branch(str(together))
        two_units = fresh_clone_check.check_branch(str(apart))

        assert [row["species"] for row in one_unit["violations"]] == ["BOTH_WORLDS"]
        assert one_unit["score"] == 0
        assert [row["species"] for row in two_units["violations"]] == ["BOTH_WORLDS", "DERIVED_EXPECTED"]

    def test_the_result_passes_and_stays_advisory_even_when_units_are_flagged(self, tmp_path):
        """A REPORT IS NOT A VERDICT - this rule nominates and a human decides."""
        result = fresh_clone_check.check_branch(str(_fresh_clone_project(tmp_path)))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "FRESH_CLONE"
        assert result["checks"][0]["name"] == "Fresh clone survivable"
        assert result["checks"][0]["passed"] is False
        assert sorted(result) == ["advisory", "checks", "passed", "score", "standard", "violations"]

    def test_a_project_with_no_test_files_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND."""
        _write(tmp_path, "apps/registry.py", "def find_repo_root():\n    return Path.cwd()")

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert result["score"] == 0
        assert "no test files found" in result["checks"][0]["message"]

    def test_an_unparseable_test_file_is_named_beside_a_scored_result(self, tmp_path):
        """AN UNREAD FILE FLAGS NOTHING, so for THIS rule silence biases toward clean."""
        _fresh_clone_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = fresh_clone_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["score"] == 75
        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]

    def test_only_twelve_flagged_units_are_named_and_the_rest_are_counted(self, tmp_path):
        """A CHECK MESSAGE PRINTING HUNDREDS OF LINES IS ONE NOBODY READS."""
        units = "\n\n\n".join(
            f"def test_row_{index:02d}():\n"
            f"    root = find_repo_root()\n"
            f'    assert collect_branches(root) == ["row-{index:02d}"]'
            for index in range(14)
        )
        _write(tmp_path, "tests/test_many.py", units)

        result = fresh_clone_check.check_branch(str(tmp_path))
        message = result["checks"][0]["message"]

        assert len(result["violations"]) == 14
        assert message.count("::test_row_") == 12
        assert message.endswith("(+2 more)")


#: api apps/modules/openrouter_client.py check_status(), minimised: the OpenAI SDK
#: is the `llm` extra, imported inside the function behind except ImportError.
_OPENROUTER_PRODUCT = """
import sys


def check_status():
    print("Provider: OpenRouter")
    try:
        import openai  # noqa: F401

        print("OpenAI SDK: available")
    except ImportError:
        print("OpenAI SDK not installed", file=sys.stderr)


def get_cache_stats():
    return {"cached_clients": 0}
"""


class TestFreshCloneOptionalExtra:
    """OPTIONAL_EXTRA: a unit calls a product function whose extra import is guarded, so the host's install decides."""

    def test_the_status_test_that_inherits_the_sdk_from_the_host_is_flagged(self, tmp_path):
        """api tests/test_openrouter_client.py pre-1.0.1 (d77aeb44): no llm extra on CI, a second warning followed."""
        _write(tmp_path, "apps/modules/openrouter_client.py", _OPENROUTER_PRODUCT)
        _write(
            tmp_path,
            "tests/test_openrouter_client.py",
            """
            from aipass.api.apps.modules import openrouter_client


            def test_check_status_no_key(capsys):
                openrouter_client.check_status()
                _out, err = capsys.readouterr()
                assert err.splitlines() == ["API key not configured"]


            def test_the_cache_is_empty():
                assert openrouter_client.get_cache_stats() == {"cached_clients": 0}
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        rows = [(row["nodeid"], row["line"], row["species"]) for row in result["violations"]]
        assert rows == [("tests/test_openrouter_client.py::test_check_status_no_key", 5, "OPTIONAL_EXTRA")]
        assert "openai" in result["violations"][0]["detail"]

    def test_a_unit_that_sets_the_module_entry_or_skips_on_its_absence_is_acquitted(self, tmp_path):
        """The cure: the test sets sys.modules['openai'] itself; importorskip is the other honest answer."""
        _write(tmp_path, "apps/modules/openrouter_client.py", _OPENROUTER_PRODUCT)
        _write(
            tmp_path,
            "tests/test_openrouter_client.py",
            """
            import sys
            import types

            import pytest

            from aipass.api.apps.modules import openrouter_client


            @pytest.mark.parametrize("sdk", [types.ModuleType("openai"), None])
            def test_check_status_no_key(sdk, capsys, monkeypatch):
                monkeypatch.setitem(sys.modules, "openai", sdk)
                openrouter_client.check_status()
                assert capsys.readouterr().err


            def test_check_status_with_the_sdk(capsys):
                pytest.importorskip("openai")
                openrouter_client.check_status()
                assert "available" in capsys.readouterr().out
            """,
        )

        assert fresh_clone_check.check_branch(str(tmp_path))["violations"] == []

    def test_a_sibling_that_names_the_extra_does_not_acquit_a_unit_that_does_not(self, tmp_path):
        """api test_check_status_with_key today: the file names openai in its sibling, this unit inherits the host."""
        _write(tmp_path, "apps/modules/openrouter_client.py", _OPENROUTER_PRODUCT)
        _write(
            tmp_path,
            "tests/test_openrouter_client.py",
            """
            import sys

            from aipass.api.apps.modules.openrouter_client import check_status


            def test_check_status_no_key(monkeypatch):
                monkeypatch.setitem(sys.modules, "openai", None)
                check_status()


            def test_check_status_with_key(capsys):
                check_status()
                assert "Provider" in capsys.readouterr().out
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert [row["nodeid"] for row in result["violations"]] == [
            "tests/test_openrouter_client.py::test_check_status_with_key"
        ]
