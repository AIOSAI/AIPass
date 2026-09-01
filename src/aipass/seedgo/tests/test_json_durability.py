"""Torn-write durability for json_handler.

Axis 1 of the fleet defect: open(path, "w") truncates the target BEFORE the new
content is written, so every concurrent reader in that window sees an empty or
partial file. Measured on this handler before the fix: 842 of 1075 concurrent
reads unusable (78.3%) — 454 empty, 388 unparseable.

The race is not merely a failed read here. ensure_json_exists() answers an
unreadable document by regenerating the type's blank template over it, so a
reader landing in the truncate window destroys live data on the next call.
"""

# =================== META ====================
# Name: test_json_durability.py
# Description: Torn-write durability tests for the json handler
# Version: 1.0.0
# Created: 2026-08-16
# Modified: 2026-08-16
# =============================================

import json
import os
import re
import threading
import warnings
import time
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.json import json_handler

HANDLER_SOURCE = Path(json_handler.__file__)

# open(..., "w"/"a"/"w+") — but NOT os.fdopen(descriptor, "w"), which is the fix
# itself. Without the lookbehind the guard convicts the helper it is protecting.
TRUNCATING_OPEN = re.compile(r"(?<!fd)open\(\s*[^)]*?,\s*[\"'][waW+]")
WRITE_TEXT = re.compile(r"\.write_text\(")


@pytest.fixture
def json_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the handler's JSON_DIR at tmp_path — never the live branch dir."""
    target = tmp_path / "seedgo_json"
    target.mkdir()
    monkeypatch.setattr(json_handler, "JSON_DIR", target)
    return target


class TestAtomicHelper:
    """The mechanism itself."""

    def test_creates_document_that_did_not_exist(self, tmp_path: Path):
        target = tmp_path / "fresh.json"
        json_handler._atomic_write_json(target, {"a": 1})
        assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}

    def test_replaces_existing_document(self, tmp_path: Path):
        target = tmp_path / "existing.json"
        target.write_text('{"old": true}\n', encoding="utf-8")
        json_handler._atomic_write_json(target, {"new": True})
        assert json.loads(target.read_text(encoding="utf-8")) == {"new": True}

    def test_leaves_no_staged_file_behind(self, tmp_path: Path):
        target = tmp_path / "clean.json"
        json_handler._atomic_write_json(target, {"a": 1})
        assert [p.name for p in tmp_path.iterdir()] == ["clean.json"]

    def test_stages_the_temp_file_in_the_target_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """os.replace is only atomic within one filesystem — the temp must be a sibling.

        Staging in /tmp would make the fix silently non-atomic the moment a
        branch lives on a different mount than the system temp dir.
        """
        target = tmp_path / "sibling.json"
        seen: list[str] = []
        real_mkstemp = json_handler.tempfile.mkstemp

        def recording_mkstemp(*args, **kwargs):
            seen.append(str(kwargs.get("dir")))
            return real_mkstemp(*args, **kwargs)

        monkeypatch.setattr(json_handler.tempfile, "mkstemp", recording_mkstemp)
        json_handler._atomic_write_json(target, {"a": 1})
        assert seen == [str(tmp_path)]

    def test_failed_write_leaves_the_original_intact_and_cleans_the_temp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """A write that dies mid-flight must not damage what is already there."""
        target = tmp_path / "survivor.json"
        target.write_text('{"live": "data"}\n', encoding="utf-8")

        def exploding_dump(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(json_handler.json, "dump", exploding_dump)

        with pytest.raises(OSError):
            json_handler._atomic_write_json(target, {"replacement": True})

        assert json.loads(target.read_text(encoding="utf-8")) == {"live": "data"}
        assert [p.name for p in tmp_path.iterdir()] == ["survivor.json"]

    def test_helper_raises_rather_than_returning_false(self, tmp_path: Path):
        """No new silent catch — a write that cannot happen must be loud."""
        missing_dir = tmp_path / "does_not_exist"
        with pytest.raises(OSError):
            json_handler._atomic_write_json(missing_dir / "x.json", {"a": 1})


class TestEveryWriteSiteIsRouted:
    """Both writers in this handler must go through the helper."""

    def test_save_json_routes_through_the_helper(self, json_dir: Path, monkeypatch: pytest.MonkeyPatch):
        calls: list[Path] = []
        monkeypatch.setattr(json_handler, "_atomic_write_json", lambda p, d: calls.append(p))
        json_handler.save_json("m", "log", [{"a": 1}])
        assert calls == [json_dir / "m_log.json"]

    def test_ensure_json_exists_routes_through_the_helper(self, json_dir: Path, monkeypatch: pytest.MonkeyPatch):
        """The regenerate path is the DATA-LOSS site, not merely another writer."""
        calls: list[Path] = []
        monkeypatch.setattr(json_handler, "_atomic_write_json", lambda p, d: calls.append(p))
        json_handler.ensure_json_exists("m", "config")
        assert calls == [json_dir / "m_config.json"]

    def test_regenerating_over_a_corrupt_document_routes_through_the_helper(
        self, json_dir: Path, monkeypatch: pytest.MonkeyPatch
    ):
        corrupt = json_dir / "m_data.json"
        corrupt.write_text("{not json", encoding="utf-8")
        calls: list[Path] = []
        monkeypatch.setattr(json_handler, "_atomic_write_json", lambda p, d: calls.append(p))
        json_handler.ensure_json_exists("m", "data")
        assert calls == [corrupt]


class TestSourceGuard:
    """No truncating write may reappear in this file."""

    def test_no_truncating_open_in_handler_source(self):
        source = HANDLER_SOURCE.read_text(encoding="utf-8")
        offenders = [
            line.strip()
            for line in source.splitlines()
            if TRUNCATING_OPEN.search(line) and not line.strip().startswith("#")
        ]
        assert offenders == []

    def test_no_write_text_in_handler_source(self):
        source = HANDLER_SOURCE.read_text(encoding="utf-8")
        offenders = [
            line.strip() for line in source.splitlines() if WRITE_TEXT.search(line) and not line.strip().startswith("#")
        ]
        assert offenders == []

    def test_guard_does_not_convict_the_fix_itself(self):
        """KNOWN TRAP: os.fdopen(fd, "w") matches a naive open( regex."""
        assert TRUNCATING_OPEN.search('with os.fdopen(descriptor, "w", encoding="utf-8") as stream:') is None

    @pytest.mark.parametrize(
        "line",
        [
            'with open(json_path, "w", encoding="utf-8") as f:',
            "with open(json_path, 'w') as f:",
            'with open(path, "a") as f:',
            'with open(path, "w+") as f:',
            'open(target, "W")',
        ],
    )
    def test_guard_still_catches_real_truncating_writes(self, line: str):
        """MUTATION CHECK: the (?<!fd) exemption must not blind the guard."""
        assert TRUNCATING_OPEN.search(line) is not None

    def test_guard_still_catches_write_text(self):
        assert WRITE_TEXT.search('json_path.write_text(json.dumps(data), encoding="utf-8")') is not None


class TestContractPreserved:
    """The mechanism changed; this handler's published contract did not."""

    def test_save_json_still_returns_true(self, json_dir: Path):
        assert json_handler.save_json("m", "log", [{"a": 1}]) is True

    def test_save_json_still_raises_on_invalid_structure(self, json_dir: Path):
        with pytest.raises(ValueError):
            json_handler.save_json("m", "config", {"missing": "keys"})

    def test_save_json_still_stamps_last_updated_on_data(self, json_dir: Path):
        json_handler.ensure_json_exists("m", "data")
        payload = json_handler.load_json("m", "data")
        assert payload is not None
        payload["last_updated"] = "1999-01-01"
        json_handler.save_json("m", "data", payload)
        reloaded = json_handler.load_json("m", "data")
        assert reloaded is not None
        assert reloaded["last_updated"] != "1999-01-01"

    def test_ensure_json_exists_still_creates_the_file(self, json_dir: Path):
        """Was pinning an unconditional `is True`. The durability contract this
        class exists to protect is that the FILE lands, not that a constant is
        returned; failure is reported by exception, not by a value."""
        json_handler.ensure_json_exists("m", "config")
        assert (json_dir / "m_config.json").exists()

    def test_round_trip_still_works(self, json_dir: Path):
        json_handler.save_json("m", "log", [{"entry": "one"}])
        assert json_handler.load_json("m", "log") == [{"entry": "one"}]

    def test_log_operation_still_rotates(self, json_dir: Path):
        json_handler.ensure_module_jsons("m")
        config = json_handler.load_json("m", "config")
        assert config is not None
        config["config"]["max_log_entries"] = 3
        json_handler.save_json("m", "config", config)
        for i in range(6):
            json_handler.log_operation(f"op{i}", module_name="m")
        log = json_handler.load_json("m", "log")
        assert log is not None
        assert len(log) == 3
        assert log[-1]["operation"] == "op5"


class TestConcurrentReadersSeeAWholeDocument:
    """The measurement that motivated the fix, run as an assertion."""

    def test_two_writers_two_readers_zero_unusable(self, json_dir: Path):
        json_handler.ensure_json_exists("race", "data")
        target = json_handler.get_json_path("race", "data")

        empty = 0
        unparseable = 0
        total = 0
        write_failures: list = []
        lock = threading.Lock()
        stop = threading.Event()

        def write(tag: str) -> None:
            # A writer that dies silently leaves the content assertions below
            # passing vacuously. On Windows an exhausted os.replace retry raises
            # here, and that must read as a probe failure, not as a clean race.
            try:
                for i in range(150):
                    json_handler.save_json(
                        "race",
                        "data",
                        {
                            "module_name": "race",
                            "created": "2026-08-16",
                            "last_updated": "2026-08-16",
                            "writer": tag,
                            "n": i,
                            # Padding widens the truncate->write window the way a
                            # real audit document (hundreds of violations) does.
                            "padding": ["x" * 120 for _ in range(80)],
                        },
                    )
            except Exception as error:  # noqa: BLE001 - surfaced through write_failures below
                with lock:
                    write_failures.append(error)

        def read() -> None:
            nonlocal empty, unparseable, total
            while not stop.is_set():
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
                    content = target.read_text(encoding="utf-8")
                except (FileNotFoundError, OSError):
                    # PermissionError lands here too: on Windows a concurrent
                    # os.replace refuses the open. A refused open is share-mode
                    # semantics — not a torn document, and not a read at all.
                    continue
                with lock:
                    total += 1
                    if not content.strip():
                        empty += 1
                    else:
                        try:
                            json.loads(content)
                        except json.JSONDecodeError:
                            unparseable += 1

        readers = [threading.Thread(target=read, daemon=True) for _ in range(2)]
        writers = [threading.Thread(target=write, args=(f"w{i}",)) for i in range(2)]
        for t in readers:
            t.start()
        for t in writers:
            t.start()
        for t in writers:
            t.join()
        stop.set()
        for t in readers:
            t.join(timeout=5)

        assert write_failures == [], f"a writer died mid-race: {write_failures[0]!r}"
        assert total > 0, "readers never observed the document — harness proves nothing"
        assert empty == 0, f"{empty} of {total} reads saw a truncated document"
        assert unparseable == 0, f"{unparseable} of {total} reads saw a partial document"

    def test_no_staged_temp_files_survive_the_race(self, json_dir: Path):
        json_handler.ensure_json_exists("race", "data")
        for i in range(20):
            json_handler.save_json("race", "data", {"module_name": "race", "created": "x", "last_updated": "x", "n": i})
        assert sorted(p.name for p in json_dir.iterdir()) == ["race_data.json"]


#: How long to let a suspected orphan settle before convicting it. A
#: mid-rename staging file is gone in milliseconds; a real orphan is there
#: until someone deletes it. Only paid when the first look found something,
#: so a clean run costs nothing.
ORPHAN_SETTLE_SECONDS: float = 0.75


def _staging_files_now(live_dir: Path) -> set:
    """Staging temps in `live_dir` that carry THIS handler's prefix.

    Args:
        live_dir: The directory the live documents are written to.

    Returns:
        Bare filenames.
    """
    document_stems = {p.stem for p in live_dir.glob("*.json")}
    return {p.name for p in live_dir.glob("*.tmp") if any(p.name.startswith(s) for s in document_stems)}


def _orphans_that_survive_a_settle(live_dir: Path, preexisting: set, *, settle=None, sleep=None) -> tuple:
    """Look twice, and convict only what is there both times.

    THE RACE THIS CLOSES, caught by @devpulse on the round-7 commit gate: the
    detector convicted `utils_logc9s1tpcu.tmp` and the file was GONE under a
    minute later. It was a concurrent citizen's write through the shared handler,
    caught mid-``os.replace``. The detector found exactly what it looks for - the
    file simply was not an ORPHAN yet.

    That is unavoidable in a single look: a staging file and an orphan are the
    same bytes in the same place, and the only thing separating them is TIME. On
    a machine with live citizens (this one, always - daemon, watchers, agents
    answering mail) a busy gate run will keep hitting it.

    So the discriminator is persistence, not appearance. A mid-rename temp is
    gone in milliseconds; a real orphan is there until somebody deletes it.

    Args:
        live_dir: The directory the live documents are written to.
        preexisting: Staging files present at session start.
        settle: Seconds to wait before the second look. Injected for the pins.
        sleep: The sleep callable. Injected so a pin can prove the settle is
            SKIPPED on a clean first look rather than merely fast.

    Returns:
        `(all_ours_now, convicted)` - everything with our prefix, and the new
        orphans that survived both looks.
    """
    settle = ORPHAN_SETTLE_SECONDS if settle is None else settle
    sleep = time.sleep if sleep is None else sleep

    ours = _staging_files_now(live_dir)
    suspects = ours - preexisting
    if not suspects:
        return ours, set()

    sleep(settle)
    ours_after = _staging_files_now(live_dir)
    return ours_after, suspects & (ours_after - preexisting)


class TestLiveDocumentsStillParse:
    """A fix that lands on a real branch must not orphan what is already there."""

    def test_every_live_seedgo_json_document_parses(self):
        live_dir = json_handler.JSON_DIR
        if not live_dir.exists():
            pytest.skip("no live json dir on this checkout")
        for document in live_dir.glob("*.json"):
            with open(document, "r", encoding="utf-8") as handle:
                json.load(handle)

    def test_no_orphaned_temp_files_from_this_handler_in_the_live_dir(self, preexisting_live_tmp_files):
        """Scoped to THIS handler's staging prefix, and to THIS session.

        Two narrowings, each for its own reason.

        SCOPE BY PREFIX: the helper stages as "<document-stem><random>.tmp";
        incremental_cache writes its own atomic temps into the same directory
        with the stdlib default "tmp<random>.tmp" prefix. A blanket *.tmp
        assertion convicts that unrelated writer — and it does: a 4.3MB
        truncated tmp2ay2d070.tmp dated 2026-08-14 06:35 sits there ending
        mid-token, from a save_cache killed between write and os.replace.

        SCOPE BY SESSION: this assertion reads LIVE state, so an orphan created
        by anything else on the machine failed a run that changed nothing —
        which is exactly how it flaked on 2026-08-27, when killing an audit at
        16:30 left help_text_check_logml8z1bf8.tmp and reddened the next full
        suite. Diffing against a session-start snapshot makes the claim the one
        this test can actually support: this session left no NEW orphan.

        Pre-existing orphans are warned about, never silently accepted — a
        baseline nobody is told about is how a leak becomes permanent.

        SCOPE BY PERSISTENCE: a staging file and an orphan are the same bytes in
        the same place, separated only by time, so a single look convicts a
        healthy write caught mid-rename. See `_orphans_that_survive_a_settle`.
        """
        live_dir = json_handler.JSON_DIR
        if not live_dir.exists():
            pytest.skip("no live json dir on this checkout")
        ours, convicted = _orphans_that_survive_a_settle(live_dir, preexisting_live_tmp_files)
        for stale in sorted(ours & preexisting_live_tmp_files):
            warnings.warn(f"pre-existing orphan staging file in {live_dir}: {stale}", stacklevel=2)
        assert sorted(convicted) == []


class TestHelperUsesTheAtomicPrimitives:
    """Pin the mechanism, not just its effect — os.replace is the whole fix."""

    def test_uses_os_replace(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        target = tmp_path / "pinned.json"
        calls: list[tuple] = []
        real_replace = os.replace

        def recording_replace(src, dst):
            calls.append((src, dst))
            return real_replace(src, dst)

        monkeypatch.setattr(json_handler.os, "replace", recording_replace)
        json_handler._atomic_write_json(target, {"a": 1})
        assert len(calls) == 1
        assert calls[0][1] == str(target)


class TestTheOrphanDetectorConvictsPersistenceNotAppearance:
    """@devpulse's round-7 gate weather, made falsifiable on any machine.

    The gate convicted `utils_logc9s1tpcu.tmp` and the file was gone under a
    minute later - a concurrent citizen's write caught mid-``os.replace``. These
    pins reproduce both sides of that race by CONSTRUCTION rather than by
    waiting for a busy machine, because a race reproduced only under load is a
    race that will be re-litigated every time the gate is quiet.
    """

    def _dir_with(self, tmp_path: Path, tmp_names) -> Path:
        (tmp_path / "utils_log.json").write_text("{}", encoding="utf-8")
        for name in tmp_names:
            (tmp_path / name).write_text("partial", encoding="utf-8")
        return tmp_path

    def test_a_staging_file_that_VANISHES_is_acquitted(self, tmp_path):
        """The convicted-healthy case. The sleep is where the rename lands."""
        live = self._dir_with(tmp_path, ["utils_logc9s1tpcu.tmp"])

        def rename_during_the_settle(_seconds):
            (live / "utils_logc9s1tpcu.tmp").unlink()

        _, convicted = _orphans_that_survive_a_settle(live, set(), settle=0, sleep=rename_during_the_settle)
        assert convicted == set()

    def test_a_staging_file_that_PERSISTS_is_still_convicted(self, tmp_path):
        """The positive control, and the reason the cure is a re-check rather
        than a skip. A detector that stopped convicting would pass every pin
        above it and find nothing forever."""
        live = self._dir_with(tmp_path, ["utils_logc9s1tpcu.tmp"])
        _, convicted = _orphans_that_survive_a_settle(live, set(), settle=0, sleep=lambda _s: None)
        assert convicted == {"utils_logc9s1tpcu.tmp"}

    def test_a_clean_first_look_does_NOT_pay_the_settle(self, tmp_path):
        """Not a performance note - a correctness one. If the settle ran
        unconditionally, every clean run in the fleet would wait for it, and a
        cure that taxes the 99.9%% of runs it does nothing for gets deleted by
        whoever is next in a hurry."""
        live = self._dir_with(tmp_path, [])
        slept = []
        _, convicted = _orphans_that_survive_a_settle(live, set(), settle=99, sleep=lambda s: slept.append(s))
        assert convicted == set()
        assert slept == []

    def test_a_suspect_that_is_pre_existing_does_not_trigger_a_settle(self, tmp_path):
        """The session-diff narrowing still comes FIRST. A machine carrying an
        old orphan would otherwise pay the settle on every run forever."""
        live = self._dir_with(tmp_path, ["utils_logold.tmp"])
        slept = []
        ours, convicted = _orphans_that_survive_a_settle(
            live, {"utils_logold.tmp"}, settle=99, sleep=lambda s: slept.append(s)
        )
        assert convicted == set()
        assert slept == []
        assert "utils_logold.tmp" in ours

    def test_a_foreign_prefix_is_still_out_of_scope_after_the_settle(self, tmp_path):
        """The prefix narrowing survives the change. incremental_cache writes
        `tmp<random>.tmp` into the same directory and is not this handler's."""
        live = self._dir_with(tmp_path, ["tmp2ay2d070.tmp"])
        ours, convicted = _orphans_that_survive_a_settle(live, set(), settle=0, sleep=lambda _s: None)
        assert convicted == set()
        assert ours == set()

    def test_a_second_orphan_appearing_DURING_the_settle_is_not_convicted(self, tmp_path):
        """The claim stays exactly as narrow as it was: a file that shows up
        after the first look was not caught by the first look either, and
        convicting it would re-open the flake from the other end - a healthy
        write started DURING the settle would be convicted by its own arrival.

        MY FIRST VERSION OF THIS PIN WAS VACUOUS and a mutant said so. It seeded
        an empty directory, so the first look found no suspects, the function
        returned before the settle, and the late file was never even created.
        The mutant that drops the intersection survived the whole file. A pin
        that exercises an early return while claiming to test what comes after
        it is the arming-probe defect one level down: it measured nothing and
        reported the same green as a working pin. Run round 7, M17.
        """
        live = self._dir_with(tmp_path, ["utils_logreal.tmp"])

        def arrives_late(_seconds):
            (live / "utils_lognew.tmp").write_text("partial", encoding="utf-8")

        _, convicted = _orphans_that_survive_a_settle(live, set(), settle=0, sleep=arrives_late)
        assert convicted == {"utils_logreal.tmp"}

    def test_the_settle_is_long_enough_to_outlast_a_rename(self):
        """The premise this cure rests on, stated as a number rather than left
        implicit: os.replace on a local filesystem is orders of magnitude faster
        than the settle. If that stops being true the cure stops working, and
        this pin is where it would be noticed."""
        assert ORPHAN_SETTLE_SECONDS >= 0.5
