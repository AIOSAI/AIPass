# =================== AIPass ====================
# Name: test_json_handler_contract_lineage.py
# Description: json_handler contract, template lineage clause: defaults, ensure, log_operation, save
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for every branch's apps/handlers/json/json_handler.py defaults, ensure, log_operation and save."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that handlers/aipass_standards/json_handler_check.py parses and imports

import copy
import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from aipass.seedgo.tests.support_json_handler_contract import (
    CONFIG_PAYLOAD,
    DECLARED_LOG_CAP_IGNORED,
    ENSURE_ALL_RETURNS_NOTHING,
    ENSURE_RETURNS_NOTHING,
    LOG_PAYLOAD,
    assert_warned_of_corrupt_bytes,
    expose,
    implementation,
    parametrized,
    prepared,
    require_document_addressing,
    require_one_service,
)

pytestmark = pytest.mark.usefixtures("quarantined_document_directories")


def document_directory(module: Any, name: str, json_type: str) -> Path:
    """Where one branch keeps a document, asked of the branch itself."""
    return Path(str(module.get_json_path(name, json_type))).parent


@pytest.mark.parametrize("branch", parametrized())
def test_the_default_document_a_missing_read_materialises_passes_the_validator(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A handler must not manufacture a default its own validator rejects."""
    module = implementation(branch)
    require_document_addressing(module, branch)
    validate = expose(module, branch, "validate_json_structure")
    module, _ = prepared(branch, tmp_path, monkeypatch)
    rejected = [
        json_type
        for json_type in ("config", "data", "log")
        if validate(module.load_json(f"absent_{json_type}", json_type), json_type) is not True
    ]
    assert not rejected, f"{branch}: the default it materialises fails its own validator for {rejected}"


@pytest.mark.parametrize("branch", parametrized())
def test_ensure_json_exists_creates_the_document(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The document exists afterwards."""
    module = implementation(branch)
    require_document_addressing(module, branch)
    ensure = expose(module, branch, "ensure_json_exists")
    module, _ = prepared(branch, tmp_path, monkeypatch)

    ensure("fresh", "config")

    assert Path(str(module.get_json_path("fresh", "config"))).exists(), f"{branch}: ensure created nothing"


@pytest.mark.parametrize("branch", parametrized(ENSURE_RETURNS_NOTHING))
def test_ensure_json_exists_reports_true(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The success signal seventeen branches publish and callers branch on."""
    module = implementation(branch)
    require_document_addressing(module, branch)
    ensure = expose(module, branch, "ensure_json_exists")
    module, _ = prepared(branch, tmp_path, monkeypatch)

    assert ensure("bool_mod", "data") is True, f"{branch}: ensure_json_exists did not answer True"


@pytest.mark.parametrize("branch", parametrized(ENSURE_ALL_RETURNS_NOTHING))
def test_ensure_module_jsons_reports_true(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The wrapper's success signal, pinned beside the one it wraps."""
    module = implementation(branch)
    require_document_addressing(module, branch)
    ensure_all = expose(module, branch, "ensure_module_jsons")
    module, _ = prepared(branch, tmp_path, monkeypatch)

    assert ensure_all("retmod") is True, f"{branch}: ensure_module_jsons did not answer True"


@pytest.mark.parametrize("branch", parametrized())
def test_ensure_json_exists_preserves_a_valid_existing_document(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Ensure is not a reset button."""
    module = implementation(branch)
    require_document_addressing(module, branch)
    ensure = expose(module, branch, "ensure_json_exists")
    module, _ = prepared(branch, tmp_path, monkeypatch)
    module.save_json("kept", "config", copy.deepcopy(CONFIG_PAYLOAD))
    before = Path(str(module.get_json_path("kept", "config"))).read_text(encoding="utf-8")

    ensure("kept", "config")

    after = Path(str(module.get_json_path("kept", "config"))).read_text(encoding="utf-8")
    assert after == before, f"{branch}: ensure_json_exists rewrote a document that was already valid"


@pytest.mark.parametrize("branch", parametrized())
def test_ensure_json_exists_regenerates_an_unreadable_document(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Unparseable bytes are replaced with something loadable."""
    module = implementation(branch)
    require_document_addressing(module, branch)
    ensure = expose(module, branch, "ensure_json_exists")
    module, _ = prepared(branch, tmp_path, monkeypatch)
    document = Path(str(module.get_json_path("corrupt", "config")))
    document.write_text("{not json at all", encoding="utf-8")

    ensure("corrupt", "config")

    assert json.loads(document.read_text(encoding="utf-8")), f"{branch}: corrupt document was not regenerated"
    assert_warned_of_corrupt_bytes(module, branch)


@pytest.mark.parametrize("branch", parametrized())
def test_ensure_json_exists_regenerates_a_structurally_invalid_document(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Parseable but wrong is still wrong."""
    module = implementation(branch)
    require_document_addressing(module, branch)
    ensure = expose(module, branch, "ensure_json_exists")
    validate = expose(module, branch, "validate_json_structure")
    module, _ = prepared(branch, tmp_path, monkeypatch)
    document = Path(str(module.get_json_path("wrong", "config")))
    document.write_text(json.dumps({"wrong": "structure"}), encoding="utf-8")

    ensure("wrong", "config")

    healed = json.loads(document.read_text(encoding="utf-8"))
    assert validate(healed, "config") is True, f"{branch}: invalid structure survived ensure_json_exists"


@pytest.mark.parametrize("branch", parametrized())
def test_ensure_module_jsons_creates_all_three_documents(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The three-document convenience wrapper does all three."""
    module = implementation(branch)
    require_document_addressing(module, branch)
    ensure_all = expose(module, branch, "ensure_module_jsons")
    module, _ = prepared(branch, tmp_path, monkeypatch)

    ensure_all("triple")

    missing = [
        json_type
        for json_type in ("config", "data", "log")
        if not Path(str(module.get_json_path("triple", json_type))).exists()
    ]
    assert not missing, f"{branch}: ensure_module_jsons did not create {missing}"


@pytest.mark.parametrize("branch", parametrized())
def test_log_operation_appends_a_timestamped_entry_and_reports_true(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """One call, one entry, carrying the operation and a timestamp."""
    module = implementation(branch)
    require_document_addressing(module, branch)
    log_operation = expose(module, branch, "log_operation")
    module, _ = prepared(branch, tmp_path, monkeypatch)

    answer = log_operation("deploy", module_name="logmod")

    entries = json.loads(Path(str(module.get_json_path("logmod", "log"))).read_text(encoding="utf-8"))
    assert entries, f"{branch}: log_operation appended nothing"
    assert entries[-1]["operation"] == "deploy", f"{branch}: the operation name was not recorded"
    assert "timestamp" in entries[-1], f"{branch}: the entry carries no timestamp"
    assert answer is True, f"{branch}: log_operation answered {answer!r}, not True"


@pytest.mark.parametrize("branch", parametrized())
def test_log_operation_attaches_the_data_it_was_given(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A payload survives to the entry, and an empty one invents nothing."""
    module = implementation(branch)
    require_document_addressing(module, branch)
    log_operation = expose(module, branch, "log_operation")
    module, _ = prepared(branch, tmp_path, monkeypatch)
    document = Path(str(module.get_json_path("datamod", "log")))

    log_operation("with_data", data={"count": 5}, module_name="datamod")
    carried = json.loads(document.read_text(encoding="utf-8"))[-1]
    assert carried.get("data", {}).get("count") == 5, f"{branch}: the data payload was lost"

    log_operation("no_data", data={}, module_name="datamod")
    empty = json.loads(document.read_text(encoding="utf-8"))[-1]
    assert not empty.get("data"), f"{branch}: an empty payload became {empty.get('data')!r}"


@pytest.mark.parametrize("branch", parametrized())
def test_log_operation_calls_accumulate_in_call_order(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Three calls leave three entries, oldest first."""
    module = implementation(branch)
    require_document_addressing(module, branch)
    log_operation = expose(module, branch, "log_operation")
    module, _ = prepared(branch, tmp_path, monkeypatch)

    for operation in ("first", "second", "third"):
        log_operation(operation, module_name="accmod")

    entries = json.loads(Path(str(module.get_json_path("accmod", "log"))).read_text(encoding="utf-8"))
    assert [entry["operation"] for entry in entries[-3:]] == ["first", "second", "third"], (
        f"{branch}: log entries did not accumulate in call order"
    )


#: Cap this suite declares for the rotation contract; small, so the test writes ten entries.
DECLARED_LOG_CAP = 5

#: Spellings for the private template factory; it is private, so the branches disagree on the name.
DEFAULT_FACTORY_NAMES = ("_get_default_for_type", "_default_for_type", "_get_default", "_default_content")


def declare_log_cap(module: Any, name: str, cap: int) -> bool:
    """Write a config document declaring a rotation cap, the way the handler reads it.

    The cap lives in the config document (``config["config"]["max_log_entries"]``), not a module attribute.
    """
    settings = module.load_json(name, "config")
    if not isinstance(settings, dict) or not isinstance(settings.get("config"), dict):
        return False
    settings["config"]["max_log_entries"] = cap
    module.save_json(name, "config", settings)
    written = module.load_json(name, "config")
    return written.get("config", {}).get("max_log_entries") == cap


@pytest.mark.parametrize("branch", parametrized(DECLARED_LOG_CAP_IGNORED))
def test_log_operation_rotates_to_the_modules_declared_cap(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """An unbounded log is a disk-filler; the cap must actually bind.

    A branch that cannot accept the declared cap fails here, named, rather than skipping.
    """
    module = implementation(branch)
    require_document_addressing(module, branch)
    log_operation = expose(module, branch, "log_operation")
    module, _ = prepared(branch, tmp_path, monkeypatch)
    assert declare_log_cap(module, "fifomod", DECLARED_LOG_CAP), (
        f"{branch}'s config document has no config mapping to declare max_log_entries in, so this "
        f"contract cannot hold it to a cap - give the document a 'config' object"
    )

    for index in range(DECLARED_LOG_CAP + 5):
        log_operation(f"op_{index}", module_name="fifomod")

    entries = json.loads(Path(str(module.get_json_path("fifomod", "log"))).read_text(encoding="utf-8"))
    assert len(entries) <= DECLARED_LOG_CAP, (
        f"{branch}: {len(entries)} entries survived a declared cap of {DECLARED_LOG_CAP}"
    )
    assert entries[-1]["operation"] == f"op_{DECLARED_LOG_CAP + 4}", (
        f"{branch}: the newest entry is not last after rotation"
    )


@pytest.mark.parametrize("branch", parametrized(DECLARED_LOG_CAP_IGNORED))
def test_log_rotation_keeps_the_newest_entries_and_not_some_other_window(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Rotation must drop the OLDEST entries, named one by one."""
    module = implementation(branch)
    require_document_addressing(module, branch)
    log_operation = expose(module, branch, "log_operation")
    module, _ = prepared(branch, tmp_path, monkeypatch)
    assert declare_log_cap(module, "windowmod", DECLARED_LOG_CAP), (
        f"{branch}'s config document has no config mapping to declare max_log_entries in, so this "
        f"contract cannot hold it to a cap - give the document a 'config' object"
    )

    # The log has to arrive ALREADY over the cap: appended one at a time, `log[cap:]` and `log[-cap:]`
    # agree on every call, so the survivor shows only on a log past its cap when rotation runs.
    seeded = [{"timestamp": "2020-01-01T00:00:00", "operation": f"op_{index}"} for index in range(105)]
    module.save_json("windowmod", "log", seeded)

    log_operation("newest", module_name="windowmod")

    entries = json.loads(Path(str(module.get_json_path("windowmod", "log"))).read_text(encoding="utf-8"))
    survived = [entry["operation"] for entry in entries]
    expected = [f"op_{index}" for index in range(105 - DECLARED_LOG_CAP + 1, 105)] + ["newest"]
    assert survived == expected, (
        f"{branch}: rotation kept {len(survived)} entries beginning {survived[:1]} — "
        f"a cap of {DECLARED_LOG_CAP} over 106 entries keeps {expected}"
    )


@pytest.mark.parametrize("branch", parametrized())
def test_save_json_reports_true_on_a_write_that_landed(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The success signal every caller branches on."""
    module = implementation(branch)
    require_document_addressing(module, branch)
    module, _ = prepared(branch, tmp_path, monkeypatch)

    assert module.save_json("sv", "config", copy.deepcopy(CONFIG_PAYLOAD)) is True, (
        f"{branch}: save_json did not answer True for a write that succeeded"
    )


@pytest.mark.parametrize("branch", parametrized())
def test_save_json_writes_a_document_that_parses_from_disk(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Read back as BYTES, not through the handler's own loader."""
    module = implementation(branch)
    require_document_addressing(module, branch)
    module, _ = prepared(branch, tmp_path, monkeypatch)
    module.save_json("disk", "log", copy.deepcopy(LOG_PAYLOAD))

    raw = Path(str(module.get_json_path("disk", "log"))).read_bytes()
    parsed = json.loads(raw.decode("utf-8"))
    assert parsed == LOG_PAYLOAD, f"{branch}: the document on disk is not what was saved"


# The skip is a decorator, not an in-body `if`: windows_compat's static scan recognises only that
# as guarding os.chmod / stat.S_IMODE below.
@pytest.mark.parametrize("branch", parametrized())
@pytest.mark.skipif(
    os.name == "nt", reason="permission bits are not the file's own on Windows; the claim has no subject there"
)
def test_rewriting_a_document_keeps_the_permission_bits_it_already_had(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A save must not silently re-permission the document it replaces.

    An atomic write is a create plus a rename, so the mode is lost unless the writer carries it over.
    """
    module = implementation(branch)
    require_document_addressing(module, branch)
    require_one_service(branch)
    module, _ = prepared(branch, tmp_path, monkeypatch)

    module.save_json("permmod", "config", copy.deepcopy(CONFIG_PAYLOAD))
    path = Path(str(module.get_json_path("permmod", "config")))
    # 0o640, not 0o664: a new document lands 0o664 under the ordinary 002 umask, so a 664 probe passes
    # whether or not the writer carries the mode over. The probe is a mode no new document is born with.
    os.chmod(path, 0o640)
    before = stat.S_IMODE(os.stat(path).st_mode)

    module.save_json("permmod", "config", copy.deepcopy(CONFIG_PAYLOAD))

    after = stat.S_IMODE(os.stat(path).st_mode)
    assert after == before, f"{branch}: a rewrite changed the document's mode from {before:o} to {after:o}"


@pytest.mark.parametrize("branch", parametrized())
def test_a_nan_or_infinity_payload_is_refused_and_the_document_left_alone(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """NaN and Infinity are not JSON, so they are refused at the writer.

    A refusal must leave the previous document on disk, byte-for-byte.
    """
    module = implementation(branch)
    require_document_addressing(module, branch)
    require_one_service(branch)
    module, _ = prepared(branch, tmp_path, monkeypatch)

    module.save_json("nanmod", "config", copy.deepcopy(CONFIG_PAYLOAD))
    path = Path(str(module.get_json_path("nanmod", "config")))
    before = path.read_bytes()

    for spelling in ("nan", "inf", "-inf"):
        payload = copy.deepcopy(CONFIG_PAYLOAD)
        payload["config"]["threshold"] = float(spelling)
        with pytest.raises(ValueError):
            module.save_json("nanmod", "config", payload)
        assert path.read_bytes() == before, f"{branch}: a refused {spelling} payload still changed the document on disk"
