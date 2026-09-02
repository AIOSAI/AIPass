# =================== AIPass ====================
# Name: test_testwrite_gate.py
# Version: 1.0.0
# Description: Tests for the test-write gate and its JSON policy switch
# Branch: hooks
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""Tests for testwrite_gate — Patrick's 2026-09-01 no-agent-test-creation ruling.

Patrick ruled (devpulse DPLAN-0323) that agents are stripped of self-directed
test creation while @seedgo's test_quality v5 pack lands, enforced by a hook
behind a JSON switch so the way back is a field flip and not a rebuild.

SEQUENCE, stated plainly because it was not test-first: the handler was written
first and these pins after it. The red evidence is therefore a mutation sweep
run afterwards rather than a red-then-green sequence — 13 mutants, all killed,
including a baseline mutant that stubs the gate to allow everything and reds 25
of the 53 pins below. One of the 13 SURVIVED the first round and is why the
``writing_enabled`` contract pin exists: flipping the missing-policy constructor
to claim writing was ON killed nothing, because the gate reads ``error`` first.

The file is organised by the question each block answers:

 1. The switch does all three of its jobs: off blocks, a branch in ``allow``
    passes, ``on`` passes for everyone.
 2. The ruling stays where Patrick drew it: creation is blocked, editing an
    existing test is not.
 3. Both lanes answer the same. The scripted lane reuses ``bash_writes``, so a
    ``cat > tests/test_x.py`` is refused exactly like a Write.
 4. The fail mode is OBSERVABLE, not merely chosen: missing and corrupt policy
    files both refuse, and both safety properties that make fail-closed
    survivable — ordinary work never reads the policy, and the policy file
    itself is always writable — have pins of their own.
 5. The admin seat passes on a VERIFIED grant only, and never on a directory
    name, mirroring test_edit_gate_bash.py's discipline.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.hooks.apps.handlers.security.testwrite_gate import handle
from aipass.hooks.apps.modules import testgate_policy, testwrite_targets

_RAIL = "aipass.ai_mail.apps.handlers.users.verified_caller"


@pytest.fixture(autouse=True)
def no_admin_grant():
    """Every seat is ordinary unless a test says otherwise.

    Without this the real rail runs, and a machine that happens to hold a valid
    devpulse grant would silently exempt half this file.
    """
    with patch(f"{_RAIL}.is_verified_admin_caller", return_value=False):
        yield


@pytest.fixture
def grant_granted():
    with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True) as m:
        yield m


@pytest.fixture
def project(tmp_path: Path) -> dict:
    """An AIPass-shaped tree with one branch that already has a test suite.

    <tmp>/AIPass/
      AIPASS_REGISTRY.json
      .aipass/test_write_policy.json      written per-test by _policy()
      src/aipass/hooks/tests/test_existing.py
      src/aipass/devpulse/                the admin seat
    """
    root = tmp_path / "AIPass"
    (root / ".aipass").mkdir(parents=True)
    (root / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")

    hooks_tests = root / "src" / "aipass" / "hooks" / "tests"
    hooks_tests.mkdir(parents=True)
    existing = hooks_tests / "test_existing.py"
    existing.write_text("def test_x():\n    assert True\n", encoding="utf-8")

    (root / "src" / "aipass" / "devpulse").mkdir(parents=True)

    return {
        "root": root,
        "seat": str(root / "src" / "aipass" / "hooks"),
        "admin_seat": str(root / "src" / "aipass" / "devpulse"),
        "tests_dir": hooks_tests,
        "existing": str(existing),
        "new_test": str(hooks_tests / "test_brand_new.py"),
        "new_conftest": str(hooks_tests / "conftest.py"),
        "not_a_test": str(root / "src" / "aipass" / "hooks" / "apps" / "thing.py"),
    }


def _policy(project: dict, **fields) -> Path:
    """Write the policy file, defaulting to the shipped ruling."""
    body = {"agent_test_writing": "off", "allow": [], "block_test_edits": False}
    body.update(fields)
    path = project["root"] / ".aipass" / "test_write_policy.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _run(cwd: str, *, file_path: str | None = None, command: str | None = None, tool: str = "Write") -> dict:
    tool_input = {"command": command} if command is not None else {"file_path": file_path}
    return handle({"tool_name": "Bash" if command is not None else tool, "tool_input": tool_input, "cwd": cwd})


def _blocked(result: dict) -> bool:
    return result["exit_code"] == 2 and json.loads(result["stdout"]).get("decision") == "block"


def _reason(result: dict) -> str:
    return json.loads(result["stdout"])["reason"]


class TestTheSwitch:
    """Off blocks, allow[] exempts one branch, on lifts it for everyone."""

    @pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit", "NotebookEdit"])
    def test_off_blocks_a_new_test_file(self, project: dict, tool: str):
        _policy(project)
        result = _run(project["seat"], file_path=project["new_test"], tool=tool)
        assert _blocked(result)
        assert "test_brand_new.py" in _reason(result)

    def test_off_blocks_a_new_conftest(self, project: dict):
        """conftest.py carries a test tree's shared setup — it grows the corpus too."""
        _policy(project)
        assert _blocked(_run(project["seat"], file_path=project["new_conftest"]))

    def test_a_branch_in_allow_may_create(self, project: dict):
        """The canary trial: one branch name added, nothing else touched."""
        _policy(project, allow=["hooks"])
        assert _run(project["seat"], file_path=project["new_test"])["exit_code"] == 0

    def test_allow_names_one_branch_not_all_of_them(self, project: dict):
        """A canary that exempts the fleet is not a canary."""
        _policy(project, allow=["seedgo"])
        assert _blocked(_run(project["seat"], file_path=project["new_test"]))

    def test_on_lifts_it_for_everyone(self, project: dict):
        """Turning the whole thing back on is one field flip."""
        _policy(project, agent_test_writing="on")
        assert _run(project["seat"], file_path=project["new_test"])["exit_code"] == 0

    def test_the_refusal_names_the_config_and_both_cures(self, project: dict):
        """A gate that refuses without saying how to open is a wall."""
        path = _policy(project)
        reason = _reason(_run(project["seat"], file_path=project["new_test"]))
        assert str(path) in reason
        assert '"allow"' in reason
        assert '"agent_test_writing" to "on"' in reason
        assert "drone @hooks testwrite" in reason

    def test_the_refusal_names_what_the_ask_must_CARRY(self, project: dict):
        """Patrick's awareness ruling: blocking without teaching is half a gate.

        The navmap house rule is not "mail @devpulse", it is "mail @devpulse with
        the defect or contract the test pins". Naming the recipient and omitting
        that clause turns a reviewable request into a re-ask.
        """
        _policy(project)
        reason = _reason(_run(project["seat"], file_path=project["new_test"]))
        assert "DEFECT OR" in reason and "PINS" in reason
        assert "navmap" in reason
        assert "drone @ai_mail email @devpulse" in reason


class TestTheRulingStaysWherePatrickDrewIt:
    """Creation is blocked. Fixing a red test is legitimate work and stays open."""

    @pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit"])
    def test_editing_an_existing_test_passes(self, project: dict, tool: str):
        _policy(project)
        assert _run(project["seat"], file_path=project["existing"], tool=tool)["exit_code"] == 0

    def test_a_non_test_file_is_never_touched(self, project: dict):
        _policy(project)
        assert _run(project["seat"], file_path=project["not_a_test"])["exit_code"] == 0

    def test_a_test_shaped_name_outside_a_tests_tree_is_not_a_test(self, project: dict):
        """Published in NOT_CAUGHT: the gate reads the TREE, not just the filename."""
        _policy(project)
        stray = str(Path(project["seat"]) / "apps" / "test_helper.py")
        assert _run(project["seat"], file_path=stray)["exit_code"] == 0

    def test_block_test_edits_is_a_live_switch_not_a_dormant_field(self, project: dict):
        """Shipped false, but executable — an unrun branch is not a switch."""
        _policy(project, block_test_edits=True)
        result = _run(project["seat"], file_path=project["existing"])
        assert _blocked(result)
        assert "block_test_edits" in _reason(result)

    def test_block_test_edits_defaults_to_off_when_absent(self, project: dict):
        path = project["root"] / ".aipass" / "test_write_policy.json"
        path.write_text(json.dumps({"agent_test_writing": "off"}), encoding="utf-8")
        assert _run(project["seat"], file_path=project["existing"])["exit_code"] == 0


class TestBothLanesAnswerTheSame:
    """The scripted lane was the hole in edit_gate for months. Not here."""

    @pytest.mark.parametrize(
        "command",
        [
            "cat > {new} <<EOF\ndef test_a(): pass\nEOF",
            "echo 'def test_a(): pass' > {new}",
            "tee {new}",
            "cp /etc/hostname {new}",
            "touch {new}",
        ],
    )
    def test_scripted_creation_is_blocked(self, project: dict, command: str):
        _policy(project)
        result = _run(project["seat"], command=command.format(new=project["new_test"]))
        assert _blocked(result)
        assert "scripted" in _reason(result)

    def test_the_scripted_lane_reuses_bash_writes(self, project: dict):
        """One shell reader for both gates. Two would eventually disagree."""
        from aipass.hooks.apps.handlers.security import testwrite_gate

        _policy(project)
        with patch.object(testwrite_gate, "testwrite_targets_bash", return_value=[]) as seam:
            assert _run(project["seat"], command=f"echo x > {project['new_test']}")["exit_code"] == 0
        assert seam.called

    def test_a_scripted_edit_of_an_existing_test_passes(self, project: dict):
        _policy(project)
        command = f"sed -i 's/True/False/' {project['existing']}"
        assert _run(project["seat"], command=command)["exit_code"] == 0

    def test_running_the_suite_is_not_writing_it(self, project: dict):
        """python -m pytest names an EXISTING test path — the existence check absorbs it."""
        _policy(project)
        command = f"python -m pytest {project['existing']}"
        assert _run(project["seat"], command=command)["exit_code"] == 0

    def test_an_unparseable_command_allows_and_logs(self, project: dict):
        """bash_writes' own contract: a command it could not read taught it nothing."""
        from aipass.hooks.apps.handlers.security import testwrite_gate

        _policy(project)
        with patch.object(testwrite_gate, "testwrite_targets_bash", side_effect=ValueError("lexer died")):
            assert _run(project["seat"], command="something ; unreadable")["exit_code"] == 0


class TestTheFailModeIsObservable:
    """Fail CLOSED on a policy that cannot be read — and why that is survivable."""

    def test_a_missing_policy_blocks_creation(self, project: dict):
        result = _run(project["seat"], file_path=project["new_test"])
        assert _blocked(result)
        assert "no test-write policy found" in _reason(result)

    def test_the_missing_refusal_names_the_file_it_wanted(self, project: dict):
        reason = _reason(_run(project["seat"], file_path=project["new_test"]))
        assert "test_write_policy.json" in reason
        assert "agent_test_writing" in reason

    def test_the_missing_refusal_names_the_RULING_it_stands_in_for(self, project: dict):
        """The message a fresh project actually hits, so it carries the most weight.

        `aipass init` stamps the gate but not a policy, so most projects meet this
        refusal and never the configured one. Without the ruling named, it reads as
        a broken install rather than a fleet decision — and the cure looks like
        "repair something" instead of "opt in".
        """
        reason = _reason(_run(project["seat"], file_path=project["new_test"]))
        assert "DPLAN-0323" in reason
        assert "Patrick" in reason
        assert "EDITING an existing test is untouched" in reason

    @pytest.mark.parametrize(
        "body",
        [
            "{not json at all",
            '["a", "list"]',
            '{"agent_test_writing": "of"}',
            '{"agent_test_writing": true}',
            "{}",
            '{"agent_test_writing": "off", "allow": "hooks"}',
            '{"agent_test_writing": "off", "block_test_edits": "yes"}',
        ],
    )
    def test_a_corrupt_policy_blocks_creation(self, project: dict, body: str):
        """The file exists, so a ruling WAS made and we cannot read it. Guessing is not allowed."""
        (project["root"] / ".aipass" / "test_write_policy.json").write_text(body, encoding="utf-8")
        result = _run(project["seat"], file_path=project["new_test"])
        assert _blocked(result)
        assert "could not be read" in _reason(result)

    def test_a_broken_policy_does_not_brick_ordinary_work(self, project: dict):
        """The safety property that makes fail-closed survivable: no test target, no policy read."""
        with patch.object(testgate_policy, "load", side_effect=AssertionError("policy must not be read")):
            assert _run(project["seat"], file_path=project["not_a_test"])["exit_code"] == 0

    def test_a_broken_policy_still_lets_the_policy_file_be_written(self, project: dict):
        """The other safety property: the cure is always reachable from where you are."""
        target = str(project["root"] / ".aipass" / "test_write_policy.json")
        assert _run(project["seat"], file_path=target)["exit_code"] == 0

    def test_an_unreadable_policy_does_not_extend_the_ruling_to_edits(self, project: dict):
        """Fail-closed stands in for the ruling — and the ruling only ever blocked creation."""
        (project["root"] / ".aipass" / "test_write_policy.json").write_text("{oops", encoding="utf-8")
        assert _run(project["seat"], file_path=project["existing"])["exit_code"] == 0

    def test_a_policy_carrying_an_error_never_claims_writing_is_enabled(self, project: dict, tmp_path: Path):
        """The reader is a public module API, and ``error`` is not its only reader.

        Found by mutation: flipping ``writing_enabled`` to True inside the
        missing-policy constructor killed nothing, because the gate short-circuits
        on ``error`` first. Any other caller reading ``.writing_enabled`` alone
        would have been told test writing was ON precisely when no policy exists.
        """
        missing = testgate_policy.load(tmp_path)
        assert missing.error is not None
        assert missing.writing_enabled is False
        assert missing.block_edits is False
        assert missing.allow == frozenset()

        (project["root"] / ".aipass" / "test_write_policy.json").write_text("{broken", encoding="utf-8")
        corrupt = testgate_policy.load(project["seat"])
        assert corrupt.error is not None
        assert corrupt.writing_enabled is False

    def test_a_gate_crash_allows_rather_than_walls(self, project: dict):
        """Fail-closed covers a policy we could not READ. A defect in this gate is ours."""
        _policy(project)
        with patch.object(testwrite_targets, "classify", side_effect=RuntimeError("gate defect")):
            assert _run(project["seat"], file_path=project["new_test"])["exit_code"] == 0


class TestTheAdminSeat:
    """Patrick's cleanup work must not be blocked — on a verified grant only."""

    def test_the_verified_admin_seat_may_create(self, project: dict, grant_granted):
        _policy(project)
        new = str(project["root"] / "src" / "aipass" / "devpulse" / "tests" / "test_new.py")
        assert _run(project["admin_seat"], file_path=new)["exit_code"] == 0

    def test_the_admin_seat_without_the_grant_is_refused(self, project: dict):
        """The seat is not the credential — same directory, no grant, blocked."""
        _policy(project)
        new = str(project["root"] / "src" / "aipass" / "devpulse" / "tests" / "test_new.py")
        assert _blocked(_run(project["admin_seat"], file_path=new))

    def test_the_admin_seat_passes_even_when_the_policy_is_unreadable(self, project: dict, grant_granted):
        """Checked BEFORE the policy read, so a broken file cannot lock Patrick out."""
        (project["root"] / ".aipass" / "test_write_policy.json").write_text("{broken", encoding="utf-8")
        new = str(project["root"] / "src" / "aipass" / "devpulse" / "tests" / "test_new.py")
        assert _run(project["admin_seat"], file_path=new)["exit_code"] == 0

    def test_an_unimportable_admin_module_refuses_rather_than_opens(self, project: dict):
        """Caught live: reaching the rail through a second module adds a second failure.

        The first cut let an ImportError propagate to the handler's crash guard,
        which allows — so a missing admin_seat.py would have exempted EVERY seat.
        edit_gate's own suite convicted the same shape in its half within the
        minute. The delegation must not become a way in.
        """
        from aipass.hooks.apps.handlers.security import testwrite_gate

        _policy(project)
        with patch.object(testwrite_gate, "_module", side_effect=ImportError("no admin_seat")):
            assert testwrite_gate._is_admin_seat(project["admin_seat"]) is False

    def test_the_grant_is_not_checked_for_a_write_that_is_not_a_test(self, project: dict):
        """Verification touches the disk; ordinary work must not pay for it."""
        _policy(project)
        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True) as rail:
            assert _run(project["seat"], file_path=project["not_a_test"])["exit_code"] == 0
        rail.assert_not_called()


class TestTheGateStaysInItsLane:
    """A PreToolUse handler sees every tool. This one answers for two."""

    @pytest.mark.parametrize("tool", ["Read", "Grep", "Glob", "Task", "WebFetch"])
    def test_a_non_write_tool_is_ignored(self, project: dict, tool: str):
        _policy(project)
        result = handle({"tool_name": tool, "tool_input": {"file_path": project["new_test"]}, "cwd": project["seat"]})
        assert result["exit_code"] == 0

    def test_an_edit_with_no_file_path_is_ignored(self, project: dict):
        _policy(project)
        assert handle({"tool_name": "Write", "tool_input": {}, "cwd": project["seat"]})["exit_code"] == 0

    def test_an_empty_bash_command_is_ignored(self, project: dict):
        _policy(project)
        assert handle({"tool_name": "Bash", "tool_input": {"command": ""}, "cwd": project["seat"]})["exit_code"] == 0


class TestTheResidualIsPublished:
    """A gap you can read from a terminal is one an agent can plan around."""

    def test_not_caught_is_data_not_prose(self):
        assert isinstance(testwrite_targets.NOT_CAUGHT, tuple)
        assert all(isinstance(gap, str) and gap for gap in testwrite_targets.NOT_CAUGHT)

    def test_the_named_gaps_really_are_gaps(self, project: dict):
        """Each claim in NOT_CAUGHT is asserted against the gate, not just written down."""
        _policy(project)
        # "outside any tests/ directory"
        stray = str(Path(project["seat"]) / "apps" / "test_helper.py")
        assert _run(project["seat"], file_path=stray)["exit_code"] == 0
        # "not .py"
        corpus = str(project["tests_dir"] / "test_corpus.json")
        assert _run(project["seat"], file_path=corpus)["exit_code"] == 0
        # "a different directory name"
        specs = str(Path(project["seat"]) / "specs" / "test_thing.py")
        assert _run(project["seat"], file_path=specs)["exit_code"] == 0

    def test_a_renamed_test_file_shape_is_still_caught(self, project: dict):
        """*_test.py is pytest-collectable, so leaving it out would be a one-rename escape."""
        _policy(project)
        renamed = str(project["tests_dir"] / "brand_new_test.py")
        assert _blocked(_run(project["seat"], file_path=renamed))
