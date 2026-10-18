# =================== AIPass ====================
# Name: test_registry_credential.py
# Description: metadata.id — the project credential a new registry is born with
# Version: 1.0.2
# Created: 2026-08-24
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/registry.py's project-credential mint (metadata.id)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(documentation) — docstrings on load_registry, resolve_project_credential and add_to_registry
# seedgo: no-test-needed(stdlib) — uuid.uuid4's randomness and uuid.UUID's own validation, which the mint relies on

import json
import uuid

import pytest

from aipass.spawn.apps.handlers import adoption_ops, delete_ops, placeholders, sync_registry_ops, update_ops
from aipass.spawn.apps.handlers import registry as registry_module
from aipass.spawn.apps.handlers.registry import (
    add_to_registry,
    load_registry,
    registry_is_writable_document,
    resolve_project_credential,
    save_registry,
)
from aipass.spawn.apps.modules.core import spawn_agent

# The mint is deliberately asymmetric: an ABSENT registry is a new project and earns a
# credential; an UNREADABLE one already has one, and minting would orphan every passport.


def test_minted_default_keeps_the_rest_of_the_schema(tmp_path):
    """Adding the credential must not disturb the fields callers already read."""
    result = load_registry(tmp_path / "NEW_REGISTRY.json")

    assert result["metadata"]["version"] == "1.0.0"
    assert result["metadata"]["total_branches"] == 0
    assert result["branches"] == []
    assert "last_updated" in result["metadata"]


def test_real_registry_credential_is_never_replaced(tmp_path):
    """A readable registry hands back its OWN id, untouched."""
    path = tmp_path / "REAL_REGISTRY.json"
    path.write_text(
        json.dumps({"metadata": {"id": "keep-me", "version": "1.0.0", "total_branches": 0}, "branches": []}),
        encoding="utf-8",
    )

    assert load_registry(path)["metadata"]["id"] == "keep-me"


def test_unreadable_registry_does_not_mint_a_replacement_credential(tmp_path):
    """An unreadable file is not a new project: an id here would orphan every passport."""
    corrupt = tmp_path / "CORRUPT_REGISTRY.json"
    corrupt.write_text("{not valid json", encoding="utf-8")

    result = load_registry(corrupt)

    assert result["metadata"].get("id") in (None, ""), (
        "load_registry minted a fresh credential for a registry that already exists — "
        "saving that would replace a live project's id"
    )


@pytest.mark.parametrize("content", ["", "   ", "{malformed"])
def test_unreadable_variants_all_withhold_a_credential(tmp_path, content):
    """Empty and malformed both mean 'cannot read', never 'does not exist'."""
    path = tmp_path / f"X{len(content)}_REGISTRY.json"
    path.write_text(content, encoding="utf-8")

    assert load_registry(path)["metadata"].get("id") in (None, "")


def test_new_registry_adopts_the_callers_credential(tmp_path):
    """The credential already stamped into the passport is the one that lands (no double mint)."""

    reg = tmp_path / "NEW_REGISTRY.json"
    branch = tmp_path / "widget"
    branch.mkdir()
    stamped = str(uuid.uuid4())

    add_to_registry(reg, "WIDGET", str(branch), "p", "@widget", credential=stamped)

    assert json.loads(reg.read_text(encoding="utf-8"))["metadata"]["id"] == stamped


def test_existing_registry_credential_survives_a_new_citizen(tmp_path):
    """Registering into a live project never re-credentials it."""

    reg = tmp_path / "REAL_REGISTRY.json"
    reg.write_text(
        json.dumps({"metadata": {"id": "the-real-lock", "version": "1.0.0", "total_branches": 0}, "branches": []}),
        encoding="utf-8",
    )
    branch = tmp_path / "widget"
    branch.mkdir()

    add_to_registry(reg, "WIDGET", str(branch), "p", "@widget", credential=str(uuid.uuid4()))

    assert json.loads(reg.read_text(encoding="utf-8"))["metadata"]["id"] == "the-real-lock"


class TestLoadDoesNotMint:
    """Loading is a READ. Minting a project credential is a DECISION.

    A minting read, saved, would put a fresh credential in whatever directory the caller stands in."""

    def test_missing_registry_yields_no_credential(self, tmp_path):
        result = load_registry(tmp_path / "NEW_REGISTRY.json")

        assert result["metadata"].get("id") in (None, ""), (
            "load_registry minted a project credential for a file that does not exist"
        )

    def test_missing_registry_still_returns_a_usable_empty_document(self, tmp_path):
        """Refusing to mint must not break the sixteen callers that just read branches.

        The empty document is never written: the next reader would take it for a real registry."""
        result = load_registry(tmp_path / "NEW_REGISTRY.json")

        assert result["branches"] == []
        assert result["metadata"]["total_branches"] == 0
        assert not (tmp_path / "NEW_REGISTRY.json").exists()

    def test_the_absence_is_said_out_loud(self, tmp_path, caplog):
        """A silent empty document is how the composition stayed invisible."""
        import logging

        with caplog.at_level(logging.INFO):
            load_registry(tmp_path / "ABSENT_REGISTRY.json")

        assert any("ABSENT_REGISTRY.json" in record.getMessage() for record in caplog.records), (
            "load_registry returned an empty document for a missing file without saying so"
        )

    def test_the_two_line_composition_writes_no_credential(self, tmp_path):
        """@memory's exact reproduction — load a path that does not exist, save it."""

        path = tmp_path / "AIPASS_REGISTRY.json"
        save_registry(path, load_registry(path))

        written = json.loads(path.read_text(encoding="utf-8"))
        assert written["metadata"].get("id") in (None, ""), (
            "a registry with a brand-new project credential appeared out of nothing"
        )


class TestResolveProjectCredentialIsTheExplicitMint:
    """The decision, made where the caller knows it is creating a project."""

    def test_absent_registry_mints_a_real_uuid(self, tmp_path):

        assert uuid.UUID(resolve_project_credential(tmp_path / "NEW_REGISTRY.json"))

    def test_each_new_project_gets_its_own(self, tmp_path):

        first = resolve_project_credential(tmp_path / "ONE_REGISTRY.json")
        second = resolve_project_credential(tmp_path / "TWO_REGISTRY.json")

        assert first != second

    def test_it_is_not_aipass_own_id(self, tmp_path):
        """The regression the 08-24 fix exists to prevent, still pinned."""

        assert resolve_project_credential(tmp_path / "NEW_REGISTRY.json") != "7087bb93-570f-4b9a-b035-4fd7f570200e"

    def test_existing_registry_hands_back_its_own_id(self, tmp_path):

        path = tmp_path / "REAL_REGISTRY.json"
        path.write_text(
            json.dumps({"metadata": {"id": "keep-me", "version": "1.0.0", "total_branches": 0}, "branches": []}),
            encoding="utf-8",
        )

        assert resolve_project_credential(path) == "keep-me"

    def test_unreadable_registry_mints_nothing(self, tmp_path):
        """Unreadable is not absent — re-credentialling orphans every passport."""

        corrupt = tmp_path / "CORRUPT_REGISTRY.json"
        corrupt.write_text("{not valid json", encoding="utf-8")

        assert resolve_project_credential(corrupt) == ""

    def test_resolving_writes_nothing_to_disk(self, tmp_path):
        """Minting a value is not creating a file — the create step does that."""

        path = tmp_path / "NEW_REGISTRY.json"
        resolve_project_credential(path)

        assert not path.exists()
        assert list(tmp_path.iterdir()) == []


class TestAbsentRegistryResolverIsHandled:
    """find_registry answers absence with None; each caller answers it by name, never crashes.

    In is_protected, None.exists() would escape the try and crash a SAFETY check."""

    def test_is_protected_answers_not_protected_when_there_is_no_registry(self, tmp_path, monkeypatch):
        """Mutant: is_protected skips find_registry and assumes None -> red."""
        asked: list = []
        monkeypatch.setattr(registry_module, "find_registry", lambda *a, **k: asked.append((a, k)))

        protected, reason = registry_module.is_protected("somebranch")

        assert asked, "is_protected never asked the resolver"
        assert protected is False
        assert reason

    def test_the_protected_floor_still_wins_without_a_registry(self, tmp_path, monkeypatch):
        """A missing registry must never unprotect infrastructure.

        Mutant: the hardcoded floor check disabled (if False) -> red."""
        asked: list = []
        monkeypatch.setattr(registry_module, "find_registry", lambda *a, **k: asked.append((a, k)))

        protected, reason = registry_module.is_protected("spawn")

        assert asked == [], "the floor must answer before any registry is looked for"
        assert protected is True
        assert "infrastructure" in reason

    def test_ensure_admin_refuses_rather_than_crashing(self, monkeypatch):
        """Mutant: ensure_admin skips find_registry and assumes None -> red."""
        asked: list = []
        monkeypatch.setattr(registry_module, "find_registry", lambda *a, **k: asked.append((a, k)))

        status, reason = registry_module.ensure_admin()

        assert asked, "ensure_admin never asked the resolver"
        assert status == "refused"
        assert "registry" in reason.lower()

    def test_get_owner_returns_none_when_there_is_no_registry(self, monkeypatch):
        """Mutant: get_owner skips find_registry and assumes None -> red."""
        asked: list = []
        monkeypatch.setattr(registry_module, "find_registry", lambda *a, **k: asked.append((a, k)))

        assert registry_module.get_owner() is None
        assert asked == [((), {"start_path": None})]


class TestCreatePathStillStampsACredential:
    """END-TO-END regression guard for the 2026-08-24 defect, after the move.

    A new project's citizen gets a real credential, and the registry carries the same one."""

    def test_a_new_project_citizen_gets_a_real_credential_in_both_files(self, tmp_path):

        project = tmp_path / "brandnew"
        project.mkdir()
        (project / "pyproject.toml").write_text("[project]\nname='brandnew'\n", encoding="utf-8")

        result = spawn_agent(str(project / "src" / "brandnew" / "widget"))
        assert result.get("success"), result

        passport = json.loads(
            (project / "src" / "brandnew" / "widget" / ".trinity" / "passport.json").read_text(encoding="utf-8")
        )
        credential = passport["citizenship"]["registry_id"]

        assert uuid.UUID(credential), "the new project's citizen was born without a credential"
        assert credential != "7087bb93-570f-4b9a-b035-4fd7f570200e", "inherited AIPass's own id"

        registry = json.loads((project / "AIPASS_REGISTRY.json").read_text(encoding="utf-8"))
        assert registry["metadata"]["id"] == credential, (
            "the passport claims one credential and the registry carries another"
        )


class TestNoRegistryAnywhereIsHandledOnTheCreatePath:
    """The other consumers of the now-nullable resolver, pinned by behaviour."""

    def test_relative_path_falls_back_to_the_bare_name(self, tmp_path, monkeypatch):
        """Mutant: resolve_relative_path skips find_registry and assumes None -> red."""
        asked: list = []
        monkeypatch.setattr(placeholders, "find_registry", lambda *a, **k: asked.append(k))
        target = tmp_path / "nowhere" / "widget"
        target.mkdir(parents=True)

        assert placeholders.resolve_relative_path(target) == "widget"
        assert asked == [{"start_path": target.parent}]

    def test_replacements_leave_registry_id_empty_rather_than_inventing_one(self, tmp_path, monkeypatch):
        """Mutant: build_replacements_dict skips find_registry and assumes None -> red."""
        asked: list = []
        monkeypatch.setattr(placeholders, "find_registry", lambda *a, **k: asked.append(k))
        target = tmp_path / "nowhere" / "widget"
        target.mkdir(parents=True)

        replacements = placeholders.build_replacements_dict(str(target), "widget")

        assert replacements["REGISTRY_ID"] == "", "a credential nobody issued was substituted"
        # Asked twice: once for the credential, once for the relative passport path.
        assert asked.count({"start_path": target.parent}) == 2, asked


class TestEveryResolverConsumerRefusesByName:
    """Sweep pin: no spawn entry point may crash on an absent registry."""

    def _no_registry(self, monkeypatch, module):
        monkeypatch.setattr(module, "find_registry", lambda *a, **k: None)

    def test_sync_registry_reports_the_absence(self, monkeypatch):

        self._no_registry(monkeypatch, sync_registry_ops)
        result = sync_registry_ops.sync_registry()

        assert "no registry" in result["error"].lower()
        assert result["stale"] == [] and result["unregistered"] == []

    def test_check_owner_identity_flags_the_absence(self, monkeypatch):

        self._no_registry(monkeypatch, sync_registry_ops)
        result = sync_registry_ops.check_owner_identity()

        assert result["clean"] is False
        assert any(issue["flag"] == "no_registry" for issue in result["issues"])

    def test_delete_refuses_rather_than_deleting_unchecked(self, monkeypatch):
        """The most important one: no protection layer means no delete."""

        self._no_registry(monkeypatch, delete_ops)
        result = delete_ops.delete_branch("somebranch")

        assert result["success"] is False
        assert "no *_REGISTRY.json" in result["error"]

    def test_update_all_returns_nothing_to_update(self, monkeypatch):

        self._no_registry(monkeypatch, update_ops)

        assert update_ops.update_all() == []

    def test_adoption_refuses_with_no_project_to_adopt_into(self, tmp_path, monkeypatch):

        self._no_registry(monkeypatch, adoption_ops)
        target = tmp_path / "orphan"
        (target / ".trinity").mkdir(parents=True)
        (target / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")

        result = adoption_ops.adopt_existing(target, "", "", None)

        assert result["success"] is False
        assert "no *_REGISTRY.json" in result["error"]


class TestAnUnreadableRegistryIsNeverOverwritten:
    """FPLAN-0492: a live registry that cannot be parsed must never be written over.

    load_registry reads missing and unreadable alike as empty; a writer would rebuild from nothing.
    delete_branch and move_branch refuse by structure ("not found in registry"), so are not pinned."""

    LIVE = {
        "metadata": {"version": "1.0.0", "last_updated": "2026-09-07", "total_branches": 2, "id": "proj-cred-123"},
        "branches": [
            {"name": "alpha", "path": "src/alpha", "email": "@alpha", "status": "active", "registry_id": "a1"},
            {"name": "beta", "path": "src/beta", "email": "@beta", "status": "active", "registry_id": "b1"},
        ],
    }

    def _corrupt_registry(self, tmp_path):
        path = tmp_path / "AIPASS_REGISTRY.json"
        text = json.dumps(self.LIVE, indent=2)
        path.write_text(text[: len(text) // 2], encoding="utf-8")  # exists, unparseable
        return path

    def test_add_to_registry_refuses_and_leaves_the_file_untouched(self, tmp_path):

        path = self._corrupt_registry(tmp_path)
        before = path.read_bytes()

        added = add_to_registry(path, "GAMMA", str(tmp_path / "src" / "gamma"), "Profile", "@gamma")

        assert added is False
        assert path.read_bytes() == before

    def test_add_to_registry_still_writes_a_readable_one(self, tmp_path):
        """The control: refusing an unreadable file must not refuse a good one."""

        path = tmp_path / "AIPASS_REGISTRY.json"
        path.write_text(json.dumps(self.LIVE, indent=2), encoding="utf-8")

        added = add_to_registry(path, "GAMMA", str(tmp_path / "src" / "gamma"), "Profile", "@gamma")

        written = json.loads(path.read_text(encoding="utf-8"))
        assert added is True
        assert [b["name"] for b in written["branches"]] == ["GAMMA", "alpha", "beta"]
        assert written["metadata"]["id"] == "proj-cred-123", "an existing credential is never touched"

    def test_a_missing_registry_is_still_created(self, tmp_path):
        """Absent is not unreadable — the create lane's own case stays open."""

        path = tmp_path / "AIPASS_REGISTRY.json"

        added = add_to_registry(path, "ALPHA", str(tmp_path / "src" / "alpha"), "Profile", "@alpha")

        assert added is True
        assert [b["name"] for b in json.loads(path.read_text(encoding="utf-8"))["branches"]] == ["ALPHA"]

    def test_sync_registry_refuses_rather_than_rebuilding(self, tmp_path, monkeypatch):

        path = self._corrupt_registry(tmp_path)
        before = path.read_bytes()
        for name in ("alpha", "beta"):
            branch = tmp_path / "src" / name / ".trinity"
            branch.mkdir(parents=True)
            (branch / "passport.json").write_text(
                json.dumps({"identity": {"citizen_class": "specialist"}}), encoding="utf-8"
            )
        monkeypatch.setattr(sync_registry_ops, "find_registry", lambda *a, **k: path)

        result = sync_registry_ops.sync_registry(fix=True)

        assert "could not be read" in result["error"]
        assert result["unregistered"] == []
        assert path.read_bytes() == before

    def test_the_guard_itself_separates_absent_from_unreadable(self, tmp_path):

        missing = tmp_path / "NOT_THERE.json"
        corrupt = self._corrupt_registry(tmp_path)
        not_an_object = tmp_path / "LIST_REGISTRY.json"
        not_an_object.write_text("[]", encoding="utf-8")
        good = tmp_path / "GOOD_REGISTRY.json"
        good.write_text(json.dumps(self.LIVE), encoding="utf-8")

        assert registry_is_writable_document(missing) is True
        assert registry_is_writable_document(corrupt) is False
        assert registry_is_writable_document(not_an_object) is False
        assert registry_is_writable_document(good) is True
