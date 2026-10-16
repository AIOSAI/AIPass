# =================== AIPass ====================
# Name: test_host_api_routes.py
# Description: Tests for the host API's live app — the extra guard, ping, bearer auth, scopes, the declared routes
# Version: 1.0.1
# Created: 2026-10-08
# Modified: 2026-10-16
# =============================================

"""Tests for create_app(), its auth and the declared routes in apps/handlers/host/server.py."""

# Split out of test_host_api.py along the unit under test (api, the oversize
# split leg, 2026-10-08): the real app over a real request path — the guard
# for the missing extra, the ping, bearer auth, scope enforcement and the
# routes that answer through it. The config and tokens live in
# test_host_api_config.py; the host-api commands in test_host_api.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(duplicate_test) — read_agent_settings() and list_projects(), test_host_{settings,fleet}.py

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import aipass.drone as drone
from aipass.api.apps.handlers.host import backup as host_backup
from aipass.api.apps.handlers.host import denials as host_denials
from aipass.api.apps.handlers.host import fleet as host_fleet
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import settings as host_settings
from aipass.api.apps.handlers.host import tokens as host_tokens

# The patch target stays this file's own constant: seedgo's discarded_patch
# rule reads a target imported from this branch's package as one it judges,
# and this silences a logger on purpose.
PATCH_SERVER_LOGGER = "aipass.api.apps.handlers.host.server.logger"
PATCH_BACKUP_DRONE = "aipass.api.apps.handlers.host.backup.drone"
PATCH_BACKUP_LOGGER = "aipass.api.apps.handlers.host.backup.logger"
PATCH_BACKUP_JSON = "aipass.api.apps.handlers.host.backup.json_handler"
PATCH_DENIALS_LOGGER = "aipass.api.apps.handlers.host.denials.logger"
PATCH_DENIALS_JSON = "aipass.api.apps.handlers.host.denials.json_handler"


# =============================================
# SERVER — handlers/host/server.py
# =============================================


class TestAvailabilityGuard:
    """Optional dependency handling — loud failure, never a silent no-op."""

    def test_create_app_without_extra_raises_with_instructions(self) -> None:
        """A missing extra tells the operator exactly how to fix it."""
        with patch.object(host_server, "HOST_API_AVAILABLE", False):
            with pytest.raises(RuntimeError) as exc:
                host_server.create_app()

        assert "install" in str(exc.value).lower()

    def test_serve_without_extra_raises_with_instructions(self) -> None:
        """Same guard on the serving path."""
        with patch.object(host_server, "HOST_API_AVAILABLE", False):
            with pytest.raises(RuntimeError):
                host_server.serve()


fastapi_required = pytest.mark.skipif(
    not host_server.is_available(),
    reason="the [host] extra is not installed",
)


@pytest.fixture
def client(store: Path):
    """A TestClient over the real app, with the token store isolated."""
    from fastapi.testclient import TestClient

    with patch(PATCH_SERVER_LOGGER):
        yield TestClient(host_server.create_app(), raise_server_exceptions=False)


@fastapi_required
class TestPing:
    """The unauthenticated liveness probe."""

    def test_ping_returns_204_without_auth(self, client: Any) -> None:
        """Reachability must be answerable without a token, or the phone cannot
        tell 'tunnel down' from 'token rejected'."""
        response = client.get("/v1/ping")

        assert response.status_code == 204

    def test_ping_has_no_body(self, client: Any) -> None:
        """It reports reachability and nothing else — no version, no hostname."""
        response = client.get("/v1/ping")

        assert response.content == b""


@fastapi_required
class TestAuth:
    """Bearer auth on a real request path."""

    def test_missing_header_is_401(self, client: Any) -> None:
        """No credentials, no answer."""
        response = client.get("/v1/whoami")

        assert response.status_code == 401

    def test_unknown_token_is_401(self, client: Any) -> None:
        """A value we never issued gets the same treatment as none at all."""
        response = client.get("/v1/whoami", headers={"Authorization": "Bearer nope"})

        assert response.status_code == 401

    def test_valid_token_is_200_and_echoes_its_own_identity(self, client: Any) -> None:
        """whoami returns only what the caller already holds."""
        record, raw = host_tokens.issue_token("pixel-8")

        response = client.get("/v1/whoami", headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 200
        assert response.json() == {"id": record["id"], "label": "pixel-8", "scope": "read"}

    def test_revoked_token_is_401_on_the_same_running_app(self, client: Any) -> None:
        """THE end-to-end property: revoke, and the very next request is denied.
        No restart, no cooperation from the phone. This is the answer to the iOS
        keychain surviving an uninstall."""
        record, raw = host_tokens.issue_token("pixel-8")
        headers = {"Authorization": f"Bearer {raw}"}
        assert client.get("/v1/whoami", headers=headers).status_code == 200

        host_tokens.revoke_token(record["id"])

        assert client.get("/v1/whoami", headers=headers).status_code == 401

    def test_errors_carry_the_shared_envelope(self, client: Any) -> None:
        """One error shape for the whole API, so the client parses one thing."""
        response = client.get("/v1/whoami")
        body = response.json()

        assert "error" in body
        assert "code" in body["error"]
        assert "message" in body["error"]


@fastapi_required
class TestScopeEnforcement:
    """require_scope on an endpoint that demands operate."""

    @pytest.fixture
    def operate_client(self, store: Path):
        """An app carrying one operate-scoped route, to exercise the dependency."""
        from fastapi import Depends
        from fastapi.testclient import TestClient

        with patch(PATCH_SERVER_LOGGER):
            app = host_server.create_app()

            @app.get("/v1/test-operate")
            async def _operate_route(record: dict = Depends(host_server.require_scope("operate"))) -> dict:
                return {"ok": True}

            yield TestClient(app, raise_server_exceptions=False)

    def test_read_token_refused_on_operate_route(self, operate_client: Any) -> None:
        """A read token reaching a destructive verb is the failure this prevents."""
        _, raw = host_tokens.issue_token("pixel-8", "read")

        response = operate_client.get("/v1/test-operate", headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 403

    def test_operate_token_accepted_on_operate_route(self, operate_client: Any) -> None:
        """The scope that is meant to work, works."""
        _, raw = host_tokens.issue_token("ops-phone", "operate")

        response = operate_client.get("/v1/test-operate", headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 200

    def test_operate_token_still_reaches_read_routes(self, operate_client: Any) -> None:
        """operate implies read, end to end."""
        _, raw = host_tokens.issue_token("ops-phone", "operate")

        response = operate_client.get("/v1/whoami", headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 200


@fastapi_required
class TestTheDeclaredRoutesAnswerThroughTheRealApp:
    """
    Four routes that were declared and never reached by a test.

    Found by seedgo's entry_point_diff on 2026-09-07, and it was right: the
    settings handler sat at 97% while not one of its six routes had ever been
    executed through the app. That is the gap this branch's own APLAN-0013 N1b
    item names, and a handler that is well tested behind a route nobody calls
    is exactly the shape a coverage number cannot show you.

    These go through the REAL app — create_app, the real dependency, the real
    auth — and assert the documented status. The handlers underneath are
    mocked, deliberately: what is unpinned is the wiring, not the logic, and a
    route test that also exercises the handler cannot say which of the two
    broke.
    """

    @pytest.fixture
    def routed(self, store: Path):
        """The real app plus a read token and an operate token for it."""
        from fastapi.testclient import TestClient

        with patch(PATCH_SERVER_LOGGER):
            _, read_raw = host_tokens.issue_token("phone", "read")
            _, operate_raw = host_tokens.issue_token("ops-phone", "operate")
            client = TestClient(host_server.create_app(), raise_server_exceptions=False)
            yield client, read_raw, operate_raw

    def test_agent_settings_reads_through_the_route(self, routed: Any) -> None:
        """GET /v1/agent-settings answers 200 with the handler's document."""
        api, read_raw, _ = routed
        owned = {"model": "opus", "outputStyle": None, "statusLine": None}

        with patch.object(host_server.host_reads, "resolve_branch_root") as resolver:
            with patch.object(host_server.host_settings, "read_agent_settings", return_value=owned) as reader:
                response = api.get(
                    "/v1/agent-settings",
                    params={"branch": "demo"},
                    headers={"Authorization": f"Bearer {read_raw}"},
                )

        assert response.status_code == 200
        assert response.json() == owned
        resolver.assert_called_once_with("demo")
        reader.assert_called_once_with(resolver.return_value)

    def test_agent_settings_refuses_a_patch_that_is_not_an_object(self, routed: Any) -> None:
        """
        POST /v1/agent-settings answers 400 when `patch` is not a JSON object.

        The route's own guard, before any handler runs — so this is the one
        piece of that endpoint that genuinely lives in the route and could not
        be pinned anywhere else.
        """
        api, _, operate_raw = routed

        response = api.post(
            "/v1/agent-settings",
            json={"branch": "demo", "patch": "not-an-object"},
            headers={"Authorization": f"Bearer {operate_raw}"},
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "settings_refused"

    def test_baud_settings_reads_through_the_route(self, routed: Any) -> None:
        """GET /v1/baud-settings answers 200 with BAUD's whole document."""
        api, read_raw, _ = routed
        document = {"theme": "dark", "fontSize": 14}

        with patch.object(host_server.host_reads, "repo_root") as root:
            with patch.object(host_server.host_settings, "read_baud_settings", return_value=document) as reader:
                response = api.get("/v1/baud-settings", headers={"Authorization": f"Bearer {read_raw}"})

        assert response.status_code == 200
        assert response.json() == document
        root.assert_called_once_with()
        reader.assert_called_once_with(root.return_value)

    def test_baud_settings_answers_503_when_the_document_cannot_be_read(self, routed: Any) -> None:
        """A SettingsUnavailable becomes 503, not a 500 traceback at the phone."""
        api, read_raw, _ = routed
        broken = host_settings.SettingsUnavailable("the settings file is not readable")

        with patch.object(host_server.host_reads, "repo_root") as root:
            with patch.object(host_server.host_settings, "read_baud_settings", side_effect=broken) as reader:
                response = api.get("/v1/baud-settings", headers={"Authorization": f"Bearer {read_raw}"})

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "settings_unavailable"
        reader.assert_called_once_with(root.return_value)

    def test_hooks_sound_reads_the_live_flag_through_the_route(self, routed: Any) -> None:
        """GET /v1/hooks-sound answers 200 and reports the flag as a bool."""
        api, read_raw, _ = routed

        with patch.object(host_server.host_settings, "hooks_sound_get", return_value=True) as reader:
            response = api.get("/v1/hooks-sound", headers={"Authorization": f"Bearer {read_raw}"})

        assert response.status_code == 200
        assert response.json() == {"active": True}
        reader.assert_called_once()

    def test_hooks_sound_refuses_a_non_boolean_active(self, routed: Any) -> None:
        """
        POST /v1/hooks-sound answers 400 unless `active` is a real boolean.

        A string "false" is the dangerous input here: truthy in most languages
        the phone could be written in, and it must not read as "on".
        """
        api, _, operate_raw = routed

        response = api.post(
            "/v1/hooks-sound",
            json={"active": "false"},
            headers={"Authorization": f"Bearer {operate_raw}"},
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "settings_refused"

    def test_projects_answers_the_census_through_the_route(self, routed: Any, tmp_path: Path) -> None:
        """
        GET /v1/projects answers 200 with @baud's project census.

        list_projects runs for real; only its far side is stubbed — the binary
        lookup, the repo root, and the exec itself, which records its argv.
        """
        api, read_raw, _ = routed
        census = {"projects": [{"name": "AIPass", "path": "/somewhere"}]}
        answered = host_fleet.subprocess.CompletedProcess(["baud"], 0, stdout=json.dumps(census), stderr="")

        with (
            patch.object(host_fleet, "snapshot_binary", return_value="baud"),
            patch.object(host_fleet, "repo_root", return_value=tmp_path),
            patch.object(host_fleet, "json_handler") as journal,
            patch.object(host_fleet.subprocess, "run", return_value=answered) as run,
        ):
            response = api.get("/v1/projects", headers={"Authorization": f"Bearer {read_raw}"})

        assert response.status_code == 200
        assert response.json() == census
        assert run.call_args.args[0] == ["baud", "--list-projects"]
        assert run.call_args.kwargs["cwd"] == str(tmp_path)
        journal.log_operation.assert_called_once_with("host_api_project_census", {"projects": 1})

    def test_projects_answers_503_when_the_fleet_binary_is_unreachable(self, routed: Any) -> None:
        """
        A FleetUnavailable becomes 503, and this is the arm that matters.

        The switcher menu going empty and the switcher menu failing are two
        different sentences on the phone, and only one of them is honest when
        the binary did not answer.
        """
        api, read_raw, _ = routed
        broken = host_fleet.FleetUnavailable("the fleet binary did not answer")

        with patch.object(host_server.host_fleet, "list_projects", side_effect=broken):
            response = api.get("/v1/projects", headers={"Authorization": f"Bearer {read_raw}"})

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "fleet_unavailable"

    def test_every_one_of_these_routes_is_behind_the_auth(self, routed: Any) -> None:
        """
        None of the four is public, checked in one place.

        Parametrised into one unit rather than four: the claim is about the
        SET, and a per-route test would let one of them quietly leave the set
        without anything going red.
        """
        api, _, _ = routed
        declared = ["/v1/agent-settings", "/v1/baud-settings", "/v1/hooks-sound", "/v1/projects"]

        unguarded = [route for route in declared if api.get(route).status_code != 401]

        assert unguarded == [], f"these routes answered without a token: {unguarded}"


@fastapi_required
class TestTheBackupDoorAnswersThroughTheRealApp:
    """POST /v1/backup/run, GET /v1/backup/job and GET /v1/backup/status, wired (DPLAN-0411)."""

    @pytest.fixture
    def backup(self, store: Path, seated: Path, monkeypatch: Any):
        """The real app, a read and an operate token, a fresh job table, and drone replaced at backup.py."""
        from fastapi.testclient import TestClient

        workers: list = []
        monkeypatch.setattr(host_backup, "JOBS", host_backup.JobTable(start=lambda target, args: workers.append(args)))
        router = MagicMock()
        router.RoutingError = drone.RoutingError
        with (
            patch(PATCH_SERVER_LOGGER),
            patch(PATCH_BACKUP_DRONE, router),
            patch(PATCH_BACKUP_LOGGER),
            patch(PATCH_BACKUP_JSON),
            patch(PATCH_DENIALS_LOGGER),
            patch(PATCH_DENIALS_JSON),
        ):
            _, read_raw = host_tokens.issue_token("phone", "read")
            _, operate_raw = host_tokens.issue_token("ops-phone", "operate")
            client = TestClient(host_server.create_app(), raise_server_exceptions=False)
            yield (
                client,
                {"Authorization": f"Bearer {read_raw}"},
                {"Authorization": f"Bearer {operate_raw}"},
                router,
                workers,
            )

    def test_run_answers_202_with_the_running_job(self, backup: Any) -> None:
        api, _, operate, _, workers = backup

        response = api.post("/v1/backup/run", json={"project": "AIPASS", "lane": "snapshot"}, headers=operate)

        assert response.status_code == 202
        job = response.json()
        assert set(job) == {"job", "project", "lane", "state", "started_at"}
        assert (job["project"], job["lane"], job["state"]) == ("AIPASS", "snapshot", "running")
        assert len(workers) == 1

    def test_a_read_token_is_refused_on_run_and_starts_nothing(self, backup: Any) -> None:
        api, read, _, _, workers = backup

        response = api.post("/v1/backup/run", json={"project": "AIPASS", "lane": "snapshot"}, headers=read)

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"
        assert workers == []

    def test_a_second_run_is_400_with_the_already_running_sentence(self, backup: Any) -> None:
        api, _, operate, _, _ = backup
        first = api.post("/v1/backup/run", json={"project": "AIPASS", "lane": "snapshot"}, headers=operate).json()

        response = api.post("/v1/backup/run", json={"project": "AIPASS", "lane": "snapshot"}, headers=operate)

        assert response.status_code == 400
        assert response.json()["error"] == {
            "code": "verb_refused",
            "message": f"snapshot already running for AIPASS since {first['started_at']}",
        }

    @pytest.mark.parametrize("body", [{"project": "AIPASS"}, {"project": "AIPASS", "lane": "nightly"}, {"lane": "all"}])
    def test_a_missing_lane_bad_lane_or_missing_project_is_400(self, backup: Any, body: dict) -> None:
        api, _, operate, _, workers = backup

        response = api.post("/v1/backup/run", json=body, headers=operate)

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "verb_refused"
        assert workers == []

    def test_an_unknown_project_is_400_in_the_census_words(self, backup: Any) -> None:
        api, _, operate, _, _ = backup

        with patch.object(host_fleet, "list_projects", return_value={"projects": []}):
            response = api.post("/v1/backup/run", json={"project": "VERA", "lane": "snapshot"}, headers=operate)

        assert response.status_code == 400
        assert "No project named 'VERA'" in response.json()["error"]["message"]

    def test_backup_unreachable_before_start_is_503_with_a_ref(self, backup: Any) -> None:
        api, _, operate, router, workers = backup
        router.resolve_branch.side_effect = drone.RoutingError("Branch not found: @backup")

        response = api.post("/v1/backup/run", json={"project": "AIPASS", "lane": "snapshot"}, headers=operate)

        assert response.status_code == 503
        error = response.json()["error"]
        assert error["code"] == "verb_unavailable"
        assert error["message"] == host_denials.SENTENCES["verb_unavailable"]
        assert error["ref"]
        assert workers == []

    def test_a_job_reads_with_a_read_token(self, backup: Any) -> None:
        api, read, operate, _, _ = backup
        job = api.post("/v1/backup/run", json={"project": "AIPASS", "lane": "snapshot"}, headers=operate).json()

        response = api.get("/v1/backup/job", params={"id": job["job"]}, headers=read)

        assert response.status_code == 200
        assert response.json() == job

    def test_an_unknown_job_is_404_job_unknown(self, backup: Any) -> None:
        api, read, _, _, _ = backup

        response = api.get("/v1/backup/job", params={"id": "b7f3c2"}, headers=read)

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "job_unknown"

    def test_status_passes_backup_through_with_the_running_list(self, backup: Any, seated: Path) -> None:
        api, read, operate, router, _ = backup
        router.route_command.return_value = MagicMock(exit_code=0, stdout=json.dumps({"runs": 64}), stderr="")
        job = api.post("/v1/backup/run", json={"project": "AIPASS", "lane": "snapshot"}, headers=operate).json()

        response = api.get("/v1/backup/status", params={"project": "AIPASS", "sizes": "1"}, headers=read)

        assert response.status_code == 200
        body = response.json()
        assert Path(body.pop("root")) == seated.resolve()
        assert body == {
            "runs": 64,
            "project": "AIPASS",
            "running": [{"job": job["job"], "lane": "snapshot", "started_at": job["started_at"]}],
        }
        assert router.route_command.call_args.args[2][1:] == ["--json", "--sizes"]

    def test_status_without_sizes_does_not_ask_for_them(self, backup: Any) -> None:
        api, read, _, router, _ = backup
        router.route_command.return_value = MagicMock(exit_code=0, stdout="{}", stderr="")

        api.get("/v1/backup/status", params={"project": "AIPASS"}, headers=read)

        assert router.route_command.call_args.args[2][1:] == ["--json"]

    def test_a_status_that_is_not_json_is_503_naming_the_missing_flag(self, backup: Any) -> None:
        api, read, _, router, _ = backup
        router.route_command.return_value = MagicMock(exit_code=0, stdout="╭─ Backup ─╮", stderr="")

        response = api.get("/v1/backup/status", params={"project": "AIPASS"}, headers=read)

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "verb_unavailable"
        assert response.json()["error"]["message"] == host_backup.STATUS_JSON_MISSING

    def test_every_backup_route_is_behind_the_auth(self, backup: Any) -> None:
        api, _, _, _, _ = backup

        answered = [
            api.post("/v1/backup/run", json={"project": "AIPASS", "lane": "snapshot"}).status_code,
            api.get("/v1/backup/job", params={"id": "b7f3c2"}).status_code,
            api.get("/v1/backup/status", params={"project": "AIPASS"}).status_code,
        ]

        assert answered == [401, 401, 401]
