# =================== AIPass ====================
# Name: test_pytest_quality_pack_fresh_clone.py
# Description: pytest_quality pack, fresh_clone checker pins (split from test_pytest_quality_pack.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/fresh_clone_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, pytest_quality_standards/fresh_clone_content.py

from pathlib import Path

from aipass.seedgo.apps.handlers.pytest_quality_standards import fresh_clone_check
from aipass.seedgo.tests.support_pytest_quality_pack import _write

# =============================================================================
# FRESH CLONE - WOULD THIS TEST PASS ON A MACHINE THAT HAS ONLY WHAT THE REPO SHIPS
# =============================================================================

# NOTHING IN THIS SECTION READS THE LIVE CHECKOUT, and the rule under test is the
# reason that has to be written down rather than assumed. A pin for a checker
# about `.trinity`, `projects/`, `find_repo_root()` and `Path(__file__).parents[1]`
# is the one place in this file where a real read of the branch tree would look
# like ordinary setup. There is none: every project below is source TEXT written
# into tmp_path, and every assertion is about what the CHECKER reported over that
# text. No fleet count, no branch name, no live registry, nothing outside the
# fixture directory - a pin for THIS rule that broke this rule would be the joke
# telling itself, and it would also be red on the fresh clone CI now runs.

#: Six units that are clone-safe for six DIFFERENT reasons - sandbox root,
#: sandbox handed out by a fixture chain, a spelling the unit builds, a negated
#: template region, a skip guard, and a machine root carrying a literal. Written
#: this way on purpose: a project whose clean units were clean for the SAME
#: reason would still score 100 with five of the six acquittals deleted.
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

#: The two rows CI went red on, transcribed from fresh_clone.md. One per species
#: that the fleet actually produced - the ai_mail `if`/`else` and the daemon
#: class-constant handed bare to production.
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
    """The same six clean units with the two fleet rows appended - eight, two flagged.

    One file rather than two, because the acquittals and the findings have to
    survive in each other's company: `sandbox_fixtures` and
    `fixture_built_spellings` are read once per FILE, and a per-file reader that
    only ever saw clean files would never be caught confusing them.
    """
    _write(root, "tests/test_fresh_clone_shapes.py", _CLONE_SAFE_UNITS + "\n\n" + _HOST_DEPENDENT_UNITS)
    return root


class TestFreshCloneDetection:
    """The three species, and the structural readings each one needs to see them.

    Each test names the one-line mutation of `fresh_clone_check` it was confirmed
    RED against, so a later reader can check the pin still bites rather than
    trusting that it once did.
    """

    def test_a_path_the_repo_refuses_to_ship_and_the_unit_never_builds_is_flagged(self, tmp_path):
        """IGNORED_PATH, and this shape is a proof that EVAPORATES rather than one that breaks.

        `**/*_json/` is ignored, so a clone has nothing under `daemon_json/` -
        and the assertion cannot go red there. It stays green forever, having
        stopped checking anything, which is worse than a loud failure because
        nobody finds out. The finding has to name the segment or a reader cannot
        tell which part of the path is the problem. Mutation caught:
        `IGNORED_SEGMENT_SUFFIXES: tuple = ("_json",)` becoming
        `IGNORED_SEGMENT_SUFFIXES: tuple = ()`, which leaves every runtime-JSON
        directory in the fleet invisible while the other two species look healthy.
        """
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
        """`logs` is a directory, `catalogs.py` is a module, and one letter apart is not a rule.

        Both units below reach a path on the filesystem and only one of them
        names an ignored directory. A substring reading would convict the second
        for the four letters at the end of its filename, which is the kind of
        false positive that gets a whole standard switched off. Mutation caught:
        `if segment in IGNORED_SEGMENTS or segment in IGNORED_FILE_NAMES:` in
        `is_ignored_segment` becoming `if any(s in segment for s in
        IGNORED_SEGMENTS) or segment in IGNORED_FILE_NAMES:`, which flags both.
        """
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
        """BOTH_WORLDS: two assertions, two claims, and only one of them ever runs.

        Whichever arm this host selects is the only arm anybody reads; the other
        is prose wearing an assert. Nothing here names an ignored spelling, so
        the row can only come from the `if`/`else` reading and not from arm one
        riding along. Mutation caught: `if not isinstance(node, ast.If) or not
        node.orelse:` in `_both_worlds` becoming `if not isinstance(node,
        ast.If) or node.orelse:`, which walks past every branch that has the
        second arm this species is made of.
        """
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
        """DERIVED_EXPECTED at its plainest: the host chose the value, the author typed it down.

        `find_repo_root()` answers a question about this checkout, and the list
        on the right of the compare was read off one terminal. Nothing about the
        READER is wrong; what is wrong is writing down what it happened to
        return here. Mutation caught: `"find_repo_root",` deleted from
        MACHINE_ROOT_CALLS, which is the single commonest spelling of the
        species and leaves the arm reporting nothing on this shape.
        """
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
        """ONE HOP, MODULE HALF - a reader that only knew local names calls this clean.

        The root is never spelled inside the unit at all: the unit says `ROOT`
        and the module says what `ROOT` is. This is the same single hop
        `host_state` spends to read a `parametrize` list, and without it the
        commonest way a test file names its own checkout is invisible. Mutation
        caught: `module_scope = _bound_names_in_body(parsed.tree.body)` in
        `find_host_dependent` becoming `module_scope = {}`.
        """
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
        """A LISTING METHOD'S WORLD IS THE THING ON ITS LEFT, not something in its parentheses.

        `Path.cwd().iterdir()` hands production nothing and describes the whole
        machine anyway, so a reader that only inspected call ARGUMENTS would
        call the loudest shape of this species clean. Mutation caught: `if tail
        in LISTING_METHODS and isinstance(call.func, ast.Attribute): return
        [call.func.value]` in `_world_arguments` becoming `... return []`.
        """
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
    """The rule's own evidence, transcribed - and each red row beside its green sibling.

    A standard derived from two measured failures has to be able to reproduce
    them, or the derivation is a story. Both files below are the shape CI ran on
    2026-09-08, and in both of them the SAME file also contains code that gets it
    right - which is what makes each row a defect rather than a style opinion.
    """

    def test_row_one_the_live_fleet_resolver_is_flagged_and_its_tmp_path_sibling_is_not(self, tmp_path):
        """@ai_mail row 1, and the green sibling twelve lines above it in the real file.

        Same resolver, called two ways. The red one calls it with ZERO arguments
        and lets the host answer, then guards itself with `is_dir()` - which is
        TRUE on a clone, because `!projects/README.md` puts the directory there
        empty, so CI walked into the arm expecting four residents. The green one
        passes `tmp_path` and builds the tree it reads. One argument is the whole
        difference and both halves have to be pinned, or a narrowing that
        acquitted the red row would look like a win. Mutation caught:
        `_asserts_in(node.orelse)` in `_both_worlds` becoming `_asserts_in([])`,
        which stops the else arm counting as a second oracle and clears the row
        the rule was written for.
        """
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
        """@daemon row 2: BRANCH_ROOT is a CLASS attribute, and two green siblings prove the shape.

        The root is assigned in the class body and referenced as
        `self.BRANCH_ROOT` in every method under it, so a reader that only knew
        module-level names would have called the red unit clean while it handed
        the live branch root to production. The two siblings carry an existence
        guard and a `pytest.skip`; they read the same machine and step aside
        when it is not theirs, which is `self_skip`'s business and not this
        rule's. Mutation caught: `scope.update(classes.get(unit.class_name,
        {}))` in `unit_scope` becoming `scope.update({})`.
        """
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
    """The difference between a rule and a nuisance - each one a measured false positive.

    The first run of this checker over the fleet produced 41 rows and the
    calibrated run produces 6. Every narrowing below took correct code off that
    list, and every one of them is a line a later edit could delete without any
    other test noticing. These are those tests.
    """

    def test_a_path_rooted_at_tmp_path_is_the_test_s_own_world(self, tmp_path):
        """NAMING AN IGNORED SPELLING ON PURPOSE IS THE CURE, so it must not be the finding.

        A test that builds `tmp_path / "projects" / "ghost"` is modelling the
        directory a clone has and ships nothing; pytest made that directory and
        pytest removes it. If the sandbox reading fails, the rule convicts the
        exact shape its own fix advice produces and there is nothing left to
        recommend. Mutation caught: `if _names_under(spine) & sandbox or
        _rooted_in_a_negated_region(spine, scope):` in `_ignored_path` becoming
        `if _rooted_in_a_negated_region(spine, scope):`.
        """
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
        """NINE ROWS, @spawn AND @memory, and every one of them this single line.

        `project, reg = _make_project(tmp_path, ...)` binds two names off one
        sandbox-rooted call. A reader that only understood a bare `Name` target
        saw `project` appear from nowhere and called a temp directory live host
        state. Unpacking is generous - if any element is the sandbox, all of
        them carry the acquittal - and generous is the safe direction for a rule
        that accuses. Mutation caught: `for child in ast.walk(target):` in
        `_target_names` becoming `for child in [target]:`, which is the
        bare-Name reading that produced those nine rows.
        """
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
        """A NAMED EXCEPTION WITH A REASON, and the reason is what has to survive an edit.

        `temp_test_dir` is not a pytest builtin. It is the fleet's own sandbox -
        `test_dir = tmp_path / "test_workspace"` in this pack's own conftest
        template, copied into branch conftests fleet-wide - and a conftest
        fixture is invisible to this reader by published limit. So the one name
        the whole fleet shares is listed beside the builtins. Measured: 1 @drone
        row. Mutation caught: `"temp_test_dir",` in SANDBOX_SEEDS becoming
        `"temp_test_dir_never",`.
        """
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
        """@memory's test_missing_file_skipped: the world is tmp_path all the way down.

        The unit builds a directory under `tmp_path`, puts its string into a
        dict, and hands that dict to a stand-in it defined three lines earlier.
        The only thing a static reader can see inside the stand-in is a
        parameter name - and a stand-in the test wrote is the test's own scope.
        Mutation caught: `bound |= _nested_parameter_names(unit_node)` in
        `_sandbox_names` becoming `bound |= set()`.
        """
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
        """THE GATE IS THE POINT - the pin above is worthless without this one.

        Spelled as a gate rather than a blanket precisely so that a stand-in
        reading real host state keeps its finding. Same file, same nested `def`,
        same `.trinity` read; the only difference is that the unit never names a
        sandbox, and the path in the dict is a machine path the author typed.
        Without this pin, widening the acquittal into a blanket - which is the
        obvious simplification of the two-line gate - passes every other test in
        this class. Mutation caught: `if _names_under(unit_node) & bound:` in
        `_sandbox_names` becoming `if True:`.
        """
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
        """THE CURE THE RULE TEACHES SECOND: build the tree, then read it.

        A `mkdir` on a path carrying the same ignored segment means the world
        under the assertion is the world the test made, on any machine, whatever
        it is rooted at. Convicting this shape would leave a branch no way to
        please the checker except by deleting the assertion. Mutation caught:
        `if on_receiver and tail in BUILDING_METHODS:` in `_call_role` becoming
        `if on_receiver and tail in set():`, which stops `mkdir`, `write_text`
        and `touch` counting as construction at all.
        """
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
        """THE BUILD IS ROUTINELY ONE FRAME UP, which is where pytest users put it.

        The fixture makes the directory and the unit reads it; neither half is
        wrong and neither half is complete on its own. Read once per FILE rather
        than once per unit, because a rule the audit engine runs on eighteen
        branches cannot afford to re-parse six fixtures for each of a file's
        four hundred units. Mutation caught: `built |= (fixture_built or
        {}).get(name, set())` in `unit_flags` becoming `built |= set()`.
        """
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
        """SIX @ai_mail ROWS, and a single hop would still miss every one of them.

        `hosted_baud` requests `repo_root`, and `repo_root` is the one that
        requests `tmp_path`; the unit then reads `projects/` under a directory
        that is two frames from the sandbox. Declared out of order here on
        purpose - the fixed point must not depend on a fixture being defined
        after the one it uses, which a single ordered pass would. Mutation
        caught: `& (SANDBOX_SEEDS | found)):` in `sandbox_fixtures` becoming `&
        SANDBOX_SEEDS):`, which finds `repo_root` and never reaches
        `hosted_baud`.
        """
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
        """FLAGGING A TEMPLATE PASSPORT IS EXACTLY BACKWARDS - the ignore file re-admits it.

        The root `.gitignore`'s only `!` lines put
        `src/aipass/spawn/templates/*/.trinity/**` back, with a comment saying a
        template must ship WHOLE. A frozen needle list cannot express a
        negation, so the negated REGION is spelled by the root's name instead
        and read one hop through the unit's own assignment. Measured: 7 @spawn
        rows, every one a template passport read. Mutation caught:
        `NEGATED_ROOT_SPELLINGS: tuple = ("template",)` becoming
        `NEGATED_ROOT_SPELLINGS: tuple = ()`.
        """
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
        """ONE DEFECT MUST NOT PRODUCE TWO FINDINGS UNDER TWO STANDARDS.

        A test carrying `pytest.skip` behind an existence check has already
        declared that it reads the host; whether that skip is honest is
        `self_skip`'s question. A fleet that gets two findings for one line
        starts discounting both, and the unit below is otherwise a textbook
        IGNORED_PATH - it reads `.trinity/local.json` off a class-constant
        branch root. Mutation caught: `return bool(calls & SKIP_CALLS) and
        bool(_existence_probe(unit.node))` in `skip_guarded` becoming `return
        bool(calls & set()) and bool(_existence_probe(unit.node))`.
        """
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
        """BARE IS THE WHOLE NARROWING, and this is the half that keeps fixtures legal.

        `Path(__file__).parent / "fixtures" / "sample.json"` is machine-rooted
        and perfectly fresh-clone safe: the repo SHIPS that file, so every
        machine reads the same bytes. What is not safe is handing a DIRECTORY to
        production and pinning what production found in it. Without this clause
        every fixture-file test in the fleet is a DERIVED_EXPECTED row. Mutation
        caught: `if not seed or any(_holds_a_literal(form) for form in forms):`
        in `bare_machine_root` becoming `if not seed:`.
        """
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
        """SEVEN ROWS ACROSS @backup, @commons AND @devpulse, all of them correct code.

        `__file__` alone names the running test file, and the repo ships it by
        definition - it IS the test. Only `.parent`, `.parents` or
        `os.path.dirname` reaches a directory whose contents are this checkout's
        business. `module_file(__file__)` is a resolver handed its own module
        path and runs identically on a clone. Mutation caught: `if
        _climbs_to_a_directory(expr) and any(` in `_machine_root_seed` becoming
        `if any(`.
        """
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
        """FOUR FAMILIES CAME OFF THE FLEET FOR THIS ONE WORD, and it is what makes the species name true.

        Both projects hand the same bare machine root to the same production
        call. The first asserts that two implementations agree - which answers
        the same on every machine, because nobody wrote a machine's answer down.
        The second pins a list read off one terminal. Only the second is a
        DERIVED_EXPECTED, and pinning only the clean half would let a mutation
        that reports nothing at all look like a narrowing. Mutation caught: `if
        any(_is_written_down(side) for side in [child.left,
        *child.comparators]):` in `pins_a_written_expectation` becoming `if
        True:`, which flags the property assertion too.
        """
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
        """ELEVEN CORRECT @ai_mail UNITS, convicted on the first run for a path they never reached.

        The path has to be REACHED on the filesystem - `exists`, `iterdir`,
        `read_text`, `open`, `os.listdir` - not merely spelled. A machine-rooted
        string handed to a PARSER is data being fed to the code under test, and
        the parser is what the test is about. Reading spellings rather than
        reaches is the single largest false-positive family this rule has.
        Mutation caught: `if _role_of(literal, parents, uses) != "read":` in
        `_ignored_path` becoming `if False:`.
        """
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
        """BOTH arms have to assert, or the shape is an ordinary guard and not a second claim.

        A branch whose else arm calls `pytest.fail` states ONE thing: the
        directory must be there. That is a test with one oracle, which is what
        this rule is asking for everywhere else - reporting it would mean the
        rule flags the strict version of its own advice. Mutation caught: `if
        not (_asserts_in(node.body) and _asserts_in(node.orelse)):` in
        `_both_worlds` becoming `if not _asserts_in(node.body):`.
        """
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
        """The number is clean-over-total, counted per unit, and six acquittals hold it up.

        Two of the eight units are the rows CI went red on; the other six are
        clean for six DIFFERENT reasons, so a mutation that collapses any single
        acquittal moves this number and cannot hide behind the other five. An
        inverted numerator still moves plausibly with a tree, which is why the
        pin carries the sentence a reader gets as well as the number. Mutation
        caught: `score = int(((total - len(flagged)) / total) * 100)` becoming
        `score = int((len(flagged) / total) * 100)`, which reports 25 where the
        honest answer is 75.
        """
        result = fresh_clone_check.check_branch(str(_fresh_clone_project(tmp_path)))

        assert result["score"] == 75
        assert len(result["violations"]) == 2
        assert (
            "2/8 test units take their answer from state a fresh clone does not have" in result["checks"][0]["message"]
        )

    def test_a_project_whose_every_unit_builds_its_own_world_scores_one_hundred(self, tmp_path):
        """A CLEAN PROJECT HAS TO SAY SO IN ITS OWN WORDS, not merely produce no rows.

        Zero rows and a 100 are the easy half; the sentence is the half a reader
        actually sees on a board, and a check that printed the flagged wording
        with an empty list after it would read as a broken rule rather than a
        clean project. All six clone-safe shapes are here at once, which is also
        the only place any of them is asserted in the company of the others.
        Mutation caught: the message ternary's `if not flagged` becoming `if
        flagged`, which prints "0/6 test units take their answer from state a
        fresh clone does not have: " over a project that has none.
        """
        result = fresh_clone_check.check_branch(str(_clone_safe_project(tmp_path)))

        assert result["violations"] == []
        assert result["score"] == 100
        assert result["checks"][0]["passed"] is True
        assert result["checks"][0]["message"] == "6/6 test units read only what the repo ships"

    def test_a_unit_carrying_two_species_is_one_row_and_two_units_carrying_one_each_are_two(self, tmp_path):
        """A SCORE THAT CAN GO NEGATIVE IS ONE NOBODY BELIEVES TWICE.

        The first project holds ONE unit that branches on the machine AND pins a
        written-down value off a bare root - both species, one place for a
        reader to go and look. The second project splits those same two shapes
        across two units. One row against two is the whole claim, and the second
        project is what stops a mutation that simply reports less from passing
        as the per-unit rule. Mutation caught: `if row["nodeid"] not in seen:`
        in `find_host_dependent` becoming `if True:`, which returns two rows for
        the single unit and would let one path-heavy test drive a project below
        zero.
        """
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
        """A REPORT IS NOT A VERDICT - this rule nominates and a human decides.

        Top-level `passed` must stay True while flags exist and `advisory` must
        stay True, so a caller can tell the two apart; the standard name and the
        violations list are the rest of the contract every rule in this pack
        answers. A flagged site may be perfectly safe for a reason this checker
        cannot see - a project that ships the directory anyway, a CI stage that
        populates it first - which is exactly why it must not fail a board.
        Mutation caught: `"passed": True,` becoming `"passed": not flagged,` in
        the scored return, which turns an advisory into a board failure on every
        branch that has one of these sites.
        """
        result = fresh_clone_check.check_branch(str(_fresh_clone_project(tmp_path)))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "FRESH_CLONE"
        assert result["checks"][0]["name"] == "Fresh clone survivable"
        assert result["checks"][0]["passed"] is False
        assert sorted(result) == ["advisory", "checks", "passed", "score", "standard", "violations"]

    def test_a_project_with_no_test_files_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND.

        A 0 blames a project for a fact about its layout and a 100 claims a
        measurement that never happened. Each check in this pack carries its own
        copy of the early return, so each one has to be pinned - and losing it
        here does not return a wrong number, it divides by zero and takes the
        caller with it. Mutation caught: `"not_applicable": True,` becoming
        `"not_applicable": False,` in the `total == 0` return.
        """
        _write(tmp_path, "apps/registry.py", "def find_repo_root():\n    return Path.cwd()")

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert result["score"] == 0
        assert "no test files found" in result["checks"][0]["message"]

    def test_an_unparseable_test_file_is_named_beside_a_scored_result(self, tmp_path):
        """AN UNREAD FILE FLAGS NOTHING, so for THIS rule silence biases toward clean.

        The early-return path carries the unreadable line by construction; the
        scored path has to append it deliberately, and dropping that one line
        leaves a branch with a healthy number and no hint that a file was never
        read at all. The message has to say NOT measured, not merely name the
        file. Mutation caught: `checks.extend(unreadable)` becoming
        `checks.extend([])`.
        """
        _fresh_clone_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = fresh_clone_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["score"] == 75
        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
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
