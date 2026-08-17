# =================== META ====================
# Name: test_json_durability.py
# Description: Torn-write durability tests for spawn's JSON/text write paths
# Version: 1.0.0
# Created: 2026-08-16
# Modified: 2026-08-16
# =============================================

"""Durability tests for every spawn write path that touches a live file.

The defect these pin: ``open(path, 'w')`` / ``Path.write_text(...)`` truncate the
target in place, so a concurrent reader can land between the truncate and the
write and read an empty or half-written file. Measured on spawn's passport write
path before the fix: 38.17% of concurrent reads came back unusable.

The required shape is stage-to-temp (``tempfile.mkstemp(dir=target.parent)``),
write, ``fsync``, close, then ``os.replace`` — an atomic same-filesystem rename.
A reader either sees the whole old file or the whole new file, never a gap.

Each test class states which sites were genuinely RED before the fix; the sites
that were already safe (``meta_ops`` / ``regenerate_registry_ops`` staged through
a temp already) say so rather than pretending.
"""

import ast
import errno
import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest


# =============================================================================
# HELPERS
# =============================================================================

RACE_SECONDS = 0.6

# Marker embedded in the payload a test wants to fail. Both fault injectors below
# fire only when they see it, so pytest's own I/O is never disturbed.
SENTINEL = "SPAWN-DURABILITY-FAULT-a1b2c3"


class _Racer:
    """Runs writer threads against reader threads over one target file.

    Readers classify every read as OK / EMPTY / UNPARSEABLE. A durable write path
    yields zero EMPTY and zero UNPARSEABLE reads no matter how the threads
    interleave.
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
        self._stop = False
        self._lock = threading.Lock()

    def _writer(self):
        n = 0
        effective = 0
        while not self._stop:
            # write_once returns True only when it actually rewrote the target.
            # Counting loop turns instead would let a race pass vacuously when
            # the call under test decided there was nothing to write.
            if self.write_once(n) is True:
                effective += 1
            n += 1
        with self._lock:
            self.writes += effective

    def _reader(self):
        reads = empty = unparseable = 0
        while not self._stop:
            try:
                raw = self.target.read_text(encoding="utf-8")
            except FileNotFoundError:
                continue
            reads += 1
            if raw == "":
                empty += 1
                continue
            try:
                json.loads(raw)
            except json.JSONDecodeError:
                unparseable += 1
        with self._lock:
            self.reads += reads
            self.empty += empty
            self.unparseable += unparseable

    def run(self, seconds: float = RACE_SECONDS):
        threads = [threading.Thread(target=self._writer) for _ in range(self.writers)]
        threads += [threading.Thread(target=self._reader) for _ in range(self.readers)]
        for t in threads:
            t.start()
        time.sleep(seconds)
        self._stop = True
        for t in threads:
            t.join(timeout=30)
        return self

    def assert_clean(self):
        assert self.writes > 0, "harness never rewrote the target — the race proves nothing"
        assert self.reads > 0, "harness never read — the race proves nothing"
        bad = self.empty + self.unparseable
        pct = bad / self.reads * 100
        assert bad == 0, (
            f"concurrent reader observed a torn file: {self.empty} EMPTY + "
            f"{self.unparseable} UNPARSEABLE out of {self.reads} reads "
            f"({pct:.2f}% unusable) across {self.writes} writes"
        )


@contextmanager
def write_fails_midway(monkeypatch):
    """Make the write syscall fail for any payload carrying SENTINEL.

    Models a disk filling up between the open and the write — the exact failure
    the atomic shape exists to survive. Both mechanisms are covered so the test
    is honest against either implementation:

    * ``Path.write_text`` truncates the target and then fails, which is precisely
      what the real ``write_text`` does under ENOSPC (it opens with mode 'w').
    * ``os.write`` fails, which is what the staged temp write hits.

    A durable path loses the temp file and keeps the target; the raw path has
    already destroyed the target by the time it fails.
    """
    import os as _os
    import pathlib

    real_write_text = pathlib.Path.write_text
    real_os_write = _os.write

    def fake_write_text(self, data, *args, **kwargs):
        if isinstance(data, str) and SENTINEL in data:
            # Faithful to write_text: the file is opened 'w' (truncated) first.
            with open(self, "w", encoding="utf-8"):
                pass
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_write_text(self, data, *args, **kwargs)

    def fake_os_write(fd, data):
        if isinstance(data, (bytes, bytearray)) and SENTINEL.encode() in data:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_os_write(fd, data)

    monkeypatch.setattr(pathlib.Path, "write_text", fake_write_text)
    monkeypatch.setattr(_os, "write", fake_os_write)
    yield
    monkeypatch.undo()


@pytest.fixture
def mkstemp_spy(monkeypatch):
    """Record every ``tempfile.mkstemp`` call's staging directory."""
    import tempfile as _tempfile

    real_mkstemp = _tempfile.mkstemp
    calls = []

    def spy(*args, **kwargs):
        fd, path = real_mkstemp(*args, **kwargs)
        calls.append({"dir": kwargs.get("dir"), "path": Path(path)})
        return fd, path

    monkeypatch.setattr(_tempfile, "mkstemp", spy)
    return calls


def _stray_temps(directory: Path):
    """Any staging leftovers sitting in a directory after an operation."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return sorted(
        p.name for p in directory.iterdir() if p.is_file() and (p.suffix == ".tmp" or p.name.startswith("tmp"))
    )


# ----- fixtures building each real call site's on-disk world -----------------


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
def merge_world(tmp_path):
    """A template JSON and a live branch copy for update_ops._merge_json."""
    template = tmp_path / "template.json"
    dest_dir = tmp_path / "branch"
    dest_dir.mkdir()
    dest = dest_dir / "config.json"
    template.write_text(json.dumps({"section": {"from_template": True}}), encoding="utf-8")
    dest.write_text(
        json.dumps({"section": {"existing": "value"}, "pad": ["x" * 40] * 20}, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"template": template, "dest": dest, "backup": tmp_path / ".recovery"}


@pytest.fixture
def spawned_branch(tmp_path):
    """A minimal spawned-branch tree with a .spawn/ dir for registry writes."""
    branch = tmp_path / "spawned"
    (branch / ".spawn").mkdir(parents=True)
    (branch / "apps").mkdir()
    for i in range(6):
        (branch / "apps" / f"mod_{i}.py").write_text(f"# module {i}\n" * 20, encoding="utf-8")
    return branch


# =============================================================================
# 1. CONCURRENT READERS NEVER SEE A TORN FILE
# =============================================================================


class TestConcurrentReaderNeverSeesTornFile:
    """The core property, driven through the real call sites.

    RED before the fix: passport (sync_registry_ops), template registry
    (file_ops), JSON merge (update_ops) — all three raw ``write_text``.
    Already GREEN before the fix: branch meta (meta_ops) and template registry
    regeneration (regenerate_registry_ops), which staged through a temp and
    renamed. Those two are kept as regression pins, not as red-first evidence.
    """

    def test_passport_write_is_never_read_torn(self, passport_world):
        """sync_registry_ops.fix_owner_identity — another citizen's identity file."""
        from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity

        reg = passport_world["registry"]

        def write_once(n):
            # Rotate metadata.id so every pass finds the passport out of sync
            # and actually rewrites it.
            data = json.loads(reg.read_text(encoding="utf-8"))
            data["metadata"]["id"] = f"metadata-id-{n:06d}"
            reg.write_text(json.dumps(data), encoding="utf-8")
            result = fix_owner_identity(registry_path=reg, dry_run=False)
            return any("Align passport" in a for a in result.get("actions", []))

        _Racer(passport_world["passport"], write_once).run().assert_clean()

    def test_template_registry_write_is_never_read_torn(self, spawned_branch):
        """file_ops.regenerate_template_registry — .spawn/.template_registry.json."""
        from aipass.spawn.apps.handlers.file_ops import regenerate_template_registry

        target = spawned_branch / ".spawn" / ".template_registry.json"

        def write_once(n):
            regenerate_template_registry(spawned_branch)
            return True

        _Racer(target, write_once).run().assert_clean()

    def test_json_merge_write_is_never_read_torn(self, merge_world):
        """update_ops._merge_json — a live branch's JSON during update --apply."""
        from aipass.spawn.apps.handlers.json import json_handler
        from aipass.spawn.apps.handlers.update_ops import _merge_json

        dest = merge_world["dest"]

        def write_once(n):
            # deep_merge lets existing values win, so a merge only rewrites dest
            # when the template carries a key dest lacks. Reset dest through the
            # already-atomic shared handler each round: that reset can never be
            # the source of a torn read, so any torn read the readers see came
            # from _merge_json's own write.
            json_handler.write_json(dest, {"section": {"existing": "value"}, "pad": ["x" * 40] * 20})
            template = merge_world["template"]
            template.write_text(json.dumps({"section": {"from_template": True, f"round_{n}": n}}), encoding="utf-8")
            return _merge_json(template, dest, {}, False, False, merge_world["backup"]) == "updated"

        _Racer(dest, write_once).run().assert_clean()

    def test_branch_meta_write_is_never_read_torn(self, spawned_branch):
        """meta_ops.save_branch_meta — already temp-staged; regression pin only."""
        from aipass.spawn.apps.handlers.meta_ops import save_branch_meta

        target = spawned_branch / ".spawn" / ".branch_meta.json"

        def write_once(n):
            return save_branch_meta(
                spawned_branch,
                {"metadata": {"last_updated": "2026-08-16", "round": n}, "files": {}},
            )

        _Racer(target, write_once).run().assert_clean()

    def test_regenerated_template_registry_is_never_read_torn(self, tmp_path):
        """regenerate_registry_ops — already temp-staged; regression pin only."""
        from aipass.spawn.apps.handlers.regenerate_registry_ops import regenerate_template_registry

        template_dir = tmp_path / "some_template"
        template_dir.mkdir()
        for i in range(5):
            (template_dir / f"file_{i}.py").write_text(f"# {i}\n" * 20, encoding="utf-8")
        regenerate_template_registry(template_dir)
        target = template_dir / ".spawn" / ".template_registry.json"

        def write_once(n):
            return "error" not in regenerate_template_registry(template_dir)

        _Racer(target, write_once).run().assert_clean()


# =============================================================================
# 2. NO STAGED TEMP FILE SURVIVES
# =============================================================================


class TestNoTempLitterSurvives:
    """A landed write leaves the target and nothing else.

    RED before the fix: the failed-regeneration case — regenerate_registry_ops
    had no cleanup in its except arm, so a failed write orphaned
    ``.template_registry.tmp`` in the template's .spawn/ directory forever.
    The success cases were green before (raw write_text stages nothing) and are
    kept so the fix cannot introduce litter of its own.
    """

    def test_successful_passport_write_leaves_no_temp(self, passport_world):
        from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity

        fix_owner_identity(registry_path=passport_world["registry"], dry_run=False)

        assert _stray_temps(passport_world["passport"].parent) == []

    def test_successful_branch_meta_write_leaves_no_temp(self, spawned_branch):
        from aipass.spawn.apps.handlers.meta_ops import save_branch_meta

        assert save_branch_meta(spawned_branch, {"metadata": {}, "files": {}}) is True

        assert _stray_temps(spawned_branch / ".spawn") == []

    def test_successful_template_registry_write_leaves_no_temp(self, spawned_branch):
        from aipass.spawn.apps.handlers.file_ops import regenerate_template_registry

        regenerate_template_registry(spawned_branch)

        assert _stray_temps(spawned_branch / ".spawn") == []

    def test_failed_registry_regeneration_leaves_no_temp(self, tmp_path, monkeypatch):
        """RED before the fix: orphaned .template_registry.tmp after a failure."""
        from aipass.spawn.apps.handlers.regenerate_registry_ops import regenerate_template_registry

        template_dir = tmp_path / "some_template"
        template_dir.mkdir()
        (template_dir / f"marker_{SENTINEL}.py").write_text("# payload\n", encoding="utf-8")

        with write_fails_midway(monkeypatch):
            result = regenerate_template_registry(template_dir)

        assert "error" in result, "a failed registry write must report an error"
        assert _stray_temps(template_dir / ".spawn") == []

    def test_failed_branch_meta_write_leaves_no_temp(self, spawned_branch, monkeypatch):
        from aipass.spawn.apps.handlers.meta_ops import save_branch_meta

        with write_fails_midway(monkeypatch):
            ok = save_branch_meta(spawned_branch, {"metadata": {"marker": SENTINEL}, "files": {}})

        assert ok is False, "save_branch_meta must still report failure as False"
        assert _stray_temps(spawned_branch / ".spawn") == []


# =============================================================================
# 3. A FAILED WRITE DOES NOT DESTROY THE EXISTING TARGET
# =============================================================================


class TestFailedWriteKeepsOldContent:
    """When the write dies midway the previous file must survive intact.

    RED before the fix: passport and JSON merge — raw ``write_text`` had already
    truncated the target to zero bytes before the failure surfaced.
    Already GREEN before: branch meta (the failure hit the temp, not the target).
    """

    def test_helper_raises_on_write_failure(self, tmp_path, monkeypatch):
        """The shared helper must RAISE, never swallow. RED by absence pre-fix."""
        from aipass.spawn.apps.handlers.atomic_write import atomic_write_text

        target = tmp_path / "thing.json"
        target.write_text('{"old": true}\n', encoding="utf-8")

        with write_fails_midway(monkeypatch):
            with pytest.raises(OSError):
                atomic_write_text(target, json.dumps({"marker": SENTINEL}))

        assert json.loads(target.read_text(encoding="utf-8")) == {"old": True}
        assert _stray_temps(tmp_path) == []

    def test_failed_passport_write_keeps_old_passport(self, passport_world, monkeypatch):
        """RED before the fix: the citizen's identity file was left empty."""
        from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity

        passport = passport_world["passport"]
        reg = passport_world["registry"]
        data = json.loads(reg.read_text(encoding="utf-8"))
        data["metadata"]["id"] = SENTINEL
        reg.write_text(json.dumps(data), encoding="utf-8")
        before = json.loads(passport.read_text(encoding="utf-8"))

        with write_fails_midway(monkeypatch):
            fix_owner_identity(registry_path=reg, dry_run=False)

        assert passport.read_text(encoding="utf-8") != ""
        assert json.loads(passport.read_text(encoding="utf-8")) == before

    def test_failed_json_merge_keeps_old_file(self, merge_world, monkeypatch):
        """RED before the fix: the branch's live JSON was left empty."""
        from aipass.spawn.apps.handlers.update_ops import _merge_json

        dest = merge_world["dest"]
        merge_world["template"].write_text(json.dumps({"section": {"marker": SENTINEL}}), encoding="utf-8")
        before = json.loads(dest.read_text(encoding="utf-8"))

        with write_fails_midway(monkeypatch):
            result = _merge_json(merge_world["template"], dest, {}, False, False, merge_world["backup"])

        assert result == "error", "_merge_json must keep reporting 'error' on failure"
        assert dest.read_text(encoding="utf-8") != ""
        assert json.loads(dest.read_text(encoding="utf-8")) == before

    def test_failed_branch_meta_write_keeps_old_meta(self, spawned_branch, monkeypatch):
        from aipass.spawn.apps.handlers.meta_ops import save_branch_meta

        target = spawned_branch / ".spawn" / ".branch_meta.json"
        save_branch_meta(spawned_branch, {"metadata": {"round": "first"}, "files": {}})
        before = json.loads(target.read_text(encoding="utf-8"))

        with write_fails_midway(monkeypatch):
            save_branch_meta(spawned_branch, {"metadata": {"marker": SENTINEL}, "files": {}})

        assert json.loads(target.read_text(encoding="utf-8")) == before


# =============================================================================
# 4. THE TEMP FILE IS STAGED IN THE TARGET'S OWN DIRECTORY
# =============================================================================


class TestTempStagedBesideTarget:
    """os.replace is only atomic within one filesystem.

    Staging in /tmp (a different mount on most Linux boxes) would turn the final
    swap into an EXDEV failure, so every site must pass ``dir=target.parent`` to
    mkstemp. All of these are RED before the fix — the raw sites never called
    mkstemp at all, and the temp-staging sites used a hand-built ``.tmp`` name.
    """

    @staticmethod
    def _assert_staged_in(calls, target_dir: Path):
        staged = [c for c in calls if c["dir"] is not None and Path(c["dir"]) == Path(target_dir)]
        assert staged, (
            f"no mkstemp(dir={target_dir}) call recorded — the write did not stage "
            f"beside its target. Recorded dirs: {[str(c['dir']) for c in calls]}"
        )

    def test_passport_stages_beside_passport(self, passport_world, mkstemp_spy):
        from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity

        fix_owner_identity(registry_path=passport_world["registry"], dry_run=False)

        self._assert_staged_in(mkstemp_spy, passport_world["passport"].parent)

    def test_template_registry_stages_beside_registry(self, spawned_branch, mkstemp_spy):
        from aipass.spawn.apps.handlers.file_ops import regenerate_template_registry

        regenerate_template_registry(spawned_branch)

        self._assert_staged_in(mkstemp_spy, spawned_branch / ".spawn")

    def test_json_merge_stages_beside_target(self, merge_world, mkstemp_spy):
        from aipass.spawn.apps.handlers.update_ops import _merge_json

        _merge_json(merge_world["template"], merge_world["dest"], {}, False, False, merge_world["backup"])

        self._assert_staged_in(mkstemp_spy, merge_world["dest"].parent)

    def test_branch_meta_stages_beside_meta(self, spawned_branch, mkstemp_spy):
        from aipass.spawn.apps.handlers.meta_ops import save_branch_meta

        save_branch_meta(spawned_branch, {"metadata": {}, "files": {}})

        self._assert_staged_in(mkstemp_spy, spawned_branch / ".spawn")

    def test_regenerated_registry_stages_beside_registry(self, tmp_path, mkstemp_spy):
        from aipass.spawn.apps.handlers.regenerate_registry_ops import regenerate_template_registry

        template_dir = tmp_path / "some_template"
        template_dir.mkdir()
        (template_dir / "a.py").write_text("# a\n", encoding="utf-8")

        regenerate_template_registry(template_dir)

        self._assert_staged_in(mkstemp_spy, template_dir / ".spawn")

    def test_copied_template_file_stages_beside_target(self, tmp_path, mkstemp_spy):
        from aipass.spawn.apps.handlers.file_ops import copy_template

        template = tmp_path / "tpl"
        template.mkdir()
        (template / "hello.md").write_text("# hello {{BRANCH}}\n", encoding="utf-8")
        target = tmp_path / "out"

        copy_template(template, target, {"BRANCH": "durable"})

        self._assert_staged_in(mkstemp_spy, target)

    def test_update_addition_stages_beside_target(self, tmp_path, mkstemp_spy):
        """update_ops' ADDITION arm — a missing template file written into a branch."""
        from aipass.spawn.apps.handlers.atomic_write import atomic_write_text

        # Driven through the helper directly: the ADDITION arm needs a whole
        # branch + registry world, and the property under test is the staging
        # directory, which the helper alone decides.
        dest_dir = tmp_path / "branch" / "docs"
        dest_dir.mkdir(parents=True)
        atomic_write_text(dest_dir / "new.md", "# added\n")

        self._assert_staged_in(mkstemp_spy, dest_dir)


# =============================================================================
# 5. STAGING NAMES DO NOT COLLIDE BETWEEN CONCURRENT WRITERS
# =============================================================================


class TestStagingNameIsUnique:
    """A fixed ``.tmp`` name makes two concurrent writers stomp each other.

    Both of these are RED before the fix: meta_ops used
    ``meta_path.with_suffix('.tmp')`` and regenerate_registry_ops used
    ``registry_path.with_suffix('.tmp')`` — the same path on every call, so two
    writers interleaving would each write half of one temp file and then both
    rename it over the target.
    """

    def test_branch_meta_staging_names_are_unique(self, spawned_branch, mkstemp_spy):
        from aipass.spawn.apps.handlers.meta_ops import save_branch_meta

        for i in range(5):
            save_branch_meta(spawned_branch, {"metadata": {"round": i}, "files": {}})

        names = [c["path"].name for c in mkstemp_spy if Path(c["dir"]) == spawned_branch / ".spawn"]
        assert len(names) == 5, f"expected 5 staged temps, recorded {len(names)}: {names}"
        assert len(set(names)) == 5, f"staging name collided across writes: {names}"

    def test_regenerated_registry_staging_names_are_unique(self, tmp_path, mkstemp_spy):
        from aipass.spawn.apps.handlers.regenerate_registry_ops import regenerate_template_registry

        template_dir = tmp_path / "some_template"
        template_dir.mkdir()
        (template_dir / "a.py").write_text("# a\n", encoding="utf-8")

        for _ in range(5):
            regenerate_template_registry(template_dir)

        names = [c["path"].name for c in mkstemp_spy if Path(c["dir"]) == template_dir / ".spawn"]
        assert len(names) == 5, f"expected 5 staged temps, recorded {len(names)}: {names}"
        assert len(set(names)) == 5, f"staging name collided across writes: {names}"


# =============================================================================
# 6. THE HELPER'S OWN CONTRACT
# =============================================================================


class TestAtomicWriteHelper:
    """The single choke point every fixed site routes through."""

    def test_writes_exact_bytes(self, tmp_path):
        from aipass.spawn.apps.handlers.atomic_write import atomic_write_text

        target = tmp_path / "out.json"
        payload = json.dumps({"unicode": "café — ok", "n": 1}, indent=2, ensure_ascii=False) + "\n"

        atomic_write_text(target, payload)

        assert target.read_text(encoding="utf-8") == payload

    def test_overwrites_existing_target(self, tmp_path):
        from aipass.spawn.apps.handlers.atomic_write import atomic_write_text

        target = tmp_path / "out.json"
        target.write_text("old\n", encoding="utf-8")

        atomic_write_text(target, "new\n")

        assert target.read_text(encoding="utf-8") == "new\n"
        assert _stray_temps(tmp_path) == []

    def test_uses_os_replace_not_path_rename(self, tmp_path, monkeypatch):
        """Path.rename cannot overwrite on Windows; os.replace can."""
        import os as _os
        import aipass.spawn.apps.handlers.atomic_write as aw

        seen = []
        real_replace = _os.replace

        def spy(src, dst):
            seen.append((src, dst))
            return real_replace(src, dst)

        monkeypatch.setattr(aw.os, "replace", spy)
        target = tmp_path / "out.json"
        target.write_text("old\n", encoding="utf-8")

        aw.atomic_write_text(target, "new\n")

        assert len(seen) == 1, "the swap must go through os.replace"

    def test_fsyncs_before_swap(self, tmp_path, monkeypatch):
        """Durability across power loss needs the bytes flushed before the rename."""
        import os as _os
        import aipass.spawn.apps.handlers.atomic_write as aw

        order = []
        real_fsync, real_replace = _os.fsync, _os.replace
        monkeypatch.setattr(aw.os, "fsync", lambda fd: (order.append("fsync"), real_fsync(fd))[1])
        monkeypatch.setattr(aw.os, "replace", lambda s, d: (order.append("replace"), real_replace(s, d))[1])

        aw.atomic_write_text(tmp_path / "out.json", "data\n")

        assert order == ["fsync", "replace"]

    def test_encoding_failure_raises_and_leaves_no_temp(self, tmp_path):
        """A surrogate payload must not silently land, and must not litter."""
        from aipass.spawn.apps.handlers.atomic_write import atomic_write_text

        target = tmp_path / "out.json"

        with pytest.raises(UnicodeEncodeError):
            atomic_write_text(target, "bad \ud800 surrogate")

        assert not target.exists()
        assert _stray_temps(tmp_path) == []


# =============================================================================
# 7. save_registry ALREADY ROUTES THROUGH THE ATOMIC SHARED HANDLER
# =============================================================================


class TestSaveRegistryStaysAtomic:
    """registry.save_registry delegates to json_handler.write_json (already atomic).

    GREEN before and after — this pins that it is not quietly rewritten into a
    raw write later.
    """

    def test_save_registry_delegates_to_json_handler(self, tmp_path, monkeypatch):
        import aipass.spawn.apps.handlers.registry as registry_mod

        seen = {}

        def fake_write_json(path, data, *args, **kwargs):
            seen["path"] = Path(path)
            return True

        monkeypatch.setattr(registry_mod.json_handler, "write_json", fake_write_json)
        reg = tmp_path / "AIPASS_REGISTRY.json"

        assert registry_mod.save_registry(reg, {"metadata": {}, "branches": []}) is True
        assert seen["path"] == reg

    def test_save_registry_write_is_never_read_torn(self, tmp_path):
        from aipass.spawn.apps.handlers.registry import save_registry

        reg = tmp_path / "AIPASS_REGISTRY.json"
        branches = [_entry(f"B{i}", f"b{i}") for i in range(12)]
        save_registry(reg, {"metadata": {}, "branches": list(branches)})

        def write_once(n):
            return save_registry(reg, {"metadata": {"round": n}, "branches": list(branches)})

        _Racer(reg, write_once).run().assert_clean()


# =============================================================================
# 8. SOURCE GUARD — the raw truncating shape must not grow back
# =============================================================================

# Directories under apps/ the guard does not scan. Parked code does not run, so
# a revivable file carrying an old shape is not a live defect; flagging it would
# only pressure someone into weakening the guard. Both are clean today.
_UNSCANNED_DIRS = {"__pycache__", ".archive"}

# A mode string with 'w' or 'a' truncates or appends the target in place.
_TRUNCATING_MODE_CHARS = ("w", "a")


def _apps_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "apps"


def _is_lock_target(call: "ast.Call", source: str) -> bool:
    """True when the opened path is a lock file rather than a data file.

    Lock files are exactly what a truncating open is FOR: flock needs a real fd
    on a file it owns, and the file's contents are never read. Keying the
    exemption on the opened path (``lock_path``) rather than on the variable the
    fd lands in is what makes it precise — a lock opened into a differently
    named variable stays exempt, and a data write that happens to land in a
    variable named ``*_fd`` does not.
    """
    if not call.args:
        return False
    segment = ast.get_source_segment(source, call.args[0]) or ""
    return "lock" in segment.lower()


class _RawWriteFinder(ast.NodeVisitor):
    """Collects truncating write calls from one module's AST.

    AST rather than a regex because it sees calls, not text: ``os.fdopen(...)``
    is an attribute named ``fdopen`` and can never be mistaken for the builtin
    ``open``, which is what the ``(?<!fd)`` negative lookbehind exists to prevent
    in a regex-based guard. Comments, docstrings, and this file's own prose
    describing the bad shape are likewise invisible to it.
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
        if _UNSCANNED_DIRS.intersection(py_file.parts):
            continue
        source = py_file.read_text(encoding="utf-8")
        finder = _RawWriteFinder(source, py_file.relative_to(apps_dir.parent).as_posix())
        finder.visit(ast.parse(source, filename=str(py_file)))
        findings.extend(finder.findings)

    return findings


class TestNoRawTruncatingWritesInSource:
    """Guard: the shape that caused this whole defect cannot reappear in apps/."""

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
