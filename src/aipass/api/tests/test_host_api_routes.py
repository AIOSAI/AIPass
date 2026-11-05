# =================== AIPass ====================
# Name: test_host_api_routes.py
# Description: Tests for the host API's live app — the extra guard, ping, bearer auth, scopes, the declared routes
# Version: 1.4.0
# Created: 2026-10-08
# Modified: 2026-11-05
# =============================================

"""Tests for create_app(), its auth and the declared routes in apps/handlers/host/server.py."""

# Split out of test_host_api.py along the unit under test (api, the oversize
# split leg, 2026-10-08): the real app over a real request path — the guard
# for the missing extra, the ping, bearer auth, scope enforcement and the
# routes that answer through it. The config and tokens live in
# test_host_api_config.py; the host-api commands in test_host_api.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(duplicate_test) — read_agent_settings() and list_projects(), test_host_{settings,fleet}.py

import json
import os
import re
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import aipass.drone as drone
from aipass.api.apps.handlers.host import agent_models as host_agent_models
from aipass.api.apps.handlers.host import agent_usage as host_agent_usage
from aipass.api.apps.handlers.host import backup as host_backup
from aipass.api.apps.handlers.host import denials as host_denials
from aipass.api.apps.handlers.host import fleet as host_fleet
from aipass.api.apps.handlers.host import machine as host_machine
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import settings as host_settings
from aipass.api.apps.handlers.host import tokens as host_tokens
from aipass.api.tests.support_host_api import FakeBaud, agent_row

# The patch target stays this file's own constant: sentry's discarded_patch
# rule reads a target imported from this branch's package as one it judges,
# and this silences a logger on purpose.
PATCH_SERVER_LOGGER = "aipass.api.apps.handlers.host.server.logger"
PATCH_BACKUP_DRONE = "aipass.api.apps.handlers.host.backup.drone"
PATCH_BACKUP_LOGGER = "aipass.api.apps.handlers.host.backup.logger"
PATCH_BACKUP_JSON = "aipass.api.apps.handlers.host.backup.json_handler"
PATCH_DENIALS_LOGGER = "aipass.api.apps.handlers.host.denials.logger"
PATCH_DENIALS_JSON = "aipass.api.apps.handlers.host.denials.json_handler"
PATCH_MACHINE_LOGGER = "aipass.api.apps.handlers.host.machine.logger"
PATCH_MACHINE_JSON = "aipass.api.apps.handlers.host.machine.json_handler"
# @skills' process door, patched where it lives: machine.py imports it inside the call.
PATCH_PROCESSES_DOOR = "aipass.skills.lib.system_status.handler.machine_processes"


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
def client(store: Path, host_app: Any):
    """A TestClient over the real app, with the token store isolated."""
    from fastapi.testclient import TestClient

    with patch(PATCH_SERVER_LOGGER):
        yield TestClient(host_app, raise_server_exceptions=False)


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

    Found by sentry's entry_point_diff on 2026-09-07, and it was right: the
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
    def routed(self, store: Path, host_app: Any):
        """The real app plus a read token and an operate token for it."""
        from fastapi.testclient import TestClient

        with patch(PATCH_SERVER_LOGGER):
            _, read_raw = host_tokens.issue_token("phone", "read")
            _, operate_raw = host_tokens.issue_token("ops-phone", "operate")
            client = TestClient(host_app, raise_server_exceptions=False)
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
        resolver.assert_called_once_with("demo", "")
        reader.assert_called_once_with(resolver.return_value)

    def _external_citizen(self, tmp_path: Path) -> Path:
        """vera's branch in another project, with keys the door does not own."""
        vera = tmp_path / "Vera-Studio" / "src" / "vera_studio" / "vera"
        (vera / ".claude").mkdir(parents=True)
        owned_by_others = {"model": "opus", "permissions": {"allow": ["Bash(ls)"]}, "enabledMcpjsonServers": ["x"]}
        (vera / ".claude" / "settings.local.json").write_text(json.dumps(owned_by_others), encoding="utf-8")
        return vera

    def test_agent_settings_reads_an_external_projects_citizen(self, routed: Any, tmp_path: Path) -> None:
        api, read_raw, _ = routed
        vera = self._external_citizen(tmp_path)

        with patch.object(host_fleet, "resolve_branch", return_value={"name": "vera", "path": str(vera)}) as census:
            response = api.get(
                "/v1/agent-settings",
                params={"branch": "vera", "project": "VERA-STUDIO"},
                headers={"Authorization": f"Bearer {read_raw}"},
            )

        assert response.status_code == 200
        assert response.json()["model"] == "opus"
        census.assert_called_once_with("VERA-STUDIO", "vera")

    def test_agent_settings_writes_an_external_projects_citizen_and_keeps_its_other_keys(
        self, routed: Any, tmp_path: Path
    ) -> None:
        api, _, operate_raw = routed
        vera = self._external_citizen(tmp_path)

        with patch.object(host_fleet, "resolve_branch", return_value={"name": "vera", "path": str(vera)}):
            response = api.post(
                "/v1/agent-settings",
                json={"branch": "vera", "project": "VERA-STUDIO", "patch": {"auto_compact_window": 300_000}},
                headers={"Authorization": f"Bearer {operate_raw}"},
            )

        assert response.status_code == 200
        written = json.loads((vera / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
        assert written == {
            "model": "opus",
            "permissions": {"allow": ["Bash(ls)"]},
            "enabledMcpjsonServers": ["x"],
            "autoCompactWindow": 300_000,
        }

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

    def test_hooks_sound_read_that_fails_is_a_503_not_a_guess(self, routed: Any) -> None:
        """An unreadable hooks state is 503 settings_unavailable, never a default bool."""
        api, read_raw, _ = routed
        broken = host_settings.SettingsUnavailable("The hooks sound state could not be read: ")

        with patch.object(host_server.host_settings, "hooks_sound_get", side_effect=broken):
            response = api.get("/v1/hooks-sound", headers={"Authorization": f"Bearer {read_raw}"})

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "settings_unavailable"

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
    """POST /v1/backup/run and /cancel, GET /v1/backup/job and /status, wired."""

    @pytest.fixture
    def backup(self, store: Path, seated: Path, monkeypatch: Any, host_app: Any):
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
            client = TestClient(host_app, raise_server_exceptions=False)
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
        # The body carries the fixed sentence, never the exception's own text (CodeQL stack-trace-exposure).
        assert response.json()["error"]["message"] == host_backup.JOB_UNKNOWN
        assert "b7f3c2" not in response.text

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
            api.post("/v1/backup/cancel", json={"project": "AIPASS", "lane": "snapshot"}).status_code,
            api.get("/v1/backup/job", params={"id": "b7f3c2"}).status_code,
            api.get("/v1/backup/status", params={"project": "AIPASS"}).status_code,
        ]

        assert answered == [401, 401, 401, 401]

    def test_cancel_answers_200_with_stops_line_after_routing_stop_with_root_and_lane(
        self, backup: Any, seated: Path
    ) -> None:
        api, _, operate, router, _ = backup
        router.route_command.return_value = MagicMock(exit_code=0, stdout="stopped all (pid 4242)\n", stderr="")

        response = api.post("/v1/backup/cancel", json={"project": "AIPASS", "lane": "all"}, headers=operate)

        assert response.status_code == 200
        stopped = {"project": "AIPASS", "lane": "all", "stopped": True, "message": "stopped all (pid 4242)"}
        assert response.json() == stopped
        target, verb, argv = router.route_command.call_args.args
        assert (target, verb, len(argv), argv[1]) == ("@backup", "stop", 2, "all")
        assert Path(argv[0]) == seated.resolve()

    def test_cancel_with_nothing_running_is_404_not_running_in_backups_words(self, backup: Any) -> None:
        api, _, operate, router, _ = backup
        router.route_command.return_value = MagicMock(exit_code=1, stdout="nothing running for AIPass\n", stderr="")

        response = api.post("/v1/backup/cancel", json={"project": "AIPASS", "lane": "all"}, headers=operate)

        assert response.status_code == 404
        assert response.json()["error"] == {"code": "not_running", "message": "nothing running for AIPass"}

    def test_cancel_never_answers_backups_stderr(self, backup: Any) -> None:
        api, _, operate, router, _ = backup
        crash = 'Traceback (most recent call last):\n  File "/home/x/stop.py", line 9\nKeyError: pid\n'
        router.route_command.return_value = MagicMock(exit_code=1, stdout="", stderr=crash)

        response = api.post("/v1/backup/cancel", json={"project": "AIPASS", "lane": "all"}, headers=operate)

        assert response.status_code == 503
        error = response.json()["error"]
        assert (error["code"], error["message"]) == ("verb_unavailable", host_denials.SENTENCES["verb_unavailable"])
        assert "Traceback" not in response.text and "stop.py" not in response.text

    def test_cancel_with_backup_unreachable_is_503_with_a_ref(self, backup: Any) -> None:
        api, _, operate, router, _ = backup
        router.route_command.side_effect = drone.RoutingError("Branch not found: @backup")

        response = api.post("/v1/backup/cancel", json={"project": "AIPASS", "lane": "all"}, headers=operate)

        assert response.status_code == 503
        error = response.json()["error"]
        assert (error["code"], error["message"]) == ("verb_unavailable", host_denials.SENTENCES["verb_unavailable"])
        assert error["ref"]

    @pytest.mark.parametrize(
        "body",
        [
            {"project": "AIPASS"},
            {"project": "AIPASS", "lane": "nightly"},
            {"lane": "all"},
            {"project": "VERA", "lane": "all"},
        ],
    )
    def test_cancel_with_a_missing_or_unknown_lane_or_project_is_400_and_asks_nothing(
        self, backup: Any, body: dict
    ) -> None:
        api, _, operate, router, _ = backup

        with patch.object(host_fleet, "list_projects", return_value={"projects": []}):
            response = api.post("/v1/backup/cancel", json=body, headers=operate)

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "verb_refused"
        router.route_command.assert_not_called()

    def test_a_read_token_is_refused_on_cancel_and_stops_nothing(self, backup: Any) -> None:
        api, read, _, router, _ = backup

        response = api.post("/v1/backup/cancel", json={"project": "AIPASS", "lane": "all"}, headers=read)

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"
        router.route_command.assert_not_called()

    def test_status_passes_backups_running_list_through_with_the_job_added(self, backup: Any) -> None:
        api, read, operate, router, _ = backup
        job = api.post("/v1/backup/run", json={"project": "AIPASS", "lane": "drive_sync"}, headers=operate).json()
        entry = {"verb": "drive_sync", "lane": "drive_sync", "pid": 175450, "started_at": "x", "progress": None}
        router.route_command.return_value = MagicMock(exit_code=0, stdout=json.dumps({"running": [entry]}), stderr="")

        response = api.get("/v1/backup/status", params={"project": "AIPASS"}, headers=read)

        assert response.status_code == 200
        assert response.json()["running"] == [{**entry, "job": job["job"]}]

    def test_a_running_that_is_not_a_list_is_503_with_the_fixed_sentence(self, backup: Any) -> None:
        api, read, _, router, _ = backup
        router.route_command.return_value = MagicMock(exit_code=0, stdout=json.dumps({"running": {}}), stderr="")

        response = api.get("/v1/backup/status", params={"project": "AIPASS"}, headers=read)

        assert response.status_code == 503
        error = response.json()["error"]
        assert (error["code"], error["message"]) == ("verb_unavailable", host_denials.SENTENCES["verb_unavailable"])


def _processes() -> dict:
    """What machine_processes() answers, contract C-B's shape, manufactured here. A success has no `ok` key."""
    chrome = {"pid": 1234, "name": "chrome", "cpu_pct": 42.5, "mem_pct": 3.1, "mem_mb": 512, "state": "running"}
    kworker = {"pid": 77, "name": "kworker", "cpu_pct": 0.0, "mem_pct": 0.0, "mem_mb": 0, "state": "idle"}
    return {
        "sampled_at": "2026-10-16T21:44:00.000+00:00",
        "window_ms": 503,
        "total": 245,
        "sort": "cpu",
        "processes": [{**chrome, "user": "u"}, {**kworker, "user": None}],
    }


# A failed door's whole error body: its code and the one fixed sentence, nothing of the exception's.
_DOOR_FAILED = {"code": "machine_door_failed", "message": host_machine.PROCESSES_DOOR_FAILED}


@fastapi_required
class TestTheMachineProcessesRoute:
    """GET /v1/machine/processes: the skill's dict verbatim, refused exactly as /v1/machine."""

    @pytest.fixture
    def processes(self, store: Path, host_app: Any):
        """The real app, a read token, and @skills' process door replaced where it lives."""
        from fastapi.testclient import TestClient

        with (
            patch(PATCH_SERVER_LOGGER),
            patch(PATCH_MACHINE_LOGGER) as log,
            patch(PATCH_MACHINE_JSON),
            patch(PATCH_DENIALS_LOGGER),
            patch(PATCH_DENIALS_JSON),
            patch(PATCH_PROCESSES_DOOR, autospec=True) as door,
        ):
            _, raw = host_tokens.issue_token("phone", "read")
            client = TestClient(host_app, raise_server_exceptions=False)
            yield client, {"Authorization": f"Bearer {raw}"}, door, log

    def test_the_route_requires_a_token(self, processes: Any) -> None:
        """Process names are machine state; they sit behind the same auth as everything."""
        api, _, door, _ = processes

        response = api.get("/v1/machine/processes")

        assert response.status_code == 401
        door.assert_not_called()

    def test_a_success_passes_through_untouched_with_the_default_limit(self, processes: Any) -> None:
        """The whole body is compared, so any reshaping in the request path goes red; no limit asks for 20."""
        api, read, door, _ = processes
        door.return_value = _processes()

        response = api.get("/v1/machine/processes", headers=read)

        assert response.status_code == 200
        assert response.json() == _processes()
        door.assert_called_once_with(20)

    @pytest.mark.parametrize("limit", [5, 500, 0])
    def test_the_limit_travels_verbatim_for_the_skill_to_clamp(self, processes: Any, limit: int) -> None:
        """The skill owns the 1..100 clamp; a second clamp here would be a second answer."""
        api, read, door, _ = processes
        door.return_value = _processes()

        response = api.get("/v1/machine/processes", params={"limit": limit}, headers=read)

        assert response.status_code == 200
        door.assert_called_once_with(limit)

    def test_a_limit_that_is_not_a_number_is_a_400_and_samples_nothing(self, processes: Any) -> None:
        """limit=abc is the caller's mistake, said in a sentence: never a 500, never a sample."""
        api, read, door, _ = processes

        response = api.get("/v1/machine/processes", params={"limit": "abc"}, headers=read)

        assert response.status_code == 400
        error = response.json()["error"]
        assert error["code"] == "machine_limit_refused"
        assert "whole number" in error["message"]
        door.assert_not_called()

    def test_another_parameter_is_refused_not_dropped(self, processes: Any) -> None:
        """A sort=mem the route ignored would read as a sort that worked."""
        api, read, door, _ = processes

        response = api.get("/v1/machine/processes", params={"sort": "mem"}, headers=read)

        assert response.status_code == 400
        error = response.json()["error"]
        assert error["code"] == "machine_parameters_refused"
        assert "sort" in error["message"]
        door.assert_not_called()

    @pytest.mark.parametrize(
        ("reason", "detail"),
        [
            ("psutil_missing", "pip install psutil, the recipe"),
            ("switched_off", "Skill 'system_status' is switched OFF and takes no readings."),
        ],
    )
    def test_a_refusal_maps_the_way_the_vitals_refusal_does(self, processes: Any, reason: str, detail: str) -> None:
        """ok False: 503 machine_refused, the code in `reason`, the fixed sentence, the detail off the wire."""
        api, read, door, _ = processes
        door.return_value = {"ok": False, "reason": reason, "detail": detail}

        response = api.get("/v1/machine/processes", headers=read)

        assert response.status_code == 503
        error = response.json()["error"]
        assert error == {
            "code": "machine_refused",
            "message": host_denials.SENTENCES["machine_refused"],
            "reason": reason,
            "ref": error["ref"],
        }
        assert re.fullmatch("[0-9a-f]{12}", error["ref"])
        assert detail not in response.text

    def test_a_door_that_raises_is_a_503_with_the_fixed_sentence(self, processes: Any) -> None:
        """The exception's words go to the host log with the traceback, never to the handset."""
        api, read, door, log = processes
        door.side_effect = RuntimeError("boom inside the door")

        response = api.get("/v1/machine/processes", headers=read)

        assert response.status_code == 503
        assert response.json()["error"] == _DOOR_FAILED
        assert "boom" not in response.text
        logged = log.error.call_args
        assert "RuntimeError: boom inside the door" in logged.args[0] % logged.args[1:]
        assert logged.kwargs["exc_info"] is True

    @pytest.mark.parametrize("answer", [None, [], "rows"])
    def test_an_answer_that_is_not_a_dict_is_a_503(self, processes: Any, answer: Any) -> None:
        """No dict means nothing to relay, and the fixed sentence says so."""
        api, read, door, _ = processes
        door.return_value = answer

        response = api.get("/v1/machine/processes", headers=read)

        assert response.status_code == 503
        assert response.json()["error"] == _DOOR_FAILED

    def test_every_read_is_a_fresh_sample(self, processes: Any) -> None:
        """Nothing is cached: the list answers what is running now, so two reads are two samples."""
        api, read, door, _ = processes
        door.side_effect = [_processes(), {**_processes(), "sampled_at": "later"}]

        first = api.get("/v1/machine/processes", headers=read).json()
        second = api.get("/v1/machine/processes", headers=read).json()

        assert door.call_count == 2
        assert (first["sampled_at"], second["sampled_at"]) == (_processes()["sampled_at"], "later")


# =============================================
# AGENT CHAT — handlers/host/agent_route.py, agent_chat.py, agent_transcript.py
# =============================================

CLAUDE_FILE = Path(".claude") / "projects" / "-srv-aipass-devpulse" / "s-1.jsonl"
CODEX_FILE = Path(".codex") / "sessions" / "2026" / "11" / "04" / "rollout-2026-11-04T10-00-00-c-1.jsonl"


def _jsonl(path: Path, rows: list) -> Path:
    """Write transcript or engine-log rows, one JSON object a line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def _claude(kind: str, content: Any, **extra: Any) -> dict:
    """One Claude Code session row."""
    message = {"role": kind, "content": content, **({"model": extra.pop("model")} if "model" in extra else {})}
    return {"type": kind, "timestamp": "2026-11-04T10:00:00Z", "message": message, **extra}


@pytest.fixture
def agents(store: Path, host_app: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The real app, a read token, HOME in tmp_path, and the baud binary answered by a FakeBaud."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(host_fleet, "snapshot_binary", lambda: "baud")
    monkeypatch.setattr(host_fleet, "repo_root", lambda: tmp_path)
    fake = FakeBaud([agent_row()])
    monkeypatch.setattr(host_fleet.subprocess, "run", fake)
    with patch(PATCH_SERVER_LOGGER):
        _, raw = host_tokens.issue_token("extension", "read")
        yield TestClient(host_app, raise_server_exceptions=False), {"Authorization": f"Bearer {raw}"}, fake


def _feed(agents: Any, path: str = "/v1/agent/AIPASS/devpulse/feed", **params: Any) -> Any:
    """GET one feed with the read token."""
    api, read, _ = agents
    return api.get(path, params=params, headers=read)


def _said(body: dict) -> list:
    """(role, text) for every feed line."""
    return [(line["role"], line["text"]) for line in body["lines"]]


@fastapi_required
class TestTheFeedReadsAClaudeSession:
    """GET /v1/agent/<p>/<n>/feed over a Claude Code session file."""

    def test_rows_become_user_agent_and_tool_lines(self, agents: Any, tmp_path: Path) -> None:
        queued = {"type": "queued_command", "commandMode": "prompt", "prompt": "and the docs"}
        _jsonl(
            tmp_path / CLAUDE_FILE,
            [
                _claude("user", "fix the bug"),
                _claude("user", "<command-name>/clear</command-name>"),
                _claude("user", [{"type": "text", "text": "<pasted_content>a long paste</pasted_content>"}]),
                _claude(
                    "assistant",
                    [
                        {"type": "text", "text": "on it"},
                        {"type": "tool_use", "name": "Edit", "input": {"file_path": "/srv/x/server.py"}},
                        {"type": "tool_use", "name": "Bash", "input": {"command": "pytest -q\nmore"}},
                    ],
                    model="claude-opus-5-5",
                ),
                {"type": "attachment", "timestamp": "t", "attachment": queued},
                _claude("assistant", [{"type": "text", "text": "side"}], isSidechain=True),
            ],
        )

        body = _feed(agents).json()

        assert _said(body) == [
            ("user", "fix the bug"),
            ("user", "a long paste"),
            ("agent", "on it"),
            ("tool", "edited server.py"),
            ("tool", "ran: pytest -q"),
            ("user", "and the docs"),
        ]
        assert body["lines"][2]["model"] == "Claude Opus 5.5"
        assert body["session"] == "s-1"

    def test_since_returns_only_the_lines_after_n(self, agents: Any, tmp_path: Path) -> None:
        _jsonl(tmp_path / CLAUDE_FILE, [_claude("user", f"line {i}") for i in range(4)])
        first = _feed(agents).json()["lines"]

        after = _feed(agents, since=first[1]["n"]).json()["lines"]

        assert [line["text"] for line in after] == ["line 2", "line 3"]
        assert [line["n"] for line in after] == [line["n"] for line in first[2:]]

    def test_n_stays_put_as_the_file_grows(self, agents: Any, tmp_path: Path) -> None:
        path = _jsonl(tmp_path / CLAUDE_FILE, [_claude("user", "one")])
        before = _feed(agents).json()["lines"]
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_claude("user", "two")) + "\n")

        after = _feed(agents, since=before[-1]["n"]).json()["lines"]

        assert [line["text"] for line in after] == ["two"]

    def test_without_since_only_the_last_80_lines_come(self, agents: Any, tmp_path: Path) -> None:
        _jsonl(tmp_path / CLAUDE_FILE, [_claude("user", f"line {i}") for i in range(100)])

        lines = _feed(agents).json()["lines"]

        assert (len(lines), lines[0]["text"], lines[-1]["text"]) == (80, "line 20", "line 99")


def _item(**payload: Any) -> dict:
    """One Codex rollout response_item row."""
    return {"type": "response_item", "timestamp": "t", "payload": payload}


@fastapi_required
class TestTheFeedPollSharesOneRosterRead:
    """The agent lookup is cached: a panel polling every 2 s does not exec @baud's roster each time."""

    def test_two_polls_inside_the_ttl_exec_the_roster_once(self, agents: Any, tmp_path: Path) -> None:
        _jsonl(tmp_path / CLAUDE_FILE, [_claude("user", "go")])

        _feed(agents)
        _feed(agents)

        assert agents[2].verbs.count("--roster") == 1


@fastapi_required
class TestTheFeedReadsACodexRollout:
    """The same route over a Codex rollout: messages, function calls and exec scripts."""

    def test_rollout_rows_become_lines_with_the_turns_model(self, agents: Any, tmp_path: Path) -> None:
        agents[2].rows[:] = [agent_row(provider="codex", session="c-1")]
        script = 'tools.exec_command({cmd:"ls -la"}); tools.write_stdin({}); tools.apply_patch("*** Begin Patch\\n*** Update File: src/app.py")'
        _jsonl(
            tmp_path / CODEX_FILE,
            [
                {"type": "turn_context", "payload": {"model": "gpt-6-sol"}},
                _item(
                    type="message", role="user", content=[{"text": "<environment_context>cwd</environment_context>"}]
                ),
                _item(type="message", role="user", content=[{"text": "run the tests"}]),
                _item(type="custom_tool_call", input=script),
                _item(type="function_call", name="Read", arguments=json.dumps({"file_path": "/a/b/notes.md"})),
                _item(type="message", role="assistant", content=[{"text": "all green"}]),
            ],
        )

        body = _feed(agents).json()

        assert _said(body) == [
            ("user", "run the tests"),
            ("tool", "ran: ls -la"),
            ("tool", "edited app.py"),
            ("tool", "read notes.md"),
            ("agent", "all green"),
        ]
        assert body["lines"][-1]["model"] == "GPT-6 Sol"


@fastapi_required
class TestTheFeedCarriesBusyAndWaiting:
    """busy and waiting come from the hooks engine log, else the transcript's age."""

    def test_a_permission_request_is_waiting_on_its_tool(self, agents: Any, tmp_path: Path, engine_log: Path) -> None:
        _jsonl(tmp_path / CLAUDE_FILE, [_claude("user", "go")])
        _jsonl(
            engine_log,
            [
                {"ts": 1.0, "event": "PreToolUse", "session_id": "s-1", "tool_name": "Bash"},
                {"ts": 2.0, "event": "PermissionRequest", "session_id": "s-1"},
            ],
        )

        body = _feed(agents).json()

        assert (body["busy"], body["waiting"]) == (True, {"tool": "Bash"})

    def test_a_stopped_turn_is_neither_busy_nor_waiting(self, agents: Any, tmp_path: Path, engine_log: Path) -> None:
        _jsonl(tmp_path / CLAUDE_FILE, [_claude("user", "go")])
        _jsonl(
            engine_log,
            [
                {"ts": 1.0, "event": "PreToolUse", "session_id": "s-1"},
                {"ts": 2.0, "event": "Stop", "session_id": "s-1"},
            ],
        )

        body = _feed(agents).json()

        assert (body["busy"], body["waiting"]) == (False, None)

    def test_with_no_hook_rows_a_fresh_transcript_is_busy_and_an_old_one_is_not(
        self, agents: Any, tmp_path: Path
    ) -> None:
        path = _jsonl(tmp_path / CLAUDE_FILE, [_claude("user", "go")])
        fresh = _feed(agents).json()["busy"]
        old = time.time() - 60
        os.utime(path, (old, old))

        assert (fresh, _feed(agents).json()["busy"]) == (True, False)


@fastapi_required
class TestTheFeedRefusesHonestly:
    """404 for an agent or transcript it cannot read, 400 for a bad name or since, 401 with no token."""

    def test_an_agent_the_roster_does_not_list_is_a_404(self, agents: Any) -> None:
        response = _feed(agents, "/v1/agent/AIPASS/nobody/feed")

        assert (response.status_code, response.json()["error"]["code"]) == (404, "agent_not_live")

    def test_an_opencode_agent_is_a_404_naming_the_two_providers_read(self, agents: Any) -> None:
        agents[2].rows[:] = [agent_row(provider="opencode")]

        response = _feed(agents)

        assert (response.status_code, response.json()["error"]["code"]) == (404, "transcript_unavailable")
        assert "only Claude and Codex" in response.json()["error"]["message"]

    def test_a_transcript_not_on_disk_is_a_404(self, agents: Any) -> None:
        response = _feed(agents)

        assert (response.status_code, response.json()["error"]["code"]) == (404, "transcript_unavailable")

    @pytest.mark.parametrize("path", ["/v1/agent/AIPASS/-rf/feed", "/v1/agent/AI.PASS/devpulse/feed"])
    def test_a_name_outside_the_fence_is_a_400_before_any_lookup(self, agents: Any, path: str) -> None:
        response = _feed(agents, path)

        assert (response.status_code, agents[2].sends) == (400, [])
        assert response.json()["error"]["code"] == "agent_refused"

    @pytest.mark.parametrize("params", [{"since": "soon"}, {"limit": "5"}])
    def test_a_bad_since_or_another_parameter_is_a_400(self, agents: Any, params: dict) -> None:
        assert _feed(agents, **params).status_code == 400

    def test_no_token_is_a_401(self, agents: Any) -> None:
        assert agents[0].get("/v1/agent/AIPASS/devpulse/feed").status_code == 401


@fastapi_required
class TestFleetRowsCarryLiveState:
    """GET /v1/fleet: each row gains state, busy, tool, model and delegating; nothing @baud sent changes."""

    def test_a_live_row_gains_its_state_and_an_asleep_row_gains_nulls(
        self, agents: Any, tmp_path: Path, engine_log: Path
    ) -> None:
        api, read, fake = agents
        asleep = agent_row(name="memory", session="s-2", interactive=False, own_room_live=False)
        fake.rows[:] = [agent_row(dispatched=True, subagents=2), asleep]
        reply = _claude("assistant", [{"type": "text", "text": "hi"}], model="claude-fable-5-1")
        _jsonl(tmp_path / CLAUDE_FILE, [reply])
        # A fresh transcript of its own: only the asleep gate keeps it from reading as working.
        _jsonl(tmp_path / ".claude" / "projects" / "-srv-aipass-memory" / "s-2.jsonl", [reply])
        _jsonl(
            engine_log,
            [
                {"ts": 1.0, "event": "PreToolUse", "session_id": "s-1", "tool_name": "Agent"},
                {"ts": 2.0, "event": "PermissionRequest", "session_id": "s-1"},
            ],
        )

        live, sleeping = api.get("/v1/fleet", headers=read).json()["branches"]

        added = ("state", "busy", "tool", "model", "delegating")
        assert [live[key] for key in added] == ["waiting", True, "Agent", "Claude Fable 5.1", True]
        assert [sleeping[key] for key in added] == [None, False, None, None, False]
        assert (live["dispatched"], live["subagents"], live["provider"]) == (True, 2, "claude")

    def test_the_live_fields_never_overwrite_a_field_baud_sent(self, agents: Any) -> None:
        api, read, fake = agents
        fake.rows[:] = [agent_row(model="as-baud-said")]

        row = api.get("/v1/fleet", headers=read).json()["branches"][0]

        assert (row["model"], row["state"]) == ("as-baud-said", None)

    def test_the_roster_rows_of_every_project_gain_the_same_live_state(
        self, agents: Any, tmp_path: Path, engine_log: Path
    ) -> None:
        api, read, fake = agents
        fake.rows[:] = [agent_row(), agent_row(name="vera", session="s-9", project="VERA")]
        _jsonl(engine_log, [{"ts": 1.0, "event": "UserPromptSubmit", "session_id": "s-9"}])

        rows = api.get("/v1/roster", headers=read).json()["branches"]

        assert [(r["project"], r["state"], r["busy"]) for r in rows] == [
            ("AIPASS", None, False),
            ("VERA", "working", True),
        ]


# =============================================
# MODELS AND USAGE — handlers/host/agent_extras_route.py, agent_models.py, agent_usage.py
# =============================================

USAGE = "/v1/agent/AIPASS/devpulse/usage"
SIGN_IN = "oat-test-sign-in-value"
CODEX_CACHE_ROWS = {
    "models": [
        {
            "slug": "gpt-6-sol",
            "display_name": "GPT-6 Sol",
            "visibility": "list",
            "supported_reasoning_levels": [{"effort": "low"}],
        },
        {"slug": "gpt-hidden", "visibility": "hide"},
    ]
}


@pytest.fixture(autouse=True)
def _no_model_or_usage_cache_between_tests() -> Any:
    """Forget the OpenCode listing and the plan-limits answer around each test: both outlive a request on purpose."""
    host_agent_models.OPENCODE_LISTING.clear()
    host_agent_usage.reset_cache()
    yield
    host_agent_models.OPENCODE_LISTING.clear()
    host_agent_usage.reset_cache()


@pytest.fixture
def catalog(client: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The real app, a read token, HOME in tmp_path; subprocess left real, so a script can stand in for opencode."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    _, raw = host_tokens.issue_token("extension", "read")
    return client, {"Authorization": f"Bearer {raw}"}, None


@pytest.mark.skipif(os.name != "posix", reason="a shell script stands in for the opencode binary")
@fastapi_required
class TestTheModelCatalog:
    """GET /v1/models: the deck's {claude, codex, opencode, switch} catalog."""

    def test_the_catalog_reads_the_codex_cache_and_a_fake_opencode(
        self, catalog: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api, read, _ = catalog
        (tmp_path / ".codex").mkdir()
        (tmp_path / ".codex" / "models_cache.json").write_text(json.dumps(CODEX_CACHE_ROWS), encoding="utf-8")
        binary = tmp_path / "bin" / "opencode"
        binary.parent.mkdir()
        binary.write_text("#!/bin/sh\necho anthropic/claude-x\necho noise\necho openai/gpt-y\n", encoding="utf-8")
        binary.chmod(0o755)
        monkeypatch.setenv("PATH", str(binary.parent))

        body = api.get("/v1/models", headers=read).json()

        assert body["claude"] == {"models": [{"name": a} for a in ("opus", "fable", "sonnet", "haiku")]}
        assert body["codex"] == {"models": [{"name": "gpt-6-sol", "label": "GPT-6 Sol", "efforts": ["low"]}]}
        assert body["opencode"] == {
            "models": [
                {"name": "anthropic/claude-x", "group": "anthropic"},
                {"name": "openai/gpt-y", "group": "openai"},
            ],
            "inline": False,
            "reason": "picker only",
        }
        assert body["switch"]["claude"] == {"codex": True, "opencode": True}
        assert body["switch"]["codex"] == {"claude": False, "opencode": True}

    def test_a_missing_opencode_and_codex_cache_are_reasons_not_errors(
        self, catalog: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api, read, _ = catalog
        monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))

        response = api.get("/v1/models", headers=read)

        assert response.status_code == 200
        assert response.json()["opencode"] == {"models": [], "inline": False, "reason": "opencode was not found"}
        assert response.json()["codex"]["models"] == [] and "no Codex model cache" in response.json()["codex"]["reason"]

    def test_the_opencode_listing_is_cached_for_a_minute(
        self, catalog: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api, read, _ = catalog
        count = tmp_path / "runs"
        binary = tmp_path / "bin" / "opencode"
        binary.parent.mkdir()
        binary.write_text(f"#!/bin/sh\necho run >> {count}\necho a/b\n", encoding="utf-8")
        binary.chmod(0o755)
        monkeypatch.setenv("PATH", str(binary.parent))

        api.get("/v1/models", headers=read)
        api.get("/v1/models", headers=read)

        assert count.read_text(encoding="utf-8").count("run") == 1


class _Usage:
    """urllib.request.urlopen at the network edge: answers *body*, or raises *error*; every request recorded."""

    def __init__(self, body: Any = None, error: Any = None) -> None:
        self.body, self.error, self.requests = body, error, []

    def __call__(self, request: Any, timeout: float = 0) -> Any:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        answer = MagicMock()
        answer.__enter__.return_value.read.return_value = json.dumps(self.body).encode("utf-8")
        return answer


def _too_many(retry_after: Any = None) -> Any:
    """A 429 as urllib raises it, Retry-After set when given."""
    from email.message import Message
    from urllib.error import HTTPError

    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return HTTPError(host_agent_usage.USAGE_URL, 429, "Too Many Requests", headers, None)


@pytest.fixture
def usage(agents: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The agents fixture with a Claude sign-in in tmp_path's home, a fake usage endpoint and a hand-wound clock."""
    credentials = tmp_path / ".claude" / ".credentials.json"
    credentials.parent.mkdir(parents=True, exist_ok=True)
    expires = (time.time() + 3600) * 1000
    credentials.write_text(json.dumps({"claudeAiOauth": {"accessToken": SIGN_IN, "expiresAt": expires}}), "utf-8")
    limits = [{"kind": "five_hour", "percent": 80, "resets_at": "2026-11-05T15:00:00Z"}, {"kind": "weekly_all"}]
    endpoint = _Usage({"limits": limits})
    monkeypatch.setattr(host_agent_usage.urllib.request, "urlopen", endpoint)
    clock = [1000.0]
    monkeypatch.setattr(host_agent_usage, "time", MagicMock(time=time.time, monotonic=lambda: clock[0]))
    return agents, endpoint, clock, credentials


def _usage(usage: Any, path: str = USAGE) -> Any:
    """GET one usage read with the read token."""
    (api, read, _), *_ = usage
    return api.get(path, headers=read)


@fastapi_required
class TestTheUsageRing:
    """GET /v1/agent/<p>/<n>/usage: context from the transcript, plan limits from the usage endpoint."""

    def test_context_comes_from_the_last_reply_and_limits_from_the_endpoint(self, usage: Any, tmp_path: Path) -> None:
        reply = _claude("assistant", "hi", model="claude-opus-5-5")
        reply["message"]["usage"] = {
            "input_tokens": 1000,
            "cache_creation_input_tokens": 2000,
            "cache_read_input_tokens": 32000,
        }
        _jsonl(tmp_path / CLAUDE_FILE, [reply, _claude("user", "next")])

        body = _usage(usage).json()

        assert body["provider"] == "claude"
        assert body["context"] == {"used": 35000, "total": host_agent_usage.CLAUDE_WINDOW, "percent": 10.0}
        assert body["limits"] == [
            {"label": "5 hour", "percent": 80.0, "severity": "warning", "resets_at": "2026-11-05T15:00:00Z"},
            {"label": "All models", "percent": 0.0, "severity": "normal", "resets_at": None},
        ]
        [request] = usage[1].requests
        assert request.get_header("Authorization") == f"Bearer {SIGN_IN}"
        assert request.get_header("Anthropic-beta") == "oauth-2025-04-20"

    def test_the_sign_in_never_reaches_the_answer_or_any_log(self, usage: Any) -> None:
        usage[1].error = _too_many()
        with patch.object(host_agent_usage, "logger") as log, patch.object(host_agent_usage, "json_handler") as ops:
            first = _usage(usage)
            usage[1].error = None
            usage[2][0] += 10_000
            second = _usage(usage)

        assert SIGN_IN not in first.text + second.text
        assert SIGN_IN not in str(log.mock_calls) + str(ops.mock_calls)

    @pytest.mark.parametrize(
        ("signed_in", "note"),
        [(None, "not signed in"), ({"accessToken": SIGN_IN, "expiresAt": 1000}, "has expired")],
    )
    def test_no_or_an_expired_sign_in_is_a_note_and_no_call(self, usage: Any, signed_in: Any, note: str) -> None:
        if signed_in is None:
            usage[3].unlink()
        else:
            usage[3].write_text(json.dumps({"claudeAiOauth": signed_in}), encoding="utf-8")

        response = _usage(usage)

        assert (response.status_code, response.json()["limits"], usage[1].requests) == (200, [], [])
        assert note in response.json()["note"]

    def test_the_limits_are_read_once_a_minute(self, usage: Any) -> None:
        _usage(usage)
        usage[2][0] += 59
        _usage(usage)
        assert len(usage[1].requests) == 1

        usage[2][0] += 2
        _usage(usage)

        assert len(usage[1].requests) == 2

    def test_a_429_holds_for_its_retry_after_and_shows_the_last_good_limits(self, usage: Any) -> None:
        good = _usage(usage).json()["limits"]
        usage[2][0] += 61
        usage[1].error = _too_many(retry_after=120)

        held = _usage(usage).json()
        usage[2][0] += 119
        _usage(usage)
        calls_inside_the_hold = len(usage[1].requests)
        usage[2][0] += 2
        _usage(usage)

        assert (held["limits"], "rate limited" in held["note"]) == (good, True)
        assert (calls_inside_the_hold, len(usage[1].requests)) == (2, 3)

    def test_a_429_without_retry_after_holds_five_minutes_then_doubles(self, usage: Any) -> None:
        usage[1].error = _too_many()
        _usage(usage)
        usage[2][0] += 299
        _usage(usage)
        assert len(usage[1].requests) == 1

        usage[2][0] += 2
        _usage(usage)
        usage[2][0] += 599
        _usage(usage)

        assert len(usage[1].requests) == 2

    def test_a_codex_agent_reads_its_newest_token_count_rows(self, usage: Any, tmp_path: Path) -> None:
        usage[0][2].rows[:] = [agent_row(provider="codex", session="c-1")]
        info = {"last_token_usage": {"total_tokens": 50000}, "model_context_window": 200000}
        rates = {"primary": {"window_minutes": 300, "used_percent": 95, "resets_at": 0}}
        counted = {"type": "event_msg", "payload": {"type": "token_count", "info": info, "rate_limits": rates}}
        _jsonl(tmp_path / CODEX_FILE, [counted])

        body = _usage(usage).json()

        assert body["context"] == {"used": 50000, "total": 200000, "percent": 25.0}
        assert body["limits"] == [
            {"label": "5 hour", "percent": 95.0, "severity": "critical", "resets_at": "1970-01-01T00:00:00+00:00"}
        ]
        assert usage[1].requests == []

    def test_an_opencode_agent_says_it_is_not_wired(self, usage: Any) -> None:
        usage[0][2].rows[:] = [agent_row(provider="opencode")]

        assert _usage(usage).json()["note"] == "OpenCode usage is not wired yet"

    def test_an_agent_that_is_not_live_is_a_404(self, usage: Any) -> None:
        response = _usage(usage, "/v1/agent/AIPASS/nobody/usage")

        assert (response.status_code, response.json()["error"]["code"]) == (404, "agent_not_live")
