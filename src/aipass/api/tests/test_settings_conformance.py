# =================== AIPass ====================
# Name: test_settings_conformance.py
# Description: The settings conformance corpus, python side — shared goldens both runtimes must satisfy
# Version: 1.0.0
# Created: 2026-08-18
# Modified: 2026-08-18
# =============================================

"""
The python runner for the shared settings conformance corpus (FPLAN-0438 R3).

WHY THIS EXISTS. The settings lane is a faithful mirror of @baud's settings.rs,
and a mirror drifts. @baud measured six real divergences between the two
implementations in one night — not by reading each other's source, by running
both — and every one of them was a place where two faces would have written the
operator's own config differently while each believed it was correct.

Prose cannot hold a mirror straight. Shared DATA can: one set of cases, in
plain JSON, that each runtime proves it satisfies in its own test suite. When
the two disagree from here on, a case goes red on one side and names the
disagreement, instead of an operator finding it.

THE CASES ARE THE CONTRACT, not this file. This file only knows how to build a
starting state, call a door, and compare an answer. A rust runner walks the same
directory with serde and does the same three things — the JSON carries no python
in it anywhere, which is the whole point.

See tests/conformance/settings/README.md for the case format.
"""

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any, Dict, List

import pytest

from aipass.api.apps.handlers.host import settings as host_settings

CORPUS = Path(__file__).parent / "conformance" / "settings"
MANIFEST = CORPUS / "manifest.json"

RUNTIME = "python"

# A case is SUPPORTED (must pass here), PENDING (a known divergence the other
# runtime has not closed yet), or DIVERGENT (a difference ruled deliberate).
SUPPORTED = "supported"
PENDING = "pending"


def _load_manifest() -> Dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _load_cases() -> List[Dict[str, Any]]:
    """Every case file, in a stable order so a failure is always the same case."""
    return [
        json.loads((CORPUS / relative).read_text(encoding="utf-8")) for relative in sorted(_load_manifest()["files"])
    ]


CASES = _load_cases()


class TestTheCorpusItself:
    """
    Guards on the corpus before the corpus guards anything.

    An empty or half-read corpus is the failure mode that matters most here,
    because it reports as SUCCESS: zero cases run, zero cases fail, the suite is
    green and nothing was checked. Every assertion in this class exists to make
    that impossible.
    """

    def test_the_corpus_is_not_empty(self) -> None:
        """The silent-success guard. A corpus that finds nothing must fail loudly."""
        assert len(CASES) > 0
        assert len(CASES) == _load_manifest()["case_count"]

    def test_the_manifest_matches_what_is_on_disk(self) -> None:
        """
        The pin. Every case file's digest is recorded, so a case edited without
        the manifest being regenerated is caught here rather than trusted.

        This is also what a vendored copy in another repository checks itself
        against: same digests, same answer, and a stale copy says so out loud.
        """
        manifest = _load_manifest()
        on_disk = {
            str(path.relative_to(CORPUS)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(CORPUS.rglob("*.json"))
            if path.name != "manifest.json"
        }

        # The failure carries the correction with it. A pin that tells you only
        # that you are wrong makes the honest move (regenerate) the tedious one,
        # and the tempting move (delete the pin) the easy one.
        corrected = json.dumps(
            {**manifest, "case_count": len(on_disk), "files": dict(sorted(on_disk.items()))},
            indent=2,
            ensure_ascii=False,
        )

        assert on_disk == manifest["files"], (
            f"The corpus and its manifest disagree. If the case change was intended, "
            f"manifest.json should now read:\n\n{corrected}\n"
        )

    def test_every_case_declares_a_verdict_for_this_runtime(self) -> None:
        """A case that forgot to say whether python must satisfy it would skip silently."""
        for entry in CASES:
            assert RUNTIME in entry["runtimes"], entry["id"]

    def test_both_documents_are_covered(self) -> None:
        """The merge semantics are as drift-prone as the patch semantics."""
        documents = {entry["document"] for entry in CASES}

        assert documents == {"agent", "baud"}


def _build(root: Path, given: Dict[str, Any]) -> Path:
    """
    Put the filesystem into the case's starting state and hand back the path.

    Every state here is one a real branch can genuinely be in — this is the
    half of a conformance case that a prose description always leaves vague.
    """
    target = root / given["path"]
    state = given["state"]

    if state == "absent_parent":
        # Deliberately nothing: not the file, not the directory holding it.
        return target

    if state == "parent_is_a_file":
        target.parent.parent.mkdir(parents=True, exist_ok=True)
        target.parent.write_text("I am a file standing where a directory belongs", encoding="utf-8")
        return target

    target.parent.mkdir(parents=True, exist_ok=True)

    if state == "missing":
        return target

    if state == "empty":
        target.write_text("", encoding="utf-8")
    elif state == "raw":
        target.write_text(given["raw"], encoding="utf-8")
    elif state in ("present", "unreadable"):
        target.write_text(json.dumps(given["content"]), encoding="utf-8")
    else:
        raise AssertionError(f"unknown given state {state!r}")

    if state == "unreadable":
        target.chmod(0o000)

    return target


def _run(root: Path, entry: Dict[str, Any]) -> Any:
    """Call the door this case is about."""
    document = entry["document"]
    operation = entry["operation"]

    if operation["kind"] == "read":
        if document == "agent":
            return host_settings.read_agent_settings(root)
        return host_settings.read_baud_settings(root)

    if document == "agent":
        return host_settings.write_agent_settings(root, operation["patch"])
    return host_settings.write_baud_settings(root, operation["patch"])


def _expectation(entry: Dict[str, Any]) -> Dict[str, Any]:
    """The case's expectation, with this runtime's overrides folded in."""
    expected = dict(entry["expect"])
    expected.update(entry.get("expect_by_runtime", {}).get(RUNTIME, {}))
    return expected


def _snapshot(target: Path) -> Any:
    """The file's exact bytes, or None when there is no file."""
    try:
        return target.read_bytes()
    except OSError:
        return None


@pytest.mark.parametrize("entry", CASES, ids=[entry["id"] for entry in CASES])
def test_the_settings_doors_satisfy_the_shared_corpus(entry: Dict[str, Any], tmp_path: Path) -> None:
    """
    One shared case, run against this runtime's doors.

    Hermetic by construction: every case builds its whole world under tmp_path
    and reads nothing the machine happens to be carrying. That is not a style
    preference — this fleet spent a night on tests that were green only because
    of state a fresh runner does not have.
    """
    verdict = entry["runtimes"][RUNTIME]

    if verdict == PENDING:
        pytest.skip(f"{entry['id']}: pending on {RUNTIME} — {entry.get('notes', 'no reason recorded')}")

    if entry["given"]["state"] == "unreadable" and os.geteuid() == 0:
        pytest.skip("root reads everything; a mode says nothing to it")

    target = _build(tmp_path, entry["given"])
    before = _snapshot(target)
    expected = _expectation(entry)
    outcome = expected["outcome"]

    try:
        if outcome == "refused":
            with pytest.raises(host_settings.SettingsRefused):
                _run(tmp_path, entry)
        elif outcome == "unavailable":
            with pytest.raises(host_settings.SettingsUnavailable):
                _run(tmp_path, entry)
        else:
            answer = _run(tmp_path, entry)

            if "view" in expected:
                assert answer == expected["view"], entry["id"]
            if "document" in expected:
                assert answer == expected["document"], entry["id"]
            if "file" in expected:
                assert json.loads(target.read_text(encoding="utf-8")) == expected["file"], entry["id"]
            if "mode" in expected:
                assert stat.S_IMODE(target.stat().st_mode) == int(expected["mode"], 8), entry["id"]

        if expected.get("file_unchanged"):
            # A refusal that already wrote something is not a refusal. This is
            # the read-then-error-then-write doctrine, asserted in bytes.
            assert _snapshot(target) == before, entry["id"]
    finally:
        if entry["given"]["state"] == "unreadable" and target.exists():
            target.chmod(0o600)
