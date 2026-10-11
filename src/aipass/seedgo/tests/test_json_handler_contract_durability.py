# =================== AIPass ====================
# Name: test_json_handler_contract_durability.py
# Description: json_handler contract, durability clause: bounded replace, public writer, concurrency
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
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


# ---------------------------------------------------------------------------
# Durability discovery: every module that ships the bounded replace helper
# ---------------------------------------------------------------------------

#: The last step of every atomic write in the fleet: rename the staged file
#: over the live document, tolerating the sharing violation a concurrent
#: Windows reader causes, bounded so a permanently blocked target still fails.
RETRY_HELPER = "_replace_with_retry"

#: Both spellings the fleet uses for it. The private one is the majority;
#: ``trigger`` exports the same helper PUBLICLY from its config module, on
#: purpose and documented there, because that module is its shared helper home
#: and another module imports the name. Matching only the private spelling is
#: how slice 2 reported fourteen implementations when there are fifteen — a
#: scan keyed to the majority's naming cannot see the one that renamed itself.
RETRY_HELPER_NAMES = ("_replace_with_retry", "replace_with_retry")

#: Path parts that mean "not shipped code". A suite copy names the same symbol
#: while monkeypatching it, and an archived file is on no import path; either
#: one would enter the parametrization as an implementation that is not one.
UNSHIPPED_PARTS = frozenset({"tests", "test", ".archive", "__pycache__", ".sorting_unprocessed", "dropbox"})


def shipped_python_files(root: Path) -> list[Path]:
    """Every ``.py`` file under ``root`` that is shipped code, sorted.

    Args:
        root: The directory walked, :data:`PACKAGE_ROOT` in the suite.

    Returns:
        The files outside every :data:`UNSHIPPED_PARTS` directory and every
        directory whose name starts with a dot.

    A directory is pruned by its own name before the walk enters it, so a
    dropbox is never listed, and ``root`` itself is never judged: a checkout
    standing under a directory named ``dropbox`` is still read whole. A dot
    directory is pruned the same way (seedgo, fleet green leg 18): hooks'
    ``.live-<stamp>`` rollback snapshots are on no import path.
    """
    found = []
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = [
            name for name in subdirectories if name not in UNSHIPPED_PARTS and not name.startswith(".")
        ]
        found.extend(Path(directory) / name for name in files if name.endswith(".py"))
    return sorted(found)


def ships_retry_helper(path: Path) -> bool:
    """Whether a package file defines the replace helper itself.

    Args:
        path: A ``.py`` file found under :data:`PACKAGE_ROOT`.

    Returns:
        True when the file contains the definition.
    """
    source = path.read_text(encoding="utf-8", errors="ignore")
    return any(f"def {name}(" in source for name in RETRY_HELPER_NAMES)


def retry_label(relative: Path) -> str:
    """A short, stable test id for one implementation.

    Args:
        relative: Implementation path relative to :data:`PACKAGE_ROOT`.

    Returns:
        The bare branch name for an implementation at the canonical handler
        location, and the full relative path for one living anywhere else.
        Deliberately verbose for the second kind rather than
        ``branch/stem``: that shorter form renders the shared module as
        ``aipass/json_handler``, which reads like the aipass BRANCH's handler
        — a label that misnames its subject is worse in a failure message
        than a long one.
    """
    canonical = relative.parts[1:] == ("apps", "handlers", "json", "json_handler.py")
    return relative.parts[0] if canonical else relative.with_suffix("").as_posix()


#: Label to file for every implementation the package ships. Each is loaded
#: from its file by :func:`retry_implementation`, never by its dotted name:
#: two of them live under a branch's ``apps/handlers`` and the fences refuse
#: that import from seedgo (DPLAN-0404); this suite reads them as specimens.
#:
#: An ``rglob`` over the package rather than the two globs that would find the
#: known families, and the difference is a measurement rather than a
#: preference: globbing ``*/apps/handlers/json/json_handler.py`` plus the
#: shared module finds most of them and misses ``spawn/atomic_write``, a copy
#: of the same helper under a name no handler glob matches.
#: Discovery narrow enough to confirm the list it was handed cannot report the
#: implementation nobody listed.
#:
#: The count is a MEASUREMENT and it is falling: sixteen on 2026-09-02,
#: fourteen on 2026-09-03 after the second sweep pair, eight on 2026-09-04
#: with fifteen of eighteen swept, six after pair 5 took commons and daemon,
#: and FIVE after pair 6 took api — the last branch handler with a retry helper
#: of its own. It did not fall when prax migrated — prax's helper MOVED into
#: ``json_service``, it did not disappear.
#:
#: NO BRANCH HANDLER IS ON THIS LIST ANY MORE. The five standing are
#: ``aipass/shared/json_handler`` (the file @aipass retires under FPLAN-0489),
#: ``hooks/apps/handlers/json/files``, the service itself,
#: ``spawn/atomic_write`` and ``trigger/apps/config``. Four of those are the
#: floor: modules that own a bounded rename for their own reasons and are not
#: json handlers. The number falls to four when FPLAN-0489 lands. No number is
#: asserted here; the floor below is, so a sweep that removes a copy cannot
#: turn this red.
RETRY_IMPLEMENTATIONS = {
    retry_label(path.relative_to(PACKAGE_ROOT)): path
    for path in shipped_python_files(PACKAGE_ROOT)
    if ships_retry_helper(path)
}

#: One module object per label for the whole run, for the same reason as
#: :data:`IMPLEMENTATIONS`: a test that captures the helper from one load and
#: patches another patches nothing.
RETRY_MODULES: dict[str, Any] = {}

#: One param per implementation, and deliberately no divergence table beside
#: it. Every body was measured assertion-identical on 2026-09-02
#: (docstring wording aside), so a disagreement discovered here is news, not a
#: known variation to be marked down in advance.
RETRY_PARAMS = [pytest.param(label, id=label) for label in RETRY_IMPLEMENTATIONS]


def retry_implementation(label: str) -> Any:
    """Load one implementation from its file by its discovery label, once.

    Args:
        label: A key of :data:`RETRY_IMPLEMENTATIONS`.

    Returns:
        The loaded module, the same object on every call.
    """
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
    """The bounded replace helper a module ships, under either spelling.

    Args:
        module: A discovered implementation.

    Returns:
        The callable, or None when the module ships neither spelling.
    """
    for name in RETRY_HELPER_NAMES:
        candidate = getattr(module, name, None)
        if callable(candidate):
            return candidate
    return None


def retry_helper_name(module: Any) -> str:
    """The spelling one module actually uses, for failure messages.

    Args:
        module: A discovered implementation.

    Returns:
        The attribute name found, or the majority spelling when neither is.
    """
    for name in RETRY_HELPER_NAMES:
        if callable(getattr(module, name, None)):
            return name
    return RETRY_HELPER


def require_retry_helper(module: Any, label: str) -> Callable:
    """The module's bounded helper, or a failure naming the module.

    Discovery only admits modules that ship one, so a miss here means
    discovery and reality disagree — which is a red, not an Optional the
    call sites should each re-check.

    Args:
        module: A discovered implementation.
        label: Discovery label, for the message.

    Returns:
        The bounded replace helper.
    """
    helper = retry_helper_of(module)
    assert helper is not None, f"{label}: discovered as an implementation but ships no bounded replace helper"
    return helper


def isolated_replace(module: Any, monkeypatch: pytest.MonkeyPatch, replace: Callable) -> list:
    """Point ONE module's ``os.replace`` and ``time.sleep`` at test doubles.

    Patches the module's own ``os`` and ``time`` bindings, never the shared
    ``os`` and ``time`` modules. The distinction is not cosmetic and was paid
    for once already in this fleet: patching ``sleep`` on the shared ``time``
    module reaches every thread in the process, so a full-suite run collected
    durations belonging to other tests and the wait pin failed intermittently
    (spawn, 2026-08-30). Fourteen implementations import those same two
    modules, which would make a shared-module patch a channel between
    parameters here as well as between files.

    The stub carries ``sleep`` and nothing else, and that narrowness is the
    point. The one service names its staged files from ``os.getpid()`` and an
    ``itertools.count()``, deliberately not from the clock, and says why in
    ``json_service.py`` (08359ec2): a caller stubbing ``time`` to take the wait
    out of the bounded retry is a legitimate thing to do, and a writer that
    cannot name a file under a stubbed clock would be failing for a reason that
    has nothing to do with writing. ``sleep`` is therefore the whole surface
    this helper has to stand in for.

    Keeping the stub strict makes it a detector. If an implementation ever
    reaches for a second ``time`` attribute, this raises ``AttributeError``
    where it happens instead of quietly accepting a new clock dependency the
    contract never agreed to — which is what a delegating stub would do. I
    briefly delegated ``time_ns`` here on 2026-09-04 after seeing exactly that
    AttributeError across all fifteen migrated branches; the cause was an
    intermediate state of the service being edited in parallel, not the surface
    as it shipped, so the delegation is gone and the pin stands.

    Args:
        module: The implementation under test.
        monkeypatch: Restores both bindings at teardown.
        replace: Stands in for ``os.replace``.

    Returns:
        The list each ``time.sleep`` duration is appended to, in order.
    """
    sleeps: list[float] = []
    monkeypatch.setattr(module, "os", SimpleNamespace(replace=replace))
    monkeypatch.setattr(module, "time", SimpleNamespace(sleep=sleeps.append))
    return sleeps


def sharing_violation(destination: Any) -> PermissionError:
    """The error Windows raises when a reader still holds the target open.

    Args:
        destination: The live document being replaced.

    Returns:
        A ``PermissionError`` shaped like the real one, errno 13.
    """
    return PermissionError(13, "sharing violation", str(destination))


# ---------------------------------------------------------------------------
# Contracts: durability of the bounded replace helper
# ---------------------------------------------------------------------------
#
# These six ran as thirty-seven separate copies in seven branches before this
# file existed, one set per implementation, because each copy exercised a
# DIFFERENT module. Nothing is asserted more weakly here to make one contract
# cover fourteen: every copy's assertions are kept verbatim, and the module
# they run against is the parameter. Pure monkeypatch and ``tmp_path``, no
# platform branch and no skip, so the Windows CI leg runs the same fourteen
# cases as the POSIX legs — which matters, because the behaviour being pinned
# only ever misbehaves on Windows.


@pytest.mark.parametrize("label", RETRY_PARAMS)
def test_the_replace_helper_is_declared_bounded_and_patient(label: str):
    """The helper exists, retries more than once, and waits a nonzero time.

    The two constants are pinned as well as the function because either one
    alone defeats it: a single attempt is not a retry, and a zero backoff is a
    busy spin that finishes before the reader handle it exists to outlast.
    """
    module = retry_implementation(label)
    assert retry_helper_of(module) is not None, (
        f"{label}: no bounded replace helper — a Windows sharing violation still kills the write"
    )
    assert module._REPLACE_ATTEMPTS > 1, f"{label}: a single attempt is not a retry"
    assert module._REPLACE_BACKOFF_SECONDS > 0, f"{label}: a zero backoff spins instead of waiting"


@pytest.mark.parametrize("label", RETRY_PARAMS)
def test_the_replace_helper_moves_the_staged_file_over_the_target(label: str, tmp_path: Path):
    """The happy path is still a plain move — the retry costs nothing idle.

    Runs against the real ``os.replace``: the point is that wrapping the
    syscall in a retry loop did not change what it does when nothing blocks.
    """
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
    """Two sharing violations then success — the move still lands.

    The count is asserted exactly, not as "more than one": a helper that gave
    up and swallowed the error would leave the destination stale, and a helper
    that never engaged the retry would fail on the first call. Only three
    attempts describe the path this pin is named for.
    """
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
    """A replace that never unblocks raises instead of retrying forever.

    Asserted against the module's own declared bound rather than a literal, so
    an implementation that tunes its attempt count stays covered and one that
    quietly stops honouring its own constant does not.
    """
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
    """The backoff is used, not merely declared.

    Deleting the sleep leaves a busy spin that passes every other pin above:
    it still retries, still bounds, still raises. But forty immediate attempts
    finish inside a microsecond and never outlast the reader handle the retry
    exists to wait out, so the retry stops being a fix and becomes decoration,
    and nothing else here would say so — the mutation survived a run on
    2026-08-18. Counting the sleeps pins the wait without asserting on
    wall-clock time, which would be flaky on a loaded runner.
    """
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
    """Only a sharing violation is worth waiting out.

    A cross-device rename or a full disk will not fix itself in 200ms, and
    retrying it forty times buys nothing but a slower failure and a longer
    wait before the caller learns what actually went wrong.
    """
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
    """Guards the mechanism the six contracts above stand on.

    If the scan silently matched nothing, all six would collect zero cases and
    the run would be green while measuring nothing at all — the failure mode
    that makes a consolidated suite more dangerous than the copies it
    replaced, since there is now one place to go quiet instead of seven. Pins
    a floor rather than a count so a new implementation does not turn this
    red, and checks every discovered label really loads.
    """
    assert len(RETRY_IMPLEMENTATIONS) >= 2, f"retry discovery found {RETRY_IMPLEMENTATIONS} under {PACKAGE_ROOT}"
    for label in RETRY_IMPLEMENTATIONS:
        module = retry_implementation(label)
        assert retry_helper_of(module) is not None, f"{label}: discovered but exposes no bounded replace helper"


def test_the_package_walk_skips_a_dropbox_and_an_archive_but_not_a_root_beneath_one(tmp_path: Path):
    """The walk reads shipped code and never a sandbox, judged below the root.

    A dropbox is a sandbox like ``.archive`` (the owner's ruling, 2026-09-27):
    what another branch hands in there is no implementation of this package,
    and the walk must not read it. The directory is judged by its own name
    relative to the walked root, so a checkout that itself stands under a
    directory named ``dropbox`` is still read whole. Red first on the walk
    that filtered absolute parts and did not name dropbox: it read
    ``dropbox/stray.py`` (seedgo, fleet green leg 4).
    """
    root = tmp_path / "dropbox" / "package"
    for relative in ("live.py", "dropbox/stray.py", ".archive/old.py", "branch/__pycache__/cached.py"):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text("", encoding="utf-8")
    assert shipped_python_files(root) == [root / "live.py"]


def test_the_package_walk_skips_a_dot_directory_but_not_a_root_beneath_one(tmp_path: Path):
    """A dot-prefixed directory below the root is never listed; the root is read whole.

    hooks keeps rollback snapshots as ``hooks/.live-<stamp>/``, copies of its
    handlers that no import path answers, and the walk listed them: the retry
    contracts then built ``aipass.hooks..live-...`` and went red nineteen
    times (seedgo, fleet green leg 18). A directory whose own name starts with
    a dot is pruned like the names of :data:`UNSHIPPED_PARTS`, judged relative
    to the walked root, so a root that itself stands inside ``.live-x`` is
    still read. Red first on the walk that pruned by name alone: it listed
    ``.live-y/copy.py``.
    """
    root = tmp_path / ".live-x" / "package"
    for relative in ("live.py", ".live-y/copy.py", "branch/.live-z/deep.py"):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text("", encoding="utf-8")
    assert shipped_python_files(root) == [root / "live.py"]


def test_every_canonical_handler_that_stages_a_write_also_retries_the_replace():
    """A handler that stages then renames must not do the rename unguarded.

    Discovery is a text scan, so it answers "who has the helper" but never
    "who should". This crosses it against the canonical handlers the rest of
    the file already found: a branch whose handler stages a temp file and then
    calls ``os.replace`` without the bounded helper has the exact defect the
    helper exists to fix, and would otherwise simply be absent from the
    parametrization above rather than reported by it.
    """
    unguarded = []
    for branch in BRANCHES:
        source = handler_path(branch).read_text(encoding="utf-8")
        if "os.replace(" in source and not any(f"def {name}(" in source for name in RETRY_HELPER_NAMES):
            unguarded.append(branch)
    assert not unguarded, f"handlers calling os.replace with no bounded retry: {json.dumps(sorted(unguarded))}"


# ---------------------------------------------------------------------------
# The public writer and the helper underneath it
# ---------------------------------------------------------------------------


class CountingReplace:
    """An ``os`` stand-in that counts ``replace`` and forwards everything else.

    Installed on ONE module's own ``os`` binding, never on the shared ``os``
    module, for the reason slice 2 records: this suite's autouse fixture and
    the logger boot it documents both provoke writes in OTHER branches during
    a test, so a global counter would count a foreign rename as though the
    subject had made it — a false green in the exact test whose only job is to
    prove the subject renamed something.

    Everything but ``replace`` is delegated to the real module, because a
    writer stages with ``os.fdopen``, cleans up with ``os.unlink`` and asks
    ``os.path`` about its target; a stub carrying one attribute would break
    the write it is supposed to be observing.
    """

    def __init__(self, real: Any, calls: list, fail: Callable | None = None):
        """Wrap the real module.

        Args:
            real: The genuine ``os`` module.
            calls: Appended to on every ``replace``.
            fail: Called first on every ``replace``; may raise to simulate a
                blocked target. None means always perform the real move.
        """
        self._real = real
        self._calls = calls
        self._fail = fail

    def __getattr__(self, name: str) -> Any:
        """Delegate every attribute this class does not define.

        Args:
            name: Attribute the writer asked for.

        Returns:
            The real module's attribute.
        """
        return getattr(self._real, name)

    def replace(self, source: Any, destination: Any) -> None:
        """Count the rename, optionally fail it, otherwise perform it.

        Args:
            source: Staged file.
            destination: Live document.
        """
        self._calls.append((str(source), str(destination)))
        if self._fail is not None:
            self._fail(len(self._calls), destination)
        self._real.replace(source, destination)


def neighbouring_modules(module: Any) -> list:
    """Every module one hop out from what this one holds.

    Split out of :func:`retry_owner` so the search stays one loop deep. A
    writer reaches its rename through a function, a class or a re-exported
    module, and all three shapes occur in this fleet, so all three are
    followed.

    Args:
        module: Module to look outward from.

    Returns:
        Modules referenced by its globals, with duplicates and None left in
        for the caller's own seen-set to handle.
    """
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

    Not the same as the handler under test, and the difference is the whole
    reason this resolver exists rather than a hardcoded map:

    * twelve branches own the helper in their own json_handler;
    * ``aipass``, ``canary``, ``memory`` and ``spawn`` re-export a writer whose
      rename happens in ``aipass/shared/json_handler.py``;
    * ``trigger``'s writer delegates again, to ``trigger/apps/config.py``,
      which is also where its PUBLICLY named helper lives.

    So the search walks out from the module that defines ``save_json``,
    following the functions, classes and modules it holds, and stops at the
    first module shipping a bounded helper under either spelling.

    Args:
        module: A branch's imported json_handler.

    Returns:
        The owning module, or None when no bounded helper is reachable at all
        — which is a finding, not a gap in this search, and is reported as a
        named divergence rather than a skip.
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
    """A branch's public writer, normalised across both calling conventions.

    The convention split is the reason these three contracts could not simply
    be copied from one branch's suite: sixteen branches wrote
    ``save_json(module_name, json_type, data)`` and resolved the path
    themselves, ``backup`` wrote ``save_json(path, data)``. Both are answered
    here so the contract bodies below never branch on it.

    Measured 2026-09-03: the split is GONE. backup's sweep took its
    path-addressed form with the old handler, so all eighteen now write the
    three-argument form. The normaliser stays — it costs one branch and it is
    the thing that would notice a nineteenth convention arriving — but it is
    down to one convention to serve, which is worth saying out loud rather
    than leaving a reader to believe the fleet is still split.

    Args:
        branch: Branch to load.
        tmp_path: pytest's per-test directory.
        monkeypatch: Passed through to the redirect.

    Returns:
        The redirected module, a one-argument ``save`` closure, and the
        document path that ``save`` writes to.
    """
    require_one_service(branch)
    module = implementation(branch)
    if required_positionals(module.save_json) == 3:
        module, _ = prepared(branch, tmp_path, monkeypatch)
        document = Path(str(module.get_json_path("durability", "data")))
        return module, lambda payload: module.save_json("durability", "data", payload), document
    document = tmp_path / "durability.json"
    return module, lambda payload: module.save_json(str(document), payload), document


def stray_temps(directory: Path) -> list:
    """Staging files left behind in a document directory.

    Args:
        directory: Where the document lives.

    Returns:
        Sorted names of everything that is not a ``.json`` document.
    """
    if not directory.is_dir():
        return []
    return sorted(child.name for child in directory.iterdir() if child.suffix != ".json")


# ---------------------------------------------------------------------------
# Contracts: the public writer's durability
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("branch", parametrized(WRITER_HAS_NO_BOUNDED_RETRY))
def test_the_public_writer_routes_its_write_through_the_bounded_replace_helper(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A write that lands by a bare rename re-introduces the Windows hang.

    Mutant: seedgo's shim saves to another document in apps/handlers/json/json_handler.py — killed.

    The helper being present is pinned above; this pins that the writer
    actually goes through it, which is a different claim and the one that
    decays silently. A refactor that inlines ``os.replace`` back into
    ``save_json`` leaves every helper contract green and the branch broken on
    Windows again.

    What is counted is the HELPER, not ``os.replace``. Counting the syscall
    was the first shape of this test and it does not work: an inlined
    ``os.replace`` in ``save_json`` still increments a syscall counter, so the
    test would have passed the very refactor it exists to forbid. Wrapping the
    helper on the OWNING module — resolved by :func:`retry_owner`, because for
    six branches the rename does not happen in the handler under test at all —
    is the assertion that actually distinguishes the two.
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
    """A write that cannot land must lose the NEW document, never the old one.

    The failure this forbids is the one that makes atomic writes worth having:
    a blocked rename that has already truncated the live file, so the caller
    loses a document it never asked to delete. The staging file is checked in
    the same breath because the other way to fail here is to preserve the
    original and leave a growing pile of ``.tmp`` beside it — correct, and
    still a bug.

    Deliberately silent about HOW the writer reports the failure: the fleet
    splits between raising and returning False, that split is pinned
    elsewhere, and folding it in here would turn a durability contract into a
    return-value contract that skips half the fleet.

    "Silent about the disposition" means the suppression has to cover every
    disposition, and it did not: it named ``PermissionError``, the exception
    the pre-migration raisers happen to let out. The one service raises
    ``WriteFailed`` instead, so on 2026-09-03 the first migrated branch failed
    this test by reporting its failure the way the spec says to. ``OSError`` is
    the honest bound — both dispositions are subclasses of it, and inside this
    block the only thing that can raise one is the write this test blocked on
    purpose.
    """
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
    """The retry is reached from the public entry point, not only in isolation.

    Two sharing violations then success, injected at the owning module's own
    rename: the document must still contain what the caller saved. This is the
    end-to-end version of the helper contract above — a writer that caught
    PermissionError itself and gave up would pass every helper pin and fail
    here.
    """
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


#: How the fleet REPORTS a write that could not land, measured 2026-09-02 with
#: the rename blocked to exhaustion. A near-even split, and deliberately not
#: written as a majority-plus-xfail table: calling either one "the contract"
#: would mark half the fleet as divergent from a coin toss. What every caller
#: actually needs is pinned instead, and it holds for all of them.
#:
#: Re-measured 2026-09-03 as the sweep began. prax and spawn both migrated that
#: night and both moved from the False column to the raise column, and the
#: exception is the service's own ``WriteFailed`` rather than the
#: ``PermissionError`` the other raisers let out. Measured on prax directly
#: (rename blocked to exhaustion); spawn is asserted on identity rather than a
#: second probe, because its handler is byte-identical to prax's — that
#: equality is exactly what the migration buys and what the IDENTITY axis above
#: pins. Counted here rather than left at yesterday's split because this is a
#: measurement record, and a record two branches stale is a record that has
#: started lying. The rest move the same way as the sweep reaches them; the
#: split ends at 18 / 0 and the constants go with the tables.
#:
#: Re-measured again 2026-09-03 afternoon, after the second sweep pair landed
#: devpulse, backup, hooks and aipass on the canonical shim. Only ``aipass`` of
#: those four was in the False column, so it crossed and the split moved by
#: one. Six branches now carry the shim; twelve have not been swept.
#:
#: Re-measured 2026-09-04 with fifteen of eighteen swept (DPLAN-0325 part B,
#: staging measurement). The near-even split of 09-02 is gone: the rename
#: blocked to exhaustion now raises for SEVENTEEN branches and returns False
#: for one. Fifteen of the seventeen raise the service's own ``WriteFailed``;
#: ``commons`` and ``daemon`` still let a bare ``PermissionError`` out of
#: their own handlers. ``ai_mail`` joins the count for the first time — the
#: 09-03 record listed seventeen branches, not eighteen, because ai_mail's own
#: helper was not reached then.
#:
#: Pair 5 the same day swept commons and daemon, so the SPLIT is unchanged at
#: 17 / 1 while its composition is not: all seventeen raisers now raise the
#: service's ``WriteFailed``, and the last bare ``PermissionError`` in the
#: fleet is gone. Recorded rather than left implied — the numbers below would
#: otherwise still read as two branches disagreeing about the exception type.
#:
#: THE SPLIT IS OVER. Re-measured 2026-09-04 after pair 6 swept api, the
#: eighteenth and last: with the rename blocked to exhaustion, all EIGHTEEN
#: branches raise, and every one of them raises the service's own
#: ``WriteFailed``. Not one returns False. The near-even split of 09-02 — the
#: reason this record exists and the reason the test below refuses to pick a
#: side — was eighteen implementations disagreeing, and there is one
#: implementation now.
#:
#: raise (18): every branch. return False (0): none.
#:
#: The constants are kept at their final values rather than deleted. They are a
#: measurement record, and the whole point of the record is that it ends
#: somewhere; a reader who finds the test below tolerating two dispositions
#: needs to be able to see that the tolerance was earned and is now historical.
#: The test itself is deliberately NOT narrowed to "must raise": the claim a
#: caller depends on is that a write that never landed never reports success,
#: and that claim should not go red the day a branch legitimately chooses the
#: other disposition again.
EXHAUSTED_WRITE_RAISES = 18
EXHAUSTED_WRITE_RETURNS_FALSE = 0


@pytest.mark.parametrize("branch", parametrized(WRITER_HAS_NO_BOUNDED_RETRY))
def test_a_write_that_cannot_land_never_reports_success(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The one thing both dispositions must agree on.

    The twins this replaces asserted ``is False`` because that is what their
    own branch does; three of them would have gone red if their handler had
    switched to raising, which is not a regression. So the assertion here is
    the claim a caller actually depends on and that both camps satisfy: a
    write that never landed must not come back looking like one that did.
    Returning True after an exhausted retry is the failure this forbids, and
    it is silent by construction — the caller has no other signal.
    """
    module, save, _ = public_writer(branch, tmp_path, monkeypatch)
    owner = retry_owner(module)
    assert owner is not None, f"{branch}: no bounded replace helper is reachable from save_json"

    def always_blocked(attempt: int, destination: Any) -> None:
        raise sharing_violation(destination)

    monkeypatch.setattr(owner, "os", CountingReplace(os, [], fail=always_blocked))
    monkeypatch.setattr(owner, "time", SimpleNamespace(sleep=lambda seconds: None))

    # Both dispositions land here without a branch: a raiser leaves the answer
    # at None, a returner leaves it at whatever it answered, and only True is
    # a failure. Written as a suppression rather than a bare except so the
    # sanctioned outcome is visible in the code instead of swallowed by it.
    answer = None
    with contextlib.suppress(PermissionError, OSError):
        answer = save(copy.deepcopy(DATA_PAYLOAD))
    assert not answer, f"{branch}: save_json answered {answer!r} for a write that never landed"


# ---------------------------------------------------------------------------
# Contracts: concurrency
# ---------------------------------------------------------------------------

#: Writers, and writes each performs. Small and fixed on purpose. The property
#: under test is "a reader never sees half a document", which a torn write
#: violates on its FIRST occurrence — piling on threads buys no sensitivity and
#: costs flake surface on a loaded runner.
CONCURRENT_WRITERS = 4
WRITES_PER_WRITER = 5

#: Ceiling on sampler loops, so a writer that dies cannot hang the run. Not a
#: timeout: nothing here asserts on elapsed time, which is the other way this
#: kind of test goes flaky.
MAX_SAMPLES = 4000

#: Join ceiling. A writer that deadlocks must fail this test rather than hang
#: the suite, and it is not a timing ASSERTION: nothing passes or fails on how
#: long the race took, only on whether a thread is still alive at the end.
THREAD_JOIN_SECONDS = 60


@pytest.mark.parametrize("branch", parametrized(TORN_DOCUMENT_OBSERVED))
def test_concurrent_writers_never_expose_a_torn_document(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A reader during a write sees the old document or the new one, never half.

    This is the property the whole staging dance exists to buy, and the only
    one in this file that needs real threads: a writer that truncates in place
    passes every single-threaded contract above and still hands a reader a
    half-written file.

    THE SKIP IS PART OF THE MEASUREMENT, not politeness. A race that did not
    actually race proves nothing, and reporting it as a pass is how a
    concurrency test rots into decoration — so the counters are asserted
    first, and a run where the sampler never read while a write was in flight
    SKIPS with those counters in the message. What is never skipped is
    evidence of damage: a sample that failed to parse, or a final document
    that is empty or unparseable, is RED even if the counters say the race was
    thin. Absence of proof skips; proof of a tear fails.
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
                # Not swallowed: a read that could not happen is evidence about
                # how thin the race was, so it is counted and reported in the
                # skip message rather than silently dropped.
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
