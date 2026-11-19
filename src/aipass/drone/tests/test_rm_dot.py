# =================== AIPass ====================
# Name: test_rm_dot.py
# Description: drone rm: a dot name is protected, citizens always, the admin only with --dot
# Version: 1.0.0
# Created: 2026-11-15
# Modified: 2026-11-15
# =============================================

"""Tests for apps/handlers/rm_handler.py's dot-name guard and the record it leaves."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(covered_elsewhere) — the broker lane of a sandboxed delete, pinned in tests/test_broker.py
# sentry: no-test-needed(covered_elsewhere) — containment and the fences, pinned in tests/test_rm.py

import pytest

from aipass.drone.apps.handlers.rm_handler import (
    safe_delete,
)

from .conftest import rail_answers, rm_ledger


class TestADotNameIsProtectedAndTheRecordSaysWhy:
    @pytest.fixture()
    def home(self, project_dir, monkeypatch):
        """Standing in @drone's own tree, @api beside it."""
        for branch in ("drone", "api"):
            (project_dir / "src" / "aipass" / branch / ".trinity").mkdir(parents=True)
        monkeypatch.chdir(project_dir / "src" / "aipass" / "drone")
        return project_dir / "src" / "aipass" / "drone"

    @pytest.mark.parametrize(
        ("relative", "admin", "flags", "shown"),
        [
            ((".env",), False, [], "mail @devpulse"),
            ((".backup", ".old.json"), False, [], "mail @devpulse"),
            ((".env",), True, [], "same command and --dot"),
            ((".env",), False, ["--dot"], "--dot is the verified admin seat's alone"),
        ],
    )
    def test_a_dot_name_is_refused_and_stays(self, home, tmp_path, monkeypatch, relative, admin, flags, shown):
        rail_answers(monkeypatch, admin)
        target = home.joinpath(*relative)
        target.parent.mkdir(exist_ok=True)
        target.write_text("keep", encoding="utf-8")

        ((_, ok, message),) = safe_delete([*flags, str(target)])

        assert (ok, target.read_text(encoding="utf-8")) == (False, "keep")
        assert f"{relative[-1]} is a dot name" in message
        assert shown in message
        assert ("--dot" in message) == (admin or bool(flags))
        (record,) = rm_ledger(tmp_path)
        assert (record["outcome"], "exemption" in record) == ("refused", False)
        assert "dot name" in record["reason"]

    @pytest.mark.parametrize("relative", [(".backup",), (".backup", ".inner")])
    def test_a_dot_folder_is_refused_whole_and_so_is_one_nested_in_it(self, home, monkeypatch, relative):
        rail_answers(monkeypatch, False)
        target = home.joinpath(*relative)
        (target / "kept.json").parent.mkdir(parents=True)
        (target / "kept.json").write_text("{}", encoding="utf-8")

        ((_, ok, message),) = safe_delete([str(target)])

        assert (ok, (target / "kept.json").exists()) == (False, True)
        assert f"{relative[-1]} is a dot name" in message

    @pytest.mark.parametrize("name", ["old.json", "plain_folder"])
    def test_what_sits_inside_a_dot_folder_moves_for_its_owner(self, home, tmp_path, monkeypatch, name):
        rail_answers(monkeypatch, False)
        target = home / ".daemon" / name
        target.parent.mkdir()
        target.mkdir() if name == "plain_folder" else target.write_text("{}", encoding="utf-8")

        ((_, ok, message),) = safe_delete([str(target)])

        assert ok is True, message
        assert (home / ".daemon" / ".archive" / name).exists()
        (record,) = rm_ledger(tmp_path)
        assert (record["outcome"], "exemption" in record) == ("moved", False)

    def test_a_link_with_a_dot_name_is_refused_though_it_points_at_a_plain_file(self, home, monkeypatch):
        rail_answers(monkeypatch, False)
        (home / "plain.md").write_text("plain", encoding="utf-8")
        link = home / ".plain_link"
        link.symlink_to(home / "plain.md")

        ((_, ok, message),) = safe_delete([str(link)])

        assert (ok, link.is_symlink()) == (False, True)
        assert ".plain_link is a dot name" in message

    @pytest.mark.parametrize(("branch", "exemption"), [("drone", "dot"), ("api", "admin+dot")])
    def test_the_admin_with_dot_moves_it_and_the_record_says_the_guard_was_lifted(
        self, home, tmp_path, monkeypatch, branch, exemption
    ):
        rail_answers(monkeypatch, True)
        target = home.parent / branch / ".env"
        target.write_text("moved", encoding="utf-8")

        ((_, ok, message),) = safe_delete(["--dot", str(target)])

        assert ok is True, message
        assert "dot guard lifted by --dot" in message
        assert (target.parent / ".archive" / ".env").read_text(encoding="utf-8") == "moved"
        (record,) = rm_ledger(tmp_path)
        assert (record["outcome"], record["exemption"]) == ("moved", exemption)

    def test_dot_never_lifts_a_carveout(self, home, monkeypatch):
        rail_answers(monkeypatch, True)
        target = home / ".trinity" / "local.json"
        target.write_text("{}", encoding="utf-8")

        ((_, ok, message),) = safe_delete(["--dot", str(target)])

        assert (ok, target.exists()) == (False, True)
        assert "inside .trinity/" in message

    def test_dot_with_no_path_is_refused(self, home):
        ((path, ok, message),) = safe_delete(["--dot"])

        assert (path, ok) == ("--dot", False)
        assert "names no path" in message

    def test_a_plain_folder_holding_dot_files_still_moves_whole(self, home, monkeypatch):
        rail_answers(monkeypatch, False)
        (home / "scratch" / ".pytest_cache").mkdir(parents=True)
        (home / "scratch" / ".gitkeep").write_text("", encoding="utf-8")

        ((_, ok, message),) = safe_delete([str(home / "scratch")])

        assert ok is True, message
        assert (home / ".archive" / "scratch" / ".gitkeep").exists()

    def test_bytecode_in_a_dot_folder_and_a_dot_file_in_temp_are_still_truly_deleted(
        self, home, tmp_path_factory, monkeypatch
    ):
        rail_answers(monkeypatch, False)
        bytecode = home / ".fixtures" / "__pycache__"
        bytecode.mkdir(parents=True)
        scratch = tmp_path_factory.mktemp("outside") / ".junk"
        scratch.write_text("x", encoding="utf-8")

        results = safe_delete([str(bytecode), str(scratch)])

        assert [ok for _, ok, _ in results] == [True, True], results
        assert (bytecode.exists(), scratch.exists()) == (False, False)
