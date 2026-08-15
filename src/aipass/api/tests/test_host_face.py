#!/usr/bin/env python3
# =================== AIPass ====================
# Name: test_host_face.py
# Description: Tests for serving @baud's phone face from the host API origin
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-08-14
# =============================================

"""
Tests for the Host API Face Lane

Option A of @baud's serving question: their bundle is served from THIS origin, so
there is no CORS allow-list to publish and nothing to misconfigure.

The load-bearing tests here are in TestTheMountCannotEatTheApi.

My first cut served the bundle as a catch-all mount at "/", the ordinary way to
serve an SPA. The existing scope tests caught it: they register a route on the
app AFTER create_app() returns, and a catch-all registered last swallows anything
added after it, so they 404'd. The bundle is now served precisely — /assets is a
real subdirectory mount and each bundle-root file has its own route — so nothing
can be shadowed. The regression test for that is
test_a_route_added_after_create_app_still_answers.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.api.apps.handlers.host import face as host_face
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import tokens as host_tokens

PATCH_SECRETS_BASE = "aipass.api.apps.handlers.auth.secrets.SECRETS_BASE"
PATCH_SECRETS_JSON = "aipass.api.apps.handlers.auth.secrets.json_handler"
PATCH_SECRETS_LOGGER = "aipass.api.apps.handlers.auth.secrets.logger"
PATCH_TOKENS_JSON = "aipass.api.apps.handlers.host.tokens.json_handler"
PATCH_TOKENS_LOGGER = "aipass.api.apps.handlers.host.tokens.logger"
PATCH_SERVER_LOGGER = "aipass.api.apps.handlers.host.server.logger"
PATCH_FACE_JSON = "aipass.api.apps.handlers.host.face.json_handler"
PATCH_FACE_LOGGER = "aipass.api.apps.handlers.host.face.logger"

ENTRY_HTML = "<!doctype html><title>BAUD</title><div id=root></div>"

fastapi_required = pytest.mark.skipif(
    not host_server.is_available(),
    reason="the [host] extra is not installed",
)


@pytest.fixture
def built_face(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A stand-in for @baud's built bundle, with the real file shape."""
    root = tmp_path / "repo"
    bundle = root / host_face.FACE_RELATIVE
    (bundle / "assets").mkdir(parents=True)
    (bundle / host_face.FACE_ENTRY).write_text(ENTRY_HTML, encoding="utf-8")
    (bundle / "assets" / "phone.js").write_text("export const face = true;", encoding="utf-8")
    (bundle / "manifest.webmanifest").write_text('{"name":"BAUD"}', encoding="utf-8")

    monkeypatch.setattr(host_face, "repo_root", lambda: root)
    return bundle


@pytest.fixture
def unbuilt_face(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A repo where nobody has run the phone build yet."""
    monkeypatch.setattr(host_face, "repo_root", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def quiet_face():
    """Silence the handler's logging and receipts."""
    with patch(PATCH_FACE_JSON), patch(PATCH_FACE_LOGGER):
        yield


class TestLocatingTheBundle:
    """The bundle path is @baud's, named once, and absence is reported."""

    def test_available_when_the_entry_exists(self, built_face: Path, quiet_face: None) -> None:
        """Presence is decided by the entry document, not the directory."""
        assert host_face.is_face_available() is True

    def test_not_available_when_unbuilt(self, unbuilt_face: Path, quiet_face: None) -> None:
        """An absent bundle is a real state, not an error to swallow."""
        assert host_face.is_face_available() is False

    def test_entry_is_phone_html_not_index(self, built_face: Path, quiet_face: None) -> None:
        """
        Their entry is phone.html.

        Assuming index.html would 404 every navigation while the directory sat
        there looking correct.
        """
        assert host_face.entry_file().name == "phone.html"

    def test_missing_bundle_names_the_build_command(self, unbuilt_face: Path, quiet_face: None) -> None:
        """The operator gets the fix, not just the symptom."""
        with pytest.raises(host_face.FaceUnavailable) as excinfo:
            host_face.entry_file()

        assert "build:phone" in str(excinfo.value)

    def test_root_files_are_enumerated_from_disk(self, built_face: Path, quiet_face: None) -> None:
        """
        Listed, not hardcoded.

        An icon @baud adds on their next build is served after a restart with no
        change here — a hardcoded list would 404 it silently.
        """
        assert set(host_face.root_files()) == {"phone.html", "manifest.webmanifest"}

    def test_root_files_excludes_directories(self, built_face: Path, quiet_face: None) -> None:
        """assets/ has its own mount; nothing nested is reachable by bare name."""
        assert "assets" not in host_face.root_files()

    def test_root_files_is_empty_when_unbuilt(self, unbuilt_face: Path, quiet_face: None) -> None:
        """No bundle, no routes — and no exception during app creation."""
        assert host_face.root_files() == []

    def test_face_root_resolves_under_the_repo(self, built_face: Path, quiet_face: None) -> None:
        """@baud's bundle path, named once, resolved from the seated repo root."""
        assert host_face.face_root() == built_face
        assert host_face.face_root().name == "dist-phone"

    def test_assets_dir_sits_under_the_bundle(self, built_face: Path, quiet_face: None) -> None:
        """The only directory this server exposes wholesale."""
        assert host_face.assets_dir() == built_face / "assets"


@pytest.fixture
def client(built_face: Path, tmp_path: Path):
    """A TestClient over the real app with the face built and tokens isolated."""
    from fastapi.testclient import TestClient

    store = tmp_path / "secrets"
    with patch(PATCH_SECRETS_BASE, store), patch(PATCH_SECRETS_JSON), patch(PATCH_SECRETS_LOGGER):
        with patch(PATCH_TOKENS_JSON), patch(PATCH_TOKENS_LOGGER), patch(PATCH_SERVER_LOGGER):
            with patch(PATCH_FACE_JSON), patch(PATCH_FACE_LOGGER):
                yield TestClient(host_server.create_app(), raise_server_exceptions=False)


@pytest.fixture
def auth(client) -> dict:
    """A valid read-scope bearer header."""
    _, raw = host_tokens.issue_token("face-test", scope="read")
    return {"Authorization": f"Bearer {raw}"}


@fastapi_required
class TestServingTheFace:
    """One origin: the page and the API answer on the same host."""

    def test_face_entry_serves_the_document_at_the_origin_root(self, client) -> None:
        """The URL Patrick types is the URL that renders."""
        response = client.get("/")

        assert response.status_code == 200
        assert "BAUD" in response.text

    def test_face_entry_returns_html_not_json(self, client) -> None:
        """A browser navigation must get a document, not an API envelope."""
        response = client.get("/")

        assert response.headers["content-type"].startswith("text/html")

    def test_root_needs_no_token(self, client) -> None:
        """
        Deliberate, and mechanical rather than a preference.

        A browser doing a top-level navigation cannot attach an Authorization
        header. Gating this would require a second, weaker auth system to guard a
        public bundle that renders a token door and nothing else.
        """
        response = client.get("/")

        assert response.status_code == 200

    def test_assets_are_served_from_the_same_origin(self, client) -> None:
        """The bundle references /assets/... absolutely; the mount must answer."""
        response = client.get("/assets/phone.js")

        assert response.status_code == 200

    def test_manifest_is_served(self, client) -> None:
        """Without it, 'add to home screen' silently degrades."""
        response = client.get("/manifest.webmanifest")

        assert response.status_code == 200


@fastapi_required
class TestTheMountCannotEatTheApi:
    """The regression this whole file exists for."""

    def test_v1_is_not_shadowed_by_the_mount(self, client) -> None:
        """Serving a page at the origin root must not cost the API its routes."""
        response = client.get("/v1/ping")

        assert response.status_code == 204

    def test_a_route_added_after_create_app_still_answers(self, built_face: Path, tmp_path: Path) -> None:
        """
        THE regression. A catch-all mount swallowed routes registered after
        create_app() returned — which is exactly what the scope tests do, and how
        this was caught. Phase 3's verb lane would have hit it next.
        """
        from fastapi.testclient import TestClient

        with patch(PATCH_SERVER_LOGGER), patch(PATCH_FACE_JSON), patch(PATCH_FACE_LOGGER):
            app = host_server.create_app()

            @app.get("/v1/added-later")
            async def _later() -> dict:
                return {"ok": True}

            response = TestClient(app, raise_server_exceptions=False).get("/v1/added-later")

        assert response.status_code == 200

    def test_the_token_wall_still_stands_behind_the_face(self, client) -> None:
        """Serving a public page must not have opened the data lane."""
        response = client.get("/v1/whoami")

        assert response.status_code == 401

    def test_authenticated_v1_still_answers(self, client, auth: dict) -> None:
        """And the wall still lets a real token through."""
        response = client.get("/v1/whoami", headers=auth)

        assert response.status_code == 200

    def test_unknown_paths_do_not_reach_the_api(self, client) -> None:
        """A miss is a miss — no route is invented by the static mount."""
        response = client.get("/not-a-real-file.js")

        assert response.status_code == 404

    def test_the_assets_mount_cannot_escape_the_bundle(self, client) -> None:
        """
        Traversal out of the one directory served wholesale.

        Starlette refuses this itself, which is precisely why /assets is a
        StaticFiles mount rather than a hand-rolled file reader — but a static
        server pointed at a repo subdirectory deserves the assertion.
        """
        response = client.get("/assets/../../../../etc/passwd")

        assert response.status_code in (403, 404)
        assert "root:" not in response.text

    def test_bundle_root_files_are_served_by_name_not_by_path(self, client) -> None:
        """
        No caller-supplied path reaches the filesystem here.

        Each bundle-root route is bound to a name from a directory listing at
        app-creation time, so there is nothing for a request to point at — the
        same names-not-paths reasoning as /v1/files.
        """
        response = client.get("/phone.html")

        assert response.status_code == 200
        assert "BAUD" in response.text


@fastapi_required
class TestUnbuiltFace:
    """An unbuilt bundle degrades honestly and takes nothing else down."""

    @pytest.fixture
    def bare_client(self, unbuilt_face: Path, tmp_path: Path):
        """A server whose face was never built."""
        from fastapi.testclient import TestClient

        store = tmp_path / "secrets"
        with patch(PATCH_SECRETS_BASE, store), patch(PATCH_SECRETS_JSON), patch(PATCH_SECRETS_LOGGER):
            with patch(PATCH_TOKENS_JSON), patch(PATCH_TOKENS_LOGGER), patch(PATCH_SERVER_LOGGER):
                with patch(PATCH_FACE_JSON), patch(PATCH_FACE_LOGGER):
                    yield TestClient(host_server.create_app(), raise_server_exceptions=False)

    def test_root_reports_the_missing_bundle(self, bare_client) -> None:
        """503 with the build command, not a blank page or a traceback."""
        response = bare_client.get("/")

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "face_unavailable"
        assert "build:phone" in response.json()["error"]["message"]

    def test_the_api_still_serves_without_a_face(self, bare_client) -> None:
        """The API is the product; the face is one of its clients."""
        response = bare_client.get("/v1/ping")

        assert response.status_code == 204
