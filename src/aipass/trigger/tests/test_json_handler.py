# =================== AIPass ====================
# Name: test_json_handler.py
# Description: Unit tests for trigger json_handler
# Version: 1.0.0
# Created: 2026-03-27
# Modified: 2026-03-27
# =============================================

"""Unit tests for aipass.trigger.apps.handlers.json.json_handler."""

import json
import pytest
from pathlib import Path

from aipass.trigger.apps import config


@pytest.fixture
def json_handler(tmp_path, monkeypatch):
    """Import json_handler with TRIGGER_JSON_DIR pointed at tmp_path."""
    import importlib
    import aipass.trigger.apps.handlers.json.json_handler as mod

    monkeypatch.setattr(mod, "TRIGGER_JSON_DIR", tmp_path)
    monkeypatch.setattr(mod, "TRIGGER_ROOT", tmp_path.parent)
    importlib.reload(mod)
    monkeypatch.setattr(mod, "TRIGGER_JSON_DIR", tmp_path)
    monkeypatch.setattr(mod, "TRIGGER_ROOT", tmp_path.parent)
    return mod


# ---------------------------------------------------------------------------
# default_factory: _get_default_template returns correct structures
# ---------------------------------------------------------------------------


class TestDefaultFactory:
    """Tests for _get_default_template factory."""

    def test_config_template_has_required_keys(self, json_handler):
        """Config template contains module_name, version, and config keys."""
        result = json_handler._get_default_template("config", "test_mod")
        assert isinstance(result, dict)
        assert "module_name" in result
        assert "version" in result
        assert "config" in result
        assert result["module_name"] == "test_mod"

    def test_data_template_has_required_keys(self, json_handler):
        """Data template contains created and last_updated keys."""
        result = json_handler._get_default_template("data", "test_mod")
        assert isinstance(result, dict)
        assert "created" in result
        assert "last_updated" in result

    def test_log_template_returns_list(self, json_handler):
        """Log template returns an empty list."""
        result = json_handler._get_default_template("log", "test_mod")
        assert isinstance(result, list)
        assert len(result) == 0

    def test_unknown_type_raises(self, json_handler):
        """Unknown json_type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown json_type"):
            json_handler._get_default_template("bogus", "test_mod")


# ---------------------------------------------------------------------------
# validate: validate_json_structure
# ---------------------------------------------------------------------------


class TestValidate:
    """Tests for validate_json_structure."""

    def test_valid_config(self, json_handler):
        """Valid config dict with all required keys passes validation."""
        data = {"module_name": "x", "version": "1.0", "config": {}}
        assert json_handler.validate_json_structure(data, "config") is True

    def test_invalid_config_missing_key(self, json_handler):
        """Config dict missing required keys fails validation."""
        assert json_handler.validate_json_structure({"module_name": "x"}, "config") is False

    def test_config_non_dict(self, json_handler):
        """Non-dict input fails config validation."""
        assert json_handler.validate_json_structure([], "config") is False

    def test_valid_data(self, json_handler):
        """Data dict with created and last_updated passes validation."""
        assert json_handler.validate_json_structure({"created": "x", "last_updated": "y"}, "data") is True

    def test_valid_log(self, json_handler):
        """List passes log validation."""
        assert json_handler.validate_json_structure([], "log") is True

    def test_unknown_type(self, json_handler):
        """Unknown json_type returns False."""
        assert json_handler.validate_json_structure({}, "bogus") is False


# ---------------------------------------------------------------------------
# get_path: get_json_path returns correct Path
# ---------------------------------------------------------------------------


class TestGetPath:
    """Tests for get_json_path."""

    def test_returns_path_object(self, json_handler):
        """Return type is a Path instance."""
        result = json_handler.get_json_path("mymod", "config")
        assert isinstance(result, Path)

    def test_path_contains_module_and_type(self, json_handler):
        """Filename encodes module name and json type."""
        result = json_handler.get_json_path("mymod", "data")
        assert result.name == "mymod_data.json"

    def test_paths_return_path(self, json_handler):
        """Return type contract: get_json_path always returns a Path."""
        for jtype in ("config", "data", "log"):
            assert isinstance(json_handler.get_json_path("mod", jtype), Path)


# ---------------------------------------------------------------------------
# ensure_exists: ensure_json_exists creates files
# ---------------------------------------------------------------------------


class TestEnsureExists:
    """Tests for ensure_json_exists."""

    def test_creates_config_file(self, json_handler, tmp_path):
        """Creates a config JSON file on disk."""
        assert json_handler.ensure_json_exists("newmod", "config") is True
        path = tmp_path / "newmod_config.json"
        assert path.exists()

    def test_does_not_overwrite_valid(self, json_handler, tmp_path):
        """no_overwrite: existing valid file is preserved."""
        path = tmp_path / "keep_config.json"
        original = {"module_name": "keep", "version": "9.9.9", "config": {"custom": True}}
        path.write_text(json.dumps(original))
        json_handler.ensure_json_exists("keep", "config")
        reloaded = json.loads(path.read_text())
        assert reloaded["version"] == "9.9.9"

    def test_regenerates_corrupt_file(self, json_handler, tmp_path):
        """corrupt_json: corrupted file gets regenerated."""
        path = tmp_path / "bad_config.json"
        path.write_text("{{{not json")
        json_handler.ensure_json_exists("bad", "config")
        reloaded = json.loads(path.read_text())
        assert "module_name" in reloaded

    def test_regenerates_empty_file(self, json_handler, tmp_path):
        """empty_file: empty file gets regenerated."""
        path = tmp_path / "empty_config.json"
        path.write_text("")
        json_handler.ensure_json_exists("empty", "config")
        reloaded = json.loads(path.read_text())
        assert "module_name" in reloaded


# ---------------------------------------------------------------------------
# load: load_json
# ---------------------------------------------------------------------------


class TestLoad:
    """Tests for load_json."""

    def test_load_auto_creates_and_returns(self, json_handler):
        """Auto-creates missing file and returns default template."""
        result = json_handler.load_json("loadtest", "config")
        assert isinstance(result, dict)
        assert result["module_name"] == "loadtest"

    def test_load_log_returns_list(self, json_handler):
        """Log type returns a list."""
        result = json_handler.load_json("loadtest", "log")
        assert isinstance(result, list)

    def test_load_missing_file_creates(self, json_handler, tmp_path):
        """missing_file: load_json creates file if missing."""
        path = tmp_path / "fresh_data.json"
        assert not path.exists()
        result = json_handler.load_json("fresh", "data")
        assert result is not None
        assert path.exists()


# ---------------------------------------------------------------------------
# save: save_json
# ---------------------------------------------------------------------------


class TestSave:
    """Tests for save_json."""

    def test_save_valid_data(self, json_handler, tmp_path):
        """Saves valid data dict to disk."""
        json_handler.ensure_json_exists("smod", "data")
        data = {"created": "2026-01-01", "last_updated": "2026-01-01", "extra": 42}
        assert json_handler.save_json("smod", "data", data) is True
        reloaded = json.loads((tmp_path / "smod_data.json").read_text())
        assert reloaded["extra"] == 42

    def test_save_invalid_raises(self, json_handler):
        """exception_contract: save_json raises ValueError for invalid structure."""
        with pytest.raises(ValueError, match="Invalid structure"):
            json_handler.save_json("smod", "config", {"wrong": True})

    def test_save_invalid_mode_raises(self, json_handler):
        """exception_contract: save with bad log type raises ValueError."""
        with pytest.raises(ValueError, match="Invalid structure"):
            json_handler.save_json("smod", "log", {"not": "a list"})


# ---------------------------------------------------------------------------
# ensure_module: ensure_module_jsons creates all 3 files
# ---------------------------------------------------------------------------


class TestEnsureModule:
    """Tests for ensure_module_jsons."""

    def test_creates_all_three(self, json_handler, tmp_path):
        """Creates config, data, and log JSON files."""
        json_handler.ensure_module_jsons("trio")
        assert (tmp_path / "trio_config.json").exists()
        assert (tmp_path / "trio_data.json").exists()
        assert (tmp_path / "trio_log.json").exists()

    def test_returns_true(self, json_handler):
        """Returns True on success."""
        assert json_handler.ensure_module_jsons("rt") is True


# ---------------------------------------------------------------------------
# log_operation + infrastructure
# ---------------------------------------------------------------------------


class TestLogOperation:
    """Tests for log_operation."""

    def test_log_operation_appends_entry(self, json_handler, tmp_path):
        """Appends a log entry with operation name."""
        json_handler.log_operation("test_op", {"key": "val"}, module_name="logmod")
        log = json.loads((tmp_path / "logmod_log.json").read_text())
        assert len(log) >= 1
        assert log[-1]["operation"] == "test_op"

    def test_log_operation_rotates(self, json_handler, tmp_path):
        """Rotation: log entries beyond max_entries are trimmed."""
        # Set max to 5 via config
        json_handler.ensure_module_jsons("rotmod")
        config = json_handler.load_json("rotmod", "config")
        config["config"]["max_log_entries"] = 5
        json_handler.save_json("rotmod", "config", config)
        for i in range(10):
            json_handler.log_operation(f"op_{i}", module_name="rotmod")
        log = json.loads((tmp_path / "rotmod_log.json").read_text())
        assert len(log) == 5

    def test_reimport_after_mock(self, json_handler, tmp_path, monkeypatch):
        """infrastructure_mocking: module works after reimport with mocked paths."""
        import importlib
        import aipass.trigger.apps.handlers.json.json_handler as mod

        new_dir = tmp_path / "reimport_test"
        new_dir.mkdir()
        monkeypatch.setattr(mod, "TRIGGER_JSON_DIR", new_dir)
        importlib.reload(mod)
        monkeypatch.setattr(mod, "TRIGGER_JSON_DIR", new_dir)
        mod.ensure_json_exists("reimp", "config")
        assert (new_dir / "reimp_config.json").exists()


# ---------------------------------------------------------------------------
# increment_counter
# ---------------------------------------------------------------------------


class TestIncrementCounter:
    """Tests for increment_counter."""

    def test_creates_and_increments_new_counter(self, json_handler, tmp_path):
        """Counter starts at 0, gets incremented to 1."""
        json_handler.increment_counter("incmod", "hits")
        data = json.loads((tmp_path / "incmod_data.json").read_text(encoding="utf-8"))
        assert data["hits"] == 1

    def test_increments_existing_counter(self, json_handler, tmp_path):
        """Pre-set counter at 5, increment brings it to 6."""
        json_handler.ensure_module_jsons("incmod2")
        data = json_handler.load_json("incmod2", "data")
        data["visits"] = 5
        json_handler.save_json("incmod2", "data", data)

        json_handler.increment_counter("incmod2", "visits")
        reloaded = json.loads((tmp_path / "incmod2_data.json").read_text(encoding="utf-8"))
        assert reloaded["visits"] == 6

    def test_custom_amount(self, json_handler, tmp_path):
        """Increment by 10."""
        json_handler.increment_counter("incmod3", "score", amount=10)
        data = json.loads((tmp_path / "incmod3_data.json").read_text(encoding="utf-8"))
        assert data["score"] == 10

    def test_returns_true_on_success(self, json_handler):
        """Return value is True on success."""
        result = json_handler.increment_counter("incmod4", "counter")
        assert result is True


# ---------------------------------------------------------------------------
# update_data_metrics
# ---------------------------------------------------------------------------


class TestUpdateDataMetrics:
    """Tests for update_data_metrics."""

    def test_sets_single_metric(self, json_handler, tmp_path):
        """Update one key."""
        json_handler.update_data_metrics("metmod", uptime=99.5)
        data = json.loads((tmp_path / "metmod_data.json").read_text(encoding="utf-8"))
        assert data["uptime"] == 99.5

    def test_sets_multiple_metrics(self, json_handler, tmp_path):
        """Update several keys at once."""
        json_handler.update_data_metrics("metmod2", cpu=0.8, mem=512, ok=True)
        data = json.loads((tmp_path / "metmod2_data.json").read_text(encoding="utf-8"))
        assert data["cpu"] == 0.8
        assert data["mem"] == 512
        assert data["ok"] is True

    def test_overwrites_existing(self, json_handler, tmp_path):
        """Set a key, then update it to a new value."""
        json_handler.update_data_metrics("metmod3", version="1.0")
        json_handler.update_data_metrics("metmod3", version="2.0")
        data = json.loads((tmp_path / "metmod3_data.json").read_text(encoding="utf-8"))
        assert data["version"] == "2.0"

    def test_returns_true_on_success(self, json_handler):
        """Return value is True on success."""
        result = json_handler.update_data_metrics("metmod4", status="ok")
        assert result is True


# ---------------------------------------------------------------------------
# Concurrency: read-modify-write cycles must not lose updates
# ---------------------------------------------------------------------------


class TestConcurrentReadModifyWrite:
    """log_operation / increment_counter / update_data_metrics all read a
    document, change it in memory, and write the whole thing back. Without a
    lock across that cycle, two callers each write back a copy missing the
    other's change and the loser's entry is gone — silently, with both calls
    returning True.

    Not theoretical here: prax fires `startup` on the first log call of EVERY
    process, and startup_log.json measured ~14 writes/min from concurrent
    short-lived processes (S79). @api found the same defect in their own
    json_handler (6cd8f22c, 2026-08-16) and named five more branches carrying
    it; checking my own paths found it here too. Measured on the unfixed
    handler: 100 appends asked, 62 on disk, 38 lost.

    atomic_write_json already makes each individual write crash-safe. Atomic is
    not the same as serialised — it stops a torn file, not a lost update.
    """

    WORKERS = 4
    PER_WORKER = 25

    def _run(self, target):
        import threading

        threads = [threading.Thread(target=target, args=(n,)) for n in range(self.WORKERS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    def test_concurrent_log_operations_lose_no_entries(self, json_handler, tmp_path):
        """Every append asked for is on disk when the writers finish."""

        def worker(n):
            for i in range(self.PER_WORKER):
                json_handler.log_operation(f"op_{n}_{i}", module_name="racetest")

        self._run(worker)

        log = json.loads((tmp_path / "racetest_log.json").read_text(encoding="utf-8"))
        assert len({entry["operation"] for entry in log}) == self.WORKERS * self.PER_WORKER

    def test_concurrent_increment_counter_reaches_full_total(self, json_handler, tmp_path):
        """The classic lost update: N increments must total N."""

        def worker(_n):
            for _ in range(self.PER_WORKER):
                json_handler.increment_counter("racecount", "hits", 1)

        json_handler.ensure_module_jsons("racecount")
        self._run(worker)

        data = json.loads((tmp_path / "racecount_data.json").read_text(encoding="utf-8"))
        assert data["hits"] == self.WORKERS * self.PER_WORKER

    def test_concurrent_metric_writers_keep_every_key(self, json_handler, tmp_path):
        """Distinct keys written concurrently all survive."""

        def worker(n):
            for i in range(self.PER_WORKER):
                json_handler.update_data_metrics("racemetrics", **{f"k_{n}_{i}": i})

        json_handler.ensure_module_jsons("racemetrics")
        self._run(worker)

        data = json.loads((tmp_path / "racemetrics_data.json").read_text(encoding="utf-8"))
        written = [k for k in data if k.startswith("k_")]
        assert len(written) == self.WORKERS * self.PER_WORKER


# ---------------------------------------------------------------------------
# transient read failures: a read that could not happen must not become a write
# ---------------------------------------------------------------------------


class _FlakyRead:
    """Path.read_text that refuses ONE path with a Windows sharing violation.

    Models the exact condition os.replace already retries for, seen from the
    OTHER side: while one thread swaps a document into place, another thread's
    read of that same document can be refused by Windows. The read is the half
    nobody hardened. Patched at Path.read_text rather than builtins.open so it
    bites wherever the handler reads, not only where it happens to use open().
    """

    def __init__(self, real_read_text, target, times):
        self._real = real_read_text
        self._target = str(target)
        self.remaining = times
        self.refusals = 0

    def as_method(self):
        """A plain function, so Path binds it as a method rather than a value."""
        flaky = self

        def read_text(path_self, *args, **kwargs):
            if str(path_self) == flaky._target and flaky.remaining:
                flaky.remaining -= 1
                flaky.refusals += 1
                raise PermissionError(
                    13, "The process cannot access the file because it is being used by another process"
                )
            return flaky._real(path_self, *args, **kwargs)

        return read_text


class TestATransientReadFailureNeverDestroysTheDocument:
    """Windows CI, run 32167459635: 98 of 100 concurrent appends survived —
    two entries gone, silently, with the byte-lock working correctly.

    The lock was never the hole. `ensure_module_jsons()` runs OUTSIDE the
    critical section, and `ensure_json_exists()` treated ANY exception while
    reading as "this document is corrupt, replace it with a fresh template".
    On Windows an open() during another writer's os.replace is refused, so a
    routine timing event was read as corruption and the whole document was
    thrown away. Reproduced on Linux: 2 entries on disk, ONE refused open,
    both entries gone.

    Unreadable is not corrupt. A read that could not be performed must never
    be turned into a write.
    """

    def _seed(self, json_handler, tmp_path, module="flaky"):
        json_handler.log_operation("first", module_name=module)
        json_handler.log_operation("second", module_name=module)
        path = tmp_path / f"{module}_log.json"
        assert len(json.loads(path.read_text(encoding="utf-8"))) == 2
        return path

    def test_a_refused_read_does_not_empty_the_document(self, json_handler, tmp_path):
        """The CI defect, constructed: one refused open, nothing lost."""
        path = self._seed(json_handler, tmp_path)
        flaky = _FlakyRead(Path.read_text, path, times=1)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(Path, "read_text", flaky.as_method())
            result = json_handler.log_operation("third", module_name="flaky")

        assert flaky.refusals == 1, "fixture did not refuse anything — test is vacuous"
        entries = [e["operation"] for e in json.loads(path.read_text(encoding="utf-8"))]
        assert entries == ["first", "second", "third"], f"document was destroyed: {entries}"
        assert result is True

    def test_the_read_waits_out_the_sharing_window(self, json_handler, tmp_path):
        """A refusal that clears is waited out, not surrendered to.

        Without the bounded retry in read_text_with_retry this returns False
        and the append is dropped — honest, but still an entry short of what
        the caller asked for, and Windows CI counts entries.
        """
        path = self._seed(json_handler, tmp_path, module="window")
        flaky = _FlakyRead(Path.read_text, path, times=5)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(Path, "read_text", flaky.as_method())
            mp.setattr(config.time, "sleep", lambda _s: None)
            result = json_handler.log_operation("third", module_name="window")

        assert flaky.refusals == 5, "fixture did not refuse anything — test is vacuous"
        assert result is True, "gave up on a refusal that would have cleared"
        entries = [e["operation"] for e in json.loads(path.read_text(encoding="utf-8"))]
        assert entries == ["first", "second", "third"]

    def test_a_permanently_refused_read_refuses_the_write(self, json_handler, tmp_path):
        """When it cannot read, it declines — it does not write a fresh one."""
        path = self._seed(json_handler, tmp_path, module="stuck")
        before = path.read_text(encoding="utf-8")
        flaky = _FlakyRead(Path.read_text, path, times=10_000)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(Path, "read_text", flaky.as_method())
            mp.setattr(config.time, "sleep", lambda _s: None)
            result = json_handler.log_operation("third", module_name="stuck")

        assert result is False, "reported success while writing nothing"
        assert path.read_text(encoding="utf-8") == before, "clobbered a document it could not read"

    def test_ensure_json_exists_declines_to_regenerate_what_it_cannot_read(self, json_handler, tmp_path):
        """The destructive step itself, isolated from log_operation."""
        path = self._seed(json_handler, tmp_path, module="ensure")
        before = path.read_text(encoding="utf-8")
        flaky = _FlakyRead(Path.read_text, path, times=10_000)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(Path, "read_text", flaky.as_method())
            mp.setattr(config.time, "sleep", lambda _s: None)
            json_handler.ensure_json_exists("ensure", "log")

        assert path.read_text(encoding="utf-8") == before

    def test_load_json_returns_none_rather_than_regenerating(self, json_handler, tmp_path):
        """Cannot-read is reported as cannot-read, not as an empty document."""
        path = self._seed(json_handler, tmp_path, module="loadfail")
        before = path.read_text(encoding="utf-8")
        flaky = _FlakyRead(Path.read_text, path, times=10_000)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(Path, "read_text", flaky.as_method())
            mp.setattr(config.time, "sleep", lambda _s: None)
            result = json_handler.load_json("loadfail", "log")

        assert result is None, "an unreadable document must not read as empty"
        assert path.read_text(encoding="utf-8") == before

    def test_genuinely_corrupt_json_is_still_regenerated(self, json_handler, tmp_path):
        """The contract that made the bad path look reasonable stays intact.

        Undecodable bytes ARE a known-bad document and regenerating is the
        right answer. Only 'I could not read it' changed meaning.
        """
        path = tmp_path / "rotten_log.json"
        path.write_text("{{{ not json", encoding="utf-8")
        json_handler.ensure_json_exists("rotten", "log")
        assert json.loads(path.read_text(encoding="utf-8")) == []


class TestTheLockOutlastsTheWrite:
    """devpulse's second hypothesis for the Windows loss (2564f815): the lock
    released before the staged file was moved into place, leaving a window
    between write and replace. It does not — `return save_json(...)` is the
    last statement INSIDE the critical section, so the move completes before
    the context manager exits. Unpinned until now, which is why it was a
    reasonable thing to suspect.
    """

    def test_the_replace_happens_between_acquire_and_release(self, json_handler, monkeypatch):
        events: list = []
        real_acquire = config._acquire_lock
        real_release = config._release_lock
        real_replace = config.replace_with_retry

        def acquire(lock_file):
            events.append("acquire")
            return real_acquire(lock_file)

        def release(lock_file):
            events.append("release")
            return real_release(lock_file)

        def replace(source, destination):
            events.append(
                "replace" if str(destination).endswith("ordering_log.json") else f"replace:{Path(destination).name}"
            )
            return real_replace(source, destination)

        # Seed first: ensure_module_jsons creates the three documents on the
        # first call, and those writes are legitimately outside the lock.
        json_handler.log_operation("seed", module_name="ordering")

        monkeypatch.setattr(config, "_acquire_lock", acquire)
        monkeypatch.setattr(config, "_release_lock", release)
        monkeypatch.setattr(config, "replace_with_retry", replace)

        json_handler.log_operation("guarded", module_name="ordering")

        assert events == ["acquire", "replace", "release"], f"replace outside the lock: {events}"


class TestEnsureNeverOverwritesADocumentThatArrivedFirst:
    """CI run 32228159169, ubuntu / py3.12 / xdist gw1: 99 of 100 concurrent
    appends survived. Linux, so NOT the Windows sharing-violation species that
    round 5 closed — a different door.

    `ensure_module_jsons()` runs OUTSIDE the critical section, and its
    create-if-missing branch was implemented as a plain overwriting write. Two
    threads that both find the log missing both stage an empty template, and
    the loser's template completes AFTER a lock holder has written its first
    real entry. Reproduced before changing anything: 3 losing runs in 400
    (4 threads x 25 appends), and the write order named the culprit — two
    empty-template writes staged first, one landing after a 1-entry write.

    No lock could have prevented this: the template write is outside every
    critical section by construction. "Ensure this exists" and "write this"
    are different operations.
    """

    def test_a_document_created_while_the_template_was_staged_survives(self, json_handler, tmp_path):
        """The race window, made deterministic.

        _get_default_template runs between the exists() check and the write,
        which is exactly the window another writer creates and fills the
        document in. Writing real content from inside it models that writer
        without threads or timing.
        """
        path = tmp_path / "race_log.json"
        real_template = json_handler._get_default_template

        def template_and_a_racing_writer(json_type, module_name):
            if module_name == "race" and json_type == "log":
                path.write_text(json.dumps([{"timestamp": "t", "operation": "kept"}]), encoding="utf-8")
            return real_template(json_type, module_name)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(json_handler, "_get_default_template", template_and_a_racing_writer)
            json_handler.ensure_json_exists("race", "log")

        entries = [e["operation"] for e in json.loads(path.read_text(encoding="utf-8"))]
        assert entries == ["kept"], f"a template landed on top of real content: {entries}"

    def test_it_still_creates_the_document_when_nothing_is_there(self, json_handler, tmp_path):
        """The contract the create path exists for, unchanged."""
        path = tmp_path / "fresh_log.json"
        assert not path.exists()
        json_handler.ensure_json_exists("fresh", "log")
        assert json.loads(path.read_text(encoding="utf-8")) == []
