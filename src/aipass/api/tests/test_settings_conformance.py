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
import tempfile
from functools import lru_cache
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

# Named platform capabilities. A case declares which ones it needs; this runner
# MEASURES each one on the machine it is running on rather than reading
# sys.platform, because "what does this OS do here" is a question with an
# answer and a platform string is a guess about it.
UNREADABLE_FILES = "unreadable_files"
POSIX_MODE_BITS = "posix_mode_bits"
PARENT_IS_A_FILE_IS_DISTINGUISHABLE = "parent_is_a_file_is_distinguishable"

CAPABILITY_MEANINGS = {
    UNREADABLE_FILES: "a file can be made genuinely unreadable to this process",
    POSIX_MODE_BITS: "st_mode carries POSIX permission bits exactly as set",
    PARENT_IS_A_FILE_IS_DISTINGUISHABLE: (
        "opening a path THROUGH a file fails as something other than FileNotFoundError"
    ),
}


def _load_manifest() -> Dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def digest(payload: bytes) -> str:
    """
    The corpus digest rule, in one place because two runtimes implement it.

    CRLF is normalized to LF FIRST. Not a convenience: git rewrites text files
    to CRLF on a Windows checkout under core.autocrlf, so a byte-for-byte
    digest measures which OS ran the checkout rather than whether a case
    changed — and it went red on the Windows lane on 2026-08-18 for exactly
    that reason. Line endings are not content of a JSON case. A scoped
    .gitattributes keeps the working tree LF everywhere as well, but the
    normalization is the CONTRACT, because a vendored copy in another
    repository carries its own checkout rules and cannot inherit ours.

    Args:
        payload: The case file's bytes, exactly as read.

    Returns:
        The lowercase hex sha256 both runtimes must agree on.
    """
    return hashlib.sha256(payload.replace(b"\r\n", b"\n")).hexdigest()


@lru_cache(maxsize=None)
def platform_capabilities() -> frozenset:
    """
    What this machine can actually do, measured once, in a throwaway directory.

    Every probe builds the real thing and looks at what happened. `chmod 000`
    is a no-op for root and only sets a read-only attribute on Windows; POSIX
    mode bits do not survive a round trip on Windows at all; and a path through
    a file may report as merely missing there, which would turn a refusal into
    a blank read. None of that is knowable from a platform string.

    Returns:
        The capability names this machine has.
    """
    found = set()

    with tempfile.TemporaryDirectory() as work:
        root = Path(work)

        denied = root / "denied.json"
        denied.write_text("{}", encoding="utf-8")
        try:
            denied.chmod(0o000)
            try:
                denied.read_bytes()
            except OSError:
                found.add(UNREADABLE_FILES)
        finally:
            denied.chmod(0o600)

        exact = root / "exact.json"
        descriptor = os.open(str(exact), os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(descriptor)
        if stat.S_IMODE(exact.stat().st_mode) == 0o600:
            found.add(POSIX_MODE_BITS)

        blocker = root / "blocker"
        blocker.write_text("a file standing where a directory belongs", encoding="utf-8")
        try:
            (blocker / "child.json").read_bytes()
        except FileNotFoundError:
            # The OS reports the broken tree as a missing file, so no rule that
            # reads missing-as-blank can tell the two apart.
            pass
        except OSError:
            found.add(PARENT_IS_A_FILE_IS_DISTINGUISHABLE)

    return frozenset(found)


def _platform_block(entry: Dict[str, Any]) -> Dict[str, Any]:
    """The case's platform block, or an empty one for the cases that need none."""
    return entry.get("platform", {})


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
            str(path.relative_to(CORPUS)).replace(os.sep, "/"): digest(path.read_bytes())
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

    def test_a_line_ending_is_not_a_case_change(self) -> None:
        """
        The digest rule, pinned rather than trusted.

        A byte digest of a JSON case measures the checkout: git's autocrlf
        rewrites these files to CRLF on Windows, and the manifest went red
        there on 2026-08-18 with nothing wrong. This asserts both halves of the
        rule at once — that a CRLF copy of a real case digests the SAME, and
        that a raw byte hash of it would not, so a normalization quietly
        removed from `digest` cannot pass this test.
        """
        relative, recorded = sorted(_load_manifest()["files"].items())[0]
        as_lf = (CORPUS / relative).read_bytes()
        as_crlf = as_lf.replace(b"\n", b"\r\n")

        assert as_crlf != as_lf, "the sample case has no newlines to convert"
        assert digest(as_lf) == recorded
        assert digest(as_crlf) == recorded
        assert hashlib.sha256(as_crlf).hexdigest() != recorded

    def test_a_platform_sensitive_expectation_declares_itself(self) -> None:
        """
        The guard that keeps `expect_without` from being optional in practice.

        `mode` is the one expectation that cannot hold everywhere — Windows has
        no 0600 — so a case carrying it MUST say what happens where the bits do
        not survive. Without this, the fix for one case would leave the next
        one to be found by CI on a platform nobody runs locally.
        """
        for entry in CASES:
            carries_mode = "mode" in entry["expect"] or any(
                "mode" in override for override in entry.get("expect_by_runtime", {}).values()
            )
            if not carries_mode:
                continue

            without = _platform_block(entry).get("expect_without", {})
            assert POSIX_MODE_BITS in without, (
                f"{entry['id']} expects a file mode but never says what a platform "
                f"without POSIX mode bits should expect"
            )

    def test_a_case_that_cannot_be_built_here_is_skipped_and_never_passed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        The skip path, exercised on a machine that does not need it.

        Deleting the whole verify-then-skip block survived a mutation pass on
        this POSIX box, and for an honest reason: every capability is present
        here, so the block never runs and nothing could notice it gone. The
        mutation would only bite on Windows or as root — which is to say, on
        the machines nobody develops on. So the capabilities are taken away by
        hand and the skip is required to happen.

        SKIPPED, not passed, is the whole point. A case whose starting state
        could not be constructed has measured the harness, and reporting that
        as a pass is how a corpus quietly stops being a corpus.
        """
        needy = [entry for entry in CASES if _platform_block(entry).get("requires")]
        assert needy, "no case declares a required capability — this guard watches nothing"

        monkeypatch.setattr(
            "aipass.api.tests.test_settings_conformance.platform_capabilities",
            lambda: frozenset(),
        )

        with pytest.raises(pytest.skip.Exception) as skipped:
            test_the_settings_doors_satisfy_the_shared_corpus(needy[0], tmp_path)

        assert needy[0]["id"] in str(skipped.value)
        assert "cannot host the case" in str(skipped.value)

    def test_a_posix_machine_measures_every_capability(self) -> None:
        """
        The counterpart to verify-then-skip, and the reason it is not a hole.

        A capability probe that stops finding things does not fail — it turns
        cases into skips, which read as green. So on the platform where all
        three capabilities genuinely exist, their absence is an ERROR here. Root
        is excluded because root really does read a mode-000 file, which is the
        capability being absent for a true reason rather than a broken probe.
        """
        if os.name != "posix":
            pytest.skip("this guard is about the platform that has all three")
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            pytest.skip("root reads everything; unreadable_files is legitimately absent")

        assert platform_capabilities() == frozenset(CAPABILITY_MEANINGS)

    def test_every_capability_a_case_names_is_one_this_runner_measures(self) -> None:
        """
        A typo in a capability name would otherwise skip a case forever, silently.

        Both directions are checked: what a case REQUIRES and what it declares
        an expectation for.
        """
        for entry in CASES:
            platform = _platform_block(entry)
            named = set(platform.get("requires", [])) | set(platform.get("expect_without", {}))

            unknown = named - set(CAPABILITY_MEANINGS)
            assert not unknown, f"{entry['id']} names capabilities nobody measures: {sorted(unknown)}"


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
    """
    The case's expectation, with the runtime's and the platform's overrides folded in.

    Order matters and is stated here because it is a contract a second runner
    has to reproduce: `expect`, then `expect_by_runtime[<runtime>]`, then one
    `expect_without[<capability>]` block for every capability this machine
    LACKS. The platform layer goes last because it is the most specific — it
    describes a machine, not an implementation.

    Args:
        entry: One case.

    Returns:
        The expectation to assert here, on this machine.
    """
    expected = dict(entry["expect"])
    expected.update(entry.get("expect_by_runtime", {}).get(RUNTIME, {}))

    have = platform_capabilities()
    for capability, override in sorted(_platform_block(entry).get("expect_without", {}).items()):
        if capability in have:
            continue
        override = dict(override)
        for key in override.pop("drop", []):
            expected.pop(key, None)
        expected.update(override)

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

    missing = sorted(set(_platform_block(entry).get("requires", [])) - platform_capabilities())
    if missing:
        # Verify-then-skip. The state this case needs cannot be BUILT here, so
        # running it would prove something about the harness, not the door. It
        # is never passed silently — the capability is named, and so is what it
        # would have meant.
        pytest.skip(
            f"{entry['id']}: this machine cannot host the case — "
            + "; ".join(f"{name} ({CAPABILITY_MEANINGS[name]})" for name in missing)
        )

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
