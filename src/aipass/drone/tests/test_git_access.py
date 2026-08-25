# =================== AIPass ====================
# Name: test_git_access.py
# Description: Tests for tier-based git access, new handlers, and PR deprecation
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-05-12
# =============================================

"""Tests for tier-based git access, new handlers (diff, log, commit, checkout), and PR deprecation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.drone.apps.plugins.devpulse_ops.auth import (
    GIT_ACCESS_TIERS,
    verify_git_access,
)
from aipass.drone.apps.handlers.git.diff_handler import get_branch_diff
from aipass.drone.apps.handlers.git.log_handler import get_git_log
from aipass.drone.apps.handlers.git.show_handler import show_object
from aipass.drone.apps.handlers.git.commit_handler import commit_changes, stage_branch_dir
from aipass.drone.apps.handlers.git.checkout_handler import checkout_branch
from aipass.drone.apps.modules.git_module import handle_command

from .conftest import OWNER_REGISTRY_ID, make_owner_project


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
def devpulse_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp project in which devpulse genuinely holds owner-tier.

    This fixture used to forge a branch name and nothing else, which is precisely
    the escalation DPLAN-0281 closed — so it now mints all four facts the gate
    checks. Tests that need one of them broken build their own via
    make_owner_project(...).
    """
    make_owner_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def seedgo_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp directory with a non-owner passport."""
    trinity = tmp_path / ".trinity"
    trinity.mkdir()
    passport = trinity / "passport.json"
    passport.write_text(
        json.dumps({"branch_info": {"branch_name": "seedgo"}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def repo_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp repo root with AIPASS_REGISTRY.json."""
    registry = tmp_path / "AIPASS_REGISTRY.json"
    registry.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ===========================================================================
# 1. GIT_ACCESS_TIERS config structure
# ===========================================================================


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
        """Owner-tier must not carry a hardcoded allowlist any more (DPLAN-0281).

        A name in this table was authority-by-string. Authority is now earned per
        repo from the caller's passport and that project's registry, which is what
        lets a project's own manager hold git without AIPass knowing their name.
        """
        assert "allowed_callers" not in GIT_ACCESS_TIERS["owner"]

    def test_pr_in_owner_tier(self) -> None:
        cmds = GIT_ACCESS_TIERS["owner"]["commands"]
        assert "pr" in cmds

    def test_prune_temp_in_owner_tier(self) -> None:
        """prune-temp deletes merged remote citizen/* branches — delete-branch class.

        It shipped in neither tier, so verify_git_access fell through to
        'Unknown git command' for every caller including the owner, while the
        help screen advertised it as global. Found in the APLAN-0003 audit,
        tier ruled by @devpulse 2026-08-13.
        """
        cmds = GIT_ACCESS_TIERS["owner"]["commands"]
        assert "prune-temp" in cmds
        assert "prune-temp" not in GIT_ACCESS_TIERS["global"]["commands"]

    def test_every_registered_command_holds_a_tier(self) -> None:
        """No command may be dispatchable without a tier — the class-level guard.

        This is the invariant prune-temp broke. Registering a verb in _COMMANDS
        and wiring it to a handler makes it *dispatchable*, never *reachable*:
        auth runs first and refuses anything it cannot find in a tier. Asserting
        the specific verb would only have caught the one instance, so assert the
        rule instead — the next verb added without a tier fails here.
        """
        from aipass.drone.apps.modules.git_module import _COMMANDS

        tiered = set(GIT_ACCESS_TIERS["global"]["commands"]) | set(GIT_ACCESS_TIERS["owner"]["commands"])
        orphaned = sorted(set(_COMMANDS) - tiered)
        assert orphaned == [], f"registered but unreachable — in no tier: {orphaned}"

    def test_no_tier_grants_a_command_that_does_not_exist(self) -> None:
        """The mirror: a tier entry with no registered command is a dead grant."""
        from aipass.drone.apps.modules.git_module import _COMMANDS

        tiered = set(GIT_ACCESS_TIERS["global"]["commands"]) | set(GIT_ACCESS_TIERS["owner"]["commands"])
        phantom = sorted(tiered - set(_COMMANDS))
        assert phantom == [], f"granted but not registered: {phantom}"


# ===========================================================================
# 2. verify_git_access — tier enforcement
# ===========================================================================


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

    def test_pr_denied_for_seedgo(self, seedgo_dir: Path) -> None:
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
        """Real git verbs drone folds into higher-level commands name their replacement.

        The refusal is correct — without the pointer it was a dead end (ERROR 26b225d3).
        """
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

    DPLAN-0281 / F59 6.3. Each test breaks exactly ONE of the four facts and
    proves the gate bites, so a future regression names which check it broke.
    """

    def test_manager_at_home_is_authorized(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The happy path: all four facts hold, owner-tier is granted."""
        make_owner_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        assert verify_git_access("commit") == "devpulse"

    def test_no_branch_is_hardcoded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A project's own manager holds git even when AIPass never heard of them.

        This is the whole point of the ruling — VERA in Vera-Studio authorizes by
        the same rule that authorizes devpulse here, with no entry in any list.
        """
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

        Asserts the SHARED loader's wording specifically. Both this layer and the
        explicit check below say "belongs to registry", so a loose match passed no
        matter which one fired — and proved neither.

        The AIPASS_REGISTRY pin is load-bearing: find_registry's cwd walk SKIPS
        registries that fail the credential check, so without it the mismatched
        fixture is passed over and resolution falls through to whatever exists
        outside the fixture — the real AIPass registry locally (mismatch, right
        wording, wrong reason) but nothing in a clean CI checkout (not-found, a
        different refusal). The env pin is priority 2, ahead of the walk, so the
        loader is forced to read THIS registry and raise its own mismatch.
        """
        make_owner_project(tmp_path, passport_registry_id="some-other-project-id")
        monkeypatch.setenv("AIPASS_REGISTRY", str(tmp_path / "AIPASS_REGISTRY.json"))
        monkeypatch.chdir(tmp_path)
        with pytest.raises(PermissionError, match="does not hold citizenship in this project's registry"):
            verify_git_access("commit")

    def test_tenancy_rechecked_when_loader_stays_silent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The explicit tenancy check is the backstop, and must refuse on its own.

        ``load_registry`` normally raises on a mismatch — but its credential check
        swallows its own exceptions and returns a silent pass, so a passport it
        fails to read reaches here unverified. Patching it to return mismatched
        data without raising is the only way to stand in that gap: with the shared
        layer quiet, this check alone decides, and it must still fail closed.

        Pinned for the same reason as test_wrong_tenancy_denied (CI 2922a685):
        this fixture's passport deliberately mismatches, so find_registry's cwd
        walk skips it and get_registry_path — which is NOT patched here — would
        otherwise resolve to whatever lives outside the fixture.
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
        """Migration boundary (F59 sec 5, row 4): a passport predating registry_id."""
        make_owner_project(tmp_path, passport_registry_id="")
        monkeypatch.chdir(tmp_path)
        with pytest.raises(PermissionError, match="no citizenship.registry_id"):
            verify_git_access("commit")

    def test_not_listed_in_registry_denied(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A manager passport for a branch this project's registry does not carry."""
        # Mint ghost's passport first, then overwrite the registry so it lists only
        # devpulse — ghost's credentials survive, their registry entry does not.
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

        Name, class, tenancy and owner flag are ALL correct — the registry id is
        readable off local disk, so a same-machine attacker can copy it. Only the
        location refuses, which is exactly why path-binding is the load-bearing check.
        """
        rogue = tmp_path / "tmp_workdir"
        make_owner_project(tmp_path, branch_dir=rogue, record_path=str(tmp_path / "real_devpulse"))
        monkeypatch.chdir(rogue)
        with pytest.raises(PermissionError, match="outside its recorded home"):
            verify_git_access("commit")

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

        The forgery sits at the repo root and the caller stands inside the real
        manager's directory, which is empty of any passport — so the walk-up
        reaches the forgery. Checking CWD would authorize it, because CWD really
        is under the recorded path. Checking the passport's own home refuses:
        standing somewhere does not make a passport found elsewhere valid there.
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

        ``_load_registry_data`` lowercases keys and absolutizes paths only for the
        LIST shape; dicts pass through as written. So this is the shape where
        case-insensitive lookup and relative-path resolution actually earn their
        keep — with a list registry the loader has already done both, and a broken
        implementation here would still pass.
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
        """Path-binding is at-OR-UNDER (F59 4.2a), not exact match.

        A registry may record an ancestor of the passport's home — a small project
        whose manager is recorded at the repo root, say. Exact-match would refuse
        them for a reason that has nothing to do with authority.

        Note this is the weaker end of the binding: the broader the recorded path,
        the more of the tree can host a forged passport. Recording the repo root
        degrades path-binding to repo-wide (reported to @devpulse for P2).
        """
        home = tmp_path / "agents" / "devpulse"
        make_owner_project(tmp_path, branch_dir=home, record_path=str(tmp_path))
        monkeypatch.chdir(home)
        assert verify_git_access("commit") == "devpulse"

    def test_unreadable_registry_denied(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fresh clone / no registry: fail CLOSED, never silent-pass (F59 4.1)."""
        make_owner_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AIPASS_REGISTRY", str(tmp_path / "does_not_exist.json"))
        with pytest.raises(PermissionError, match="registry could not be read"):
            verify_git_access("commit")

    @pytest.mark.parametrize("command", ["status", "log", "diff"])
    def test_global_tier_never_acquires_the_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
    ) -> None:
        """Regression (F59 6.3 #7): read-only stays open to any citizen."""
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

    @pytest.mark.parametrize("command", ["commit", "sync", "checkout", "unlock", "tag"])
    def test_portable_verbs_work(self, vera_home: Path, command: str) -> None:
        """Translated scope: these work in any git repo for its manager.

        'tag' joined the list in DPLAN-0290 item 1 — the handler tags that repo's
        own HEAD, so the gate no longer has a half-run to protect anyone from.
        """
        assert verify_git_access(command) == "VERA"

    @pytest.mark.parametrize("command", ["dev-pr", "pr", "merge", "fix"])
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

    @pytest.mark.parametrize("command", ["dev-pr", "pr", "merge", "fix"])
    def test_warn_mode_does_not_lift_an_untranslated_verb(
        self, vera_home: Path, monkeypatch: pytest.MonkeyPatch, command: str
    ) -> None:
        """Warn-mode rolls back the AUTHORITY migration (F59 6.1), never this refusal.

        The two were entangled: warn-mode tested one flag for every refusal, so the
        authority rollback also re-armed a half-run of OUR dev→PR→main flow inside
        someone else's repo — the exact mess _AIPASS_FLOW_VERBS exists to prevent.
        Third scope limit on warn-mode, beside identification.
        """
        monkeypatch.setenv("AIPASS_GIT_AUTH_MODE", "warn")
        with pytest.raises(PermissionError, match="not translated for external repos"):
            verify_git_access(command)

    def test_untranslated_refusal_does_not_call_a_proven_owner_unauthorized(self, vera_home: Path) -> None:
        """VERA cleared all four authority checks — 'not authorized' would be a false trail.

        The wording decides where the reader goes next: audit a passport that is
        fine, or wait for the verb to be translated.
        """
        with pytest.raises(PermissionError) as exc_info:
            verify_git_access("pr")
        assert "not authorized" not in str(exc_info.value)
        assert "cannot run 'pr'" in str(exc_info.value)


class TestGitAuthWarnMode:
    """One env var is the rollback (F59 6.1): warn logs the refusal and allows."""

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
        """The DEFAULT is enforce (F59 6.1 decision).

        Separate from the parametrized test above, which only proves that *set*
        values other than 'warn' enforce — flipping the default would sail past it.
        """
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
        """F59 6.3 #1: a non-owner passport with the RIGHT registry id is still governed.

        Proves the tenancy check did not become a backdoor — it narrows, it never grants.
        """
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
    """Severity is owned by auth.py: designed refusals warn, real denials error.

    One refusal used to log ERROR in both auth.py and git_module.py, so a single
    event produced two @trigger fingerprints 0.12s apart — suppressing one left
    the twin paging. See @trigger log-fix 906263c8ff2e / 1c8a86e955c1.
    """

    def test_missing_passport_logs_warning_not_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Failing closed on a non-branch CWD is designed behaviour, not a fault."""
        monkeypatch.chdir(tmp_path)
        with patch("aipass.drone.apps.plugins.devpulse_ops.auth.logger") as mock_logger:
            with pytest.raises(PermissionError, match="No .trinity/passport.json"):
                verify_git_access("status")
        mock_logger.warning.assert_called_once()
        mock_logger.error.assert_not_called()

    def test_owner_tier_denial_still_logs_error(self, seedgo_dir: Path) -> None:
        """An identified branch reaching for owner-tier IS a fault — must still page."""
        with patch("aipass.drone.apps.plugins.devpulse_ops.auth.logger") as mock_logger:
            with pytest.raises(PermissionError, match="not authorized"):
                verify_git_access("commit")
        mock_logger.error.assert_called_once()

    def test_untranslated_verb_warns_instead_of_paging(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A proven owner meeting an untranslated verb is a capability gap, not a fault.

        Live incident (@trigger error 38439475, 2026-08-24): BAUD ran `pr` in its own
        repo, cleared every authority check, hit the untranslated-verb wall — and the
        refusal logged ERROR, paging @drone about a gate working exactly as designed.
        """
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


# ===========================================================================
# 3. diff_handler
# ===========================================================================


class TestDiffHandler:
    """Scoped git diff tests."""

    def test_basic_diff(self, repo_dir: Path) -> None:
        diff_output = (
            "diff --git a/src/aipass/api/foo.py b/src/aipass/api/foo.py\n"
            "--- a/src/aipass/api/foo.py\n"
            "+++ b/src/aipass/api/foo.py\n"
            "@@ -1,3 +1,4 @@\n"
            "+new line\n"
            "diff --git a/src/aipass/drone/bar.py b/src/aipass/drone/bar.py\n"
            "--- a/src/aipass/drone/bar.py\n"
            "+++ b/src/aipass/drone/bar.py\n"
        )
        mock_result = MagicMock(returncode=0, stdout=diff_output, stderr="")
        branch_dir = repo_dir / "src" / "aipass" / "api"

        with patch("aipass.drone.apps.handlers.git.diff_handler.subprocess.run", return_value=mock_result):
            result = get_branch_diff(branch_dir)

        assert result["files_changed"] == 1
        assert "src/aipass/api/foo.py" in result["diff"]
        assert "src/aipass/drone/bar.py" not in result["diff"]

    def test_staged_diff(self, repo_dir: Path) -> None:
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        branch_dir = repo_dir / "src" / "aipass" / "api"

        with patch("aipass.drone.apps.handlers.git.diff_handler.subprocess.run", return_value=mock_result) as mock_run:
            get_branch_diff(branch_dir, staged=True)

        cmd = mock_run.call_args[0][0]
        assert "--staged" in cmd

    def test_empty_diff(self, repo_dir: Path) -> None:
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        branch_dir = repo_dir / "src" / "aipass" / "api"

        with patch("aipass.drone.apps.handlers.git.diff_handler.subprocess.run", return_value=mock_result):
            result = get_branch_diff(branch_dir)

        assert result["files_changed"] == 0
        assert result["diff"] == ""

    def test_git_failure(self, repo_dir: Path) -> None:
        mock_result = MagicMock(returncode=128, stderr="fatal: not a git repo", stdout="")
        branch_dir = repo_dir / "src" / "aipass" / "api"

        with patch("aipass.drone.apps.handlers.git.diff_handler.subprocess.run", return_value=mock_result):
            result = get_branch_diff(branch_dir)

        assert result["files_changed"] == 0
        assert "error" in result["message"].lower()

    def test_os_error(self, repo_dir: Path) -> None:
        branch_dir = repo_dir / "src" / "aipass" / "api"

        with patch("aipass.drone.apps.handlers.git.diff_handler.subprocess.run", side_effect=OSError("git not found")):
            result = get_branch_diff(branch_dir)

        assert result["files_changed"] == 0
        assert "failed" in result["message"].lower()


# ===========================================================================
# 4. log_handler
# ===========================================================================


class TestLogHandler:
    """Git log tests."""

    def test_basic_log(self, repo_dir: Path) -> None:
        log_output = "abc1234 feat: first\ndef5678 fix: second\n"
        mock_result = MagicMock(returncode=0, stdout=log_output, stderr="")

        with patch("aipass.drone.apps.handlers.git.log_handler.subprocess.run", return_value=mock_result):
            result = get_git_log(count=5)

        assert result["count"] == 2
        assert len(result["entries"]) == 2

    def test_custom_count_passed_to_git(self, repo_dir: Path) -> None:
        mock_result = MagicMock(returncode=0, stdout="", stderr="")

        with patch("aipass.drone.apps.handlers.git.log_handler.subprocess.run", return_value=mock_result) as mock_run:
            get_git_log(count=25)

        cmd = mock_run.call_args[0][0]
        assert "-25" in cmd

    def test_git_failure(self, repo_dir: Path) -> None:
        mock_result = MagicMock(returncode=128, stderr="fatal: bad default", stdout="")

        with patch("aipass.drone.apps.handlers.git.log_handler.subprocess.run", return_value=mock_result):
            result = get_git_log()

        assert result["count"] == 0
        assert "error" in result["message"].lower()

    def test_os_error(self, repo_dir: Path) -> None:
        with patch("aipass.drone.apps.handlers.git.log_handler.subprocess.run", side_effect=OSError("git not found")):
            result = get_git_log()

        assert result["count"] == 0
        assert "failed" in result["message"].lower()


# ===========================================================================
# 5. commit_handler
# ===========================================================================


class TestShowHandler:
    """git show — reading history at global read tier.

    Requested by @seedgo via @devpulse 2026-08-13: auditing a bypass prune means
    reading what was DELETED, and status/diff/log only show the present. Reading
    history is not a write, so every citizen auditing its own past can do it.
    """

    def test_show_ref_only(self, repo_dir: Path) -> None:
        mock_result = MagicMock(returncode=0, stdout="commit abc1234\n\n    feat: thing\n", stderr="")

        with patch("aipass.drone.apps.handlers.git.show_handler.subprocess.run", return_value=mock_result) as run:
            result = show_object("abc1234")

        assert result["success"] is True
        assert "feat: thing" in result["content"]
        assert run.call_args[0][0] == ["git", "show", "abc1234"]

    def test_show_ref_with_path_uses_colon_form(self, repo_dir: Path) -> None:
        """`show <ref> <path>` must read the file AT that commit, not the diff."""
        mock_result = MagicMock(returncode=0, stdout='{"bypass": []}\n', stderr="")

        with patch("aipass.drone.apps.handlers.git.show_handler.subprocess.run", return_value=mock_result) as run:
            result = show_object("abc1234", "src/aipass/prax/.seedgo/bypass.json")

        assert result["success"] is True
        assert run.call_args[0][0] == ["git", "show", "abc1234:src/aipass/prax/.seedgo/bypass.json"]

    def test_show_is_not_scoped_to_callers_branch(self, repo_dir: Path) -> None:
        """A path outside the caller's own branch must be readable.

        The whole point is @seedgo verifying @prax's prune. Scoping this to the
        caller's directory the way status/diff/log do would refuse exactly the
        use case it was granted for.
        """
        mock_result = MagicMock(returncode=0, stdout="content", stderr="")

        with patch("aipass.drone.apps.handlers.git.show_handler.subprocess.run", return_value=mock_result) as run:
            result = show_object("HEAD~5", "src/aipass/memory/apps/memory.py")

        assert result["success"] is True
        assert "src/aipass/memory/apps/memory.py" in run.call_args[0][0][2]

    def test_ref_that_git_would_read_as_a_flag_is_refused(self, repo_dir: Path) -> None:
        """Refuse before any argv is built — the tag_handler lesson (S49)."""
        for bad in ("", "-n", "--output=/tmp/x", "-"):
            result = show_object(bad)
            assert result["success"] is False, f"accepted flag-like ref {bad!r}"
            assert "content" in result

    def test_path_that_git_would_read_as_a_flag_is_refused(self, repo_dir: Path) -> None:
        result = show_object("abc1234", "--output=/tmp/pwned")
        assert result["success"] is False

    def test_git_failure_reports_honestly(self, repo_dir: Path) -> None:
        mock_result = MagicMock(returncode=128, stdout="", stderr="fatal: bad object deadbeef")

        with patch("aipass.drone.apps.handlers.git.show_handler.subprocess.run", return_value=mock_result):
            result = show_object("deadbeef")

        assert result["success"] is False
        assert "bad object" in result["message"]

    def test_subprocess_error_is_caught(self, repo_dir: Path) -> None:
        with patch(
            "aipass.drone.apps.handlers.git.show_handler.subprocess.run",
            side_effect=OSError("git missing"),
        ):
            result = show_object("abc1234")

        assert result["success"] is False
        assert "git missing" in result["message"]


class TestShowCommandRouting:
    """`drone @git show` reaches the handler at global tier."""

    def test_show_is_global_tier(self) -> None:
        assert "show" in GIT_ACCESS_TIERS["global"]["commands"]
        assert "show" not in GIT_ACCESS_TIERS["owner"]["commands"]

    def test_non_owner_may_show(self, seedgo_dir: Path) -> None:
        """The requesting citizen is a non-owner — that is the whole point."""
        assert verify_git_access("show") == "seedgo"

    def test_show_dispatches_to_handler(self, seedgo_dir: Path) -> None:
        with patch("aipass.drone.apps.modules.git_module.show_handler.show_object") as mock_show:
            mock_show.return_value = {"success": True, "content": "file body", "message": "ok"}
            result = handle_command("show", ["abc1234", "some/path.py"])

        mock_show.assert_called_once_with("abc1234", "some/path.py")
        assert result["exit_code"] == 0
        assert result["stdout"] == "file body"

    def test_show_without_ref_returns_usage(self, seedgo_dir: Path) -> None:
        result = handle_command("show", [])
        assert result["exit_code"] == 1
        assert "Usage" in result["stderr"]


class TestStageBranchDir:
    """Shared staging utility tests."""

    def test_stage_success(self, repo_dir: Path) -> None:
        mock_result = MagicMock(returncode=0, stderr="")
        branch_dir = repo_dir / "src" / "aipass" / "api"

        with patch("aipass.drone.apps.handlers.git.commit_handler.subprocess.run", return_value=mock_result):
            result = stage_branch_dir(branch_dir, repo_dir)

        assert result["success"] is True

    def test_stage_failure(self, repo_dir: Path) -> None:
        mock_result = MagicMock(returncode=1, stderr="fatal: pathspec error")
        branch_dir = repo_dir / "src" / "aipass" / "api"

        with patch("aipass.drone.apps.handlers.git.commit_handler.subprocess.run", return_value=mock_result):
            result = stage_branch_dir(branch_dir, repo_dir)

        assert result["success"] is False
        assert "failed" in result["message"].lower()


def _assert_ordered_calls(mock_run: MagicMock, expected: list[tuple[tuple[str, ...], tuple[str, ...]]]) -> None:
    """Assert subprocess.run's recorded calls match expected (required, forbidden) argv markers, in order.

    An ordered side_effect list feeds canned results by position, not by argv match. If
    commit_handler gains, drops, or reorders a subprocess call, a canned result silently
    feeds the wrong step and the test can keep passing while testing nonsense. This checks
    the real argv at each position against the step it was written for.
    """
    calls = mock_run.call_args_list
    assert len(calls) == len(expected), (
        f"expected {len(expected)} subprocess.run calls, got {len(calls)}: {[c.args[0] for c in calls]}"
    )
    for call, (required, forbidden) in zip(calls, expected):
        argv = call.args[0]
        for marker in required:
            assert marker in argv, f"expected {marker!r} in argv {argv!r} (call order mismatch?)"
        for marker in forbidden:
            assert marker not in argv, f"unexpected {marker!r} in argv {argv!r} (call order mismatch?)"


_RUFF_FIX = (("check", "--fix"), ())
_RUFF_FORMAT = (("format",), ("--fix",))
_RUFF_GATE = (("check",), ("--fix",))
_GIT_STATUS = (("status", "--porcelain"), ())
_PYTEST = (("-m", "pytest"), ())
_GIT_ADD_ALL = (("add", "-A"), ())
_GIT_DIFF_CACHED = (("diff", "--cached"), ())
_GIT_COMMIT = (("commit", "-m"), ())


class TestCommitChanges:
    """Commit handler tests."""

    def test_commit_staged(self, repo_dir: Path) -> None:
        mock_diff = MagicMock(returncode=1, stdout="", stderr="")
        mock_commit = MagicMock(returncode=0, stdout="[main abc123] test commit", stderr="")

        with patch(
            "aipass.drone.apps.handlers.git.commit_handler.subprocess.run",
            side_effect=[mock_diff, mock_commit],
        ) as mock_run:
            result = commit_changes("test commit")

        assert result["exit_code"] == 0
        assert "abc123" in result["stdout"]
        _assert_ordered_calls(mock_run, [_GIT_DIFF_CACHED, _GIT_COMMIT])

    def test_commit_nothing_staged(self, repo_dir: Path) -> None:
        mock_diff = MagicMock(returncode=0, stdout="", stderr="")

        with patch("aipass.drone.apps.handlers.git.commit_handler.subprocess.run", return_value=mock_diff):
            result = commit_changes("test commit")

        assert result["exit_code"] == 1
        assert "nothing to commit" in result["stderr"].lower()

    def test_commit_all_stages_first(self, repo_dir: Path) -> None:
        mock_ruff_fix = MagicMock(returncode=0, stdout="", stderr="")
        mock_ruff_format = MagicMock(returncode=0, stdout="", stderr="")
        mock_ruff_gate = MagicMock(returncode=0, stdout="", stderr="")
        mock_status = MagicMock(returncode=0, stdout=" M src/aipass/api/app.py\n", stderr="")
        mock_add = MagicMock(returncode=0, stderr="")
        mock_diff = MagicMock(returncode=1, stdout="", stderr="")
        mock_commit = MagicMock(returncode=0, stdout="[main def456] all commit", stderr="")

        branch_dir = repo_dir / "src" / "aipass" / "api"

        with (
            patch("shutil.which", return_value="/usr/bin/ruff"),
            patch(
                "aipass.drone.apps.handlers.git.commit_handler.subprocess.run",
                side_effect=[
                    mock_ruff_fix,
                    mock_ruff_format,
                    mock_ruff_gate,
                    mock_status,
                    mock_add,
                    mock_diff,
                    mock_commit,
                ],
            ) as mock_run,
        ):
            result = commit_changes("all commit", branch_dir=branch_dir, all_files=True)

        assert result["exit_code"] == 0
        _assert_ordered_calls(
            mock_run,
            [_RUFF_FIX, _RUFF_FORMAT, _RUFF_GATE, _GIT_STATUS, _GIT_ADD_ALL, _GIT_DIFF_CACHED, _GIT_COMMIT],
        )

    def test_commit_all_blocks_on_test_failure(self, repo_dir: Path) -> None:
        mock_ruff_fix = MagicMock(returncode=0, stdout="", stderr="")
        mock_ruff_format = MagicMock(returncode=0, stdout="", stderr="")
        mock_ruff_gate = MagicMock(returncode=0, stdout="", stderr="")
        mock_status = MagicMock(
            returncode=0,
            stdout=" M src/aipass/drone/apps/handlers/git/commit_handler.py\n",
            stderr="",
        )
        mock_pytest = MagicMock(
            returncode=1,
            stdout="FAILED test_foo.py::test_bar - assert 1 == 2\n1 failed",
            stderr="",
        )

        drone_dir = repo_dir / "src" / "aipass" / "drone"
        drone_dir.mkdir(parents=True)
        (drone_dir / ".trinity").mkdir()
        test_dir = drone_dir / "tests"
        test_dir.mkdir()

        with (
            patch("shutil.which", return_value="/usr/bin/ruff"),
            patch(
                "aipass.drone.apps.handlers.git.commit_handler.subprocess.run",
                side_effect=[mock_ruff_fix, mock_ruff_format, mock_ruff_gate, mock_status, mock_pytest],
            ) as mock_run,
        ):
            result = commit_changes("fail commit", all_files=True)

        assert result["exit_code"] == 1
        assert "Test failures" in result["stderr"]
        assert "drone" in result["stderr"]
        _assert_ordered_calls(mock_run, [_RUFF_FIX, _RUFF_FORMAT, _RUFF_GATE, _GIT_STATUS, _PYTEST])

    def test_commit_all_passes_with_green_tests(self, repo_dir: Path) -> None:
        mock_ruff_fix = MagicMock(returncode=0, stdout="", stderr="")
        mock_ruff_format = MagicMock(returncode=0, stdout="", stderr="")
        mock_ruff_gate = MagicMock(returncode=0, stdout="", stderr="")
        mock_status = MagicMock(
            returncode=0,
            stdout=" M src/aipass/drone/apps/handlers/git/commit_handler.py\n",
            stderr="",
        )
        mock_pytest = MagicMock(returncode=0, stdout="3 passed", stderr="")
        mock_add = MagicMock(returncode=0, stderr="")
        mock_diff = MagicMock(returncode=1, stdout="", stderr="")
        mock_commit = MagicMock(returncode=0, stdout="[main abc999] green commit", stderr="")

        drone_dir = repo_dir / "src" / "aipass" / "drone"
        drone_dir.mkdir(parents=True)
        (drone_dir / ".trinity").mkdir()
        test_dir = drone_dir / "tests"
        test_dir.mkdir()

        with (
            patch("shutil.which", return_value="/usr/bin/ruff"),
            patch(
                "aipass.drone.apps.handlers.git.commit_handler.subprocess.run",
                side_effect=[
                    mock_ruff_fix,
                    mock_ruff_format,
                    mock_ruff_gate,
                    mock_status,
                    mock_pytest,
                    mock_add,
                    mock_diff,
                    mock_commit,
                ],
            ) as mock_run,
        ):
            result = commit_changes("green commit", all_files=True)

        assert result["exit_code"] == 0
        _assert_ordered_calls(
            mock_run,
            [_RUFF_FIX, _RUFF_FORMAT, _RUFF_GATE, _GIT_STATUS, _PYTEST, _GIT_ADD_ALL, _GIT_DIFF_CACHED, _GIT_COMMIT],
        )

    def test_commit_all_skips_branches_without_tests(self, repo_dir: Path) -> None:
        mock_ruff_fix = MagicMock(returncode=0, stdout="", stderr="")
        mock_ruff_format = MagicMock(returncode=0, stdout="", stderr="")
        mock_ruff_gate = MagicMock(returncode=0, stdout="", stderr="")
        mock_status = MagicMock(
            returncode=0,
            stdout=" M src/aipass/flow/apps/module.py\n",
            stderr="",
        )
        mock_add = MagicMock(returncode=0, stderr="")
        mock_diff = MagicMock(returncode=1, stdout="", stderr="")
        mock_commit = MagicMock(returncode=0, stdout="[main skip77] no tests", stderr="")

        with (
            patch("shutil.which", return_value="/usr/bin/ruff"),
            patch(
                "aipass.drone.apps.handlers.git.commit_handler.subprocess.run",
                side_effect=[
                    mock_ruff_fix,
                    mock_ruff_format,
                    mock_ruff_gate,
                    mock_status,
                    mock_add,
                    mock_diff,
                    mock_commit,
                ],
            ) as mock_run,
        ):
            result = commit_changes("no tests commit", all_files=True)

        assert result["exit_code"] == 0
        _assert_ordered_calls(
            mock_run,
            [_RUFF_FIX, _RUFF_FORMAT, _RUFF_GATE, _GIT_STATUS, _GIT_ADD_ALL, _GIT_DIFF_CACHED, _GIT_COMMIT],
        )

    def test_commit_os_error(self, repo_dir: Path) -> None:
        mock_diff = MagicMock(returncode=1, stdout="", stderr="")

        with patch(
            "aipass.drone.apps.handlers.git.commit_handler.subprocess.run",
            side_effect=[mock_diff, OSError("git not found")],
        ) as mock_run:
            result = commit_changes("test commit")

        assert result["exit_code"] == 1
        assert "failed" in result["stderr"].lower()
        _assert_ordered_calls(mock_run, [_GIT_DIFF_CACHED, _GIT_COMMIT])


# ===========================================================================
# 6. checkout_handler
# ===========================================================================


class TestCheckoutHandler:
    """Branch checkout with hard guard tests."""

    def test_checkout_main_allowed(self, repo_dir: Path) -> None:
        mock_status = MagicMock(returncode=0, stdout="", stderr="")
        mock_checkout = MagicMock(returncode=0, stdout="", stderr="Switched to branch 'main'")

        with patch(
            "aipass.drone.apps.handlers.git.checkout_handler.subprocess.run",
            side_effect=[mock_status, mock_checkout],
        ):
            result = checkout_branch("main")

        assert result["exit_code"] == 0
        assert result["current_branch"] == "main"

    def test_checkout_dev_allowed(self, repo_dir: Path) -> None:
        mock_status = MagicMock(returncode=0, stdout="", stderr="")
        mock_checkout = MagicMock(returncode=0, stdout="", stderr="Switched to branch 'dev'")

        with patch(
            "aipass.drone.apps.handlers.git.checkout_handler.subprocess.run",
            side_effect=[mock_status, mock_checkout],
        ):
            result = checkout_branch("dev")

        assert result["exit_code"] == 0
        assert result["current_branch"] == "dev"

    def test_checkout_feature_branch_denied(self) -> None:
        result = checkout_branch("feat/my-feature")
        assert result["exit_code"] == 1
        assert "denied" in result["stderr"].lower()
        assert result["current_branch"] == ""

    def test_checkout_arbitrary_branch_denied(self) -> None:
        result = checkout_branch("release/v2")
        assert result["exit_code"] == 1
        assert "denied" in result["stderr"].lower()

    def test_checkout_dirty_tree_aborts(self, repo_dir: Path) -> None:
        mock_status = MagicMock(returncode=0, stdout=" M some/file.py\n", stderr="")

        with patch("aipass.drone.apps.handlers.git.checkout_handler.subprocess.run", return_value=mock_status):
            result = checkout_branch("main")

        assert result["exit_code"] == 1
        assert "uncommitted" in result["stderr"].lower()

    def test_checkout_git_failure(self, repo_dir: Path) -> None:
        mock_status = MagicMock(returncode=0, stdout="", stderr="")
        mock_checkout = MagicMock(returncode=1, stdout="", stderr="error: pathspec 'main' did not match")
        mock_create = MagicMock(returncode=0, stdout="Switched to a new branch 'main'", stderr="")

        with patch(
            "aipass.drone.apps.handlers.git.checkout_handler.subprocess.run",
            side_effect=[mock_status, mock_checkout, mock_create],
        ):
            result = checkout_branch("main")

        assert result["exit_code"] == 0
        assert result["current_branch"] == "main"


# ===========================================================================
# 7. PR deprecation through handle_command
# ===========================================================================


class TestPrCommand:
    """PR command routes to create_branch_pr for authorized callers."""

    def test_pr_no_args_shows_usage(self, devpulse_dir: Path) -> None:
        result = handle_command("pr")
        assert result["exit_code"] == 1
        assert "usage" in result["stderr"].lower()

    @patch("aipass.drone.apps.handlers.git.dev_pr_handler.create_branch_pr")
    def test_pr_with_description_calls_handler(self, mock_pr: MagicMock, devpulse_dir: Path) -> None:
        mock_pr.return_value = {"success": True, "message": "PR created", "pr_url": "https://example.com"}
        handle_command("pr", ["test description"])
        mock_pr.assert_called_once()


# ===========================================================================
# 8. New commands via handle_command routing
# ===========================================================================


class TestNewCommandRouting:
    """Verify new commands route through handle_command correctly."""

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    def test_diff_routes(self, _mock_auth: MagicMock, repo_dir: Path) -> None:
        trinity = repo_dir / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text(json.dumps({"branch_info": {"branch_name": "test_branch"}}))

        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("aipass.drone.apps.handlers.git.diff_handler.subprocess.run", return_value=mock_result):
            result = handle_command("diff")
        assert result["exit_code"] == 0

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    def test_log_routes(self, _mock_auth: MagicMock, repo_dir: Path) -> None:
        mock_result = MagicMock(returncode=0, stdout="abc123 test\n", stderr="")
        with patch("aipass.drone.apps.handlers.git.log_handler.subprocess.run", return_value=mock_result):
            result = handle_command("log")
        assert result["exit_code"] == 0
        assert "abc123" in result["stdout"]

    @pytest.mark.parametrize(
        ("args", "expected_flag"),
        [
            (["20"], "-20"),
            (["-n", "20"], "-20"),
            (["--count", "20"], "-20"),
            (["--max-count", "20"], "-20"),
            (["-20"], "-20"),
            ([], "-10"),
        ],
    )
    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    def test_log_count_arg_forms(
        self, _mock_auth: MagicMock, repo_dir: Path, args: list[str], expected_flag: str
    ) -> None:
        """All git count idioms resolve to the same -N flag. `-20` used to emit `--20` (git fatal)."""
        mock_result = MagicMock(returncode=0, stdout="abc123 test\n", stderr="")
        with patch("aipass.drone.apps.handlers.git.log_handler.subprocess.run", return_value=mock_result) as mock_run:
            result = handle_command("log", args)
        assert result["exit_code"] == 0
        assert mock_run.call_args[0][0] == ["git", "log", "--oneline", expected_flag]

    @pytest.mark.parametrize("flag", ["-n", "--count", "--max-count"])
    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    def test_log_count_flags_log_no_warning(self, _mock_auth: MagicMock, repo_dir: Path, flag: str) -> None:
        """Count flags are skipped silently — they used to warn, polluting the logs @trigger watches."""
        mock_result = MagicMock(returncode=0, stdout="abc123 test\n", stderr="")
        with (
            patch("aipass.drone.apps.handlers.git.log_handler.subprocess.run", return_value=mock_result),
            patch("aipass.drone.apps.modules.git_module.logger") as mock_logger,
        ):
            handle_command("log", [flag, "20"])
        mock_logger.warning.assert_not_called()

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    def test_log_unknown_arg_still_warns(self, _mock_auth: MagicMock, repo_dir: Path) -> None:
        """Genuinely unparseable args still warn — the fix narrows the noise, it doesn't silence it."""
        mock_result = MagicMock(returncode=0, stdout="abc123 test\n", stderr="")
        with (
            patch("aipass.drone.apps.handlers.git.log_handler.subprocess.run", return_value=mock_result),
            patch("aipass.drone.apps.modules.git_module.logger") as mock_logger,
        ):
            handle_command("log", ["--bogus"])
        mock_logger.warning.assert_called_once()

    @pytest.mark.parametrize("bad_count", ["0", "-n 0"])
    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    def test_log_rejects_non_positive_count(self, _mock_auth: MagicMock, repo_dir: Path, bad_count: str) -> None:
        """Zero/negative count fails honestly instead of handing git a bad flag."""
        result = handle_command("log", bad_count.split())
        assert result["exit_code"] == 1
        assert "must be 1 or greater" in result["stderr"]

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="devpulse")
    def test_commit_no_args_error(self, _mock_auth: MagicMock) -> None:
        result = handle_command("commit")
        assert result["exit_code"] == 1
        assert "usage" in result["stderr"].lower()

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="devpulse")
    def test_checkout_no_args_error(self, _mock_auth: MagicMock) -> None:
        result = handle_command("checkout")
        assert result["exit_code"] == 1
        assert "usage" in result["stderr"].lower()

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="devpulse")
    def test_checkout_routes_to_handler(self, _mock_auth: MagicMock, repo_dir: Path) -> None:
        mock_status = MagicMock(returncode=0, stdout="", stderr="")
        mock_checkout = MagicMock(returncode=0, stdout="", stderr="")
        with patch(
            "aipass.drone.apps.handlers.git.checkout_handler.subprocess.run",
            side_effect=[mock_status, mock_checkout],
        ):
            result = handle_command("checkout", ["main"])
        assert result["exit_code"] == 0

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="devpulse")
    def test_checkout_guard_rejects_feature(self, _mock_auth: MagicMock) -> None:
        result = handle_command("checkout", ["feat/bad"])
        assert result["exit_code"] == 1
        assert "denied" in result["stderr"].lower()


# ===========================================================================
# 9. Help text includes new commands and tiers
# ===========================================================================


class TestUpdatedHelp:
    """Help and introspection reflect new commands and tiers."""

    def test_help_includes_diff(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        text = get_help()
        assert "diff" in text

    def test_help_includes_log(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        text = get_help()
        assert "log" in text

    def test_help_includes_commit(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        text = get_help()
        assert "commit" in text

    def test_help_includes_checkout(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        text = get_help()
        assert "checkout" in text

    def test_help_shows_tier_sections(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        text = get_help()
        assert "global" in text.lower()
        assert "owner" in text.lower()

    def test_help_includes_pr_command(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        text = get_help()
        assert "pr" in text.lower()

    def test_introspection_includes_new_handlers(self) -> None:
        from aipass.drone.apps.modules.git_module import get_introspective

        text = get_introspective()
        assert "diff_handler" in text
        assert "log_handler" in text
        assert "commit_handler" in text
        assert "checkout_handler" in text

    def test_introspection_shows_tiers(self) -> None:
        from aipass.drone.apps.modules.git_module import get_introspective

        text = get_introspective()
        assert "global" in text.lower()
        assert "owner" in text.lower()


# ===========================================================================
# 10. gh passthrough commands (issue, run, workflow)
# ===========================================================================


class TestGhPassthroughTierConfig:
    """Passthrough commands are in the global tier."""

    def test_issue_in_global_tier(self) -> None:
        assert "issue" in GIT_ACCESS_TIERS["global"]["commands"]

    def test_run_in_global_tier(self) -> None:
        assert "run" in GIT_ACCESS_TIERS["global"]["commands"]

    def test_workflow_in_global_tier(self) -> None:
        assert "workflow" in GIT_ACCESS_TIERS["global"]["commands"]

    def test_passthrough_not_in_owner_tier(self) -> None:
        owner_cmds = GIT_ACCESS_TIERS["owner"]["commands"]
        assert "issue" not in owner_cmds
        assert "run" not in owner_cmds
        assert "workflow" not in owner_cmds


class TestGhPassthroughAccess:
    """Global-tier access for passthrough commands."""

    def test_issue_allowed_for_any_branch(self, seedgo_dir: Path) -> None:
        assert verify_git_access("issue") == "seedgo"

    def test_run_allowed_for_any_branch(self, seedgo_dir: Path) -> None:
        assert verify_git_access("run") == "seedgo"

    def test_workflow_allowed_for_any_branch(self, seedgo_dir: Path) -> None:
        assert verify_git_access("workflow") == "seedgo"


class TestGhPassthroughRouting:
    """handle_command routes passthrough to subprocess."""

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    @patch("aipass.drone.apps.modules.git_module.subprocess.run")
    def test_issue_list(self, mock_run: MagicMock, _mock_auth: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="Issue #1\nIssue #2\n", stderr="")
        result = handle_command("issue", ["list"])
        assert result["exit_code"] == 0
        assert "Issue #1" in result["stdout"]
        mock_run.assert_called_once_with(
            ["gh", "issue", "list"],
            capture_output=True,
            text=True,
            timeout=60,
        )

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    @patch("aipass.drone.apps.modules.git_module.subprocess.run")
    def test_run_list(self, mock_run: MagicMock, _mock_auth: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="run 123\n", stderr="")
        result = handle_command("run", ["list"])
        assert result["exit_code"] == 0
        mock_run.assert_called_once_with(
            ["gh", "run", "list"],
            capture_output=True,
            text=True,
            timeout=60,
        )

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    @patch("aipass.drone.apps.modules.git_module.subprocess.run")
    def test_workflow_list(self, mock_run: MagicMock, _mock_auth: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="CI workflow\n", stderr="")
        result = handle_command("workflow", ["list"])
        assert result["exit_code"] == 0
        mock_run.assert_called_once_with(
            ["gh", "workflow", "list"],
            capture_output=True,
            text=True,
            timeout=60,
        )

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    @patch("aipass.drone.apps.modules.git_module.subprocess.run")
    def test_passthrough_no_args(self, mock_run: MagicMock, _mock_auth: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="usage info\n", stderr="")
        result = handle_command("issue")
        assert result["exit_code"] == 0
        mock_run.assert_called_once_with(
            ["gh", "issue"],
            capture_output=True,
            text=True,
            timeout=60,
        )

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    @patch("aipass.drone.apps.modules.git_module.subprocess.run")
    def test_passthrough_returns_stderr(self, mock_run: MagicMock, _mock_auth: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not authenticated")
        result = handle_command("issue", ["list"])
        assert result["exit_code"] == 1
        assert "not authenticated" in result["stderr"]

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    @patch("aipass.drone.apps.modules.git_module.subprocess.run", side_effect=FileNotFoundError("gh"))
    def test_passthrough_gh_not_found(self, _mock_run: MagicMock, _mock_auth: MagicMock) -> None:
        result = handle_command("issue", ["list"])
        assert result["exit_code"] == 1
        assert "gh CLI not found" in result["stderr"]

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    @patch(
        "aipass.drone.apps.modules.git_module.subprocess.run",
        side_effect=__import__("subprocess").TimeoutExpired(["gh", "issue"], 60),
    )
    def test_passthrough_timeout(self, _mock_run: MagicMock, _mock_auth: MagicMock) -> None:
        result = handle_command("issue", ["list"])
        assert result["exit_code"] == 1
        assert "timed out" in result["stderr"]

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    @patch("aipass.drone.apps.modules.git_module.subprocess.run")
    def test_passthrough_multiple_args(self, mock_run: MagicMock, _mock_auth: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        handle_command("issue", ["create", "--title", "Bug", "--body", "Details"])
        mock_run.assert_called_once_with(
            ["gh", "issue", "create", "--title", "Bug", "--body", "Details"],
            capture_output=True,
            text=True,
            timeout=60,
        )


class TestGhPassthroughHelp:
    """Help text includes passthrough commands."""

    def test_help_includes_issue(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        assert "issue" in get_help()

    def test_help_includes_run(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        assert "run" in get_help()

    def test_help_includes_workflow(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        assert "workflow" in get_help()

    def test_per_command_help_issue(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        text = get_help("issue")
        assert "gh issue" in text
        assert "global" in text.lower()

    def test_per_command_help_run(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        text = get_help("run")
        assert "gh run" in text

    def test_per_command_help_workflow(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        text = get_help("workflow")
        assert "gh workflow" in text

    def test_introspection_includes_passthrough(self) -> None:
        from aipass.drone.apps.modules.git_module import get_introspective

        text = get_introspective()
        assert "issue" in text
        assert "run" in text
        assert "workflow" in text
