# =================== AIPass ====================
# Name: test_json_handler.py
# Description: Tests for the fleet json service through prax's own shim
# Version: 2.1.0
# Created: 2026-03-28
# Modified: 2026-09-11
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
import logging
import os
import stat
from datetime import date

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

    @pytest.mark.skipif(os.name == "nt", reason="creating a directory symlink needs privileges on Windows")
    def test_a_symlinked_path_is_not_followed(self, tmp_path):
        """resolve() would walk the link to its target and name the WRONG branch.
        The absence of resolve() is a behaviour, not just an omission.

        The skip asks the MACHINE (``os.name``) and nothing else. It used to make
        the link inside a ``try`` and call ``pytest.skip`` from the ``except``,
        which reads as an unconditional skip: any OSError at all — a full disk, a
        typo in the path — turned a failure into a silent pass on every platform.
        """
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

        One value, not a choice of two. ``if test_dir:`` treats "" as absence, so
        the answer is the real tree. A mutation to ``is not None`` builds
        ``Path("") / "prax" / "prax_json"`` — the RELATIVE ``prax/prax_json`` — and
        ``Path("/")`` would build the filesystem root; this equality refuses both.
        """
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", "")
        resolved = json_service.for_module(json_handler.__file__)

        assert resolved.json_dir == resolved.branch_root / "prax_json"
        assert resolved.json_dir.is_absolute()

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

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "-inf"])
    def test_a_non_finite_number_raises_valueerror(self, handle, tmp_path, bad):
        """NaN and Infinity are not JSON, and Python writes them anyway.

        json.dumps defaults to allow_nan=True and emits the bare tokens NaN,
        Infinity and -Infinity. The document lands, prax reads it back happily
        (json.load accepts its own dialect), and the failure surfaces in some
        other language's strict parser days later, nowhere near the branch that
        wrote it. The service refuses instead — the same answer it gives an
        unknown json_type — so the payload bug is found in the sweep that made
        it. The class is ValueError, json's own for out-of-range floats.
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


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits — Windows has no mode to preserve")
class TestTheWriteNeverChoosesTheDocumentsMode:
    """A write must not change permissions the caller never asked it to change.

    MEASURED (skills, DPLAN-0325 pair 2): the staged write went through
    tempfile.NamedTemporaryFile, which creates at a hardcoded 0600, and
    os.replace carries the STAGED file's mode onto the target. Every service
    write therefore narrowed the document it rewrote — a 664 config came back
    600 on its next write, fleet-wide, and the group that could read it
    yesterday could not today. Nothing failed loudly; the document was simply
    less readable than the branch that owns it intended.

    The two directions are pinned separately because they are two different
    mechanisms: an existing document is carried over with fchmod, a new one is
    left to the kernel and the process umask.
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
        """The reference is measured in the same directory, never hardcoded.

        The right mode for a NEW document is not 0664 and not 0600 — it is
        whatever this process's umask would have produced, which is what a
        plain open(path, "w") gives. So the expectation is taken from exactly
        that, in the same breath, rather than written down as a number that is
        wrong under any other umask.
        """
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
        """A default the handler would itself reject is a self-healing loop.

        The floor is the declared type list itself: an empty (or shortened)
        JSON_TYPES would make the loop below assert nothing and still pass.
        """
        assert json_service.JSON_TYPES == ("config", "data", "log")

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

    def test_a_non_finite_number_in_telemetry_answers_false(self, handle):
        """The NaN refusal must not become a raise on the monitor's threads.

        write_json raises ValueError on a non-finite number — correct for a
        caller writing a document, fatal for telemetry: log_operation is called
        per event from the watchdog and display threads, where a raising writer
        is silent half-death. The existing (OSError, TypeError, ValueError)
        catch already covers it; this pins that it stays covered.
        """
        assert handle.log_operation("rate", {"lines_per_min": float("inf")}, module_name="ops") is False

    def test_names_the_calling_module_when_not_told(self, handle, sandbox):
        """Frame 2, and it is why the shim BINDS: a wrapper would add a frame and
        rename every operation in the log to the wrapper's own file."""
        handle.log_operation("auto")

        entries = json.loads((sandbox / "test_json_handler_log.json").read_text(encoding="utf-8"))
        assert entries[-1]["operation"] == "auto"


# =============================================
# THE DATA LEG — lifetime state (FPLAN-0542)
# =============================================


def _seed_data(sandbox, module_name, document):
    """Put a data document on disk exactly as given, bypassing the service."""
    sandbox.mkdir(parents=True, exist_ok=True)
    (sandbox / f"{module_name}_data.json").write_text(json.dumps(document), encoding="utf-8")


def _read_data(sandbox, module_name):
    """The data document as bytes on disk say it is, not as the service reads it."""
    return json.loads((sandbox / f"{module_name}_data.json").read_text(encoding="utf-8"))


class TestTheDataLegIsHealedNotReplaced:
    """ensure_json_exists adds a data document's missing base keys and keeps the rest.

    Replace-on-invalid was harmless while nothing wrote the data leg. Once every
    log write bumps it, and rate_tracker keeps its ``files`` in it, a replace
    would wipe live state on the way to counting — log_operation runs ensure
    before every bump.
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

    def test_the_config_leg_is_still_regenerated_not_merged(self, handle, sandbox):
        """The heal is the data leg's alone: an invalid config comes back as the
        default, with nothing of the invalid one carried over."""
        sandbox.mkdir(parents=True, exist_ok=True)
        (sandbox / "stray_config.json").write_text(
            json.dumps({"module_name": "stray", "stray": True}), encoding="utf-8"
        )

        assert handle.ensure_json_exists("stray", "config") is True

        written = json.loads((sandbox / "stray_config.json").read_text(encoding="utf-8"))
        assert written == json_service._default_document("config", "stray")

    def test_a_data_document_that_cannot_be_written_back_is_left_as_it_was(self, handle, sandbox):
        """json.load reads NaN; the writer refuses it. Healing such a document
        would mean dropping keys, so it is neither raised on nor replaced — and
        the log leg beside it still works."""
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
        """Read-modify-write, never a fresh dict. The old-era success/failure
        counters stay exactly as they were: the call carries no success signal."""
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
        """The live case: prax_json/prax_logger_data.json is literally ``{}``.
        save_json's structure check refuses that, so without the heal every log
        call for such a module would fail its bump."""
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
        """A bool is an int to Python — True + 1 would count to 2 from nothing.

        The type is asserted too: ``True == 1``, so an untouched ``true`` on
        disk would pass an equality alone.
        """
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
    def test_a_failed_bump_never_breaks_the_log(self, handle, sandbox, monkeypatch, caplog, failure):
        """Telemetry on the monitor's threads: the log entry already landed, so
        the answer stays the log's own True and the failure is a warning."""
        real_save = handle.save_json

        def refuse_the_data(module_name, json_type, data):
            if json_type == "data":
                raise failure
            return real_save(module_name, json_type, data)

        monkeypatch.setattr(handle, "save_json", refuse_the_data)

        with caplog.at_level(logging.WARNING, logger=json_service.logger.name):
            answer = handle.log_operation("survives", module_name="fragile")

        assert answer is True
        entries = json.loads((sandbox / "fragile_log.json").read_text(encoding="utf-8"))
        assert [entry["operation"] for entry in entries] == ["survives"]
        assert "operations_total" not in _read_data(sandbox, "fragile")
        warned = [
            record.getMessage()
            for record in caplog.records
            if record.name == json_service.logger.name and record.levelno == logging.WARNING
        ]
        assert any("fragile" in message and str(failure) in message for message in warned), warned


class TestRateTrackerKeepsKeysItDoesNotOwn:
    """rate_tracker_data.json is both the tracker's state and its data leg."""

    def test_the_counters_and_the_trackers_files_survive_each_others_writes(self, sandbox, monkeypatch):
        """The real tracker against the real shim, both writing one document.

        The old _save_state rebuilt the dict every scan: ``created`` re-stamped
        to today and the service's counters wiped. Now each writer sets only its
        own keys — and the bump that follows a save keeps the tracker's files.
        """
        import importlib

        tracker = importlib.import_module("aipass.prax.apps.handlers.monitoring.rate_tracker")
        monkeypatch.setattr(tracker, "json_handler", json_handler)
        monkeypatch.setattr(tracker, "_tracked", {})
        _seed_data(sandbox, "rate_tracker", {"created": "2020-01-01", "last_updated": "2020-01-01"})

        json_handler.log_operation("runaway_detected", module_name="rate_tracker")
        json_handler.log_operation("runaway_detected", module_name="rate_tracker")
        tracker._tracked["/logs/a.log"] = tracker.FileRateState(4096, 1000.0)
        tracker._save_state()

        saved = _read_data(sandbox, "rate_tracker")
        assert saved["operations_total"] == 2
        assert saved["last_operation"] == "runaway_detected"
        assert saved["created"] == "2020-01-01"
        assert saved["module_name"] == "rate_tracker"
        assert saved["files"] == {"/logs/a.log": tracker.FileRateState(4096, 1000.0).to_dict()}

        json_handler.log_operation("runaway_detected", module_name="rate_tracker")

        bumped = _read_data(sandbox, "rate_tracker")
        assert bumped["operations_total"] == 3
        assert bumped["files"] == saved["files"]


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
        """The type is half the claim; the other half is WHICH function it binds.

        ``isinstance(..., JsonHandle)`` alone passes for any wrapper that happens
        to hold a handle. The identity below is the value: the shim's name IS the
        service's own callable, not a copy of it and not a forwarder around it.
        """
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
        import aipass.prax

        assert aipass.prax.json_handler is json_service

    def test_the_exception_types_are_reachable_from_the_entry_point(self):
        import aipass.prax

        assert issubclass(aipass.prax.json_handler.InvalidDocument, ValueError)
        assert issubclass(aipass.prax.json_handler.WriteFailed, OSError)
