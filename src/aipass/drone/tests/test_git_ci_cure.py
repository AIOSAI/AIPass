# =================== AIPass ====================
# Name: test_git_ci_cure.py
# Description: Tests for the ci-cure tier and its verb — own file, as test_git_module.py nears the size cap
# Version: 1.0.0
# Created: 2026-10-22
# Modified: 2026-10-23
# =============================================

"""Tests for apps/handlers/git/ci_cure_handler.py through apps/modules/git_module.py, and its tier in auth.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — subprocess.run; git runs only in tmp_path repos, origin is a local bare repo

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import pytest

from aipass.drone.apps.handlers.git import ci_cure_handler
from aipass.drone.apps.modules.git_module import get_help, handle_command
from aipass.drone.apps.plugins.devpulse_ops.auth import GIT_ACCESS_TIERS, verify_git_access

from .conftest import OWNER_REGISTRY_ID

RUN = "18712345678"
GOOD_MESSAGE = f"fix(hooks): bypass lines re-pinned, run {RUN}\n\nThe anchors moved two lines."
HOOKS_FILE = "src/aipass/hooks/bypass.json"


def _git(cwd: Path, *argv: str) -> str:
    """Run git in *cwd* for fixture setup and read-back; raises on failure."""
    return subprocess.run(
        ["git", *argv], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout.strip()


def _ledger(tmp_path: Path) -> list[dict]:
    """The ci-cure records, read from beside the test's isolated deletion log."""
    path = tmp_path / ci_cure_handler.LEDGER_NAME
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def _grant(root: Path, name: str) -> Path:
    """Add *name* to the registry with ci_cure: true and a bound passport; returns its seat."""
    seat = root / "src" / "aipass" / name
    (seat / ".trinity").mkdir(parents=True, exist_ok=True)
    passport = {
        "branch_info": {"branch_name": name},
        "identity": {"citizen_class": "specialist"},
        "citizenship": {"registered": True, "registry_id": OWNER_REGISTRY_ID},
    }
    (seat / ".trinity" / "passport.json").write_text(json.dumps(passport), encoding="utf-8")
    registry_path = root / "AIPASS_REGISTRY.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["branches"].append({"name": name, "path": str(seat), "status": "active", "ci_cure": True})
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    return seat


@pytest.fixture()
def cure_repo(aipass_github: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """AIPass on dev, pushed to a local bare origin, standing in @trigger's seat (holder of ci_cure); returns root."""
    root = aipass_github
    seat = _grant(root, "trigger")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, capture_output=True)
    _git(root, "remote", "set-url", "origin", str(origin))
    (root / "src" / "aipass" / "hooks").mkdir(parents=True)
    for rel in (HOOKS_FILE, "CHANGELOG.md", "src/aipass/drone/x.py"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("before\n", encoding="utf-8")
    _git(root, "add", "src/aipass/hooks", "src/aipass/drone/x.py", "CHANGELOG.md")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", "dev")
    _git(root, "push", "-q", "origin", "dev")
    monkeypatch.chdir(seat)
    return root


def _heads(root: Path) -> tuple[str, str]:
    """(local dev, origin's dev)."""
    return _git(root, "rev-parse", "dev"), _git(root / ".." / "origin.git", "rev-parse", "dev")


class TestCiCureTier:
    """The tier is granted by the registry fact ci_cure: true on one entry, and by nothing else."""

    def test_ci_cure_sits_in_its_own_tier_and_in_no_other(self) -> None:
        assert GIT_ACCESS_TIERS["ci-cure"]["commands"] == ["ci-cure"]
        assert "ci-cure" not in GIT_ACCESS_TIERS["owner"]["commands"]
        assert "ci-cure" not in GIT_ACCESS_TIERS["global"]["commands"]

    def test_the_holder_of_the_fact_is_granted(self, cure_repo: Path) -> None:
        assert verify_git_access("ci-cure") == "trigger"

    def test_the_owner_without_the_fact_is_refused_at_error(
        self, cure_repo: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.chdir(cure_repo / "src" / "aipass" / "devpulse")
        with caplog.at_level(logging.ERROR), pytest.raises(PermissionError) as refused:
            verify_git_access("ci-cure")
        assert str(refused.value) == (
            "Branch 'devpulse' is not authorized for 'ci-cure': "
            "caller 'devpulse' is listed in AIPASS_REGISTRY.json without ci_cure: true."
        )
        assert [r.levelname for r in caplog.records if "ci-cure" in r.getMessage()] == ["ERROR"]

    def test_a_second_holder_refuses_both_so_the_tier_stays_held_alone(self, cure_repo: Path) -> None:
        _grant(cure_repo, "hooks")
        with pytest.raises(PermissionError, match=r"2 entries in AIPASS_REGISTRY.json carry ci_cure: true"):
            verify_git_access("ci-cure")

    def test_a_fact_that_is_not_the_boolean_true_grants_nothing(self, cure_repo: Path) -> None:
        registry_path = cure_repo / "AIPASS_REGISTRY.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["branches"][-1]["ci_cure"] = "true"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")
        with pytest.raises(PermissionError, match="listed in AIPASS_REGISTRY.json without ci_cure: true"):
            verify_git_access("ci-cure")

    def test_warn_mode_does_not_lift_a_ci_cure_refusal(
        self, cure_repo: Path, builder_seat: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AIPASS_GIT_AUTH_MODE", "warn")
        with pytest.raises(PermissionError, match="is not authorized for 'ci-cure'"):
            verify_git_access("ci-cure")

    def test_help_lists_the_verb_with_its_fences(self) -> None:
        page = get_help()
        assert "ci-cure <run_id> @<owner> <msg> <path ...>" in page
        verb_page = get_help("ci-cure")
        assert ci_cure_handler.USAGE in verb_page
        assert ci_cure_handler.REFUSE_NOT_DEV.format(branch="<branch>") in verb_page


_TRIGGER = "trigger"
_OTHER = "other"

_REFUSALS = [
    pytest.param(
        [RUN, "@hooks", GOOD_MESSAGE, "src/aipass/drone/x.py"],
        ci_cure_handler.REFUSE_PATH.format(path="src/aipass/drone/x.py", owner="hooks"),
        id="path-in-another-tree",
    ),
    pytest.param(
        [RUN, "@hooks", GOOD_MESSAGE, "src/aipass/hooks/../drone/x.py"],
        ci_cure_handler.REFUSE_PATH.format(path="src/aipass/hooks/../drone/x.py", owner="hooks"),
        id="path-climbs-out",
    ),
    pytest.param(
        [RUN, "@hooks", GOOD_MESSAGE, "src/aipass/hooks/*"],
        ci_cure_handler.REFUSE_PATH.format(path="src/aipass/hooks/*", owner="hooks"),
        id="path-is-a-glob",
    ),
    pytest.param(
        [RUN, "@hooks", f"chore(hooks): run {RUN}", HOOKS_FILE],
        ci_cure_handler.REFUSE_PREFIX.format(owner="hooks"),
        id="message-not-fix-owner",
    ),
    pytest.param(
        [RUN, "@hooks", f"fix(hooks): re-pinned\n\nrun {RUN}", HOOKS_FILE],
        ci_cure_handler.REFUSE_RUN_UNNAMED.format(run_id=RUN),
        id="run-id-only-in-the-body",
    ),
    pytest.param(
        [RUN, "@hooks", f"fix(hooks): run {RUN}9", HOOKS_FILE],
        ci_cure_handler.REFUSE_RUN_UNNAMED.format(run_id=RUN),
        id="run-id-only-as-a-prefix-of-another",
    ),
    pytest.param([RUN, "@hooks", GOOD_MESSAGE], ci_cure_handler.REFUSE_NO_PATHS, id="no-paths"),
    pytest.param(
        ["latest", "@hooks", GOOD_MESSAGE, HOOKS_FILE],
        ci_cure_handler.REFUSE_RUN_ID.format(run_id="latest"),
        id="run-id-not-numeric",
    ),
]


class TestCiCureRefusals:
    """Every refusal leaves dev and origin where they were, says why, and writes one ledger row."""

    @pytest.mark.parametrize("seat", [_TRIGGER, _OTHER])
    @pytest.mark.parametrize(("args", "refusal"), _REFUSALS)
    def test_a_refused_cure_commits_and_pushes_nothing(
        self, cure_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, seat: str, args: list, refusal: str
    ) -> None:
        if seat == _OTHER:
            monkeypatch.chdir(cure_repo / "src" / "aipass" / "devpulse")
        (cure_repo / HOOKS_FILE).write_text("after\n", encoding="utf-8")
        before = _heads(cure_repo)

        result = handle_command("ci-cure", list(args))

        expected = refusal if seat == _TRIGGER else _gate_refusal("devpulse")
        assert result == {"stdout": "", "stderr": expected, "exit_code": 1}
        assert _heads(cure_repo) == before
        assert _git(cure_repo, "diff", "--cached", "--name-only") == ""
        assert [(row["outcome"], row["reason"]) for row in _ledger(tmp_path)] == [("refused", expected)]

    @pytest.mark.parametrize("seat", [_TRIGGER, _OTHER])
    def test_off_dev_is_a_capability_refusal_at_warning(
        self,
        cure_repo: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        seat: str,
    ) -> None:
        if seat == _OTHER:
            monkeypatch.chdir(cure_repo / "src" / "aipass" / "devpulse")
        _git(cure_repo, "checkout", "-q", "main")
        (cure_repo / HOOKS_FILE).write_text("after\n", encoding="utf-8")
        main_before = _git(cure_repo, "rev-parse", "main")

        with caplog.at_level(logging.WARNING):
            result = handle_command("ci-cure", [RUN, "@hooks", GOOD_MESSAGE, HOOKS_FILE])

        if seat == _TRIGGER:
            assert result["stderr"] == ci_cure_handler.REFUSE_NOT_DEV.format(branch="main")
            assert [r.levelname for r in caplog.records if "ci-cure refused" in r.getMessage()] == ["WARNING"]
        else:
            assert result["stderr"] == _gate_refusal("devpulse")
        assert result["exit_code"] == 1
        assert _git(cure_repo, "rev-parse", "main") == main_before
        assert _ledger(tmp_path)[0]["outcome"] == "refused"

    def test_the_repo_flag_is_refused_and_nothing_runs(self, cure_repo: Path) -> None:
        (cure_repo / HOOKS_FILE).write_text("after\n", encoding="utf-8")
        before = _heads(cure_repo)

        result = handle_command("ci-cure", [RUN, "@hooks", GOOD_MESSAGE, HOOKS_FILE, "--repo", str(cure_repo)])

        assert result["exit_code"] == 1
        assert result["stdout"] == ""
        assert _heads(cure_repo) == before


def _gate_refusal(name: str) -> str:
    """The gate's refusal for a registry citizen without the fact."""
    return (
        f"Branch '{name}' is not authorized for 'ci-cure': "
        f"caller '{name}' is listed in AIPASS_REGISTRY.json without ci_cure: true."
    )


class TestCiCureSuccess:
    """A fenced cure on dev is committed alone, pushed to origin/dev, and its sha printed and recorded."""

    def test_only_the_named_paths_are_committed_and_dev_is_pushed(self, cure_repo: Path, tmp_path: Path) -> None:
        (cure_repo / HOOKS_FILE).write_text("after\n", encoding="utf-8")
        (cure_repo / "CHANGELOG.md").write_text("before\n- the bullet\n", encoding="utf-8")
        (cure_repo / "src" / "aipass" / "hooks" / "new.py").write_text("new\n", encoding="utf-8")
        (cure_repo / "src" / "aipass" / "drone" / "x.py").write_text("devpulse's work\n", encoding="utf-8")
        _git(cure_repo, "add", "src/aipass/drone/x.py")
        paths = [HOOKS_FILE, "src/aipass/hooks/new.py", "CHANGELOG.md"]

        result = handle_command("ci-cure", [RUN, "@hooks", GOOD_MESSAGE, *paths])

        local, remote = _heads(cure_repo)
        assert result["exit_code"] == 0, result["stderr"]
        assert result["stdout"].splitlines()[0] == local == remote
        assert _git(cure_repo, "show", "--name-only", "--format=%B", "HEAD").split("\n\n", 2)[:2] == [
            f"fix(hooks): bypass lines re-pinned, run {RUN}",
            "The anchors moved two lines.",
        ]
        assert sorted(_git(cure_repo, "show", "--name-only", "--format=", "HEAD").splitlines()) == sorted(paths)
        assert _git(cure_repo, "diff", "--cached", "--name-only") == "src/aipass/drone/x.py"
        assert _ledger(tmp_path) == [
            {
                **_ledger(tmp_path)[0],
                "caller": "trigger",
                "outcome": "pushed",
                "run_id": RUN,
                "owner": "hooks",
                "paths": paths,
                "sha": local,
            }
        ]

    def test_unchanged_paths_are_refused_as_no_change(self, cure_repo: Path) -> None:
        result = handle_command("ci-cure", [RUN, "@hooks", GOOD_MESSAGE, HOOKS_FILE])
        assert result["stderr"] == ci_cure_handler.REFUSE_NO_CHANGE
        assert result["exit_code"] == 1

    def test_a_failed_push_prints_the_sha_and_records_the_failure(self, cure_repo: Path, tmp_path: Path) -> None:
        _git(cure_repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
        (cure_repo / HOOKS_FILE).write_text("after\n", encoding="utf-8")

        result = handle_command("ci-cure", [RUN, "@hooks", GOOD_MESSAGE, HOOKS_FILE])

        sha = _git(cure_repo, "rev-parse", "dev")
        assert result["exit_code"] == 1
        assert result["stdout"] == sha
        assert result["stderr"].startswith(f"ci-cure committed {sha} on dev; the push failed: ")
        assert [(row["outcome"], row["sha"]) for row in _ledger(tmp_path)] == [("failed", sha)]
