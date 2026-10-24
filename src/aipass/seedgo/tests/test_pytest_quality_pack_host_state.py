# =================== AIPass ====================
# Name: test_pytest_quality_pack_host_state.py
# Description: pytest_quality pack, host_state checker pins (split from test_pytest_quality_pack.py)
# Version: 1.0.1
# Created: 2026-10-08
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/host_state_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, pytest_quality_standards/host_state_content.py

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.pytest_quality_standards import host_state_check
from aipass.seedgo.tests.support_pytest_quality_pack import _line_of, _write


# Every project here is source text in tmp_path: no environment, cwd, process or file outside the fixture is touched.


def _effectful_module(root: Path, verbs: str) -> Path:
    """The production half of the incident: systemctl AND a published verb set."""
    return _write(
        root,
        "apps/timer_install.py",
        f"""
        HANDLED_COMMANDS = ({verbs},)


        def _run_systemctl(*args):
            command = ["systemctl", "--user", *args]
            return subprocess.run(command, check=False)


        def main():
            _run_systemctl("stop", "daemon-tick.timer")
        """,
    )


def _host_state_project(root: Path) -> Path:
    """A six-unit project where exactly two units leave the machine changed."""
    _effectful_module(root, '"install-timer", "uninstall-timer", "timer-status"')
    _write(
        root,
        "tests/test_cli_routing.py",
        """
        GATED_VERBS = ["uninstall-timer", "help"]
        TIMER_SEAM = "apps.timer_install.subprocess.run"


        @pytest.mark.parametrize("verb", GATED_VERBS)
        def test_a_stray_positional_is_refused(verb):
            with patch.object(sys, "argv", ["daemon", verb, "not_a_real_subarg"]):
                with pytest.raises(SystemExit):
                    _daemon_mod.main()


        def test_the_timer_is_stopped_before_the_state_is_read():
            subprocess.run(["systemctl", "--user", "stop", "daemon-tick.timer"])
            assert read_state() == "stopped"


        def test_the_router_refuses_an_unknown_subcommand():
            with patch("apps.timer_install.subprocess.run") as runner:
                with patch.object(sys, "argv", ["daemon", "install-timer", "junk"]):
                    with pytest.raises(SystemExit):
                        _daemon_mod.main()
            assert not runner.called


        def test_the_seam_named_by_a_constant_is_patched():
            with patch(TIMER_SEAM) as runner:
                with patch.object(sys, "argv", ["daemon", "uninstall-timer"]):
                    _daemon_mod.main()
            assert runner.called


        def test_the_branch_is_read_from_the_environment(monkeypatch):
            monkeypatch.setenv("AIPASS_BRANCH", "daemon")
            assert read_branch() == "daemon"


        def test_the_real_config_is_snapshotted_into_the_fixture(tmp_path):
            config = Path.home() / ".config" / "daemon.json"
            snapshot = tmp_path / config.name
            snapshot.write_text("{}")
            assert snapshot.is_file()
        """,
    )
    return root


class TestHostStateDetection:
    """The six species, and the incident that is the whole reason for the sixth."""

    def test_a_verb_production_made_effectful_driven_through_an_entry_point_is_flagged(self, tmp_path):
        """THE INCIDENT SHAPE, both halves written out, and the reason this rule exists."""
        _write(
            tmp_path,
            "apps/timer_install.py",
            """
            HANDLED_COMMANDS = ("install-timer", "uninstall-timer", "timer-status")


            def _run_systemctl(*args):
                command = ["systemctl", "--user", *args]
                return subprocess.run(command, check=False)


            def main():
                _run_systemctl("stop", "daemon-tick.timer")
            """,
        )
        _write(
            tmp_path,
            "tests/test_cli_routing.py",
            """
            def test_a_stray_positional_is_refused():
                with patch.object(sys, "argv", ["daemon", "uninstall-timer", "not_a_real_subarg"]):
                    with pytest.raises(SystemExit):
                        _daemon_mod.main()
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))
        row = result["violations"][0]

        assert [r["species"] for r in result["violations"]] == ["EFFECTFUL_VERB"]
        assert row["nodeid"] == "tests/test_cli_routing.py::test_a_stray_positional_is_refused"
        assert "'uninstall-timer'" in row["detail"]
        assert "apps/timer_install.py" in row["detail"]
        assert "systemctl" in row["detail"]

    def test_a_verb_reached_only_through_a_parametrized_module_list_is_flagged(self, tmp_path):
        """ONE HOP, FIRST HALF: the verb in the incident is not in the unit at all."""
        _effectful_module(tmp_path, '"uninstall-timer"')
        _write(
            tmp_path,
            "tests/test_cli_routing.py",
            """
            GATED_VERBS = ["uninstall-timer", "help"]


            @pytest.mark.parametrize("verb", GATED_VERBS)
            def test_a_stray_positional_is_refused(verb):
                with patch.object(sys, "argv", ["daemon", verb, "not_a_real_subarg"]):
                    with pytest.raises(SystemExit):
                        _daemon_mod.main()
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert [row["nodeid"] for row in result["violations"]] == [
            "tests/test_cli_routing.py::test_a_stray_positional_is_refused"
        ]
        assert "'uninstall-timer'" in result["violations"][0]["detail"]

    def test_a_verb_reached_by_a_loop_over_the_same_list_inside_the_unit_is_flagged(self, tmp_path):
        """ONE HOP, SECOND HALF: a reader that walked only decorators calls this clean."""
        _effectful_module(tmp_path, '"uninstall-timer"')
        _write(
            tmp_path,
            "tests/test_cli_routing.py",
            """
            GATED_VERBS = ["uninstall-timer", "help"]


            def test_help_outranks_the_gate():
                for verb in GATED_VERBS:
                    with patch.object(sys, "argv", ["daemon", verb, "--help"]):
                        with pytest.raises(SystemExit):
                            _daemon_mod.main()
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert [row["nodeid"] for row in result["violations"]] == [
            "tests/test_cli_routing.py::test_help_outranks_the_gate"
        ]
        assert "'uninstall-timer'" in result["violations"][0]["detail"]

    def test_the_dangerous_verbs_follow_a_rename_in_production(self, tmp_path):
        """DERIVED, NEVER LISTED - and this is the pin that stops a roster being added."""
        driver = """
            def test_the_old_name_is_refused():
                with patch.object(sys, "argv", ["daemon", "uninstall-timer", "junk"]):
                    with pytest.raises(SystemExit):
                        _daemon_mod.main()


            def test_the_new_name_is_refused():
                with patch.object(sys, "argv", ["daemon", "retire-timer", "junk"]):
                    with pytest.raises(SystemExit):
                        _daemon_mod.main()
            """
        before, after = tmp_path / "before", tmp_path / "after"
        for root, verbs in ((before, '"uninstall-timer"'), (after, '"retire-timer"')):
            _effectful_module(root, verbs)
            _write(root, "tests/test_cli_routing.py", driver)

        flagged_before = host_state_check.check_branch(str(before))["violations"]
        flagged_after = host_state_check.check_branch(str(after))["violations"]

        assert [row["nodeid"] for row in flagged_before] == ["tests/test_cli_routing.py::test_the_old_name_is_refused"]
        assert [row["nodeid"] for row in flagged_after] == ["tests/test_cli_routing.py::test_the_new_name_is_refused"]

    def test_a_subprocess_driving_a_service_manager_is_flagged(self, tmp_path):
        """SERVICE_CONTROL: the species the incident is made of, seen directly."""
        _write(
            tmp_path,
            "tests/test_timer.py",
            """
            def test_the_timer_is_stopped():
                subprocess.run(["systemctl", "--user", "stop", "daemon-tick.timer"])
                assert read_state() == "stopped"
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["SERVICE_CONTROL"]
        assert "runs systemctl through subprocess.run" in result["violations"][0]["detail"]

    def test_a_signal_sent_to_a_process_the_unit_did_not_start_is_flagged(self, tmp_path):
        """PROCESS_SIGNAL: a signalled process is not put back by a finally clause."""
        _write(
            tmp_path,
            "tests/test_lock.py",
            """
            def test_the_stale_holder_is_signalled():
                os.kill(pid_from_the_lockfile, signal.SIGTERM)
                assert lock.is_free()
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["PROCESS_SIGNAL"]
        assert result["violations"][0]["nodeid"] == "tests/test_lock.py::test_the_stale_holder_is_signalled"

    def test_a_write_under_the_real_home_directory_is_flagged(self, tmp_path):
        """HOME_WRITE: a config file overwritten in the user's own home stays overwritten."""
        _write(
            tmp_path,
            "tests/test_config.py",
            """
            def test_the_config_is_written():
                (Path.home() / ".config" / "daemon.json").write_text("{}")
                assert load_config() == {}
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["HOME_WRITE"]
        assert result["violations"][0]["nodeid"] == "tests/test_config.py::test_the_config_is_written"

    def test_an_assignment_into_os_environ_is_flagged(self, tmp_path):
        """ENV_MUTATION: the interpreter's environment is process-wide."""
        _write(
            tmp_path,
            "tests/test_env.py",
            """
            def test_the_branch_is_read_from_the_environment():
                os.environ["AIPASS_BRANCH"] = "daemon"
                assert read_branch() == "daemon"
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["ENV_MUTATION"]
        assert "monkeypatch.setenv is restored for you" in result["violations"][0]["detail"]

    @pytest.mark.parametrize("decoy", ["snapshot = dict(os.environ)", 'patch("app.config.environment_name")'])
    def test_a_builtin_call_or_a_longer_name_does_not_patch_os_environ(self, tmp_path, decoy):
        _write(
            tmp_path,
            "tests/test_env.py",
            f"""
            def test_the_branch_is_read_from_the_environment():
                {decoy}
                os.environ["AIPASS_BRANCH"] = "daemon"
                assert read_branch() == "daemon"
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["ENV_MUTATION"]

    def test_a_raw_chdir_with_no_restore_is_flagged(self, tmp_path):
        """CWD_CHANGE: os.chdir moves the whole process, not this test."""
        _write(
            tmp_path,
            "tests/test_root.py",
            """
            def test_the_registry_is_found_from_the_repo_root():
                os.chdir(repo_root)
                assert Path("registry.json").is_file()
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["CWD_CHANGE"]
        assert "monkeypatch.chdir is restored for you" in result["violations"][0]["detail"]

    def test_a_fixture_that_reaches_host_state_and_yields_nothing_after_it_is_flagged(self, tmp_path):
        """FIXTURE_NO_TEARDOWN: the setup landed and the teardown never did."""
        _write(
            tmp_path,
            "tests/test_timer.py",
            """
            @pytest.fixture
            def stopped_timer():
                subprocess.run(["systemctl", "--user", "stop", "daemon-tick.timer"])
                yield


            def test_the_state_reads_stopped(stopped_timer):
                assert read_state() == "stopped"
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert [row["nodeid"] for row in result["violations"]] == ["tests/test_timer.py::stopped_timer"]
        assert result["violations"][0]["species"] == "FIXTURE_NO_TEARDOWN"
        assert "SERVICE_CONTROL" in result["violations"][0]["detail"]

    def test_a_unit_carrying_three_species_is_reported_as_one_row(self, tmp_path):
        """ONE ROW PER UNIT: three species is one unit a reader has to go and read."""
        _write(
            tmp_path,
            "tests/test_many.py",
            """
            def test_three_species_in_one_unit():
                os.chdir(repo_root)
                os.environ["AIPASS_BRANCH"] = "daemon"
                subprocess.run(["systemctl", "--user", "stop", "daemon-tick.timer"])
                assert read_state() == "stopped"


            def test_one_clean_unit(monkeypatch):
                monkeypatch.setenv("AIPASS_BRANCH", "daemon")
                assert read_branch() == "daemon"
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))
        flagged = [row["nodeid"] for row in result["violations"]]

        assert flagged == ["tests/test_many.py::test_three_species_in_one_unit"]
        assert result["score"] == 50

    def test_a_runtime_assembled_argv_is_not_read_at_all(self, tmp_path):
        """A LIMIT PINNED AS A LIMIT, so nobody fixes the blind spot into a guess."""
        _write(
            tmp_path,
            "tests/test_timer.py",
            """
            def test_the_timer_is_stopped():
                command = ["systemctl", "--user", "stop", "daemon-tick.timer"]
                subprocess.run(command)
                assert read_state() == "stopped"
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_module_that_publishes_verbs_and_reaches_nothing_makes_none_of_them_dangerous(self, tmp_path):
        """The other half of the derivation: an ordinary CLI is not a service manager."""
        _write(
            tmp_path,
            "apps/cli.py",
            """
            HANDLED_COMMANDS = ("uninstall-timer", "status")


            def main():
                return route(sys.argv[1:])
            """,
        )
        _write(
            tmp_path,
            "tests/test_cli_routing.py",
            """
            def test_a_stray_positional_is_refused():
                with patch.object(sys, "argv", ["daemon", "uninstall-timer", "junk"]):
                    with pytest.raises(SystemExit):
                        _daemon_mod.main()
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100


class TestHostStateAcquittals:
    """The difference between a rule and a nuisance - each one a measured false positive."""

    def test_a_seam_patched_by_a_string_literal_acquits_the_verb(self, tmp_path):
        """TOUCHING THE REAL THING IS ALLOWED - reaching a patched seam is not touching it."""
        _effectful_module(tmp_path, '"uninstall-timer"')
        _write(
            tmp_path,
            "tests/test_cli_routing.py",
            """
            def test_the_router_refuses_an_unknown_subcommand():
                with patch("apps.timer_install.subprocess.run") as runner:
                    with patch.object(sys, "argv", ["daemon", "uninstall-timer", "junk"]):
                        with pytest.raises(SystemExit):
                            _daemon_mod.main()
                assert not runner.called
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_patch_target_held_in_a_module_level_constant_acquits_the_verb(self, tmp_path):
        """THE ONE HOP ON THE ACQUITTAL SIDE, and a rule that lacked it gave bad advice."""
        _effectful_module(tmp_path, '"uninstall-timer"')
        _write(
            tmp_path,
            "tests/test_cli_routing.py",
            """
            TIMER_SEAM = "apps.timer_install.subprocess.run"


            def test_the_router_refuses_an_unknown_subcommand():
                with patch(TIMER_SEAM) as runner:
                    with patch.object(sys, "argv", ["daemon", "uninstall-timer", "junk"]):
                        with pytest.raises(SystemExit):
                            _daemon_mod.main()
                assert not runner.called
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_monkeypatch_setenv_and_delenv_are_never_a_finding(self, tmp_path):
        """USING THEM IS THE CURE, so flagging them would convict the fix itself."""
        _write(
            tmp_path,
            "tests/test_env.py",
            """
            def test_the_branch_is_read_from_the_environment(monkeypatch):
                monkeypatch.setenv("AIPASS_BRANCH", "daemon")
                monkeypatch.delenv("AIPASS_ROOT", raising=False)
                assert read_branch() == "daemon"
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_monkeypatch_chdir_acquits_a_raw_chdir_deeper_in_the_same_unit(self, tmp_path):
        """A STATEMENT ABOUT HOW MONKEYPATCH WORKS, not a convenience."""
        _write(
            tmp_path,
            "tests/test_registry.py",
            """
            def test_the_registry_file_is_found(tmp_path, monkeypatch):
                monkeypatch.chdir(tmp_path)
                os.chdir(tmp_path / "nested")
                assert Path("registry.json").is_file()
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_path_under_tmp_path_is_not_host_state(self, tmp_path):
        """A write to a directory pytest created and removes is not the host."""
        _write(
            tmp_path,
            "tests/test_config.py",
            """
            def test_the_real_config_is_snapshotted_into_the_fixture(tmp_path):
                config = Path.home() / ".config" / "daemon.json"
                snapshot = tmp_path / config.name
                snapshot.write_text("{}")
                assert snapshot.is_file()
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_same_file_fixture_restoring_os_environ_acquits_the_units_that_request_it(self, tmp_path):
        """THE PYTEST IDIOM: a bare yield then a restore, and it must not be flagged twice."""
        _write(
            tmp_path,
            "tests/test_identity.py",
            """
            @pytest.fixture
            def clean_env():
                saved = os.environ.pop("AIPASS_BRANCH", None)
                yield
                os.environ["AIPASS_BRANCH"] = saved or ""


            def test_the_branch_is_read_from_the_environment(clean_env):
                os.environ["AIPASS_BRANCH"] = "daemon"
                assert read_branch() == "daemon"
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_same_file_fixture_calling_monkeypatch_chdir_acquits_the_units_that_request_it(self, tmp_path):
        """@drone's lock_dir, which is correct code and was one row on the first run."""
        _write(
            tmp_path,
            "tests/test_registry.py",
            """
            @pytest.fixture
            def lock_dir(tmp_path, monkeypatch):
                monkeypatch.chdir(tmp_path)
                return tmp_path


            def test_the_registry_file_is_found(lock_dir):
                os.chdir(lock_dir / "nested")
                assert Path("registry.json").is_file()
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_an_env_change_guarded_by_its_own_finally_is_not_the_row(self, tmp_path):
        """The cure written inline: the guarded mutation is not what gets reported."""
        path = _write(
            tmp_path,
            "tests/test_env.py",
            """
            def test_the_branch_is_read_from_the_environment():
                try:
                    os.environ["AIPASS_BRANCH"] = "daemon"
                    assert read_branch() == "daemon"
                finally:
                    del os.environ["AIPASS_BRANCH"]
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))
        reported = [row["line"] for row in result["violations"]]

        assert _line_of(path, '        os.environ["AIPASS_BRANCH"] = "daemon"') not in reported

    def test_a_cwd_change_guarded_by_its_own_finally_is_not_the_row(self, tmp_path):
        """The same acquittal for the working directory, and it needs its own pin."""
        path = _write(
            tmp_path,
            "tests/test_root.py",
            """
            def test_the_registry_is_found_from_the_repo_root():
                origin = os.getcwd()
                try:
                    os.chdir(repo_root)
                    assert Path("registry.json").is_file()
                finally:
                    os.chdir(origin)
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))
        reported = [row["line"] for row in result["violations"]]

        assert _line_of(path, "        os.chdir(repo_root)") not in reported

    def test_the_restoring_statement_in_the_finally_is_not_itself_a_row(self, tmp_path):
        """THE RULE MUST NOT CONVICT THE CURE ITS OWN RULE TEXT TEACHES."""
        _write(
            tmp_path,
            "tests/test_env.py",
            """
            def test_the_branch_is_read_from_the_environment():
                try:
                    os.environ["AIPASS_BRANCH"] = "daemon"
                    assert read_branch() == "daemon"
                finally:
                    del os.environ["AIPASS_BRANCH"]


            def test_the_registry_is_found_from_the_repo_root():
                origin = os.getcwd()
                try:
                    os.chdir(repo_root)
                    assert Path("registry.json").is_file()
                finally:
                    os.chdir(origin)
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_finally_that_puts_nothing_back_does_not_acquit_the_change(self, tmp_path):
        """THE ACQUITTAL IS THE RESTORE, NEVER THE KEYWORD."""
        path = _write(
            tmp_path,
            "tests/test_env.py",
            """
            def test_the_branch_is_read_from_the_environment():
                try:
                    os.environ["AIPASS_BRANCH"] = "daemon"
                    assert read_branch() == "daemon"
                finally:
                    logger.info("done")
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["ENV_MUTATION"]
        assert [row["line"] for row in result["violations"]] == [
            _line_of(path, '        os.environ["AIPASS_BRANCH"] = "daemon"')
        ]

    def test_the_finally_acquittal_does_not_reach_a_service_control(self, tmp_path):
        """DELIBERATELY NOT GENERAL: environment and working directory, and nothing else."""
        path = _write(
            tmp_path,
            "tests/test_timer.py",
            """
            def test_the_state_reads_stopped():
                try:
                    subprocess.run(["systemctl", "--user", "stop", "daemon-tick.timer"])
                    assert read_state() == "stopped"
                finally:
                    subprocess.run(["systemctl", "--user", "start", "daemon-tick.timer"])
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))
        reported = [row["line"] for row in result["violations"]]

        assert [row["species"] for row in result["violations"]] == ["SERVICE_CONTROL"]
        assert reported == [_line_of(path, '        subprocess.run(["systemctl", "--user", "stop"')]
        assert result["score"] == 0


class TestHostStateBranchCheck:
    """The scoring-API contract, and the two paths where silence reads as clean."""

    def test_the_score_is_the_share_of_units_that_leave_the_machine_as_they_found_it(self, tmp_path):
        """The number is clean-over-total, counted per unit, and four acquittals hold it up."""
        result = host_state_check.check_branch(str(_host_state_project(tmp_path)))

        assert result["score"] == 66
        assert len(result["violations"]) == 2
        assert (
            "2/6 test units and fixtures change live host state with no visible restore"
            in result["checks"][0]["message"]
        )

    def test_fixtures_are_counted_in_the_denominator_that_scores_them(self, tmp_path):
        """A SCORE THAT CAN GO NEGATIVE IS ONE NOBODY BELIEVES TWICE."""
        _write(
            tmp_path,
            "tests/test_fixtures.py",
            """
            @pytest.fixture
            def stopped_timer():
                subprocess.run(["systemctl", "--user", "stop", "daemon-tick.timer"])
                yield


            @pytest.fixture
            def moved_home():
                os.chdir("/tmp")
                yield


            def test_the_state_reads_stopped(stopped_timer):
                assert read_state() == "stopped"
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert len(result["violations"]) == 2
        assert result["score"] == 33
        assert "2/3 test units and fixtures" in result["checks"][0]["message"]

    def test_the_result_passes_and_stays_advisory_even_when_units_are_flagged(self, tmp_path):
        """SHADOW MODE GATES NOTHING - this rule scores before it is calibrated."""
        result = host_state_check.check_branch(str(_host_state_project(tmp_path)))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "HOST_STATE"
        assert result["checks"][0]["passed"] is False

    def test_a_project_with_no_test_files_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND."""
        _effectful_module(tmp_path, '"uninstall-timer"')

        result = host_state_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A broken file must never read as an absent one - the ordering pin."""
        _effectful_module(tmp_path, '"uninstall-timer"')
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = host_state_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_broken.py" in check["message"] for check in result["checks"])

    def test_an_unparseable_test_file_is_named_beside_a_scored_result(self, tmp_path):
        """The unreadable line must also survive onto the path that DOES score."""
        _host_state_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = host_state_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["score"] == 66
        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]
