# =================== AIPass ====================
# Name: test_sandbox_check.py
# Description: Tests for sandbox prerequisite checker and doctor integration
# Version: 1.1.2
# Created: 2026-06-10
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/sandbox_check/sandbox_checker.py and the doctor integration it drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every module this file imports parses and imports

import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest  # pyright: ignore[reportMissingImports]

from aipass.aipass.apps.handlers.sandbox_check import sandbox_checker
from aipass.aipass.apps.handlers.sandbox_check.sandbox_checker import (
    check_broker_alive,
    check_bwrap_functional,
    check_bwrap_present,
    check_node_present,
    check_rg_present,
    check_sandbox_flag,
    check_srt_resolvable,
    is_linux,
)
from aipass.aipass.apps.handlers.ui.progress import GLYPH_FAIL, GLYPH_PASS, GLYPH_WARN
from aipass.aipass.apps.modules.doctor import _check_sandbox


# =============================================================================
# Fixtures
# =============================================================================


def _path_with(monkeypatch, tmp_path: Path, *names: str) -> dict[str, str]:
    """PATH holds only a tmp bin dir with these executables; returns name -> path shutil.which will answer."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    found = {}
    for name in names:
        exe = bin_dir / (name + (".exe" if os.name == "nt" else ""))
        exe.write_text("", encoding="utf-8")
        exe.chmod(0o755)
        found[name] = str(exe)
    monkeypatch.setenv("PATH", str(bin_dir))
    return found


@pytest.fixture(autouse=True)
def _stub_json_handler():
    """Suppress json_handler.log_operation side effects in all tests."""
    with patch("aipass.aipass.apps.handlers.sandbox_check.sandbox_checker.json_handler", autospec=True) as mock:
        mock.log_operation = MagicMock()
        yield mock


# =============================================================================
# check_sandbox_flag
# =============================================================================


class TestCheckSandboxFlag:
    def test_flag_off_by_default(self, monkeypatch):
        monkeypatch.delenv("AIPASS_SANDBOX_ENABLED", raising=False)
        result = check_sandbox_flag()
        assert result["enabled"] is False
        assert result["raw_value"] == ""

    def test_flag_on_with_1(self, monkeypatch):
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")
        result = check_sandbox_flag()
        assert result["enabled"] is True

    def test_flag_on_with_true(self, monkeypatch):
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "true")
        result = check_sandbox_flag()
        assert result["enabled"] is True

    def test_flag_on_with_yes(self, monkeypatch):
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "yes")
        result = check_sandbox_flag()
        assert result["enabled"] is True

    def test_flag_on_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "TRUE")
        result = check_sandbox_flag()
        assert result["enabled"] is True

    def test_flag_off_with_garbage(self, monkeypatch):
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "maybe")
        result = check_sandbox_flag()
        assert result["enabled"] is False


# =============================================================================
# check_bwrap_present
# =============================================================================


class TestCheckBwrapPresent:
    def test_bwrap_found(self, monkeypatch, tmp_path):
        """Mutant: `shutil.which("bwrap")` -> `shutil.which("bubblewrap")` reddens this test."""
        bins = _path_with(monkeypatch, tmp_path, "bwrap")
        result = check_bwrap_present()
        assert result["found"] is True
        assert result["path"] == bins["bwrap"]

    def test_bwrap_not_found(self, monkeypatch, tmp_path):
        _path_with(monkeypatch, tmp_path, "node")
        result = check_bwrap_present()
        assert result["found"] is False
        assert result["path"] is None

    @pytest.mark.skipif(not shutil.which("bwrap"), reason="bwrap not installed")
    def test_bwrap_live(self):
        result = check_bwrap_present()
        assert result["found"] is True
        assert "bwrap" in result["path"]


# =============================================================================
# check_bwrap_functional
# =============================================================================


class TestCheckBwrapFunctional:
    def test_bwrap_missing(self, monkeypatch, tmp_path):
        _path_with(monkeypatch, tmp_path)
        result = check_bwrap_functional()
        assert result["ok"] is False
        assert "not found" in result["detail"]

    def test_bwrap_succeeds(self, monkeypatch, tmp_path):
        """Mutant: argv `[bwrap, ...]` -> `["bwrap", ...]` reddens this test."""
        bins = _path_with(monkeypatch, tmp_path, "bwrap")
        mock_proc = MagicMock(returncode=0, stderr="")
        with patch(
            "aipass.aipass.apps.handlers.sandbox_check.sandbox_checker.subprocess.run",
            return_value=mock_proc,
        ) as mock_run:
            result = check_bwrap_functional()
        assert result["ok"] is True
        argv = mock_run.call_args[0][0]
        assert argv[0] == bins["bwrap"]
        assert "--ro-bind" in argv
        assert "true" in argv

    def test_bwrap_fails_reports_sysctl(self, monkeypatch, tmp_path):
        _path_with(monkeypatch, tmp_path, "bwrap")
        mock_proc = MagicMock(returncode=1, stderr="permission denied")
        with (
            patch(
                "aipass.aipass.apps.handlers.sandbox_check.sandbox_checker.subprocess.run",
                return_value=mock_proc,
            ),
            patch(
                "aipass.aipass.apps.handlers.sandbox_check.sandbox_checker._read_userns_sysctl",
                return_value="1",
            ),
        ):
            result = check_bwrap_functional()
        assert result["ok"] is False
        assert "exit 1" in result["detail"]
        assert result["sysctl_value"] == "1"

    def test_bwrap_timeout(self, monkeypatch, tmp_path):
        _path_with(monkeypatch, tmp_path, "bwrap")
        with patch(
            "aipass.aipass.apps.handlers.sandbox_check.sandbox_checker.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="bwrap", timeout=10),
        ):
            result = check_bwrap_functional()
        assert result["ok"] is False
        assert "timed out" in result["detail"]

    @pytest.mark.skipif(not shutil.which("bwrap"), reason="bwrap not installed")
    def test_bwrap_functional_live(self):
        """Mutant: bwrap exit code read inverted -> red."""
        bwrap = shutil.which("bwrap") or "bwrap"
        probe = [bwrap, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "true"]
        sandbox_works = subprocess.run(probe, capture_output=True, timeout=10, check=False).returncode == 0
        result = check_bwrap_functional()
        assert result["ok"] is sandbox_works
        if sandbox_works:
            assert result["detail"] == "trivial sandbox succeeded"


# =============================================================================
# check_node_present
# =============================================================================


class TestCheckNodePresent:
    def test_node_found(self, monkeypatch, tmp_path):
        """Mutant: `shutil.which("node")` -> `shutil.which("nodejs")` reddens this test."""
        bins = _path_with(monkeypatch, tmp_path, "node")
        result = check_node_present()
        assert result["found"] is True
        assert result["path"] == bins["node"]

    def test_node_not_found(self, monkeypatch, tmp_path):
        _path_with(monkeypatch, tmp_path, "bwrap")
        result = check_node_present()
        assert result["found"] is False

    @pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
    def test_node_live(self):
        result = check_node_present()
        assert result["found"] is True


# =============================================================================
# check_srt_resolvable
# =============================================================================


class TestCheckSrtResolvable:
    def test_no_node(self, monkeypatch, tmp_path):
        _path_with(monkeypatch, tmp_path, "bwrap")
        result = check_srt_resolvable()
        assert result["found"] is False
        assert "node" in result["install_hint"].lower()

    def test_srt_found(self, monkeypatch, tmp_path):
        """Mutant: argv `[node, ...]` -> `["node", ...]` reddens this test."""
        resolver = tmp_path / "_srt_resolve.mjs"
        resolver.touch()
        bins = _path_with(monkeypatch, tmp_path, "node")
        monkeypatch.setattr(
            "aipass.aipass.apps.handlers.sandbox_check.sandbox_checker._find_srt_resolver",
            lambda: resolver,
        )
        mock_proc = MagicMock(
            returncode=0,
            stdout="/usr/lib/node_modules/@anthropic-ai/sandbox-runtime/dist/index.js\n",
            stderr="",
        )
        with patch(
            "aipass.aipass.apps.handlers.sandbox_check.sandbox_checker.subprocess.run",
            return_value=mock_proc,
        ) as mock_run:
            result = check_srt_resolvable()
        assert result["found"] is True
        assert "sandbox-runtime" in result["path"]
        assert result["install_hint"] == ""
        argv = mock_run.call_args[0][0]
        assert argv[0] == bins["node"]
        assert argv[1] == str(resolver)
        assert argv[2] == "--resolve"

    def test_srt_not_found(self, monkeypatch, tmp_path):
        resolver = tmp_path / "_srt_resolve.mjs"
        resolver.touch()
        _path_with(monkeypatch, tmp_path, "node")
        monkeypatch.setattr(
            "aipass.aipass.apps.handlers.sandbox_check.sandbox_checker._find_srt_resolver",
            lambda: resolver,
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.handlers.sandbox_check.sandbox_checker._srt_install_hint",
            lambda: "npm install -g @anthropic-ai/sandbox-runtime",
        )
        mock_proc = MagicMock(returncode=1, stdout="", stderr="tried: /a\n/b")
        with patch(
            "aipass.aipass.apps.handlers.sandbox_check.sandbox_checker.subprocess.run",
            return_value=mock_proc,
        ):
            result = check_srt_resolvable()
        assert result["found"] is False
        assert "npm install" in result["install_hint"]

    def test_srt_timeout(self, monkeypatch, tmp_path):
        resolver = tmp_path / "_srt_resolve.mjs"
        resolver.touch()
        _path_with(monkeypatch, tmp_path, "node")
        monkeypatch.setattr(
            "aipass.aipass.apps.handlers.sandbox_check.sandbox_checker._find_srt_resolver",
            lambda: resolver,
        )
        with patch(
            "aipass.aipass.apps.handlers.sandbox_check.sandbox_checker.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="node", timeout=10),
        ):
            result = check_srt_resolvable()
        assert result["found"] is False

    def test_srt_resolver_missing_falls_back(self, monkeypatch, tmp_path):
        """When aipass.hooks isn't importable / resolver file is absent, fail gracefully."""
        _path_with(monkeypatch, tmp_path, "node")
        monkeypatch.setattr(
            "aipass.aipass.apps.handlers.sandbox_check.sandbox_checker._find_srt_resolver",
            lambda: None,
        )
        result = check_srt_resolvable()
        assert result["found"] is False
        assert result["path"] is None
        assert "npm install" in result["install_hint"]


# =============================================================================
# _find_srt_resolver
# =============================================================================


def _hooks_package_at(monkeypatch, location: Path | None) -> None:
    """find_spec("aipass.hooks") answers: None = not importable, else a package at *location*."""
    spec = None if location is None else MagicMock(submodule_search_locations=[str(location)])
    monkeypatch.setattr(sandbox_checker.importlib.util, "find_spec", lambda name: spec)


class TestFindSrtResolver:
    def test_resolves_real_hooks_branch(self, monkeypatch, tmp_path):
        """aipass.hooks is a real namespace package in this repo — resolver should be found.

        Mutant: resolver name `"_srt_resolve.mjs"` -> `"_srt_resolve.js"` reddens this test.
        """
        _path_with(monkeypatch, tmp_path, "node")
        mock_proc = MagicMock(returncode=0, stdout="/x/index.js\n", stderr="")
        with patch(
            "aipass.aipass.apps.handlers.sandbox_check.sandbox_checker.subprocess.run",
            return_value=mock_proc,
        ) as mock_run:
            result = check_srt_resolvable()
        resolver = Path(mock_run.call_args[0][0][1])
        assert result["found"] is True
        assert resolver.name == "_srt_resolve.mjs"
        assert resolver.is_file()

    def test_missing_spec_returns_none(self, monkeypatch, tmp_path):
        """Mutant: `if spec is None or not spec.submodule_search_locations:` -> `if False:` reddens this test."""
        _path_with(monkeypatch, tmp_path, "node")
        _hooks_package_at(monkeypatch, None)
        with patch("aipass.aipass.apps.handlers.sandbox_check.sandbox_checker.subprocess.run") as mock_run:
            result = check_srt_resolvable()
        assert mock_run.call_count == 0
        assert result["found"] is False

    def test_missing_file_returns_none(self, monkeypatch, tmp_path):
        """Mutant: `if not resolver.is_file():` -> `if False:` reddens this test."""
        _path_with(monkeypatch, tmp_path, "node")
        _hooks_package_at(monkeypatch, tmp_path)
        with patch("aipass.aipass.apps.handlers.sandbox_check.sandbox_checker.subprocess.run") as mock_run:
            result = check_srt_resolvable()
        assert mock_run.call_count == 0
        assert result["found"] is False


# =============================================================================
# the install hint check_srt_resolvable gives when srt is missing
# =============================================================================


class TestSrtInstallHint:
    def test_no_npm_falls_back_to_plain(self, monkeypatch, tmp_path):
        _path_with(monkeypatch, tmp_path, "node")
        _hooks_package_at(monkeypatch, None)
        hint = check_srt_resolvable()["install_hint"]
        assert hint == "npm install -g @anthropic-ai/sandbox-runtime"

    def test_npm_root_success_names_prefix(self, monkeypatch, tmp_path):
        """Mutant: `[npm, "root", "-g"]` -> `[npm, "root"]` reddens this test."""
        bins = _path_with(monkeypatch, tmp_path, "node", "npm")
        _hooks_package_at(monkeypatch, None)
        mock_proc = MagicMock(returncode=0, stdout="/usr/local/lib/node_modules\n", stderr="")
        with patch(
            "aipass.aipass.apps.handlers.sandbox_check.sandbox_checker.subprocess.run",
            return_value=mock_proc,
        ) as mock_run:
            hint = check_srt_resolvable()["install_hint"]
        assert mock_run.call_args[0][0] == [bins["npm"], "root", "-g"]
        assert "/usr/local/lib/node_modules" in hint
        assert "npm install -g @anthropic-ai/sandbox-runtime" in hint

    def test_npm_root_failure_falls_back_to_plain(self, monkeypatch, tmp_path):
        _path_with(monkeypatch, tmp_path, "node", "npm")
        _hooks_package_at(monkeypatch, None)
        with patch(
            "aipass.aipass.apps.handlers.sandbox_check.sandbox_checker.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="npm", timeout=5),
        ):
            hint = check_srt_resolvable()["install_hint"]
        assert hint == "npm install -g @anthropic-ai/sandbox-runtime"


# =============================================================================
# check_rg_present
# =============================================================================


class TestCheckRgPresent:
    def test_rg_on_path(self, monkeypatch, tmp_path):
        """Mutant: `shutil.which("rg")` -> `shutil.which("ripgrep")` reddens this test."""
        bins = _path_with(monkeypatch, tmp_path, "rg")
        result = check_rg_present()
        assert result["found"] is True
        assert result["path"] == bins["rg"]

    def test_rg_not_on_path_but_in_local_bin(self, monkeypatch, tmp_path):
        _path_with(monkeypatch, tmp_path)
        fake_rg = tmp_path / ".local" / "bin" / "rg"
        fake_rg.parent.mkdir(parents=True)
        fake_rg.touch()
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        result = check_rg_present()
        assert result["found"] is True
        assert str(fake_rg) == result["path"]

    def test_rg_not_found(self, monkeypatch, tmp_path):
        _path_with(monkeypatch, tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        result = check_rg_present()
        assert result["found"] is False

    @pytest.mark.skipif(not shutil.which("rg"), reason="rg not installed")
    def test_rg_live(self):
        result = check_rg_present()
        assert result["found"] is True


# =============================================================================
# check_broker_alive
# =============================================================================


class TestCheckBrokerAlive:
    def test_no_repo_root_no_env(self, monkeypatch, tmp_path):
        monkeypatch.delenv("AIPASS_HOME", raising=False)
        monkeypatch.chdir(tmp_path)
        result = check_broker_alive(repo_root=None)
        assert result["alive"] is False

    def test_socket_missing(self, tmp_path):
        ai_central = tmp_path / ".ai_central"
        ai_central.mkdir()
        result = check_broker_alive(repo_root=tmp_path)
        assert result["alive"] is False
        assert "missing" in result["detail"]

    @pytest.mark.skipif(sys.platform != "linux", reason="AF_UNIX broker sockets are Linux-only")
    def test_socket_connect_success(self, tmp_path):
        ai_central = tmp_path / ".ai_central"
        ai_central.mkdir()
        sock_path = ai_central / "drone_broker.sock"

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock_path))
        server.listen(1)
        try:
            result = check_broker_alive(repo_root=tmp_path)
            assert result["alive"] is True
            assert "connected" in result["detail"]
        finally:
            server.close()

    @pytest.mark.skipif(sys.platform != "linux", reason="AF_UNIX broker sockets are Linux-only")
    def test_socket_connect_refused(self, tmp_path):
        ai_central = tmp_path / ".ai_central"
        ai_central.mkdir()
        sock_path = ai_central / "drone_broker.sock"
        sock_path.touch()
        result = check_broker_alive(repo_root=tmp_path)
        assert result["alive"] is False
        assert "connect failed" in result["detail"]

    def test_repo_root_from_env(self, monkeypatch, tmp_path):
        ai_central = tmp_path / ".ai_central"
        ai_central.mkdir()
        monkeypatch.setenv("AIPASS_HOME", str(tmp_path))
        result = check_broker_alive(repo_root=None)
        assert result["alive"] is False
        assert "missing" in result["detail"]


# =============================================================================
# is_linux
# =============================================================================


class TestIsLinux:
    def test_linux(self, monkeypatch):
        monkeypatch.setattr("aipass.aipass.apps.handlers.sandbox_check.sandbox_checker.sys.platform", "linux")
        assert is_linux() is True

    def test_darwin(self, monkeypatch):
        monkeypatch.setattr("aipass.aipass.apps.handlers.sandbox_check.sandbox_checker.sys.platform", "darwin")
        assert is_linux() is False

    def test_win32(self, monkeypatch):
        monkeypatch.setattr("aipass.aipass.apps.handlers.sandbox_check.sandbox_checker.sys.platform", "win32")
        assert is_linux() is False


# =============================================================================
# _check_sandbox (doctor integration)
# =============================================================================


@pytest.fixture
def _stub_doctor_json():
    """Stub json_handler inside doctor.py too."""
    with patch("aipass.aipass.apps.modules.doctor.json_handler", autospec=True) as mock:
        mock.log_operation = MagicMock()
        yield mock


def _platform_is_linux(monkeypatch, answer: bool) -> list[str]:
    """doctor's is_linux answers *answer*; the returned list records each time doctor asked."""
    asked: list[str] = []

    def is_linux() -> bool:
        asked.append("is_linux")
        return answer

    monkeypatch.setattr("aipass.aipass.apps.modules.doctor.is_linux", is_linux)
    return asked


class TestCheckSandboxDoctor:
    """Mutants: doctor `if not is_linux():` -> `if not (is_linux() and is_linux()):` reddens the 7 Linux tests;
    -> `if not is_linux() and not is_linux():` reddens test_non_linux_one_info_line."""

    def test_non_linux_one_info_line(self, monkeypatch):
        asked = _platform_is_linux(monkeypatch, False)
        results = _check_sandbox()
        assert asked == ["is_linux"]
        assert len(results) == 1
        assert "Linux-only" in results[0].detail
        assert results[0].glyph == GLYPH_PASS

    def test_flag_off_missing_prereq_is_warn(self, monkeypatch):
        monkeypatch.delenv("AIPASS_SANDBOX_ENABLED", raising=False)
        asked = _platform_is_linux(monkeypatch, True)
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_sandbox_flag", lambda: {"enabled": False, "raw_value": ""}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_bwrap_present", lambda: {"found": False, "path": None}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_node_present", lambda: {"found": False, "path": None}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_srt_resolvable",
            lambda: {"found": False, "path": None, "install_hint": "npm install -g ..."},
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_rg_present", lambda: {"found": False, "path": None}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_broker_alive",
            lambda repo_root=None: {"alive": False, "detail": "not found"},
        )
        monkeypatch.setattr("aipass.aipass.apps.modules.doctor.find_project_root", lambda p: None)

        results = _check_sandbox()
        assert asked == ["is_linux"]
        # THE FLOOR (v5 unentered_assert, 2026-09-08). Six rows measured from
        # the shell the same day with every prereq stubbed absent; an empty
        # result made "no FAIL anywhere" true by vacuity.
        assert len(results) >= 6, f"only {len(results)} rows - the loop below proves nothing"
        for r in results:
            assert r.glyph != GLYPH_FAIL, f"Flag OFF should not produce FAIL, got FAIL for {r.label}"

    def test_flag_on_missing_prereq_is_fail(self, monkeypatch):
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")
        asked = _platform_is_linux(monkeypatch, True)
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_sandbox_flag", lambda: {"enabled": True, "raw_value": "1"}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_bwrap_present", lambda: {"found": False, "path": None}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_node_present", lambda: {"found": False, "path": None}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_srt_resolvable",
            lambda: {"found": False, "path": None, "install_hint": "npm install -g ..."},
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_rg_present", lambda: {"found": False, "path": None}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_broker_alive",
            lambda repo_root=None: {"alive": False, "detail": "not found"},
        )
        monkeypatch.setattr("aipass.aipass.apps.modules.doctor.find_project_root", lambda p: None)

        results = _check_sandbox()
        assert asked == ["is_linux"]
        fail_results = [r for r in results if r.glyph == GLYPH_FAIL]
        assert len(fail_results) >= 4, f"Flag ON + missing prereqs should produce FAILs, got {len(fail_results)}"

    def test_flag_on_all_present_is_pass(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")
        asked = _platform_is_linux(monkeypatch, True)
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_sandbox_flag", lambda: {"enabled": True, "raw_value": "1"}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_bwrap_present", lambda: {"found": True, "path": "/usr/bin/bwrap"}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_bwrap_functional",
            lambda: {"ok": True, "detail": "trivial sandbox succeeded", "sysctl_value": None},
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_node_present", lambda: {"found": True, "path": "/usr/bin/node"}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_srt_resolvable",
            lambda: {"found": True, "path": "/usr/lib/srt/index.js", "install_hint": ""},
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_rg_present", lambda: {"found": True, "path": "/usr/bin/rg"}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_broker_alive",
            lambda repo_root=None: {"alive": True, "detail": "connected"},
        )
        monkeypatch.setattr("aipass.aipass.apps.modules.doctor.find_project_root", lambda p: tmp_path / "fake")

        results = _check_sandbox()
        assert asked == ["is_linux"]
        # THE FLOOR (v5 unentered_assert, 2026-09-08). Seven rows measured from
        # the shell the same day with every prereq stubbed present - one more
        # than the flag-off shape, because bwrap functional is only probed when
        # bwrap is there. An empty result made "all PASS" true by vacuity.
        assert len(results) >= 7, f"only {len(results)} rows - the loop below proves nothing"
        for r in results:
            assert r.glyph == GLYPH_PASS, f"All present should be PASS, got {r.glyph} for {r.label}"

    def test_bwrap_functional_skipped_when_not_present(self, monkeypatch):
        asked = _platform_is_linux(monkeypatch, True)
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_sandbox_flag", lambda: {"enabled": False, "raw_value": ""}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_bwrap_present", lambda: {"found": False, "path": None}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_node_present", lambda: {"found": True, "path": "/usr/bin/node"}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_srt_resolvable",
            lambda: {"found": True, "path": "/x", "install_hint": ""},
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_rg_present", lambda: {"found": True, "path": "/usr/bin/rg"}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_broker_alive",
            lambda repo_root=None: {"alive": True, "detail": "ok"},
        )
        monkeypatch.setattr("aipass.aipass.apps.modules.doctor.find_project_root", lambda p: None)

        results = _check_sandbox()
        assert asked == ["is_linux"]
        labels = [r.label for r in results]
        assert "bwrap functional" not in labels

    def test_bwrap_functional_included_when_present(self, monkeypatch):
        asked = _platform_is_linux(monkeypatch, True)
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_sandbox_flag", lambda: {"enabled": False, "raw_value": ""}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_bwrap_present", lambda: {"found": True, "path": "/usr/bin/bwrap"}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_bwrap_functional",
            lambda: {"ok": True, "detail": "ok", "sysctl_value": None},
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_node_present", lambda: {"found": True, "path": "/usr/bin/node"}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_srt_resolvable",
            lambda: {"found": True, "path": "/x", "install_hint": ""},
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_rg_present", lambda: {"found": True, "path": "/usr/bin/rg"}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_broker_alive",
            lambda repo_root=None: {"alive": True, "detail": "ok"},
        )
        monkeypatch.setattr("aipass.aipass.apps.modules.doctor.find_project_root", lambda p: None)

        results = _check_sandbox()
        assert asked == ["is_linux"]
        labels = [r.label for r in results]
        assert "bwrap functional" in labels

    def test_sysctl_in_detail_on_functional_fail(self, monkeypatch):
        asked = _platform_is_linux(monkeypatch, True)
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_sandbox_flag", lambda: {"enabled": True, "raw_value": "1"}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_bwrap_present", lambda: {"found": True, "path": "/usr/bin/bwrap"}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_bwrap_functional",
            lambda: {"ok": False, "detail": "exit 1: denied", "sysctl_value": "1"},
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_node_present", lambda: {"found": True, "path": "/usr/bin/node"}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_srt_resolvable",
            lambda: {"found": True, "path": "/x", "install_hint": ""},
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_rg_present", lambda: {"found": True, "path": "/usr/bin/rg"}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_broker_alive",
            lambda repo_root=None: {"alive": True, "detail": "ok"},
        )
        monkeypatch.setattr("aipass.aipass.apps.modules.doctor.find_project_root", lambda p: None)

        results = _check_sandbox()
        assert asked == ["is_linux"]
        func_result = [r for r in results if r.label == "bwrap functional"][0]
        assert "apparmor_restrict_unprivileged_userns=1" in func_result.detail

    def test_inert_suffix_when_flag_off(self, monkeypatch):
        asked = _platform_is_linux(monkeypatch, True)
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_sandbox_flag", lambda: {"enabled": False, "raw_value": ""}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_bwrap_present", lambda: {"found": False, "path": None}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_node_present", lambda: {"found": False, "path": None}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_srt_resolvable",
            lambda: {"found": False, "path": None, "install_hint": "npm install -g ..."},
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_rg_present", lambda: {"found": False, "path": None}
        )
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor.check_broker_alive",
            lambda repo_root=None: {"alive": False, "detail": "not found"},
        )
        monkeypatch.setattr("aipass.aipass.apps.modules.doctor.find_project_root", lambda p: None)

        results = _check_sandbox()
        assert asked == ["is_linux"]
        missing_results = [r for r in results if r.glyph == GLYPH_WARN]
        # THE FLOOR AND THE ESCAPE, BOTH (v5 unentered_assert + assertion_shape,
        # 2026-09-08). Measured from the shell the same day: five WARN rows -
        # bwrap, node, srt, rg, broker daemon - and NOT the sandbox flag row,
        # which reads PASS when the flag is off. So the `or r.label ==
        # "sandbox flag"` arm never once fired, and it acquitted every row it
        # would have reached. Empty results made the loop vacuous on top.
        assert len(missing_results) >= 5, f"only {len(missing_results)} WARN rows - the loop proves nothing"
        assert "sandbox flag" not in [r.label for r in missing_results]
        for r in missing_results:
            assert "inert" in r.detail, f"Missing prereq {r.label} should show inert suffix"
