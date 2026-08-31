# =================== META ====================
# Name: test_json_durability.py
# Description: Torn-write durability tests for spawn's JSON/text write paths
# Version: 1.1.0
# Created: 2026-08-16
# Modified: 2026-08-18
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
import os
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest


# =============================================================================
# HELPERS
# =============================================================================

RACE_SECONDS = 0.6

# How long run() will wait for BOTH sides to prove they are live before it opens
# the timed window. On an idle machine the first read and write land inside a few
# milliseconds and this costs nothing; on a loaded one it converts "the scheduler
# was busy" from a red into a little latency. Generous on purpose — the deadline
# exists to bound a hang, not to tune a race.
RACE_WARMUP_SECONDS = 20.0

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
        self.missing = 0
        self.refused = 0
        self.warmed_up = False
        self._stop = False
        self._lock = threading.Lock()
        # One-way flags, set by the threads the instant they first succeed, so
        # run() can watch the race come alive. The per-thread counters above are
        # only merged at join time, which is far too late to wait on. A bool
        # that goes False -> True exactly once needs no lock under the GIL.
        self._saw_read = False
        self._saw_write = False

    def _writer(self):
        n = 0
        effective = 0
        while not self._stop:
            # Same 1ms yield as the reader, same reason: a zero-delay write loop
            # keeps an os.replace nearly always in flight, and Windows share-mode
            # semantics then refuse every reader open — a slow CI runner can end
            # the whole race with reads == 0 (Windows CI, 2026-08-28). No fleet
            # workload rewrites a config file in a hot loop either.
            time.sleep(0.001)
            # write_once returns True only when it actually rewrote the target.
            # Counting loop turns instead would let a race pass vacuously when
            # the call under test decided there was nothing to write.
            if self.write_once(n) is True:
                effective += 1
                self._saw_write = True
            n += 1
        with self._lock:
            self.writes += effective

    def _reader(self):
        reads = empty = unparseable = missing = refused = 0
        while not self._stop:
            # Yield between polls — Windows share-mode semantics, not tuning.
            # A zero-delay spin-reader holds the target open at near-100% duty
            # cycle, and Python opens files without FILE_SHARE_DELETE, so on
            # Windows an os.replace onto a handle a reader holds fails with
            # WinError 5. Two spinning readers can then collide with every one
            # of the writer's bounded retry attempts and starve a correct retry
            # into exhaustion (first full Windows CI run, 2026-08-18). 1ms
            # models a real reader — no fleet workload spin-reads a config file
            # — and weakens no content check below. At the top of the pass so
            # the `continue` paths yield too: a refused open means a replace is
            # in flight, exactly when re-spinning hurts most.
            time.sleep(0.001)
            try:
                raw = self.target.read_text(encoding="utf-8")
            except FileNotFoundError:
                # Counted, not swallowed. "The file was not there yet" and "the
                # reader never got a turn" both end with reads == 0, and the
                # skip reason has to be able to tell them apart — that is the
                # difference between a slow starter and a starved scheduler.
                missing += 1
                continue
            except PermissionError:
                # Windows refuses the open while a concurrent os.replace is in
                # flight. A refused open is share-mode semantics — not a torn
                # document, and not counted as a read. Counted separately so a
                # run starved by share-mode collisions says so out loud.
                refused += 1
                continue
            reads += 1
            self._saw_read = True
            if raw == "":
                empty += 1
                continue
            try:
                json.loads(raw)
            except json.JSONDecodeError:
                # The defect this whole file exists to catch: a half-written
                # document. Recorded, and assert_clean fails on it.
                unparseable += 1
        with self._lock:
            self.reads += reads
            self.empty += empty
            self.unparseable += unparseable
            self.missing += missing
            self.refused += refused

    def run(self, seconds: float = RACE_SECONDS, warmup: float = RACE_WARMUP_SECONDS):
        """Start the threads, wait until both sides are live, then race.

        The timed window used to open the instant the threads were started, so
        on a loaded machine a 0.6s race could end with the reader never having
        been scheduled at all — reads == 0, and assert_clean called that a
        defect (@prax, whole-tree batch run 2026-08-30). Waiting for first
        contact first turns that from a red into a few milliseconds of latency
        on an idle box and a bounded wait on a busy one.
        """
        threads = [threading.Thread(target=self._writer) for _ in range(self.writers)]
        threads += [threading.Thread(target=self._reader) for _ in range(self.readers)]
        for t in threads:
            t.start()

        deadline = time.monotonic() + warmup
        while time.monotonic() < deadline and not (self._saw_read and self._saw_write):
            time.sleep(0.005)
        self.warmed_up = self._saw_read and self._saw_write

        time.sleep(seconds)
        self._stop = True
        for t in threads:
            t.join(timeout=30)
        return self

    def final_state(self) -> str:
        """One direct read of the target, after the threads have stopped.

        Returns exactly one of: ``absent`` (never created — not a tear),
        ``empty`` / ``unparseable`` (torn, right now, on disk), ``unreadable``
        (the open itself was refused — share-mode or permissions, which is not
        evidence of tearing and must not be convicted as such), or ``whole``.
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

        Order matters and is the whole safety argument: the tear check runs
        FIRST, so an observed tear fails loudly no matter how few reads or
        writes the run managed. Only once the file is known clean does an
        unexercised race downgrade to a skip — a test may say "I could not
        measure this", but it may never say "this is broken" when that is what
        it means.

        The tear check reads the target DIRECTLY here as well as through the
        reader threads' samples. @prax asked for exactly this when reviewing
        the skip ordering (2026-08-31), and it was a real gap rather than a
        formality: the readers poll on a 1ms yield, so a file left torn by the
        final write can go unsampled entirely — and a run ending with reads == 0
        would then take the skip branch while the target sits torn on disk. One
        open at assert time cannot be starved by the scheduler. A missing target
        is still not a tear; never-created is the case the skip exists for.
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
        """RED before the fix: the citizen's identity file was left empty.

        The durability property is unchanged and still the whole point: the write
        that FAILS must leave the previous file intact, never a truncated husk.

        What changed is the snapshot this used to compare against. ``fix_owner_identity``
        makes TWO independent writes to this passport, and only the first one carries
        SENTINEL:

          1. align citizenship.registry_id to the registry's metadata.id — the
             registry id IS the sentinel here, so this write is the one that dies;
          2. migrate a retired identity.citizen_class to its live replacement
             (DPLAN-0319 extended this from builder→aipass_framework to
             aipass_framework→specialist). The fixture passport says
             "aipass_framework", so this write legitimately fires and legitimately
             SUCCEEDS — it carries no sentinel and nothing is failing it.

        A flat ``== before`` therefore asserted the second write never happened,
        which is a claim about the migration, not about durability. The fields are
        pinned separately instead, so a regression in either one is named.
        """
        from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity

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

        # DURABILITY — the failed write neither truncated the file nor landed.
        assert passport.read_text(encoding="utf-8") != ""
        assert after["citizenship"] == before["citizenship"]
        assert after["citizenship"]["registry_id"] != SENTINEL
        # The bulky payload the truncation used to destroy survives byte for byte.
        assert after["identity"]["traits"] == before["identity"]["traits"]

        # The one legitimate difference: the separate, successful class migration.
        assert after["identity"]["citizen_class"] == "specialist"
        assert after == {**before, "identity": {**before["identity"], "citizen_class": "specialist"}}

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
# 6b. THE WINDOWS SHARING-VIOLATION RETRY
# =============================================================================


class TestReplaceRetriesThroughSharingViolations:
    """os.replace is atomic, but on Windows it is not always *available*.

    Windows gives no FILE_SHARE_DELETE on Python's open, so os.replace raises
    PermissionError for as long as ANY reader holds the target open. Readers
    hold those handles for microseconds, so a short bounded retry converges —
    but an unretried swap simply dies, and on 2026-08-18 one stuck swap starved
    a whole CI run into 45-minute cancels.

    Linux never produces that error on an open file, so every test here injects
    it. The injection is the only cross-platform proof the retry path exists —
    and a standards audit found _replace_with_retry had ZERO tests fleet-wide
    before this sweep, so these are the first eyes on it.
    """

    def test_helper_exists_and_is_bounded(self):
        import aipass.spawn.apps.handlers.atomic_write as aw

        assert hasattr(aw, "_replace_with_retry"), (
            "_replace_with_retry missing — a sharing violation still kills the write"
        )
        assert aw._REPLACE_ATTEMPTS > 1, "a single attempt is not a retry"
        assert aw._REPLACE_BACKOFF_SECONDS > 0, "a zero backoff spins instead of waiting"

    def test_retries_through_a_transient_sharing_violation(self, tmp_path, monkeypatch):
        """Two sharing violations then success — the write still lands."""
        import os as _os
        import aipass.spawn.apps.handlers.atomic_write as aw

        calls = {"count": 0}
        real_replace = _os.replace

        def flaky(src, dst):
            calls["count"] += 1
            if calls["count"] <= 2:
                raise PermissionError(13, "sharing violation", str(dst))
            return real_replace(src, dst)

        monkeypatch.setattr(aw.os, "replace", flaky)
        target = tmp_path / "out.json"
        target.write_text("old\n", encoding="utf-8")

        aw.atomic_write_text(target, "new\n")

        assert target.read_text(encoding="utf-8") == "new\n"
        assert calls["count"] == 3, "retry path never engaged"
        assert _stray_temps(tmp_path) == []

    def test_retry_is_bounded_and_raises(self, tmp_path, monkeypatch):
        """A swap that never unblocks raises instead of retrying forever."""
        import aipass.spawn.apps.handlers.atomic_write as aw

        calls = {"count": 0}

        def blocked(src, dst):
            calls["count"] += 1
            raise PermissionError(13, "sharing violation", str(dst))

        monkeypatch.setattr(aw.os, "replace", blocked)
        monkeypatch.setattr(aw, "_REPLACE_BACKOFF_SECONDS", 0)
        target = tmp_path / "out.json"
        target.write_text("old\n", encoding="utf-8")

        with pytest.raises(PermissionError):
            aw.atomic_write_text(target, "new\n")

        assert calls["count"] == aw._REPLACE_ATTEMPTS, "bound not honoured"
        assert target.read_text(encoding="utf-8") == "old\n", "the live file was damaged"
        assert _stray_temps(tmp_path) == []

    def test_retry_waits_between_attempts(self, tmp_path, monkeypatch):
        """The backoff is used, not just declared.

        Deleting the sleep leaves a busy spin that passes every other pin in
        this class: it still retries, still bounds, still raises. But 40
        immediate attempts finish inside a microsecond and never outlast the
        reader handle the retry exists to wait out — the retry stops being a fix
        and becomes decoration. It survived a mutation run on 2026-08-18.
        Counting the sleeps pins the wait without asserting on wall-clock time,
        which would be flaky on a loaded runner.

        The patch replaces atomic_write's OWN ``time`` name, not the attribute
        on the shared time module. ``setattr(aw.time, "sleep", ...)`` reached
        every thread in the process, so this list collected foreign sleeps too
        and the test failed intermittently in a full-suite run (seen
        2026-08-30). Same rule as the logger fixture: patch the consuming
        module's binding, not something upstream of it. atomic_write uses
        nothing from ``time`` but ``sleep`` (one call site, line 73), so a stub
        carrying only ``sleep`` is the whole surface.
        """
        import aipass.spawn.apps.handlers.atomic_write as aw

        sleeps = []
        monkeypatch.setattr(aw, "time", SimpleNamespace(sleep=sleeps.append))
        monkeypatch.setattr(
            aw.os,
            "replace",
            lambda src, dst: (_ for _ in ()).throw(PermissionError(13, "sharing violation", str(dst))),
        )
        target = tmp_path / "out.json"
        target.write_text("old\n", encoding="utf-8")

        with pytest.raises(PermissionError):
            aw.atomic_write_text(target, "new\n")

        # One wait between each pair of attempts — never after the last, which raises.
        assert sleeps == [aw._REPLACE_BACKOFF_SECONDS] * (aw._REPLACE_ATTEMPTS - 1)

    def test_non_permission_error_propagates_immediately(self, tmp_path, monkeypatch):
        """A cross-device rename will not fix itself in 200ms — do not wait it out."""
        import aipass.spawn.apps.handlers.atomic_write as aw

        calls = {"count": 0}

        def broken(src, dst):
            calls["count"] += 1
            raise OSError(errno.EXDEV, "invalid cross-device link")

        monkeypatch.setattr(aw.os, "replace", broken)
        monkeypatch.setattr(aw, "_REPLACE_BACKOFF_SECONDS", 0)

        with pytest.raises(OSError) as caught:
            aw.atomic_write_text(tmp_path / "out.json", "new\n")

        assert caught.value.errno == errno.EXDEV
        assert calls["count"] == 1, "a non-sharing failure was retried"
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


# =============================================================================
# THE HARNESS ITSELF — a race that never raced must not read as a defect
# =============================================================================


class TestRacerReportsWeatherHonestly:
    """The guard "the race proves nothing" is right; failing for it is not.

    MEASURED by @prax 2026-08-30, running every json/log test file in the tree
    as one batch from the repo root: 1380 passed, 1 failed — ours, and it failed
    on its OWN guard (``reads == 0``), not on a torn read. It passes 3/3 alone.
    Under a loaded machine the reader thread simply never gets scheduled inside
    a 0.6s window, so the harness genuinely never read; the guard correctly
    refuses to claim the race was exercised, and then reports that refusal as a
    defect in the code under test. That reds a whole-repo run for weather.

    A test may say "I could not measure this". It may not say "this is broken"
    when what it means is "I could not measure this" — the same species as
    tonight's migrate-passports empty scan reporting an all-clear.

    So the harness now does two things: it WAITS for evidence that both sides
    are live before the timed window opens (weather becomes latency, not
    failure), and if even that deadline expires it SKIPS with the counters in
    the reason. What it never does is let a skip mask a torn read — the tear
    check runs first, so an observed tear fails loudly no matter how few reads
    or writes the run managed.
    """

    def test_a_race_that_never_read_skips_rather_than_fails(self, tmp_path):
        """reads == 0 is a result, not a defect."""
        racer = _Racer(tmp_path / "never_created.json", lambda n: True)
        racer.run(seconds=0.05, warmup=0.05)

        assert racer.reads == 0, "fixture assumption broken — the target must never appear"
        with pytest.raises(pytest.skip.Exception) as exc:
            racer.assert_clean()

        assert "never read" in str(exc.value)

    def test_a_race_that_never_wrote_skips_rather_than_fails(self, tmp_path):
        """writes == 0 is the same result seen from the other side."""
        target = tmp_path / "static.json"
        target.write_text('{"a": 1}\n', encoding="utf-8")

        racer = _Racer(target, lambda n: False)
        racer.run(seconds=0.05, warmup=0.05)

        with pytest.raises(pytest.skip.Exception) as exc:
            racer.assert_clean()

        assert "never rewrote" in str(exc.value)

    def test_the_skip_reason_carries_the_counters(self, tmp_path):
        """A skip nobody can diagnose is only a quieter silence."""
        racer = _Racer(tmp_path / "never_created.json", lambda n: True)
        racer.run(seconds=0.05, warmup=0.05)

        with pytest.raises(pytest.skip.Exception) as exc:
            racer.assert_clean()

        reason = str(exc.value)
        assert "reads=0" in reason
        assert "writes=" in reason

    def test_an_observed_tear_still_fails_even_with_one_read(self, tmp_path):
        """ORDERING PIN — the tear check must run BEFORE the skip.

        Without this, a run unlucky enough to be short would skip past a real
        torn read and call the day green. This is the pin that makes the skip
        safe to add.
        """
        racer = _Racer(tmp_path / "irrelevant.json", lambda n: True)
        racer.reads = 1
        racer.empty = 1
        racer.writes = 0

        with pytest.raises(AssertionError) as exc:
            racer.assert_clean()

        assert "torn file" in str(exc.value)

    def test_a_clean_exercised_race_still_passes(self, tmp_path):
        """The normal path is untouched."""
        from aipass.spawn.apps.handlers.atomic_write import atomic_write_text

        target = tmp_path / "live.json"

        def write_once(n):
            atomic_write_text(target, json.dumps({"round": n}) + "\n")
            return True

        racer = _Racer(target, write_once).run()
        racer.assert_clean()

        assert racer.reads > 0 and racer.writes > 0

    def test_warmup_waits_for_a_slow_starter(self, tmp_path):
        """A target that appears late still gets a real race, not a skip.

        This is the half that turns weather into latency: the timed window does
        not open until both sides have proven they are live.
        """
        from aipass.spawn.apps.handlers.atomic_write import atomic_write_text

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
def _target(content):
    """A _Racer over a throwaway file with a known final state, zero samples.

    ``content=None`` leaves the target absent. The counters start at zero on
    purpose: these pins measure what the DIRECT read contributes, so the
    sampling readers must have contributed nothing.
    """
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "final_state.json"
        if content is not None:
            target.write_text(content, encoding="utf-8")
        racer = _Racer(target, lambda n: True)
        racer.reads = 0
        racer.writes = 0
        yield racer


def _verdict(racer):
    """Classify what assert_clean DID: FAILED / SKIPPED / PASSED.

    The pins below must be able to tell a red apart from a skip, and
    ``pytest.raises(AssertionError)`` cannot: ``pytest.skip`` raises its own
    exception, which sails straight past the raises block and reports the whole
    test as SKIPPED — a defeat wearing a pass's clothes. That is the same
    species @memory killed in their own guard tests on 2026-08-30. Catching
    both here makes the verdict a value the test asserts on.
    """
    try:
        racer.assert_clean()
    except AssertionError as exc:
        return "FAILED", str(exc)
    except pytest.skip.Exception as exc:
        return "SKIPPED", str(exc)
    return "PASSED", ""


class TestTheFinalStateIsCheckedDirectly:
    """@prax's review question, answered by closing it rather than agreeing.

    Reviewing the skip ordering, @prax wrote: "If your tear check reads the file
    directly at the end rather than only through the reader thread's samples,
    that closes the last thing I would have asked about."

    It did not, and the honest answer was to build it. ``assert_clean`` judged
    only what the reader THREADS happened to sample, so a target left torn on
    disk was invisible whenever no sample landed on the write that tore it —
    and the run then SKIPPED, with the very reasonable-sounding explanation that
    nothing had been observed. The ordering was already right; the evidence set
    was too small. A direct read costs one open and cannot be starved by the
    scheduler, which is the exact condition under which the sampling reader
    fails.
    """

    def test_a_torn_file_nobody_sampled_is_a_red_not_a_skip(self):
        """reads == 0 must not launder a file that is torn right now."""
        with _target('{"half') as racer:
            verdict, message = _verdict(racer)

        assert verdict == "FAILED", (
            f"a file left torn on disk was reported {verdict} — the sampling "
            f"readers saw nothing, so only a direct read can catch it: {message}"
        )
        assert "torn" in message.lower()
        assert "UNPARSEABLE" in message

    def test_an_empty_file_nobody_sampled_is_a_red_not_a_skip(self):
        with _target("") as racer:
            verdict, message = _verdict(racer)

        assert verdict == "FAILED", f"an empty target was reported {verdict}: {message}"
        assert "EMPTY" in message

    def test_a_missing_target_is_still_a_skip_not_a_tear(self):
        """Never created is not torn — the distinction the skip exists for."""
        with _target(None) as racer:
            verdict, message = _verdict(racer)

        assert verdict == "SKIPPED", f"a never-created target was reported {verdict}"
        assert "final=absent" in message

    def test_a_whole_file_at_the_end_does_not_invent_a_tear(self):
        """Positive control — the direct read must not manufacture reds."""
        with _target('{"round": 7}\n') as racer:
            racer.reads = 5
            racer.writes = 5
            verdict, message = _verdict(racer)

        assert verdict == "PASSED", f"a whole file was reported {verdict}: {message}"

    def test_an_unreadable_target_is_not_convicted_as_torn(self):
        """Share-mode / permission refusal is not evidence of tearing.

        The world here is built by chmod, and chmod does not build it
        everywhere: Windows ignores POSIX mode bits (it wants an ACL), and root
        reads through them on POSIX. Both were guesses in the first version of
        this test — it inferred "running as root" from a PASSED verdict, which
        is a cause read off a symptom, and on the Windows gate the verdict was
        SKIPPED for a different reason entirely and the assertion below failed
        (@devpulse, ebb8075d windows-setup).

        So the world is PROBED, not assumed: after the chmod, actually try to
        read the file. If it still reads, this host cannot build the state and
        the test says so with what it measured. @memory's ruling, applied —
        probe the host, do not skipif what a probe can measure.
        """
        with _target('{"whole": true}') as racer:
            racer.target.chmod(0o000)
            try:
                try:
                    racer.target.read_text(encoding="utf-8")
                except OSError:
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
