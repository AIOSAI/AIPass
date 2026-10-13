# =================== AIPass ====================
# Name: test_baud.py
# Description: Tests for aipass baud's command line: each value flag reaches the function it feeds
# Version: 1.3.0
# Created: 2026-10-08
# Modified: 2026-10-13
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


_RECEIPT = "~/.secrets/aipass/host_api/<label>.token"


def _ready(host: str = "127.0.0.1", tailnet: str = _TAILNET_IP, server: str = "serving") -> baud.PhoneReady:
    return baud.PhoneReady(api=True, host=host, port=8787, tailnet=tailnet, server=server, receipt=_RECEIPT)


class TestPrintPhoneReady:
    """An @api without the installer doors (slice B's print): the commands that do it by hand."""

    def test_the_print_gives_the_url_the_token_command_its_receipt_the_sign_in_and_the_guide(self, capsys):
        baud.print_phone_ready(_ready())
        out, err = capsys.readouterr()
        assert f"Phone URL:  http://{_TAILNET_IP}:8787/" in out
        assert "drone @api host-api issue-token <label> --scope operate" in out
        assert f"its 0600 receipt lands at {_RECEIPT}" in out
        assert "paste the token on the sign-in page" in out
        assert "https://github.com/AIOSAI/baud/blob/main/docs/phone-setup-android.md" in out
        assert "Tailscale is" not in err

    def test_a_loopback_bind_names_the_command_that_moves_it_to_the_tailnet(self, capsys):
        baud.print_phone_ready(_ready())
        out, _err = capsys.readouterr()
        assert f"drone @api host-api set-config --host {_TAILNET_IP} --port 8787" in out

    def test_no_receipt_door_states_no_path(self, capsys):
        """Mutant: the receipt line printed whatever ready.receipt holds -> an empty path -> red."""
        baud.print_phone_ready(baud.PhoneReady(True, "127.0.0.1", 8787, _TAILNET_IP, "serving"))
        out, _err = capsys.readouterr()
        assert "its 0600 receipt path is printed when it is issued" in out
        assert "receipt lands at" not in out

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

    def test_a_dry_run_without_the_doors_names_the_commands_and_gives_no_url(self, capsys):
        baud.print_phone_ready(_ready(tailnet="absent", server="unprobed"), dry_run=True)
        out, _err = capsys.readouterr()
        assert "would read this host's tailnet address: tailscale ip -4" in out
        assert "would move @api's bind (now 127.0.0.1:8787) to the tailnet address, when tailscale is up" in out
        assert "would name the boot unit's commands: drone @api host-api serve --detach" in out
        assert "would ask the server on that bind whether it answers (GET /, no token)" in out
        assert "Phone URL" not in out


class _Refused(Exception):
    pass


class _Unsupported(Exception):
    pass


class _Unreachable(Exception):
    pass


def _steps(*names: str, ok: object = True) -> dict:
    return {"dry_run": ok is None, "ok": ok is not False, "steps": [{"step": n, "ok": ok, "detail": ""} for n in names]}


class _ApiDoor(_ApiStore):
    """@api's host module door with slice C's installer doors; each call is recorded, none touches systemd."""

    BindRefused = _Refused
    AutostartUnsupported = _Unsupported
    SupervisorUnreachable = _Unreachable
    LifetimeError = _Unreachable

    def __init__(self, host: str = "127.0.0.1", **answers: object) -> None:
        super().__init__(host=host)
        self.calls: list[tuple] = []
        self.answers = answers

    def _answer(self, name: str, default: dict) -> dict:
        answer = self.answers.get(name, default)
        if isinstance(answer, BaseException):
            raise answer
        assert isinstance(answer, dict)
        return answer

    def set_bind(self, host: str, port: int) -> dict:
        self.calls.append(("set_bind", host, port))
        return self._answer("set_bind", {"host": host, "port": port, "changed": True, "previous": {}})

    def autostart(self) -> dict:
        self.calls.append(("autostart",))
        return self._answer("autostart", {"unit": "/u/aipass-host.service", "rendered": True, "running": 0})

    def install_unit(self, dry_run: bool = False) -> dict:
        self.calls.append(("install_unit", dry_run))
        names = ("mkdir -p ~/.config/systemd/user", "cp unit", "systemctl --user daemon-reload")
        return self._answer("install_unit", _steps(*names, ok=None if dry_run else True))

    def enable_unit(self, dry_run: bool = False) -> dict:
        self.calls.append(("enable_unit", dry_run))
        return self._answer("enable_unit", _steps("systemctl --user enable --now unit", ok=None if dry_run else True))

    def receipt_path(self, label: str) -> Path:
        return Path.home() / ".secrets" / "aipass" / "host_api" / f"{label}.token"

    def issue_token(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("the install minted a token")


@pytest.fixture
def probes(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """The re-probe after the boot unit, at the network edge: records (host, port), answers serving."""
    seen: list[tuple] = []
    monkeypatch.setattr(baud, "server_answers", lambda host, port: seen.append((host, port)) or "serving")
    return seen


class TestFinishPhone:
    def test_a_loopback_bind_is_moved_to_the_tailnet_and_the_server_asked_there_once(self, capsys, probes):
        door = _ApiDoor()
        baud.finish_phone(_ready(server="silent"), host_config=door)
        out, _err = capsys.readouterr()
        assert door.calls[0] == ("set_bind", _TAILNET_IP, 8787)
        assert f"Bind:       moved to {_TAILNET_IP}:8787 (was 127.0.0.1:8787)" in out
        assert probes == [(_TAILNET_IP, 8787)]
        assert "Server:     answering, serving the face" in out
        assert "set-config" not in out

    def test_a_tailnet_bind_is_kept_and_set_bind_never_called(self, capsys, probes):
        door = _ApiDoor(host=_TAILNET_IP)
        baud.finish_phone(_ready(host=_TAILNET_IP), host_config=door)
        out, _err = capsys.readouterr()
        assert "set_bind" not in [c[0] for c in door.calls]
        assert f"kept {_TAILNET_IP}:8787, already a tailnet address" in out

    def test_a_refused_bind_prints_apis_words_and_the_set_config_line(self, capsys, probes):
        door = _ApiDoor(set_bind=_Refused("100.101.102.103 is not an address on this host"))
        baud.finish_phone(_ready(), host_config=door)
        out, _err = capsys.readouterr()
        assert "@api refused 100.101.102.103: 100.101.102.103 is not an address on this host" in out
        assert f"drone @api host-api set-config --host {_TAILNET_IP} --port 8787" in out
        assert probes == [("127.0.0.1", 8787)]

    def test_the_boot_doors_run_in_order_and_each_step_gets_a_line(self, capsys, probes):
        door = _ApiDoor()
        baud.finish_phone(_ready(), host_config=door)
        out, _err = capsys.readouterr()
        assert [c[0] for c in door.calls] == ["set_bind", "autostart", "install_unit", "enable_unit"]
        assert ("install_unit", False) in door.calls and ("enable_unit", False) in door.calls
        assert "Boot unit:  installed and enabled" in out
        assert "ok      systemctl --user daemon-reload" in out
        assert "ok      systemctl --user enable --now unit" in out

    def test_a_unit_systemd_already_runs_is_left_alone(self, capsys, probes):
        door = _ApiDoor(host=_TAILNET_IP, autostart={"unit": "/u/x.service", "rendered": False, "running": 4242})
        baud.finish_phone(_ready(host=_TAILNET_IP), host_config=door)
        out, _err = capsys.readouterr()
        assert [c[0] for c in door.calls] == ["autostart"]
        assert "Boot unit:  left alone, systemd already runs it (pid 4242)" in out

    def test_a_failed_install_step_says_why_and_never_enables(self, capsys, probes):
        failed = {"dry_run": False, "ok": False, "steps": [{"step": "cp unit", "ok": False, "detail": "denied"}]}
        door = _ApiDoor(install_unit=failed)
        baud.finish_phone(_ready(), host_config=door)
        out, _err = capsys.readouterr()
        assert "enable_unit" not in [c[0] for c in door.calls]
        assert "failed  cp unit: denied" in out
        assert "at every boot: drone @api host-api autostart" in out

    def test_an_enable_refused_over_a_hand_started_server_prints_the_sentence_and_the_stop(self, capsys, probes):
        refused = "A hand-started server holds the port (pid 5150); stop it first: drone @api host-api stop"
        door = _ApiDoor(enable_unit={"dry_run": False, "ok": False, "steps": [], "refused": refused})
        baud.finish_phone(_ready(), host_config=door)
        out, _err = capsys.readouterr()
        assert f"Boot unit:  not enabled. {refused}" in out
        assert "Stop it: drone @api host-api stop" in out

    def test_no_systemd_says_so_once_and_names_serve_detach(self, capsys, probes):
        door = _ApiDoor(install_unit=_Unsupported("Autostart needs a user-level systemd"))
        baud.finish_phone(_ready(server="silent"), host_config=door)
        out, _err = capsys.readouterr()
        assert "Boot unit:  none here (Autostart needs a user-level systemd)" in out
        assert "Start it: drone @api host-api serve --detach" in out
        assert "host-api autostart" not in out

    def test_an_unreachable_supervisor_prints_its_message_and_both_manual_commands(self, capsys, probes):
        door = _ApiDoor(autostart=_Unreachable("systemctl --user did not answer"))
        baud.finish_phone(_ready(), host_config=door)
        out, _err = capsys.readouterr()
        assert "Boot unit:  not set up: systemctl --user did not answer" in out
        assert "Start it: drone @api host-api serve --detach" in out
        assert "at every boot: drone @api host-api autostart" in out

    def test_a_dry_run_plans_the_unit_steps_and_neither_moves_the_bind_nor_renders(self, capsys, probes):
        door = _ApiDoor()
        baud.finish_phone(_ready(server="unprobed"), dry_run=True, host_config=door)
        out, _err = capsys.readouterr()
        assert door.calls == [("install_unit", True), ("enable_unit", True)]
        assert probes == []
        assert "would move @api's bind (now 127.0.0.1:8787) to the tailnet address, when tailscale is up" in out
        assert "would render the boot unit (autostart), unless systemd already runs it" in out
        assert "would run: systemctl --user daemon-reload" in out
        assert "would run: systemctl --user enable --now unit" in out

    def test_a_dry_run_on_a_tailnet_bind_says_it_is_kept(self, capsys, probes):
        """Mutant: the dry run always promises a move -> red."""
        baud.finish_phone(_ready(host=_TAILNET_IP, tailnet="absent"), dry_run=True, host_config=_ApiDoor())
        out, _err = capsys.readouterr()
        assert f"would keep @api's bind (now {_TAILNET_IP}:8787), already a tailnet address" in out
        assert "would move" not in out

    def test_the_receipt_line_comes_from_apis_receipt_path(self, closed_port):
        door = _ApiDoor()
        door.port = closed_port
        assert baud.phone_readiness(dry_run=True, host_config=door).receipt == _RECEIPT


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
