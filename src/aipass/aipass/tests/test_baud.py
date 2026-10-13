# =================== AIPass ====================
# Name: test_baud.py
# Description: Tests for aipass baud's command line: each value flag reaches the function it feeds
# Version: 1.2.0
# Created: 2026-10-08
# Modified: 2026-10-12
# =============================================

"""Tests for apps/modules/baud.py: the install and status flags as a user types them, and the phone print."""
# install_phone_face and show_status are replaced by recorders where baud.py reads
# them, so each flag's value is seen arriving as its keyword; the fetch, verify and
# unpack behind them never run. handle_command ends in sys.exit, so every call is
# read through the SystemExit it raises.
# The phone print (FPLAN-0642 slice B): @api is a fake store with load_config, the
# module door's shape; tailscale is a fake script alone on PATH; the server is a real
# http.server on 127.0.0.1. No real install, no real @api config, no token minted.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every module this file imports parses and imports

import http.server
import os
import socket
import stat
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from aipass.aipass.apps.modules import baud
from aipass.aipass.apps.modules.install import handle_command as install_command

_TAILNET_IP = "100.101.102.103"
_POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="the fake tailscale is a POSIX shell script")


class _Recorder:
    """Stands where baud.py reads a function, keeps each call's keywords, answers 0."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, **kwargs: object) -> int:
        self.calls.append(kwargs)
        return 0


@pytest.fixture
def installs(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    recorder = _Recorder()
    monkeypatch.setattr(baud, "install_phone_face", recorder)
    return recorder


def _exit_code(args: list[str]) -> object:
    """Run `aipass baud <args>` and answer the code it exits with."""
    with pytest.raises(SystemExit) as exited:
        baud.handle_command("baud", args)
    return exited.value.code


class TestInstallFlags:
    def test_tag_reaches_the_install_as_its_tag(self, installs):
        assert _exit_code(["install", "--tag", "v0.2.1"]) == 0
        assert [call["tag"] for call in installs.calls] == ["v0.2.1"]

    def test_from_reaches_the_install_as_its_from_path(self, installs, tmp_path):
        tarball = str(tmp_path / "baud-phone-v0.2.1.tar.gz")
        assert _exit_code(["install", "--from", tarball]) == 0
        assert [call["from_path"] for call in installs.calls] == [tarball]

    def test_sums_reaches_the_install_as_its_sums_path(self, installs, tmp_path):
        tarball = str(tmp_path / "baud-phone-v0.2.1.tar.gz")
        sums = str(tmp_path / "SHA256SUMS.txt")
        assert _exit_code(["install", "--from", tarball, "--sums", sums]) == 0
        assert [call["sums_path"] for call in installs.calls] == [sums]

    def test_binary_reaches_the_install_as_its_binary_path(self, installs, tmp_path):
        tarball = str(tmp_path / "baud-phone-v0.2.1.tar.gz")
        binary = str(tmp_path / "baud-cli-v0.2.1-linux-x86_64")
        assert _exit_code(["install", "--from", tarball, "--binary", binary]) == 0
        assert [call["binary_path"] for call in installs.calls] == [binary]

    def test_dest_reaches_the_install_as_its_dest(self, installs, tmp_path):
        dest = str(tmp_path / "phone")
        assert _exit_code(["install", "--dest", dest]) == 0
        assert [call["dest"] for call in installs.calls] == [dest]


class TestStatusDest:
    def test_dest_reaches_the_status_as_its_dest(self, monkeypatch, tmp_path):
        statuses = _Recorder()
        monkeypatch.setattr(baud, "show_status", statuses)
        dest = str(tmp_path / "phone")
        assert _exit_code(["status", "--dest", dest]) == 0
        assert statuses.calls == [{"dest": dest}]


class TestFromOnlyRule:
    @pytest.mark.parametrize("flag", ["--sums", "--binary"])
    def test_a_from_only_flag_without_from_answers_2_and_installs_nothing(self, installs, capsys, tmp_path, flag):
        assert _exit_code(["install", flag, str(tmp_path / "given")]) == 2
        _out, err = capsys.readouterr()
        assert f"{flag} goes with --from" in err
        assert installs.calls == []


class TestInstallBestEffort:
    def test_a_crashing_face_install_warns_prints_the_retry_hint_and_answers_false(self, monkeypatch, capsys):
        def crash(**_kwargs: object) -> int:
            raise RuntimeError("boom")

        monkeypatch.setattr(baud, "install_phone_face", crash)
        assert baud.install_best_effort() is False
        out, err = capsys.readouterr()
        assert "boom" in err
        assert baud.RETRY_HINT in out

    def test_a_pointed_face_install_answers_true_without_the_hint(self, installs, capsys):
        assert baud.install_best_effort(dry_run=True) is True
        assert installs.calls == [{"tag": "latest", "dry_run": True, "best_effort": True}]
        out, _err = capsys.readouterr()
        assert baud.RETRY_HINT not in out

    def test_the_install_tag_reaches_the_face_install(self, installs):
        """aipass install --baud-tag lands here as tag (FPLAN-0642 slice B). Mutant: tag not passed on -> red."""
        baud.install_best_effort(tag="v0.2.1")
        assert installs.calls == [{"tag": "v0.2.1", "dry_run": False, "best_effort": True}]


class _ApiStore:
    """@api's host module door as baud reads it: load_config, nothing else."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8787, broken: bool = False) -> None:
        self.host, self.port, self.broken = host, port, broken

    def load_config(self) -> dict:
        if self.broken:
            raise OSError("host_api.json unreadable")
        return {"host": self.host, "port": self.port}


class _Face(http.server.BaseHTTPRequestHandler):
    status = 200

    def _get(self) -> None:
        self.send_response(self.status)
        self.end_headers()
        self.wfile.write(b"<html>face</html>")

    do_GET = _get  # the name http.server dispatches a GET to

    def log_message(self, format: str, *args: object) -> None:
        return


def _serve(status: int) -> Iterator[int]:
    handler = type("Face", (_Face,), {"status": status})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def face_server() -> Iterator[int]:
    yield from _serve(200)


@pytest.fixture
def error_server() -> Iterator[int]:
    yield from _serve(503)


@pytest.fixture
def closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def tailscale(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A fake tailscale alone on PATH: (set its answer, the file each run appends its argv to)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    runs = tmp_path / "tailscale_runs"
    monkeypatch.setenv("PATH", str(bin_dir))

    def answer(stdout: str, code: int = 0) -> None:
        script = bin_dir / "tailscale"
        script.write_text(f'#!/bin/sh\necho "$@" >> "{runs}"\nprintf "{stdout}"\nexit {code}\n', encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)

    return answer, runs


class TestPhoneReadiness:
    @_POSIX_ONLY
    def test_a_dry_run_reads_the_bind_and_runs_no_tailscale_and_no_probe(self, tailscale, face_server):
        answer, runs = tailscale
        answer(_TAILNET_IP)
        ready = baud.phone_readiness(dry_run=True, host_config=_ApiStore(port=face_server))
        assert (ready.api, ready.host, ready.port) == (True, "127.0.0.1", face_server)
        assert (ready.tailnet, ready.server) == ("absent", "unprobed")
        assert not runs.exists()

    @_POSIX_ONLY
    def test_tailscale_up_and_a_serving_face_are_read_as_such(self, tailscale, face_server):
        answer, runs = tailscale
        answer(f"{_TAILNET_IP}\\n")
        ready = baud.phone_readiness(host_config=_ApiStore(port=face_server))
        assert (ready.tailnet, ready.server) == (_TAILNET_IP, "serving")
        assert runs.read_text(encoding="utf-8").split() == ["ip", "-4"]

    @_POSIX_ONLY
    def test_tailscale_with_no_tailnet_address_is_down_not_an_address(self, tailscale, closed_port):
        answer, _runs = tailscale
        answer("", code=1)
        assert baud.phone_readiness(host_config=_ApiStore(port=closed_port)).tailnet == "down"
        answer("192.168.1.20")
        assert baud.phone_readiness(host_config=_ApiStore(port=closed_port)).tailnet == "down"

    def test_no_tailscale_on_path_is_absent(self, tmp_path, monkeypatch, closed_port):
        monkeypatch.setenv("PATH", str(tmp_path))
        assert baud.phone_readiness(host_config=_ApiStore(port=closed_port)).tailnet == "absent"

    def test_an_error_status_is_up_but_not_serving_and_a_closed_port_is_silent(self, error_server, closed_port):
        assert baud.phone_readiness(host_config=_ApiStore(port=error_server)).server == "answering"
        assert baud.phone_readiness(host_config=_ApiStore(port=closed_port)).server == "silent"

    def test_an_unreadable_api_config_is_no_api_not_a_loopback_bind(self):
        assert baud.phone_readiness(host_config=_ApiStore(broken=True)).api is False
        assert baud.phone_readiness(host_config=object()).api is False


def _ready(host: str = "127.0.0.1", tailnet: str = _TAILNET_IP, server: str = "serving") -> baud.PhoneReady:
    return baud.PhoneReady(api=True, host=host, port=8787, tailnet=tailnet, server=server)


class TestPrintPhoneReady:
    def test_the_print_gives_the_url_the_token_command_its_receipt_the_sign_in_and_the_guide(self, capsys):
        baud.print_phone_ready(_ready())
        out, err = capsys.readouterr()
        assert f"Phone URL:  http://{_TAILNET_IP}:8787/" in out
        assert "drone @api host-api issue-token <label> --scope operate" in out
        assert "~/.secrets/aipass/host_api/<label>.token" in out
        assert "paste the token on the sign-in page" in out
        assert "https://github.com/AIOSAI/baud/blob/main/docs/phone-setup-android.md" in out
        assert "Tailscale is" not in err

    def test_a_loopback_bind_names_the_command_that_moves_it_to_the_tailnet(self, capsys):
        baud.print_phone_ready(_ready())
        out, _err = capsys.readouterr()
        assert f"drone @api host-api set-config --host {_TAILNET_IP} --port 8787" in out

    def test_a_bind_already_on_the_tailnet_is_kept_and_said_so(self, capsys):
        baud.print_phone_ready(_ready(host=_TAILNET_IP))
        out, _err = capsys.readouterr()
        assert f"kept {_TAILNET_IP}:8787, already a tailnet address" in out
        assert "set-config" not in out

    def test_without_tailscale_the_url_is_loopback_and_the_install_line_is_given(self, capsys):
        baud.print_phone_ready(_ready(tailnet="absent"))
        out, err = capsys.readouterr()
        assert "Phone URL:  http://127.0.0.1:8787/" in out
        assert "Tailscale is absent here: the phone URL works on this machine only until it is up" in err
        assert "curl -fsSL https://tailscale.com/install.sh | sh" in out
        assert "set-config" not in out

    def test_a_silent_server_names_serve_and_the_boot_unit(self, capsys):
        baud.print_phone_ready(_ready(server="silent"))
        out, _err = capsys.readouterr()
        assert "drone @api host-api serve --detach" in out
        assert "drone @api host-api autostart" in out
        assert "serving the face" not in out

    def test_a_dry_run_says_what_it_would_do_and_gives_no_url(self, capsys):
        baud.print_phone_ready(_ready(tailnet="absent", server="unprobed"), dry_run=True)
        out, _err = capsys.readouterr()
        assert "would read this host's tailnet address: tailscale ip -4" in out
        assert "would check @api's bind (now 127.0.0.1:8787)" in out
        assert "would ask the server on that bind whether it answers (GET /, no token)" in out
        assert "Phone URL" not in out

    def test_a_dry_run_on_a_tailnet_bind_says_it_is_kept(self, capsys):
        """Mutant: the dry run always promises a move command -> red."""
        baud.print_phone_ready(_ready(host=_TAILNET_IP, tailnet="absent", server="unprobed"), dry_run=True)
        out, _err = capsys.readouterr()
        assert f"would keep @api's bind (now {_TAILNET_IP}:8787), already a tailnet address" in out
        assert "moves it" not in out


class TestInstallEndsOnThePhone:
    @_POSIX_ONLY
    def test_a_dry_run_install_passes_the_tag_and_ends_on_the_phone_lines(
        self, tmp_path, monkeypatch, capsys, tailscale
    ):
        """--baud-tag reaches baud's install as tag; on --no-chat the phone's dry-run lines are the last print."""
        answer, runs = tailscale
        answer(_TAILNET_IP)
        installs: list[dict] = []
        monkeypatch.setattr(baud, "install_phone_face", lambda **kw: installs.append(kw) or 0)
        monkeypatch.setattr(baud, "_api_host_config", lambda: _ApiStore())
        args = ["--dry-run", "--no-chat", "--non-interactive", "--path", str(tmp_path / "AIPass")]
        args += ["--baud-tag", "v0.2.1", "--force-global-home"]
        # tmp_path is a throwaway home; install reads its override from sys.argv, as a user types it.
        monkeypatch.setattr(sys, "argv", ["aipass", "install", *args])
        with pytest.raises(SystemExit) as exc:
            install_command("install", args)
        assert exc.value.code == 0
        assert installs == [{"tag": "v0.2.1", "dry_run": True, "best_effort": True}]
        out = capsys.readouterr().out.rstrip()
        assert out.endswith("would print the phone URL, the token command, the sign-in note and the guide")
        assert not runs.exists()
        assert not (tmp_path / "AIPass").exists()
