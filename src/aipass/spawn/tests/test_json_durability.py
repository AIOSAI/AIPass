# =================== META ====================
# Name: test_json_durability.py
# Description: Torn-write durability tests for spawn's JSON/text write paths
# Version: 1.1.3
# Created: 2026-08-16
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/atomic_write.py and the write paths it makes durable."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(documentation) — docstrings on the handler functions this file drives
# seedgo: no-test-needed(stdlib) — tempfile.mkstemp's filename-uniqueness guarantee

import ast
import errno
import json
import logging
import os
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from aipass.spawn.apps.handlers import file_ops, regenerate_registry_ops, update_ops
from aipass.spawn.apps.handlers.atomic_write import atomic_write_text
from aipass.spawn.apps.handlers.json import json_handler
from aipass.spawn.apps.handlers.meta_ops import save_branch_meta
from aipass.spawn.apps.handlers.registry import save_registry
from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity
import aipass.spawn.apps.handlers.atomic_write as aw
import aipass.spawn.apps.handlers.registry as registry_mod

logger = logging.getLogger(__name__)


def _update_merge(world) -> str:
    """Run the public update once over merge_world; answer what it did to config.json."""
    result = update_ops.update_branch("branch", dry_run=False, registry_path=world["registry"])
    if result["errors"]:
        return "error"
    return "updated" if "config.json" in [d["branch_path"] for d in result["_updates_detail"]] else "unchanged"


# ``open(path, 'w')`` / ``write_text`` truncate in place, so a concurrent reader can read an empty or
# half-written file. Required shape: mkstemp(dir=target.parent), write, fsync, close, os.replace.


RACE_SECONDS = 0.6

# Bounds the wait for both sides to go live; generous on purpose, it bounds a hang, not a race.
RACE_WARMUP_SECONDS = 20.0

# The fault injectors fire only on this marker, so pytest's own I/O is never disturbed.
SENTINEL = "SPAWN-DURABILITY-FAULT-a1b2c3"


class _ModuleView:
    """atomic_write's OWN binding of a stdlib module, with named functions swapped.

    Patch the consuming module's binding, never the shared ``os`` / ``tempfile``: that reaches every thread.
    """

    def __init__(self, real, **overrides):
        self._real = real
        self.__dict__.update(overrides)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _Racer:
    """Runs writer threads against reader threads over one target file.

    A durable write path yields zero EMPTY and zero UNPARSEABLE reads however the threads interleave.
    """

    def __init__(self, target: Path, write_once, writers: int = 1, readers: int = 2):
        self.target = Path(target)
        self.write_once = write_once
        self.writers = writers
        self.readers = readers
        self.empty = 0
        self.unparseable = 0
        self.reads = 0
        self.writes = 0
        self.missing = 0
        self.refused = 0
        self.warmed_up = False
        self._stop = False
        self._lock = threading.Lock()
        # Set on first success so run() can wait for a live race; the counters merge only at join.
        self._saw_read = threading.Event()
        self._saw_write = threading.Event()

    def _writer(self):
        n = 0
        effective = 0
        while not self._stop:
            # A zero-delay loop keeps a replace in flight and Windows then refuses every reader open.
            time.sleep(0.001)
            # Count real rewrites, not loop turns, or a race passes vacuously.
            if self.write_once(n) is True:
                effective += 1
                self._saw_write.set()
            n += 1
        with self._lock:
            self.writes += effective

    def _reader(self):
        reads = empty = unparseable = missing = refused = 0
        while not self._stop:
            # Windows share-mode: a spinning reader starves os.replace's bounded retry (WinError 5).
            time.sleep(0.001)
            try:
                raw = self.target.read_text(encoding="utf-8")
            except FileNotFoundError:
                # Counted so the skip reason can tell a slow starter from a starved scheduler.
                missing += 1
                logger.debug("racer: target absent: %s", self.target)
                continue
            except PermissionError as exc:
                # Share-mode refusal during a replace: not a torn read, counted apart.
                refused += 1
                logger.debug("racer: open refused: %s (%s)", self.target, exc)
                continue
            reads += 1
            self._saw_read.set()
            if raw == "":
                empty += 1
                continue
            try:
                json.loads(raw)
            except json.JSONDecodeError as exc:
                unparseable += 1
                logger.warning("racer: torn read of %s: %s", self.target, exc)
        with self._lock:
            self.reads += reads
            self.empty += empty
            self.unparseable += unparseable
            self.missing += missing
            self.refused += refused

    def run(self, seconds: float = RACE_SECONDS, warmup: float = RACE_WARMUP_SECONDS):
        """Start the threads, wait until both sides are live, then race.

        Without the wait a loaded machine can end the window before the reader is ever scheduled.
        """
        threads = [threading.Thread(target=self._writer) for _ in range(self.writers)]
        threads += [threading.Thread(target=self._reader) for _ in range(self.readers)]
        for t in threads:
            t.start()

        # One shared deadline: the two waits together never exceed ``warmup``.
        deadline = time.monotonic() + warmup
        self._saw_read.wait(timeout=warmup)
        self._saw_write.wait(timeout=max(0.0, deadline - time.monotonic()))
        self.warmed_up = self._saw_read.is_set() and self._saw_write.is_set()

        time.sleep(seconds)
        self._stop = True
        for t in threads:
            t.join(timeout=30)
        return self

    def final_state(self) -> str:
        """One direct read of the target, after the threads have stopped.

        One of absent, empty, unparseable, unreadable (refused open, not a tear), or whole.
        """
        try:
            raw = self.target.read_text(encoding="utf-8")
        except FileNotFoundError:
            return "absent"
        except OSError:
            return "unreadable"
        if raw == "":
            return "empty"
        try:
            json.loads(raw)
        except json.JSONDecodeError:
            return "unparseable"
        return "whole"

    def assert_clean(self):
        """Fail on a torn file; SKIP when the race never happened.

        The tear check runs first, and reads the target directly too (sampling readers can miss the
        final write), so a skip can never mask a tear.
        """
        final = self.final_state()
        bad = self.empty + self.unparseable

        sampled = f"{self.empty} EMPTY + {self.unparseable} UNPARSEABLE out of {self.reads} reads"
        if self.reads:
            sampled += f" ({bad / self.reads * 100:.2f}% unusable)"

        assert bad == 0 and final not in ("empty", "unparseable"), (
            f"torn file: sampled {sampled}; file on disk at the end of the run "
            f"is {final.upper()} — across {self.writes} writes"
        )

        if self.writes == 0:
            pytest.skip(
                "race not exercised: harness never rewrote the target "
                f"(reads={self.reads}, writes=0, final={final}) — 0 writes is a "
                "result, not a defect"
            )
        if self.reads == 0:
            pytest.skip(
                "race not exercised: harness never read "
                f"(reads=0, writes={self.writes}, target-absent={self.missing}, "
                f"open-refused={self.refused}, final={final}) — the file itself was "
                "checked directly and is not torn; nothing else is claimed either way"
            )


@contextmanager
def write_fails_midway(monkeypatch):
    """Make the write syscall fail for any payload carrying SENTINEL.

    Models a disk filling up mid-write; a durable path loses the temp file and keeps the target.

    Mutant: os.unlink(tmp_path) -> pass (temp orphaned on failure) -> red (2 tests).
    """
    real_os_write = os.write

    def fake_os_write(fd, data):
        if isinstance(data, (bytes, bytearray)) and SENTINEL.encode() in data:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_os_write(fd, data)

    monkeypatch.setattr(aw, "os", _ModuleView(os, write=fake_os_write))
    yield
    monkeypatch.undo()


@pytest.fixture
def mkstemp_spy(monkeypatch):
    """Record every ``tempfile.mkstemp`` call's staging directory.

    Mutant: mkstemp(dir=path.parent) -> mkstemp(dir=path.parent.parent) -> red (7 tests).
    """
    real_mkstemp = tempfile.mkstemp
    calls = []

    def spy(*args, **kwargs):
        fd, path = real_mkstemp(*args, **kwargs)
        calls.append({"dir": kwargs.get("dir"), "path": Path(path)})
        return fd, path

    monkeypatch.setattr(aw, "tempfile", _ModuleView(tempfile, mkstemp=spy))
    return calls


def _stray_temps(directory: Path):
    """Any staging leftovers sitting in a directory after an operation."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return sorted(
        p.name for p in directory.iterdir() if p.is_file() and (p.suffix == ".tmp" or p.name.startswith("tmp"))
    )


def _make_registry(tmp_path: Path, metadata_id: str, branches: list) -> Path:
    reg = tmp_path / "AIPASS_REGISTRY.json"
    reg.write_text(
        json.dumps(
            {
                "metadata": {
                    "version": "1.0.0",
                    "last_updated": "2026-08-16",
                    "total_branches": len(branches),
                    "id": metadata_id,
                },
                "branches": branches,
            }
        ),
        encoding="utf-8",
    )
    return reg


def _make_citizen(tmp_path: Path, rel_path: str, passport_rid: str = "old-rid") -> Path:
    branch_dir = tmp_path / rel_path
    (branch_dir / ".trinity").mkdir(parents=True, exist_ok=True)
    passport = {
        "identity": {"citizen_class": "aipass_framework", "traits": ["steady"] * 30},
        "citizenship": {"registry_id": passport_rid},
    }
    (branch_dir / ".trinity" / "passport.json").write_text(
        json.dumps(passport, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return branch_dir


def _entry(name, path):
    return {
        "name": name,
        "path": path,
        "email": f"@{name.lower()}",
        "status": "active",
        "profile": "library",
        "description": "durability subject",
        "created": "2026-01-01",
        "last_active": "2026-01-01",
        "owner": True,
        "registry_id": "citizen-uid-0001",
    }


@pytest.fixture
def passport_world(tmp_path):
    """A registry + one citizen whose passport fix_owner_identity will rewrite."""
    branch_dir = _make_citizen(tmp_path, "citizen_a")
    reg = _make_registry(tmp_path, "metadata-id-0000", [_entry("CITIZEN_A", "citizen_a")])
    return {
        "registry": reg,
        "passport": branch_dir / ".trinity" / "passport.json",
        "branch_dir": branch_dir,
    }


@pytest.fixture
def merge_world(tmp_path, monkeypatch):
    """A one-branch project the public update merges ONE JSON file into; no living branch is reached."""
    tpl = tmp_path / "template"
    tpl.mkdir()
    template = tpl / "config.json"
    branch = tmp_path / "branch"
    (branch / ".trinity").mkdir(parents=True)
    passport = {"identity": {"citizen_class": "specialist"}}
    (branch / ".trinity" / "passport.json").write_text(json.dumps(passport), encoding="utf-8")
    dest = branch / "config.json"
    template.write_text(json.dumps({"section": {"from_template": True}}), encoding="utf-8")
    dest.write_text(
        json.dumps({"section": {"existing": "value"}, "pad": ["x" * 40] * 20}, indent=2) + "\n",
        encoding="utf-8",
    )
    registry = tmp_path / "AIPASS_REGISTRY.json"
    registry.write_text(json.dumps({"branches": [{"name": "BRANCH", "path": "branch"}]}), encoding="utf-8")

    def template_for(citizen_class):
        return tpl

    monkeypatch.setattr(update_ops, "get_template_dir", template_for)
    return {"template": template, "dest": dest, "registry": registry}


@pytest.fixture
def spawned_branch(tmp_path):
    """A minimal spawned-branch tree with a .spawn/ dir for registry writes."""
    branch = tmp_path / "spawned"
    (branch / ".spawn").mkdir(parents=True)
    (branch / "apps").mkdir()
    for i in range(6):
        (branch / "apps" / f"mod_{i}.py").write_text(f"# module {i}\n" * 20, encoding="utf-8")
    return branch


class TestConcurrentReaderNeverSeesTornFile:
    """The core property, driven through the real call sites."""

    def test_passport_write_is_never_read_torn(self, passport_world):
        """sync_registry_ops.fix_owner_identity — another citizen's identity file."""

        reg = passport_world["registry"]

        def write_once(n):
            # Rotate metadata.id so every pass actually rewrites the passport.
            data = json.loads(reg.read_text(encoding="utf-8"))
            data["metadata"]["id"] = f"metadata-id-{n:06d}"
            reg.write_text(json.dumps(data), encoding="utf-8")
            result = fix_owner_identity(registry_path=reg, dry_run=False)
            return any("Align passport" in a for a in result.get("actions", []))

        _Racer(passport_world["passport"], write_once).run().assert_clean()

    def test_template_registry_write_is_never_read_torn(self, spawned_branch):
        """file_ops.regenerate_template_registry — .spawn/.template_registry.json."""

        target = spawned_branch / ".spawn" / ".template_registry.json"

        def write_once(n):
            file_ops.regenerate_template_registry(spawned_branch)
            return True

        _Racer(target, write_once).run().assert_clean()

    def test_json_merge_write_is_never_read_torn(self, merge_world):
        """update_ops._merge_json — a live branch's JSON during update --apply."""

        dest = merge_world["dest"]

        def write_once(n):
            # Reset through the already-atomic handler, so any torn read comes from the merge's own write.
            json_handler.write_json(dest, {"section": {"existing": "value"}, "pad": ["x" * 40] * 20})
            template = merge_world["template"]
            template.write_text(json.dumps({"section": {"from_template": True, f"round_{n}": n}}), encoding="utf-8")
            return _update_merge(merge_world) == "updated"

        _Racer(dest, write_once).run().assert_clean()

    def test_branch_meta_write_is_never_read_torn(self, spawned_branch):
        """meta_ops.save_branch_meta — already temp-staged; regression pin only."""

        target = spawned_branch / ".spawn" / ".branch_meta.json"

        def write_once(n):
            return save_branch_meta(
                spawned_branch,
                {"metadata": {"last_updated": "2026-08-16", "round": n}, "files": {}},
            )

        _Racer(target, write_once).run().assert_clean()

    def test_regenerated_template_registry_is_never_read_torn(self, tmp_path):
        """regenerate_registry_ops — already temp-staged; regression pin only."""

        template_dir = tmp_path / "some_template"
        template_dir.mkdir()
        for i in range(5):
            (template_dir / f"file_{i}.py").write_text(f"# {i}\n" * 20, encoding="utf-8")
        regenerate_registry_ops.regenerate_template_registry(template_dir)
        target = template_dir / ".spawn" / ".template_registry.json"

        def write_once(n):
            return "error" not in regenerate_registry_ops.regenerate_template_registry(template_dir)

        _Racer(target, write_once).run().assert_clean()


class TestNoTempLitterSurvives:
    """A landed write leaves the target and nothing else."""

    def test_successful_passport_write_leaves_no_temp(self, passport_world):

        fix_owner_identity(registry_path=passport_world["registry"], dry_run=False)

        assert _stray_temps(passport_world["passport"].parent) == []

    def test_successful_branch_meta_write_leaves_no_temp(self, spawned_branch):

        assert save_branch_meta(spawned_branch, {"metadata": {}, "files": {}}) is True

        assert _stray_temps(spawned_branch / ".spawn") == []

    def test_successful_template_registry_write_leaves_no_temp(self, spawned_branch):

        file_ops.regenerate_template_registry(spawned_branch)

        assert _stray_temps(spawned_branch / ".spawn") == []

    def test_failed_registry_regeneration_leaves_no_temp(self, tmp_path, monkeypatch):
        """A failed regeneration must not orphan .template_registry.tmp."""

        template_dir = tmp_path / "some_template"
        template_dir.mkdir()
        (template_dir / f"marker_{SENTINEL}.py").write_text("# payload\n", encoding="utf-8")

        with write_fails_midway(monkeypatch):
            result = regenerate_registry_ops.regenerate_template_registry(template_dir)

        assert "error" in result, "a failed registry write must report an error"
        assert _stray_temps(template_dir / ".spawn") == []

    def test_failed_branch_meta_write_leaves_no_temp(self, spawned_branch, monkeypatch):

        with write_fails_midway(monkeypatch):
            ok = save_branch_meta(spawned_branch, {"metadata": {"marker": SENTINEL}, "files": {}})

        assert ok is False, "save_branch_meta must still report failure as False"
        assert _stray_temps(spawned_branch / ".spawn") == []


class TestFailedWriteKeepsOldContent:
    """When the write dies midway the previous file must survive intact."""

    def test_helper_raises_on_write_failure(self, tmp_path, monkeypatch):
        """The shared helper must RAISE, never swallow."""

        target = tmp_path / "thing.json"
        target.write_text('{"old": true}\n', encoding="utf-8")

        with write_fails_midway(monkeypatch):
            with pytest.raises(OSError):
                atomic_write_text(target, json.dumps({"marker": SENTINEL}))

        assert json.loads(target.read_text(encoding="utf-8")) == {"old": True}
        assert _stray_temps(tmp_path) == []

    def test_failed_passport_write_keeps_old_passport(self, passport_world, monkeypatch):
        """The failed write must leave the citizen's identity file intact, never empty.

        fix_owner_identity writes this passport twice: the registry_id align carries SENTINEL and dies;
        the retired-class migration carries none and succeeds. Fields are pinned separately.
        """

        passport = passport_world["passport"]
        reg = passport_world["registry"]
        data = json.loads(reg.read_text(encoding="utf-8"))
        data["metadata"]["id"] = SENTINEL
        reg.write_text(json.dumps(data), encoding="utf-8")
        before = json.loads(passport.read_text(encoding="utf-8"))
        assert before["identity"]["citizen_class"] == "aipass_framework", "fixture no longer exercises the migration"

        with write_fails_midway(monkeypatch):
            fix_owner_identity(registry_path=reg, dry_run=False)

        after = json.loads(passport.read_text(encoding="utf-8"))

        assert passport.read_text(encoding="utf-8") != ""
        assert after["citizenship"] == before["citizenship"]
        assert after["citizenship"]["registry_id"] != SENTINEL
        assert after["identity"]["traits"] == before["identity"]["traits"]

        # The one legitimate difference: the separate, successful class migration.
        assert after["identity"]["citizen_class"] == "specialist"
        assert after == {**before, "identity": {**before["identity"], "citizen_class": "specialist"}}

    def test_failed_json_merge_keeps_old_file(self, merge_world, monkeypatch):
        """The branch's live JSON must survive a failed merge write."""

        dest = merge_world["dest"]
        merge_world["template"].write_text(json.dumps({"section": {"marker": SENTINEL}}), encoding="utf-8")
        before = json.loads(dest.read_text(encoding="utf-8"))

        with write_fails_midway(monkeypatch):
            result = _update_merge(merge_world)

        assert result == "error", "the update must keep reporting the merge as an error on failure"
        assert dest.read_text(encoding="utf-8") != ""
        assert json.loads(dest.read_text(encoding="utf-8")) == before

    def test_failed_branch_meta_write_keeps_old_meta(self, spawned_branch, monkeypatch):

        target = spawned_branch / ".spawn" / ".branch_meta.json"
        save_branch_meta(spawned_branch, {"metadata": {"round": "first"}, "files": {}})
        before = json.loads(target.read_text(encoding="utf-8"))

        with write_fails_midway(monkeypatch):
            save_branch_meta(spawned_branch, {"metadata": {"marker": SENTINEL}, "files": {}})

        assert json.loads(target.read_text(encoding="utf-8")) == before


class TestTempStagedBesideTarget:
    """os.replace is only atomic within one filesystem.

    Staging in /tmp (often another mount) turns the swap into EXDEV, so every site passes dir=target.parent.
    """

    @staticmethod
    def _assert_staged_in(calls, target_dir: Path):
        staged = [c for c in calls if c["dir"] is not None and Path(c["dir"]) == Path(target_dir)]
        assert staged, (
            f"no mkstemp(dir={target_dir}) call recorded — the write did not stage "
            f"beside its target. Recorded dirs: {[str(c['dir']) for c in calls]}"
        )

    def test_passport_stages_beside_passport(self, passport_world, mkstemp_spy):

        fix_owner_identity(registry_path=passport_world["registry"], dry_run=False)

        self._assert_staged_in(mkstemp_spy, passport_world["passport"].parent)

    def test_template_registry_stages_beside_registry(self, spawned_branch, mkstemp_spy):

        file_ops.regenerate_template_registry(spawned_branch)

        self._assert_staged_in(mkstemp_spy, spawned_branch / ".spawn")

    def test_json_merge_stages_beside_target(self, merge_world, mkstemp_spy):

        _update_merge(merge_world)

        self._assert_staged_in(mkstemp_spy, merge_world["dest"].parent)

    def test_branch_meta_stages_beside_meta(self, spawned_branch, mkstemp_spy):

        save_branch_meta(spawned_branch, {"metadata": {}, "files": {}})

        self._assert_staged_in(mkstemp_spy, spawned_branch / ".spawn")

    def test_regenerated_registry_stages_beside_registry(self, tmp_path, mkstemp_spy):

        template_dir = tmp_path / "some_template"
        template_dir.mkdir()
        (template_dir / "a.py").write_text("# a\n", encoding="utf-8")

        regenerate_registry_ops.regenerate_template_registry(template_dir)

        self._assert_staged_in(mkstemp_spy, template_dir / ".spawn")

    def test_copied_template_file_stages_beside_target(self, tmp_path, mkstemp_spy):

        template = tmp_path / "tpl"
        template.mkdir()
        (template / "hello.md").write_text("# hello {{BRANCH}}\n", encoding="utf-8")
        target = tmp_path / "out"

        file_ops.copy_template(template, target, {"BRANCH": "durable"})

        self._assert_staged_in(mkstemp_spy, target)

    def test_update_addition_stages_beside_target(self, tmp_path, mkstemp_spy):
        """update_ops' ADDITION arm — a missing template file written into a branch."""

        # The helper alone decides the staging directory, so it is driven directly.
        dest_dir = tmp_path / "branch" / "docs"
        dest_dir.mkdir(parents=True)
        atomic_write_text(dest_dir / "new.md", "# added\n")

        self._assert_staged_in(mkstemp_spy, dest_dir)


class TestStagingNameIsUnique:
    """A fixed ``.tmp`` name makes two concurrent writers stomp each other."""

    def test_branch_meta_staging_names_are_unique(self, spawned_branch, mkstemp_spy):

        for i in range(5):
            save_branch_meta(spawned_branch, {"metadata": {"round": i}, "files": {}})

        names = [c["path"].name for c in mkstemp_spy if Path(c["dir"]) == spawned_branch / ".spawn"]
        assert len(names) == 5, f"expected 5 staged temps, recorded {len(names)}: {names}"
        assert len(set(names)) == 5, f"staging name collided across writes: {names}"

    def test_regenerated_registry_staging_names_are_unique(self, tmp_path, mkstemp_spy):

        template_dir = tmp_path / "some_template"
        template_dir.mkdir()
        (template_dir / "a.py").write_text("# a\n", encoding="utf-8")

        for _ in range(5):
            regenerate_registry_ops.regenerate_template_registry(template_dir)

        names = [c["path"].name for c in mkstemp_spy if Path(c["dir"]) == template_dir / ".spawn"]
        assert len(names) == 5, f"expected 5 staged temps, recorded {len(names)}: {names}"
        assert len(set(names)) == 5, f"staging name collided across writes: {names}"


class TestAtomicWriteHelper:
    """The single choke point every fixed site routes through."""

    def test_writes_exact_bytes(self, tmp_path):

        target = tmp_path / "out.json"
        payload = json.dumps({"unicode": "café — ok", "n": 1}, indent=2, ensure_ascii=False) + "\n"

        atomic_write_text(target, payload)

        assert target.read_text(encoding="utf-8") == payload

    def test_overwrites_existing_target(self, tmp_path):

        target = tmp_path / "out.json"
        target.write_text("old\n", encoding="utf-8")

        atomic_write_text(target, "new\n")

        assert target.read_text(encoding="utf-8") == "new\n"
        assert _stray_temps(tmp_path) == []

    def test_uses_os_replace_not_path_rename(self, tmp_path, monkeypatch):
        """Path.rename cannot overwrite on Windows; os.replace can.

        Mutant: os.replace(source, destination) -> os.rename(source, destination) -> red.
        """
        seen = []
        real_replace = os.replace

        def spy(src, dst):
            seen.append((src, dst))
            return real_replace(src, dst)

        monkeypatch.setattr(aw, "os", _ModuleView(os, replace=spy))
        target = tmp_path / "out.json"
        target.write_text("old\n", encoding="utf-8")

        aw.atomic_write_text(target, "new\n")

        assert len(seen) == 1, "the swap must go through os.replace"

    def test_fsyncs_before_swap(self, tmp_path, monkeypatch):
        """Durability across power loss needs the bytes flushed before the rename.

        Mutant: os.fsync(fd) deleted -> red.
        """
        order = []
        real_fsync, real_replace = os.fsync, os.replace
        monkeypatch.setattr(
            aw,
            "os",
            _ModuleView(
                os,
                fsync=lambda fd: (order.append("fsync"), real_fsync(fd))[1],
                replace=lambda s, d: (order.append("replace"), real_replace(s, d))[1],
            ),
        )

        aw.atomic_write_text(tmp_path / "out.json", "data\n")

        assert order == ["fsync", "replace"]

    def test_encoding_failure_raises_and_leaves_no_temp(self, tmp_path):
        """A surrogate payload must not silently land, and must not litter."""

        target = tmp_path / "out.json"

        with pytest.raises(UnicodeEncodeError):
            atomic_write_text(target, "bad \ud800 surrogate")

        assert not target.exists()
        assert _stray_temps(tmp_path) == []


class TestReplaceRetriesThroughSharingViolations:
    """os.replace is atomic, but on Windows it is not always *available*.

    Python opens without FILE_SHARE_DELETE, so on Windows os.replace raises PermissionError while any
    reader holds the target; a short bounded retry converges. Linux never raises it, so tests inject it.
    """

    def test_helper_exists_and_is_bounded(self, tmp_path, monkeypatch):
        """The SHIPPED bound and backoff, measured through the public write.

        More than one attempt, every wait non-zero; aw's own ``time`` is stubbed so nothing sleeps.

        Mutant: _REPLACE_ATTEMPTS = 40 -> _REPLACE_ATTEMPTS = 1 -> red.
        """
        attempts = []
        sleeps = []

        def blocked(src, dst):
            attempts.append(dst)
            raise PermissionError(13, "sharing violation", str(dst))

        monkeypatch.setattr(aw, "time", SimpleNamespace(sleep=sleeps.append))
        monkeypatch.setattr(aw, "os", _ModuleView(os, replace=blocked))

        with pytest.raises(PermissionError):
            atomic_write_text(tmp_path / "out.json", "new\n")

        assert len(attempts) > 1, "a single attempt is not a retry"
        assert len(sleeps) == len(attempts) - 1
        assert all(s > 0 for s in sleeps), f"a zero backoff spins instead of waiting: {sleeps}"

    def test_retries_through_a_transient_sharing_violation(self, tmp_path, monkeypatch):
        """Two sharing violations then success — the write still lands."""
        calls = {"count": 0}
        real_replace = os.replace

        def flaky(src, dst):
            calls["count"] += 1
            if calls["count"] <= 2:
                raise PermissionError(13, "sharing violation", str(dst))
            return real_replace(src, dst)

        monkeypatch.setattr(aw, "os", _ModuleView(os, replace=flaky))
        target = tmp_path / "out.json"
        target.write_text("old\n", encoding="utf-8")

        aw.atomic_write_text(target, "new\n")

        assert target.read_text(encoding="utf-8") == "new\n"
        assert calls["count"] == 3, "retry path never engaged"
        assert _stray_temps(tmp_path) == []

    def test_retry_is_bounded_and_raises(self, tmp_path, monkeypatch):
        """A swap that never unblocks raises instead of retrying forever.

        Mutant: attempt == _REPLACE_ATTEMPTS - 1 -> attempt == _REPLACE_ATTEMPTS - 2 -> red.
        """

        calls = {"count": 0}

        def blocked(src, dst):
            calls["count"] += 1
            raise PermissionError(13, "sharing violation", str(dst))

        monkeypatch.setattr(aw, "os", _ModuleView(os, replace=blocked))
        monkeypatch.setattr(aw, "_REPLACE_BACKOFF_SECONDS", 0)
        monkeypatch.setattr(aw, "_REPLACE_ATTEMPTS", 3)
        target = tmp_path / "out.json"
        target.write_text("old\n", encoding="utf-8")

        with pytest.raises(PermissionError):
            aw.atomic_write_text(target, "new\n")

        assert calls["count"] == 3, "bound not honoured"
        assert target.read_text(encoding="utf-8") == "old\n", "the live file was damaged"
        assert _stray_temps(tmp_path) == []

    def test_retry_waits_between_attempts(self, tmp_path, monkeypatch):
        """The backoff is used, not just declared.

        A busy spin passes every other pin here but never outlasts the reader handle. Patches aw's own
        ``time`` binding: patching the shared module collects other threads' sleeps.

        Mutant: time.sleep(_REPLACE_BACKOFF_SECONDS) -> time.sleep(0) -> red.
        """

        sleeps = []
        monkeypatch.setattr(aw, "time", SimpleNamespace(sleep=sleeps.append))
        monkeypatch.setattr(aw, "_REPLACE_ATTEMPTS", 4)
        monkeypatch.setattr(aw, "_REPLACE_BACKOFF_SECONDS", 0.25)
        monkeypatch.setattr(
            aw,
            "os",
            _ModuleView(
                os,
                replace=lambda src, dst: (_ for _ in ()).throw(PermissionError(13, "sharing violation", str(dst))),
            ),
        )
        target = tmp_path / "out.json"
        target.write_text("old\n", encoding="utf-8")

        with pytest.raises(PermissionError):
            aw.atomic_write_text(target, "new\n")

        assert sleeps == [0.25, 0.25, 0.25]

    def test_non_permission_error_propagates_immediately(self, tmp_path, monkeypatch):
        """A cross-device rename will not fix itself in 200ms — do not wait it out."""

        calls = {"count": 0}

        def broken(src, dst):
            calls["count"] += 1
            raise OSError(errno.EXDEV, "invalid cross-device link")

        monkeypatch.setattr(aw, "os", _ModuleView(os, replace=broken))
        monkeypatch.setattr(aw, "_REPLACE_BACKOFF_SECONDS", 0)

        with pytest.raises(OSError) as caught:
            aw.atomic_write_text(tmp_path / "out.json", "new\n")

        assert caught.value.errno == errno.EXDEV
        assert calls["count"] == 1, "a non-sharing failure was retried"
        assert _stray_temps(tmp_path) == []


class TestSaveRegistryStaysAtomic:
    """registry.save_registry delegates to json_handler.write_json (already atomic)."""

    def test_save_registry_delegates_to_json_handler(self, tmp_path, monkeypatch):

        seen = {}

        def fake_write_json(path, data, *args, **kwargs):
            seen["path"] = Path(path)
            return True

        monkeypatch.setattr(registry_mod.json_handler, "write_json", fake_write_json)
        reg = tmp_path / "AIPASS_REGISTRY.json"

        assert registry_mod.save_registry(reg, {"metadata": {}, "branches": []}) is True
        assert seen["path"] == reg

    def test_save_registry_write_is_never_read_torn(self, tmp_path):

        reg = tmp_path / "AIPASS_REGISTRY.json"
        branches = [_entry(f"B{i}", f"b{i}") for i in range(12)]
        save_registry(reg, {"metadata": {}, "branches": list(branches)})

        def write_once(n):
            return save_registry(reg, {"metadata": {"round": n}, "branches": list(branches)})

        _Racer(reg, write_once).run().assert_clean()


# Parked code does not run, and nothing looks into a dropbox; flagging them would only weaken the guard.
_UNSCANNED_DIRS = {"__pycache__", ".archive", "dropbox"}

_TRUNCATING_MODE_CHARS = ("w", "a")


def _apps_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "apps"


def _is_lock_target(call: "ast.Call", source: str) -> bool:
    """True when the opened path is a lock file rather than a data file.

    Keyed on the opened path, not the variable the fd lands in, so the exemption stays precise.
    """
    if not call.args:
        return False
    segment = ast.get_source_segment(source, call.args[0]) or ""
    return "lock" in segment.lower()


class _RawWriteFinder(ast.NodeVisitor):
    """Collects truncating write calls from one module's AST.

    AST, not regex: it sees calls, so ``os.fdopen`` and prose about the bad shape never match.
    """

    def __init__(self, source: str, rel_path: str):
        self.source = source
        self.rel_path = rel_path
        self.findings: list[str] = []

    def _record(self, node, shape: str):
        self.findings.append(f"{self.rel_path}:{node.lineno}: {shape}")

    @staticmethod
    def _mode_of(call: "ast.Call") -> str | None:
        if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
            if isinstance(call.args[1].value, str):
                return call.args[1].value
        for kw in call.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                if isinstance(kw.value.value, str):
                    return kw.value.value
        return None

    def visit_Call(self, node):
        func = node.func

        is_builtin_open = isinstance(func, ast.Name) and func.id == "open"
        is_io_open = isinstance(func, ast.Attribute) and func.attr == "open"

        if is_builtin_open or is_io_open:
            mode = self._mode_of(node)
            if mode and any(c in mode for c in _TRUNCATING_MODE_CHARS):
                if not _is_lock_target(node, self.source):
                    self._record(node, f"truncating open(..., {mode!r}) — use atomic_write_text")

        if isinstance(func, ast.Attribute) and func.attr == "write_text":
            self._record(node, "Path.write_text(...) — use atomic_write_text")

        self.generic_visit(node)


def scan_for_raw_writes(apps_dir: Path | None = None) -> list[str]:
    """Return every raw truncating write shape found in spawn's own source."""
    apps_dir = Path(apps_dir) if apps_dir is not None else _apps_dir()
    findings: list[str] = []

    for py_file in sorted(apps_dir.rglob("*.py")):
        if _UNSCANNED_DIRS.intersection(py_file.relative_to(apps_dir).parts):
            continue
        source = py_file.read_text(encoding="utf-8")
        finder = _RawWriteFinder(source, py_file.relative_to(apps_dir.parent).as_posix())
        finder.visit(ast.parse(source, filename=str(py_file)))
        findings.extend(finder.findings)

    return findings


class TestNoRawTruncatingWritesInSource:
    """Guard: the shape that caused this whole defect cannot reappear in apps/."""

    def test_guard_never_walks_into_a_dropbox(self, tmp_path):
        """The walk skips a dropbox; the same write beside it is still reported."""
        raw_write = "def save(path, text):\n    with open(path, 'w', encoding='utf-8') as f:\n        f.write(text)\n"
        dropbox = tmp_path / "apps" / "dropbox"
        dropbox.mkdir(parents=True)
        (dropbox / "dropped.py").write_text(raw_write, encoding="utf-8")
        (tmp_path / "apps" / "live.py").write_text(raw_write, encoding="utf-8")

        findings = scan_for_raw_writes(tmp_path / "apps")

        assert len(findings) == 1
        assert findings[0].startswith("apps/live.py")

    def test_apps_source_has_no_raw_truncating_writes(self):
        findings = scan_for_raw_writes()

        assert findings == [], (
            "raw truncating write(s) found in spawn source — a concurrent reader "
            "can observe an empty or partial file. Route through "
            "apps/handlers/atomic_write.atomic_write_text:\n  " + "\n  ".join(findings)
        )

    def test_guard_catches_a_raw_open_write(self, tmp_path):
        """Mutation check: the guard must fail on a reintroduced open(..., 'w')."""
        apps = tmp_path / "apps"
        apps.mkdir()
        (apps / "regressed.py").write_text(
            "def save(path, text):\n    with open(path, 'w', encoding='utf-8') as f:\n        f.write(text)\n",
            encoding="utf-8",
        )

        findings = scan_for_raw_writes(apps)

        assert len(findings) == 1, findings
        assert "truncating open" in findings[0]

    def test_guard_catches_a_raw_write_text(self, tmp_path):
        """Mutation check: the guard must fail on a reintroduced .write_text()."""
        apps = tmp_path / "apps"
        apps.mkdir()
        (apps / "regressed.py").write_text(
            "import json\n\n\ndef save(path, data):\n    path.write_text(json.dumps(data), encoding='utf-8')\n",
            encoding="utf-8",
        )

        findings = scan_for_raw_writes(apps)

        assert len(findings) == 1, findings
        assert "write_text" in findings[0]

    def test_guard_catches_append_and_update_modes(self, tmp_path):
        apps = tmp_path / "apps"
        apps.mkdir()
        (apps / "regressed.py").write_text(
            "def a(p):\n    open(p, 'a').close()\n\n\ndef b(p):\n    open(p, 'w+').close()\n",
            encoding="utf-8",
        )

        findings = scan_for_raw_writes(apps)

        assert len(findings) == 2, findings

    def test_guard_exempts_lock_files(self, tmp_path):
        """The two real flock targets must not be flagged."""
        apps = tmp_path / "apps"
        apps.mkdir()
        (apps / "locking.py").write_text(
            "def take(lock_path):\n"
            "    lock_fd = open(lock_path, 'w', encoding='utf-8')  # noqa: SIM115\n"
            "    return lock_fd\n",
            encoding="utf-8",
        )

        assert scan_for_raw_writes(apps) == []

    def test_guard_does_not_flag_reads_or_fdopen(self, tmp_path):
        """Read-mode opens and os.fdopen are not truncating writes."""
        apps = tmp_path / "apps"
        apps.mkdir()
        (apps / "reader.py").write_text(
            "import os\n\n\n"
            "def r(p):\n    return open(p, 'r', encoding='utf-8').read()\n\n\n"
            "def rb(p):\n    with open(p, 'rb') as f:\n        return f.read()\n\n\n"
            "def d(p):\n    return p.read_text(encoding='utf-8')\n\n\n"
            "def f(fd):\n    return os.fdopen(fd, 'w')\n",
            encoding="utf-8",
        )

        assert scan_for_raw_writes(apps) == []

    def test_guard_flags_the_real_lock_sites_if_they_stop_being_locks(self):
        """The exemption is narrow: it keys on the path, not the file it lives in."""
        apps = _apps_dir()
        registry_src = (apps / "handlers" / "registry.py").read_text(encoding="utf-8")

        assert 'open(lock_path, "w"' in registry_src, (
            "registry.py's flock target changed shape — re-check the guard exemption"
        )


class _Turns:
    """A write_once stand-in that records the turn numbers the racer hands it.

    The verdict is fixed; the test asserts the racer consulted it turn after turn, from 0.
    """

    def __init__(self, wrote: bool):
        self.wrote = wrote
        self.seen: list[int] = []

    def __call__(self, n: int) -> bool:
        self.seen.append(n)
        return self.wrote


def _never_called(n: int) -> bool:
    """write_once for a racer whose counters are set by hand: the race never runs."""
    raise AssertionError(f"write_once called with turn {n}; this pin never starts the race")


class TestRacerReportsWeatherHonestly:
    """The guard "the race proves nothing" is right; failing for it is not.

    Under load the reader may never be scheduled; reads == 0 is "could not measure", not "broken".
    The harness waits for both sides, then skips with counters; the tear check still runs first.
    """

    def test_a_race_that_never_read_skips_rather_than_fails(self, tmp_path):
        """reads == 0 is a result, not a defect."""
        turns = _Turns(wrote=True)
        racer = _Racer(tmp_path / "never_created.json", turns)
        racer.run(seconds=0.05, warmup=0.05)

        assert racer.reads == 0, "fixture assumption broken — the target must never appear"
        with pytest.raises(pytest.skip.Exception) as exc:
            racer.assert_clean()

        assert "never read" in str(exc.value)
        assert turns.seen[:1] == [0] and turns.seen == list(range(len(turns.seen)))
        assert racer.writes == len(turns.seen)

    def test_a_race_that_never_wrote_skips_rather_than_fails(self, tmp_path):
        """writes == 0 is the same result seen from the other side."""
        target = tmp_path / "static.json"
        target.write_text('{"a": 1}\n', encoding="utf-8")

        turns = _Turns(wrote=False)
        racer = _Racer(target, turns)
        racer.run(seconds=0.05, warmup=0.05)

        with pytest.raises(pytest.skip.Exception) as exc:
            racer.assert_clean()

        assert "never rewrote" in str(exc.value)
        assert turns.seen[:1] == [0] and turns.seen == list(range(len(turns.seen)))
        assert racer.writes == 0

    def test_the_skip_reason_carries_the_counters(self, tmp_path):
        """A skip nobody can diagnose is only a quieter silence."""
        turns = _Turns(wrote=True)
        racer = _Racer(tmp_path / "never_created.json", turns)
        racer.run(seconds=0.05, warmup=0.05)

        with pytest.raises(pytest.skip.Exception) as exc:
            racer.assert_clean()

        reason = str(exc.value)
        assert "reads=0" in reason
        assert f"writes={len(turns.seen)}" in reason

    def test_an_observed_tear_still_fails_even_with_one_read(self, tmp_path):
        """ORDERING PIN — the tear check must run BEFORE the skip."""
        racer = _Racer(tmp_path / "irrelevant.json", _never_called)
        racer.reads = 1
        racer.empty = 1
        racer.writes = 0

        with pytest.raises(AssertionError) as exc:
            racer.assert_clean()

        assert "torn file" in str(exc.value)

    def test_a_clean_exercised_race_still_passes(self, tmp_path):
        """The normal path is untouched."""

        target = tmp_path / "live.json"

        def write_once(n):
            atomic_write_text(target, json.dumps({"round": n}) + "\n")
            return True

        racer = _Racer(target, write_once).run()
        racer.assert_clean()

        assert racer.reads > 0 and racer.writes > 0

    def test_warmup_waits_for_a_slow_starter(self, tmp_path):
        """A target that appears late still gets a real race, not a skip."""

        target = tmp_path / "slow.json"

        def write_once(n):
            if n < 3:
                return False
            atomic_write_text(target, json.dumps({"round": n}) + "\n")
            return True

        racer = _Racer(target, write_once).run(seconds=0.2, warmup=20.0)
        racer.assert_clean()

        assert racer.reads > 0 and racer.writes > 0


@contextmanager
def _target(tmp_path: Path, content):
    """A _Racer over a throwaway file with a known final state, zero samples.

    ``content=None`` leaves it absent; zero counters isolate what the direct read contributes.
    """
    target = tmp_path / "final_state.json"
    if content is not None:
        target.write_text(content, encoding="utf-8")
    racer = _Racer(target, _never_called)
    racer.reads = 0
    racer.writes = 0
    yield racer


def _verdict(racer):
    """Classify what assert_clean DID: FAILED / SKIPPED / PASSED.

    ``pytest.raises(AssertionError)`` lets a skip sail past and report SKIPPED; this makes it a value.
    """
    try:
        racer.assert_clean()
    except AssertionError as exc:
        return "FAILED", str(exc)
    except pytest.skip.Exception as exc:
        return "SKIPPED", str(exc)
    return "PASSED", ""


class TestTheFinalStateIsCheckedDirectly:
    """A target torn on disk must fail even when no reader thread sampled it.

    A direct read costs one open and cannot be starved by the scheduler.
    """

    def test_a_torn_file_nobody_sampled_is_a_red_not_a_skip(self, tmp_path):
        """reads == 0 must not launder a file that is torn right now."""
        with _target(tmp_path, '{"half') as racer:
            verdict, message = _verdict(racer)

        assert verdict == "FAILED", (
            f"a file left torn on disk was reported {verdict} — the sampling "
            f"readers saw nothing, so only a direct read can catch it: {message}"
        )
        assert "torn" in message.lower()
        assert "UNPARSEABLE" in message

    def test_an_empty_file_nobody_sampled_is_a_red_not_a_skip(self, tmp_path):
        with _target(tmp_path, "") as racer:
            verdict, message = _verdict(racer)

        assert verdict == "FAILED", f"an empty target was reported {verdict}: {message}"
        assert "EMPTY" in message

    def test_a_missing_target_is_still_a_skip_not_a_tear(self, tmp_path):
        """Never created is not torn — the distinction the skip exists for."""
        with _target(tmp_path, None) as racer:
            verdict, message = _verdict(racer)

        assert verdict == "SKIPPED", f"a never-created target was reported {verdict}"
        assert "final=absent" in message

    def test_a_whole_file_at_the_end_does_not_invent_a_tear(self, tmp_path):
        """Positive control — the direct read must not manufacture reds."""
        with _target(tmp_path, '{"round": 7}\n') as racer:
            racer.reads = 5
            racer.writes = 5
            verdict, message = _verdict(racer)

        assert verdict == "PASSED", f"a whole file was reported {verdict}: {message}"

    def test_an_unreadable_target_is_not_convicted_as_torn(self, tmp_path):
        """Share-mode / permission refusal is not evidence of tearing.

        chmod cannot build the state everywhere (Windows ignores mode bits, root reads through), so the
        host is probed, not assumed.
        """
        with _target(tmp_path, '{"whole": true}') as racer:
            racer.target.chmod(0o000)
            try:
                try:
                    racer.target.read_text(encoding="utf-8")
                except OSError as exc:
                    logger.debug("probe: chmod 0o000 made the target unreadable: %s", exc)
                    unreadable = True
                else:
                    unreadable = False

                verdict, message = _verdict(racer)
            finally:
                racer.target.chmod(0o644)

        if not unreadable:
            pytest.skip(
                "world not built: chmod(0o000) left the file readable on this "
                f"host (platform={sys.platform}, euid={getattr(os, 'geteuid', lambda: 'n/a')()}) "
                "— Windows ignores POSIX mode bits and root reads through them, "
                "so the unreadable state cannot be constructed this way here"
            )

        assert verdict == "SKIPPED", f"an unreadable target was reported {verdict}: {message}"
        assert "final=unreadable" in message
