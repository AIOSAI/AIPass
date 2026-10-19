# =================== AIPass ====================
# Name: test_host_perf.py
# Description: Tests for the host API's cost doctrine — threadpool, cache, pin
# Version: 1.0.4
# Created: 2026-08-18
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/host/server.py's cost doctrine: threadpool routes, the fleet cache, the pump cap."""

# NOTHING HERE INVOKES THE REAL BINARY (the standing rule in test_host_fleet.py): every exec is a counted fake.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that server.py parses and imports
# seedgo: no-test-needed(covered_elsewhere) — what each route returns, tests/test_host_fleet.py
# seedgo: no-test-needed(external) — the real baud binary; every subprocess.run here is a counted fake

import contextlib
import json
import signal
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from aipass.api.apps.handlers.host import attach as host_attach
from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host import fleet as host_fleet
from aipass.api.apps.handlers.host import pump as host_pump
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import tokens as host_tokens


PATCH_SECRETS_BASE = "aipass.api.apps.handlers.auth.secrets.SECRETS_BASE"
PATCH_SECRETS_JSON = "aipass.api.apps.handlers.auth.secrets.json_handler"
PATCH_SECRETS_LOGGER = "aipass.api.apps.handlers.auth.secrets.logger"
PATCH_TOKENS_JSON = "aipass.api.apps.handlers.host.tokens.json_handler"
PATCH_TOKENS_LOGGER = "aipass.api.apps.handlers.host.tokens.logger"
PATCH_SERVER_LOGGER = "aipass.api.apps.handlers.host.server.logger"
PATCH_FLEET_LOGGER = "aipass.api.apps.handlers.host.fleet.logger"
PATCH_FLEET_JSON = "aipass.api.apps.handlers.host.fleet.json_handler"
PATCH_CONFIG_LOGGER = "aipass.api.apps.handlers.host.config.logger"

SERVER_SOURCE = Path(host_server.__file__)

# GETs that may stay on the loop: both return values the server already holds (no file, exec or registry).
LOOP_SAFE_GETS = {"/v1/ping", "/v1/whoami"}

# POSTs off the loop, each with nothing the loop must serialize: upload writes a fresh uniquely named file;
# pair writes under the token store's file lock and a threading lock; backup/run's job table holds its own lock;
# backup/cancel and verbs/new-project write nothing of this server's and wait seconds that must not hold the loop.
LOOP_FREE_POSTS = {"/v1/files/upload", "/v1/pair", "/v1/backup/run", "/v1/backup/cancel", "/v1/verbs/new-project"}

fastapi_required = pytest.mark.skipif(
    not host_server.is_available(),
    reason="the [host] extra is not installed",
)


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    """Build a fake CompletedProcess."""
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


ENVELOPE = {
    "project": "AIPASS",
    "root": "/srv/aipass",
    "generated_at": "2026-08-18T09:00:00Z",
    "error": None,
    "live_agent_sessions": [],
    "branches": [
        {"name": "api", "project": "AIPASS", "has_room": True, "path": "/srv/aipass/api"},
        {"name": "baud", "project": "AIPASS", "has_room": False, "path": "/srv/aipass/baud"},
    ],
}


@pytest.fixture
def seated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Pin the gate open and the exec's location, the way test_host_fleet does."""
    monkeypatch.setattr(host_fleet, "SNAPSHOT_READY", True)
    monkeypatch.setattr(host_fleet, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(host_fleet, "snapshot_binary", lambda: "baud")


@pytest.fixture
def counted_exec(monkeypatch: pytest.MonkeyPatch, seated: None) -> list:
    """Replace the snapshot exec with a counted fake. Returns the call log."""
    calls: list = []

    def _run(command, **kwargs):
        calls.append(list(command))
        return _completed(0, json.dumps(ENVELOPE))

    monkeypatch.setattr(host_fleet.subprocess, "run", _run)
    monkeypatch.setattr(host_fleet, "logger", MagicMock())
    monkeypatch.setattr(host_fleet, "json_handler", MagicMock())
    return calls


@fastapi_required
class TestReadRoutesRunOffTheEventLoop:
    """The rule: a route whose body blocks must not be declared async."""

    # Derived from the app's own routing table: a written-down list of routes drifts silently.

    def _v1_routes(self) -> list:
        """Every /v1 route the app registers, with its endpoint and methods."""
        app = host_server.create_app()
        rows = []
        for route in app.routes:
            path = getattr(route, "path", "")
            endpoint = getattr(route, "endpoint", None)
            if not path.startswith("/v1") or endpoint is None:
                continue
            rows.append((path, sorted(getattr(route, "methods", set()) or set()), endpoint))
        return rows

    def test_every_read_route_is_declared_sync(self) -> None:
        """The whole point: a GET that does work runs in the threadpool."""
        import inspect

        with patch(PATCH_SERVER_LOGGER):
            offenders = [
                path
                for path, methods, endpoint in self._v1_routes()
                if "GET" in methods and path not in LOOP_SAFE_GETS and inspect.iscoroutinefunction(endpoint)
            ]

        assert offenders == [], f"these read routes still run ON the event loop: {offenders}"

    def test_the_rule_covers_more_than_a_handful(self) -> None:
        """Vacuity floor: an app that registered nothing would pass the above."""
        with patch(PATCH_SERVER_LOGGER):
            reads = [path for path, methods, _ in self._v1_routes() if "GET" in methods]

        assert len(reads) >= 15

    def test_the_two_loop_safe_gets_are_still_async(self) -> None:
        """They hold no blocking work, so moving them would buy a thread hop."""
        import inspect

        with patch(PATCH_SERVER_LOGGER):
            rows = {path: endpoint for path, _methods, endpoint in self._v1_routes()}

        # The floor first: an empty LOOP_SAFE_GETS would never enter the loop and pass measuring nothing.
        assert LOOP_SAFE_GETS, "the loop-safe exemption list is empty — nothing was checked"

        for path in LOOP_SAFE_GETS:
            assert inspect.iscoroutinefunction(rows[path]), f"{path} is in LOOP_SAFE_GETS but no longer async"

    def test_the_loop_safe_gets_reach_no_handler_module(self) -> None:
        """Their claim, checked: ping and whoami call into nothing that blocks."""
        import ast

        tree = ast.parse(SERVER_SOURCE.read_text(encoding="utf-8"))
        bodies = {
            node.name: ast.dump(node)
            for node in ast.walk(tree)
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name in {"ping", "whoami"}
        }

        assert set(bodies) == {"ping", "whoami"}
        for name, dumped in bodies.items():
            assert "host_" not in dumped, f"{name} now calls a handler module — it can no longer stay on the loop"

    def test_write_routes_are_async_on_purpose(self) -> None:
        """A decision pin, not an accident."""
        # Settings and memory config read-modify-write with no lock; the event loop is their only serialization.
        import inspect

        with patch(PATCH_SERVER_LOGGER):
            loose = [
                path
                for path, methods, endpoint in self._v1_routes()
                if "POST" in methods and path not in LOOP_FREE_POSTS and not inspect.iscoroutinefunction(endpoint)
            ]

        assert loose == [], f"these write routes left the loop without a lock landing: {loose}"

    def test_the_upload_route_is_the_named_exception(self) -> None:
        """It writes a file of its own, so it has no shared document to lose."""
        import inspect

        with patch(PATCH_SERVER_LOGGER):
            rows = {path: endpoint for path, _methods, endpoint in self._v1_routes()}

        upload = rows["/v1/files/upload"]
        if upload.__name__ == "files_upload_unavailable":
            pytest.skip("python-multipart is absent — the registered route is the refusal stand-in")

        assert not inspect.iscoroutinefunction(upload)


@fastapi_required
class TestASlowReadDoesNotFreezeTheServer:
    """The behavioural half, counted by events rather than timed by a clock."""

    @contextlib.contextmanager
    def _client(self, tmp_path: Path):
        """A TestClient in a CONTEXT — one shared event loop across requests."""
        # Outside a `with`, each request gets a fresh loop and a blocked one is never observed.
        # The store stays patched for the REQUESTS too: auth re-reads it per call.
        from fastapi.testclient import TestClient

        store = tmp_path / "secrets"
        store.mkdir()
        with patch(PATCH_SECRETS_BASE, store), patch(PATCH_SECRETS_JSON), patch(PATCH_SECRETS_LOGGER):
            with patch(PATCH_TOKENS_JSON), patch(PATCH_TOKENS_LOGGER), patch(PATCH_SERVER_LOGGER):
                _, raw = host_tokens.issue_token("phone", "read")
                yield TestClient(host_server.create_app(), raise_server_exceptions=False), raw

    def test_ping_answers_while_a_read_is_blocked_mid_handler(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The property the owner feels: one slow card does not freeze the phone."""
        entered = threading.Event()
        release = threading.Event()

        def _blocking_snapshot(project: str = ""):
            entered.set()
            release.wait(timeout=10)
            return dict(ENVELOPE)

        monkeypatch.setattr(host_fleet, "read_snapshot", _blocking_snapshot)

        with self._client(tmp_path) as (client, raw):
            headers = {"Authorization": f"Bearer {raw}"}
            answers: list = []

            answered = threading.Event()

            def _ask_ping() -> None:
                answers.append(client.get("/v1/ping"))
                answered.set()

            asker = threading.Thread(target=_ask_ping)

            with client:
                slow = threading.Thread(target=lambda: answers.append(client.get("/v1/fleet", headers=headers)))
                slow.start()
                try:
                    assert entered.wait(timeout=10), "the slow read never reached its handler"

                    # Its OWN thread, bounded: inline, a blocked loop just answers 204 late and passes.
                    asker.start()

                    assert answered.wait(timeout=5.0), (
                        "/v1/ping could not be answered while a read was blocked mid-handler — "
                        "the read is holding the event loop"
                    )
                finally:
                    release.set()
                    slow.join(timeout=10)
                    asker.join(timeout=10)

            assert [answer.status_code for answer in answers] == [204, 200]

    def test_the_probe_can_see_a_loop_that_really_is_blocked(self, tmp_path: Path) -> None:
        """Vacuity floor: the same measurement against a deliberately async block."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        entered = threading.Event()
        release = threading.Event()
        app = FastAPI()

        @app.get("/slow")
        async def slow_on_the_loop() -> dict:
            entered.set()
            release.wait(timeout=10)
            return {"done": True}

        @app.get("/fast")
        async def fast() -> dict:
            return {"ok": True}

        client = TestClient(app)
        answered_at_ready = threading.Event()

        def _ask() -> None:
            client.get("/fast")
            answered_at_ready.set()

        asker = threading.Thread(target=_ask)

        with client:
            worker = threading.Thread(target=lambda: client.get("/slow"))
            worker.start()
            try:
                assert entered.wait(timeout=10)

                asker.start()

                assert not answered_at_ready.wait(timeout=1.0), (
                    "an async blocking route did NOT freeze the loop — this probe cannot detect blocking, "
                    "so the test above proves nothing"
                )
            finally:
                release.set()
                worker.join(timeout=10)
                asker.join(timeout=10)


@fastapi_required
class TestTheSnapshotIsCoalesced:
    """One exec per question per TTL, and one exec per stampede."""

    def test_a_second_read_inside_the_ttl_does_not_exec(self, counted_exec: list) -> None:
        """The TTL half."""
        host_fleet.read_snapshot()
        host_fleet.read_snapshot()

        assert len(counted_exec) == 1

    def test_the_cached_answer_is_the_real_one(self, counted_exec: list) -> None:
        """A cache that returns something else is worse than no cache."""
        first = host_fleet.read_snapshot()
        second = host_fleet.read_snapshot()

        assert first == second == ENVELOPE

    def test_a_read_after_the_ttl_execs_again(
        self,
        counted_exec: list,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The TTL expires — against a clock this test drives, not one it hopes for."""
        # Windows' monotonic ticks in ~15.6ms steps, so a sleep can land on the same tick.
        # fleet's OWN `time` name: a global time.monotonic patch would freeze pytest-timeout's clock too.
        clock = [1000.0]
        monkeypatch.setattr(host_fleet, "time", SimpleNamespace(monotonic=lambda: clock[0]))

        host_fleet.read_snapshot()
        clock[0] += host_fleet.SNAPSHOT_TTL_SECONDS + 0.001
        host_fleet.read_snapshot()

        assert len(counted_exec) == 2

    def test_a_read_just_inside_the_ttl_still_does_not_exec(
        self,
        counted_exec: list,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The other side of the same boundary, on the same driven clock."""
        clock = [1000.0]
        monkeypatch.setattr(host_fleet, "time", SimpleNamespace(monotonic=lambda: clock[0]))

        host_fleet.read_snapshot()
        clock[0] += host_fleet.SNAPSHOT_TTL_SECONDS - 0.001
        host_fleet.read_snapshot()

        assert len(counted_exec) == 1

    def test_rooms_and_fleet_share_one_exec(self, counted_exec: list) -> None:
        """The exact double-spawn a screen refresh used to pay."""
        host_fleet.read_snapshot()
        host_fleet.read_rooms()

        assert len(counted_exec) == 1

    def test_a_stampede_of_readers_shares_one_exec(
        self,
        monkeypatch: pytest.MonkeyPatch,
        seated: None,
    ) -> None:
        """Single flight: eight callers arriving together spawn ONE process."""
        calls: list = []
        started = threading.Barrier(8, timeout=15)

        def _run(command, **kwargs):
            calls.append(list(command))
            time.sleep(0.2)
            return _completed(0, json.dumps(ENVELOPE))

        monkeypatch.setattr(host_fleet.subprocess, "run", _run)

        answers: list = []

        def _ask() -> None:
            started.wait()
            answers.append(host_fleet.read_snapshot())

        threads = [threading.Thread(target=_ask) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)

        assert len(answers) == 8, "not every caller got an answer"
        assert all(answer == ENVELOPE for answer in answers)
        assert len(calls) == 1, f"the stampede spawned {len(calls)} processes"

    def test_a_different_project_is_a_different_question(self, counted_exec: list) -> None:
        """Two projects must not answer each other."""
        host_fleet.read_snapshot()
        host_fleet.read_snapshot("BAUD")

        assert len(counted_exec) == 2
        assert counted_exec[1][-2:] == ["--project", "BAUD"]

    def test_a_failure_is_not_remembered(
        self,
        monkeypatch: pytest.MonkeyPatch,
        seated: None,
    ) -> None:
        """A binary that comes back works on the NEXT request, not in 1.5s."""
        outcomes = [_completed(2, "", "nope"), _completed(0, json.dumps(ENVELOPE))]
        monkeypatch.setattr(host_fleet.subprocess, "run", lambda *a, **k: outcomes.pop(0))

        with pytest.raises(host_fleet.FleetUnavailable):
            host_fleet.read_snapshot()

        assert host_fleet.read_snapshot() == ENVELOPE

    def test_editing_the_first_answer_does_not_poison_the_cache(self, counted_exec: list) -> None:
        """The caller who MISSED gets their own object, so the store is safe."""
        first = host_fleet.read_snapshot()
        first["branches"][0]["name"] = "TAMPERED"
        first["injected"] = True

        second = host_fleet.read_snapshot()

        assert second == ENVELOPE
        assert "injected" not in second

    def test_editing_a_cached_answer_does_not_poison_the_cache_either(self, counted_exec: list) -> None:
        """And so does the caller who HIT — the other half of the same defence."""
        host_fleet.read_snapshot()
        second = host_fleet.read_snapshot()
        second["branches"][0]["name"] = "TAMPERED"
        second["injected"] = True

        third = host_fleet.read_snapshot()

        assert third == ENVELOPE
        assert "injected" not in third

    def test_ending_a_room_forgets_the_snapshot(
        self,
        monkeypatch: pytest.MonkeyPatch,
        seated: None,
    ) -> None:
        """The fleet CHANGED — serving the pre-kill card would show a ghost."""
        calls: list = []

        def _run(command, **kwargs):
            calls.append(list(command))
            return _completed(0, json.dumps(ENVELOPE))

        monkeypatch.setattr(host_fleet.subprocess, "run", _run)

        host_fleet.read_snapshot()
        host_fleet.end_room("api", "AIPASS")
        host_fleet.read_snapshot()

        snapshots = [call for call in calls if "--snapshot" in call]
        assert len(snapshots) == 2, "the snapshot survived a room kill"

    def test_the_cache_can_be_cleared_by_name(self, counted_exec: list) -> None:
        """A cache nobody can clear is a cache that outlives its own truth."""
        host_fleet.read_snapshot()
        host_fleet.reset_snapshot_cache()
        host_fleet.read_snapshot()

        assert len(counted_exec) == 2


class TestTheRegistryIsPinnedAtBoot:
    """drone re-resolves the registry per lookup; a long-lived server pays it."""

    def test_pinning_hands_drone_the_path_it_found(self, tmp_path: Path) -> None:
        """The pin is drone's own public door, not an env var we hope is read."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")

        # On the module, NOT in sys.modules: `import aipass.drone as drone` binds through the parent package.
        with patch("aipass.drone.get_registry_path", return_value=str(registry)):
            with patch("aipass.drone.set_registry_path") as pin, patch(PATCH_CONFIG_LOGGER):
                pinned = host_config.pin_registry()

        assert pinned == registry
        pin.assert_called_once_with(registry)

    def test_a_registry_that_is_not_there_pins_nothing(self, tmp_path: Path) -> None:
        """Never pin a path that does not exist — that freezes a broken answer."""
        with patch("aipass.drone.get_registry_path", return_value=str(tmp_path / "gone.json")):
            with patch("aipass.drone.set_registry_path") as pin, patch(PATCH_CONFIG_LOGGER):
                pinned = host_config.pin_registry()

        assert pinned is None
        pin.assert_not_called()

    @fastapi_required
    def test_building_an_app_never_pins(self) -> None:
        """The isolation rule: create_app is called constantly by this suite."""
        with patch("aipass.drone.set_registry_path") as pin, patch(PATCH_SERVER_LOGGER):
            host_server.create_app()

        pin.assert_not_called()

    @fastapi_required
    def test_serving_pins_before_the_first_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """And serve() does — before uvicorn is handed anything."""
        order: list = []

        monkeypatch.setattr(host_server.host_config, "load_config", lambda: {"host": "127.0.0.1", "port": 8787})
        monkeypatch.setattr(host_server.host_config, "pin_registry", lambda: order.append("pinned"))
        monkeypatch.setattr(host_server, "create_app", lambda: order.append("app") or MagicMock())

        uvicorn = MagicMock()
        uvicorn.run = lambda *args, **kwargs: order.append("served")

        with patch.dict("sys.modules", {"uvicorn": uvicorn}), patch(PATCH_SERVER_LOGGER):
            host_server.serve()

        assert order == ["pinned", "app", "served"]

    @fastapi_required
    def test_serving_runs_uvicorn_with_its_access_log_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """One access line per phone request grew the unit's log to 12.8 MB unrotated (10-01)."""
        calls: list = []

        monkeypatch.setattr(host_server.host_config, "load_config", lambda: {"host": "127.0.0.1", "port": 8787})
        monkeypatch.setattr(host_server.host_config, "pin_registry", lambda: calls.append("pinned"))
        monkeypatch.setattr(host_server, "create_app", MagicMock)

        uvicorn = MagicMock()
        uvicorn.run = lambda *args, **kwargs: calls.append(kwargs)

        with patch.dict("sys.modules", {"uvicorn": uvicorn}), patch(PATCH_SERVER_LOGGER):
            host_server.serve()

        assert calls == ["pinned", {"host": "127.0.0.1", "port": 8787, "access_log": False}]


# An honest skip: the attach lane is POSIX-only (open_attach refuses on PTY_AVAILABLE first).
sighup_required = pytest.mark.skipif(
    not hasattr(signal, "SIGHUP"),
    reason="hangup detaches with SIGHUP, which this platform does not have",
)


@pytest.fixture
def full_pump(monkeypatch: pytest.MonkeyPatch) -> list:
    """A cap of one, already taken, on a host open_attach would otherwise serve."""
    slots = threading.BoundedSemaphore(1)
    slots.acquire()
    spawned: list = []
    monkeypatch.setattr(host_attach, "_PUMP_SLOTS", slots)
    monkeypatch.setattr(host_attach, "PTY_AVAILABLE", True)
    monkeypatch.setattr(host_attach, "TMUX_BINARY", sys.executable)
    monkeypatch.setattr(host_attach, "pty", SimpleNamespace(openpty=lambda: spawned.append("pty") or (-7, -8)))
    monkeypatch.setattr(host_attach, "set_winsize", lambda *a: spawned.append("winsize"))
    monkeypatch.setattr(host_attach.subprocess, "Popen", lambda *a, **k: spawned.append("popen") or MagicMock(pid=1))
    return spawned


class TestThePumpPoolIsBoundedOutLoud:
    """The pump pool is capped, and a session past the cap is refused in words, never hung silent."""

    # Each socket parks a thread in os.read for life; asyncio's default pool filled and the next socket hung blank.

    def test_the_pool_is_the_lanes_own_and_named(self) -> None:
        """Not asyncio's default: these threads never come back."""
        pool = host_attach.pump_executor()

        assert pool is host_attach.pump_executor(), "a new pool per call would uncap the whole thing"
        assert pool._max_workers == host_attach.PUMP_WORKERS
        assert pool._thread_name_prefix == "host-attach"

    def test_the_pump_hands_its_read_to_that_pool(self) -> None:
        """The pool exists to be used — the read must actually reach it."""
        pump = Path(host_pump.__file__).read_text(encoding="utf-8")

        assert "run_in_executor(host_attach.pump_executor(), session.read)" in pump

    def test_a_session_beyond_the_cap_is_refused_in_words(self, full_pump: list) -> None:
        """The whole point: a cap that speaks instead of a terminal that hangs."""
        with pytest.raises(host_attach.AttachUnavailable) as refusal:
            host_attach.open_attach("", room="baud-api")

        assert "cap" in str(refusal.value)
        assert "baud-api" in str(refusal.value)

    def test_the_refusal_does_not_wait_for_a_slot(self, full_pump: list) -> None:
        """Waiting IS the silent hang, wearing a different hat."""
        refused = threading.Event()

        def _try() -> None:
            with contextlib.suppress(host_attach.AttachUnavailable):
                host_attach.open_attach("", room="baud-api")
            refused.set()

        waiter = threading.Thread(target=_try)
        waiter.start()
        try:
            assert refused.wait(timeout=2.0), "the reservation is waiting for a slot instead of refusing"
        finally:
            waiter.join(timeout=5)

    def test_the_cap_is_reserved_before_anything_is_spawned(self, full_pump: list) -> None:
        """Refused, not opened. A PTY spawned only to be refused is waste."""
        # Reserving after the spawn would let two concurrent sockets both pass a cap with room for one.
        with pytest.raises(host_attach.AttachUnavailable):
            host_attach.open_attach("", room="baud-api")

        assert full_pump == [], "a PTY was opened for a session that was then refused"

    @sighup_required
    def test_a_hangup_gives_the_thread_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Otherwise the server refuses terminals while pumping none."""
        # Hung up TWICE: a socket that errors then closes does that, and a second release would over-credit.
        slots = threading.BoundedSemaphore(1)
        monkeypatch.setattr(host_attach, "_PUMP_SLOTS", slots)
        slots.acquire()

        session = host_attach.AttachSession(MagicMock(), -1, "api", "baud-api")
        with patch.object(host_attach, "json_handler", MagicMock()), patch.object(host_attach, "logger", MagicMock()):
            session.hangup()
            session.hangup()

        # The CONTRAST is the oracle: one reservation fits and the next does not, catching zero and double releases.
        assert slots.acquire(blocking=False) is True
        assert slots.acquire(blocking=False) is False

    def test_a_failed_spawn_gives_the_thread_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No session will be built to own that reservation."""
        sized: list = []
        closed: list = []
        slots = threading.BoundedSemaphore(1)
        monkeypatch.setattr(host_attach, "_PUMP_SLOTS", slots)
        monkeypatch.setattr(host_attach, "pty", SimpleNamespace(openpty=lambda: (-7, -8)))
        monkeypatch.setattr(host_attach, "set_winsize", lambda *a: sized.append(a))
        monkeypatch.setattr(host_attach.subprocess, "Popen", MagicMock(side_effect=OSError("no")))

        with patch.object(host_attach, "logger", MagicMock()):
            with pytest.raises(host_attach.AttachUnavailable):
                host_attach._spawn_pty(["true"], None, "baud-api", close_fd=closed.append)

        # A list in close order, not a set: a set hides a second close of the same end.
        assert sized == [(-7, host_attach.DEFAULT_COLS, host_attach.DEFAULT_ROWS)]
        assert closed == [-7, -8]
        assert slots.acquire(blocking=False) is True

    def test_an_over_release_is_loud_not_silent_capacity(self) -> None:
        """A slot handed back twice is an accounting bug, and says so."""
        # The MODULE's own semaphore: a stand-in is bounded whatever the module chose, so a downgrade would pass.
        host_attach._reserve_session("baud-api")
        host_attach._release_session()

        with pytest.raises(ValueError):
            host_attach._release_session()
