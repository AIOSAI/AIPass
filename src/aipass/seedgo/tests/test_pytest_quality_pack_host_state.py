# =================== AIPass ====================
# Name: test_pytest_quality_pack_host_state.py
# Description: pytest_quality pack, host_state checker pins (split from test_pytest_quality_pack.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/host_state_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, pytest_quality_standards/host_state_content.py

from pathlib import Path

from aipass.seedgo.apps.handlers.pytest_quality_standards import host_state_check
from aipass.seedgo.tests.support_pytest_quality_pack import _line_of, _write

# =============================================================================
# HOST STATE - DID THE TEST PUT THE MACHINE BACK
# =============================================================================

# NOTHING IN THIS SECTION TOUCHES HOST STATE, and the rule under test is why that
# has to be written down rather than assumed. A pin for a checker about services,
# signals, os.environ and the working directory is the one place in this file
# where a real `os.environ[...] = ...`, a real `os.chdir` or a real subprocess
# would read as ordinary setup. There is none: every project below is source TEXT
# written into tmp_path, and every assertion is about what the CHECKER reported
# over that text. No environment variable is set, no directory is entered, no
# process is signalled and nothing is written outside the fixture directory -
# a pin for this rule that broke this rule would be the joke telling itself.


def _effectful_module(root: Path, verbs: str) -> Path:
    """The production half of the incident: systemctl AND a published verb set.

    BOTH HALVES ARE THE DERIVATION, and that is why they are written together: a
    module that drives a service manager gives a reader no verb to look for
    unless it also publishes one, and a module full of verbs that touches
    nothing is an ordinary CLI. `verbs` is interpolated into the constant so a
    test can rename them and watch the finding follow the rename.
    """
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
    """A six-unit project where exactly two units leave the machine changed.

    The four clean units are clean for four DIFFERENT reasons - a seam patched
    by a literal, a seam patched through a module-level constant, monkeypatch,
    and a path under tmp_path - so no single acquittal carries the whole 66 and
    collapsing any one of them moves the number.
    """
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
    """The six species, and the incident that is the whole reason for the sixth.

    Each test names the one-line mutation of `host_state_check` it was confirmed
    RED against, so a later reader can check the pin still bites rather than
    trusting that it once did.
    """

    def test_a_verb_production_made_effectful_driven_through_an_entry_point_is_flagged(self, tmp_path):
        """THE INCIDENT SHAPE, both halves written out, and the reason this rule exists.

        No AST reader can follow `main()` into `systemctl` - that is an
        interpreter, not a reader - so the dangerous verbs are DERIVED from the
        branch's own production: a module that reaches host control and also
        publishes a HANDLED_COMMANDS-style constant makes those verbs
        host-effectful. A unit that feeds one to a real entry point with nothing
        patched on the seam is the site that stopped daemon-tick.timer for
        twenty-three hours, and the finding has to name the module that made the
        verb dangerous or a reader cannot triage it. Mutation caught: `"main"`
        deleted from ENTRY_POINT_CALLS, which acquits the exact shape the rule
        was written for and leaves the other five species looking healthy.
        """
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
        """ONE HOP, FIRST HALF: the verb in the incident is not in the unit at all.

        `TestUnknownArgumentIsRefused` parametrises over a module-level
        GATED_VERBS list, so a rule reading only the unit's own literals would
        have missed the very site it was written for. The list here also holds a
        verb production never declared, so the resolution has to pick the
        dangerous one rather than flag on the presence of a list. Mutation
        caught: `if isinstance(child, ast.Name) and child.id in
        module_collections:` becoming `... child.id in {}:`, which resolves no
        name and reports nothing.
        """
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
        """ONE HOP, SECOND HALF: a reader that walked only decorators calls this clean.

        The same file that parametrises over GATED_VERBS also loops over it
        inside a unit body, driving the same verbs through the same `main()`,
        and both halves were needed for the real site. The `--help` in the argv
        is not an acquittal either: it only saves the machine if production's
        help gate fires before the work does, and relying on a guard inside
        production is precisely the reliance that failed here. Mutation caught:
        `for scope in [*unit.node.decorator_list, unit.node]:` becoming `for
        scope in [*unit.node.decorator_list]:` - which leaves the parametrized
        pin above green and this one red.
        """
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
        """DERIVED, NEVER LISTED - and this is the pin that stops a roster being added.

        One test file drives two verb spellings; two projects declare one each.
        A hardcoded list of verb names would keep flagging the old spelling
        after a branch renamed it and would never flag the new one - stale, and
        stale in the silent direction. Mutation caught: `for verb in
        _declared_verbs(tree):` becoming `for verb in ("uninstall-timer",):`,
        which keeps flagging the old spelling in the after project and never
        flags the new one - stale, and silent about it.
        """
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
        """SERVICE_CONTROL: the species the incident is made of, seen directly.

        A test that stops a timer and walks away has changed what the machine is
        DOING, not what it contains, and no later test in the session puts it
        back. Mutation caught: `return program if program in
        HOST_CONTROL_BINARIES else ""` in `_argv_binary` becoming `return ""`,
        which reads every argv and recognises no program in any of them.
        """
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
        """PROCESS_SIGNAL: a signalled process is not put back by a finally clause.

        Narrow on purpose - `os.kill`, `os.killpg`, `signal.raise_signal` and
        nothing else, because `handle.terminate()` on a Popen the unit itself
        opened is correct teardown and telling the two apart needs the receiver.
        Mutation caught: `"os.kill"` deleted from the SIGNAL_CALLS frozenset,
        which leaves the commonest spelling of the species unread.
        """
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
        """HOME_WRITE: a config file overwritten in the user's own home stays overwritten.

        The destination roots at `Path.home()`, so this is the user's real
        `.config`, not a fixture directory, and nothing in the unit puts the
        previous contents back. Mutation caught: `"write_text",` in
        MUTATING_PATH_METHODS becoming `"write_text_never",` - the roster losing
        the single commonest way a test writes a file at all.
        """
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
        """ENV_MUTATION: the interpreter's environment is process-wide.

        A variable set here outlives the unit and every later test in the
        session sees it, which is how a suite acquires an order dependency
        nobody can find. Assignment is found STRUCTURALLY because
        `os.environ["X"] = "y"` has no call in it to read by name. Mutation
        caught: `_env_touch`'s Assign arm - `return "assignment into os.environ"
        if _subscripts_environ(node.targets) else ""` - becoming `return ""`.
        """
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

    def test_a_raw_chdir_with_no_restore_is_flagged(self, tmp_path):
        """CWD_CHANGE: os.chdir moves the whole process, not this test.

        A later test resolving a relative path lands somewhere else, and the
        failure surfaces in a unit that has nothing to do with this one.
        Mutation caught: `corpus.dotted_name(node.func) != "os.chdir"` in
        `_cwd_change` becoming `!= "os.chdir_never"`, which reads every call and
        matches none.
        """
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
        """FIXTURE_NO_TEARDOWN: the setup landed and the teardown never did.

        A fixture is the RIGHT place to touch the host - it is the one place a
        restore runs for a failing test too - so the half-built version is worth
        its own species, and it is reported under the fixture's own nodeid
        because that is where a reader has to go. Mutation caught: `if not
        reached or _teardown_after_yield(node): continue` becoming `if not
        reached or not _teardown_after_yield(node): continue`, which reports
        every correctly restoring fixture and nothing else.
        """
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
        """ONE ROW PER UNIT: three species is one unit a reader has to go and read.

        Counting findings instead of units would let a single test drive a
        project's score below zero, and a score that can go negative is one
        nobody believes twice. Mutation caught: `if row["nodeid"] not in seen:`
        in `find_unrestored` becoming `if True:`, which reports the same unit
        three times and takes this two-unit project to -50.
        """
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
        """A LIMIT PINNED AS A LIMIT, so nobody fixes the blind spot into a guess.

        Only a literal first element - or the first word of a literal command
        string - is evidence of which binary runs. The list here is assembled
        into a name first, so the checker says nothing, and that silence is the
        published contract rather than an oversight. Reading the whole unit for
        stray literals the way `_control_binary_anywhere` reads production would
        flag any test that merely MENTIONS systemctl in an assertion. Mutation
        caught: `program = _argv_binary(node)` in `_service_control` becoming
        `program = _argv_binary(node) or _control_binary_anywhere(unit.node)`.
        """
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
        """The other half of the derivation: an ordinary CLI is not a service manager.

        Every branch in the fleet publishes a COMMANDS-style constant and nearly
        every branch has a routing test that drives one of those verbs through
        `main()`. If publication alone made a verb dangerous, this rule would
        convict all of them and be switched off inside a week. Mutation caught:
        `program = _module_reaches_host_control(tree)` in `host_effectful_verbs`
        becoming `program = _module_reaches_host_control(tree) or "systemctl"`,
        which derives verbs from a module that touches nothing.
        """
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
    """The difference between a rule and a nuisance - each one a measured false positive.

    Every acquittal below was added because the rule convicted correct code on a
    real fleet run, and every one of them is a line a later edit could delete
    without any test noticing. These are those tests.
    """

    def test_a_seam_patched_by_a_string_literal_acquits_the_verb(self, tmp_path):
        """TOUCHING THE REAL THING IS ALLOWED - reaching a patched seam is not touching it.

        This is the cure the rule teaches first: patch the module that does the
        work, and the refusal under test is actually proven rather than merely
        survived. If the cure does not acquit, the rule has nothing to recommend
        and every routing test in the fleet stays flagged forever. Mutation
        caught: `if needle and needle in target:` in `_seam_is_patched` becoming
        `if needle and needle == target:`, which only ever matches a patch
        target spelled as the bare module stem.
        """
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
        """THE ONE HOP ON THE ACQUITTAL SIDE, and a rule that lacked it gave bad advice.

        @daemon wrote its cure with the seam in a module-level constant, and the
        literal-only reading kept flagging all three of its cured sites - which
        told an owner to inline a constant they had every reason to keep. A rule
        that pushes a branch into worse code to please the checker is the v4
        behaviour this pack exists to correct. Mutation caught: `if text in
        known:` in `patched_targets` becoming `if text in ():`, which leaves the
        bare name TIMER_SEAM as the only patched target and matches no needle.
        """
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
        """USING THEM IS THE CURE, so flagging them would convict the fix itself.

        pytest restores a monkeypatched environment at teardown by contract, on
        every path including the failing one - which is exactly what the finding
        for a raw assignment tells the author to go and do. Mutation caught:
        `if dotted == "os.putenv":` in `_env_touch` becoming `if dotted in
        ("os.putenv", "monkeypatch.setenv", "monkeypatch.delenv"):`, the
        plausible edit of someone widening the roster by spelling rather than by
        meaning.
        """
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
        """A STATEMENT ABOUT HOW MONKEYPATCH WORKS, not a convenience.

        `monkeypatch.chdir` records the working directory at the moment it is
        called and restores THAT at teardown, so a raw `os.chdir` deeper into
        the same tree is undone with it. Reading the second call on its own
        convicts correct code, and the author's only way to please the checker
        would be to delete a line that changes nothing. Mutation caught:
        `_cwd_change`'s early return comparing against `"monkeypatch.chdir"`
        becoming `"monkeypatch.chdir_never"`.
        """
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
        """A write to a directory pytest created and removes is not the host.

        The subject here is BOTH: rooted at the fixture and named from a
        `Path.home()` expression one hop back, which is the shape a snapshot
        test really has - read the user's config, land a copy where pytest will
        clean it up. The sandbox reading has to win, and it has to survive the
        hop, or every snapshot test in the fleet is a HOME_WRITE. Mutation
        caught: `sandbox_names = _bound_to(unit.node, SANDBOX_FIXTURES)` in
        `_home_write` becoming `sandbox_names = set()`.
        """
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
        """THE PYTEST IDIOM: a bare yield then a restore, and it must not be flagged twice.

        @ai_mail's `clean_env` strips four identity variables, yields, and puts
        all four back; twenty-nine units then set one of those same four inside
        the test. Reading the units alone called all twenty-nine unrestored when
        the file restores every one - and demanding a `try`/`finally` instead of
        a plain yield convicted thirty correct fixtures on the first fleet run.
        Both halves are pinned here: the requesting unit is clean AND the
        fixture itself is clean. Mutation caught: `if {argument.arg for argument
        in unit.node.args.args} & restoring_fixtures:` in `_env_mutation`
        becoming `... & set():`.
        """
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
        """@drone's lock_dir, which is correct code and was one row on the first run.

        The fixture records the original directory through monkeypatch and the
        unit then walks deeper with a raw `os.chdir`; teardown puts the process
        back where it started regardless. The acquittal travels from the fixture
        to every unit in the same file that requests it, one hop, no imports.
        Mutation caught: `if "monkeypatch.chdir" in calls:` in
        `restoring_fixtures` becoming `if "monkeypatch.chdir" in set():`.
        """
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
        """The cure written inline: the guarded mutation is not what gets reported.

        A variable set inside a `try` whose `finally` deletes it has been
        restored on every path including the failing one, and convicting the
        line the rule's own fix advice produces would teach projects to delete
        their restores. Only the guarded statement is asserted about here - what
        the checker says about the restoring statement in the `finally` is its
        owner's call and is deliberately not pinned. Mutation caught: `if not
        touched or _undone_in_a_finally(unit.node, node, ("os.environ",
        "os.putenv")):` losing its second clause, which reports the assignment
        inside the try.
        """
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
        """The same acquittal for the working directory, and it needs its own pin.

        `_cwd_change` consults the finally reading through a separate call with
        its own needles, so the env pin above cannot cover it: an edit that
        drops the cwd needles leaves that one green. Only the guarded statement
        is asserted about, same as above. Mutation caught:
        `_undone_in_a_finally(unit.node, node, ("os.chdir",))` becoming
        `_undone_in_a_finally(unit.node, node, ("os.chdir_never",))`.
        """
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
        """THE RULE MUST NOT CONVICT THE CURE ITS OWN RULE TEXT TEACHES.

        Measured defect, 2026-09-08: the first version read the whole `Try` for
        its evidence and the try body alone for its location, so the guarded
        change was acquitted and the RESTORE was reported - the worked example
        in host_state.md scored 0, with the row on the `del`. A rule that flags
        the restore teaches projects to delete restores, which is the incident
        again with more steps. The whole unit is asserted clean here, both
        halves, which is what the two pins above deliberately left open.
        Mutation caught: `if not in_body and line not in
        _lines_of(candidate.finalbody):` becoming `if not in_body:`, which is
        the original locating logic and reports the `del` again.
        """
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
        """THE ACQUITTAL IS THE RESTORE, NEVER THE KEYWORD.

        Measured defect, 2026-09-08, the same one line as the pin above read
        from the other side: evidence collected by walking the whole `Try` meant
        a change inside the body satisfied its own acquittal, so `finally:
        logger.info(...)` acquitted an environment variable nobody put back.
        Correct code scored 0 and incorrect code scored 100 for one shape.
        Mutation caught: `counterpart = candidate.finalbody if in_body else
        candidate.body` becoming `counterpart = list(candidate.body) +
        list(candidate.finalbody)`, which is the original whole-try evidence
        walk and acquits this unit on its own mention.
        """
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
        """DELIBERATELY NOT GENERAL: environment and working directory, and nothing else.

        `systemctl --user start` in a `finally` is not proof the machine is back
        - the unit file may already be deleted, the start may be a silent no-op,
        and the limit that matters most is that a `finally` does not run when
        the process is killed. A restore the checker cannot verify must not
        acquit the species the incident was made of. Pinned by the LINE the
        finding lands on, not by the row count: the guarded `stop` inside the
        try is the statement that must still be reported. Mutation caught:
        `_service_control`'s guard gaining `or _undone_in_a_finally(unit.node,
        node, ("subprocess",))`, which generalises the acquittal by one clause -
        and which a count alone cannot see, because that mutation moves the row
        onto the restart instead of removing it.
        """
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
        """The number is clean-over-total, counted per unit, and four acquittals hold it up.

        Two of the six units are the real thing; the other four are clean for
        four different reasons, so a mutation that collapses any single
        acquittal moves this number and cannot hide behind the other three. An
        inverted numerator still moves plausibly with a tree, which is why it is
        pinned by the number and by the sentence a reader gets. Mutation caught:
        `score = int(((total - len(flagged)) / total) * 100)` becoming `score =
        int((len(flagged) / total) * 100)`, which reports 33 where the honest
        answer is 66.
        """
        result = host_state_check.check_branch(str(_host_state_project(tmp_path)))

        assert result["score"] == 66
        assert len(result["violations"]) == 2
        assert (
            "2/6 test units and fixtures change live host state with no visible restore"
            in result["checks"][0]["message"]
        )

    def test_fixtures_are_counted_in_the_denominator_that_scores_them(self, tmp_path):
        """A SCORE THAT CAN GO NEGATIVE IS ONE NOBODY BELIEVES TWICE.

        Measured defect, 2026-09-08: `find_unrestored` reports fixture rows as
        well as unit rows, and the first version divided both by a count of
        UNITS alone. One clean unit beside two unrestoring fixtures scored -100
        and printed the sentence "2/1 test units". Every subject the rule judges
        has to be in the denominator that scores it. Mutation caught:
        `population = total + fixture_count(scanned)` becoming `population =
        total`, which returns -100 here.
        """
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
        """SHADOW MODE GATES NOTHING - this rule scores before it is calibrated.

        Top-level `passed` must stay True while flags exist and `advisory` must
        stay True, so a caller can tell a report from a verdict. Mutation
        caught: `"passed": True` becoming `"passed": not flagged` in the scored
        return, which turns an uncalibrated advisory into a board failure on
        every branch that has one of these sites.
        """
        result = host_state_check.check_branch(str(_host_state_project(tmp_path)))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "HOST_STATE"
        assert result["checks"][0]["passed"] is False

    def test_a_project_with_no_test_files_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND.

        A 0 blames a project for a fact about its layout and a 100 claims a
        measurement that never happened. Each check in this pack carries its own
        copy of the early return, so each one has to be pinned - and losing it
        here does not return a wrong number, it divides by zero and takes the
        caller with it. Mutation caught: `"not_applicable": True,` becoming
        `"not_applicable": False,` in the `total == 0` return.
        """
        _effectful_module(tmp_path, '"uninstall-timer"')

        result = host_state_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A broken file must never read as an absent one - the ordering pin.

        An unparseable file contributes no units, so it cannot lower a score,
        and silence about it reads as a clean result. This is the one path where
        nothing else can catch it: the message a caller sees must say the file
        was present and unreadable, not that the project has never written a
        test. Mutation caught: the `measured` ternary's `if not
        scanned.unparseable` becoming `if True`, which makes the two cases
        indistinguishable.
        """
        _effectful_module(tmp_path, '"uninstall-timer"')
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = host_state_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_broken.py" in check["message"] for check in result["checks"])

    def test_an_unparseable_test_file_is_named_beside_a_scored_result(self, tmp_path):
        """The unreadable line must also survive onto the path that DOES score.

        The early-return path carries it by construction; the scored path has to
        append it deliberately, and dropping that one line leaves a branch with
        a healthy number and no hint that a file was never read at all - which
        for this rule biases toward CLEAN, since an unread file flags nothing.
        Mutation caught: `checks.extend(unreadable)` becoming
        `checks.extend([])`.
        """
        _host_state_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = host_state_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["score"] == 66
        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]
