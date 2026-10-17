# =================== AIPass ====================
# Name: test_identity_fence.py
# Description: Tests for the caller identity fence (no branch under caller = refuse)
# Version: 1.0.2
# Created: 2026-08-21
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/users/branch_detection.py and the fence it enforces fleetwide."""

# AIPASS_CALLER_CWD is the evidence of where the caller stood: set and outside any branch,
# every verb refuses, and a claim in AIPASS_CALLER_BRANCH cannot outvote it.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(windows_compat) — the sys.platform == "win32" stdout/stderr reconfigure block

from pathlib import Path

import json

import pytest

from aipass.ai_mail.apps import ai_mail as entry
from aipass.ai_mail.apps.handlers.users import branch_detection as bd
from aipass.ai_mail.apps.handlers.users.branch_detection import detect_branch_from_pwd
from aipass.ai_mail.apps.handlers.users.user import get_current_user
from aipass.ai_mail.apps.handlers.users.verified_caller import resolve_verified_caller


@pytest.fixture(autouse=True)
def _clear_caller_env(monkeypatch):
    """Every test states its own caller env — an ambient one would decide for it."""
    monkeypatch.delenv("AIPASS_CALLER_BRANCH", raising=False)
    monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
    monkeypatch.delenv("AIPASS_CALLER_IDENTITY_SOURCE", raising=False)


def _non_branch_dir(tmp_path: Path) -> Path:
    """A directory with no .trinity/passport.json at or above it."""
    d = tmp_path / "not_a_branch"
    d.mkdir()
    return d


class TestCallerCwdOutranksClaim:
    """A branch CLAIM cannot survive cwd evidence that the caller stood outside."""

    def test_detect_refuses_when_caller_cwd_is_not_a_branch(self, tmp_path, monkeypatch):
        """At the repo root the project dir name collides with the @aipass citizen; nothing may resolve."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "aipass")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(_non_branch_dir(tmp_path)))
        assert detect_branch_from_pwd() is None

    def test_get_current_user_raises_from_non_branch_cwd(self, tmp_path, monkeypatch):
        """Every route funnels here, and here already says NO FALLBACKS."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "aipass")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(_non_branch_dir(tmp_path)))
        with pytest.raises(RuntimeError, match="BRANCH DETECTION FAILED"):
            get_current_user()

    def test_failure_reason_names_the_cwd_not_the_claim(self, tmp_path, monkeypatch):
        """The cwd message fires, not the CALLER_BRANCH one that would misreport CALLER_CWD as unset."""
        outside = _non_branch_dir(tmp_path)
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "aipass")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(outside))
        with pytest.raises(RuntimeError) as exc:
            get_current_user()
        text = str(exc.value)
        assert str(outside) in text
        assert "re-run from within" in text

    def test_verified_caller_is_unproven_from_non_branch_cwd(self, tmp_path, monkeypatch):
        """The privilege rail reads the same evidence: an unprovable caller is ""."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "aipass")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(_non_branch_dir(tmp_path)))
        assert resolve_verified_caller() == ""


class TestLegitimateCallersUnaffected:
    """The fence must fire on the defect and nothing else."""

    def test_caller_inside_a_branch_still_resolves(self, monkeypatch):
        """The everyday case: an agent running from its own branch."""
        repo_root = Path(__file__).resolve().parents[3].parent
        devpulse = repo_root / "src" / "aipass" / "devpulse"
        if not (devpulse / ".trinity" / "passport.json").exists():
            pytest.skip("devpulse branch not present in this tree")
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(devpulse))
        info = detect_branch_from_pwd()
        assert info is not None
        assert info.get("email") == "@devpulse"

    def test_caller_cwd_unset_is_left_alone(self, tmp_path, monkeypatch):
        """In-process callers carry no AIPASS_CALLER_CWD: no cwd means no verdict, the passport walk decides.

        CALLER_BRANCH is unset too: with it set, the caller_branch lane returns before the walk.
        """
        branch = tmp_path / "src" / "aipass" / "ai_mail"
        (branch / ".trinity").mkdir(parents=True)
        (branch / ".trinity" / "passport.json").write_text(
            json.dumps({"branch_info": {"branch_name": "ai_mail", "email": "@ai_mail", "path": "src/aipass/ai_mail"}}),
            encoding="utf-8",
        )
        (tmp_path / "AIPASS_REGISTRY.json").write_text(
            json.dumps(
                {
                    "metadata": {"version": "1.0.0", "total_branches": 1},
                    "branches": [
                        {
                            "name": "AI_MAIL",
                            "path": "src/aipass/ai_mail",
                            "email": "@ai_mail",
                            "status": "active",
                            "profile": "library",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
        monkeypatch.delenv("AIPASS_CALLER_BRANCH", raising=False)
        monkeypatch.chdir(branch)
        # BRANCH_REGISTRY_PATH is frozen at import from find_repo_root(): the live machine's registry.
        monkeypatch.setattr(bd, "BRANCH_REGISTRY_PATH", tmp_path / "AIPASS_REGISTRY.json")

        info = detect_branch_from_pwd()

        assert info is not None, "no CALLER_CWD must not refuse — the walk decides"
        assert info.get("email") == "@ai_mail"


class TestEveryVerbIsFenced:
    """The ruling is on ai_mail itself, not just dispatch."""

    @pytest.mark.parametrize("verb", ["inbox", "view", "reply", "close", "sent", "send", "dispatch"])
    def test_verb_exits_nonzero_from_non_branch_cwd(self, tmp_path, monkeypatch, verb):
        """Every verb refuses; view/close/reply's _resolve_branch_path() once fell back to ai_mail's mailbox."""

        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "aipass")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(_non_branch_dir(tmp_path)))
        monkeypatch.setattr("sys.argv", ["ai_mail.py", verb])
        assert entry.main() != 0

    def test_help_still_works_from_anywhere(self, tmp_path, monkeypatch):
        """Help is never fenced: a cross-OS preflight runs `drone @ai_mail --help` as a routing probe."""

        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "aipass")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(_non_branch_dir(tmp_path)))
        monkeypatch.setattr("sys.argv", ["ai_mail.py", "--help"])
        assert entry.main() == 0


class TestProvenanceLiftsTheOverRefusal:
    """@drone's AIPASS_CALLER_IDENTITY_SOURCE: assigned and passport are credentials, project never is."""

    def test_assigned_identity_resolves_from_outside_any_branch(self, tmp_path, monkeypatch):
        """A dispatched agent that cds out of its branch is still itself, keyed to the credential."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "ai_mail")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(_non_branch_dir(tmp_path)))
        monkeypatch.setenv("AIPASS_CALLER_IDENTITY_SOURCE", "assigned")
        info = detect_branch_from_pwd()
        assert info is not None
        assert info.get("email") == "@ai_mail"

    def test_project_source_is_still_refused(self, tmp_path, monkeypatch):
        """A directory name is not a credential, even when it spells a real citizen."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "aipass")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(_non_branch_dir(tmp_path)))
        monkeypatch.setenv("AIPASS_CALLER_IDENTITY_SOURCE", "project")
        assert detect_branch_from_pwd() is None

    def test_passport_source_is_a_credential(self, tmp_path, monkeypatch):
        """If drone proved a passport and this walk disagrees, trust drone: it saw the real cwd."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "ai_mail")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(_non_branch_dir(tmp_path)))
        monkeypatch.setenv("AIPASS_CALLER_IDENTITY_SOURCE", "passport")
        info = detect_branch_from_pwd()
        assert info is not None and info.get("email") == "@ai_mail"

    def test_absent_flag_keeps_the_cwd_rule(self, tmp_path, monkeypatch):
        """No flag (older drone, non-drone caller): the cwd evidence still decides."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "aipass")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(_non_branch_dir(tmp_path)))
        monkeypatch.delenv("AIPASS_CALLER_IDENTITY_SOURCE", raising=False)
        assert detect_branch_from_pwd() is None

    def test_unknown_flag_value_is_not_a_credential(self, tmp_path, monkeypatch):
        """Fail closed on a value this code does not recognise."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "aipass")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(_non_branch_dir(tmp_path)))
        monkeypatch.setenv("AIPASS_CALLER_IDENTITY_SOURCE", "unknown")
        assert detect_branch_from_pwd() is None

    def test_verified_caller_accepts_assigned_outside_a_branch(self, tmp_path, monkeypatch):
        """The privilege rail lifts with the same key, or the wake lane stays closed to dispatched agents."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "daemon")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(_non_branch_dir(tmp_path)))
        monkeypatch.setenv("AIPASS_CALLER_IDENTITY_SOURCE", "assigned")
        assert resolve_verified_caller() == "@daemon"

    def test_verified_caller_still_refuses_project(self, tmp_path, monkeypatch):
        """A project name may never buy a privileged sender claim."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "aipass")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(_non_branch_dir(tmp_path)))
        monkeypatch.setenv("AIPASS_CALLER_IDENTITY_SOURCE", "project")
        assert resolve_verified_caller() == ""

    def test_entry_point_lets_an_assigned_caller_through(self, tmp_path, monkeypatch):
        """End to end: the CLI fence stops refusing a credentialed caller."""

        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "ai_mail")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(_non_branch_dir(tmp_path)))
        monkeypatch.setenv("AIPASS_CALLER_IDENTITY_SOURCE", "assigned")
        monkeypatch.setattr("sys.argv", ["ai_mail.py", "inbox"])
        assert entry.main() == 0


class TestThePoisonedContactRowCannotOutvoteTheRegistry:
    """contacts.json is a writable cache; the registry outranks it for every citizen it knows."""

    def _poison(self, monkeypatch, tmp_path, victim_dir):
        """Stage a contact row for 'ai_mail' whose inbox is another branch's."""

        contact_row = {"project": "", "inbox": str(victim_dir / ".ai_mail.local" / "inbox.json")}
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.email.contacts.get_contact",
            lambda name: contact_row if name.lstrip("@").lower() == "ai_mail" else None,
        )
        return bd

    def test_the_registry_wins_when_a_contact_row_contradicts_it(self, monkeypatch, tmp_path):
        """The regression test for the live leak: right name must mean right mailbox."""
        registry_root = tmp_path / "repo"
        real = registry_root / "src" / "aipass" / "ai_mail"
        victim = registry_root / "src" / "aipass" / "flow"
        for branch in (real, victim):
            (branch / ".ai_mail.local").mkdir(parents=True)

        registry = registry_root / "AIPASS_REGISTRY.json"
        registry.write_text(
            json.dumps(
                {
                    "branches": [
                        {"name": "AI_MAIL", "email": "@ai_mail", "path": "src/aipass/ai_mail"},
                        {"name": "FLOW", "email": "@flow", "path": "src/aipass/flow"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        bd = self._poison(monkeypatch, tmp_path, victim)
        monkeypatch.setattr(bd, "BRANCH_REGISTRY_PATH", registry)
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "ai_mail")
        monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)

        resolved = bd.detect_branch_from_pwd()

        assert resolved is not None, "premise: the caller must still resolve"
        assert Path(resolved["path"]).name == "ai_mail", (
            f"served another citizen's branch: {resolved['path']} — this is the live leak"
        )

    def test_contacts_still_serve_a_name_the_registry_does_not_know(self, monkeypatch, tmp_path):
        """The cache keeps its actual job: external projects absent from the registry."""

        stranger = tmp_path / "outside" / "vera"
        (stranger / ".ai_mail.local").mkdir(parents=True)

        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text(json.dumps({"branches": []}), encoding="utf-8")

        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.email.contacts.get_contact",
            lambda name: (
                {"project": "Vera", "inbox": str(stranger / ".ai_mail.local" / "inbox.json")}
                if name.lstrip("@").lower() == "vera"
                else None
            ),
        )
        monkeypatch.setattr(bd, "BRANCH_REGISTRY_PATH", registry)
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "vera")
        monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)

        resolved = bd.detect_branch_from_pwd()

        assert resolved is not None
        assert Path(resolved["path"]).name == "vera"


class TestAProjectCitizenResolvesAgainstItsOwnRegistry:
    """A registry row's path is relative to the registry it came from; the reader absolutises it.

    Joined to the AIPass root instead, a project citizen's path silently became a phantom mailbox.
    """

    @staticmethod
    def _project(tmp_path):
        """A project citizen laid out exactly like projects/baud."""
        project_root = tmp_path / "projects" / "baud"
        citizen = project_root / "src" / "baud" / "baud"
        (citizen / ".ai_mail.local").mkdir(parents=True)
        # A real seat: the fence refuses a caller_cwd that stands in no branch.
        (citizen / ".trinity").mkdir()
        (citizen / ".trinity" / "passport.json").write_text(
            json.dumps({"branch_info": {"branch_name": "baud", "email": "@baud"}}), encoding="utf-8"
        )
        (project_root / "BAUD_REGISTRY.json").write_text(
            json.dumps({"branches": [{"name": "BAUD", "email": "@baud", "path": "src/baud/baud"}]}),
            encoding="utf-8",
        )
        return project_root, citizen

    def test_the_relative_path_is_rooted_at_its_own_registry(self, monkeypatch, tmp_path):
        """The regression test: a project row must not be joined to the AIPass root."""
        project_root, citizen = self._project(tmp_path)

        aipass_registry = tmp_path / "AIPASS_REGISTRY.json"
        aipass_registry.write_text(json.dumps({"branches": []}), encoding="utf-8")
        monkeypatch.setattr(bd, "BRANCH_REGISTRY_PATH", aipass_registry)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(citizen))
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "baud")

        resolved = bd.detect_branch_from_pwd()

        assert resolved is not None, "premise: the project citizen must still resolve"
        assert Path(resolved["path"]).is_absolute(), (
            f"a row leaving the registry reader must carry its root. Got: {resolved['path']}"
        )
        assert Path(resolved["path"]).resolve() == citizen.resolve(), (
            f"resolved to the wrong tree: {resolved['path']} (his mailbox is at {citizen})"
        )

    def test_an_aipass_citizen_with_a_relative_row_is_unaffected(self, monkeypatch, tmp_path):
        """Six of the eighteen AIPass rows are relative — this must not move them."""
        repo = tmp_path / "aipass"
        citizen = repo / "src" / "aipass" / "ai_mail"
        (citizen / ".trinity").mkdir(parents=True)
        (citizen / ".trinity" / "passport.json").write_text(
            json.dumps({"branch_info": {"branch_name": "ai_mail", "email": "@ai_mail"}}), encoding="utf-8"
        )
        registry = repo / "AIPASS_REGISTRY.json"
        registry.write_text(
            json.dumps({"branches": [{"name": "AI_MAIL", "email": "@ai_mail", "path": "src/aipass/ai_mail"}]}),
            encoding="utf-8",
        )
        monkeypatch.setattr(bd, "BRANCH_REGISTRY_PATH", registry)
        monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "ai_mail")

        resolved = bd.detect_branch_from_pwd()

        assert resolved is not None
        assert Path(resolved["path"]).resolve() == citizen.resolve()

    def test_the_mailbox_follows_the_corrected_root(self, monkeypatch, tmp_path):
        """The consequence the citizen actually feels: inbox and reply find his mail."""

        project_root, citizen = self._project(tmp_path)
        aipass_registry = tmp_path / "AIPASS_REGISTRY.json"
        aipass_registry.write_text(json.dumps({"branches": []}), encoding="utf-8")
        monkeypatch.setattr(bd, "BRANCH_REGISTRY_PATH", aipass_registry)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(citizen))
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "baud")

        user = get_current_user()

        assert Path(user["mailbox_path"]).resolve() == (citizen / ".ai_mail.local").resolve(), (
            f"his commands would read {user['mailbox_path']} instead of his own mailbox"
        )
