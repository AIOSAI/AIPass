# =================== AIPass ====================
# Name: test_json_handler.py
# Description: Tests for the fleet json service through prax's own shim
# Version: 2.4.0
# Created: 2026-03-28
# Modified: 2026-11-17
# =============================================

"""Tests for apps/handlers/json/json_handler.py and apps/handlers/json/json_service.py."""

# Redirection is the AIPASS_TEST_LOG_DIR seam, never a patched attribute: the service resolves per call.

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(json_handler) — that json_handler.py binds byte-identically fleet-wide

import json
import os
import stat
import time
from datetime import date

import pytest

import aipass.prax
from aipass.prax.apps.handlers.json import json_handler
from aipass.prax.apps.handlers.json import json_service
from aipass.prax.apps.handlers.monitoring import rate_tracker


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    """Point the service at a temp tree; set AFTER import on purpose, so a late redirect must still work."""
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
    handle = json_service.for_module(json_handler.__file__)
    return handle.json_dir


@pytest.fixture
def handle(monkeypatch, tmp_path):
    """A JsonHandle for prax, writing under a temp tree."""
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
    return json_service.for_module(json_handler.__file__)


@pytest.fixture
def sample_data():
    """A valid config document — the shape the service declares for "config"."""
    return {"module_name": "sample", "version": "1.0.0", "config": {"max_log_entries": 5}}


class TestForModule:
    """for_module derives the branch root from the shim's own __file__."""

    def test_derives_the_branch_root_from_the_shim(self):
        """apps/handlers/json/json_handler.py -> the branch directory."""
        resolved = json_service.for_module(json_handler.__file__)

        assert resolved.branch_root.name == "prax"

    def test_takes_the_path_apart_without_resolving_it(self, tmp_path):
        """parents[3], not resolve(): a deleted cwd or a missing path is still taken apart correctly."""
        made_up = tmp_path / "notabranch" / "apps" / "handlers" / "json" / "json_handler.py"

        resolved = json_service.for_module(made_up)

        assert resolved.branch_root == tmp_path / "notabranch"

    def test_a_symlinked_path_is_not_followed(self, tmp_path):
        """resolve() would walk the link to its target and name the WRONG branch."""
        real = tmp_path / "real_branch" / "apps" / "handlers" / "json"
        real.mkdir(parents=True)
        (real / "json_handler.py").write_text("", encoding="utf-8")
        link = tmp_path / "linked_branch"
        link.symlink_to(tmp_path / "real_branch", target_is_directory=True)

        resolved = json_service.for_module(link / "apps" / "handlers" / "json" / "json_handler.py")

        assert resolved.branch_root == link
        assert resolved.branch_root.name == "linked_branch"


class TestTheJsonDirectoryIsResolvedPerCall:
    """AIPASS_TEST_LOG_DIR, in trigger's form, honoured on every access."""

    def test_the_env_var_redirects_out_of_the_real_tree(self, monkeypatch, tmp_path):
        resolved = json_service.for_module(json_handler.__file__)
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))

        assert resolved.json_dir == tmp_path / "prax" / "prax_json"

    def test_absent_env_var_is_the_real_tree(self, monkeypatch):
        monkeypatch.delenv("AIPASS_TEST_LOG_DIR", raising=False)
        resolved = json_service.for_module(json_handler.__file__)

        assert resolved.json_dir.name == "prax_json"
        assert resolved.json_dir.parent.name == "prax"

    def test_an_empty_env_var_is_absence_not_the_filesystem_root(self, monkeypatch):
        """AIPASS_TEST_LOG_DIR='' must not resolve to /prax/prax_json.

        ``is not None`` would build the RELATIVE prax/prax_json, ``Path("/")`` the root; this equality refuses both.
        """
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", "")
        resolved = json_service.for_module(json_handler.__file__)

        assert resolved.json_dir == resolved.branch_root / "prax_json"
        assert resolved.json_dir.is_absolute()

    def test_a_later_change_of_the_variable_wins(self, monkeypatch, tmp_path):
        """Nothing is captured: a value read once at import made a redirect stick for the process."""
        resolved = json_service.for_module(json_handler.__file__)
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "first"))
        first = resolved.json_dir

        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "second"))

        assert first == tmp_path / "first" / "prax" / "prax_json"
        assert resolved.json_dir == tmp_path / "second" / "prax" / "prax_json"

    def test_the_path_builder_resolves_at_call_time(self, monkeypatch, tmp_path):
        """The use site, not just the property: get_json_path must not read a captured directory."""
        resolved = json_service.for_module(json_handler.__file__)
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))

        built = resolved.get_json_path("probe", "config")

        assert built == tmp_path / "prax" / "prax_json" / "probe_config.json"


class TestReadJson:
    """read_json never raises: it answers None or a document."""

    def test_returns_the_document(self, handle, tmp_path):
        target = tmp_path / "doc.json"
        target.write_text(json.dumps({"a": 1}), encoding="utf-8")

        assert handle.read_json(target) == {"a": 1}

    def test_missing_file_is_none(self, handle, tmp_path):
        assert handle.read_json(tmp_path / "nothing.json") is None

    def test_unparseable_file_is_none(self, handle, tmp_path):
        target = tmp_path / "broken.json"
        target.write_text("{not json", encoding="utf-8")

        assert handle.read_json(target) is None

    def test_a_directory_is_none_not_a_crash(self, handle, tmp_path):
        """An OSError that is not FileNotFoundError still answers None."""
        assert handle.read_json(tmp_path) is None


class TestWriteJson:
    """write_json lands atomically, answers bool, and never hides a payload bug."""

    def test_writes_and_creates_parents(self, handle, tmp_path):
        target = tmp_path / "deep" / "nested" / "doc.json"

        assert handle.write_json(target, {"a": 1}) is True
        assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}

    def test_leaves_no_temp_file_behind(self, handle, tmp_path):
        handle.write_json(tmp_path / "doc.json", {"a": 1})

        assert list(tmp_path.glob("*.tmp")) == []

    def test_a_killed_writers_old_temp_file_is_swept_and_a_fresh_one_kept(self, handle, tmp_path):
        """Only orphans over an hour old go: a fresh one may be another writer's in-flight stage."""
        stale, fresh, foreign = tmp_path / ".111_0.tmp", tmp_path / ".222_0.tmp", tmp_path / ".other.tmp"
        for path in (stale, fresh, foreign):
            path.write_text("{}", encoding="utf-8")
        two_hours_ago = stale.stat().st_mtime - 7200
        os.utime(stale, (two_hours_ago, two_hours_ago))
        os.utime(foreign, (two_hours_ago, two_hours_ago))

        handle.write_json(tmp_path / "doc.json", {"a": 1})

        assert not stale.exists()
        assert fresh.exists()
        assert foreign.exists()

    def test_a_non_serialisable_payload_raises_typeerror(self, handle, tmp_path):
        """A payload bug is not a write failure: serialising FIRST keeps it from collapsing to False."""
        with pytest.raises(TypeError):
            handle.write_json(tmp_path / "doc.json", {"bad": object()})

    def test_a_circular_payload_raises_valueerror(self, handle, tmp_path):
        payload: dict = {}
        payload["self"] = payload

        with pytest.raises(ValueError):
            handle.write_json(tmp_path / "doc.json", payload)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "-inf"])
    def test_a_non_finite_number_raises_valueerror(self, handle, tmp_path, bad):
        """NaN and Infinity are not JSON, and Python writes them anyway.

        A strict parser elsewhere fails days later; the service raises ValueError in the sweep that made it.
        """
        with pytest.raises(ValueError):
            handle.write_json(tmp_path / "doc.json", {"measure": bad})

    def test_a_refused_non_finite_number_writes_nothing_at_all(self, handle, tmp_path):
        """Refusing after landing a half-document would be worse than allowing it."""
        target = tmp_path / "doc.json"
        target.write_text(json.dumps({"live": True}), encoding="utf-8")

        with pytest.raises(ValueError):
            handle.write_json(target, {"measure": float("nan")})

        assert json.loads(target.read_text(encoding="utf-8")) == {"live": True}
        assert list(tmp_path.glob("*.tmp")) == []

    def test_a_failed_write_answers_false_and_never_raises(self, handle, tmp_path, monkeypatch):
        """OSError anywhere on the way answers False: the six production bool consumers depend on it."""
        monkeypatch.setattr(json_service.os, "replace", _raise_oserror)

        assert handle.write_json(tmp_path / "doc.json", {"a": 1}) is False

    def test_a_failed_write_cleans_up_its_temp_file(self, handle, tmp_path, monkeypatch):
        """A staged file left behind is litter that accumulates silently."""
        monkeypatch.setattr(json_service.os, "replace", _raise_oserror)

        handle.write_json(tmp_path / "doc.json", {"a": 1})

        assert list(tmp_path.glob("*.tmp")) == []

    def test_a_failed_write_leaves_the_original_intact(self, handle, tmp_path, monkeypatch):
        """The staged-write guarantee: a write that cannot land destroys nothing."""
        target = tmp_path / "doc.json"
        target.write_text(json.dumps({"live": True}), encoding="utf-8")
        monkeypatch.setattr(json_service.os, "replace", _raise_oserror)

        handle.write_json(target, {"replacement": True})

        assert json.loads(target.read_text(encoding="utf-8")) == {"live": True}


def _raise_oserror(source, destination):
    """Stand-in for an os.replace that always fails."""
    raise OSError("replace refused")


class TestTheWriteNeverChoosesTheDocumentsMode:
    """A write must not change permissions the caller never asked it to change.

    A staged NamedTemporaryFile is 0600 and os.replace carries that mode over. Existing documents keep
    theirs by fchmod, new ones get the umask: two mechanisms, pinned separately.
    """

    @pytest.mark.parametrize("mode", [0o664, 0o644, 0o600, 0o640], ids=["664", "644", "600", "640"])
    def test_an_existing_documents_mode_survives_a_rewrite(self, handle, tmp_path, mode):
        """Preserved, not widened and not narrowed: whatever it was, it stays."""
        target = tmp_path / "doc.json"
        target.write_text(json.dumps({"a": 1}), encoding="utf-8")
        os.chmod(target, mode)

        assert handle.write_json(target, {"a": 2}) is True

        assert stat.S_IMODE(target.stat().st_mode) == mode
        assert json.loads(target.read_text(encoding="utf-8")) == {"a": 2}

    def test_a_new_document_gets_the_mode_a_plain_open_would_give(self, handle, tmp_path):
        """The reference is measured in the same directory, never hardcoded: the umask decides."""
        reference = tmp_path / "reference.txt"
        with open(reference, "w", encoding="utf-8") as probe:
            probe.write("x")
        expected = stat.S_IMODE(reference.stat().st_mode)

        target = tmp_path / "fresh.json"
        assert handle.write_json(target, {"a": 1}) is True

        assert stat.S_IMODE(target.stat().st_mode) == expected

    def test_a_typed_document_the_service_creates_itself_is_no_different(self, handle, sandbox):
        """ensure_json_exists is how most documents are born; same rule."""
        reference = sandbox.parent / "reference.txt"
        reference.parent.mkdir(parents=True, exist_ok=True)
        with open(reference, "w", encoding="utf-8") as probe:
            probe.write("x")
        expected = stat.S_IMODE(reference.stat().st_mode)

        handle.ensure_json_exists("mode_probe", "config")

        assert stat.S_IMODE((sandbox / "mode_probe_config.json").stat().st_mode) == expected


class TestValidateJsonStructure:
    """The three declared shapes, and the refusal of a fourth."""

    @pytest.mark.parametrize(
        "json_type,document,expected",
        [
            ("config", {"module_name": "m", "version": "1.0.0", "config": {}}, True),
            ("config", {"module_name": "m", "version": "1.0.0"}, False),
            ("config", "not a dict", False),
            ("data", {"created": "d", "last_updated": "d"}, True),
            ("data", {"created": "d"}, False),
            ("data", [], False),
            ("log", [], True),
            ("log", [{"operation": "x"}], True),
            ("log", {}, False),
            ("mystery", {"anything": True}, False),
        ],
    )
    def test_the_declared_shapes(self, handle, json_type, document, expected):
        assert handle.validate_json_structure(document, json_type) is expected


class TestGetJsonPath:
    """The name on disk, and the one behaviour that refuses rather than writes."""

    def test_builds_module_and_type(self, handle, sandbox):
        assert handle.get_json_path("mod", "data") == sandbox / "mod_data.json"

    def test_an_unknown_json_type_is_refused(self, handle):
        """A typo'd type used to create a document nothing would ever read."""
        with pytest.raises(ValueError):
            handle.get_json_path("mod", "confg")


class TestEnsureJsonExists:
    """Self-healing: the document is there and valid when this returns."""

    def test_creates_a_missing_document_from_the_in_code_default(self, handle, sandbox):
        assert handle.ensure_json_exists("fresh", "config") is True

        written = json.loads((sandbox / "fresh_config.json").read_text(encoding="utf-8"))
        assert written["module_name"] == "fresh"
        assert written["config"]["max_log_entries"] == json_service.DEFAULT_MAX_LOG_ENTRIES

    def test_the_default_passes_its_own_validator(self, handle):
        """A default the handler would itself reject is a self-healing loop; the type list is the floor."""
        assert json_service.JSON_TYPES == ("config", "data", "log")

        # Reached through ensure_json_exists on a missing document, the door that writes it.
        for json_type in json_service.JSON_TYPES:
            assert handle.ensure_json_exists("any", json_type) is True
            document = handle.read_json(handle.get_json_path("any", json_type))

            assert handle.validate_json_structure(document, json_type) is True

    def test_a_valid_document_is_preserved(self, handle, sandbox):
        sandbox.mkdir(parents=True, exist_ok=True)
        original = {"module_name": "keep", "version": "9.9.9", "config": {"custom": True}}
        (sandbox / "keep_config.json").write_text(json.dumps(original), encoding="utf-8")

        handle.ensure_json_exists("keep", "config")

        assert json.loads((sandbox / "keep_config.json").read_text(encoding="utf-8")) == original

    @pytest.mark.parametrize(
        "content",
        ["{not json", "", json.dumps(["a", "list"])],
        ids=["unreadable", "empty", "misshaped"],
    )
    def test_a_bad_document_raises_and_is_never_overwritten(self, handle, sandbox, content):
        """A corrupt config read as absent and replaced by the default loses the owner's keys."""
        sandbox.mkdir(parents=True, exist_ok=True)
        target = sandbox / "broken_config.json"
        target.write_text(content, encoding="utf-8")

        with pytest.raises(json_service.InvalidDocument, match="not overwritten"):
            handle.ensure_json_exists("broken", "config")

        assert target.read_text(encoding="utf-8") == content

    def test_a_misshaped_log_on_disk_answers_false_and_is_left_as_it_was(self, handle, sandbox):
        """log_operation is telemetry: a bad document is refused without raising and without a rewrite."""
        sandbox.mkdir(parents=True, exist_ok=True)
        target = sandbox / "bad_log.json"
        target.write_text(json.dumps({"not": "a list"}), encoding="utf-8")

        assert handle.log_operation("probe", module_name="bad") is False

        assert json.loads(target.read_text(encoding="utf-8")) == {"not": "a list"}

    def test_ensure_module_jsons_creates_all_three(self, handle, sandbox):
        assert handle.ensure_module_jsons("trio") is True

        for json_type in json_service.JSON_TYPES:
            assert (sandbox / f"trio_{json_type}.json").exists()


class TestLoadJson:
    """A caller that asks for a document of a known shape gets one."""

    def test_creates_then_loads(self, handle):
        loaded = handle.load_json("madeup", "config")

        assert loaded["module_name"] == "madeup"

    def test_returns_what_is_on_disk(self, handle, sandbox):
        sandbox.mkdir(parents=True, exist_ok=True)
        (sandbox / "live_data.json").write_text(
            json.dumps({"created": "d", "last_updated": "d", "files": {"x": 1}}), encoding="utf-8"
        )

        assert handle.load_json("live", "data")["files"] == {"x": 1}

    def test_an_unknown_json_type_is_refused(self, handle):
        with pytest.raises(ValueError):
            handle.load_json("mod", "logs")


class TestSaveJson:
    """save_json either lands or raises — it never answers False."""

    def test_writes_a_document_that_parses_from_disk(self, handle, sandbox, sample_data):
        assert handle.save_json("saver", "config", sample_data) is True
        assert json.loads((sandbox / "saver_config.json").read_text(encoding="utf-8")) == sample_data

    def test_a_saved_document_round_trips_through_load(self, handle, sample_data):
        """Written and read back by the service itself: the two halves have to agree about one file."""
        handle.save_json("roundtrip", "config", sample_data)

        assert handle.load_json("roundtrip", "config") == sample_data

    def test_a_data_document_gets_a_fresh_last_updated(self, handle):
        document = {"created": "2020-01-01", "last_updated": "2020-01-01"}

        handle.save_json("stamped", "data", document)

        assert document["last_updated"] != "2020-01-01"

    def test_an_invalid_document_raises_invaliddocument(self, handle):
        """False here would be indistinguishable from a disk failure."""
        with pytest.raises(json_service.InvalidDocument):
            handle.save_json("bad", "config", {"module_name": "only"})

    def test_a_write_that_cannot_land_raises_writefailed(self, handle, monkeypatch):
        """A lost document must not look like success, nor like a caller's validation mistake."""
        monkeypatch.setattr(json_service.os, "replace", _raise_oserror)

        with pytest.raises(json_service.WriteFailed):
            handle.save_json("doomed", "log", [])

    def test_a_non_serialisable_payload_raises_typeerror(self, handle):
        with pytest.raises(TypeError):
            handle.save_json("bad", "log", [object()])


class TestLogOperation:
    """Telemetry: loud about a caller bug, quiet about a disk failure."""

    def test_appends_a_timestamped_entry(self, handle, sandbox):
        assert handle.log_operation("started", module_name="ops") is True

        entries = json.loads((sandbox / "ops_log.json").read_text(encoding="utf-8"))
        assert len(entries) == 1
        assert entries[0]["operation"] == "started"
        assert entries[0]["timestamp"]

    def test_attaches_data_when_given(self, handle, sandbox):
        handle.log_operation("started", {"pid": 7}, module_name="ops")

        entries = json.loads((sandbox / "ops_log.json").read_text(encoding="utf-8"))
        assert entries[0]["data"] == {"pid": 7}

    def test_accumulates_in_order(self, handle, sandbox):
        for name in ("first", "second", "third"):
            handle.log_operation(name, module_name="ops")

        entries = json.loads((sandbox / "ops_log.json").read_text(encoding="utf-8"))
        assert [entry["operation"] for entry in entries] == ["first", "second", "third"]

    def test_rotates_to_the_declared_cap(self, handle, sandbox):
        """The knob published in every config document is honoured, not a constant."""
        handle.ensure_module_jsons("capped")
        config = handle.load_json("capped", "config")
        config["config"]["max_log_entries"] = 3
        handle.save_json("capped", "config", config)

        for index in range(6):
            handle.log_operation(f"op{index}", module_name="capped")

        entries = json.loads((sandbox / "capped_log.json").read_text(encoding="utf-8"))
        assert [entry["operation"] for entry in entries] == ["op3", "op4", "op5"]

    def test_a_non_integer_cap_falls_back_to_the_default(self, handle):
        handle.ensure_module_jsons("weird")
        config = handle.load_json("weird", "config")
        config["config"]["max_log_entries"] = "lots"
        handle.save_json("weird", "config", config)

        assert handle._max_log_entries("weird") == json_service.DEFAULT_MAX_LOG_ENTRIES

    def test_a_write_failure_answers_false_and_does_not_raise(self, handle, monkeypatch):
        """log_operation runs on the monitor's threads: a raising writer there is silent half-death."""
        monkeypatch.setattr(json_service.os, "replace", _raise_oserror)

        assert handle.log_operation("doomed", module_name="ops") is False

    def test_a_non_serialisable_payload_answers_false(self, handle):
        """A payload bug in telemetry still must not take the caller down."""
        assert handle.log_operation("bad", {"obj": object()}, module_name="ops") is False

    def test_a_non_finite_number_in_telemetry_answers_false(self, handle):
        """The NaN refusal must not become a raise on the monitor's threads."""
        assert handle.log_operation("rate", {"lines_per_min": float("inf")}, module_name="ops") is False

    def test_names_the_calling_module_when_not_told(self, handle, sandbox):
        """Frame 2, and it is why the shim BINDS: a wrapper would rename every logged operation."""
        handle.log_operation("auto")

        entries = json.loads((sandbox / "test_json_handler_log.json").read_text(encoding="utf-8"))
        assert entries[-1]["operation"] == "auto"


def _trail_errors(tmp_path):
    """ERROR lines on the json service's trail under the seam."""
    trail_file = tmp_path / "prax" / "logs" / "json_service.jsonl"
    if not trail_file.exists():
        return []
    lines = [json.loads(line) for line in trail_file.read_text(encoding="utf-8").splitlines()]
    return [line for line in lines if line["level"] == "ERROR"]


def _one_more(document):
    """An update that counts its own rounds."""
    document["rounds"] = document.get("rounds", 0) + 1
    return document


class TestUpdateJson:
    """One read-modify-write under the module's lock: lands whole, or not at all and loudly."""

    def test_a_missing_document_starts_from_the_default_and_takes_the_change(self, handle, sandbox):
        assert handle.update_json("fresh", "data", _one_more) is True

        saved = _read_data(sandbox, "fresh")
        assert saved["rounds"] == 1
        assert saved["created"] == saved["last_updated"] == date.today().isoformat()

    def test_a_raising_fn_leaves_the_document_byte_for_byte_and_the_lock_free(self, handle, sandbox):
        handle.update_json("held", "data", _one_more)
        before = (sandbox / "held_data.json").read_bytes()

        def half_done(document):
            document["rounds"] = 99
            raise RuntimeError("fn failed")

        with pytest.raises(RuntimeError, match="fn failed"):
            handle.update_json("held", "data", half_done)

        assert (sandbox / "held_data.json").read_bytes() == before
        assert handle.update_json("held", "data", _one_more) is True
        assert _read_data(sandbox, "held")["rounds"] == 2

    def test_asking_again_for_the_held_lock_is_refused_at_once_with_one_error(
        self, handle, sandbox, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(json_service, "LOCK_DEADLINE_SECONDS", 0.5)
        handle.update_json("nested", "data", _one_more)
        before = (sandbox / "nested_data.json").read_bytes()

        started = time.monotonic()
        with pytest.raises(json_service.LockReentry):
            handle.update_json("nested", "data", lambda document: handle.update_json("nested", "data", _one_more))
        waited = time.monotonic() - started

        assert waited < 0.25
        assert (sandbox / "nested_data.json").read_bytes() == before
        assert [(e["msg"], e["module"]) for e in _trail_errors(tmp_path)] == [
            ("json_service: update_json lock not acquired", "nested")
        ]

    def test_log_operation_inside_fn_answers_false_and_the_update_still_lands(
        self, handle, sandbox, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(json_service, "LOCK_DEADLINE_SECONDS", 0.5)
        answers = []

        def logs_inside(document):
            answers.append(handle.log_operation("inside", module_name="nested"))
            return _one_more(document)

        started = time.monotonic()
        assert handle.update_json("nested", "data", logs_inside) is True

        assert time.monotonic() - started < 0.25
        assert answers == [False]
        assert _read_data(sandbox, "nested")["rounds"] == 1
        assert not (sandbox / "nested_log.json").exists()
        assert [e["msg"] for e in _trail_errors(tmp_path)] == ["json_service: log_operation lock not acquired"]

    @pytest.mark.parametrize("bad", ["{not json", "[1, 2]"], ids=["corrupt", "misshaped"])
    def test_a_bad_document_is_set_aside_refused_once_and_rebuilt_on_the_next_call(
        self, handle, sandbox, tmp_path, bad
    ):
        sandbox.mkdir(parents=True)
        (sandbox / "broken_data.json").write_text(bad, encoding="utf-8")

        with pytest.raises(json_service.InvalidDocument):
            handle.update_json("broken", "data", _one_more)

        kept = list(sandbox.glob("broken_data.json.corrupt-*"))
        assert [path.read_text(encoding="utf-8") for path in kept] == [bad]
        errors = _trail_errors(tmp_path)
        assert [(e["msg"], e["kept"]) for e in errors] == [
            ("json_service: update_json refused a corrupt document", str(kept[0]))
        ]

        assert handle.update_json("broken", "data", _one_more) is True
        assert _read_data(sandbox, "broken")["rounds"] == 1

    def test_a_misshaped_result_from_fn_is_refused_and_the_good_document_stays(self, handle, sandbox):
        handle.update_json("kept", "data", _one_more)
        before = (sandbox / "kept_data.json").read_bytes()

        with pytest.raises(json_service.InvalidDocument):
            handle.update_json("kept", "data", lambda document: None)

        assert (sandbox / "kept_data.json").read_bytes() == before
        assert not list(sandbox.glob("kept_data.json.corrupt-*"))

    @pytest.mark.skipif(os.geteuid() == 0, reason="root reads a 000 file: the unreadable route needs a non-root user")
    def test_an_unreadable_document_is_left_in_place_not_set_aside(self, handle, sandbox, tmp_path):
        handle.update_json("locked", "data", _one_more)
        target = sandbox / "locked_data.json"
        target.chmod(0)
        try:
            with pytest.raises(json_service.InvalidDocument):
                handle.update_json("locked", "data", _one_more)
        finally:
            target.chmod(0o644)

        assert _read_data(sandbox, "locked")["rounds"] == 1
        assert not list(sandbox.glob("locked_data.json.corrupt-*"))
        assert _trail_errors(tmp_path)[0]["kept"].startswith("left in place: ")


def _seed_data(sandbox, module_name, document):
    """Put a data document on disk exactly as given, bypassing the service."""
    sandbox.mkdir(parents=True, exist_ok=True)
    (sandbox / f"{module_name}_data.json").write_text(json.dumps(document), encoding="utf-8")


def _read_data(sandbox, module_name):
    """The data document as bytes on disk say it is, not as the service reads it."""
    return json.loads((sandbox / f"{module_name}_data.json").read_text(encoding="utf-8"))


class TestTheDataLegIsHealedNotReplaced:
    """ensure_json_exists adds a data document's missing base keys and keeps the rest.

    log_operation runs ensure before every bump; a replace would wipe rate_tracker's live ``files``.
    """

    def test_a_data_document_missing_its_base_keys_keeps_every_key_it_has(self, handle, sandbox):
        """Existing keys win: ``created`` is not re-stamped, ``files`` is not dropped."""
        _seed_data(sandbox, "partial", {"created": "2020-01-01", "files": {"a.log": {"last_offset": 7}}})

        assert handle.ensure_json_exists("partial", "data") is True

        assert _read_data(sandbox, "partial") == {
            "created": "2020-01-01",
            "files": {"a.log": {"last_offset": 7}},
            "last_updated": date.today().isoformat(),
        }

    def test_the_config_leg_is_refused_not_merged(self, handle, sandbox):
        """The heal is the data leg's alone: an invalid config raises and keeps its keys."""
        sandbox.mkdir(parents=True, exist_ok=True)
        stray = {"module_name": "stray", "stray": True}
        (sandbox / "stray_config.json").write_text(json.dumps(stray), encoding="utf-8")

        with pytest.raises(json_service.InvalidDocument):
            handle.ensure_json_exists("stray", "config")

        assert json.loads((sandbox / "stray_config.json").read_text(encoding="utf-8")) == stray

    def test_a_data_document_that_cannot_be_written_back_is_left_as_it_was(self, handle, sandbox):
        """json.load reads NaN, the writer refuses it: the document is left as it was, the log leg works."""
        sandbox.mkdir(parents=True, exist_ok=True)
        target = sandbox / "nan_data.json"
        target.write_text('{"rate": NaN}', encoding="utf-8")

        assert handle.ensure_json_exists("nan", "data") is False
        assert target.read_text(encoding="utf-8") == '{"rate": NaN}'
        assert handle.log_operation("still_logs", module_name="nan") is True
        assert target.read_text(encoding="utf-8") == '{"rate": NaN}'


class TestEveryLogWriteBumpsTheDataLeg:
    """log_operation counts itself into the module's lifetime data document."""

    def test_every_logged_operation_counts_exactly_once(self, handle, sandbox):
        for name in ("first", "second", "third"):
            assert handle.log_operation(name, module_name="counted") is True

        document = _read_data(sandbox, "counted")
        assert document["operations_total"] == 3
        assert document["last_operation"] == "third"
        assert document["last_updated"] == date.today().isoformat()

    def test_keys_the_bump_does_not_own_survive_it(self, handle, sandbox):
        """Read-modify-write, never a fresh dict: the old-era success/failure counters stay as they were."""
        seeded = {
            "module_name": "keeper",
            "created": "2020-01-01",
            "last_updated": "2020-01-01",
            "operations_total": 41,
            "operations_successful": 0,
            "operations_failed": 0,
            "files": {"/logs/a.log": {"last_offset": 7, "rates": [[1.0, 2.0]]}},
        }
        _seed_data(sandbox, "keeper", seeded)

        assert handle.log_operation("kept", module_name="keeper") is True

        assert _read_data(sandbox, "keeper") == {
            **seeded,
            "operations_total": 42,
            "last_operation": "kept",
            "last_updated": date.today().isoformat(),
        }

    def test_an_empty_data_document_is_healed_and_counted_not_refused(self, handle, sandbox):
        """The live case: a data document of ``{}`` is healed, or every log call fails its bump."""
        _seed_data(sandbox, "blank", {})

        assert handle.log_operation("first", module_name="blank") is True

        today = date.today().isoformat()
        assert _read_data(sandbox, "blank") == {
            "created": today,
            "last_updated": today,
            "module_name": "blank",
            "operations_total": 1,
            "last_operation": "first",
        }

    @pytest.mark.parametrize("junk", ["abc", True, None, [3]], ids=["str", "bool", "null", "list"])
    def test_a_total_that_is_not_an_integer_restarts_at_one(self, handle, sandbox, junk):
        """A bool is an int to Python, so True + 1 would count to 2; the type is asserted too."""
        _seed_data(sandbox, "junky", {"created": "2020-01-01", "last_updated": "2020-01-01", "operations_total": junk})

        assert handle.log_operation("recount", module_name="junky") is True

        total = _read_data(sandbox, "junky")["operations_total"]
        assert total == 1 and type(total) is int, total

    def test_a_log_entry_that_did_not_land_is_not_counted(self, handle, sandbox, monkeypatch):
        """The bump follows the log write; a failed log is not an operation."""
        _seed_data(sandbox, "unlogged", {"created": "2020-01-01", "last_updated": "2020-01-01"})
        real_save = handle.save_json

        def refuse_the_log(module_name, json_type, data):
            if json_type == "log":
                raise json_service.WriteFailed("log leg refused")
            return real_save(module_name, json_type, data)

        monkeypatch.setattr(handle, "save_json", refuse_the_log)

        assert handle.log_operation("lost", module_name="unlogged") is False
        assert "operations_total" not in _read_data(sandbox, "unlogged")

    @pytest.mark.parametrize(
        "failure",
        [
            json_service.WriteFailed("data leg refused"),
            json_service.InvalidDocument("data leg invalid"),
            TypeError("data leg unserialisable"),
        ],
        ids=["writefailed", "invaliddocument", "typeerror"],
    )
    def test_a_failed_bump_never_breaks_the_log(self, handle, sandbox, monkeypatch, tmp_path, failure):
        """Telemetry on the monitor's threads: the log entry already landed, so
        the answer stays the log's own True and the failure is a warning on prax's trail."""
        real_save = handle.save_json

        def refuse_the_data(module_name, json_type, data):
            if json_type == "data":
                raise failure
            return real_save(module_name, json_type, data)

        monkeypatch.setattr(handle, "save_json", refuse_the_data)

        answer = handle.log_operation("survives", module_name="fragile")

        assert answer is True
        entries = json.loads((sandbox / "fragile_log.json").read_text(encoding="utf-8"))
        assert [entry["operation"] for entry in entries] == ["survives"]
        assert "operations_total" not in _read_data(sandbox, "fragile")
        trail_file = tmp_path / "prax" / "logs" / "json_service.jsonl"
        warned = [json.loads(line) for line in trail_file.read_text(encoding="utf-8").splitlines()]
        assert [(r["level"], r["module"], r["error"]) for r in warned] == [("WARNING", "fragile", str(failure))]


def _real_tracker(monkeypatch, tmp_path):
    """The real tracker on the real shim with a fresh process's state; returns the one log file it scans."""
    logs = tmp_path / "scanned_logs"
    logs.mkdir()
    log_file = logs / "a.log"
    log_file.write_bytes(b"x" * 4096)
    monkeypatch.setattr(rate_tracker, "json_handler", json_handler)
    monkeypatch.setattr(rate_tracker, "_tracked", {})
    monkeypatch.setattr(rate_tracker, "_state_loaded", False)
    monkeypatch.setattr(rate_tracker, "_logs_dir", None)
    monkeypatch.setattr(rate_tracker, "_suppressed_files", set())
    rate_tracker.configure(logs_dir=logs)
    return log_file


class TestRateTrackerKeepsKeysItDoesNotOwn:
    """rate_tracker_data.json is both the tracker's state and its data leg."""

    def test_the_counters_and_the_trackers_files_survive_each_others_writes(self, sandbox, monkeypatch, tmp_path):
        """The real tracker against the real shim, both writing one document; each sets only its own keys."""
        log_file = _real_tracker(monkeypatch, tmp_path)
        seed = {"created": "2020-01-01", "last_updated": "2020-01-01"}
        _seed_data(sandbox, "rate_tracker", seed)

        json_handler.log_operation("runaway_detected", module_name="rate_tracker")
        json_handler.log_operation("runaway_detected", module_name="rate_tracker")
        rate_tracker.scan_rates()

        saved = _read_data(sandbox, "rate_tracker")
        assert saved["operations_total"] == 2
        assert saved["last_operation"] == "runaway_detected"
        assert saved["created"] == seed["created"]
        assert saved["module_name"] == "rate_tracker"
        assert list(saved["files"]) == [str(log_file)]
        assert saved["files"][str(log_file)]["last_offset"] == 4096

        json_handler.log_operation("runaway_detected", module_name="rate_tracker")

        bumped = _read_data(sandbox, "rate_tracker")
        assert bumped["operations_total"] == 3
        assert bumped["files"] == saved["files"]

    def test_a_corrupt_document_is_set_aside_by_one_scan_and_rebuilt_by_the_next(self, sandbox, monkeypatch, tmp_path):
        log_file = _real_tracker(monkeypatch, tmp_path)
        sandbox.mkdir(parents=True)
        (sandbox / "rate_tracker_data.json").write_text("{torn", encoding="utf-8")

        rate_tracker.scan_rates()

        assert [path.read_text(encoding="utf-8") for path in sandbox.glob("rate_tracker_data.json.corrupt-*")] == [
            "{torn"
        ]
        assert [e["msg"] for e in _trail_errors(tmp_path)] == ["json_service: update_json refused a corrupt document"]

        rate_tracker.scan_rates()

        assert list(_read_data(sandbox, "rate_tracker")["files"]) == [str(log_file)]


class TestTheShimBindsAndNeverWraps:
    """The shim's names are the service's own callables."""

    BOUND_NAMES = (
        "read_json",
        "write_json",
        "validate_json_structure",
        "get_json_path",
        "ensure_json_exists",
        "ensure_module_jsons",
        "load_json",
        "save_json",
        "log_operation",
    )

    @pytest.mark.parametrize("name", BOUND_NAMES)
    def test_every_public_name_is_a_bound_method_of_a_jsonhandle(self, name):
        """The type is half the claim; the identity pins WHICH callable: not a copy, not a forwarder."""
        bound = getattr(json_handler, name)

        assert isinstance(getattr(bound, "__self__", None), json_service.JsonHandle), (
            f"{name} is not a bound method — a wrapper adds a frame and breaks caller attribution"
        )
        assert bound.__func__ is getattr(json_service.JsonHandle, name)
        assert bound.__name__ == name

    def test_the_shim_is_bound_to_prax(self):
        assert json_handler.get_json_path.__self__.branch_root.name == "prax"


class TestTheEntryPoint:
    """from aipass.prax import json_handler — the one sanctioned import."""

    def test_the_lazy_package_attribute_is_the_service(self):
        assert aipass.prax.json_handler is json_service

    def test_the_exception_types_are_reachable_from_the_entry_point(self):
        assert issubclass(aipass.prax.json_handler.InvalidDocument, ValueError)
        assert issubclass(aipass.prax.json_handler.WriteFailed, OSError)
