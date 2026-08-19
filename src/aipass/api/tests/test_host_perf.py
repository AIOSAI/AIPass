#!/usr/bin/env python3
# =================== AIPass ====================
# Name: test_host_perf.py
# Description: Tests for the host API's cost doctrine — threadpool, cache, pin
# Version: 1.0.0
# Created: 2026-08-18
# Modified: 2026-08-18
# =============================================

"""Tests for the host API's cost doctrine (DPLAN-0305 Audit 2).

Patrick, 2026-08-18: the phone lags. @devpulse audited and found three causes in
this branch, none of them exotic — the server was doing blocking work in the one
place that must never block, re-walking the filesystem for a registry it already
knew, and paying for the same 90ms process spawn twice per screen refresh.

THREE PROPERTIES ARE PINNED HERE, AND EACH IS PINNED SO IT CAN GO RED:

1. A read route runs OFF the event loop. A handler declared `async def` runs ON
   the loop, so a 90ms exec inside it means the whole server answers nothing for
   90ms — including /v1/ping. Declared `def`, FastAPI runs it in the anyio
   threadpool. The structural test is DERIVED from the app's routing table, not
   from a list written down here, so a new read route added as async goes red
   without anyone remembering this file exists.

2. The blocking probe below can actually SEE a blocked loop. A test that starts
   a slow request and then checks a fast one answers is worthless if the harness
   gives each request its own event loop — it would pass against a fully async
   server too. So the probe carries a vacuity floor: the same measurement is run
   against a deliberately-async blocking route and MUST fail there.

3. The snapshot exec is coalesced. Within the TTL the answer is remembered, and
   concurrent callers asking the same question share ONE exec rather than each
   spawning their own. Both halves are counted, never timed.

4. The socket pump's threads are its OWN and its cap is a sentence. Eight was
   never a decision — it is what asyncio's default executor happens to be on a
   4-CPU host, and the ninth terminal connected, authenticated, and then never
   pumped a byte. A cap the operator cannot see is the worst kind.

5. The audit trail's caller detection fetches ONE frame. It used to build a
   FrameInfo for the whole stack, which is cheap in a script and 1.77ms deep
   inside a request. The fast path and the old walk must give the same answer —
   a faster audit trail that names the wrong module is not a win.

NOTHING HERE INVOKES THE REAL BINARY (the standing rule in test_host_fleet.py) —
every exec is a counted fake.
"""

import contextlib
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import attach as host_attach
from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host import fleet as host_fleet
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

# The two GET routes that may stay on the loop, and why. Both return values the
# server already holds — no file, no exec, no registry — so there is nothing to
# move off the loop. Every OTHER read route must be sync.
LOOP_SAFE_GETS = {"/v1/ping", "/v1/whoami"}

# The one POST that is NOT held on the loop, and why it is the exception rather
# than the start of a trend: it blocks for the whole of an image body, and it
# has nothing to serialize — every upload writes a NEW file under a name it
# makes itself (a timestamp plus token_hex), so two concurrent uploads cannot
# be racing over one document the way every other write route can.
LOOP_FREE_POSTS = {"/v1/files/upload"}

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
    "root": "/home/patrick/Projects/AIPass",
    "generated_at": "2026-08-18T09:00:00Z",
    "error": None,
    "live_agent_sessions": [],
    "branches": [
        {"name": "api", "project": "AIPASS", "has_room": True, "path": "/tmp/api"},
        {"name": "baud", "project": "AIPASS", "has_room": False, "path": "/tmp/baud"},
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


# ==============================================
# 1. THE THREADPOOL DOCTRINE, DERIVED FROM THE APP
# ==============================================


@fastapi_required
class TestReadRoutesRunOffTheEventLoop:
    """
    The rule: a route whose body blocks must not be declared async.

    Measured before the change (DPLAN-0305 Audit 2): 34 of this server's route
    handlers were `async def` and 34 of them never awaited anything. Every one
    of them held the single uvicorn worker's event loop for the whole of its
    blocking work — a `baud --snapshot` at 60-90ms, a registry walk, a git
    exec — while /v1/ping and every other request queued behind it.

    Derived from the app's own routing table on purpose. A written-down list
    of routes drifts silently; this branch has already been bitten by exactly
    that (the create_app roll-call named 18 doors out of nearly forty).
    """

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

        for path in LOOP_SAFE_GETS:
            assert inspect.iscoroutinefunction(rows[path]), f"{path} is in LOOP_SAFE_GETS but no longer async"

    def test_the_loop_safe_gets_reach_no_handler_module(self) -> None:
        """Their claim, checked: ping and whoami call into nothing that blocks.

        This is what makes LOOP_SAFE_GETS a fact rather than an exemption. If
        someone gives whoami a registry lookup, its body starts naming a
        handler module and this goes red — the exemption has to be re-earned.
        """
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
        """A decision pin, not an accident.

        The POST routes stay on the loop DELIBERATELY: settings and memory
        config do read-modify-write with no in-process lock, so the single
        event loop is currently their only serialization. Moving them into the
        threadpool without a lock would turn a slow write into a lost one.
        Flip this only together with that lock (todo: AXIS 2).
        """
        import inspect

        with patch(PATCH_SERVER_LOGGER):
            loose = [
                path
                for path, methods, endpoint in self._v1_routes()
                if "POST" in methods and path not in LOOP_FREE_POSTS and not inspect.iscoroutinefunction(endpoint)
            ]

        assert loose == [], f"these write routes left the loop without a lock landing: {loose}"

    def test_the_upload_route_is_the_named_exception(self) -> None:
        """It writes a file of its own, so it has no shared document to lose.

        Named here rather than left to a reader's inference: the reason the
        upload may leave the loop is NOT that it is fast (it is the slowest
        write on the server) but that its answer is a file nobody else is
        writing. Registered as async when python-multipart is missing, and
        that stand-in does nothing but refuse — so this only asserts when the
        real route is the one registered.
        """
        import inspect

        with patch(PATCH_SERVER_LOGGER):
            rows = {path: endpoint for path, _methods, endpoint in self._v1_routes()}

        upload = rows["/v1/files/upload"]
        if upload.__name__ == "files_upload_unavailable":
            pytest.skip("python-multipart is absent — the registered route is the refusal stand-in")

        assert not inspect.iscoroutinefunction(upload)


@fastapi_required
class TestASlowReadDoesNotFreezeTheServer:
    """
    The behavioural half, counted by events rather than timed by a clock.

    A wall-clock assertion on a threadpool is a flake generator. So the slow
    route parks on a threading.Event, the fast route is asked while it is
    parked, and the answer is asserted to have arrived BEFORE the event was
    released. Nothing is measured in milliseconds.
    """

    @contextlib.contextmanager
    def _client(self, tmp_path: Path):
        """A TestClient in a CONTEXT — one shared event loop across requests.

        This matters more than it looks. Outside a `with`, starlette's
        TestClient starts a fresh blocking portal (a fresh event loop) per
        request, and a blocked loop in one request could never be observed
        from another. Entered, both requests share the server's single loop —
        which is the thing under test.

        The isolated token store has to stay patched for the REQUESTS too, not
        just for issuing the token: the auth dependency reads the store on
        every call, and a client built inside a `with` and then used outside it
        gets a 401 from the real store. Found by this test failing that way.
        """
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
        """The property Patrick feels: one slow card does not freeze the phone."""
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

                    # The ping goes on its OWN thread and is waited for with a
                    # bound. Asking for it inline cannot detect the failure at
                    # all: on a blocked loop the call simply does not return
                    # until the slow read lets go, and then answers 204 — which
                    # is why the first version of this test passed against an
                    # async /v1/fleet. Proven by mutation.
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

            # Order matters and is the claim: the ping (204) landed FIRST,
            # while the fleet read (200) was still parked in its handler. A 401
            # on either would have made this a test of the auth refusal path,
            # which never reaches a handler at all.

    def test_the_probe_can_see_a_loop_that_really_is_blocked(self, tmp_path: Path) -> None:
        """Vacuity floor: the same measurement against a deliberately async block.

        Without this, the test above would pass on a server where every route
        was async — it would only be proving that the harness runs requests on
        separate loops. Here the blocking route IS async, so ping cannot be
        answered until it lets go, and the probe must notice.
        """
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

                # The loop is held by the async route, so /fast cannot land.
                assert not answered_at_ready.wait(timeout=1.0), (
                    "an async blocking route did NOT freeze the loop — this probe cannot detect blocking, "
                    "so the test above proves nothing"
                )
            finally:
                release.set()
                worker.join(timeout=10)
                asker.join(timeout=10)


# ==============================================
# 2. THE SNAPSHOT IS COALESCED, NOT REPEATED
# ==============================================


@fastapi_required
class TestTheSnapshotIsCoalesced:
    """
    One exec per question per TTL, and one exec per stampede.

    Measured cost of the thing being avoided: `baud --snapshot` spawns a
    process that walks a 17-branch census off disk, 60-90ms. /v1/fleet and
    /v1/rooms are the SAME read — rooms is a projection of the fleet envelope —
    so one screen refresh showing both cards used to pay for it twice.
    """

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
        """The TTL expires. Proven by shrinking it, never by sleeping 1.5s."""
        monkeypatch.setattr(host_fleet, "SNAPSHOT_TTL_SECONDS", 0.0)

        host_fleet.read_snapshot()
        time.sleep(0.01)
        host_fleet.read_snapshot()

        assert len(counted_exec) == 2

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
        """Single flight: eight callers arriving together spawn ONE process.

        The TTL alone cannot do this — with an empty cache, eight simultaneous
        callers all miss, and all exec. The fake below is deliberately slow
        enough that they overlap.
        """
        calls: list = []
        started = threading.Barrier(8, timeout=15)

        def _run(command, **kwargs):
            calls.append(list(command))
            time.sleep(0.2)
            return _completed(0, json.dumps(ENVELOPE))

        monkeypatch.setattr(host_fleet.subprocess, "run", _run)
        monkeypatch.setattr(host_fleet, "logger", MagicMock())
        monkeypatch.setattr(host_fleet, "json_handler", MagicMock())

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
        """A binary that comes back works on the NEXT request, not in 1.5s.

        Caching the refusal would be cheaper and wrong: it converts a
        momentary failure into a guaranteed window of refusals, during which
        the server reports a fleet outage that has already ended.
        """
        outcomes = [_completed(2, "", "nope"), _completed(0, json.dumps(ENVELOPE))]
        monkeypatch.setattr(host_fleet.subprocess, "run", lambda *a, **k: outcomes.pop(0))
        monkeypatch.setattr(host_fleet, "logger", MagicMock())
        monkeypatch.setattr(host_fleet, "json_handler", MagicMock())

        with pytest.raises(host_fleet.FleetUnavailable):
            host_fleet.read_snapshot()

        assert host_fleet.read_snapshot() == ENVELOPE

    def test_editing_the_first_answer_does_not_poison_the_cache(self, counted_exec: list) -> None:
        """The caller who MISSED gets their own object, so the store is safe.

        Without this, the first caller to annotate their envelope would have
        annotated every caller's for the remainder of the TTL — silently, and
        only ever under load.
        """
        first = host_fleet.read_snapshot()
        first["branches"][0]["name"] = "TAMPERED"
        first["injected"] = True

        second = host_fleet.read_snapshot()

        assert second == ENVELOPE
        assert "injected" not in second

    def test_editing_a_cached_answer_does_not_poison_the_cache_either(self, counted_exec: list) -> None:
        """And so does the caller who HIT — the other half of the same defence.

        Two separate copies stand between a caller and the stored envelope: one
        when it is put in, one when it is handed out. A test that only mutates
        the first answer exercises the store-side copy and passes with the
        hand-out copy deleted — measured, which is why this second test exists.
        """
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
        monkeypatch.setattr(host_fleet, "logger", MagicMock())
        monkeypatch.setattr(host_fleet, "json_handler", MagicMock())

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


# ==============================================
# 3. THE REGISTRY IS RESOLVED ONCE, AT BOOT
# ==============================================


class TestTheRegistryIsPinnedAtBoot:
    """
    drone re-resolves the registry per lookup; a long-lived server pays it.

    Measured 2026-08-18: the walk (up from cwd, glob each parent, credential-
    check every candidate against the nearest passport) costs 0.73ms, against
    0.003ms for the env var and ~0 for an explicit pin. Small per call, and
    this server does it on most read routes.

    ON THE RECORD, because the audit named this as the fix and it is only part
    of one: the other ~10ms of a drone get_branch_info is an audit-log write
    and a full registry re-read with a per-branch path resolve, both inside
    @drone's own tree. Reported to them, not reached into from here.
    """

    def test_pinning_hands_drone_the_path_it_found(self, tmp_path: Path) -> None:
        """The pin is drone's own public door, not an env var we hope is read."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")

        # Patched on the module, NOT swapped in sys.modules: `import aipass.drone
        # as drone` binds through the already-imported parent package's
        # attribute, so a sys.modules entry is simply not consulted and the
        # test silently exercises the real registry. Found by this test failing
        # with the machine's own path in the assertion.
        with patch("aipass.drone.get_registry_path", return_value=str(registry)):
            with patch("aipass.drone.set_registry_path") as pin, patch(PATCH_CONFIG_LOGGER):
                pinned = host_config.pin_registry()

        assert pinned == registry
        pin.assert_called_once_with(registry)

    def test_a_registry_that_is_not_there_pins_nothing(self, tmp_path: Path) -> None:
        """Never pin a path that does not exist — that freezes a broken answer.

        drone's own resolution has fallbacks (AIPASS_HOME, the package walk).
        Pinning a missing file would take all of them away for the life of the
        process, and turn a recoverable miss into a permanent one.
        """
        with patch("aipass.drone.get_registry_path", return_value=str(tmp_path / "gone.json")):
            with patch("aipass.drone.set_registry_path") as pin, patch(PATCH_CONFIG_LOGGER):
                pinned = host_config.pin_registry()

        assert pinned is None
        pin.assert_not_called()

    @fastapi_required
    def test_building_an_app_never_pins(self) -> None:
        """The isolation rule: create_app is called constantly by this suite.

        Pinning there would mutate the real drone module underneath every other
        test in the run — a test-order-dependent failure of exactly the kind
        that takes a day to find. The pin belongs to serve(), which runs once.
        """
        with patch("aipass.drone.set_registry_path") as pin, patch(PATCH_SERVER_LOGGER):
            host_server.create_app()

        pin.assert_not_called()

    @fastapi_required
    def test_serving_pins_before_the_first_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """And serve() does — before uvicorn is handed anything."""
        order: list = []

        monkeypatch.setattr(host_server.host_config, "load_config", lambda: {"host": "127.0.0.1", "port": 8787})
        monkeypatch.setattr(host_server.host_config, "validate_bind", lambda host, port: None)
        monkeypatch.setattr(host_server.host_config, "pin_registry", lambda: order.append("pinned"))
        monkeypatch.setattr(host_server, "create_app", lambda: order.append("app") or MagicMock())
        monkeypatch.setattr(host_server, "json_handler", MagicMock())

        uvicorn = MagicMock()
        uvicorn.run = lambda *args, **kwargs: order.append("served")

        with patch.dict("sys.modules", {"uvicorn": uvicorn}), patch(PATCH_SERVER_LOGGER):
            host_server.serve()

        assert order == ["pinned", "app", "served"]


# ==============================================
# 4. THE AUDIT TRAIL FETCHES ONE FRAME, NOT THE STACK
# ==============================================


# A `sys` with no _getframe, for driving the non-CPython fallback FROM CPython.
# Nulling the real sys._getframe cannot be used: inspect.stack() calls it to
# find the current frame, so the fallback would die on the way in.
_NO_GETFRAME = SimpleNamespace(platform=sys.platform)


class TestCallerDetectionFetchesOneFrame:
    """
    Same answer, two orders of magnitude cheaper.

    log_operation auto-detects its caller, and every one of the 37 audit calls
    in the host lane leaves the module name off. Measured 2026-08-18: the old
    inspect.stack() walk cost 0.21ms called two frames down and 1.77ms called
    fifty down — and fifty is ordinary depth inside a FastAPI request, so the
    cost was smallest exactly where it was measured and largest where it ran.
    """

    def test_both_paths_attribute_a_real_log_to_this_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Driven through log_operation, because the DEPTH is the whole risk.

        _getframe(2) and stack()[2] have to mean the same frame, and both have
        to mean the caller of log_operation rather than log_operation itself.
        Calling the detector directly would prove neither — it is one frame
        shallower than every real use, so the arithmetic under test would not
        be the arithmetic that runs.
        """
        monkeypatch.setattr(json_handler, "API_JSON_DIR", tmp_path)

        assert json_handler.log_operation("probe_fast") is True

        with patch.object(json_handler, "sys", _NO_GETFRAME):
            assert json_handler.log_operation("probe_walked") is True

        written = sorted(path.name for path in tmp_path.glob("*_log.json"))
        assert written == ["test_host_perf_log.json"], f"the audit trail named the wrong module: {written}"

        entries = json.loads((tmp_path / "test_host_perf_log.json").read_text(encoding="utf-8"))
        assert [entry["operation"] for entry in entries] == ["probe_fast", "probe_walked"]

    def test_the_detection_is_actually_cheaper(self) -> None:
        """A performance claim with no measurement is a hope.

        Deliberately loose (5x against a measured 38x): this asserts the walk
        was really removed, not a millisecond budget that would go red on a
        loaded CI box.
        """
        depth = 30

        def _call_at_depth(remaining: int) -> str:
            if remaining:
                return _call_at_depth(remaining - 1)
            return json_handler._get_caller_module_name()

        def _time(iterations: int = 40) -> float:
            start = time.perf_counter()
            for _ in range(iterations):
                _call_at_depth(depth)
            return time.perf_counter() - start

        _time(5)
        fast = _time()
        with patch.object(json_handler, "sys", _NO_GETFRAME):
            _time(5)
            walked = _time()

        assert fast * 5 < walked, f"one-frame fetch ({fast:.4f}s) is not clearly cheaper than the walk ({walked:.4f}s)"

    def test_a_private_caller_is_still_unknown(self) -> None:
        """Unchanged contract: an underscore-prefixed module does not name it."""
        frame = MagicMock()
        frame.f_code.co_filename = "/somewhere/_private.py"

        with patch.object(json_handler, "sys", SimpleNamespace(_getframe=lambda _depth: frame)):
            assert json_handler._get_caller_module_name() == "unknown"

    def test_a_broken_frame_fetch_is_unknown_not_a_crash(self) -> None:
        """The audit trail must never be the reason an operation fails."""

        def _boom(_depth: int):
            raise ValueError("no such frame")

        with patch.object(json_handler, "sys", SimpleNamespace(_getframe=_boom)):
            with patch.object(json_handler, "logger", MagicMock()):
                assert json_handler._get_caller_module_name() == "unknown"


# ==============================================
# 5. THE PUMP'S THREADS ARE ITS OWN, AND ITS CAP SPEAKS
# ==============================================


class TestThePumpPoolIsBoundedOutLoud:
    """
    The silent failure this replaces (DPLAN-0305 Audit 2, finding 9).

    Every live socket parks one thread in a blocking os.read for the whole life
    of the attach. Those reads went to asyncio's DEFAULT executor, which sizes
    itself to min(32, cpu_count + 4) — eight threads on this host. The ninth
    socket completed its handshake, passed auth, was accepted, and then sat
    with its read queued behind eight threads that never return: a blank
    terminal and no error anywhere. Nobody chose eight.
    """

    def test_the_pool_is_the_lanes_own_and_named(self) -> None:
        """Not asyncio's default: these threads never come back.

        A pool this lane permanently consumes is a pool nothing else can
        safely borrow, so it does not share one.
        """
        pool = host_attach.pump_executor()

        assert pool is host_attach.pump_executor(), "a new pool per call would uncap the whole thing"
        assert pool._max_workers == host_attach.PUMP_WORKERS
        assert pool._thread_name_prefix == "host-attach"

    def test_the_pump_hands_its_read_to_that_pool(self) -> None:
        """The pool exists to be used — the read must actually reach it."""
        pump = Path(host_server.__file__).read_text(encoding="utf-8")

        assert "run_in_executor(host_attach.pump_executor(), session.read)" in pump

    def test_a_session_beyond_the_cap_is_refused_in_words(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The whole point: a cap that speaks instead of a terminal that hangs."""
        monkeypatch.setattr(host_attach, "_PUMP_SLOTS", threading.BoundedSemaphore(1))
        host_attach._reserve_session("baud-first")

        with pytest.raises(host_attach.AttachUnavailable) as refusal:
            host_attach._reserve_session("baud-api")

        assert "cap" in str(refusal.value)
        assert "baud-api" in str(refusal.value)

    def test_the_refusal_does_not_wait_for_a_slot(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Waiting IS the silent hang, wearing a different hat.

        A blocking acquire would leave the socket accepted and empty until some
        other operator happened to close a terminal — the same blank screen the
        default executor gave, with a nicer implementation behind it.
        """
        monkeypatch.setattr(host_attach, "_PUMP_SLOTS", threading.BoundedSemaphore(1))
        host_attach._reserve_session("baud-first")

        refused = threading.Event()

        def _try() -> None:
            with contextlib.suppress(host_attach.AttachUnavailable):
                host_attach._reserve_session("baud-api")
            refused.set()

        waiter = threading.Thread(target=_try)
        waiter.start()
        try:
            assert refused.wait(timeout=2.0), "the reservation is waiting for a slot instead of refusing"
        finally:
            waiter.join(timeout=5)

    def test_the_cap_is_reserved_before_anything_is_spawned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Refused, not opened. A PTY spawned only to be refused is waste.

        Also the ordering that makes the cap real under concurrency: reserving
        after the spawn would let two sockets arriving together both pass a cap
        with room for one.
        """
        monkeypatch.setattr(host_attach, "_PUMP_SLOTS", threading.BoundedSemaphore(1))
        host_attach._reserve_session("baud-first")
        spawned: list = []
        monkeypatch.setattr(host_attach.pty, "openpty", lambda: spawned.append("pty") or (0, 0))

        with pytest.raises(host_attach.AttachUnavailable):
            host_attach._spawn_pty(["true"], None, "baud-api")

        assert spawned == [], "a PTY was opened for a session that was then refused"

    def test_a_hangup_gives_the_thread_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Otherwise the server refuses terminals while pumping none.

        Hung up TWICE on purpose — a socket that errors and then closes does
        exactly that, and a second release would over-credit the pool.
        """
        monkeypatch.setattr(host_attach, "_PUMP_SLOTS", threading.BoundedSemaphore(1))
        host_attach._reserve_session("baud-api")

        session = host_attach.AttachSession(MagicMock(), -1, "api", "baud-api")
        with patch.object(host_attach, "json_handler", MagicMock()), patch.object(host_attach, "logger", MagicMock()):
            session.hangup()
            session.hangup()

        # The slot is back: a fresh reservation succeeds where the cap is one.
        host_attach._reserve_session("baud-next")

    def test_a_failed_spawn_gives_the_thread_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No session will be built to own that reservation.

        Without the release, a machine that fails to spawn PUMP_WORKERS times
        refuses every terminal from then on while pumping precisely none — a
        leak that only ever shows up on the worst day.
        """
        monkeypatch.setattr(host_attach, "_PUMP_SLOTS", threading.BoundedSemaphore(1))
        monkeypatch.setattr(host_attach.pty, "openpty", lambda: (-1, -1))
        monkeypatch.setattr(host_attach, "set_winsize", lambda *a, **k: None)
        monkeypatch.setattr(host_attach.os, "close", lambda _fd: None)
        monkeypatch.setattr(host_attach.subprocess, "Popen", MagicMock(side_effect=OSError("no")))

        with patch.object(host_attach, "logger", MagicMock()):
            with pytest.raises(host_attach.AttachUnavailable):
                host_attach._spawn_pty(["true"], None, "baud-api")

        # The slot came back: a fresh reservation succeeds where the cap is one.
        host_attach._reserve_session("baud-next")

    def test_an_over_release_is_loud_not_silent_capacity(self) -> None:
        """A slot handed back twice is an accounting bug, and says so.

        Clamping would be the quiet option and the wrong one: it invents a
        thread the pool does not have, and the seventeenth socket lands in the
        same silent hang this whole change exists to delete.
        """
        # The MODULE's own semaphore, not a stand-in: a stand-in built here
        # would be bounded no matter what the module chose, and the pin would
        # pass with the module downgraded to a plain Semaphore. Proven by
        # mutation — it survived exactly that way first. Safe to use directly:
        # a bounded semaphore refuses the over-release rather than performing
        # it, so this leaves the count where it found it, and the conftest
        # fixture rebuilds it regardless.
        host_attach._reserve_session("baud-api")
        host_attach._release_session()

        with pytest.raises(ValueError):
            host_attach._release_session()
