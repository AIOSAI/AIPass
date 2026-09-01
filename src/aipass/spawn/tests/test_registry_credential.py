# =================== AIPass ====================
# Name: test_registry_credential.py
# Description: metadata.id — the project credential a new registry is born with
# Version: 1.0.0
# Created: 2026-08-24
# Modified: 2026-08-24
# =============================================

"""Tests for the registry credential (metadata.id).

A project registry's ``metadata.id`` is the branch-registry lock: every passport
in that project carries it as ``citizenship.registry_id``, and BAUD renders it
as "Branch reg no.". A registry born WITHOUT one is not merely incomplete — its
first citizen's passport falls back to whatever registry discovery finds next,
which in practice is AIPass's own id, so a brand-new project's agent displays a
number belonging to a project it has never been part of.

The mint is deliberately ASYMMETRIC, and these tests pin that asymmetry:

  - registry file ABSENT  -> a genuinely new project -> mint a credential.
  - registry file PRESENT but unreadable -> the project ALREADY HAS a
    credential we simply cannot read. Minting a fresh one here would
    re-credential a live project and orphan every existing passport, so this
    path must NOT invent one.

MOVED 2026-08-31: that asymmetry used to live inside ``load_registry``, which
meant a READ minted an identity for any path that did not exist — and the shared
resolver used to hand out ``Path.cwd() / AIPASS_REGISTRY.json`` for an absence,
so the two composed into a project credential appearing in whatever directory
the caller stood in (@memory). The asymmetry is unchanged and still pinned; it
now lives in ``resolve_project_credential``, which the create sites call by
name. The three tests that asserted the mint against ``load_registry`` moved to
``TestResolveProjectCredentialIsTheExplicitMint`` rather than being deleted —
the behaviour they guard is the same behaviour, one layer over.
"""

import json
import uuid

import pytest

from aipass.spawn.apps.handlers.registry import load_registry


# =============================================================================
# ABSENT REGISTRY — a new project earns a credential
# =============================================================================


def test_minted_default_keeps_the_rest_of_the_schema(tmp_path):
    """Adding the credential must not disturb the fields callers already read."""
    result = load_registry(tmp_path / "NEW_REGISTRY.json")

    assert result["metadata"]["version"] == "1.0.0"
    assert result["metadata"]["total_branches"] == 0
    assert result["branches"] == []
    assert "last_updated" in result["metadata"]


# =============================================================================
# EXISTING REGISTRY — never re-credential what we merely failed to read
# =============================================================================


def test_real_registry_credential_is_never_replaced(tmp_path):
    """A readable registry hands back its OWN id, untouched."""
    path = tmp_path / "REAL_REGISTRY.json"
    path.write_text(
        json.dumps({"metadata": {"id": "keep-me", "version": "1.0.0", "total_branches": 0}, "branches": []}),
        encoding="utf-8",
    )

    assert load_registry(path)["metadata"]["id"] == "keep-me"


def test_unreadable_registry_does_not_mint_a_replacement_credential(tmp_path):
    """An unreadable file is not a new project — inventing an id here would
    silently re-credential a live project and orphan every passport in it."""
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


# =============================================================================
# CALLER-SUPPLIED CREDENTIAL — one project, one id
# =============================================================================


def test_new_registry_adopts_the_callers_credential(tmp_path):
    """The credential already stamped into the passport is the one that lands.

    Regression guard for a double mint: load_registry mints an id for a missing
    file, so an "is the id already set?" check would see that fresh mint and
    silently discard the caller's — leaving the passport claiming one credential
    and the registry file carrying a different one.
    """
    from aipass.spawn.apps.handlers.registry import add_to_registry

    reg = tmp_path / "NEW_REGISTRY.json"
    branch = tmp_path / "widget"
    branch.mkdir()
    stamped = str(uuid.uuid4())

    add_to_registry(reg, "WIDGET", str(branch), "p", "@widget", credential=stamped)

    assert json.loads(reg.read_text(encoding="utf-8"))["metadata"]["id"] == stamped


def test_existing_registry_credential_survives_a_new_citizen(tmp_path):
    """Registering into a live project never re-credentials it."""
    from aipass.spawn.apps.handlers.registry import add_to_registry

    reg = tmp_path / "REAL_REGISTRY.json"
    reg.write_text(
        json.dumps({"metadata": {"id": "the-real-lock", "version": "1.0.0", "total_branches": 0}, "branches": []}),
        encoding="utf-8",
    )
    branch = tmp_path / "widget"
    branch.mkdir()

    add_to_registry(reg, "WIDGET", str(branch), "p", "@widget", credential=str(uuid.uuid4()))

    assert json.loads(reg.read_text(encoding="utf-8"))["metadata"]["id"] == "the-real-lock"


# =============================================================================
# THE LOAD-SIDE MINT — a read must not create an identity
# =============================================================================


class TestLoadDoesNotMint:
    """Loading is a READ. Minting a project credential is a DECISION.

    MEASURED by @memory 2026-08-31, statically proven against live code: the
    shared resolver ``registry_discovery.find_registry`` returns
    ``Path.cwd() / AIPASS_REGISTRY.json`` when nothing exists — a PATH for an
    ABSENCE — and ``load_registry`` then answered that path with a well-formed
    document carrying a freshly minted ``metadata.id``. Compose the two and
    ``save_registry`` writes a registry with a brand-new project credential into
    whatever directory the caller happened to be standing in. Nobody calls it
    that way today: a loaded gun, not a fired one.

    The 2026-08-24 fix this replaces was right about the DEFECT — a new project
    whose first citizen inherits AIPass's own id — and wrong about WHERE to fix
    it. The create path knows it is creating; the load path does not know
    anything. So the mint moved to ``resolve_project_credential``, which the two
    real create sites call by name, and ``load_registry`` went back to being a
    read. The asymmetry the old file pinned survives intact, one layer over:
    absent means mint (when a creator asks), unreadable never does.

    Fleet ruling this implements: absence is a signal said out loud, never
    silently papered into a valid-looking value.
    """

    def test_missing_registry_yields_no_credential(self, tmp_path):
        result = load_registry(tmp_path / "NEW_REGISTRY.json")

        assert result["metadata"].get("id") in (None, ""), (
            "load_registry minted a project credential for a file that does not exist"
        )

    def test_missing_registry_still_returns_a_usable_empty_document(self, tmp_path):
        """Refusing to mint must not break the sixteen callers that just read branches."""
        result = load_registry(tmp_path / "NEW_REGISTRY.json")

        assert result["branches"] == []
        assert result["metadata"]["version"] == "1.0.0"
        assert result["metadata"]["total_branches"] == 0

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
        from aipass.spawn.apps.handlers.registry import save_registry

        path = tmp_path / "AIPASS_REGISTRY.json"
        save_registry(path, load_registry(path))

        written = json.loads(path.read_text(encoding="utf-8"))
        assert written["metadata"].get("id") in (None, ""), (
            "a registry with a brand-new project credential appeared out of nothing"
        )


class TestResolveProjectCredentialIsTheExplicitMint:
    """The decision, made where the caller knows it is creating a project."""

    def test_absent_registry_mints_a_real_uuid(self, tmp_path):
        from aipass.spawn.apps.handlers.registry import resolve_project_credential

        assert uuid.UUID(resolve_project_credential(tmp_path / "NEW_REGISTRY.json"))

    def test_each_new_project_gets_its_own(self, tmp_path):
        from aipass.spawn.apps.handlers.registry import resolve_project_credential

        first = resolve_project_credential(tmp_path / "ONE_REGISTRY.json")
        second = resolve_project_credential(tmp_path / "TWO_REGISTRY.json")

        assert first != second

    def test_it_is_not_aipass_own_id(self, tmp_path):
        """The regression the 08-24 fix exists to prevent, still pinned."""
        from aipass.spawn.apps.handlers.registry import resolve_project_credential

        assert resolve_project_credential(tmp_path / "NEW_REGISTRY.json") != "7087bb93-570f-4b9a-b035-4fd7f570200e"

    def test_existing_registry_hands_back_its_own_id(self, tmp_path):
        from aipass.spawn.apps.handlers.registry import resolve_project_credential

        path = tmp_path / "REAL_REGISTRY.json"
        path.write_text(
            json.dumps({"metadata": {"id": "keep-me", "version": "1.0.0", "total_branches": 0}, "branches": []}),
            encoding="utf-8",
        )

        assert resolve_project_credential(path) == "keep-me"

    def test_unreadable_registry_mints_nothing(self, tmp_path):
        """Unreadable is not absent — re-credentialling orphans every passport."""
        from aipass.spawn.apps.handlers.registry import resolve_project_credential

        corrupt = tmp_path / "CORRUPT_REGISTRY.json"
        corrupt.write_text("{not valid json", encoding="utf-8")

        assert resolve_project_credential(corrupt) == ""

    def test_resolving_writes_nothing_to_disk(self, tmp_path):
        """Minting a value is not creating a file — the create step does that."""
        from aipass.spawn.apps.handlers.registry import resolve_project_credential

        path = tmp_path / "NEW_REGISTRY.json"
        resolve_project_credential(path)

        assert not path.exists()
        assert list(tmp_path.iterdir()) == []


# =============================================================================
# THE OTHER HALF LANDED FIRST — find_registry now answers absence with None
# =============================================================================


class TestAbsentRegistryResolverIsHandled:
    """@aipass's half of tonight's ruling is already in the tree, and it reaches here.

    FOUND, not authored by me: ``aipass/shared/registry_discovery.find_registry``
    now returns ``None`` on absence instead of ``Path.cwd() / AIPASS_REGISTRY.json``.
    Its docstring names the reason and names this branch — "a path that need not
    exist is a lie with a type signature, and @spawn's load_registry mints a
    fresh metadata.id for exactly such a path". Correct, and it is the resolver
    half of the same fix as TestLoadDoesNotMint above.

    The consequence is mine: spawn had ~18 call sites written against a resolver
    that always returned a Path, and four of them dereference the result with no
    guard. Those were not type-checker noise — ``None.exists()`` is an
    AttributeError, and in ``is_protected`` it would escape a try that only
    catches OSError/ValueError/KeyError, turning "no registry here" into a crash
    inside a SAFETY check.

    Absence is answered by name, in each function's own vocabulary: not
    protected, refused, no owner.
    """

    def test_is_protected_answers_not_protected_when_there_is_no_registry(self, tmp_path, monkeypatch):
        from aipass.spawn.apps.handlers import registry as registry_module

        monkeypatch.setattr(registry_module, "find_registry", lambda *a, **k: None)

        protected, reason = registry_module.is_protected("somebranch")

        assert protected is False
        assert reason

    def test_the_protected_floor_still_wins_without_a_registry(self, tmp_path, monkeypatch):
        """A missing registry must never unprotect infrastructure."""
        from aipass.spawn.apps.handlers import registry as registry_module

        monkeypatch.setattr(registry_module, "find_registry", lambda *a, **k: None)

        protected, reason = registry_module.is_protected("spawn")

        assert protected is True
        assert "infrastructure" in reason

    def test_ensure_admin_refuses_rather_than_crashing(self, monkeypatch):
        from aipass.spawn.apps.handlers import registry as registry_module

        monkeypatch.setattr(registry_module, "find_registry", lambda *a, **k: None)

        status, reason = registry_module.ensure_admin()

        assert status == "refused"
        assert "registry" in reason.lower()

    def test_get_owner_returns_none_when_there_is_no_registry(self, monkeypatch):
        from aipass.spawn.apps.handlers import registry as registry_module

        monkeypatch.setattr(registry_module, "find_registry", lambda *a, **k: None)

        assert registry_module.get_owner() is None


class TestCreatePathStillStampsACredential:
    """END-TO-END regression guard for the 2026-08-24 defect, after the move.

    The mint left ``load_registry``; it must not have left the product. A
    citizen created into a brand-new project must still be born with a real
    project credential in its passport, and the registry that lands must carry
    the SAME one — the whole reason the credential is resolved before the
    passport is written rather than at registration time.
    """

    def test_a_new_project_citizen_gets_a_real_credential_in_both_files(self, tmp_path):
        from aipass.spawn.apps.modules.core import _spawn_agent

        project = tmp_path / "brandnew"
        project.mkdir()
        (project / "pyproject.toml").write_text("[project]\nname='brandnew'\n", encoding="utf-8")

        result = _spawn_agent(str(project / "src" / "brandnew" / "widget"))
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
        from aipass.spawn.apps.handlers import placeholders

        monkeypatch.setattr(placeholders, "find_registry", lambda *a, **k: None)
        target = tmp_path / "nowhere" / "widget"
        target.mkdir(parents=True)

        assert placeholders.resolve_relative_path(target) == "widget"

    def test_replacements_leave_registry_id_empty_rather_than_inventing_one(self, tmp_path, monkeypatch):
        from aipass.spawn.apps.handlers import placeholders

        monkeypatch.setattr(placeholders, "find_registry", lambda *a, **k: None)
        target = tmp_path / "nowhere" / "widget"
        target.mkdir(parents=True)

        replacements = placeholders.build_replacements_dict(str(target), "widget")

        assert replacements["REGISTRY_ID"] == "", "a credential nobody issued was substituted"


class TestEveryResolverConsumerRefusesByName:
    """Sweep pin: no spawn entry point may crash on an absent registry.

    @aipass's resolver change reached eleven more sites than the four the first
    pass caught — none exercised by a test that runs without a registry, all of
    them one ``None.parent`` away from a traceback. Type errors found them; these
    pins keep them found, because "the type checker was green that day" is not a
    thing a future reader can verify.

    Each refuses in its own vocabulary rather than raising: a delete that cannot
    consult the protection layer must not run, a sync has nothing to synchronise,
    an adoption has no project to adopt into.
    """

    def _no_registry(self, monkeypatch, module):
        monkeypatch.setattr(module, "find_registry", lambda *a, **k: None)

    def test_sync_registry_reports_the_absence(self, monkeypatch):
        from aipass.spawn.apps.handlers import sync_registry_ops

        self._no_registry(monkeypatch, sync_registry_ops)
        result = sync_registry_ops.sync_registry()

        assert "no registry" in result["error"].lower()
        assert result["stale"] == [] and result["unregistered"] == []

    def test_check_owner_identity_flags_the_absence(self, monkeypatch):
        from aipass.spawn.apps.handlers import sync_registry_ops

        self._no_registry(monkeypatch, sync_registry_ops)
        result = sync_registry_ops.check_owner_identity()

        assert result["clean"] is False
        assert any(issue["flag"] == "no_registry" for issue in result["issues"])

    def test_delete_refuses_rather_than_deleting_unchecked(self, monkeypatch):
        """The most important one: no protection layer means no delete."""
        from aipass.spawn.apps.handlers import delete_ops

        self._no_registry(monkeypatch, delete_ops)
        result = delete_ops.delete_branch("somebranch")

        assert result["success"] is False
        assert "no *_REGISTRY.json" in result["error"]

    def test_update_all_returns_nothing_to_update(self, monkeypatch):
        from aipass.spawn.apps.handlers import update_ops

        self._no_registry(monkeypatch, update_ops)

        assert update_ops.update_all() == []

    def test_adoption_refuses_with_no_project_to_adopt_into(self, tmp_path, monkeypatch):
        from aipass.spawn.apps.handlers import adoption_ops

        self._no_registry(monkeypatch, adoption_ops)
        target = tmp_path / "orphan"
        (target / ".trinity").mkdir(parents=True)
        (target / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")

        result = adoption_ops.adopt_existing(target, "", "", None)

        assert result["success"] is False
        assert "no *_REGISTRY.json" in result["error"]
