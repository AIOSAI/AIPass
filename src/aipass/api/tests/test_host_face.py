# =================== AIPass ====================
# Name: test_host_face.py
# Description: Tests for serving @baud's phone face from the host API origin
# Version: 1.0.2
# Created: 2026-08-14
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/host/face.py and the face routes apps/handlers/host/server.py mounts."""

# Trap: a catch-all mount at "/" swallows routes added after create_app(); /assets is
# a subdirectory mount and each bundle-root file has its own route (TestTheMountCannotEatTheApi).

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(duplicate_test) — set_face_dir(), test_host_api_config.py; its config command, test_host_api.py
# seedgo: no-test-needed(duplicate_test) — issue_token() and verify_token() themselves, tests/test_host_api_config.py

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host import denials as host_denials
from aipass.api.apps.handlers.host import face as host_face
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import tokens as host_tokens

PATCH_SECRETS_BASE = "aipass.api.apps.handlers.auth.secrets.SECRETS_BASE"
PATCH_SECRETS_JSON = "aipass.api.apps.handlers.auth.secrets.json_handler"
PATCH_SECRETS_LOGGER = "aipass.api.apps.handlers.auth.secrets.logger"
PATCH_CONFIG_LOGGER = "aipass.api.apps.handlers.host.config.logger"
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


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path):
    """
    Every test here reads the host config, because locating the face does.

    Without it a face_dir in this machine's real config would decide what they see.
    """
    with patch(PATCH_SECRETS_BASE, tmp_path / "secrets"), patch(PATCH_SECRETS_JSON), patch(PATCH_SECRETS_LOGGER):
        with patch(PATCH_CONFIG_LOGGER):
            yield tmp_path / "secrets"


def _bundle(directory: Path, marker: str) -> Path:
    """A built phone bundle outside the checkout, whose files say which one it is."""
    (directory / "assets").mkdir(parents=True)
    (directory / host_face.FACE_ENTRY).write_text(f"<!doctype html><title>{marker}</title>", encoding="utf-8")
    (directory / "assets" / "phone.js").write_text(f"export const bundle = '{marker}';", encoding="utf-8")
    return directory


def _rendered(mock_log_method) -> list:
    """The face lines a patched logger method was handed, formatted as they would print."""
    calls = mock_log_method.call_args_list
    return [call.args[0] % call.args[1:] for call in calls if "phone face" in str(call.args[0])]


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
        assert host_face.face_location().is_available() is True

    def test_not_available_when_unbuilt(self, unbuilt_face: Path, quiet_face: None) -> None:
        """An absent bundle is a real state, not an error to swallow."""
        assert host_face.face_location().is_available() is False

    def test_entry_is_phone_html_not_index(self, built_face: Path, quiet_face: None) -> None:
        """Their entry is phone.html."""
        assert host_face.entry_file().name == "phone.html"

    def test_missing_bundle_names_the_build_command(self, unbuilt_face: Path, quiet_face: None) -> None:
        """The operator gets the fix, not just the symptom."""
        with pytest.raises(host_face.FaceUnavailable) as excinfo:
            host_face.entry_file()

        assert "build:phone" in str(excinfo.value)

    def test_root_files_are_enumerated_from_disk(self, built_face: Path, quiet_face: None) -> None:
        """Listed, not hardcoded."""
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


class TestWhereTheFaceLives:
    """A configured face_dir wins, the checkout build is the default."""

    def test_the_checkout_build_when_nothing_is_configured(self, built_face: Path, quiet_face: None) -> None:
        """No face_dir stored: what the checkout built, exactly as before."""
        location = host_face.face_location()

        assert location.root == built_face
        assert location.source == host_face.SOURCE_CHECKOUT

    def test_a_configured_dir_wins_over_the_checkout(self, built_face: Path, tmp_path: Path, quiet_face: None) -> None:
        """Served from the installed bundle even where a checkout build also sits."""
        installed = _bundle(tmp_path / "installed", "INSTALLED")
        host_config.set_face_dir(installed)

        location = host_face.face_location()

        assert location.root == installed
        assert location.source == host_face.SOURCE_CONFIGURED
        assert host_face.face_root() == installed
        assert host_face.entry_file() == installed / host_face.FACE_ENTRY

    def test_clearing_returns_the_checkout_default(self, built_face: Path, tmp_path: Path, quiet_face: None) -> None:
        """set_face_dir(None) hands the face back to the checkout build."""
        host_config.set_face_dir(_bundle(tmp_path / "installed", "INSTALLED"))

        assert host_config.set_face_dir(None) is None

        location = host_face.face_location()
        assert location.root == built_face
        assert location.source == host_face.SOURCE_CHECKOUT

    def test_a_configured_dir_that_lost_its_entry_names_the_configured_source(
        self, built_face: Path, tmp_path: Path, quiet_face: None
    ) -> None:
        """
        Valid when it was stored, emptied since: an uninstall, a moved directory.

        Falling back to the checkout build would serve a face nobody chose.
        """
        installed = _bundle(tmp_path / "installed", "INSTALLED")
        host_config.set_face_dir(installed)
        (installed / host_face.FACE_ENTRY).unlink()

        assert host_face.face_location().is_available() is False
        with pytest.raises(host_face.FaceUnavailable) as excinfo:
            host_face.entry_file()

        message = str(excinfo.value)
        assert "configured face dir" in message
        assert str(installed) in message
        assert "aipass baud install" in message
        assert "set-config --face-dir" in message
        assert "build:phone" not in message

    def test_an_unbuilt_checkout_names_the_checkout_source(self, unbuilt_face: Path, quiet_face: None) -> None:
        """The default's fix is the npm build, as it was, and says it is the default."""
        with pytest.raises(host_face.FaceUnavailable) as excinfo:
            host_face.entry_file()

        # The root is tmp_path, whose name carries this test's own words; read around it.
        message = str(excinfo.value).replace(str(unbuilt_face), "<root>")
        assert "checkout" in message
        assert "npm run build:phone" in message
        assert "aipass baud install" not in message

    def test_a_relative_configured_dir_is_never_served(
        self, unbuilt_face: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, quiet_face: None
    ) -> None:
        """set_face_dir refuses a relative path; a hand-edited store can still hold one."""
        _bundle(tmp_path / "dist-phone", "WORKING-DIRECTORY")
        monkeypatch.chdir(tmp_path)
        host_config.save_config({"face_dir": "dist-phone"})

        assert host_face.face_location().source == host_face.SOURCE_CONFIGURED
        assert host_face.face_location().is_available() is False
        assert host_face.root_files() == []


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
        """The URL the owner types is the URL that renders."""
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

        A browser doing a top-level navigation cannot attach an Authorization header.
        """
        response = client.get("/")
        gated = client.get("/v1/whoami")

        assert response.status_code == 200
        assert gated.status_code == 401

    def test_assets_are_served_from_the_same_origin(self, client, built_face: Path) -> None:
        """The bundle references /assets/... absolutely; the mount must answer."""
        response = client.get("/assets/phone.js")

        assert response.status_code == 200
        assert response.text == (built_face / "assets" / "phone.js").read_text(encoding="utf-8")

    def test_manifest_is_served(self, client) -> None:
        """Without it, 'add to home screen' silently degrades."""
        response = client.get("/manifest.webmanifest")

        assert response.status_code == 200
        assert response.json() == {"name": "BAUD"}


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
        create_app() returned.
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
        """Traversal out of the one directory served wholesale."""
        response = client.get("/assets/../../../../etc/passwd")

        assert response.status_code in (403, 404)
        assert "root:" not in response.text

    def test_bundle_root_files_are_served_by_name_not_by_path(self, client) -> None:
        """No caller-supplied path reaches the filesystem here."""
        response = client.get("/phone.html")

        assert response.status_code == 200
        assert "BAUD" in response.text


@fastapi_required
class TestTheEntryDocumentIsNeverServedStale:
    """
    A stable name plus no cache-control is a stale bundle waiting to happen.

    A stable-named file must revalidate (RFC 9111 heuristic freshness); hashed /assets
    keep caching. no-cache, not no-store: the etag still answers 304.
    """

    def test_the_entry_document_must_revalidate(self, client) -> None:
        """The measured defect, asked of the response @baud measured."""
        response = client.get("/")

        assert response.headers.get("cache-control") == "no-cache"

    def test_the_pwa_start_url_must_revalidate_too(self, client) -> None:
        """The route a phone actually launches, and the one a narrow fix misses.

        @baud's manifest declares start_url /phone.html, not "/".
        """
        response = client.get("/phone.html")

        assert response.status_code == 200
        assert response.headers.get("cache-control") == "no-cache"

    def test_the_manifest_must_revalidate(self, client) -> None:
        """Un-hashed and it names the start_url and the icons — same class."""
        response = client.get("/manifest.webmanifest")

        assert response.status_code == 200
        assert response.headers.get("cache-control") == "no-cache"

    def test_revalidating_still_answers_304_and_sends_no_bytes(self, client) -> None:
        """no-cache, not no-store — the distinction is the whole cost argument."""
        first = client.get("/")

        assert "etag" in {key.lower() for key in first.headers}

        second = client.get("/", headers={"If-None-Match": first.headers["etag"]})

        assert second.status_code == 304
        assert second.content == b""

    def test_hashed_assets_keep_their_caching(self, client) -> None:
        """The lane that must NOT be touched, pinned so a widening is noticed."""
        response = client.get("/assets/phone.js")

        assert response.status_code == 200
        assert response.headers.get("cache-control") is None


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
        """503 face_unavailable with a ref into the log, not a blank page or a traceback."""
        response = bare_client.get("/")

        assert response.status_code == 503
        error = response.json()["error"]
        assert error["code"] == "face_unavailable"
        # The exception's words stay in the host log; the client gets the code's sentence and a ref.
        assert error["message"] == host_denials.SENTENCES["face_unavailable"]
        assert re.fullmatch("[0-9a-f]{12}", error["ref"])
        assert "build:phone" not in response.text

    def test_the_api_still_serves_without_a_face(self, bare_client) -> None:
        """The API is the product; the face is one of its clients."""
        response = bare_client.get("/v1/ping")

        assert response.status_code == 204


@fastapi_required
class TestTheServerResolvesTheFaceOnce:
    """
    FPLAN-0587's stated limit, pinned: the face is resolved at create_app().

    Per-request resolution would pair a new phone.html with the old /assets mount.
    """

    def test_the_origin_serves_a_configured_dir(self, built_face: Path, tmp_path: Path) -> None:
        """Configured wins at the origin too, the assets mount included."""
        from fastapi.testclient import TestClient

        host_config.set_face_dir(_bundle(tmp_path / "installed", "INSTALLED"))

        with patch(PATCH_SERVER_LOGGER), patch(PATCH_FACE_JSON), patch(PATCH_FACE_LOGGER):
            client = TestClient(host_server.create_app(), raise_server_exceptions=False)
            responses = [client.get(path) for path in ("/", "/phone.html", "/assets/phone.js")]

        assert [response.status_code for response in responses] == [200, 200, 200]
        assert all("INSTALLED" in response.text for response in responses)

    def test_a_running_server_keeps_the_dir_it_started_with(self, built_face: Path, tmp_path: Path) -> None:
        """A face_dir stored after start changes nothing until a restart, on every face route."""
        from fastapi.testclient import TestClient

        host_config.set_face_dir(_bundle(tmp_path / "first", "FIRST"))

        with patch(PATCH_SERVER_LOGGER), patch(PATCH_FACE_JSON), patch(PATCH_FACE_LOGGER):
            client = TestClient(host_server.create_app(), raise_server_exceptions=False)
            host_config.set_face_dir(_bundle(tmp_path / "second", "SECOND"))
            responses = [client.get(path) for path in ("/", "/phone.html", "/assets/phone.js")]

        assert [response.status_code for response in responses] == [200, 200, 200]
        assert all("FIRST" in response.text for response in responses)

    def test_the_startup_log_names_the_source(self, built_face: Path, tmp_path: Path) -> None:
        """Which bundle a server is showing is answerable from its log alone."""
        installed = _bundle(tmp_path / "installed", "INSTALLED")
        host_config.set_face_dir(installed)

        with patch(PATCH_SERVER_LOGGER) as server_logger, patch(PATCH_FACE_JSON), patch(PATCH_FACE_LOGGER):
            host_server.create_app()

        served = _rendered(server_logger.info)
        assert len(served) == 1
        assert str(installed) in served[0]
        assert host_face.SOURCE_CONFIGURED in served[0]

    def test_an_unservable_configured_dir_is_a_503_named_in_the_log_not_the_checkout(
        self, built_face: Path, tmp_path: Path
    ) -> None:
        """The checkout build is right there, and is still not served."""
        from fastapi.testclient import TestClient

        installed = _bundle(tmp_path / "installed", "INSTALLED")
        host_config.set_face_dir(installed)
        (installed / host_face.FACE_ENTRY).unlink()

        with patch(PATCH_SERVER_LOGGER) as server_logger, patch(PATCH_FACE_JSON), patch(PATCH_FACE_LOGGER):
            client = TestClient(host_server.create_app(), raise_server_exceptions=False)
            response = client.get("/")

        assert response.status_code == 503
        error = response.json()["error"]
        assert error["code"] == "face_unavailable"
        assert error["message"] == host_denials.SENTENCES["face_unavailable"]
        assert re.fullmatch("[0-9a-f]{12}", error["ref"])
        assert "configured face dir" not in response.text
        warned = _rendered(server_logger.warning)
        assert len(warned) == 1
        assert "configured face dir" in warned[0]
