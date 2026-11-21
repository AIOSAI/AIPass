# =================== AIPass ====================
# Name: test_rm_archive.py
# Description: drone rm: the in-tree move to .archive, the name clash, the log line, the rm module
# Version: 1.0.2
# Created: 2026-11-15
# Modified: 2026-11-21
# =============================================

"""Tests for apps/handlers/rm_handler.py's move to .archive and apps/modules/rm.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(covered_elsewhere) — the deletion record's contents, pinned in tests/test_deletion_log.py
# sentry: no-test-needed(covered_elsewhere) — the broker lane of a sandboxed delete, pinned in tests/test_broker.py
# sentry: no-test-needed(covered_elsewhere) — containment and the fences, pinned in tests/test_rm.py

from unittest.mock import patch

import pytest

from aipass.drone.apps import drone as drone_cli
from aipass.drone.apps.handlers import rm_handler
from aipass.drone.apps.handlers.rm_handler import (
    safe_delete,
)
from aipass.drone.apps.modules.rm import handle_command, print_help, print_introspection

from .conftest import logged_lines, rail_answers, rm_ledger


@pytest.fixture()
def in_project(project_dir, monkeypatch):
    """Stand in a citizen's seat in the fake project: off the admin seat, drone rm moves only inside its own branch."""
    seat = project_dir / "src" / "aipass" / "me"
    (seat / ".trinity").mkdir(parents=True)
    monkeypatch.chdir(seat)
    return seat


class TestAnInTreeTargetMovesToTheLocalArchive:
    def test_a_file_moves_into_the_archive_beside_it_and_the_record_says_where(self, in_project, tmp_path):
        target = in_project / "notes" / "draft.md"
        target.parent.mkdir()
        target.write_text("keep me", encoding="utf-8")

        ((_, ok, message),) = safe_delete([str(target)])

        moved = in_project / "notes" / ".archive" / "draft.md"
        assert ok is True
        assert not target.exists()
        assert moved.read_text(encoding="utf-8") == "keep me"
        assert str(moved) in message
        (record,) = rm_ledger(tmp_path)
        assert (record["outcome"], record["path"], record["moved_to"]) == ("moved", str(target), str(moved))

    def test_a_directory_moves_whole(self, in_project):
        target = in_project / "scratch"
        (target / "deep").mkdir(parents=True)
        (target / "deep" / "a.txt").write_text("a", encoding="utf-8")

        ((_, ok, _),) = safe_delete([str(target)])

        assert ok is True
        assert not target.exists()
        assert (in_project / ".archive" / "scratch" / "deep" / "a.txt").read_text(encoding="utf-8") == "a"

    def test_a_name_taken_after_any_look_is_never_overwritten(self, in_project, monkeypatch, tmp_path):
        """A twin move can take the name in the instant before the rename: only the rename itself may refuse it."""
        (in_project / ".archive").mkdir()
        (in_project / ".archive" / "plan.md").write_text("first", encoding="utf-8")
        (in_project / "plan.md").write_text("second", encoding="utf-8")
        monkeypatch.setattr(rm_handler, "_archive_names", lambda name: iter([name, f"{name}.twin"]))

        ((_, ok, _),) = safe_delete([str(in_project / "plan.md")])

        assert ok is True
        assert (in_project / ".archive" / "plan.md").read_text(encoding="utf-8") == "first"
        assert (in_project / ".archive" / "plan.md.twin").read_text(encoding="utf-8") == "second"
        assert rm_ledger(tmp_path)[0]["moved_to"].endswith("plan.md.twin")

    def test_a_name_already_archived_keeps_both_and_overwrites_nothing(self, in_project):
        archive = in_project / ".archive"
        archive.mkdir()
        (archive / "plan.md").write_text("first", encoding="utf-8")
        target = in_project / "plan.md"
        target.write_text("second", encoding="utf-8")

        ((_, ok, _),) = safe_delete([str(target)])

        assert ok is True
        assert (archive / "plan.md").read_text(encoding="utf-8") == "first"
        (stamped,) = [p for p in archive.iterdir() if p.name != "plan.md"]
        assert stamped.name.startswith("plan.md.")
        assert stamped.read_text(encoding="utf-8") == "second"

    @pytest.mark.parametrize("inside", [False, True])
    def test_a_target_in_an_archive_is_refused_and_stays(self, in_project, tmp_path, inside):
        archive = in_project / ".archive"
        archive.mkdir()
        (archive / "old.md").write_text("old", encoding="utf-8")
        target = archive / "old.md" if inside else archive

        ((_, ok, message),) = safe_delete([str(target)])

        assert ok is False
        assert ".archive" in message
        assert (archive / "old.md").read_text(encoding="utf-8") == "old"
        (record,) = rm_ledger(tmp_path)
        assert record["outcome"] == "refused"

    @pytest.mark.parametrize("name", ["__pycache__", "mod.cpython-312.pyc"])
    def test_bytecode_is_truly_deleted_and_no_archive_is_made(self, in_project, tmp_path, name):
        target = in_project / "pkg" / name
        target.parent.mkdir()
        if name == "__pycache__":
            target.mkdir()
            (target / "m.pyc").write_bytes(b"\0")
        else:
            target.write_bytes(b"\0")

        ((_, ok, _),) = safe_delete([str(target)])

        assert ok is True
        assert not target.exists()
        assert not (in_project / "pkg" / ".archive").exists()
        (record,) = rm_ledger(tmp_path)
        assert record["outcome"] == "deleted"

    def test_a_temp_dir_target_outside_the_project_is_truly_deleted(self, in_project, tmp_path_factory, tmp_path):
        target = tmp_path_factory.mktemp("scratch") / "junk.txt"
        target.write_text("x", encoding="utf-8")

        ((_, ok, _),) = safe_delete([str(target)])

        assert ok is True
        assert not target.exists()
        assert not (target.parent / ".archive").exists()
        (record,) = rm_ledger(tmp_path)
        assert record["outcome"] == "deleted"

    def test_an_archive_that_is_a_symlink_is_refused_and_nothing_moves(self, in_project, tmp_path_factory, tmp_path):
        elsewhere = tmp_path_factory.mktemp("elsewhere")
        (in_project / ".archive").symlink_to(elsewhere, target_is_directory=True)
        target = in_project / "keep.md"
        target.write_text("here", encoding="utf-8")

        ((_, ok, message),) = safe_delete([str(target)])

        assert ok is False
        assert "symlink" in message
        assert target.read_text(encoding="utf-8") == "here"
        assert list(elsewhere.iterdir()) == []
        (record,) = rm_ledger(tmp_path)
        assert record["outcome"] == "refused"


class TestTheRmLogLineTellsTheWholeStory:
    def test_a_move_line_names_the_caller_the_path_and_where_it_went(self, in_project, tmp_path):
        target = in_project / "draft.md"
        target.write_text("x", encoding="utf-8")

        with patch("aipass.drone.apps.handlers.rm_handler.logger") as log:
            safe_delete([str(target)])

        (record,) = rm_ledger(tmp_path)
        (line,) = [line for line in logged_lines(log.info) if "moved" in line]
        assert record["caller"] in line
        assert str(target) in line
        assert str(in_project / ".archive" / "draft.md") in line

    @pytest.mark.parametrize("case", ["sibling", "carveout", "archive", "symlinked_archive"])
    def test_every_deliberate_refusal_logs_info_never_warning(
        self, at_drone_beside_api, monkeypatch, tmp_path_factory, case
    ):
        rail_answers(monkeypatch, False)
        drone = at_drone_beside_api.parent / "drone"
        if case == "symlinked_archive":
            (drone / ".archive").symlink_to(tmp_path_factory.mktemp("elsewhere"), target_is_directory=True)
        else:
            (drone / ".archive").mkdir()
            (drone / ".archive" / "old.md").write_text("x", encoding="utf-8")
        target = {
            "sibling": at_drone_beside_api / "README.md",
            "carveout": drone / ".trinity",
            "archive": drone / ".archive" / "old.md",
            "symlinked_archive": drone / "README.md",
        }[case]

        with patch("aipass.drone.apps.handlers.rm_handler.logger") as log:
            ((_, ok, _),) = safe_delete([str(target)])

        assert ok is False
        assert not log.warning.called
        assert not log.error.called
        assert any("refused" in line for line in logged_lines(log.info))

    def test_the_command_logs_every_target_under_one_key(self, in_project):
        with patch("aipass.drone.apps.modules.rm.json_handler") as service:
            handle_command("first.txt", ["second.txt", "third.txt"])

        assert service.log_operation.call_args_list[0].args == (
            "rm_command",
            {"targets": ["first.txt", "second.txt", "third.txt"]},
        )


class TestRmModule:
    def test_handle_command_help_prints_the_usage_and_deletes_nothing(self, capsys):
        """Mutant killed: handle_command's --help branch returning True without print_help()."""
        result = handle_command("--help")

        assert result is True
        assert "Usage: drone rm" in capsys.readouterr().out

    def test_handle_command_with_no_arguments_prints_the_self_map(self, capsys):
        """Mutant killed: handle_command's no-argument branch returning True without print_introspection()."""
        result = handle_command(None, None)

        assert result is True
        assert "Contained Safe-Delete" in capsys.readouterr().out

    def test_print_introspection(self, capsys):
        """The self-map names the module and points at --help."""
        print_introspection()

        printed = capsys.readouterr().out
        assert "Contained Safe-Delete" in printed
        assert "--help" in printed

    def test_print_help(self, capsys):
        """--help states the usage line and the containment rule it enforces."""
        print_help()

        printed = capsys.readouterr().out
        assert "Usage: drone rm" in printed
        assert "Carve-outs" in printed

    def test_help_says_files_in_the_temp_dir_are_deleted_not_the_temp_dir(self, capsys):
        print_help()

        printed = capsys.readouterr().out
        assert "files in the system temp dir" in printed
        assert "Everything else is moved" in printed
        assert "only these: the system temp dir" not in printed

    def test_a_move_prints_the_source_and_destination_each_whole_on_its_own_line(self, in_project, capsys):
        """Longer than the pinned console width, so a wrapping print would split the name."""
        target = in_project / ("a_long_scratch_name_" * 12 + ".txt")
        target.write_text("x", encoding="utf-8")

        assert handle_command(str(target), []) is True

        lines = [line.strip() for line in capsys.readouterr().out.splitlines()]
        assert str(target) in lines
        assert f"-> {in_project / '.archive' / target.name}" in lines

    def test_a_sibling_refusal_prints_the_path_whole_says_it_is_recorded_and_what_to_do(
        self, at_drone_beside_api, monkeypatch, capsys
    ):
        rail_answers(monkeypatch, False)
        target = at_drone_beside_api / ("deep_" * 45) / "notes.md"
        target.parent.mkdir()
        target.write_text("x", encoding="utf-8")

        assert handle_command(str(target), []) is False

        lines = [line.strip() for line in capsys.readouterr().err.splitlines()]
        assert str(target) in lines
        assert any("recorded" in line for line in lines)
        assert any("mail @devpulse the path and why" in line for line in lines)
        assert not any("PLAN-" in line for line in lines)

    def test_a_refusal_outside_every_root_is_a_failure_not_a_quiet_success(self, tmp_path):
        """A refusal is an error: handle_command reports False, the CLI exits 1.

        The root and target are siblings under tmp_path with roots narrowed by hand: ``_patch_roots``
        allows /tmp and ``project_dir`` IS ``tmp_path``, so either would put the target inside a root.
        """
        root = tmp_path / "the_only_allowed_root"
        root.mkdir()
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        target = elsewhere / "keepme.txt"
        target.write_text("must survive", encoding="utf-8")

        with patch(
            "aipass.drone.apps.handlers.rm_handler.get_allowed_roots",
            return_value=[root.resolve()],
        ):
            assert handle_command(str(target)) is False

        assert target.exists(), "the refusal did not hold — the file was deleted"

    def test_the_cli_maps_a_refusal_to_a_non_zero_exit(self, monkeypatch, tmp_path):
        """False is not flattened to 0 on the way out; mutant killed: _handle_rm returning 0 always."""
        target = str(tmp_path / "refused")
        calls = []

        def answer(verdict):
            def recorder(command, args=None):
                calls.append((command, args))
                return verdict

            return recorder

        monkeypatch.setattr("sys.argv", ["drone", "rm", target])
        monkeypatch.setattr("aipass.drone.apps.modules.rm.handle_command", answer(False))
        assert drone_cli.main() == 1
        monkeypatch.setattr("aipass.drone.apps.modules.rm.handle_command", answer(True))
        assert drone_cli.main() == 0
        assert calls == [(target, None), (target, None)]

    def test_no_path_prints_the_usage_and_exits_non_zero(self, monkeypatch, capsys):
        """A missing required argument is a usage error; --help alone exits 0. Mutant: no-arg returning 0."""
        monkeypatch.setattr("sys.argv", ["drone", "rm"])
        assert drone_cli.main() == 1
        assert "Usage: drone rm" in capsys.readouterr().out
        monkeypatch.setattr("sys.argv", ["drone", "rm", "--help"])
        assert drone_cli.main() == 0
