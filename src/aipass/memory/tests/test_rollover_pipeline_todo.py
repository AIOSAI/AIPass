# =================== AIPass ====================
# Name: test_rollover_pipeline_todo.py
# Description: Rollover pipeline - the todo pad rolls to a backlog file, the backlog trim and restore
# Version: 1.0.1
# Created: 2026-10-08
# Modified: 2026-10-23
# Category: memory/tests
# =============================================

"""Tests for apps/handlers/rollover/todo_roll.py — the pad's roll to its backlog, the trim and the restore."""

# All tests use mocks or tmp_path -- no live filesystem or infrastructure access.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — compose_meta(), read here as the oracle; tests/test_tab_renderer.py

import json
from datetime import datetime
from pathlib import Path

import pytest

from aipass.memory.apps.handlers import write_fence


# The live tree's pads and the real .backup/todo/ are never reachable from here.


def _todo_roll():
    """The real todo_roll handler (the harnesses above stand mocks in per test only)."""
    import importlib

    return importlib.import_module("aipass.memory.apps.handlers.rollover.todo_roll")


def _canon(value) -> str:
    """JSON equality as text: key order ignored, 1 / 1.0 / true kept distinct."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _todo(number, task=None, **extra) -> dict:
    """One todo in the pad's shape."""
    todo = {"number": number, "task": task or f"task {number}", "date": "2026-09-01", "priority": "normal"}
    todo.update(extra)
    return todo


def _todo_cap(module) -> int:
    """The live cap on a todo's task, read from the config the gate reads.

    Never a literal: a copied cap would pass on after the real one moved.
    """
    limits = module.load_entry_limits("guinea")
    return int(limits["entry_types"]["todos"]["max_chars"])


def _mint_pad(root: Path, todos: list, name: str = "guinea") -> Path:
    """A branch directory under *root* whose local memory file holds *todos*; returns that file."""
    local = root / name / ".trinity" / "local.json"
    local.parent.mkdir(parents=True, exist_ok=True)
    document = {"document_metadata": {"document_type": "session_history"}, "sessions": [], "todos": todos}
    local.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return local


def _backlog_file(tmp_path: Path, name: str = "guinea") -> Path:
    """Where the backlog lands under the tmp .backup root."""
    return tmp_path / ".backup" / "todo" / name / "backlog.json"


def _point_todos_count(monkeypatch, tmp_path: Path, tr, count: int) -> None:
    """Give the handler a throwaway config whose todos count is *count*."""
    import copy
    import importlib

    loader = importlib.import_module("aipass.memory.apps.handlers.json.config_loader")
    config = copy.deepcopy(loader.DEFAULT_CONFIG)
    config["rollover"]["defaults"]["local"]["todos"] = {"count": count}
    config["rollover"]["per_branch"] = {}
    path = tmp_path / "custom_config" / "memory.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    monkeypatch.setattr(loader, "_CONFIG_PATH", path)
    monkeypatch.setattr(tr, "config_loader", loader)


def _scratch_backlogs(tmp_path: Path, monkeypatch) -> None:
    """No pin may reach the repo's real .backup/todo/: an unrouted backlog lands under tmp_path."""
    tr = _todo_roll()
    real = tr.backlog_path_for

    def scratch(branch_dir, backup_root=None):
        return real(branch_dir, tmp_path / ".backup" if backup_root is None else backup_root)

    monkeypatch.setattr(tr, "backlog_path_for", scratch)


def _tab(next_label) -> str:
    """A todos_meta line exactly as memory's renderer writes it for @guinea (count 10, task cap 100)."""
    return (
        "⟦ pad of 10 · oldest roll to .backup/todo/guinea/backlog.json · task ≤100 chars · draft to 80"
        f" · next #{next_label} ⟧ One line of what to do."
    )


class TestTodoRoll:
    """roll_todos: append -> atomic replace -> read back -> only then prune the pad."""

    @pytest.fixture(autouse=True)
    def _backlogs_stay_in_tmp(self, tmp_path, monkeypatch):
        _scratch_backlogs(tmp_path, monkeypatch)

    @pytest.fixture
    def tr(self, tmp_path, monkeypatch):
        module = _todo_roll()
        _point_todos_count(monkeypatch, tmp_path, module, 10)
        return module

    @staticmethod
    def _roll(tr, local: Path, tmp_path: Path) -> dict:
        return tr.roll_todos("guinea", local_path=local, backup_root=tmp_path / ".backup")

    def test_the_oldest_by_number_roll_off_and_the_rest_keep_their_order(self, tr, tmp_path):
        order = [7, 1, 12, 3, 9, 2, 11, 5, 10, 4, 8, 6]
        local = _mint_pad(tmp_path, [_todo(n) for n in order])

        result = self._roll(tr, local, tmp_path)

        assert result["success"] is True, result["error"]
        assert result["numbers"] == [1, 2]
        assert [t["number"] for t in json.loads(local.read_text(encoding="utf-8"))["todos"]] == [
            n for n in order if n not in (1, 2)
        ]
        entries = json.loads(_backlog_file(tmp_path).read_text(encoding="utf-8"))["entries"]
        assert [record["entry"]["number"] for record in entries] == [1, 2]

    def test_a_backlog_outside_the_aipass_root_is_refused_and_the_pad_kept(self, tr, tmp_path, monkeypatch):
        """The backlog's directory is made BEFORE the gated write, so it needs its own fence.

        Without it the gate refuses the file but leaves an empty directory behind in the other project.
        """

        home = tmp_path / "aipass"
        monkeypatch.setattr(write_fence, "ROOT", home)
        local = _mint_pad(home, [_todo(n) for n in range(1, 13)])
        before = local.read_bytes()
        foreign_backup = tmp_path / "other_root" / ".backup"

        result = tr.roll_todos("guinea", local_path=local, backup_root=foreign_backup)

        assert result["success"] is False
        assert "NOTHING PRUNED" in result["error"]
        assert local.read_bytes() == before
        assert not (foreign_backup / "todo").exists()

    def test_the_backlog_is_the_nested_document(self, tr, tmp_path):
        local = _mint_pad(tmp_path, [_todo(n) for n in range(1, 13)])
        self._roll(tr, local, tmp_path)

        document = json.loads(_backlog_file(tmp_path).read_text(encoding="utf-8"))
        assert set(document) == {"document_metadata", "entries"}
        assert document["document_metadata"] == {"managed_by": "memory", "branch": "guinea", "high_water": 12}, (
            "high_water is the highest number on the WHOLE pad as found (the kept #12), not only the rolled #1, #2"
        )
        assert len(document["entries"]) == 2
        for record in document["entries"]:
            assert set(record) == {"rolled", "reason", "entry"}
            assert record["reason"] == "overflow"
            assert datetime.fromisoformat(record["rolled"]).tzinfo is not None

    def test_a_rolled_todo_is_json_identical_to_the_pad_copy(self, tr, tmp_path):
        odd = _todo(
            1, task="café ≤ naïve — “quoted”", tags=["a", "b"], meta={"weight": 1.0, "flag": True, "gone": None}
        )
        local = _mint_pad(tmp_path, [odd] + [_todo(n) for n in range(2, 13)])
        on_the_pad = json.loads(local.read_text(encoding="utf-8"))["todos"][0]

        self._roll(tr, local, tmp_path)

        entry = json.loads(_backlog_file(tmp_path).read_text(encoding="utf-8"))["entries"][0]["entry"]
        assert _canon(entry) == _canon(on_the_pad)

    def test_a_second_roll_appends_and_never_overwrites(self, tr, tmp_path):
        local = _mint_pad(tmp_path, [_todo(n) for n in range(1, 13)])
        self._roll(tr, local, tmp_path)
        first = json.loads(_backlog_file(tmp_path).read_text(encoding="utf-8"))["entries"]

        document = json.loads(local.read_text(encoding="utf-8"))
        document["todos"] += [_todo(n) for n in (13, 14, 15)]
        local.write_text(json.dumps(document, indent=2), encoding="utf-8")
        result = self._roll(tr, local, tmp_path)

        entries = json.loads(_backlog_file(tmp_path).read_text(encoding="utf-8"))["entries"]
        assert result["numbers"] == [3, 4, 5]
        assert entries[:2] == first, "the records already in the backlog were rewritten"
        assert [record["entry"]["number"] for record in entries] == [1, 2, 3, 4, 5]

    def test_a_backlog_that_reads_back_wrong_leaves_the_pad_untouched(self, tr, tmp_path, monkeypatch):
        """THE ORDER: the pad is pruned only after the backlog reads back json-equal."""
        local = _mint_pad(tmp_path, [_todo(n) for n in range(1, 13)])
        before = local.read_bytes()
        real_write = tr._write_document

        def tampering_write(path, document):
            if Path(path).name == "backlog.json":
                document = json.loads(json.dumps(document))
                document["entries"][-1]["entry"]["task"] = "silently changed on the way to disk"
            return real_write(path, document)

        monkeypatch.setattr(tr, "_write_document", tampering_write)
        result = self._roll(tr, local, tmp_path)

        assert result["success"] is False
        assert result["error"].startswith("NOTHING PRUNED - backlog read-back failed"), result["error"]
        assert local.read_bytes() == before

    def test_a_refused_backlog_write_leaves_the_pad_untouched(self, tr, tmp_path, monkeypatch):
        local = _mint_pad(tmp_path, [_todo(n) for n in range(1, 13)])
        before = local.read_bytes()
        real_write = tr._write_document
        monkeypatch.setattr(
            tr,
            "_write_document",
            lambda path, document: "disk full" if Path(path).name == "backlog.json" else real_write(path, document),
        )

        result = self._roll(tr, local, tmp_path)

        assert result["success"] is False
        assert "NOTHING PRUNED" in result["error"] and "disk full" in result["error"]
        assert local.read_bytes() == before

    def test_an_unreadable_backlog_is_refused_and_never_written_over(self, tr, tmp_path):
        local = _mint_pad(tmp_path, [_todo(n) for n in range(1, 13)])
        before = local.read_bytes()
        backlog = _backlog_file(tmp_path)
        backlog.parent.mkdir(parents=True)
        backlog.write_text("{not json", encoding="utf-8")

        result = self._roll(tr, local, tmp_path)

        assert result["success"] is False
        assert "never written over" in result["error"]
        assert backlog.read_text(encoding="utf-8") == "{not json"
        assert local.read_bytes() == before

    def test_a_pad_within_its_count_writes_nothing(self, tr, tmp_path):
        local = _mint_pad(tmp_path, [_todo(n) for n in range(1, 11)])
        before = local.read_bytes()

        result = self._roll(tr, local, tmp_path)

        assert result["success"] is True and result["rolled"] == 0
        assert local.read_bytes() == before
        assert not (tmp_path / ".backup").exists()

    def test_the_count_comes_from_config(self, tr, tmp_path, monkeypatch):
        _point_todos_count(monkeypatch, tmp_path, tr, 4)
        local = _mint_pad(tmp_path, [_todo(n) for n in range(1, 7)])

        result = self._roll(tr, local, tmp_path)

        assert result["count"] == 4
        assert result["numbers"] == [1, 2]

    def test_high_water_is_raised_never_lowered_and_an_old_backlog_still_takes_a_roll(self, tr, tmp_path):
        """A backlog written before high_water existed has no floor, never an error; the roll stamps one."""
        backlog = _backlog_file(tmp_path)
        backlog.parent.mkdir(parents=True)
        earlier = {"rolled": "2026-09-14T23:00:00+00:00", "reason": "overflow", "entry": _todo(1)}
        backlog.write_text(
            json.dumps({"document_metadata": {"managed_by": "memory", "branch": "guinea"}, "entries": [earlier]}),
            encoding="utf-8",
        )
        local = _mint_pad(tmp_path, [_todo(n) for n in range(13, 1, -1)])

        first = self._roll(tr, local, tmp_path)

        assert first["success"] is True, first["error"]
        assert tr.high_water_of(tr.read_backlog(backlog)["document"]) == 13

        document = json.loads(backlog.read_text(encoding="utf-8"))
        document["document_metadata"]["high_water"] = 99
        backlog.write_text(json.dumps(document), encoding="utf-8")
        pad = json.loads(local.read_text(encoding="utf-8"))
        pad["todos"] = [_todo(n) for n in (16, 15, 14)] + pad["todos"]
        local.write_text(json.dumps(pad), encoding="utf-8")

        second = self._roll(tr, local, tmp_path)

        assert second["success"] is True, second["error"]
        back = tr.read_backlog(backlog)
        assert tr.high_water_of(back["document"]) == 99, "a roll never lowers high_water"
        assert [record["entry"]["number"] for record in back["entries"]] == [1, 2, 3, 4, 5, 6]

    def test_a_high_water_that_reads_back_wrong_leaves_the_pad_untouched(self, tr, tmp_path, monkeypatch):
        """high_water is read back like every record: a drifted floor prunes nothing."""
        local = _mint_pad(tmp_path, [_todo(n) for n in range(12, 0, -1)])
        before = local.read_bytes()
        real_write = tr._write_document

        def tampering_write(path, document):
            if Path(path).name == "backlog.json":
                document = json.loads(json.dumps(document))
                document["document_metadata"]["high_water"] = 3
            return real_write(path, document)

        monkeypatch.setattr(tr, "_write_document", tampering_write)
        result = self._roll(tr, local, tmp_path)

        assert result["success"] is False
        assert result["error"].startswith("NOTHING PRUNED - backlog read-back failed"), result["error"]
        assert "document_metadata (high_water) does not read back as written" in result["error"]
        assert local.read_bytes() == before


class TestTodoTarget:
    """ONE branch, keyed by directory name, from --branch or where the caller stood."""

    @staticmethod
    def _fleet(tmp_path: Path) -> list:
        return [
            {"name": "guinea", "path": str(tmp_path / "src" / "aipass" / "guinea"), "residency": "core"},
            {"name": "pig", "path": str(tmp_path / "projects" / "farm" / "pig"), "residency": "resident"},
        ]

    def test_a_directory_name_shared_by_core_and_resident_is_refused_by_name(self, tmp_path):
        tr = _todo_roll()
        twin = tmp_path / "projects" / "guinea" / "guinea"
        fleet = self._fleet(tmp_path) + [{"name": "guinea", "path": str(twin), "residency": "resident"}]
        local = _mint_pad(tmp_path / "src" / "aipass", [_todo(n) for n in range(1, 13)])
        before = local.read_bytes()

        target = tr.resolve_target("@guinea", fleet=fleet, backup_root=tmp_path / ".backup")
        result = tr.roll_todos("guinea", fleet=fleet, backup_root=tmp_path / ".backup")

        assert target["name"] is None
        assert "REFUSED: directory name 'guinea' is shared by 2 branches" in target["error"]
        assert f"core at {tmp_path / 'src' / 'aipass' / 'guinea'}" in target["error"]
        assert f"resident at {twin}" in target["error"]
        assert result["success"] is False and "REFUSED" in result["error"]
        assert local.read_bytes() == before
        assert not (tmp_path / ".backup").exists()

    def test_the_backlog_is_keyed_by_directory_name(self, tmp_path):
        tr = _todo_roll()
        target = tr.resolve_target("@GUINEA", fleet=self._fleet(tmp_path), backup_root=tmp_path / ".backup")

        assert target["name"] == "guinea"
        assert target["backlog"] == _backlog_file(tmp_path, "guinea")
        assert target["local"] == tmp_path / "src" / "aipass" / "guinea" / ".trinity" / "local.json"

    def test_the_caller_cwd_resolves_the_branch_it_stands_in(self, tmp_path):
        tr = _todo_roll()
        where = tmp_path / "projects" / "farm" / "pig" / "apps" / "modules"

        target = tr.resolve_target(fleet=self._fleet(tmp_path), environ={"AIPASS_CALLER_CWD": str(where)})

        assert target["name"] == "pig"

    def test_the_repo_root_resolves_no_branch(self, tmp_path):
        tr = _todo_roll()

        target = tr.resolve_target(fleet=self._fleet(tmp_path), environ={"AIPASS_CALLER_CWD": str(tmp_path)})

        assert target["name"] is None and target["error"] is None
        assert "is not inside a registered branch directory" in target["reason"]

    def test_a_branch_name_without_a_caller_cwd_is_no_evidence(self, tmp_path, monkeypatch):
        """Drone runs @memory from memory's own directory: that cwd says nothing about the caller."""
        tr = _todo_roll()
        branch = tmp_path / "src" / "aipass" / "guinea"
        branch.mkdir(parents=True)
        monkeypatch.chdir(branch)

        launched = tr.resolve_target(fleet=self._fleet(tmp_path), environ={"AIPASS_BRANCH_NAME": "memory"})
        bare = tr.resolve_target(fleet=self._fleet(tmp_path), environ={})

        assert launched["name"] is None
        assert "AIPASS_BRANCH_NAME is set without AIPASS_CALLER_CWD" in launched["reason"]
        assert bare["name"] == "guinea", "with no launcher at all, the process cwd is the caller's"


def _point_backlog_ceiling(monkeypatch, tmp_path: Path, tr, ceiling) -> None:
    """Rewrite the throwaway config's ``rollover.backlog.max_records`` in place.

    Written, not monkeypatched onto the accessor, so the pins measure the config read too.
    """
    del tr  # the loader is repointed by _point_todos_count; kept for call-site symmetry
    path = tmp_path / "custom_config" / "memory.config.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    if ceiling is None:
        config["rollover"].pop("backlog", None)
    else:
        config["rollover"]["backlog"] = {"max_records": ceiling}
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


class TestTheBacklogTrim:
    """A backlog past its ceiling moves its oldest records to a SIBLING archive.

    A backlog is the only copy of a rolled todo (never vectorised): trim moves deeper, never deletes.
    """

    @pytest.fixture(autouse=True)
    def _backlogs_stay_in_tmp(self, tmp_path, monkeypatch):
        _scratch_backlogs(tmp_path, monkeypatch)

    @pytest.fixture
    def tr(self, tmp_path, monkeypatch):
        module = _todo_roll()
        _point_todos_count(monkeypatch, tmp_path, module, 10)
        return module

    @staticmethod
    def _backlog_of(tmp_path: Path, count: int, start: int = 1) -> Path:
        path = _backlog_file(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        records = [
            {"rolled": f"2026-09-01T10:00:{index % 60:02d}+00:00", "reason": "overflow", "entry": _todo(index)}
            for index in range(start, start + count)
        ]
        document = {
            "document_metadata": {"managed_by": "memory", "branch": "guinea", "high_water": start + count - 1},
            "entries": records,
        }
        path.write_text(json.dumps(document, indent=2), encoding="utf-8")
        return path

    @staticmethod
    def _numbers(path: Path) -> list:
        if not path.exists():
            return []
        return [record["entry"]["number"] for record in json.loads(path.read_text(encoding="utf-8"))["entries"]]

    def test_a_backlog_within_its_ceiling_is_not_touched(self, tr, tmp_path):
        backlog = self._backlog_of(tmp_path, 5)
        before = backlog.read_bytes()

        result = tr.trim_backlog(backlog, "guinea", ceiling=10)

        assert result["success"] is True
        assert result["archived"] == 0
        assert backlog.read_bytes() == before
        assert not tr.archive_path_for(backlog).exists(), "an archive was created with nothing to put in it"

    def test_a_backlog_exactly_at_its_ceiling_is_not_touched(self, tr, tmp_path):
        backlog = self._backlog_of(tmp_path, 10)

        assert tr.trim_backlog(backlog, "guinea", ceiling=10)["archived"] == 0
        assert len(self._numbers(backlog)) == 10

    def test_the_oldest_records_move_to_the_sibling_archive_and_none_is_lost(self, tr, tmp_path):
        backlog = self._backlog_of(tmp_path, 14)

        result = tr.trim_backlog(backlog, "guinea", ceiling=10)

        assert result["success"] is True, result["error"]
        assert result["archived"] == 4
        assert self._numbers(backlog) == [5, 6, 7, 8, 9, 10, 11, 12, 13, 14]
        assert self._numbers(tr.archive_path_for(backlog)) == [1, 2, 3, 4]

    def test_an_archived_record_is_carried_json_equal_not_reshaped(self, tr, tmp_path):
        backlog = self._backlog_of(tmp_path, 12)
        original = json.loads(backlog.read_text(encoding="utf-8"))["entries"][0]

        tr.trim_backlog(backlog, "guinea", ceiling=10)

        archived = json.loads(tr.archive_path_for(backlog).read_text(encoding="utf-8"))["entries"][0]
        assert archived == original, "the archive rewrote the record on its way in"

    def test_the_archive_is_verified_before_the_backlog_is_shortened(self, tr, tmp_path, monkeypatch):
        # A record may sit in both files for an instant, and must never sit in neither.
        backlog = self._backlog_of(tmp_path, 12)
        writes = []
        real_write = tr._write_document
        monkeypatch.setattr(
            tr, "_write_document", lambda path, doc: writes.append(Path(path).name) or real_write(path, doc)
        )

        tr.trim_backlog(backlog, "guinea", ceiling=10)

        assert writes == ["backlog.archive.json", "backlog.json"]

    def test_an_archive_that_does_not_land_leaves_the_backlog_whole(self, tr, tmp_path, monkeypatch):
        backlog = self._backlog_of(tmp_path, 12)
        before = backlog.read_bytes()
        real_write = tr._write_document
        monkeypatch.setattr(
            tr,
            "_write_document",
            lambda path, doc: "disk full" if Path(path).name == "backlog.archive.json" else real_write(path, doc),
        )

        result = tr.trim_backlog(backlog, "guinea", ceiling=10)

        assert result["success"] is False
        assert "NOTHING TRIMMED" in result["error"]
        assert backlog.read_bytes() == before, "records left the backlog with nowhere to go"

    def test_high_water_survives_a_trim_so_a_number_is_never_re_issued(self, tr, tmp_path):
        # The archive is unreachable from `todo restore`, so the floor must outlive the record.
        backlog = self._backlog_of(tmp_path, 12)

        tr.trim_backlog(backlog, "guinea", ceiling=10)

        document = json.loads(backlog.read_text(encoding="utf-8"))
        assert tr.high_water_of(document) == 12

    def test_a_second_trim_appends_to_the_archive_rather_than_replacing_it(self, tr, tmp_path):
        backlog = self._backlog_of(tmp_path, 12)
        tr.trim_backlog(backlog, "guinea", ceiling=10)
        self._backlog_of(tmp_path, 12, start=13)

        tr.trim_backlog(backlog, "guinea", ceiling=10)

        assert self._numbers(tr.archive_path_for(backlog)) == [1, 2, 13, 14]

    def test_an_archive_belonging_to_another_branch_is_refused(self, tr, tmp_path):
        backlog = self._backlog_of(tmp_path, 12)
        archive = tr.archive_path_for(backlog)
        archive.write_text(
            json.dumps({"document_metadata": {"managed_by": "memory", "branch": "elsewhere"}, "entries": []}),
            encoding="utf-8",
        )

        result = tr.trim_backlog(backlog, "guinea", ceiling=10)

        assert result["success"] is False
        assert "belongs to 'elsewhere'" in result["error"]
        assert len(self._numbers(backlog)) == 12

    def test_the_ceiling_is_read_from_the_config_when_none_is_passed(self, tr, tmp_path, monkeypatch):
        # The CONTROL for the parametrized guard below, which would otherwise pass vacuously.
        backlog = self._backlog_of(tmp_path, 12)
        _point_backlog_ceiling(monkeypatch, tmp_path, tr, 10)

        result = tr.trim_backlog(backlog, "guinea")

        assert result["archived"] == 2, result["error"]
        assert self._numbers(tr.archive_path_for(backlog)) == [1, 2]

    @pytest.mark.parametrize("ceiling", [None, 0, -3, "100", True])
    def test_an_unusable_ceiling_means_no_trim_never_a_trim_to_zero(self, tr, tmp_path, monkeypatch, ceiling):
        backlog = self._backlog_of(tmp_path, 12)
        _point_backlog_ceiling(monkeypatch, tmp_path, tr, ceiling)

        result = tr.trim_backlog(backlog, "guinea")

        assert result["archived"] == 0
        assert len(self._numbers(backlog)) == 12
        assert not tr.archive_path_for(backlog).exists()

    def test_a_missing_backlog_is_a_state_not_an_error(self, tr, tmp_path):
        result = tr.trim_backlog(_backlog_file(tmp_path), "guinea", ceiling=10)

        assert result["success"] is True
        assert result["archived"] == 0

    def test_the_roll_trims_on_its_way_past(self, tr, tmp_path, monkeypatch):
        # The trim hangs off append_to_backlog, the one choke point the roll and the push share.
        _point_backlog_ceiling(monkeypatch, tmp_path, tr, 10)
        self._backlog_of(tmp_path, 10)
        local = _mint_pad(tmp_path, [_todo(n) for n in range(20, 33)])

        result = tr.roll_todos("guinea", local_path=local, backup_root=tmp_path / ".backup")

        assert result["success"] is True, result["error"]
        assert len(self._numbers(_backlog_file(tmp_path))) == 10, "the backlog grew past its ceiling"
        assert self._numbers(tr.archive_path_for(_backlog_file(tmp_path))) == [1, 2, 3]

    def test_a_failed_trim_never_fails_the_append(self, tr, tmp_path, monkeypatch):
        # A trim that could veto the append would strand open work on a full pad.
        _point_backlog_ceiling(monkeypatch, tmp_path, tr, 10)
        self._backlog_of(tmp_path, 10)
        monkeypatch.setattr(tr, "trim_backlog", lambda *a, **k: {"success": False, "archived": 0, "error": "boom"})
        local = _mint_pad(tmp_path, [_todo(n) for n in range(20, 33)])

        result = tr.roll_todos("guinea", local_path=local, backup_root=tmp_path / ".backup")

        assert result["success"] is True, result["error"]
        assert [t["number"] for t in json.loads(local.read_text(encoding="utf-8"))["todos"]] == list(range(23, 33))


class TestTodoRestore:
    """restore_todo: pad first, then the backlog - never in neither place."""

    @pytest.fixture(autouse=True)
    def _backlogs_stay_in_tmp(self, tmp_path, monkeypatch):
        _scratch_backlogs(tmp_path, monkeypatch)

    @pytest.fixture
    def tr(self, tmp_path, monkeypatch):
        module = _todo_roll()
        _point_todos_count(monkeypatch, tmp_path, module, 10)
        return module

    @staticmethod
    def _backlog_with(tmp_path: Path, records: list) -> Path:
        path = _backlog_file(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {"document_metadata": {"managed_by": "memory", "branch": "guinea"}, "entries": records}
        path.write_text(json.dumps(document, indent=2), encoding="utf-8")
        return path

    @staticmethod
    def _record(todo: dict, rolled: str = "2026-09-01T10:00:00+00:00") -> dict:
        return {"rolled": rolled, "reason": "overflow", "entry": todo}

    @staticmethod
    def _restore(tr, number, local: Path, tmp_path: Path) -> dict:
        return tr.restore_todo("guinea", number, local_path=local, backup_root=tmp_path / ".backup")

    def test_restore_reissues_the_next_number_and_carries_every_other_field(self, tr, tmp_path):
        original = _todo(2, task="bring it back", priority="high")
        local = _mint_pad(tmp_path, [_todo(n) for n in (5, 9, 3)])
        backlog = self._backlog_with(
            tmp_path, [self._record(_todo(1)), self._record(original), self._record(_todo(14))]
        )

        result = self._restore(tr, 2, local, tmp_path)

        assert result["success"] is True, result["error"]
        assert result["number"] == 15, "max(pad 9, backlog originals 14) + 1"
        assert json.loads(local.read_text(encoding="utf-8"))["todos"][0] == {**original, "number": 15}
        remaining = json.loads(backlog.read_text(encoding="utf-8"))["entries"]
        assert [record["entry"]["number"] for record in remaining] == [1, 14]

    def test_restoring_a_non_canonical_todo_is_refused_and_the_field_is_named(self, tr, tmp_path):
        # Restore must never reshape a record to pass the gate, so the honest outcome is a refusal.
        # The field substring is asserted exactly: a loose `or` passed on a refusal that named nothing.
        original = _todo(2, task="bring it back", tags=["x"])
        local = _mint_pad(tmp_path, [_todo(5)])
        backlog = self._backlog_with(tmp_path, [self._record(original)])

        result = self._restore(tr, 2, local, tmp_path)

        assert result["success"] is False
        assert "field 'tags' is not part of the entry shape" in result["error"], result["error"]
        assert "NOTHING RESTORED" in result["error"]
        assert [t["number"] for t in json.loads(local.read_text(encoding="utf-8"))["todos"]] == [5]
        assert [r["entry"]["number"] for r in json.loads(backlog.read_text(encoding="utf-8"))["entries"]] == [2]

    def test_every_broken_rule_is_named_in_one_refusal_not_one_per_attempt(self, tr, tmp_path):
        cap = _todo_cap(tr)
        original = _todo(2, task="x" * (cap + 17), status="open")
        local = _mint_pad(tmp_path, [_todo(5)])
        self._backlog_with(tmp_path, [self._record(original)])

        error = self._restore(tr, 2, local, tmp_path)["error"]

        assert "field 'status' is not part of the entry shape" in error, error
        assert f"'task' is {cap + 17}/{cap} chars (+17 over)" in error, error

    def test_the_refusal_lands_before_anything_is_written(self, tr, tmp_path, monkeypatch):
        writes = []
        monkeypatch.setattr(tr, "_write_document", lambda path, document: writes.append(Path(path).name))
        local = _mint_pad(tmp_path, [_todo(5)])
        self._backlog_with(tmp_path, [self._record(_todo(2, task="bring it back", tags=["x"]))])

        assert self._restore(tr, 2, local, tmp_path)["success"] is False
        assert writes == [], f"the shape check ran after a write: {writes}"

    def test_a_legal_record_passes_the_shape_check_untouched(self, tr, tmp_path):
        # A pre-flight stricter than the gate it predicts is a new dead end.
        local = _mint_pad(tmp_path, [_todo(5)])
        self._backlog_with(tmp_path, [self._record(_todo(2, task="bring it back", priority="high"))])

        result = self._restore(tr, 2, local, tmp_path)

        assert result["success"] is True, result["error"]

    def test_the_check_reports_and_never_repairs(self, tr, tmp_path):
        # Cut-to-fit vs verbatim for an over-cap task is an open ruling; a quiet trim would decide it.
        cap = _todo_cap(tr)
        original = _todo(2, task="x" * (cap * 2))
        local = _mint_pad(tmp_path, [_todo(5)])
        backlog = self._backlog_with(tmp_path, [self._record(original)])

        assert self._restore(tr, 2, local, tmp_path)["success"] is False
        record = json.loads(backlog.read_text(encoding="utf-8"))["entries"][0]["entry"]
        assert record["task"] == "x" * (cap * 2), "the backlog record was reshaped"
        assert json.loads(local.read_text(encoding="utf-8"))["todos"] == [_todo(5)]

    def test_the_pad_is_written_before_the_backlog_is_touched(self, tr, tmp_path, monkeypatch):
        local = _mint_pad(tmp_path, [_todo(3)])
        self._backlog_with(tmp_path, [self._record(_todo(1))])
        real_write = tr._write_document
        writes = []

        def recording_write(path, document):
            writes.append(Path(path).name)
            return real_write(path, document)

        monkeypatch.setattr(tr, "_write_document", recording_write)

        assert self._restore(tr, 1, local, tmp_path)["success"] is True
        assert writes == ["local.json", "backlog.json"]

    def test_a_pad_that_does_not_land_leaves_the_backlog_untouched(self, tr, tmp_path, monkeypatch):
        local = _mint_pad(tmp_path, [_todo(3)])
        backlog = self._backlog_with(tmp_path, [self._record(_todo(1))])
        pad_before, backlog_before = local.read_bytes(), backlog.read_bytes()
        real_write = tr._write_document
        monkeypatch.setattr(
            tr,
            "_write_document",
            lambda path, document: "disk full" if Path(path).name == "local.json" else real_write(path, document),
        )

        result = self._restore(tr, 1, local, tmp_path)

        assert result["success"] is False
        assert result["error"].startswith("NOTHING RESTORED"), result["error"]
        assert backlog.read_bytes() == backlog_before
        assert local.read_bytes() == pad_before

    def test_an_ambiguous_number_is_refused_naming_every_candidate(self, tr, tmp_path):
        local = _mint_pad(tmp_path, [_todo(8)])
        backlog = self._backlog_with(
            tmp_path,
            [
                self._record(_todo(4, task="first four"), rolled="2026-09-01T10:00:00+00:00"),
                self._record(_todo(6)),
                self._record(_todo(4, task="second four"), rolled="2026-09-10T08:30:00+00:00"),
            ],
        )
        pad_before, backlog_before = local.read_bytes(), backlog.read_bytes()

        result = self._restore(tr, 4, local, tmp_path)

        assert result["success"] is False
        assert "todo #4 is ambiguous - 2 backlog records carry it" in result["error"]
        assert "rolled 2026-09-01T10:00:00+00:00: first four" in result["error"]
        assert "rolled 2026-09-10T08:30:00+00:00: second four" in result["error"]
        assert local.read_bytes() == pad_before and backlog.read_bytes() == backlog_before

    def test_a_full_pad_is_refused_at_the_count_config_names(self, tr, tmp_path, monkeypatch):
        _point_todos_count(monkeypatch, tmp_path, tr, 3)
        local = _mint_pad(tmp_path, [_todo(n) for n in (2, 3, 4)])
        backlog = self._backlog_with(tmp_path, [self._record(_todo(1))])
        pad_before, backlog_before = local.read_bytes(), backlog.read_bytes()

        refused = self._restore(tr, 1, local, tmp_path)

        assert refused["success"] is False
        assert refused["error"] == "pad is full (3/3) - finish or delete one before restoring #1"
        assert local.read_bytes() == pad_before and backlog.read_bytes() == backlog_before

        _point_todos_count(monkeypatch, tmp_path, tr, 4)
        assert self._restore(tr, 1, local, tmp_path)["success"] is True, "the count is config's, not a literal"

    def test_an_unknown_number_is_refused(self, tr, tmp_path):
        local = _mint_pad(tmp_path, [_todo(3)])
        backlog = self._backlog_with(tmp_path, [self._record(_todo(1))])

        result = self._restore(tr, 99, local, tmp_path)

        assert result["success"] is False
        assert result["error"] == f"no todo #99 in the backlog at {backlog}"

    def test_no_backlog_is_an_honest_answer_not_an_error(self, tr, tmp_path):
        missing = _backlog_file(tmp_path)
        state = tr.read_backlog(missing)

        assert state["exists"] is False
        assert state["error"] is None
        assert state["entries"] == []
        assert state["message"].startswith(f"no backlog at {missing} - nothing has rolled off this pad")

        local = _mint_pad(tmp_path, [_todo(4)])
        result = self._restore(tr, 1, local, tmp_path)
        assert result["success"] is False and result["error"] == state["message"]
        assert tr.next_number([_todo(4)], state["entries"]) == 5
        assert not (tmp_path / ".backup").exists()

    def test_the_next_number_spans_pad_and_backlog(self, tr, tmp_path):
        assert tr.next_number([], []) == 1
        assert tr.next_number([{"number": 3}], [{"entry": {"number": 9}}]) == 10
        assert tr.next_number([{"number": True}], [{"entry": {"number": "7"}}]) == 1

        backlog = self._backlog_with(tmp_path, [self._record(_todo(11))])
        assert tr.next_number([_todo(2)], tr.read_backlog(backlog)["entries"]) == 12

    def test_the_restored_todo_lands_on_top_and_the_pad_stays_newest_first(self, tr, tmp_path):
        """@canary's audit went 99: a restore appended at the tail - 'number 12 is not below the entry above it'."""
        local = _mint_pad(tmp_path, [_todo(n) for n in (9, 5, 3)])
        self._backlog_with(tmp_path, [self._record(_todo(2, task="bring it back"))])

        result = self._restore(tr, 2, local, tmp_path)

        assert result["success"] is True, result["error"]
        pad = json.loads(local.read_text(encoding="utf-8"))["todos"]
        assert pad[0] == _todo(10, task="bring it back")
        numbers = [todo["number"] for todo in pad]
        assert numbers == sorted(set(numbers), reverse=True) == [10, 9, 5, 3], "strictly descending"

    def test_a_restored_then_deleted_number_is_never_issued_again(self, tr, tmp_path):
        """restore -> delete the restored todo by hand -> the next restore skips its number (high_water)."""
        local = _mint_pad(tmp_path, [_todo(3)])
        backlog = self._backlog_with(tmp_path, [self._record(_todo(1)), self._record(_todo(2))])
        assert tr.high_water_of(tr.read_backlog(backlog)["document"]) is None, "a backlog from before: no floor"

        first = self._restore(tr, 1, local, tmp_path)

        assert first["success"] is True and first["number"] == 4, first
        assert tr.high_water_of(tr.read_backlog(backlog)["document"]) == 4, "restore stamps high_water"

        document = json.loads(local.read_text(encoding="utf-8"))
        document["todos"] = [todo for todo in document["todos"] if todo["number"] != 4]
        local.write_text(json.dumps(document, indent=2), encoding="utf-8")

        second = self._restore(tr, 2, local, tmp_path)

        assert second["success"] is True, second["error"]
        assert second["number"] == 5, "#4 was issued and deleted: it is never handed out again"
        assert [todo["number"] for todo in json.loads(local.read_text(encoding="utf-8"))["todos"]] == [5, 3]
        assert tr.high_water_of(tr.read_backlog(backlog)["document"]) == 5

    def test_the_tab_the_pad_last_rendered_lifts_the_restored_number(self, tr, tmp_path):
        """The pad's own next #20 is a floor: #3..#19 were issued and deleted by hand before this backlog knew."""
        local = _mint_pad(tmp_path, [_todo(3)])
        document = json.loads(local.read_text(encoding="utf-8"))
        document["todos_meta"] = _tab(20)
        local.write_text(json.dumps(document, indent=2), encoding="utf-8")
        backlog = self._backlog_with(tmp_path, [self._record(_todo(1)), self._record(_todo(2))])

        result = self._restore(tr, 1, local, tmp_path)

        assert result["success"] is True and result["number"] == 20, result
        assert tr.high_water_of(tr.read_backlog(backlog)["document"]) == 20

    def test_the_restore_re_renders_the_tab_to_the_number_after_the_fresh_one(self, tr, tmp_path):
        """@canary: restore 3 -> #15 left the tab at next #15 with #15 on the pad - a hand copy would collide."""
        import importlib

        local = _mint_pad(tmp_path, [_todo(n) for n in (14, 11, 4)])
        document = json.loads(local.read_text(encoding="utf-8"))
        document["todos_meta"] = _tab(15)
        local.write_text(json.dumps(document, indent=2), encoding="utf-8")
        backlog = self._backlog_with(tmp_path, [self._record(_todo(3))])

        result = self._restore(tr, 3, local, tmp_path)

        assert result["success"] is True and result["number"] == 15, result
        after = json.loads(local.read_text(encoding="utf-8"))
        assert " · next #16 ⟧ " in after["todos_meta"], after["todos_meta"]
        renderer = importlib.import_module("aipass.memory.apps.handlers.tracking.tab_renderer")
        config = tr.config_loader.load()
        context = renderer.todo_context("guinea", after["todos"], tr.read_backlog(backlog))
        expected = renderer.compose_meta("todos", config["rollover"], config["entry_limits"], "guinea", context)
        assert after["todos_meta"].encode("utf-8") == expected.encode("utf-8")

    def test_a_high_water_that_reads_back_wrong_is_reported_not_silent(self, tr, tmp_path, monkeypatch):
        local = _mint_pad(tmp_path, [_todo(3)])
        self._backlog_with(tmp_path, [self._record(_todo(1))])
        real_write = tr._write_document

        def tampering_write(path, document):
            if Path(path).name == "backlog.json":
                document = json.loads(json.dumps(document))
                document["document_metadata"]["high_water"] = 1
            return real_write(path, document)

        monkeypatch.setattr(tr, "_write_document", tampering_write)
        result = self._restore(tr, 1, local, tmp_path)

        assert result["success"] is False
        assert "document_metadata (high_water) does not read back as written" in result["error"], result["error"]
        assert result["error"].endswith("it is in both places, never in neither")

    def test_the_floors_lift_the_number_and_garbage_is_no_floor(self, tr):
        """high_water and the tab's N - 1 lift next_number; a bool, a string, #? or foreign text do not."""
        assert tr.next_number([_todo(3)], [], high_water=40) == 41
        assert tr.next_number([_todo(3)], [], tab_floor=40) == 41
        assert tr.next_number([_todo(50)], [], high_water=40, tab_floor=12) == 51, "a floor never lowers"
        assert tr.next_number([], [], high_water=True, tab_floor=False) == 1, "a bool is not a number"

        assert tr.high_water_of({"document_metadata": {"managed_by": "memory", "high_water": 7}}) == 7
        for document in (
            {"document_metadata": {"managed_by": "memory"}},
            {"document_metadata": {"high_water": True}},
            {"document_metadata": {"high_water": "7"}},
            {"document_metadata": {"high_water": 7.0}},
            {"document_metadata": "high_water"},
            None,
        ):
            assert tr.high_water_of(document) is None, document

        assert tr.floor_from_tab(_tab(20)) == 19
        assert tr.floor_from_tab("⟦ no pad size configured — nothing rolls · task ≤100 chars · next #3 ⟧ x") == 2
        for garbage in (_tab("?"), _tab(0), _tab(-4), _tab("2x"), "next #20", "see ⟦ a · next #20 ⟧", None, 20):
            assert tr.floor_from_tab(garbage) is None, garbage
