# =================== AIPass ====================
# Name: test_identity_fence.py
# Description: Tests for the caller identity fence (no branch under caller = refuse)
# Version: 1.0.0
# Created: 2026-08-21
# Modified: 2026-08-21
# =============================================

"""Tests for the caller identity fence.

Patrick's ruling, 2026-08-21: "ur dispatch should fail if u run from [outside]
ur cwd, and if aimail was run in root it should fail outright."

The defect these pin (@devpulse, 0bb77ec2 / 096c9a42): running any ai_mail verb
from the repo root resolved to the @aipass CITIZEN and read its mailbox. The
mechanism is a name collision, not a missing policy — drone's
``resolve_caller_identity(<repo root>)`` returns ``'aipass'`` derived from the
PROJECT directory name, ai_mail's contact lookup finds the same-named citizen,
and the identity is stamped "verified". A dispatch sent that way cost $1.41 and
woke the wrong citizen.

The rule: ``AIPASS_CALLER_CWD`` is the evidence of where the caller actually
stood. When it is set and does not sit inside a branch, no identity is provable
and every verb refuses — a claim in ``AIPASS_CALLER_BRANCH`` cannot outvote it.
"""

from pathlib import Path

import json

import pytest

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
        """THE REPRODUCTION: drone stamps CALLER_BRANCH from the project dir name
        at the repo root, which collides with the @aipass citizen. The cwd proves
        the caller was not in a branch, so nothing may resolve."""
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
        """The existing message already names this exact mistake and tells the
        caller to re-run from within the sending branch. It must be the one that
        fires — the CALLER_BRANCH text would misreport CALLER_CWD as unset."""
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
        """In-process library callers (@trigger delivery, @daemon wake) and the
        dispatch env carry no AIPASS_CALLER_CWD. The fence keys on evidence that
        contradicts, not on evidence that is absent — no cwd means no verdict
        here, and the existing passport walk still decides.

        THE SEAT IS SYNTHETIC. This used to resolve against the live registry on
        the author's machine and returned None on a fresh checkout, where the
        registry does not exist — reported red in CI on PR 739 (@devpulse,
        2026-08-23). It was testing the machine. The walk now runs entirely
        inside tmp_path, so "the passport walk still decides" is demonstrated
        rather than borrowed.

        AIPASS_CALLER_BRANCH IS NOW UNSET TOO, and that is a correction rather
        than a convenience. With it set, detect_branch_from_pwd takes the
        caller_branch lane and returns before the passport walk is reached — so
        the old version named a mechanism its own input could never exercise.
        The real callers this test speaks for (in-process @trigger delivery,
        @daemon wake) carry no caller env at all, which is what it now sets up.
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
        # BRANCH_REGISTRY_PATH is frozen at import from find_repo_root(), so it
        # points at whatever machine this runs on — the live registry here, a
        # cwd-derived guess on a fresh checkout. Pointed at the fixture for the
        # same reason conftest points FEED_PATH and CONTACTS_FILE at tmp_path.
        monkeypatch.setattr(bd, "BRANCH_REGISTRY_PATH", tmp_path / "AIPASS_REGISTRY.json")

        info = detect_branch_from_pwd()

        assert info is not None, "no CALLER_CWD must not refuse — the walk decides"
        assert info.get("email") == "@ai_mail"


class TestEveryVerbIsFenced:
    """The ruling is on ai_mail itself, not just dispatch."""

    @pytest.mark.parametrize("verb", ["inbox", "view", "reply", "close", "sent", "send", "dispatch"])
    def test_verb_exits_nonzero_from_non_branch_cwd(self, tmp_path, monkeypatch, verb):
        """inbox, view, reply, send, dispatch — all of them. view/close/reply
        matter most: they resolve through _resolve_branch_path(), whose own
        fallback pointed at ai_mail's mailbox when detection failed."""
        from aipass.ai_mail.apps import ai_mail as entry

        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "aipass")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(_non_branch_dir(tmp_path)))
        monkeypatch.setattr("sys.argv", ["ai_mail.py", verb])
        assert entry.main() != 0

    def test_help_still_works_from_anywhere(self, tmp_path, monkeypatch):
        """Help needs no identity and must not be fenced — @aipass's cross-OS
        preflight runs `drone @ai_mail --help` as a routing probe."""
        from aipass.ai_mail.apps import ai_mail as entry

        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "aipass")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(_non_branch_dir(tmp_path)))
        monkeypatch.setattr("sys.argv", ["ai_mail.py", "--help"])
        assert entry.main() == 0


class TestProvenanceLiftsTheOverRefusal:
    """@drone's AIPASS_CALLER_IDENTITY_SOURCE (shipped 2026-08-21 21:42) tells the
    two cases apart that were byte-identical when the fence landed at 19:21.

    The fence had to refuse both. That over-refusal broke S102 in practice — "an
    agent that cds into another branch to read its code is still itself" — and it
    is the live regression from my own fix. The flag lifts it:

      assigned  — AIPASS_BRANCH_NAME, set when the process was created. A
                  credential, true from ANY directory. Accept.
      passport  — a passport under the caller's feet. Accept.
      project   — a registry-derived PROJECT name that happens to spell a citizen.
                  Never identity. Refuse, forever — that is the whole incident.
    """

    def test_assigned_identity_resolves_from_outside_any_branch(self, tmp_path, monkeypatch):
        """S102 RESTORED: a dispatched agent that cds out of its branch is still
        itself. This is the case test_detect_resolves_identity_when_cwd_is_wrong
        pinned before the fence superseded it — brought back, now keyed to the
        credential rather than to a bare name."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "ai_mail")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(_non_branch_dir(tmp_path)))
        monkeypatch.setenv("AIPASS_CALLER_IDENTITY_SOURCE", "assigned")
        info = detect_branch_from_pwd()
        assert info is not None
        assert info.get("email") == "@ai_mail"

    def test_project_source_is_still_refused(self, tmp_path, monkeypatch):
        """THE $1.41 CASE. A directory name is not a credential, no matter that it
        spells a real citizen. This must never loosen."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "aipass")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(_non_branch_dir(tmp_path)))
        monkeypatch.setenv("AIPASS_CALLER_IDENTITY_SOURCE", "project")
        assert detect_branch_from_pwd() is None

    def test_passport_source_is_a_credential(self, tmp_path, monkeypatch):
        """Defensive: if drone proved a passport but this walk disagrees, drone saw
        the caller's real cwd and this process did not. Trust the prover."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "ai_mail")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(_non_branch_dir(tmp_path)))
        monkeypatch.setenv("AIPASS_CALLER_IDENTITY_SOURCE", "passport")
        assert detect_branch_from_pwd() is not None

    def test_absent_flag_keeps_the_cwd_rule(self, tmp_path, monkeypatch):
        """An older drone, or a caller that is not drone, stamps no flag. The cwd
        evidence still decides — the lift is opt-in, never assumed."""
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
        """The privilege rail lifts with the same key — refusing 'assigned' here
        would keep the wake lane closed for exactly the dispatched agents it exists
        to serve."""
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
        from aipass.ai_mail.apps import ai_mail as entry

        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "ai_mail")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(_non_branch_dir(tmp_path)))
        monkeypatch.setenv("AIPASS_CALLER_IDENTITY_SOURCE", "assigned")
        monkeypatch.setattr("sys.argv", ["ai_mail.py", "inbox"])
        assert entry.main() == 0


class TestThePoisonedContactRowCannotOutvoteTheRegistry:
    """Found live, 2026-08-23: `drone @ai_mail inbox` served @flow's mailbox.

    The system's own identity log is what named it — right name, right email,
    WRONG PATH, and stamped "verified":

        strategy       caller_branch:contact
        confidence     verified
        resolved_name  AI_MAIL
        resolved_email @ai_mail
        resolved_path  .../src/aipass/flow

    contacts.json is a LEARNED, WRITABLE cache; AIPASS_REGISTRY.json is the
    authoritative catalog. Consulting the cache FIRST let one poisoned row
    outrank the catalog for a citizen the catalog knows perfectly well. The
    existing staleness guard could not catch it: it only asks whether the
    branch root is a directory, and the wrong directory was a real live branch.

    Contacts exist for EXTERNAL projects that are not in the registry — that is
    what _get_contact_info's own docstring says. So the ordering was backwards
    for every AIPass citizen, which is every caller that matters here.
    """

    def _poison(self, monkeypatch, tmp_path, victim_dir):
        """Stage a contact row for 'ai_mail' whose inbox is another branch's."""
        from aipass.ai_mail.apps.handlers.users import branch_detection as bd

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
        """The cache keeps its actual job: external projects absent from the registry.

        Without this, "registry first" would quietly become "registry only" and
        break every external-tier caller — the case contacts were built for.
        """
        from aipass.ai_mail.apps.handlers.users import branch_detection as bd

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
