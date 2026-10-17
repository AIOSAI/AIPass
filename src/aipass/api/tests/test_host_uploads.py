# =================== AIPass ====================
# Name: test_host_uploads.py
# Description: Tests for the host API photo lane — bytes onto disk, named by the server
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/host/uploads.py and its POST /v1/files/upload route."""

# Real files in a real tmp directory: the failures here are filesystem-shaped (a partial
# file left behind, a mode set after creation) and a mocked filesystem invents past them.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — handlers/host/attach.py, where the path goes; tests/test_host_attach.py
# seedgo: no-test-needed(covered_elsewhere) — token issue and check in host_tokens; tests/test_host_token_store.py

import os
import stat
import sys
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import tokens as host_tokens
from aipass.api.apps.handlers.host import uploads as host_uploads

PATCH_SECRETS_BASE = "aipass.api.apps.handlers.auth.secrets.SECRETS_BASE"
PATCH_SECRETS_JSON = "aipass.api.apps.handlers.auth.secrets.json_handler"
PATCH_SECRETS_LOGGER = "aipass.api.apps.handlers.auth.secrets.logger"
PATCH_TOKENS_JSON = "aipass.api.apps.handlers.host.tokens.json_handler"
PATCH_TOKENS_LOGGER = "aipass.api.apps.handlers.host.tokens.logger"
PATCH_UPLOADS_JSON = "aipass.api.apps.handlers.host.uploads.json_handler"
PATCH_UPLOADS_LOGGER = "aipass.api.apps.handlers.host.uploads.logger"
PATCH_SERVER_JSON = "aipass.api.apps.handlers.host.server.json_handler"
PATCH_SERVER_LOGGER = "aipass.api.apps.handlers.host.server.logger"

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
GIF = b"GIF89a" + b"\x00" * 64
WEBP = b"RIFF\x24\x00\x00\x00WEBP" + b"\x00" * 64
HEIC = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64

fastapi_required = pytest.mark.skipif(
    not host_server.is_available(),
    reason="the [host] extra is not installed",
)

multipart_required = pytest.mark.skipif(
    not getattr(host_server, "MULTIPART_AVAILABLE", False),
    reason="python-multipart is not installed",
)


@pytest.fixture
def landing(tmp_path: Path):
    """Point the upload directory at a temp dir — never the operator's Pictures."""
    root = tmp_path / "Pictures" / "BAUD"
    with patch.object(host_uploads, "upload_root", lambda: root):
        with patch(PATCH_UPLOADS_JSON), patch(PATCH_UPLOADS_LOGGER):
            yield root


@pytest.fixture
def store(tmp_path: Path):
    """Redirect the token store — no real token is ever touched."""
    with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_SECRETS_JSON), patch(PATCH_SECRETS_LOGGER):
        with patch(PATCH_TOKENS_JSON), patch(PATCH_TOKENS_LOGGER):
            yield tmp_path


class TestTheServerNamesTheFile:
    """The client's filename is not sanitised, fenced or normalised — it is absent."""

    def test_the_name_is_generated_not_taken(self, landing: Path) -> None:
        """Stamp, random suffix, sniffed extension — none of it from the caller."""
        result = host_uploads.store_image(BytesIO(PNG))

        name = Path(str(result["path"])).name
        assert name.startswith("phone-")
        assert name.endswith(".png")

    def test_two_uploads_in_the_same_second_are_two_files(self, landing: Path) -> None:
        """A timestamp alone collides; the random suffix makes a burst of uploads a burst of files."""
        first = host_uploads.store_image(BytesIO(PNG))
        second = host_uploads.store_image(BytesIO(PNG))

        assert first["path"] != second["path"]
        assert len(list(landing.iterdir())) == 2

    def test_a_name_collision_refuses_and_leaves_the_earlier_file_alone(self, landing: Path) -> None:
        """
        A hard error, and ONLY a hard error — never a silent loss either way.

        On an O_EXCL collision the destination is the EARLIER upload, so cleanup must not remove it.
        """
        first = host_uploads.store_image(BytesIO(JPEG))
        taken = Path(str(first["path"]))

        with patch.object(host_uploads, "_generated_name", lambda extension: taken.name):
            with pytest.raises(host_uploads.UploadUnavailable):
                host_uploads.store_image(BytesIO(JPEG))

        assert taken.read_bytes() == JPEG
        assert list(landing.iterdir()) == [taken]

    def test_a_stream_that_fails_mid_write_leaves_no_partial_file(self, landing: Path) -> None:
        """
        The other half of the same line: a file this write DID create is still its mess.
        """

        class DroppedConnection(BytesIO):
            def read(self, size: Any = -1) -> bytes:
                if self.tell() > 0:
                    raise OSError("connection reset by peer")
                return super().read(size)

        with pytest.raises(host_uploads.UploadUnavailable):
            host_uploads.store_image(DroppedConnection(PNG + os.urandom(200_000)))

        assert list(landing.iterdir()) == []

    def test_the_upload_lands_in_the_upload_directory(self, landing: Path) -> None:
        """One folder, the same one the desktop's own captures use."""
        result = host_uploads.store_image(BytesIO(PNG))

        assert Path(str(result["path"])).parent == landing

    def test_the_directory_is_created_when_it_does_not_exist(self, landing: Path) -> None:
        """First upload on a fresh machine must not fail on a missing folder."""
        assert not landing.exists()

        host_uploads.store_image(BytesIO(PNG))

        assert landing.is_dir()

    def test_the_stored_bytes_are_the_uploaded_bytes(self, landing: Path) -> None:
        """Including the sniffed head: the first 32 bytes are read off the stream and must be written back."""
        result = host_uploads.store_image(BytesIO(JPEG))

        assert Path(str(result["path"])).read_bytes() == JPEG

    def test_a_large_image_survives_chunking_intact(self, landing: Path) -> None:
        """
        Bigger than one chunk, so the loop actually loops.
        """
        payload = PNG + os.urandom(200_000)

        result = host_uploads.store_image(BytesIO(payload))

        assert Path(str(result["path"])).read_bytes() == payload
        assert result["bytes"] == len(payload)


@fastapi_required
@multipart_required
class TestAHostileFilenameGoesNowhere:
    """
    The route is handed real hostile names through a real multipart parser.
    """

    def _post(self, client: Any, raw: str, filename: str, data: bytes = PNG) -> Any:
        """POST one image under a chosen filename."""
        return client.post(
            "/v1/files/upload",
            files={"image": (filename, BytesIO(data), "image/png")},
            headers={"Authorization": f"Bearer {raw}"},
        )

    @pytest.mark.parametrize(
        "hostile",
        [
            "../../../../etc/passwd",
            "..\\..\\Windows\\System32\\drivers\\etc\\hosts",
            "/etc/shadow",
            ".bashrc",
            "....//....//authorized_keys",
            "photo.png\x00.sh",
            "  spaces and.png  ",
            "a" * 500 + ".png",
        ],
    )
    def test_a_hostile_filename_never_reaches_the_filesystem(self, store: Any, landing: Path, hostile: str) -> None:
        """Every one of these lands as a generated name inside the upload dir."""
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")

        with patch(PATCH_SERVER_JSON), patch(PATCH_SERVER_LOGGER):
            response = self._post(TestClient(host_server.create_app()), raw, hostile)

        assert response.status_code == 200

        stored = Path(response.json()["path"])
        assert stored.parent == landing
        assert stored.name.startswith("phone-")
        assert list(landing.iterdir()) == [stored]

    def test_nothing_is_written_outside_the_upload_directory(self, store: Any, landing: Path) -> None:
        """
        The traversal claim, checked at the destination rather than the input.
        """
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")

        with patch(PATCH_SERVER_JSON), patch(PATCH_SERVER_LOGGER):
            response = self._post(TestClient(host_server.create_app()), raw, "../../escape.png")

        stored = Path(response.json()["path"]).resolve()
        assert stored.is_relative_to(landing.resolve())


class TestTheContentTypeIsNeverBelieved:
    """
    `Content-Type: image/png` costs a caller nothing to write.
    """

    @pytest.mark.parametrize(
        "payload,extension",
        [(PNG, "png"), (JPEG, "jpg"), (GIF, "gif"), (WEBP, "webp"), (HEIC, "heic")],
    )
    def test_each_format_is_recognised_by_its_magic(self, payload: bytes, extension: str) -> None:
        """The formats a phone camera roll actually produces."""
        assert host_uploads.sniff_image(payload) == extension

    def test_a_container_brand_is_matched_at_its_offset(self) -> None:
        """WebP and HEIC put a size field before their brand; a byte-zero check misses both."""
        assert host_uploads.sniff_image(WEBP) == "webp"
        assert host_uploads.sniff_image(HEIC) == "heic"

    def test_a_script_declaring_itself_an_image_is_refused(self, landing: Path) -> None:
        """The whole point. The header said PNG; the bytes said shell script."""
        with pytest.raises(host_uploads.UploadRefused):
            host_uploads.store_image(BytesIO(b"#!/bin/sh\nrm -rf ~\n"))

    def test_a_refused_upload_writes_no_file_at_all(self, landing: Path) -> None:
        """Sniffed BEFORE the directory is touched, so a rejected upload never becomes a file."""
        with pytest.raises(host_uploads.UploadRefused):
            host_uploads.store_image(BytesIO(b"not an image at all"))

        assert not landing.exists()

    def test_an_empty_upload_is_refused(self, landing: Path) -> None:
        """Zero bytes is not a small image, it is no image."""
        with pytest.raises(host_uploads.UploadRefused) as caught:
            host_uploads.store_image(BytesIO(b""))

        assert "empty" in str(caught.value).lower()

    def test_a_truncated_signature_is_refused(self, landing: Path) -> None:
        """
        Two bytes of a PNG header is not a PNG.

        A slice past a short buffer's end returns short rather than raising, so a naive check matches.
        """
        with pytest.raises(host_uploads.UploadRefused):
            host_uploads.store_image(BytesIO(b"\x89P"))


class TestTheCapRefusesAndNeverTruncates:
    """A truncated image is a corrupt one wearing a success response."""

    def test_an_oversized_declared_length_is_refused_before_reading(self, landing: Path) -> None:
        """The cheap gate: a Content-Length already over the cap needs no body read."""
        never_read = BytesIO(PNG)

        with pytest.raises(host_uploads.UploadRefused):
            host_uploads.store_image(never_read, declared_length=host_uploads.MAX_UPLOAD_BYTES + 1)

        assert never_read.tell() == 0

    def test_a_lying_content_length_is_still_caught(self, landing: Path) -> None:
        """The running total holds: trusting the header alone is how a 25MB cap passes a 200MB body."""
        payload = PNG + b"\x00" * (host_uploads.MAX_UPLOAD_BYTES + 1)

        with pytest.raises(host_uploads.UploadRefused) as caught:
            host_uploads.store_image(BytesIO(payload), declared_length=10)

        assert "cap" in str(caught.value)

    def test_an_over_cap_upload_leaves_no_partial_file(self, landing: Path) -> None:
        """The refusal fires mid-write, so the partial already on disk must be removed."""
        payload = PNG + b"\x00" * (host_uploads.MAX_UPLOAD_BYTES + 1)

        with pytest.raises(host_uploads.UploadRefused):
            host_uploads.store_image(BytesIO(payload))

        assert list(landing.iterdir()) == []

    def test_an_upload_at_the_cap_is_stored(self, landing: Path) -> None:
        """The boundary, from the allowed side: a cap that refuses its own limit is an off-by-one."""
        payload = PNG + b"\x00" * (host_uploads.MAX_UPLOAD_BYTES - len(PNG))

        result = host_uploads.store_image(BytesIO(payload))

        assert result["bytes"] == host_uploads.MAX_UPLOAD_BYTES


class TestTheFileOnDisk:
    """What the stored object actually is, checked on a real filesystem."""

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="0o600 is a POSIX mode; Windows st_mode carries no owner-only story to assert",
    )
    def test_it_is_created_private_not_narrowed_afterwards(self, landing: Path) -> None:
        """0o600 via os.open, not chmod-after: a file narrowed a moment later was readable for that moment."""
        result = host_uploads.store_image(BytesIO(PNG))

        mode = stat.S_IMODE(os.stat(str(result["path"])).st_mode)
        assert mode == 0o600

    def test_the_response_carries_an_absolute_path(self, landing: Path) -> None:
        """That path IS the product; a relative one resolves against the receiving agent's cwd."""
        result = host_uploads.store_image(BytesIO(PNG))

        assert Path(str(result["path"])).is_absolute()

    def test_a_write_failure_is_ours_not_the_callers(self, landing: Path) -> None:
        """A full disk is not a bad request: 503-shaped."""
        with patch.object(host_uploads.os, "open", side_effect=OSError("no space left on device")):
            with pytest.raises(host_uploads.UploadUnavailable):
                host_uploads.store_image(BytesIO(PNG))

    def test_an_unwritable_destination_is_ours_not_the_callers(self, landing: Path) -> None:
        """
        Same split, one layer up: the directory itself could not be made.

        Asserts the mkdir sentence, not the word "directory": the OS's "No such file or directory" has it.
        """
        with patch.object(Path, "mkdir", side_effect=OSError("permission denied")):
            with pytest.raises(host_uploads.UploadUnavailable) as caught:
                host_uploads.store_image(BytesIO(PNG))

        assert str(caught.value).startswith("Could not create the upload directory")
        assert "permission denied" in str(caught.value)


class TestWhereImagesLand:
    """
    Mirrors the desktop rather than inventing a second home.

    screenshot.rs writes Pictures/BAUD/baud-<stamp>.png.
    """

    def test_the_root_is_the_desktops_own_directory(self, tmp_path: Path) -> None:
        """Pictures/BAUD, the same leaf the Rust side uses."""
        with patch.dict(os.environ, {"XDG_PICTURES_DIR": str(tmp_path / "Bilder")}, clear=False):
            assert host_uploads.upload_root() == tmp_path / "Bilder" / "BAUD"

    def test_a_relocated_pictures_directory_is_honoured(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Read from the XDG config the way Tauri's picture_dir() does, so both land in one folder."""
        config = tmp_path / ".config"
        config.mkdir()
        (config / "user-dirs.dirs").write_text('XDG_PICTURES_DIR="$HOME/Billeder"\n', encoding="utf-8")

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.delenv("XDG_PICTURES_DIR", raising=False)

        assert host_uploads.upload_root() == tmp_path / "Billeder" / "BAUD"

    def test_the_fallback_needs_no_platform_branch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """~/Pictures is also the right answer on Windows and macOS."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.delenv("XDG_PICTURES_DIR", raising=False)

        assert host_uploads.upload_root() == tmp_path / "Pictures" / "BAUD"

    def test_reading_the_root_creates_nothing(self, tmp_path: Path) -> None:
        """A getter with a side effect leaves empty directories behind."""
        with patch.dict(os.environ, {"XDG_PICTURES_DIR": str(tmp_path / "Pics")}, clear=False):
            root = host_uploads.upload_root()

        assert not root.exists()

    def test_an_unreadable_xdg_config_falls_back_rather_than_raising(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Most machines have no usable XDG config; that is the normal case, not an error."""
        config = tmp_path / ".config"
        config.mkdir()
        (config / "user-dirs.dirs").write_bytes(b"\xff\xfe\xfa not utf-8")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.delenv("XDG_PICTURES_DIR", raising=False)

        assert host_uploads.upload_root() == tmp_path / "Pictures" / "BAUD"


@fastapi_required
class TestTheUploadRouteIsGuardedLikeEveryOtherWrite:
    """Scope, method and availability, read off a real app."""

    def test_the_route_is_registered_as_a_post(self) -> None:
        """One door, one method."""
        app = host_server.create_app()
        methods = [sorted(route.methods) for route in app.routes if getattr(route, "path", "") == "/v1/files/upload"]

        assert methods == [["POST"]]

    def test_it_is_not_reachable_by_get(self, store: Any) -> None:
        """A write must not be a link somebody can follow."""
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")

        with patch(PATCH_SERVER_JSON), patch(PATCH_SERVER_LOGGER):
            client = TestClient(host_server.create_app())
            response = client.get("/v1/files/upload", headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 405

    @multipart_required
    def test_a_read_token_cannot_upload(self, store: Any, landing: Path) -> None:
        """It writes to disk, so it is operate."""
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="read")

        with patch(PATCH_SERVER_JSON), patch(PATCH_SERVER_LOGGER):
            client = TestClient(host_server.create_app())
            response = client.post(
                "/v1/files/upload",
                files={"image": ("x.png", BytesIO(PNG), "image/png")},
                headers={"Authorization": f"Bearer {raw}"},
            )

        assert response.status_code == 403
        assert not landing.exists()

    @multipart_required
    def test_an_unauthenticated_upload_is_refused(self, store: Any, landing: Path) -> None:
        """No token, no write."""
        from fastapi.testclient import TestClient

        with patch(PATCH_SERVER_JSON), patch(PATCH_SERVER_LOGGER):
            client = TestClient(host_server.create_app())
            response = client.post("/v1/files/upload", files={"image": ("x.png", BytesIO(PNG), "image/png")})

        assert response.status_code in (401, 403)
        assert not landing.exists()

    @multipart_required
    def test_a_refused_upload_is_a_400_carrying_the_reason(self, store: Any, landing: Path) -> None:
        """The caller's fault, named as theirs — the phone renders the sentence."""
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")

        with patch(PATCH_SERVER_JSON), patch(PATCH_SERVER_LOGGER):
            client = TestClient(host_server.create_app())
            response = client.post(
                "/v1/files/upload",
                files={"image": ("x.png", BytesIO(b"#!/bin/sh"), "image/png")},
                headers={"Authorization": f"Bearer {raw}"},
            )

        assert response.status_code == 400
        assert "not an image" in response.text.lower()

    @multipart_required
    def test_a_server_side_failure_is_a_503(self, store: Any, landing: Path) -> None:
        """Ours, not theirs — the same 400/503 split as every other lane."""
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")

        with patch(PATCH_SERVER_JSON), patch(PATCH_SERVER_LOGGER):
            with patch.object(host_uploads, "store_image", side_effect=host_uploads.UploadUnavailable("disk full")):
                client = TestClient(host_server.create_app())
                response = client.post(
                    "/v1/files/upload",
                    files={"image": ("x.png", BytesIO(PNG), "image/png")},
                    headers={"Authorization": f"Bearer {raw}"},
                )

        assert response.status_code == 503

    def test_a_missing_multipart_library_answers_503_not_404(self, store: Any) -> None:
        """
        FastAPI raises at ROUTE-REGISTRATION time for a form route without python-multipart,
        so the route is guarded; registered anyway, because a 404 reads as "wrong URL".
        """
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")

        with patch(PATCH_SERVER_JSON), patch(PATCH_SERVER_LOGGER):
            with patch.object(host_server, "MULTIPART_AVAILABLE", False):
                app = host_server.create_app()
                response = TestClient(app).post("/v1/files/upload", headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 503
        assert "python-multipart" in response.text

    @staticmethod
    def _declared(part_headers: dict) -> tuple:
        """
        Upload PNG with `part_headers` on the image part; the status and the length store_image was handed.
        """
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")

        with patch(PATCH_SERVER_JSON), patch(PATCH_SERVER_LOGGER):
            with patch.object(host_uploads, "store_image", wraps=host_uploads.store_image) as stored:
                response = TestClient(host_server.create_app()).post(
                    "/v1/files/upload",
                    files={"image": ("x.png", BytesIO(PNG), "image/png", part_headers)},
                    headers={"Authorization": f"Bearer {raw}"},
                )

        return response.status_code, stored.call_args.args[1]

    @multipart_required
    def test_the_declared_length_reader_never_raises_on_a_bad_header(self, store: Any, landing: Path) -> None:
        """A malformed Content-Length falls through to None and the running total; never a 500."""
        assert self._declared({"content-length": "not-a-number"}) == (200, None)

    @multipart_required
    def test_a_missing_length_header_is_not_an_error(self, store: Any, landing: Path) -> None:
        """A chunked upload has no Content-Length, and that is normal."""
        assert self._declared({}) == (200, None)

    @multipart_required
    def test_a_declared_length_is_handed_on_as_a_number(self, store: Any, landing: Path) -> None:
        """The floor under the two above: a reader that always answered None would pass both."""
        assert self._declared({"content-length": str(len(PNG))}) == (200, len(PNG))


@fastapi_required
class TestValidationErrorsUseTheDocumentedEnvelope:
    """
    @baud's finding, 2026-08-14 23:57, from the owner's first real photo.

    Validation fires in front of every handler; it must answer `{"error": ...}`, not FastAPI's `{"detail": [...]}`.
    """

    @multipart_required
    def test_the_wrong_field_name_names_the_field(self, store: Any, landing: Path) -> None:
        """The client sent `file`, the server wants `image`; the phone's sentence must say so."""
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")

        with patch(PATCH_SERVER_JSON), patch(PATCH_SERVER_LOGGER):
            client = TestClient(host_server.create_app())
            response = client.post(
                "/v1/files/upload",
                files={"file": ("x.png", BytesIO(PNG), "image/png")},
                headers={"Authorization": f"Bearer {raw}"},
            )

        assert response.status_code == 422

        body = response.json()
        assert body["error"]["code"] == "invalid_request"
        assert body["error"]["message"] == "image: Field required"

    def test_a_missing_query_parameter_gets_the_same_envelope(self, store: Any) -> None:
        """
        Every route, not just the one that was hit: the fix is in the layer.

        `file`, not `branch`: a missing branch is the fence's 400 (test_host_roots.py).
        """
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="read")

        with patch(PATCH_SERVER_JSON), patch(PATCH_SERVER_LOGGER):
            client = TestClient(host_server.create_app())
            response = client.get("/v1/files", headers={"Authorization": f"Bearer {raw}"})

        body = response.json()
        assert response.status_code == 422
        assert body["error"]["code"] == "invalid_request"
        assert "file" in body["error"]["message"]

    def test_the_raw_detail_shape_is_gone(self, store: Any) -> None:
        """A top-level `detail` beside the envelope would keep two contracts alive."""
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="read")

        with patch(PATCH_SERVER_JSON), patch(PATCH_SERVER_LOGGER):
            client = TestClient(host_server.create_app())
            body = client.get("/v1/files", headers={"Authorization": f"Bearer {raw}"}).json()

        assert "detail" not in body
        assert set(body) == {"error"}

    def test_the_structured_original_is_kept_beside_the_sentence(self, store: Any) -> None:
        """`fields` carries the loc/msg pairs: a client that wanted the structure still has it."""
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="read")

        with patch(PATCH_SERVER_JSON), patch(PATCH_SERVER_LOGGER):
            client = TestClient(host_server.create_app())
            body = client.get("/v1/files", headers={"Authorization": f"Bearer {raw}"}).json()

        locations = [field["loc"] for field in body["error"]["fields"]]
        assert ["query", "file"] in locations

    def test_the_message_is_never_empty(self) -> None:
        """
        A 422 whose message is a blank string is the same failure, one layer further in.

        By name: FastAPI never raises with an empty list, so no request reaches this input.
        """
        assert host_server._validation_sentence([]) != ""


@fastapi_required
@multipart_required
class TestTheEndToEndPathIsUsable:
    """
    The whole point, proven once: bytes in, a real path out, a real file there.
    """

    def test_an_uploaded_screenshot_lands_readable_at_the_returned_path(self, store: Any, landing: Path) -> None:
        """A phone posts a PNG; the path in the response holds those bytes."""
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")
        payload = PNG + os.urandom(4096)

        with patch(PATCH_SERVER_JSON), patch(PATCH_SERVER_LOGGER):
            client = TestClient(host_server.create_app())
            response = client.post(
                "/v1/files/upload",
                files={"image": ("IMG_20260814_231500.jpg", BytesIO(payload), "image/jpeg")},
                headers={"Authorization": f"Bearer {raw}"},
            )

        assert response.status_code == 200

        body = response.json()
        stored = Path(body["path"])

        assert stored.read_bytes() == payload
        assert body["bytes"] == len(payload)
        # Declared jpeg, sniffed png: the extension follows the bytes.
        assert body["type"] == "png"
        assert stored.suffix == ".png"
