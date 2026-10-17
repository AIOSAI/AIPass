# =================== AIPass ====================
# Name: test_json_handler_contract_durability.py
# Description: json_handler contract, durability clause: bounded replace, public writer, concurrency
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for every branch's apps/handlers/json/json_handler.py writer and every shipped bounded replace helper."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — os.replace's own atomicity; the tests only choose what it raises

import contextlib
import copy
import errno
import importlib.util
import inspect
import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from aipass.seedgo.tests.support_json_handler_contract import (
    BRANCHES,
    DATA_PAYLOAD,
    PACKAGE_ROOT,
    TORN_DOCUMENT_OBSERVED,
    WRITER_HAS_NO_BOUNDED_RETRY,
    handler_path,
    implementation,
    parametrized,
    prepared,
    require_one_service,
    required_positionals,
)

pytestmark = pytest.mark.usefixtures("quarantined_document_directories")


#: The last step of every atomic write in the fleet: rename the staged file
#: over the live document, tolerating the sharing violation a concurrent
#: Windows reader causes, bounded so a permanently blocked target still fails.
RETRY_HELPER = "_replace_with_retry"

#: Both spellings the fleet uses for it: the private one is the majority; ``trigger`` exports it PUBLICLY
#: from its config module, and a scan keyed to the majority's naming cannot see that one.
RETRY_HELPER_NAMES = ("_replace_with_retry", "replace_with_retry")

#: Path parts that mean "not shipped code": a suite copy names the symbol while monkeypatching it, and
#: an archived file is on no import path.
UNSHIPPED_PARTS = frozenset({"tests", "test", ".archive", "__pycache__", ".sorting_unprocessed", "dropbox"})


def shipped_python_files(root: Path) -> list[Path]:
    """Every ``.py`` file under ``root`` that is shipped code, sorted."""
    found = []
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = [
            name for name in subdirectories if name not in UNSHIPPED_PARTS and not name.startswith(".")
        ]
        found.extend(Path(directory) / name for name in files if name.endswith(".py"))
    return sorted(found)


def ships_retry_helper(path: Path) -> bool:
    """Whether a package file defines the replace helper itself."""
    source = path.read_text(encoding="utf-8", errors="ignore")
    return any(f"def {name}(" in source for name in RETRY_HELPER_NAMES)


def retry_label(relative: Path) -> str:
    """A short, stable test id for one implementation.

    Off the canonical location the label is the full path: ``branch/stem`` would read the shared
    module as ``aipass/json_handler``, the aipass BRANCH's handler.
    """
    canonical = relative.parts[1:] == ("apps", "handlers", "json", "json_handler.py")
    return relative.parts[0] if canonical else relative.with_suffix("").as_posix()


#: Label to file for every implementation the package ships, loaded from its file by :func:`retry_implementation`:
#: the fences refuse that import from seedgo. An ``rglob``, not handler globs: a copy of the helper under
#: another name (``spawn/atomic_write``) matches no handler glob. No count is asserted; the floor is.
RETRY_IMPLEMENTATIONS = {
    retry_label(path.relative_to(PACKAGE_ROOT)): path
    for path in shipped_python_files(PACKAGE_ROOT)
    if ships_retry_helper(path)
}

#: One module object per label for the whole run: a test that captures the helper from one load and
#: patches another patches nothing.
RETRY_MODULES: dict[str, Any] = {}

#: One param per implementation, and deliberately no divergence table: a disagreement here is news.
RETRY_PARAMS = [pytest.param(label, id=label) for label in RETRY_IMPLEMENTATIONS]


def retry_implementation(label: str) -> Any:
    """Load one implementation from its file by its discovery label, once."""
    module = RETRY_MODULES.get(label)
    if module is None:
        key = "_aipass_contract_retry_" + label.replace("/", "_").replace(".", "_")
        spec = importlib.util.spec_from_file_location(key, RETRY_IMPLEMENTATIONS[label])
        assert spec is not None and spec.loader is not None, f"{label}: {RETRY_IMPLEMENTATIONS[label]} has no loader"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        RETRY_MODULES[label] = module
    return module


def retry_helper_of(module: Any) -> Callable | None:
    """The bounded replace helper a module ships, under either spelling."""
    for name in RETRY_HELPER_NAMES:
        candidate = getattr(module, name, None)
        if callable(candidate):
            return candidate
    return None


def retry_helper_name(module: Any) -> str:
    """The spelling one module actually uses, for failure messages."""
    for name in RETRY_HELPER_NAMES:
        if callable(getattr(module, name, None)):
            return name
    return RETRY_HELPER


def require_retry_helper(module: Any, label: str) -> Callable:
    """The module's bounded helper, or a failure naming the module."""
    helper = retry_helper_of(module)
    assert helper is not None, f"{label}: discovered as an implementation but ships no bounded replace helper"
    return helper


def isolated_replace(module: Any, monkeypatch: pytest.MonkeyPatch, replace: Callable) -> list:
    """Point ONE module's ``os.replace`` and ``time.sleep`` at test doubles.

    Patching ``sleep`` on the shared ``time`` reaches every thread in the process. The stub carries
    ``sleep`` only, so an implementation reaching for another ``time`` attribute raises where it does.
    """
    sleeps: list[float] = []
    monkeypatch.setattr(module, "os", SimpleNamespace(replace=replace))
    monkeypatch.setattr(module, "time", SimpleNamespace(sleep=sleeps.append))
    return sleeps


def sharing_violation(destination: Any) -> PermissionError:
    """The error Windows raises when a reader still holds the target open."""
    return PermissionError(13, "sharing violation", str(destination))


# Pure monkeypatch and ``tmp_path``, no platform branch or skip: the Windows leg runs the same cases,
# and the behaviour pinned here only ever misbehaves on Windows.


@pytest.mark.parametrize("label", RETRY_PARAMS)
def test_the_replace_helper_is_declared_bounded_and_patient(label: str):
    """The helper exists, retries more than once, and waits a nonzero time."""
    module = retry_implementation(label)
    assert retry_helper_of(module) is not None, (
        f"{label}: no bounded replace helper — a Windows sharing violation still kills the write"
    )
    assert module._REPLACE_ATTEMPTS > 1, f"{label}: a single attempt is not a retry"
    assert module._REPLACE_BACKOFF_SECONDS > 0, f"{label}: a zero backoff spins instead of waiting"


@pytest.mark.parametrize("label", RETRY_PARAMS)
def test_the_replace_helper_moves_the_staged_file_over_the_target(label: str, tmp_path: Path):
    """The happy path is still a plain move — the retry costs nothing idle."""
    module = retry_implementation(label)
    source = tmp_path / "staged.tmp"
    source.write_text("new", encoding="utf-8")
    destination = tmp_path / "live.json"
    destination.write_text("old", encoding="utf-8")

    require_retry_helper(module, label)(str(source), str(destination))

    assert destination.read_text(encoding="utf-8") == "new", f"{label}: the staged content did not land"
    assert not source.exists(), f"{label}: the staged file survived the move"


@pytest.mark.parametrize("label", RETRY_PARAMS)
def test_the_replace_helper_retries_through_a_transient_sharing_violation(
    label: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Two sharing violations then success — the move still lands."""
    module = retry_implementation(label)
    calls = {"count": 0}
    real_replace = os.replace

    def flaky_replace(source: str, destination: str) -> None:
        calls["count"] += 1
        if calls["count"] <= 2:
            raise sharing_violation(destination)
        real_replace(source, destination)

    isolated_replace(module, monkeypatch, flaky_replace)
    source = tmp_path / "staged.tmp"
    source.write_text("new", encoding="utf-8")
    destination = tmp_path / "live.json"
    destination.write_text("old", encoding="utf-8")

    require_retry_helper(module, label)(str(source), str(destination))

    assert destination.read_text(encoding="utf-8") == "new", f"{label}: the retried move never landed"
    assert calls["count"] == 3, f"{label}: retry path never engaged"


@pytest.mark.parametrize("label", RETRY_PARAMS)
def test_the_replace_retry_is_bounded_and_raises_when_exhausted(
    label: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A replace that never unblocks raises instead of retrying forever."""
    module = retry_implementation(label)
    calls = {"count": 0}

    def blocked_replace(source: str, destination: str) -> None:
        calls["count"] += 1
        raise sharing_violation(destination)

    isolated_replace(module, monkeypatch, blocked_replace)

    with pytest.raises(PermissionError):
        require_retry_helper(module, label)(str(tmp_path / "staged.tmp"), str(tmp_path / "live.json"))

    assert calls["count"] == module._REPLACE_ATTEMPTS, f"{label}: bound not honoured"


@pytest.mark.parametrize("label", RETRY_PARAMS)
def test_the_replace_retry_waits_between_attempts(label: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The backoff is used, not merely declared."""
    module = retry_implementation(label)

    def blocked_replace(source: str, destination: str) -> None:
        raise sharing_violation(destination)

    sleeps = isolated_replace(module, monkeypatch, blocked_replace)

    with pytest.raises(PermissionError):
        require_retry_helper(module, label)(str(tmp_path / "staged.tmp"), str(tmp_path / "live.json"))

    # One wait between each pair of attempts — never after the last, which raises.
    expected = [module._REPLACE_BACKOFF_SECONDS] * (module._REPLACE_ATTEMPTS - 1)
    assert sleeps == expected, f"{label}: the declared backoff was not slept"


@pytest.mark.parametrize("label", RETRY_PARAMS)
def test_a_non_permission_error_propagates_without_a_retry(label: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Only a sharing violation is worth waiting out."""
    module = retry_implementation(label)
    calls = {"count": 0}

    def broken_replace(source: str, destination: str) -> None:
        calls["count"] += 1
        raise OSError(errno.EXDEV, "invalid cross-device link")

    isolated_replace(module, monkeypatch, broken_replace)

    with pytest.raises(OSError) as caught:
        require_retry_helper(module, label)(str(tmp_path / "staged.tmp"), str(tmp_path / "live.json"))

    assert caught.value.errno == errno.EXDEV, f"{label}: a different error surfaced"
    assert calls["count"] == 1, f"{label}: a non-sharing failure was retried"


def test_retry_discovery_finds_the_whole_package_and_names_no_module_itself():
    """Guards the mechanism the six contracts above stand on."""
    assert len(RETRY_IMPLEMENTATIONS) >= 2, f"retry discovery found {RETRY_IMPLEMENTATIONS} under {PACKAGE_ROOT}"
    for label in RETRY_IMPLEMENTATIONS:
        module = retry_implementation(label)
        assert retry_helper_of(module) is not None, f"{label}: discovered but exposes no bounded replace helper"


def test_the_package_walk_skips_a_dropbox_and_an_archive_but_not_a_root_beneath_one(tmp_path: Path):
    """The walk reads shipped code and never a sandbox, judged below the root."""
    root = tmp_path / "dropbox" / "package"
    for relative in ("live.py", "dropbox/stray.py", ".archive/old.py", "branch/__pycache__/cached.py"):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text("", encoding="utf-8")
    assert shipped_python_files(root) == [root / "live.py"]


def test_the_package_walk_skips_a_dot_directory_but_not_a_root_beneath_one(tmp_path: Path):
    """A dot-prefixed directory below the root is never listed; the root is read whole."""
    root = tmp_path / ".live-x" / "package"
    for relative in ("live.py", ".live-y/copy.py", "branch/.live-z/deep.py"):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text("", encoding="utf-8")
    assert shipped_python_files(root) == [root / "live.py"]


def test_every_canonical_handler_that_stages_a_write_also_retries_the_replace():
    """A handler that stages then renames must not do the rename unguarded."""
    unguarded = []
    for branch in BRANCHES:
        source = handler_path(branch).read_text(encoding="utf-8")
        if "os.replace(" in source and not any(f"def {name}(" in source for name in RETRY_HELPER_NAMES):
            unguarded.append(branch)
    assert not unguarded, f"handlers calling os.replace with no bounded retry: {json.dumps(sorted(unguarded))}"


class CountingReplace:
    """An ``os`` stand-in that counts ``replace`` and forwards everything else."""

    def __init__(self, real: Any, calls: list, fail: Callable | None = None):
        """Wrap the real module."""
        self._real = real
        self._calls = calls
        self._fail = fail

    def __getattr__(self, name: str) -> Any:
        """Delegate every attribute this class does not define."""
        return getattr(self._real, name)

    def replace(self, source: Any, destination: Any) -> None:
        """Count the rename, optionally fail it, otherwise perform it."""
        self._calls.append((str(source), str(destination)))
        if self._fail is not None:
            self._fail(len(self._calls), destination)
        self._real.replace(source, destination)


def neighbouring_modules(module: Any) -> list:
    """Every module one hop out from what this one holds."""
    found = []
    for value in vars(module).values():
        if inspect.isfunction(value) or inspect.ismethod(value):
            found.append(inspect.getmodule(inspect.unwrap(value)))
        elif inspect.ismodule(value):
            found.append(value)
        elif inspect.isclass(value):
            found.append(inspect.getmodule(value))
    return found


def retry_owner(module: Any) -> Any:
    """The module that will actually perform this writer's rename.

    The rename may live in a re-exported module or a delegate (``aipass/shared``, ``trigger/apps/config.py``),
    so the search walks out from ``save_json``'s module; None is a named finding, not a gap.
    """
    start = inspect.getmodule(inspect.unwrap(module.save_json))
    seen: set[str] = set()
    queue = [start]
    while queue:
        candidate = queue.pop(0)
        if candidate is None or candidate.__name__ in seen:
            continue
        seen.add(candidate.__name__)
        if retry_helper_of(candidate) is not None:
            return candidate
        if candidate.__name__.startswith("aipass."):
            queue.extend(neighbouring_modules(candidate))
    return None


def public_writer(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Callable, Path]:
    """A branch's public writer, normalised across both calling conventions."""
    require_one_service(branch)
    module = implementation(branch)
    if required_positionals(module.save_json) == 3:
        module, _ = prepared(branch, tmp_path, monkeypatch)
        document = Path(str(module.get_json_path("durability", "data")))
        return module, lambda payload: module.save_json("durability", "data", payload), document
    document = tmp_path / "durability.json"
    return module, lambda payload: module.save_json(str(document), payload), document


def stray_temps(directory: Path) -> list:
    """Staging files left behind in a document directory."""
    if not directory.is_dir():
        return []
    return sorted(child.name for child in directory.iterdir() if child.suffix != ".json")


@pytest.mark.parametrize("branch", parametrized(WRITER_HAS_NO_BOUNDED_RETRY))
def test_the_public_writer_routes_its_write_through_the_bounded_replace_helper(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A write that lands by a bare rename re-introduces the Windows hang.

    Counted at the HELPER on the owning module (:func:`retry_owner`): an inlined ``os.replace`` would
    still bump a syscall counter.
    """
    module, save, document = public_writer(branch, tmp_path, monkeypatch)
    owner = retry_owner(module)
    assert owner is not None, f"{branch}: no bounded replace helper is reachable from save_json"

    name = retry_helper_name(owner)
    real = getattr(owner, name)
    calls: list = []

    def counting(source: Any, destination: Any) -> None:
        calls.append((str(source), str(destination)))
        real(source, destination)

    monkeypatch.setattr(owner, name, counting)
    save(copy.deepcopy(DATA_PAYLOAD))

    assert [destination for _source, destination in calls] == [str(document)], (
        f"{branch}: one save_json made {len(calls)} calls to {owner.__name__}.{name} ({calls}) — "
        f"expected exactly one staged write of {document} routed through the bounded retry"
    )


@pytest.mark.parametrize("branch", parametrized(WRITER_HAS_NO_BOUNDED_RETRY))
def test_an_exhausted_retry_leaves_the_original_intact_and_cleans_the_staged_temp(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A write that cannot land must lose the NEW document, never the old one."""
    module, save, document = public_writer(branch, tmp_path, monkeypatch)
    owner = retry_owner(module)
    assert owner is not None, f"{branch}: no bounded replace helper is reachable from save_json"

    save(copy.deepcopy(DATA_PAYLOAD))
    original = document.read_bytes()

    def always_blocked(attempt: int, destination: Any) -> None:
        raise sharing_violation(destination)

    monkeypatch.setattr(owner, "os", CountingReplace(os, [], fail=always_blocked))
    monkeypatch.setattr(owner, "_REPLACE_BACKOFF_SECONDS", 0, raising=False)
    monkeypatch.setattr(owner, "time", SimpleNamespace(sleep=lambda seconds: None))

    with contextlib.suppress(OSError):
        save({**copy.deepcopy(DATA_PAYLOAD), "counters": {"seen": 999}})

    assert document.read_bytes() == original, f"{branch}: the exhausted write damaged the live document"
    assert stray_temps(document.parent) == [], f"{branch}: staging files survived the failed write"


@pytest.mark.parametrize("branch", parametrized(WRITER_HAS_NO_BOUNDED_RETRY))
def test_the_public_writer_survives_a_transient_sharing_violation(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The retry is reached from the public entry point, not only in isolation."""
    module, save, document = public_writer(branch, tmp_path, monkeypatch)
    owner = retry_owner(module)
    assert owner is not None, f"{branch}: no bounded replace helper is reachable from save_json"

    def blocked_twice(attempt: int, destination: Any) -> None:
        if attempt <= 2:
            raise sharing_violation(destination)

    calls: list = []
    monkeypatch.setattr(owner, "os", CountingReplace(os, calls, fail=blocked_twice))
    monkeypatch.setattr(owner, "time", SimpleNamespace(sleep=lambda seconds: None))

    payload = {**copy.deepcopy(DATA_PAYLOAD), "counters": {"seen": 4242}}
    save(payload)

    assert len(calls) == 3, f"{branch}: retry path never engaged ({len(calls)} rename attempts)"
    landed = json.loads(document.read_text(encoding="utf-8"))
    assert landed["counters"] == {"seen": 4242}, f"{branch}: the retried write never landed"
    assert stray_temps(document.parent) == [], f"{branch}: staging files survived the retried write"


#: How the fleet REPORTS a write that could not land, rename blocked to exhaustion: every branch raises
#: the service's ``WriteFailed``. The test below still tolerates both dispositions: the caller's claim
#: is only that a write that never landed never reports success.
EXHAUSTED_WRITE_RAISES = 18
EXHAUSTED_WRITE_RETURNS_FALSE = 0


@pytest.mark.parametrize("branch", parametrized(WRITER_HAS_NO_BOUNDED_RETRY))
def test_a_write_that_cannot_land_never_reports_success(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The one thing both dispositions must agree on."""
    module, save, _ = public_writer(branch, tmp_path, monkeypatch)
    owner = retry_owner(module)
    assert owner is not None, f"{branch}: no bounded replace helper is reachable from save_json"

    def always_blocked(attempt: int, destination: Any) -> None:
        raise sharing_violation(destination)

    monkeypatch.setattr(owner, "os", CountingReplace(os, [], fail=always_blocked))
    monkeypatch.setattr(owner, "time", SimpleNamespace(sleep=lambda seconds: None))

    # A raiser leaves the answer at None, a returner at what it answered; only True fails. A suppression,
    # not a bare except, so the sanctioned outcome is visible.
    answer = None
    with contextlib.suppress(PermissionError, OSError):
        answer = save(copy.deepcopy(DATA_PAYLOAD))
    assert not answer, f"{branch}: save_json answered {answer!r} for a write that never landed"


#: Writers, and writes each performs. Small on purpose: a torn write fails on its FIRST occurrence,
#: and more threads only add flake surface.
CONCURRENT_WRITERS = 4
WRITES_PER_WRITER = 5

#: Ceiling on sampler loops, so a dead writer cannot hang the run; nothing asserts on elapsed time.
MAX_SAMPLES = 4000

#: Join ceiling: a deadlocked writer fails rather than hangs; nothing passes or fails on duration.
THREAD_JOIN_SECONDS = 60


@pytest.mark.parametrize("branch", parametrized(TORN_DOCUMENT_OBSERVED))
def test_concurrent_writers_never_expose_a_torn_document(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A reader during a write sees the old document or the new one, never half.

    A race that did not race SKIPS with its counters; evidence of a tear is always RED.
    """
    module, save, document = public_writer(branch, tmp_path, monkeypatch)
    save(copy.deepcopy(DATA_PAYLOAD))

    torn: list = []
    failures: list = []
    unreadable: list = []
    writes = {"done": 0}
    sampled = {"count": 0}
    finished = threading.Event()

    def writer(seat: int) -> None:
        for round_number in range(WRITES_PER_WRITER):
            payload = {**copy.deepcopy(DATA_PAYLOAD), "counters": {"seen": seat * 100 + round_number}}
            try:
                save(payload)
                writes["done"] += 1
            except Exception as error:  # recorded and re-reported below
                failures.append(f"writer {seat}: {type(error).__name__}: {error}")

    def sampler() -> None:
        for _ in range(MAX_SAMPLES):
            if finished.is_set():
                return
            try:
                raw = document.read_bytes()
            except (FileNotFoundError, PermissionError) as error:
                # Not swallowed: a read that could not happen is evidence of how thin the race was, so it is
                # counted into the skip message.
                unreadable.append(f"{type(error).__name__}: {error}")
                continue
            sampled["count"] += 1
            if not raw.strip():
                torn.append("empty document observed mid-write")
                continue
            try:
                json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                torn.append(f"unparseable document observed mid-write: {error}")

    watcher = threading.Thread(target=sampler, daemon=True)
    watcher.start()
    writers = [threading.Thread(target=writer, args=(seat,)) for seat in range(CONCURRENT_WRITERS)]
    for thread in writers:
        thread.start()
    for thread in writers:
        thread.join(timeout=THREAD_JOIN_SECONDS)
    finished.set()
    watcher.join(timeout=THREAD_JOIN_SECONDS)
    stuck = [thread.name for thread in writers if thread.is_alive()]

    assert not stuck, f"{branch}: writers never finished: {stuck}"
    assert not torn, f"{branch}: reader observed a torn document — {torn[:3]}"
    assert not failures, f"{branch}: a concurrent write raised — {failures[:3]}"

    final = document.read_bytes()
    assert final.strip(), f"{branch}: the document is empty after the race"
    json.loads(final.decode("utf-8"))
    assert stray_temps(document.parent) == [], f"{branch}: staging files survived the race"

    if sampled["count"] == 0 or writes["done"] == 0:
        pytest.skip(
            f"{branch}: the race did not race — "
            f"{writes['done']} writes completed, {sampled['count']} samples read, "
            f"{len(unreadable)} reads could not happen; "
            f"nothing was observed concurrently, so no tear could have been seen"
        )
