# =================== AIPass ====================
# Name: test_json_handler_contract_lineage.py
# Description: json_handler contract, template lineage clause: defaults, ensure, log_operation, save
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
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


# ---------------------------------------------------------------------------
# Contracts: the template lineage — defaults, ensure, log_operation, save
# ---------------------------------------------------------------------------
#
# These absorb the largest stamped family in the fleet: 41 identities copied
# across api, devpulse, drone, seedgo and spawn. Every one was read before it
# was folded, because the fingerprint that grouped them drops names and
# literals — and doing so turned up one group whose members assert OPPOSITE
# things through the same statement shape, recorded below rather than averaged
# away.


def document_directory(module: Any, name: str, json_type: str) -> Path:
    """Where one branch keeps a document, asked of the branch itself.

    Args:
        module: A redirected handler.
        name: Document module name.
        json_type: ``config``, ``data`` or ``log``.

    Returns:
        The directory the document lives in.
    """
    return Path(str(module.get_json_path(name, json_type))).parent


@pytest.mark.parametrize("branch", parametrized())
def test_the_default_document_a_missing_read_materialises_passes_the_validator(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A handler must not manufacture a default its own validator rejects.

    The copies this replaces asserted the default's KEYS one branch at a time
    ("config default must have module_name"), which is the same claim written
    against a constant. Asked of the branch's own validator instead, so a
    branch that legitimately carries different keys is still held to the rule
    that matters: the document it invents on a missing read has to be one it
    would accept back.
    """
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
    """The document exists afterwards.

    Only the effect, deliberately. What ``ensure_json_exists`` ANSWERS is a
    real fleet divergence with a reasoned case on both sides, so it is pinned
    separately rather than folded in here where it would look like part of
    the same claim.
    """
    module = implementation(branch)
    require_document_addressing(module, branch)
    ensure = expose(module, branch, "ensure_json_exists")
    module, _ = prepared(branch, tmp_path, monkeypatch)

    ensure("fresh", "config")

    assert Path(str(module.get_json_path("fresh", "config"))).exists(), f"{branch}: ensure created nothing"


@pytest.mark.parametrize("branch", parametrized(ENSURE_RETURNS_NOTHING))
def test_ensure_json_exists_reports_true(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The success signal seventeen branches publish and callers branch on.

    Worth pinning even though the value is a constant on every branch that
    has it: callers DO write ``if ensure_json_exists(...)``, and a branch that
    silently changed to None would send all of them down the failure path
    while every file kept being created exactly as before.
    """
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
    """Ensure is not a reset button.

    The failure this forbids is the expensive one: a handler that regenerates
    unconditionally silently discards a caller's live config every time
    anything asks whether the file is there.
    """
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
    """Unparseable bytes are replaced with something loadable.

    A handler that leaves the corruption in place hands the next reader the
    same crash forever; one that raises here makes the caller handle a
    condition ensure exists to resolve.
    """
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
    """Parseable but wrong is still wrong.

    Distinct from the corrupt case on purpose: the bytes here are valid JSON,
    so a handler that only guards ``json.loads`` sails past this and leaves a
    document its own validator would reject sitting on disk.
    """
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
    """A payload survives to the entry, and an empty one invents nothing.

    The second half is the copies' own weaker claim made exact: they allowed
    an absent key OR an empty one, which is two behaviours. Both are fine —
    what is not fine is a handler that fabricates content for a caller who
    passed nothing, so that is what is pinned.
    """
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
    """Three calls leave three entries, oldest first.

    Order is asserted, not just the count: a log that accumulates but reverses
    is useless to every reader that takes ``[-1]`` as "most recent", which is
    how the fleet reads it.
    """
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


#: Cap this suite declares for the rotation contract. Small so the test writes
#: ten entries rather than a hundred and five.
DECLARED_LOG_CAP = 5

#: Spellings the fleet uses for the private "template for this json_type"
#: factory. A list because it IS private, so nothing obliges the branches to
#: agree on the name, and they do not.
DEFAULT_FACTORY_NAMES = ("_get_default_for_type", "_default_for_type", "_get_default", "_default_content")


def declare_log_cap(module: Any, name: str, cap: int) -> bool:
    """Write a config document declaring a rotation cap, the way the handler reads it.

    Measured correction to how the stamped copies did this. They searched four
    MODULE attribute spellings for the cap, and no branch in the fleet defines
    any of them — it is read out of the module's own CONFIG DOCUMENT
    (``config["config"]["max_log_entries"]``), with a literal fallback in the
    code. So the copies' search could only ever answer "no cap": two of the
    four skipped on every run, and the two that passed used a number they had
    invented rather than the one the handler applies.

    Declaring it instead of hunting for it also means the contract exercises
    rotation on every branch that reads the setting, rather than only the ones
    that happen to ship a document with the key already in it.

    Args:
        module: A redirected handler.
        name: Document module name to configure.
        cap: Entries to keep.

    Returns:
        True when the handler accepted the declaration.
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

    The cap is DECLARED by this contract in the document the handler reads,
    rather than hunted for on the module — see :func:`declare_log_cap` for why
    the hunt could not work.

    A BRANCH THAT CANNOT ACCEPT THE DECLARATION FAILS HERE, AND USED TO SKIP
    (SELF-SKIP, 2026-09-07). Measured across the whole 22-branch roster before
    the change: 44 of 44 parametrisations declared the cap and none skipped, so
    the skip arm protected nobody and could only ever hide a regression. A
    branch whose config document has no `config` mapping cannot be held to a cap
    at all, which is the disk-filler this contract exists to prevent — that is a
    red with the branch named, not a quiet pass.
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
    """Rotation must drop the OLDEST entries, named one by one.

    ADDED 2026-09-07 from @devpulse's advisory mutation run (FPLAN-0492 ruling
    5): a survivor turned the service's ``log[-cap:]`` into ``log[cap:]``,
    which keeps 5 of 105 entries — the five OLDEST — and both existing
    rotation assertions still passed. The count test only bounds how many
    survive, and "newest is last" is true of any contiguous window taken in
    order. So the two of them together could not tell a FIFO from a filter
    that threw away everything recent, which is the one thing rotation exists
    to get right: the entries a reader goes to the log for are the last ones
    written.

    Pinned by CONTENT: every surviving operation name is asserted, in order,
    over a log that is already past its cap when rotation runs.
    """
    module = implementation(branch)
    require_document_addressing(module, branch)
    log_operation = expose(module, branch, "log_operation")
    module, _ = prepared(branch, tmp_path, monkeypatch)
    assert declare_log_cap(module, "windowmod", DECLARED_LOG_CAP), (
        f"{branch}'s config document has no config mapping to declare max_log_entries in, so this "
        f"contract cannot hold it to a cap - give the document a 'config' object"
    )

    # THE LOG HAS TO ARRIVE ALREADY LONG, and this is the half that took a
    # measurement to see. Appending one entry at a time never distinguishes the
    # two slices: the first append over the cap truncates to a single entry and
    # the log never grows past the cap again, so `log[cap:]` and `log[-cap:]`
    # agree on every subsequent call. The survivor only shows itself on a log
    # that is already over the cap when rotation runs — a document written
    # before the cap was lowered, or by a handler that was not rotating.
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
    """The success signal every caller branches on.

    Pinned separately from the round trip because a handler can persist
    correctly and still answer None, and the callers that check are then
    wrong in the safe-looking direction.
    """
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
    """Read back as BYTES, not through the handler's own loader.

    The round-trip contract goes out and back through the same module, so a
    loader that tolerates its own writer's quirk would hide them both. This
    reads the file the way every other process on the machine will.
    """
    module = implementation(branch)
    require_document_addressing(module, branch)
    module, _ = prepared(branch, tmp_path, monkeypatch)
    module.save_json("disk", "log", copy.deepcopy(LOG_PAYLOAD))

    raw = Path(str(module.get_json_path("disk", "log"))).read_bytes()
    parsed = json.loads(raw.decode("utf-8"))
    assert parsed == LOG_PAYLOAD, f"{branch}: the document on disk is not what was saved"


# windows_compat item 23: the skip below moved from a runtime `if` to a
# decorator so the checker's static test-scan recognises the guard covering
# os.chmod / stat.S_IMODE further down — an in-body `if os.name == "nt":
# pytest.skip(...)` guards nothing lexically, only at runtime.
@pytest.mark.parametrize("branch", parametrized())
@pytest.mark.skipif(
    os.name == "nt", reason="permission bits are not the file's own on Windows; the claim has no subject there"
)
def test_rewriting_a_document_keeps_the_permission_bits_it_already_had(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A save must not silently re-permission the document it replaces.

    ADDED 2026-09-07 from @devpulse's advisory mutation run (FPLAN-0492 ruling
    5): three survivors restored the DPLAN-0325 pair-2 regression in which a
    664 config came back 600 across the whole fleet. An atomic write is a
    CREATE plus a rename, so the new file is born with the stager's mode and
    the document's own bits are lost unless the writer carries them over —
    and nothing in this contract read a mode back, so all three mutants lived.

    The failure is quiet in exactly the way that costs a day: the document is
    correct, the write reports success, and the next process that is not this
    user cannot read it.
    """
    module = implementation(branch)
    require_document_addressing(module, branch)
    require_one_service(branch)
    module, _ = prepared(branch, tmp_path, monkeypatch)

    module.save_json("permmod", "config", copy.deepcopy(CONFIG_PAYLOAD))
    path = Path(str(module.get_json_path("permmod", "config")))
    # 0o640, NOT the 0o664 the mutation report names. A new document is staged
    # 0o666 and lands 0o664 under the ordinary 002 umask, so a 664 probe passes
    # whether or not the writer carries the mode over — measured 2026-09-07, the
    # first draft of this test could not kill the mutant it was written for. The
    # probe mode has to be one no new document would be born with.
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

    ADDED 2026-09-07 from @devpulse's advisory mutation run (FPLAN-0492 ruling
    5): three survivors flipped ``allow_nan=False`` off and nothing went red.
    The service's docstring spends a paragraph on why the refusal exists —
    Python writes the bare tokens ``NaN`` and ``Infinity``, the document lands
    looking fine, and every strict parser in the fleet and every other
    language rejects it later, far from the branch that wrote it — and no test
    held it to that.

    Both halves are asserted, because a refusal that has already clobbered the
    file is not a refusal: the previous document must still be on disk,
    byte-for-byte.
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
