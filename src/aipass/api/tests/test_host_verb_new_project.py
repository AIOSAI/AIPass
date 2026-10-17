# =================== AIPass ====================
# Name: test_host_verb_new_project.py
# Description: Tests for POST /v1/verbs/new-project, the phone's new-project door (FPLAN-0649)
# Version: 1.0.0
# Created: 2026-10-16
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/host/new_project_route.py and verbs.new_project behind it."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that new_project_route.py parses and imports
# seedgo: no-test-needed(external) — project_door's real create_project, @aipass's; every call to it is patched

import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from aipass.aipass.apps.modules import new_project as project_door
from aipass.api.apps.handlers.host import denials as host_denials
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import tokens as host_tokens
from aipass.api.apps.handlers.host import verbs as host_verbs

ROUTE = "/v1/verbs/new-project"
TEMPLATES = ("empty", "python")
PATCH_QUIET = (
    "aipass.api.apps.handlers.host.server.logger",
    "aipass.api.apps.handlers.host.server.json_handler",
    "aipass.api.apps.handlers.host.face.logger",
    "aipass.api.apps.handlers.host.face.json_handler",
    "aipass.api.apps.handlers.host.denials.logger",
    "aipass.api.apps.handlers.host.denials.json_handler",
    "aipass.api.apps.handlers.host.verbs.logger",
)

fastapi_required = pytest.mark.skipif(not host_server.is_available(), reason="the [host] extra is not installed")


def _result(seat: Path, name: str = "probe", template: str = "empty") -> dict:
    """What create_project answers, field for field."""
    target = seat / "projects" / name
    return {
        "name": name,
        "template": template,
        "target": str(target),
        "host": str(seat),
        "registry_id": "0f0f",
        "registry_file": "PROBE_REGISTRY.json",
        "files": ["README.md"],
        "agent_created": True,
        "agent_home": str(target / "src" / name / name),
        "spawn_result": {"success": True, "branch_name": "probe_manager", "files_copied": 9},
    }


@pytest.fixture
def seat(tmp_path: Path) -> Path:
    """The installation root this server is seated in, as repo_root() names it."""
    return tmp_path / "seat"


@pytest.fixture
def door(seat: Path):
    """@aipass's create_project, patched where verbs.py looks it up; never a real project."""
    with patch.object(project_door, "TEMPLATES", TEMPLATES, create=True):
        with patch.object(project_door, "create_project", create=True) as create:
            create.return_value = _result(seat)
            with patch.object(host_verbs.host_reads, "repo_root", return_value=seat):
                yield create


@pytest.fixture
def journal(store: Path):
    """verbs.py's json log, held so a test can read what the verb recorded."""
    with patch("aipass.api.apps.handlers.host.verbs.json_handler") as handler:
        yield handler


@pytest.fixture
def client(store: Path, journal: Any):
    """A test client over the conftest token store, every log of the lane silenced."""
    from contextlib import ExitStack

    from fastapi.testclient import TestClient

    with ExitStack() as stack:
        for target in PATCH_QUIET:
            stack.enter_context(patch(target))
        yield TestClient(host_server.create_app(), raise_server_exceptions=False)


def _post(client: Any, body: Any, scope: str = "operate") -> Any:
    """POST the route with a fresh token of *scope*."""
    _, raw = host_tokens.issue_token("phone", scope=scope)
    return client.post(ROUTE, json=body, headers={"Authorization": f"Bearer {raw}"})


def _error(response: Any) -> dict:
    """The shared error envelope's inner object."""
    return response.json()["error"]


@fastapi_required
class TestTheNameIsRefusedBeforeTheDoor:
    def test_an_empty_body_is_a_400_project_name_refused_and_creates_nothing(self, client: Any, door: Any) -> None:
        response = _post(client, {})

        assert response.status_code == 400
        assert _error(response)["code"] == "project_name_refused"
        assert "letter" in _error(response)["message"]
        assert not door.called

    @pytest.mark.parametrize("name", ["1project", "a" * 65, "two words", "dot.name", "probe\n", "-probe"])
    def test_a_name_outside_the_rule_is_a_400_and_creates_nothing(self, client: Any, door: Any, name: str) -> None:
        response = _post(client, {"name": name})

        assert response.status_code == 400
        assert _error(response)["code"] == "project_name_refused"
        assert not door.called

    def test_a_64_character_name_is_inside_the_cap_and_reaches_the_door(self, client: Any, door: Any) -> None:
        response = _post(client, {"name": "a" * 64})

        assert response.status_code == 200
        assert door.call_args.args[0] == "a" * 64


@fastapi_required
class TestTheTemplateIsRefusedBeforeTheDoor:
    def test_an_unknown_template_is_a_400_listing_the_templates(self, client: Any, door: Any) -> None:
        response = _post(client, {"name": "probe", "template": "rust"})

        assert response.status_code == 400
        assert _error(response)["code"] == "template_refused"
        assert all(template in _error(response)["message"] for template in TEMPLATES)
        assert not door.called

    def test_an_omitted_template_is_empty(self, client: Any, door: Any) -> None:
        _post(client, {"name": "probe"})

        assert door.call_args.args[1] == "empty"


@fastapi_required
class TestTheDoorsRefusalsMapToCodes:
    def test_project_already_exists_is_a_409_carrying_the_functions_sentence(
        self, client: Any, door: Any, seat: Path
    ) -> None:
        sentence = f"Project already exists: {seat / 'projects' / 'probe'}"
        door.side_effect = RuntimeError(sentence)

        response = _post(client, {"name": "probe"})

        assert response.status_code == 409
        assert _error(response) == {"code": "project_exists", "message": sentence}

    def test_another_runtime_error_is_a_503_with_the_fixed_sentence_and_a_ref(self, client: Any, door: Any) -> None:
        door.side_effect = RuntimeError("git commit: fatal: unable to auto-detect email address (got 'zork@quux')")

        response = _post(client, {"name": "probe"})

        assert response.status_code == 503
        assert _error(response)["code"] == "project_door_failed"
        assert _error(response)["message"] == host_denials.SENTENCES["project_door_failed"]
        assert _error(response)["ref"]
        assert "zork" not in response.text

    def test_an_os_error_from_the_door_is_a_503_and_keeps_its_words(self, client: Any, door: Any) -> None:
        door.side_effect = OSError("zork quux refused")

        response = _post(client, {"name": "probe"})

        assert response.status_code == 503
        assert _error(response)["code"] == "project_door_failed"
        assert "zork" not in response.text

    def test_a_value_error_from_the_door_is_a_400_and_keeps_its_words(self, client: Any, door: Any) -> None:
        door.side_effect = ValueError("zork quux is not a name")

        response = _post(client, {"name": "probe"})

        assert response.status_code == 400
        assert _error(response)["code"] == "project_refused"
        assert _error(response)["ref"]
        assert "zork" not in response.text

    def test_a_door_without_create_project_is_a_503_never_a_500(self, client: Any, door: Any) -> None:
        with patch.object(project_door, "create_project", None, create=True):
            response = _post(client, {"name": "probe"})

        assert response.status_code == 503
        assert _error(response)["code"] == "project_door_failed"


@fastapi_required
class TestAProjectIsCreatedWithItsManager:
    def test_the_200_carries_the_contracts_shape_exactly(self, client: Any, door: Any, seat: Path) -> None:
        response = _post(client, {"name": "probe", "template": "empty"})

        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "name": "probe",
            "target": str(seat / "projects" / "probe"),
            "template": "empty",
            "agent": "probe_manager",
            "agent_home": str(seat / "projects" / "probe" / "src" / "probe" / "probe"),
            "detail": "Project probe created with its manager agent",
        }

    def test_the_call_names_the_seat_as_host_and_always_makes_the_agent(
        self, client: Any, door: Any, seat: Path
    ) -> None:
        door.return_value = _result(seat, template="python")

        _post(client, {"name": "probe", "template": "python"})

        assert door.call_args.args == ("probe", "python")
        assert door.call_args.kwargs == {"no_agent": False, "host": seat}

    def test_the_server_never_changes_its_working_directory(self, client: Any, door: Any) -> None:
        before = os.getcwd()
        door.side_effect = lambda *args, **kwargs: (os.getcwd(), _result(kwargs["host"]))[1]

        _post(client, {"name": "probe"})

        assert os.getcwd() == before

    def test_the_verb_records_the_outcome_and_the_refusal_code(self, client: Any, door: Any, journal: Any) -> None:
        _post(client, {"name": "probe"})
        _post(client, {"name": "1probe"})

        records = [call.args for call in journal.log_operation.call_args_list]
        assert ("host_api_verb_new_project", {"name": "probe", "template": "empty", "ok": True}) in records
        refused = {"name": "1probe", "template": "empty", "ok": False, "code": "project_name_refused"}
        assert ("host_api_verb_new_project", refused) in records


@fastapi_required
class TestTheScopeWallStopsTheDoor:
    def test_a_read_token_is_a_403_and_creates_nothing(self, client: Any, door: Any) -> None:
        response = _post(client, {"name": "probe"}, scope="read")

        assert response.status_code == 403
        assert not door.called

    def test_no_token_is_a_401_and_creates_nothing(self, client: Any, door: Any) -> None:
        response = client.post(ROUTE, json={"name": "probe"})

        assert response.status_code == 401
        assert not door.called

    def test_the_route_is_post_only(self, client: Any, door: Any) -> None:
        _, raw = host_tokens.issue_token("phone", scope="operate")

        response = client.get(ROUTE, headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 405
        assert not door.called
