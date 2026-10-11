# =================== AIPass ====================
# Name: test_config_verbs_todo.py
# Description: The todo lane of the verbs - the todos count shown never set, the rollover pad, the todo verbs
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/modules/todo.py and the todo lane of apps/modules/rollover.py and rollover_config.py."""

# Split from test_config_verbs.py on 2026-10-08 (oversize_test_file): the todo
# lane, one subject - the todos count `config get` shows and `config set` never
# writes (DPLAN-0345), the ONE pad `rollover check` / `run` acts on, and the
# `todo` / `todo backlog` / `todo restore` verbs (FPLAN-0590 row 5), all on the
# same minted config and registry.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — push_defaults_to_per_branch() itself, tests/test_config_loader.py

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# The real display module, imported once at the top: nothing in the suite
# stands it in, conftest imports it the same way, and its consoles are patched
# at the edge (their width) per test.
from aipass.cli.apps.modules import display
from aipass.memory.tests.support_config_verbs import (
    _ANSI,
    _payload,
    _rollover_section,
    _run,
    _run_rollover,
    _streams,
    _unwrapped,
)

# ===========================================================================
# 8. Todos (DPLAN-0345) -- the count is shown, never set; ONE pad per rollover verb
# ===========================================================================


def _stdout(capsys: pytest.CaptureFixture) -> str:
    """Raw stdout, ANSI-stripped -- exactly what @hooks' PreCompact grep reads."""
    return _ANSI.sub("", capsys.readouterr().out)


class TestTodosCountIsDisplayOnly:
    """`config get` shows the todos count; `config set` / `set-default` never write it in v1."""

    def test_get_shows_the_todos_default(self, verbs, capsys) -> None:
        _run(verbs, "get")
        rows = [line for line in _streams(capsys).splitlines() if line.strip().startswith("todos")]
        assert len(rows) == 1 and "10" in rows[0] and "read-only in v1" in rows[0], rows

    def test_get_branch_shows_the_todos_count(self, verbs, capsys) -> None:
        _run(verbs, "get", "@memory")
        out = _streams(capsys)
        assert any(line.strip().startswith("todos") and "10" in line for line in out.splitlines()), out
        assert "read-only in v1 — the todo roll reads it, config set does not" in out

    def test_json_defaults_mark_todos_read_only(self, verbs, capsys) -> None:
        assert _payload(verbs, capsys, "get", "--json")["defaults"]["todos"] == {"count": 10, "read_only": True}

    def test_json_branch_limits_mark_todos_read_only(self, verbs, capsys) -> None:
        row = _payload(verbs, capsys, "get", "@memory", "--json")["limits"]["todos"]
        assert row == {
            "count": 10,
            "default_count": 10,
            "is_override": False,
            "source": "per_branch",
            "read_only": True,
        }

    @pytest.mark.parametrize("args", [("set", "@memory", "todos", "5"), ("set-default", "todos", "5")])
    def test_setting_todos_is_refused_and_writes_nothing(self, verbs, capsys, args) -> None:
        before = verbs.path.read_bytes()
        _run(verbs, *args)
        out = _unwrapped(_streams(capsys))
        assert (
            _unwrapped("'todos' is display-only in v1: config get shows its count, config set cannot change it") in out
        )
        assert _unwrapped("Settable types: sessions, key_learnings, observations") in out
        assert verbs.path.read_bytes() == before


class TestTodosCountMaterializesThroughTheVerbs:
    """Every per_branch local block a verb writes carries the todos count."""

    def test_the_seeded_per_branch_carries_todos(self, verbs) -> None:
        per_branch = _rollover_section(verbs)["per_branch"]
        assert set(per_branch) == {"memory", "devpulse", "daemon"}
        for name, entry in per_branch.items():
            assert entry["local"]["todos"] == {"count": 10}, name

    def test_a_set_on_a_block_without_todos_writes_it(self, verbs) -> None:
        raw = json.loads(verbs.path.read_text(encoding="utf-8"))
        del raw["rollover"]["per_branch"]["memory"]["local"]["todos"]
        verbs.path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

        _run(verbs, "set", "@memory", "sessions", "12")

        local = _rollover_section(verbs)["per_branch"]["memory"]["local"]
        assert local["sessions"]["count"] == 12
        assert local["todos"] == {"count": 10}

    def test_a_push_writes_todos_into_every_block(self, verbs) -> None:
        raw = json.loads(verbs.path.read_text(encoding="utf-8"))
        for entry in raw["rollover"]["per_branch"].values():
            del entry["local"]["todos"]
        verbs.path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

        _run_rollover(verbs, "push")

        for name, entry in _rollover_section(verbs)["per_branch"].items():
            assert entry["local"]["todos"] == {"count": 10}, name


class TestRolloverTodoPad:
    """`rollover check` / `run` act on ONE pad: --branch, or the branch the caller stood in."""

    @pytest.fixture
    def pad(self, verbs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
        """A @memory pad inside the minted repo; the todo lane and the memory writer pointed at the fixture."""
        todo_roll = importlib.import_module("aipass.memory.apps.handlers.rollover.todo_roll")
        todo_report = importlib.import_module("aipass.memory.apps.handlers.rollover.todo_report")
        monkeypatch.setattr(todo_roll, "_find_repo_root", lambda: tmp_path)
        monkeypatch.setattr(todo_roll, "config_loader", verbs.loader)
        monkeypatch.setattr(todo_report, "todo_roll", todo_roll)
        monkeypatch.setattr(todo_report, "detector", verbs.detector)
        monkeypatch.setattr(verbs.rollover, "todo_report", todo_report)
        for holder in ("memory_files", "entry_limits"):
            module = importlib.import_module(f"aipass.memory.apps.handlers.json.{holder}")
            monkeypatch.setattr(module, "config_loader", verbs.loader)
        execute = MagicMock(return_value={"success": True, "triggers_count": 0})
        monkeypatch.setattr(verbs.rollover, "_handler_execute_rollover", execute)

        local = tmp_path / "src" / "aipass" / "memory" / ".trinity" / "local.json"
        local.parent.mkdir(parents=True)

        def write(count: int) -> bytes:
            todos = [
                {"number": n, "task": f"task {n}", "date": "2026-09-01", "priority": "normal"}
                for n in range(1, count + 1)
            ]
            document = {"document_metadata": {}, "sessions": [], "todos": todos}
            local.write_text(json.dumps(document, indent=2), encoding="utf-8")
            return local.read_bytes()

        backlog = tmp_path / ".backup" / "todo" / "memory" / "backlog.json"
        return SimpleNamespace(local=local, backlog=backlog, execute=execute, write=write, before=write(12))

    def test_check_over_count_says_ready_for_rollover(self, verbs, pad, capsys) -> None:
        capsys.readouterr()
        _run_rollover(verbs, "check", "--branch", "@memory")
        out = _stdout(capsys)
        assert "@memory todos: pad 12/10 - 2 ready for rollover (oldest by number -> " in out, out
        assert pad.local.read_bytes() == pad.before
        assert not pad.backlog.exists()

    def test_the_phrase_survives_a_narrow_pipe(self, verbs, pad, capsys, monkeypatch) -> None:
        """@hooks greps raw stdout. At 40 columns a hard wrap would land between 'for' and 'rollover'."""
        monkeypatch.setattr(display.CONSOLE, "_width", 40)
        capsys.readouterr()
        _run_rollover(verbs, "check", "--branch", "@memory")
        assert "ready for rollover" in _stdout(capsys)

    def test_check_labels_the_classic_file_list_fleet_wide(self, verbs, pad, capsys, monkeypatch) -> None:
        """--branch scopes the pad line only. The classic list is the fleet walk (scope unchanged) and says so,
        with "ready for rollover" whole on its first line even on a 40-column pipe (@hooks greps it)."""
        monkeypatch.setattr(display.CONSOLE, "_width", 40)
        triggers = ["CANARY.local 16/15", "memory.local 16/15"]
        monkeypatch.setattr(
            verbs.rollover.detector, "check_all_branches", lambda: {"success": True, "triggers": triggers}
        )
        within = pad.write(10)
        capsys.readouterr()
        _run_rollover(verbs, "check", "--branch", "@memory")
        lines = _stdout(capsys).splitlines()
        assert "Found 2 files ready for rollover (fleet-wide):" in lines, lines
        assert verbs.rollover.FLEET_WIDE_NOTE in lines, lines
        assert "--branch" in verbs.rollover.FLEET_WIDE_NOTE and "fleet-wide" in verbs.rollover.FLEET_WIDE_NOTE
        assert [line for line in lines if line.startswith("  * ")] == [f"  * {trigger}" for trigger in triggers]
        assert any("@memory todos: pad 10/10 - within count" in line for line in lines), lines
        assert pad.local.read_bytes() == within, "check writes nothing"
        assert not pad.backlog.exists()

    def test_a_pad_at_its_count_is_within_count(self, verbs, pad, capsys) -> None:
        pad.write(10)
        capsys.readouterr()
        _run_rollover(verbs, "check", "--branch=@memory")
        out = _stdout(capsys)
        assert "@memory todos: pad 10/10 - within count" in out, out
        assert "ready for rollover" not in out

    def test_at_the_repo_root_no_pad_is_checked_or_rolled(self, verbs, pad, capsys, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))
        capsys.readouterr()
        _run_rollover(verbs, "check")
        _run_rollover(verbs, "run")
        out = _stdout(capsys)
        todo_lines = [line for line in out.splitlines() if line.startswith("Todos:")]
        assert len(todo_lines) == 2, out
        assert todo_lines[0].startswith("Todos: no branch resolved (")
        assert todo_lines[0].endswith("- no todo pad checked; pass --branch @name")
        assert todo_lines[1].endswith("- no todo pad rolled; pass --branch @name")
        assert "ready for rollover" not in out
        assert pad.local.read_bytes() == pad.before
        assert not pad.backlog.exists()

    def test_run_rolls_the_named_pad_into_its_backlog(self, verbs, pad, capsys) -> None:
        capsys.readouterr()
        assert _run_rollover(verbs, "run", "--branch", "@memory") is True
        out = _stdout(capsys)
        assert "@memory todos: rolled 2 oldest (#1, #2) -> " in out, out
        assert "pad now 10/10" in out
        assert [t["number"] for t in json.loads(pad.local.read_text(encoding="utf-8"))["todos"]] == list(range(3, 13))
        entries = json.loads(pad.backlog.read_text(encoding="utf-8"))["entries"]
        assert [record["entry"]["number"] for record in entries] == [1, 2]
        pad.execute.assert_called_once_with()

    @pytest.mark.parametrize(
        ("args", "sentence"),
        [
            (("run", "--branch"), "--branch needs a branch name (rollover run)"),
            (("check", "--brnach", "@memory"), "Unknown argument: '--brnach' (rollover check)"),
            (("run", "--branch", "@memory", "extra"), "Unknown argument: 'extra' (rollover run)"),
        ],
    )
    def test_a_bad_flag_is_refused_and_nothing_runs(self, verbs, pad, capsys, args, sentence) -> None:
        capsys.readouterr()
        _run_rollover(verbs, *args)
        assert _unwrapped(sentence) in _unwrapped(_streams(capsys))
        pad.execute.assert_not_called()
        assert pad.local.read_bytes() == pad.before
        assert not pad.backlog.exists()

    def test_an_unknown_branch_is_refused_by_name(self, verbs, pad, capsys) -> None:
        capsys.readouterr()
        _run_rollover(verbs, "check", "--branch", "@wizard")
        assert _unwrapped("Todos not checked - Unknown branch: @wizard") in _unwrapped(_streams(capsys))


_TODO_FORMS = (
    "drone @memory todo [@name]",
    "drone @memory todo backlog [@name]",
    "drone @memory todo restore <number>",
)


def _todo_exit(todo: SimpleNamespace, *args: str) -> int:
    """Run `todo <args>` through the module and map it to the exit code main() returns (resolve_exit)."""
    todo.display.reset_command_state()
    return todo.display.resolve_exit(todo.module.handle_command("todo", list(args)))


def _todo_pad(todo: SimpleNamespace, numbers) -> bytes:
    """Write canonical todos with these numbers onto the scratch pad; return its bytes."""
    todos = [{"number": n, "date": "2026-09-01", "task": f"task {n}", "priority": "medium"} for n in numbers]
    document = {"document_metadata": {}, "sessions": [], "todos": todos}
    todo.local.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return todo.local.read_bytes()


def _todo_record(number: int, task: str, rolled: str = "2026-09-15T01:00:00+10:00", **extra) -> dict:
    """One backlog record; *extra* lands inside the entry (priority, status), `reason` on the record."""
    reason = extra.pop("reason", "overflow")
    return {
        "rolled": rolled,
        "reason": reason,
        "entry": {"number": number, "date": "2026-09-01", "task": task, **extra},
    }


def _todo_backlog(todo: SimpleNamespace, records: list) -> bytes:
    """Write the scratch backlog document; return its bytes."""
    todo.backlog.parent.mkdir(parents=True, exist_ok=True)
    document = {"document_metadata": {"managed_by": "memory", "branch": "memory"}, "entries": records}
    todo.backlog.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return todo.backlog.read_bytes()


def _set_todos_count(verbs: SimpleNamespace, count: int) -> None:
    """Set the todos count in defaults and every materialized per_branch block of the minted config."""
    config = json.loads(verbs.path.read_text(encoding="utf-8"))
    for block in [config["rollover"]["defaults"], *config["rollover"]["per_branch"].values()]:
        block["local"]["todos"] = {"count": count}
    assert verbs.loader._write_config_file(config), "could not write the minted config"


class TestTodoVerbs:
    """`todo` / `todo backlog` / `todo restore` (FPLAN-0590 row 5): the real module and handlers on a minted repo."""

    @pytest.fixture(autouse=True)
    def _backlogs_stay_in_tmp(self, verbs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No pin in this class may reach the repo's real .backup/todo/: an unrouted backlog lands under tmp_path."""
        todo_roll = importlib.import_module("aipass.memory.apps.handlers.rollover.todo_roll")
        real = todo_roll.backlog_path_for

        def scratch(branch_dir, backup_root=None):
            return real(branch_dir, tmp_path / ".backup" if backup_root is None else backup_root)

        monkeypatch.setattr(todo_roll, "backlog_path_for", scratch)

    @pytest.fixture
    def todo(self, verbs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """The todo module wired to the minted repo; the caller stands in @memory's directory."""
        todo_roll = importlib.import_module("aipass.memory.apps.handlers.rollover.todo_roll")
        todo_report = importlib.import_module("aipass.memory.apps.handlers.rollover.todo_report")
        monkeypatch.setattr(todo_roll, "_find_repo_root", lambda: tmp_path)
        monkeypatch.setattr(todo_roll, "config_loader", verbs.loader)
        monkeypatch.setattr(todo_roll, "json_handler", MagicMock())
        monkeypatch.setattr(todo_report, "todo_roll", todo_roll)
        monkeypatch.setattr(todo_report, "detector", verbs.detector)
        monkeypatch.setattr(todo_report, "json_handler", MagicMock())
        for holder in ("memory_files", "entry_limits"):
            module = importlib.import_module(f"aipass.memory.apps.handlers.json.{holder}")
            monkeypatch.setattr(module, "config_loader", verbs.loader)
        monkeypatch.delitem(sys.modules, "aipass.memory.apps.modules.todo", raising=False)
        module = importlib.import_module("aipass.memory.apps.modules.todo")
        monkeypatch.setattr(module, "todo_report", todo_report)
        monkeypatch.setattr(module, "json_handler", MagicMock())

        branch = tmp_path / "src" / "aipass" / "memory"
        local = branch / ".trinity" / "local.json"
        local.parent.mkdir(parents=True)
        (tmp_path / "src" / "aipass" / "devpulse").mkdir(parents=True)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(branch))
        monkeypatch.delenv("AIPASS_BRANCH_NAME", raising=False)

        backlog = tmp_path / ".backup" / "todo" / "memory" / "backlog.json"
        assert todo_roll.backlog_path_for("memory") == backlog
        yield SimpleNamespace(
            module=module, local=local, backlog=backlog, branch=branch, root=tmp_path, display=display, verbs=verbs
        )
        display.reset_command_state()

    def test_bare_is_one_line_the_pad_of_the_configured_count_and_the_backlog(self, todo, capsys) -> None:
        _set_todos_count(todo.verbs, 7)
        _todo_pad(todo, range(1, 7))
        capsys.readouterr()
        assert _todo_exit(todo) == 0
        captured = capsys.readouterr()
        assert _ANSI.sub("", captured.out).splitlines() == [
            "memory: pad 6 of 7 · backlog 0 (no backlog yet: .backup/todo/memory/backlog.json)"
        ], captured.out
        assert captured.err == ""

        _todo_backlog(todo, [_todo_record(1, "one"), _todo_record(2, "two")])
        assert _todo_exit(todo, "@memory") == 0
        assert _ANSI.sub("", capsys.readouterr().out).splitlines() == [
            "memory: pad 6 of 7 · backlog 2 (.backup/todo/memory/backlog.json)"
        ]

    def test_bare_at_the_repo_root_resolves_no_branch_and_says_so(self, todo, capsys, monkeypatch) -> None:
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(todo.root))
        _todo_pad(todo, range(1, 4))
        capsys.readouterr()
        assert _todo_exit(todo) == 0
        lines = _ANSI.sub("", capsys.readouterr().out).splitlines()
        assert len(lines) == 1, lines
        assert lines[0].startswith("Todos: no branch resolved (")
        assert lines[0].endswith(") - no todo pad counted; pass --branch @name")

        assert _todo_exit(todo, "--branch", "@memory") == 0
        assert _ANSI.sub("", capsys.readouterr().out).startswith("memory: pad 3 of ")

    def test_backlog_lists_each_record_with_its_task_and_never_its_status(self, todo, capsys) -> None:
        log = "open - 23:19 wake-back LOG-MARKER " * 40
        _todo_backlog(
            todo,
            [
                _todo_record(
                    7, "Check on seedgo's errors in logs", reason="non-canonical", priority="high", status=log
                ),
                _todo_record(9, "fix drone help", rolled="2026-09-15T02:00:00+10:00"),
            ],
        )
        capsys.readouterr()
        assert _todo_exit(todo, "backlog") == 0
        captured = capsys.readouterr()
        out = _ANSI.sub("", captured.out)
        assert out.splitlines() == [
            "memory backlog: 2 record(s), oldest roll first (.backup/todo/memory/backlog.json)",
            "  #7 · 2026-09-01 · priority high · rolled 2026-09-15T01:00:00+10:00 · non-canonical"
            " · Check on seedgo's errors in logs",
            "  #9 · 2026-09-01 · rolled 2026-09-15T02:00:00+10:00 · overflow · fix drone help",
        ], out
        assert "LOG-MARKER" not in out + captured.err

    def test_a_missing_backlog_is_an_honest_line_and_exits_zero(self, todo, capsys) -> None:
        capsys.readouterr()
        assert _todo_exit(todo, "backlog") == 0
        assert _todo_exit(todo, "backlog", "@devpulse") == 0
        captured = capsys.readouterr()
        lines = _ANSI.sub("", captured.out).splitlines()
        assert lines[0].startswith("memory: no backlog - .backup/todo/memory/backlog.json does not exist."), lines
        assert lines[1].startswith("devpulse: no backlog - .backup/todo/devpulse/backlog.json does not exist."), lines
        assert captured.err == ""
        assert not todo.backlog.exists()

    def test_a_corrupt_backlog_is_refused_non_zero_and_left_as_it_was(self, todo, capsys) -> None:
        _todo_pad(todo, range(1, 4))
        todo.backlog.parent.mkdir(parents=True)
        todo.backlog.write_text("{not json", encoding="utf-8")
        capsys.readouterr()
        assert _todo_exit(todo, "backlog") == 2
        assert _unwrapped("memory: backlog not listed - backlog at") in _unwrapped(
            _ANSI.sub("", capsys.readouterr().err)
        )
        assert _todo_exit(todo) == 2
        assert _unwrapped("memory: pad 3 of 10 · backlog unreadable - backlog at") in _unwrapped(
            _ANSI.sub("", capsys.readouterr().err)
        )
        assert todo.backlog.read_text(encoding="utf-8") == "{not json"

    def test_restore_renumbers_to_max_of_pad_and_backlog_plus_one(self, todo, capsys) -> None:
        _todo_pad(todo, range(9, 2, -1))
        _todo_backlog(
            todo, [_todo_record(1, "Check on seedgo's errors in logs", priority="high"), _todo_record(2, "b")]
        )
        capsys.readouterr()
        assert _todo_exit(todo, "restore", "1") == 0
        out = _ANSI.sub("", capsys.readouterr().out)
        assert out.splitlines() == [
            "@memory todo restored: #1 -> #10 · Check on seedgo's errors in logs · pad now 8/10"
        ]
        pad = json.loads(todo.local.read_text(encoding="utf-8"))["todos"]
        assert pad[0] == {
            "number": 10,
            "date": "2026-09-01",
            "task": "Check on seedgo's errors in logs",
            "priority": "high",
        }, "lists are newest-first: the restored todo carries the highest number, so it goes on top"
        assert [t["number"] for t in pad] == [10, 9, 8, 7, 6, 5, 4, 3]
        entries = json.loads(todo.backlog.read_text(encoding="utf-8"))["entries"]
        assert [record["entry"]["number"] for record in entries] == [2]

    def test_a_full_pad_refuses_non_zero_at_the_count_read_from_config(self, todo, capsys) -> None:
        _set_todos_count(todo.verbs, 4)
        pad_before = _todo_pad(todo, range(3, 7))
        backlog_before = _todo_backlog(todo, [_todo_record(1, "fix drone help")])
        capsys.readouterr()
        assert _todo_exit(todo, "restore", "1") == 2
        err = _unwrapped(_ANSI.sub("", capsys.readouterr().err))
        assert _unwrapped("@memory todo #1 NOT restored - pad is full (4/4) - finish or delete one") in err, err
        assert todo.local.read_bytes() == pad_before
        assert todo.backlog.read_bytes() == backlog_before

    def test_an_ambiguous_number_is_refused_naming_every_candidate(self, todo, capsys) -> None:
        pad_before = _todo_pad(todo, range(20, 23))
        backlog_before = _todo_backlog(
            todo,
            [
                _todo_record(5, "first five"),
                _todo_record(6, "six"),
                _todo_record(5, "second five", rolled="2026-09-15T03:00:00+10:00"),
            ],
        )
        capsys.readouterr()
        assert _todo_exit(todo, "restore", "#5") == 2
        err = _unwrapped(_ANSI.sub("", capsys.readouterr().err))
        assert (
            _unwrapped(
                "@memory todo #5 NOT restored - todo #5 is ambiguous - 2 backlog records carry it: "
                "rolled 2026-09-15T01:00:00+10:00: first five; rolled 2026-09-15T03:00:00+10:00: second five. "
                "Nothing restored"
            )
            in err
        ), err
        assert todo.local.read_bytes() == pad_before
        assert todo.backlog.read_bytes() == backlog_before

    def test_restore_acts_on_the_callers_own_branch_only(self, todo, capsys, monkeypatch) -> None:
        pad_before = _todo_pad(todo, range(5, 2, -1))
        backlog_before = _todo_backlog(todo, [_todo_record(1, "fix drone help")])
        capsys.readouterr()
        assert _todo_exit(todo, "restore", "1", "--branch", "@devpulse") == 2
        err = _unwrapped(_ANSI.sub("", capsys.readouterr().err))
        assert _unwrapped("Todo #1 not restored - --branch names @devpulse, but you are in @memory") in err, err
        assert todo.local.read_bytes() == pad_before
        assert todo.backlog.read_bytes() == backlog_before
        assert not (todo.root / "src" / "aipass" / "devpulse" / ".trinity").exists()

        monkeypatch.setenv("AIPASS_CALLER_CWD", str(todo.root))
        assert _todo_exit(todo, "restore", "1", "--branch", "@memory") == 2
        err = _unwrapped(_ANSI.sub("", capsys.readouterr().err))
        assert _unwrapped("Todo #1 not restored - no branch resolved from where you stand (") in err, err
        assert todo.local.read_bytes() == pad_before

        monkeypatch.setenv("AIPASS_CALLER_CWD", str(todo.branch))
        assert _todo_exit(todo, "restore", "1", "@memory") == 0
        assert [t["number"] for t in json.loads(todo.local.read_text(encoding="utf-8"))["todos"]] == [6, 5, 4, 3]

    @pytest.mark.parametrize(
        ("args", "sentence"),
        [
            (("frobnicate",), "Unknown todo argument: 'frobnicate'"),
            (("--json",), "Unknown todo argument: '--json'"),
            (("restore",), "todo restore needs the todo's number from the backlog, got nothing"),
            (("restore", "seven"), "todo restore needs the todo's number from the backlog, got 'seven'"),
            (("backlog", "extra"), "Unknown argument: 'extra' (todo backlog)"),
            (("@memory", "extra"), "Unknown argument: 'extra' (todo)"),
            (("--branch",), "--branch needs a branch name (todo)"),
        ],
    )
    def test_a_bad_argument_is_refused_non_zero_naming_the_valid_forms(self, todo, capsys, args, sentence) -> None:
        pad_before = _todo_pad(todo, range(1, 4))
        capsys.readouterr()
        assert _todo_exit(todo, *args) == 2
        err = _unwrapped(_ANSI.sub("", capsys.readouterr().err))
        assert _unwrapped(sentence) in err, err
        for form in _TODO_FORMS:
            assert _unwrapped(form) in err, form
        assert todo.local.read_bytes() == pad_before
        assert not todo.backlog.exists()

    def test_help_in_any_slot_prints_usage_and_restores_nothing(self, todo, capsys) -> None:
        pad_before = _todo_pad(todo, range(3, 6))
        backlog_before = _todo_backlog(todo, [_todo_record(1, "fix drone help")])
        capsys.readouterr()
        assert _todo_exit(todo, "restore", "1", "--help") == 0
        out = _ANSI.sub("", capsys.readouterr().out)
        assert "USAGE:" in out
        for form in _TODO_FORMS:
            assert form in out, form
        assert todo.local.read_bytes() == pad_before
        assert todo.backlog.read_bytes() == backlog_before

    def test_the_entry_point_help_lists_the_todo_verbs(self, todo, capsys) -> None:
        """`drone @memory --help` names all three forms; the bare `drone @memory` map lists the discovered module."""
        entry = importlib.import_module("aipass.memory.apps.memory")
        capsys.readouterr()
        entry.print_help()
        out = _unwrapped(_ANSI.sub("", capsys.readouterr().out))
        for row in ("todo [@branch]", "todo backlog [@branch]", "todo restore <number>", "todo [backlog|restore]"):
            assert _unwrapped(row) in out, row

        entry.print_introspection()
        lines = [line.strip() for line in _ANSI.sub("", capsys.readouterr().out).splitlines()]
        assert "* todo" in lines, lines
