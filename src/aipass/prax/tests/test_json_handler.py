# =================== AIPass ====================
# Name: test_json_handler.py
# Description: Tests for the fleet json service through prax's own shim
# Version: 2.0.0
# Created: 2026-03-28
# Modified: 2026-09-03
# =============================================

"""Tests for the fleet's one json service (DPLAN-0325), exercised through prax's
own shim.

What this file used to be is in tests/.archive/: eighteen tests that re-simulated
the handler's logic inline (``json.loads`` on a template they had just written,
``all(k in data for k in required)``) and never called the module under test. The
v4 template stamp; every one of them passed against a handler that had been
deleted. They are subsumed by seedgo's cross-branch contract and are not
rewritten here.

These call the service. Redirection is the AIPASS_TEST_LOG_DIR seam, never a
patched module attribute — the service resolves its directory per call, and the
shim has no attributes to patch.
"""

import json
import os

import pytest

from aipass.prax.apps.handlers.json import json_handler
from aipass.prax.apps.handlers.json import json_service


# =============================================
# FIXTURES
# =============================================


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    """Point the service at a temp tree and hand back the json directory.

    Set AFTER import on purpose: the seam only works because json_dir is a
    property computed on every access, so a redirect that arrives late must
    still take effect.
    """
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


# =============================================
# THE HANDLE — branch resolution and the seam
# =============================================


class TestForModule:
    """for_module derives the branch root from the shim's own __file__."""

    def test_derives_the_branch_root_from_the_shim(self):
        """apps/handlers/json/json_handler.py -> the branch directory."""
        resolved = json_service.for_module(json_handler.__file__)

        assert resolved.branch_root.name == "prax"

    def test_takes_the_path_apart_without_resolving_it(self, tmp_path):
        """parents[3], not resolve(). A branch root is derived from the path the
        caller passed, so the service still works with a deleted cwd — and a
        path that does not exist is still taken apart correctly."""
        made_up = tmp_path / "notabranch" / "apps" / "handlers" / "json" / "json_handler.py"

        resolved = json_service.for_module(made_up)

        assert resolved.branch_root == tmp_path / "notabranch"

    def test_a_symlinked_path_is_not_followed(self, tmp_path):
        """resolve() would walk the link to its target and name the WRONG branch.
        The absence of resolve() is a behaviour, not just an omission."""
        real = tmp_path / "real_branch" / "apps" / "handlers" / "json"
        real.mkdir(parents=True)
        (real / "json_handler.py").write_text("", encoding="utf-8")
        link = tmp_path / "linked_branch"
        try:
            link.symlink_to(tmp_path / "real_branch", target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable on this platform")

        resolved = json_service.for_module(link / "apps" / "handlers" / "json" / "json_handler.py")

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
        """AIPASS_TEST_LOG_DIR='' must not resolve to /prax/prax_json."""
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", "")
        resolved = json_service.for_module(json_handler.__file__)

        assert resolved.json_dir.parts[0] != os.sep or resolved.json_dir.parent.name == "prax"
        assert resolved.json_dir.name == "prax_json"

    def test_a_later_change_of_the_variable_wins(self, monkeypatch, tmp_path):
        """Nothing is captured. The load-bearing pin: a value read once at
        import made a redirect stick for the life of the process."""
        resolved = json_service.for_module(json_handler.__file__)
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "first"))
        first = resolved.json_dir

        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "second"))

        assert first == tmp_path / "first" / "prax" / "prax_json"
        assert resolved.json_dir == tmp_path / "second" / "prax" / "prax_json"

    def test_the_path_builder_resolves_at_call_time(self, monkeypatch, tmp_path):
        """The use site, not just the property: a mutation reading a captured
        directory inside get_json_path survives every test above."""
        resolved = json_service.for_module(json_handler.__file__)
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))

        built = resolved.get_json_path("probe", "config")

        assert built == tmp_path / "prax" / "prax_json" / "probe_config.json"


# =============================================
# PATH PRIMITIVES — read_json / write_json
# =============================================


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

    def test_a_non_serialisable_payload_raises_typeerror(self, handle, tmp_path):
        """A payload bug is not a write failure. Serialising FIRST is what makes
        the difference visible instead of collapsing to a False."""
        with pytest.raises(TypeError):
            handle.write_json(tmp_path / "doc.json", {"bad": object()})

    def test_a_circular_payload_raises_valueerror(self, handle, tmp_path):
        payload: dict = {}
        payload["self"] = payload

        with pytest.raises(ValueError):
            handle.write_json(tmp_path / "doc.json", payload)

    def test_a_failed_write_answers_false_and_never_raises(self, handle, tmp_path, monkeypatch):
        """OSError anywhere on the way answers False. This is the semantics the
        six production bool consumers depend on."""
        monkeypatch.setattr(json_service, "_replace_with_retry", _raise_oserror)

        assert handle.write_json(tmp_path / "doc.json", {"a": 1}) is False

    def test_a_failed_write_cleans_up_its_temp_file(self, handle, tmp_path, monkeypatch):
        """A staged file left behind is litter that accumulates silently."""
        monkeypatch.setattr(json_service, "_replace_with_retry", _raise_oserror)

        handle.write_json(tmp_path / "doc.json", {"a": 1})

        assert list(tmp_path.glob("*.tmp")) == []

    def test_a_failed_write_leaves_the_original_intact(self, handle, tmp_path, monkeypatch):
        """The staged-write guarantee: a write that cannot land destroys nothing."""
        target = tmp_path / "doc.json"
        target.write_text(json.dumps({"live": True}), encoding="utf-8")
        monkeypatch.setattr(json_service, "_replace_with_retry", _raise_oserror)

        handle.write_json(target, {"replacement": True})

        assert json.loads(target.read_text(encoding="utf-8")) == {"live": True}


def _raise_oserror(source, destination):
    """Stand-in for the bounded replace that always fails."""
    raise OSError("replace refused")


class TestTheBoundedReplaceRetry:
    """os.replace on Windows fails while any reader holds the target open."""

    def test_a_transient_sharing_violation_is_survived(self, monkeypatch, tmp_path):
        attempts = {"count": 0}
        real_replace = os.replace

        def flaky(source, destination):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise PermissionError("sharing violation")
            real_replace(source, destination)

        monkeypatch.setattr(json_service.os, "replace", flaky)
        source = tmp_path / "staged"
        source.write_text("payload", encoding="utf-8")

        json_service._replace_with_retry(str(source), str(tmp_path / "live"))

        assert attempts["count"] == 3
        assert (tmp_path / "live").read_text(encoding="utf-8") == "payload"

    def test_the_retry_is_bounded_and_then_raises(self, monkeypatch, tmp_path):
        """Bounded, then honest: a permanent permission problem is not retried
        forever, it surfaces."""
        attempts = {"count": 0}

        def always_blocked(source, destination):
            attempts["count"] += 1
            raise PermissionError("sharing violation")

        monkeypatch.setattr(json_service.os, "replace", always_blocked)
        monkeypatch.setattr(json_service, "_REPLACE_BACKOFF_SECONDS", 0)

        with pytest.raises(PermissionError):
            json_service._replace_with_retry("source", "destination")

        assert attempts["count"] == json_service._REPLACE_ATTEMPTS

    def test_a_non_sharing_oserror_is_not_retried(self, monkeypatch):
        """Only the Windows sharing violation is transient. Retrying a genuine
        failure 40 times buys nothing and hides it for 200ms."""
        attempts = {"count": 0}

        def wrong_kind(source, destination):
            attempts["count"] += 1
            raise FileNotFoundError("no such file")

        monkeypatch.setattr(json_service.os, "replace", wrong_kind)

        with pytest.raises(FileNotFoundError):
            json_service._replace_with_retry("source", "destination")

        assert attempts["count"] == 1


# =============================================
# TYPED DOCUMENTS
# =============================================


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
        """A default the handler would itself reject is a self-healing loop."""
        for json_type in json_service.JSON_TYPES:
            document = json_service._default_document(json_type, "any")

            assert handle.validate_json_structure(document, json_type) is True

    def test_a_valid_document_is_preserved(self, handle, sandbox):
        sandbox.mkdir(parents=True, exist_ok=True)
        original = {"module_name": "keep", "version": "9.9.9", "config": {"custom": True}}
        (sandbox / "keep_config.json").write_text(json.dumps(original), encoding="utf-8")

        handle.ensure_json_exists("keep", "config")

        assert json.loads((sandbox / "keep_config.json").read_text(encoding="utf-8")) == original

    def test_an_unreadable_document_is_regenerated(self, handle, sandbox):
        sandbox.mkdir(parents=True, exist_ok=True)
        (sandbox / "broken_config.json").write_text("{not json", encoding="utf-8")

        assert handle.ensure_json_exists("broken", "config") is True
        assert json.loads((sandbox / "broken_config.json").read_text(encoding="utf-8"))["module_name"] == "broken"

    def test_an_empty_document_is_regenerated(self, handle, sandbox):
        sandbox.mkdir(parents=True, exist_ok=True)
        (sandbox / "empty_config.json").write_text("", encoding="utf-8")

        assert handle.ensure_json_exists("empty", "config") is True
        assert json.loads((sandbox / "empty_config.json").read_text(encoding="utf-8"))["module_name"] == "empty"

    def test_a_structurally_invalid_document_is_regenerated(self, handle, sandbox):
        sandbox.mkdir(parents=True, exist_ok=True)
        (sandbox / "wrong_config.json").write_text(json.dumps(["a", "list"]), encoding="utf-8")

        assert handle.ensure_json_exists("wrong", "config") is True
        assert isinstance(json.loads((sandbox / "wrong_config.json").read_text(encoding="utf-8")), dict)

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
        """Written and read back by the service itself, not by a raw json.load —
        the two halves have to agree about the same file."""
        handle.save_json("roundtrip", "config", sample_data)

        assert handle.load_json("roundtrip", "config") == sample_data

    def test_a_data_document_gets_a_fresh_last_updated(self, handle):
        document = {"created": "2020-01-01", "last_updated": "2020-01-01"}

        handle.save_json("stamped", "data", document)

        assert document["last_updated"] != "2020-01-01"

    def test_an_invalid_document_raises_invaliddocument(self, handle):
        """The old handler answered False here, which is indistinguishable from
        a disk failure — two very different bugs wearing one return value."""
        with pytest.raises(json_service.InvalidDocument):
            handle.save_json("bad", "config", {"module_name": "only"})

    def test_a_write_that_cannot_land_raises_writefailed(self, handle, monkeypatch):
        """A lost document must not look like success, and must not look like a
        caller's validation mistake either."""
        monkeypatch.setattr(json_service, "_replace_with_retry", _raise_oserror)

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
        """The knob is published in every config document. It used to be
        advertised and ignored — the cap was a constant."""
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
        """log_operation is called from the monitor's display and watchdog
        threads. A raising writer there is silent half-death, not fail-honestly."""
        monkeypatch.setattr(json_service, "_replace_with_retry", _raise_oserror)

        assert handle.log_operation("doomed", module_name="ops") is False

    def test_a_non_serialisable_payload_answers_false(self, handle):
        """A payload bug in telemetry still must not take the caller down."""
        assert handle.log_operation("bad", {"obj": object()}, module_name="ops") is False

    def test_names_the_calling_module_when_not_told(self, handle, sandbox):
        """Frame 2, and it is why the shim BINDS: a wrapper would add a frame and
        rename every operation in the log to the wrapper's own file."""
        handle.log_operation("auto")

        entries = json.loads((sandbox / "test_json_handler_log.json").read_text(encoding="utf-8"))
        assert entries[-1]["operation"] == "auto"


# =============================================
# THE SHIM
# =============================================


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
        bound = getattr(json_handler, name)

        assert isinstance(getattr(bound, "__self__", None), json_service.JsonHandle), (
            f"{name} is not a bound method — a wrapper adds a frame and breaks caller attribution"
        )

    def test_the_exceptions_are_the_services_own(self):
        assert json_handler.InvalidDocument is json_service.InvalidDocument
        assert json_handler.WriteFailed is json_service.WriteFailed

    def test_the_shim_carries_nothing_else(self):
        """Byte-identical in every branch by design. Anything a branch adds here
        is drift, and the whole point of DPLAN-0325 is that there is none."""
        public = {name for name in vars(json_handler) if not name.startswith("_")}

        assert public == set(json_handler.__all__) | {"json_handler"}

    def test_the_shim_is_bound_to_prax(self):
        assert json_handler.get_json_path.__self__.branch_root.name == "prax"


class TestTheEntryPoint:
    """from aipass.prax import json_handler — the one sanctioned import."""

    def test_the_lazy_package_attribute_is_the_service(self):
        import aipass.prax

        assert aipass.prax.json_handler is json_service

    def test_the_exception_types_are_reachable_from_the_entry_point(self):
        import aipass.prax

        assert issubclass(aipass.prax.json_handler.InvalidDocument, ValueError)
        assert issubclass(aipass.prax.json_handler.WriteFailed, OSError)
