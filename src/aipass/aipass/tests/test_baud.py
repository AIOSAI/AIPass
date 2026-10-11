# =================== AIPass ====================
# Name: test_baud.py
# Description: Tests for aipass baud's command line: each value flag reaches the function it feeds
# Version: 1.1.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/modules/baud.py: the install and status flags as a user types them."""
# install_phone_face and show_status are replaced by recorders where baud.py reads
# them, so each flag's value is seen arriving as its keyword; the fetch, verify and
# unpack behind them never run. handle_command ends in sys.exit, so every call is
# read through the SystemExit it raises.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every module this file imports parses and imports

import pytest  # pyright: ignore[reportMissingImports]

from aipass.aipass.apps.modules import baud


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
        assert installs.calls == [{"dry_run": True, "best_effort": True}]
        out, _err = capsys.readouterr()
        assert baud.RETRY_HINT not in out
