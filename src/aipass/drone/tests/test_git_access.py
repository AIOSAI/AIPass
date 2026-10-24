# =================== AIPass ====================
# Name: test_git_access.py
# Description: Tests for tier-based git access — the tiers, the owner gate and its log severity
# Version: 1.4.1
# Created: 2026-05-12
# Modified: 2026-10-24
# =============================================

"""Tests for apps/plugins/devpulse_ops/auth.py: the git tiers and how owner tier is earned per repo."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — subprocess.run; git is stubbed wherever a verb is routed here

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.drone.apps.plugins.devpulse_ops.auth import (
    GIT_ACCESS_TIERS,
    external_owner_verbs,
    verify_git_access,
)
from aipass.drone.apps.handlers.git import help_pages
from aipass.drone.apps.modules.git_module import handle_command

from .conftest import OWNER_REGISTRY_ID, make_owner_project


def _registered_verbs() -> list[str]:
    """Every verb the module registers, read from its own unknown-command refusal.

    The gate is a recorder here, so the refusal is the router's and no git runs.
    """
    with patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="devpulse") as gate:
        result = handle_command("no-such-verb", ["x"])
    gate.assert_called_once_with("no-such-verb")
    assert result["exit_code"] == 1
    return result["stderr"].split("Available: ", 1)[1].split(", ")


def _failing_resolve(target: Path, failure: type[Exception]) -> Callable[[Path], Path]:
    """A stand-in for auth's resolve seam that raises *failure* for *target* and resolves every other path."""

    def resolve(path: Path) -> Path:
        if path == target:
            raise failure("simulated resolve failure")
        return path.resolve()

    return resolve


class TestGitAccessTiers:
    """Verify the tier config is correctly structured."""

    def test_tiers_has_global_and_owner(self) -> None:
        assert "global" in GIT_ACCESS_TIERS
        assert "owner" in GIT_ACCESS_TIERS

    def test_global_commands(self) -> None:
        cmds = GIT_ACCESS_TIERS["global"]["commands"]
        assert "status" in cmds
        assert "diff" in cmds
        assert "log" in cmds
        assert "lock" in cmds

    def test_owner_commands(self) -> None:
        cmds = GIT_ACCESS_TIERS["owner"]["commands"]
        assert "commit" in cmds
        assert "checkout" in cmds
        assert "sync" in cmds
        assert "unlock" in cmds
        assert "pr" in cmds
        assert "merge" in cmds
        assert "smart-sync" in cmds
        assert "fix" in cmds

    def test_owner_tier_names_no_branch(self) -> None:
        """Owner-tier must not carry a hardcoded allowlist: authority is earned per repo, not by name."""
        assert "allowed_callers" not in GIT_ACCESS_TIERS["owner"]

    def test_prune_temp_in_owner_tier(self) -> None:
        """prune-temp deletes merged remote citizen/* branches — delete-branch class."""
        cmds = GIT_ACCESS_TIERS["owner"]["commands"]
        assert "prune-temp" in cmds
        assert "prune-temp" not in GIT_ACCESS_TIERS["global"]["commands"]

    def test_every_registered_command_holds_a_tier(self) -> None:
        """No command may be dispatchable without a tier — the class-level guard.

        Auth runs first and refuses anything in no tier, so an untiered verb is unreachable.
        """
        tiered = {verb for tier in GIT_ACCESS_TIERS.values() for verb in tier["commands"]}
        orphaned = sorted(set(_registered_verbs()) - tiered)
        assert orphaned == [], f"registered but unreachable — in no tier: {orphaned}"

    def test_no_tier_grants_a_command_that_does_not_exist(self) -> None:
        """The mirror: a tier entry with no registered command is a dead grant."""
        tiered = {verb for tier in GIT_ACCESS_TIERS.values() for verb in tier["commands"]}
        phantom = sorted(tiered - set(_registered_verbs()))
        assert phantom == [], f"granted but not registered: {phantom}"


class TestVerifyGitAccessGlobal:
    """Global-tier commands should pass for any caller."""

    def test_status_allowed_for_any_branch(self, devpulse_dir: Path) -> None:
        assert verify_git_access("status") == "devpulse"

    def test_diff_allowed_for_seedgo(self, seedgo_dir: Path) -> None:
        assert verify_git_access("diff") == "seedgo"

    def test_log_allowed_for_any_branch(self, seedgo_dir: Path) -> None:
        assert verify_git_access("log") == "seedgo"

    def test_lock_allowed_for_any_branch(self, seedgo_dir: Path) -> None:
        assert verify_git_access("lock") == "seedgo"


class TestVerifyGitAccessOwner:
    """Owner-tier commands should only pass for devpulse."""

    def test_commit_allowed_for_devpulse(self, devpulse_dir: Path) -> None:
        assert verify_git_access("commit") == "devpulse"

    def test_commit_denied_for_seedgo(self, seedgo_dir: Path) -> None:
        with pytest.raises(PermissionError, match="not authorized"):
            verify_git_access("commit")

    def test_checkout_denied_for_seedgo(self, seedgo_dir: Path) -> None:
        with pytest.raises(PermissionError, match="not authorized"):
            verify_git_access("checkout")

    def test_sync_denied_for_seedgo(self, seedgo_dir: Path) -> None:
        with pytest.raises(PermissionError, match="not authorized"):
            verify_git_access("sync")

    def test_unlock_denied_for_seedgo(self, seedgo_dir: Path) -> None:
        with pytest.raises(PermissionError, match="not authorized"):
            verify_git_access("unlock")

    def test_pr_denied_for_seedgo(self, seedgo_dir: Path) -> None:
        with pytest.raises(PermissionError, match="not authorized"):
            verify_git_access("pr")


class TestVerifyGitAccessPrOwnerOnly:
    """PR command should be allowed for devpulse, denied for others."""

    def test_pr_allowed_for_devpulse(self, devpulse_dir: Path) -> None:
        result = verify_git_access("pr")
        assert result == "devpulse"

    def test_pr_denied_for_a_manager_who_is_not_the_owner(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        make_owner_project(tmp_path, owner=False)
        monkeypatch.chdir(tmp_path)
        with pytest.raises(PermissionError, match="not authorized"):
            verify_git_access("pr")


class TestVerifyGitAccessUnknown:
    """Unknown commands should be denied."""

    def test_unknown_command_denied(self, devpulse_dir: Path) -> None:
        with pytest.raises(PermissionError, match="Unknown git command"):
            verify_git_access("nonexistent")

    @pytest.mark.parametrize(
        ("command", "pointer"),
        [
            ("add", "commit"),
            ("push", "dev-pr"),
            ("pull", "sync"),
        ],
    )
    def test_rerouted_verbs_point_at_replacement(self, devpulse_dir: Path, command: str, pointer: str) -> None:
        """Real git verbs drone folds into higher-level commands name their replacement."""
        with pytest.raises(PermissionError) as exc_info:
            verify_git_access(command)
        assert pointer in str(exc_info.value)

    def test_unknown_verb_gets_no_hint(self, devpulse_dir: Path) -> None:
        """Only rerouted verbs get a pointer — a typo must not be handed a bogus suggestion."""
        with pytest.raises(PermissionError) as exc_info:
            verify_git_access("nonexistent")
        assert str(exc_info.value) == "Unknown git command: 'nonexistent'."


class TestOwnerTierIsEarnedPerRepo:
    """Owner-tier authorization: manager + tenancy + owner flag + path-binding.

    Each test breaks exactly ONE of the four facts, so a regression names its check.
    """

    def test_manager_at_home_is_authorized(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The happy path: all four facts hold, owner-tier is granted."""
        make_owner_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        assert verify_git_access("commit") == "devpulse"

    def test_no_branch_is_hardcoded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A project's own manager holds git even when AIPass never heard of them."""
        make_owner_project(tmp_path, branch="VERA", registry_name="VERA-STUDIO_REGISTRY.json")
        monkeypatch.chdir(tmp_path)
        assert verify_git_access("commit") == "VERA"

    def test_non_manager_denied(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Forged/insufficient class: everything else correct, class is not manager."""
        make_owner_project(tmp_path, branch="seedgo", citizen_class="builder")
        monkeypatch.chdir(tmp_path)
        with pytest.raises(PermissionError, match="citizen_class"):
            verify_git_access("commit")

    def test_wrong_tenancy_denied(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """T-C: a manager of another project, holding a passport for a different registry.

        Matches the SHARED loader's wording, which the explicit check does not share.
        The AIPASS_REGISTRY pin is load-bearing: the cwd walk SKIPS a mismatched registry,
        so unpinned the test reads whatever lies outside the fixture (differs local vs CI).
        """
        make_owner_project(tmp_path, passport_registry_id="some-other-project-id")
        monkeypatch.setenv("AIPASS_REGISTRY", str(tmp_path / "AIPASS_REGISTRY.json"))
        monkeypatch.chdir(tmp_path)
        with pytest.raises(PermissionError, match="does not hold citizenship in this project's registry"):
            verify_git_access("commit")

    def test_tenancy_rechecked_when_loader_stays_silent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The explicit tenancy check is the backstop, and must refuse on its own.

        The loader's credential check can pass silently, so it is patched quiet here.
        Pinned for the same reason as test_wrong_tenancy_denied.
        """
        make_owner_project(tmp_path, passport_registry_id="some-other-project-id")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AIPASS_REGISTRY", str(tmp_path / "AIPASS_REGISTRY.json"))
        silent = {
            "metadata": {"id": OWNER_REGISTRY_ID},
            "branches": {"devpulse": {"name": "devpulse", "path": str(tmp_path), "owner": True}},
        }
        with patch("aipass.drone.apps.plugins.devpulse_ops.auth.load_registry", return_value=silent):
            with pytest.raises(PermissionError, match="belongs to registry some-other-project-id"):
                verify_git_access("commit")

    def test_missing_tenancy_id_denied(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Migration boundary: a passport predating registry_id."""
        make_owner_project(tmp_path, passport_registry_id="")
        monkeypatch.chdir(tmp_path)
        with pytest.raises(PermissionError, match="no citizenship.registry_id"):
            verify_git_access("commit")

    def test_not_listed_in_registry_denied(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A manager passport for a branch this project's registry does not carry."""
        # The second call overwrites the registry: ghost keeps a passport, loses the entry.
        ghost = make_owner_project(tmp_path, branch="ghost", branch_dir=tmp_path / "ghost")
        make_owner_project(tmp_path, branch="devpulse")
        monkeypatch.chdir(ghost)
        with pytest.raises(PermissionError, match="not listed"):
            verify_git_access("commit")

    def test_owner_flag_false_denied(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Listed and a manager, but the registry does not mark them owner."""
        make_owner_project(tmp_path, owner=False)
        monkeypatch.chdir(tmp_path)
        with pytest.raises(PermissionError, match="without owner: true"):
            verify_git_access("commit")

    def test_passport_outside_recorded_home_denied(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """T-A, the escalation that mattered: a forged passport in a directory the attacker controls.

        Every other fact is correct (the registry id is copyable); only the location refuses.
        """
        rogue = tmp_path / "tmp_workdir"
        make_owner_project(tmp_path, branch_dir=rogue, record_path=str(tmp_path / "real_devpulse"))
        monkeypatch.chdir(rogue)
        with pytest.raises(PermissionError, match="outside its recorded home"):
            verify_git_access("commit")

    @pytest.mark.parametrize("failure", [OSError, RuntimeError])
    def test_recorded_home_that_cannot_resolve_is_named(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: type[Exception]
    ) -> None:
        """Mutant: _recorded_home's except returns None — an unresolvable path is refused as "records no path".

        Mutant: the except narrowed to OSError — a 3.12 symlink-loop RuntimeError escapes as a traceback.
        """
        marker = tmp_path / "unresolvable_home"
        make_owner_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AIPASS_REGISTRY", str(tmp_path / "AIPASS_REGISTRY.json"))
        registry = {
            "metadata": {"id": OWNER_REGISTRY_ID},
            "branches": {"devpulse": {"name": "devpulse", "path": str(marker), "owner": True}},
        }
        monkeypatch.setattr("aipass.drone.apps.plugins.devpulse_ops.auth.load_registry", lambda *a, **k: registry)
        monkeypatch.setattr(
            "aipass.drone.apps.plugins.devpulse_ops.auth._resolve_location", _failing_resolve(marker, failure)
        )
        with pytest.raises(PermissionError, match="could not be resolved") as refused:
            verify_git_access("commit")
        assert "records no path" not in str(refused.value)

    def test_recorded_home_failure_is_named_for_its_own_type(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A RecursionError is a RuntimeError but not a symlink loop; the refusal names what was raised.

        Mutant: the RuntimeError arm relabels as f"symlink loop: {exc}" again — killed.
        """
        marker = tmp_path / "unresolvable_home"
        make_owner_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AIPASS_REGISTRY", str(tmp_path / "AIPASS_REGISTRY.json"))
        registry = {
            "metadata": {"id": OWNER_REGISTRY_ID},
            "branches": {"devpulse": {"name": "devpulse", "path": str(marker), "owner": True}},
        }
        monkeypatch.setattr("aipass.drone.apps.plugins.devpulse_ops.auth.load_registry", lambda *a, **k: registry)
        monkeypatch.setattr(
            "aipass.drone.apps.plugins.devpulse_ops.auth._resolve_location", _failing_resolve(marker, RecursionError)
        )
        with pytest.raises(PermissionError, match="could not be resolved") as refused:
            verify_git_access("commit")
        assert "RecursionError: simulated resolve failure" in str(refused.value)
        assert "symlink loop" not in str(refused.value)

    @pytest.mark.parametrize("failure", [OSError, RuntimeError, RecursionError])
    def test_registry_directory_that_cannot_resolve_is_refused_not_raised(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: type[Exception]
    ) -> None:
        """The registry's own directory failing to resolve is a named refusal, never a traceback out of the gate.

        Mutant: the registry-root try removed (a bare resolve, as before) — the failure escapes uncaught, killed.
        """
        make_owner_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AIPASS_REGISTRY", str(tmp_path / "AIPASS_REGISTRY.json"))
        monkeypatch.setattr(
            "aipass.drone.apps.plugins.devpulse_ops.auth._resolve_location", _failing_resolve(tmp_path, failure)
        )
        with pytest.raises(PermissionError, match="could not be resolved") as refused:
            verify_git_access("commit")
        assert f"{failure.__name__}: simulated resolve failure" in str(refused.value)
        assert "AIPASS_REGISTRY.json" in str(refused.value)

    @pytest.mark.parametrize("mode", ["enforce", "warn"])
    def test_an_unresolvable_registry_directory_is_an_authority_refusal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, mode: str
    ) -> None:
        """The refusal is of the species authority: it stands under enforcement, and the
        warn-mode rollback lifts it; the warning names the directory.

        Mutants: species changed to capability (warn raises "cannot run"); the warning removed."""
        make_owner_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AIPASS_REGISTRY", str(tmp_path / "AIPASS_REGISTRY.json"))
        monkeypatch.setenv("AIPASS_GIT_AUTH_MODE", mode)
        monkeypatch.setattr(
            "aipass.drone.apps.plugins.devpulse_ops.auth._resolve_location", _failing_resolve(tmp_path, OSError)
        )
        if mode == "warn":
            assert verify_git_access("commit") == "devpulse"
        else:
            with pytest.raises(PermissionError, match="is not authorized for 'commit'"):
                verify_git_access("commit")
        assert f"Registry directory {tmp_path} could not be resolved: OSError" in caplog.text

    def test_subdirectory_of_recorded_home_allowed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Path-binding accepts at-or-under, so working from a subdir still authorizes."""
        make_owner_project(tmp_path)
        nested = tmp_path / "apps" / "handlers"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)
        assert verify_git_access("commit") == "devpulse"

    def test_ancestor_passport_denied_from_inside_recorded_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Binding anchors to where the PASSPORT is, not where the caller stands.

        Checking CWD would authorize the walked-up forgery, since CWD is under the recorded path.
        """
        recorded = tmp_path / "devpulse"
        recorded.mkdir()
        make_owner_project(tmp_path, branch_dir=tmp_path, record_path=str(recorded))
        monkeypatch.chdir(recorded)
        with pytest.raises(PermissionError, match="outside its recorded home"):
            verify_git_access("commit")

    def test_relative_registry_path_resolves(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Registries record relative paths ('src/aipass/devpulse', 'src/vera_studio/vera')."""
        home = tmp_path / "src" / "vera_studio" / "vera"
        make_owner_project(
            tmp_path,
            branch="VERA",
            registry_name="VERA-STUDIO_REGISTRY.json",
            branch_dir=home,
            record_path="src/vera_studio/vera",
        )
        monkeypatch.chdir(home)
        assert verify_git_access("commit") == "VERA"

    def test_dict_shaped_registry_binds(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A registry authored as a dict skips the loader's normalization entirely.

        Only this shape exercises auth's own case-insensitive lookup and relative-path resolution.
        """
        home = tmp_path / "src" / "vera"
        home.mkdir(parents=True)
        (tmp_path / "VERA-STUDIO_REGISTRY.json").write_text(
            json.dumps(
                {
                    "metadata": {"id": OWNER_REGISTRY_ID},
                    "branches": {"VERA": {"name": "VERA", "path": "src/vera", "owner": True, "status": "active"}},
                }
            ),
            encoding="utf-8",
        )
        (home / ".trinity").mkdir()
        (home / ".trinity" / "passport.json").write_text(
            json.dumps(
                {
                    "branch_info": {"branch_name": "VERA"},
                    "identity": {"citizen_class": "manager"},
                    "citizenship": {"registry_id": OWNER_REGISTRY_ID},
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.chdir(home)
        assert verify_git_access("commit") == "VERA"

    def test_passport_under_recorded_ancestor_allowed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Path-binding is at-OR-UNDER, not exact match.

        Trap: a recorded repo root degrades path-binding to repo-wide.
        """
        home = tmp_path / "agents" / "devpulse"
        make_owner_project(tmp_path, branch_dir=home, record_path=str(tmp_path))
        monkeypatch.chdir(home)
        assert verify_git_access("commit") == "devpulse"

    def test_unreadable_registry_denied(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fresh clone / no registry: fail CLOSED, never silent-pass."""
        make_owner_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AIPASS_REGISTRY", str(tmp_path / "does_not_exist.json"))
        with pytest.raises(PermissionError, match="registry could not be read"):
            verify_git_access("commit")

    @pytest.mark.parametrize("command", ["status", "log", "diff"])
    def test_global_tier_never_acquires_the_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
    ) -> None:
        """Regression: read-only stays open to any citizen."""
        make_owner_project(tmp_path, branch="seedgo", citizen_class="builder", owner=False)
        monkeypatch.chdir(tmp_path)
        assert verify_git_access(command) == "seedgo"


class TestExternalRepoVerbTranslation:
    """AIPass-flow verbs must refuse honestly in an external repo, not half-run."""

    @pytest.fixture()
    def vera_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        home = make_owner_project(tmp_path, branch="VERA", registry_name="VERA-STUDIO_REGISTRY.json")
        monkeypatch.chdir(home)
        return home

    @pytest.mark.parametrize("command", ["commit", "sync", "checkout", "unlock", "tag", "dev-pr", "merge"])
    def test_portable_verbs_work(self, vera_home: Path, command: str) -> None:
        """Translated scope: these work in any git repo for its manager, each aimed at that repo."""
        assert verify_git_access(command) == "VERA"

    def test_the_refusal_and_the_help_name_exactly_the_verbs_the_gate_lets_through(self, vera_home: Path) -> None:
        """Mutant: dev-pr back on the untranslated list — the help still names it as runnable."""
        runnable = external_owner_verbs()
        with pytest.raises(PermissionError) as exc_info:
            verify_git_access("pr")

        assert "dev-pr" in runnable and "merge" in runnable and "pr" not in runnable
        assert str(exc_info.value).endswith(f"these work here: {', '.join(runnable)}.")
        assert f"own seat, runs: {', '.join(runnable)}. The rest refuse there." in " ".join(help_pages.page().split())

    @pytest.mark.parametrize("command", ["pr", "close-pr", "fix"])
    def test_aipass_flow_verbs_refuse_honestly(self, vera_home: Path, command: str) -> None:
        """These assume our dev→PR→main flow; refusing beats half-running in someone's repo."""
        with pytest.raises(PermissionError, match="not translated for external repos"):
            verify_git_access(command)

    @pytest.mark.parametrize("command", ["dev-pr", "pr", "merge", "tag", "fix"])
    def test_same_verbs_work_in_aipass(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str) -> None:
        """The refusal is scoped to external repos — AIPass's own flow is untouched."""
        make_owner_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        assert verify_git_access(command) == "devpulse"

    @pytest.mark.parametrize("command", ["pr", "close-pr", "fix"])
    def test_warn_mode_does_not_lift_an_untranslated_verb(
        self, vera_home: Path, monkeypatch: pytest.MonkeyPatch, command: str
    ) -> None:
        """Warn-mode rolls back the AUTHORITY migration, never this refusal."""
        monkeypatch.setenv("AIPASS_GIT_AUTH_MODE", "warn")
        with pytest.raises(PermissionError, match="not translated for external repos"):
            verify_git_access(command)

    def test_untranslated_refusal_does_not_call_a_proven_owner_unauthorized(self, vera_home: Path) -> None:
        """VERA cleared all four authority checks — 'not authorized' would be a false trail."""
        with pytest.raises(PermissionError) as exc_info:
            verify_git_access("pr")
        assert "not authorized" not in str(exc_info.value)
        assert "cannot run 'pr'" in str(exc_info.value)


class TestGitAuthWarnMode:
    """One env var is the rollback: warn logs the refusal and allows."""

    def test_warn_mode_allows_and_logs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        make_owner_project(tmp_path, citizen_class="builder")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AIPASS_GIT_AUTH_MODE", "warn")
        with patch("aipass.drone.apps.plugins.devpulse_ops.auth.logger") as mock_logger:
            assert verify_git_access("commit") == "devpulse"
        mock_logger.warning.assert_called_once()
        assert "would be denied" in mock_logger.warning.call_args[0][0]

    @pytest.mark.parametrize("value", ["enforce", "", "yes", "warn-only", "1"])
    def test_only_the_exact_word_warn_opens_the_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        """Anything that isn't exactly 'warn' enforces — no near-miss opens the gate."""
        make_owner_project(tmp_path, citizen_class="builder")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AIPASS_GIT_AUTH_MODE", value)
        with pytest.raises(PermissionError):
            verify_git_access("commit")

    def test_unset_env_enforces(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The DEFAULT is enforce; the parametrized test above only covers set values."""
        make_owner_project(tmp_path, citizen_class="builder")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("AIPASS_GIT_AUTH_MODE", raising=False)
        with pytest.raises(PermissionError):
            verify_git_access("commit")

    def test_warn_mode_does_not_weaken_identification(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Warn mode relaxes authorization, never identification — no passport is still no entry."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AIPASS_GIT_AUTH_MODE", "warn")
        with pytest.raises(PermissionError, match="No .trinity/passport.json"):
            verify_git_access("commit")


class TestRegistryIdIsNotASecret:
    """The registry id is readable off local disk, so it cannot carry authority alone."""

    def test_correct_tenancy_alone_does_not_authorize(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A non-owner passport with the RIGHT registry id is still governed: tenancy never grants."""
        make_owner_project(tmp_path, branch="devpulse")
        rogue = tmp_path / "rogue"
        rogue.mkdir()
        (rogue / ".trinity").mkdir()
        (rogue / ".trinity" / "passport.json").write_text(
            json.dumps(
                {
                    "branch_info": {"branch_name": "seedgo"},
                    "identity": {"citizen_class": "manager"},
                    "citizenship": {"registry_id": OWNER_REGISTRY_ID},
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.chdir(rogue)
        with pytest.raises(PermissionError):
            verify_git_access("commit")


class TestGitAccessLogSeverity:
    """Severity is owned by auth.py: designed refusals warn, real denials error."""

    def test_missing_passport_logs_info_never_warning(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Failing closed on a non-branch CWD is designed behaviour: refused, never escalated."""
        monkeypatch.chdir(tmp_path)
        with patch("aipass.drone.apps.plugins.devpulse_ops.auth.logger") as mock_logger:
            with pytest.raises(PermissionError, match="No .trinity/passport.json"):
                verify_git_access("status")
        mock_logger.info.assert_called_once()
        mock_logger.warning.assert_not_called()
        mock_logger.error.assert_not_called()

    def test_a_passport_less_read_is_refused_and_git_module_logs_it_at_info(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        with patch("aipass.drone.apps.modules.git_module.logger") as mock_logger:
            result = handle_command("status")
        assert result["exit_code"] == 1
        assert "No .trinity/passport.json" in result["stderr"]
        mock_logger.info.assert_called_once()
        mock_logger.warning.assert_not_called()

    def test_owner_tier_denial_still_logs_error(self, seedgo_dir: Path) -> None:
        """An identified branch reaching for owner-tier IS a fault — must still page."""
        with patch("aipass.drone.apps.plugins.devpulse_ops.auth.logger") as mock_logger:
            with pytest.raises(PermissionError, match="not authorized"):
                verify_git_access("commit")
        mock_logger.error.assert_called_once()

    def test_untranslated_verb_warns_instead_of_paging(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A proven owner meeting an untranslated verb is a capability gap, not a fault."""
        home = make_owner_project(tmp_path, branch="BAUD", registry_name="BAUD_REGISTRY.json")
        monkeypatch.chdir(home)
        with patch("aipass.drone.apps.plugins.devpulse_ops.auth.logger") as mock_logger:
            with pytest.raises(PermissionError, match="not translated for external repos"):
                verify_git_access("pr")
        mock_logger.warning.assert_called_once()
        mock_logger.error.assert_not_called()

    def test_git_module_does_not_duplicate_denial_error(self, repo_dir: Path) -> None:
        """git_module re-logs the denial at WARNING — auth.py already logged it authoritatively."""
        with (
            patch(
                "aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access",
                side_effect=PermissionError("nope"),
            ),
            patch("aipass.drone.apps.modules.git_module.logger") as mock_logger,
        ):
            result = handle_command("status")
        assert result["exit_code"] == 1
        assert "nope" in result["stderr"]
        mock_logger.warning.assert_called_once()
        mock_logger.error.assert_not_called()
