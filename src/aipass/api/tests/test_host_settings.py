# =================== AIPass ====================
# Name: test_host_settings.py
# Description: Host API settings handler — the desktop's gear rules, held in Python
# Version: 1.0.0
# Created: 2026-08-16
# Modified: 2026-08-16
# =============================================

"""
The settings lane mirrors @baud's settings.rs, and these tests pin the rules
that make the two faces write one truth: surgical three-state patches, the
never-treat-unreadable-as-blank refusal, and the idempotent mute flag.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.api.apps.handlers.host import settings as host_settings

# Asked of @hooks' own module in a child process: where WOULD the flag go under
# the environment this test just built? The answer has to come from there — a
# copy of the rule computed here would agree with itself and prove nothing.
WHERE_THE_FLAG_LIVES = "from aipass.hooks.apps import sound; print(sound.MUTE_FLAG)"


def _where_the_door_would_write() -> Path:
    """
    Ask @hooks' own module, in a child that inherits this process's environment.

    The answer has to come from THERE. Computing the path here would agree with
    itself no matter what the environment says, which is precisely the failure
    this exists to catch: `tempfile.gettempdir()` falls back to the machine's
    real temp directory when TMPDIR points at a directory that does not exist,
    silently, so a redirect can look applied and not be.

    Returns:
        The path the door's own process would write the mute flag to.
    """
    child = subprocess.run(
        [sys.executable, "-c", WHERE_THE_FLAG_LIVES],
        capture_output=True,
        text=True,
        timeout=host_settings.HOOKS_SOUND_TIMEOUT_SECONDS,
    )

    assert child.returncode == 0, child.stderr
    return Path(child.stdout.strip())


def _fingerprint(path: Path) -> tuple:
    """
    Enough of a file to notice it was touched at all.

    Args:
        path: The operator's real mute flag.

    Returns:
        (exists, size, mtime_ns) — absent files fingerprint as absent rather
        than raising, because the flag not existing IS a legitimate state.
    """
    if not path.exists():
        return (False, None, None)

    stat = path.stat()
    return (True, stat.st_size, stat.st_mtime_ns)


def _ok() -> subprocess.CompletedProcess:
    """What the door returns when it is happy — and, as it turns out, also when
    it has no idea what you asked for. See the test that pins that."""
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


@pytest.fixture
def muted_elsewhere(tmp_path, monkeypatch):
    """
    @hooks' flag, relocated into this test's own directory, plus a stand-in for
    the door that moves it.

    The machine's real flag is the OPERATOR's — muting a sleeping developer's
    fleet from a test suite is not a side effect anyone signed up for, and this
    file's tests run on every suite. So the owner's own constant is redirected
    and the subprocess is replaced by one that does to that file exactly what
    the real command does to the real one.

    Returns:
        (flag, calls) — the relocated flag, and every command the lane sent.
    """
    flag = tmp_path / "aipass-hooks-muted"
    calls: list = []

    def fake_door(command, **kwargs):
        calls.append(list(command))
        verb = command[-1]
        if verb == "off":
            flag.touch()
        elif verb == "on":
            flag.unlink(missing_ok=True)
        return _ok()

    monkeypatch.setattr(host_settings.hooks_sound, "MUTE_FLAG", flag)
    monkeypatch.setattr(host_settings.subprocess, "run", fake_door)
    return flag, calls


def agent_file(root):
    return root / ".claude" / "settings.local.json"


class TestAgentSettings:
    """The surgical door: three owned keys, everything else survives."""

    def test_a_fresh_branch_reads_all_null(self, tmp_path) -> None:
        """No settings file is not a fault — every dial sits at absent."""
        assert host_settings.read_agent_settings(tmp_path) == {
            "model": None,
            "auto_compact_enabled": None,
            "auto_compact_window": None,
        }

    def test_a_patch_sets_claudes_own_spelling_and_preserves_strangers(self, tmp_path) -> None:
        """camelCase on disk, snake_case in the API — and the operator's other
        keys come back byte-identical, which is the whole surgical promise."""
        path = agent_file(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"permissions": {"allow": ["Bash"]}, "model": "opus"}))

        view = host_settings.write_agent_settings(tmp_path, {"model": "sonnet", "auto_compact_window": 350_000})

        document = json.loads(path.read_text())
        assert document["model"] == "sonnet"
        assert document["autoCompactWindow"] == 350_000
        assert document["permissions"] == {"allow": ["Bash"]}
        assert view["model"] == "sonnet"
        assert view["auto_compact_window"] == 350_000

    def test_null_removes_and_absent_touches_nothing(self, tmp_path) -> None:
        """The three-state contract in one write."""
        path = agent_file(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"model": "opus", "autoCompactEnabled": True}))

        view = host_settings.write_agent_settings(tmp_path, {"model": None})

        document = json.loads(path.read_text())
        assert "model" not in document
        assert document["autoCompactEnabled"] is True
        assert view == {"model": None, "auto_compact_enabled": True, "auto_compact_window": None}

    def test_a_corrupt_file_refuses_both_directions_and_stays_corrupt(self, tmp_path) -> None:
        """Unreadable must never be treated as blank: a write that 'recovered'
        a corrupt file to {} would destroy whatever the operator had there."""
        path = agent_file(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text("{not json")

        with pytest.raises(host_settings.SettingsRefused):
            host_settings.read_agent_settings(tmp_path)
        with pytest.raises(host_settings.SettingsRefused):
            host_settings.write_agent_settings(tmp_path, {"model": "opus"})
        assert path.read_text() == "{not json"

    def test_wrong_typed_values_read_as_null(self, tmp_path) -> None:
        """A dial cannot show a value it does not understand — including the
        bool-is-an-int trap, which is why the window check excludes bools."""
        path = agent_file(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"model": 7, "autoCompactEnabled": "yes", "autoCompactWindow": True}))

        assert host_settings.read_agent_settings(tmp_path) == {
            "model": None,
            "auto_compact_enabled": None,
            "auto_compact_window": None,
        }

    def test_the_allowlist_is_the_contract(self, tmp_path) -> None:
        """Unknown fields refuse — the door owns three keys and no more."""
        with pytest.raises(host_settings.SettingsRefused):
            host_settings.write_agent_settings(tmp_path, {"permissions": {}})
        with pytest.raises(host_settings.SettingsRefused):
            host_settings.write_agent_settings(tmp_path, {"auto_compact_window": True})
        with pytest.raises(host_settings.SettingsRefused):
            host_settings.write_agent_settings(tmp_path, {"auto_compact_window": -5})
        assert not agent_file(tmp_path).exists()


class TestBaudSettings:
    """The opaque document: shallow merge, null removes, nested replaces."""

    def test_merge_keeps_null_removes_and_replaces_subtrees(self, tmp_path) -> None:
        path = tmp_path / ".aipass" / "baud.settings.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"startup_agent": "devpulse", "poll_interval_ms": 5000, "extra": {"a": 1}}))

        result = host_settings.write_baud_settings(
            tmp_path, {"startup_agent": None, "bell_sound": True, "extra": {"b": 2}}
        )

        assert "startup_agent" not in result
        assert result["poll_interval_ms"] == 5000
        assert result["bell_sound"] is True
        # Replaced whole, never merged into — a caller says what a subtree IS.
        assert result["extra"] == {"b": 2}
        assert json.loads(path.read_text()) == result


class TestHooksSound:
    """
    The mute flag: @hooks' file, @hooks' door, idempotent both ways.

    The CONTRACT here is unchanged from the hand-written version — sounds are
    active when the flag is absent, and both directions of the flip are no-ops
    when they are already true, because two faces may race on the same file.
    Only the mechanism moved: this lane no longer knows where that file lives
    or how to write it.
    """

    def test_this_module_does_not_know_where_the_mute_flag_lives(self) -> None:
        """
        The boundary, stated as a fact about this file's source.

        Patrick's ruling: api is api. The flag's location is @hooks' knowledge —
        it is declared once, at aipass/hooks/apps/sound.py, and a second copy
        here is a second truth that drifts the first time they move it. This
        lane had one: a module constant holding the file name and a helper
        rebuilding the path beside it, both written before the door existed.
        """
        source = Path(host_settings.__file__).read_text(encoding="utf-8")

        assert "aipass-hooks-muted" not in source
        assert "hooks_mute_flag" not in source

    def test_the_flip_goes_through_the_hooks_door(self, muted_elsewhere) -> None:
        """
        The WRITE is the registered command, not a touch and an unlink.

        'drone @hooks hooksound on|off' has existed the whole time — this
        module's own docstring named it while bypassing it. What travels is the
        command; nothing here opens the file for writing.
        """
        flag, calls = muted_elsewhere

        host_settings.hooks_sound_set(False)
        host_settings.hooks_sound_set(True)

        assert [call[-2:] for call in calls] == [["hooksound", "off"], ["hooksound", "on"]]
        assert all(call[:2] == ["drone", "@hooks"] for call in calls)

    def test_active_means_no_flag_and_flips_are_idempotent(self, muted_elsewhere) -> None:
        """
        The behaviour that was true before and is still true — same assertions,
        new mechanism underneath.
        """
        flag, _ = muted_elsewhere

        assert host_settings.hooks_sound_get() is True
        assert host_settings.hooks_sound_set(False) is False
        assert host_settings.hooks_sound_set(False) is False
        assert flag.exists()
        assert host_settings.hooks_sound_set(True) is True
        assert host_settings.hooks_sound_set(True) is True
        assert not flag.exists()

    def test_a_door_that_answers_but_does_not_flip_is_a_failure(self, muted_elsewhere) -> None:
        """
        MEASURED, and the reason this lane re-reads instead of trusting a zero.

        'drone @hooks hooksound sideways' prints 'Unknown command' and exits
        ZERO. So does a real flip. An exit code is therefore not evidence that
        anything moved, and a lane that returned success on it would tell a
        face the sound was muted while the fleet kept ringing. The flag itself
        is the only witness, so it is read back and disagreement is a refusal.
        """
        flag, _ = muted_elsewhere
        host_settings.hooks_sound_set(False)

        # The door answers, exits zero, and does nothing at all.
        with patch.object(host_settings.subprocess, "run", return_value=_ok()):
            with pytest.raises(host_settings.SettingsUnavailable) as refusal:
                host_settings.hooks_sound_set(True)

        assert "hook sounds" in str(refusal.value).lower()

    def test_a_door_that_cannot_be_reached_refuses_rather_than_writing_the_file(self, muted_elsewhere) -> None:
        """
        No silent fallback to hand-writing. If the door is gone, say so — the
        one thing this lane must never do is quietly become the thing it
        replaced.
        """
        flag, _ = muted_elsewhere

        with patch.object(host_settings.subprocess, "run", side_effect=FileNotFoundError("drone")):
            with pytest.raises(host_settings.SettingsUnavailable):
                host_settings.hooks_sound_set(False)

        assert not flag.exists()

    def test_the_door_really_answers_to_this_command(self, tmp_path, monkeypatch) -> None:
        """
        NOT hermetic, on purpose, and the only test here that is not.

        Every other test in this class mocks the subprocess, which pins what
        this lane SENDS and nothing about whether anyone is listening. If
        @hooks renames the verb tomorrow, those tests all still pass and the
        phone's toggle silently stops working. This one runs the real command.

        KEPT DELIBERATELY, with both of its costs paid rather than argued away.

        COST ONE — it needs a live @hooks, and CI has none. The registry is
        machine-managed and gitignored, so on a fresh runner drone answers
        "Branch '@hooks' not found in registry" and exits 1; this test was red
        on the Windows and ubuntu lanes for exactly that reason. The obvious
        cure does not work here: a hand-built registry pointing at the real
        @hooks is silently DROPPED by drone's own _validate_branch_path, which
        discards any branch whose path escapes the registry file's directory —
        measured, the branches map comes back empty. A registry in tmp can only
        point at a tree in tmp, and a tmp tree is not the door this test exists
        to reach. So it asks the door read-only first and SKIPS when there is
        nobody home. A skip is honest; a mock would be this test pretending to
        be the four above it.

        COST TWO — it flips a real switch, so it must flip its own. TMPDIR is
        redirected and @hooks' own constant with it, and neither is TRUSTED:
        the redirect is verified in @hooks' own module, in a child process,
        BEFORE anything is written. That guard is not hypothetical. While
        investigating this defect I redirected TMPDIR to a directory that did
        not exist yet, tempfile silently fell back to /tmp, and the probe wrote
        to the operator's real flag. The verdict was unchanged and the mtime
        was not, which is precisely what a fingerprint catches and a "did it
        work" assertion does not.
        """
        # @hooks' own declaration, read before it is redirected. Naming the
        # path here instead would be the second copy of a truth this class
        # already refuses to keep.
        operator_flag = Path(str(host_settings.hooks_sound.MUTE_FLAG))
        before = _fingerprint(operator_flag)

        flag = tmp_path / operator_flag.name
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        monkeypatch.setattr(host_settings.hooks_sound, "MUTE_FLAG", flag)

        listening = subprocess.run(
            list(host_settings.HOOKS_SOUND_DOOR),
            capture_output=True,
            text=True,
            timeout=host_settings.HOOKS_SOUND_TIMEOUT_SECONDS,
        )
        if listening.returncode != 0:
            pytest.skip(
                "no live @hooks on this machine — the door said: "
                f"{(listening.stderr or listening.stdout).strip()[:120]}"
            )

        # Where @hooks' OWN module says it would write, before a byte moves.
        would_write = _where_the_door_would_write()
        assert would_write == flag, (
            "the redirect did not reach the door's own process — refusing to "
            f"flip anything. It would have written {would_write}"
        )

        try:
            assert host_settings.hooks_sound_set(False) is False
            assert flag.exists()
            assert host_settings.hooks_sound_set(True) is True
            assert not flag.exists()
        finally:
            # The operator's switch, unmoved — existence, size AND mtime, so a
            # rewrite that lands on the same state still fails this.
            assert _fingerprint(operator_flag) == before


class TestTheGuardsOnTheLiveDoorTest:
    """
    Two hermetic tests about the ONE non-hermetic test above it.

    A deliberate live-door pin is only defensible while its isolation is
    verified rather than assumed, and both of these exist because the assumption
    failed in practice: while investigating this defect I pointed TMPDIR at a
    directory I had not created yet, tempfile fell back to the machine's real
    temp directory, and a probe wrote to the operator's own flag. The verdict was
    unchanged and the mtime was not.
    """

    def test_the_redirect_check_asks_the_door_rather_than_computing_the_answer(self, tmp_path, monkeypatch) -> None:
        """
        The failure mode, reproduced, with no live @hooks needed.

        TMPDIR points at a directory that does not exist. A guard that COMPUTED
        the expected path from the environment would answer inside it and be
        satisfied; the door's own module answers somewhere else entirely,
        because gettempdir falls back and says nothing. That difference is the
        guard, so it is asserted here rather than trusted.
        """
        doomed = tmp_path / "never-created"
        monkeypatch.setenv("TMPDIR", str(doomed))

        would_write = _where_the_door_would_write()

        assert doomed not in would_write.parents, (
            "tempfile no longer falls back on a missing TMPDIR — good news, but "
            "the live test's guard was written for a platform where it does"
        )

    def test_the_fingerprint_notices_a_rewrite_that_changed_nothing(self, tmp_path) -> None:
        """
        Why the operator's flag is fingerprinted with its mtime and not just its state.

        Muting an already-muted fleet is idempotent: the file is there before and
        there after, same zero bytes. A check on existence alone would call that
        untouched. The flag's whole job is to be a marker, so the honest question
        is whether anything wrote to it at all.
        """
        flag = tmp_path / "aipass-hooks-muted"
        flag.touch()
        before = _fingerprint(flag)

        # An idempotent re-write: same path, same (empty) content, later clock.
        flag.touch()
        os.utime(flag, ns=(before[2] + 1_000_000_000, before[2] + 1_000_000_000))

        assert flag.exists()
        assert _fingerprint(flag) != before


class TestAnUnreadableFileIsNeverBlank:
    """
    The module docstring's own rule, now held all the way down.

    read_object used to answer {} for EVERY OSError. Two very different
    situations were arriving at the same answer: a branch that has no settings
    yet, and a settings file this process is not allowed to read. The first is
    ordinary; the second is a fault, and reading it as blank invites a patch to
    write a fresh document over settings that were only ever unreadable.
    """

    def test_a_branch_with_no_settings_still_reads_as_blank(self, tmp_path) -> None:
        """The no-fault case, unchanged: absent means absent."""
        assert host_settings.read_object(tmp_path / "settings.local.json") == {}

    def test_a_missing_parent_directory_also_reads_as_blank(self, tmp_path) -> None:
        """Nothing on the way to the file exists either — still just absent."""
        assert host_settings.read_object(tmp_path / "nope" / "settings.local.json") == {}

    def test_a_directory_where_the_file_should_be_is_a_fault(self, tmp_path) -> None:
        """Something IS there and it cannot be read as settings. Say so."""
        occupied = tmp_path / "settings.local.json"
        occupied.mkdir()

        with pytest.raises(host_settings.SettingsUnavailable) as refusal:
            host_settings.read_object(occupied)

        assert "settings.local.json" in str(refusal.value)

    @pytest.mark.skipif(os.geteuid() == 0, reason="root reads everything; the mode says nothing to it")
    def test_a_file_we_may_not_read_is_a_fault_not_a_blank(self, tmp_path) -> None:
        """The one that would have cost real settings: unreadable, not empty."""
        secret = tmp_path / "settings.local.json"
        secret.write_text(json.dumps({"model": "opus"}), encoding="utf-8")
        secret.chmod(0o000)

        try:
            with pytest.raises(host_settings.SettingsUnavailable):
                host_settings.read_object(secret)
        finally:
            secret.chmod(0o600)


class TestAFailedWriteLeavesNothingBehind:
    """The staged file is cleanup, and cleanup that fails is still reported."""

    def test_the_staged_file_does_not_survive_a_failed_write(self, tmp_path) -> None:
        path = tmp_path / "settings.local.json"

        with pytest.raises(TypeError):
            host_settings.write_atomically(path, {"unserialisable": object()})

        assert not path.exists()
        assert list(tmp_path.iterdir()) == []

    def test_a_cleanup_that_itself_fails_is_logged_not_swallowed(self, tmp_path, monkeypatch) -> None:
        """
        Losing the temp file is survivable; losing the FACT is not. The original
        failure still travels — cleanup never overwrites the reason.
        """
        path = tmp_path / "settings.local.json"
        complaints = []

        def refuse_to_unlink(_target):
            raise OSError("the staged file cannot be removed either")

        monkeypatch.setattr(host_settings.os, "unlink", refuse_to_unlink)
        monkeypatch.setattr(
            host_settings.logger, "warning", lambda *a, **k: complaints.append(a[0] % a[1:] if len(a) > 1 else a[0])
        )

        with pytest.raises(TypeError):
            host_settings.write_atomically(path, {"unserialisable": object()})

        assert complaints, "a failed cleanup left no trace at all"
        assert any("staged" in line for line in complaints)


class TestTheCorpusForcedTwoFixes:
    """
    Both ruled by the conformance corpus (FPLAN-0438 R3), both red first.

    @baud measured every divergence between the two settings implementations
    against real rust, and the strict side wins by doctrine. On these two, rust
    was the strict side and this lane was the lenient one.
    """

    def test_a_parent_that_is_a_FILE_is_a_fault_not_a_fresh_branch(self, tmp_path) -> None:
        """
        Divergence 2. A missing directory on the way to the file means nobody
        has written settings yet. A FILE standing where a directory belongs
        means the tree is broken, and reading that as 'no settings yet' invites
        a patch to write a document into a path that cannot hold one.
        """
        blocking = tmp_path / "claude-settings"
        blocking.write_text("I am a file, not a directory", encoding="utf-8")

        with pytest.raises(host_settings.SettingsUnavailable):
            host_settings.read_object(blocking / "settings.local.json")

    def test_a_negative_window_reads_as_null_not_as_a_negative(self, tmp_path) -> None:
        """
        Divergence 5, and the one where rust was already right: their as_u64
        declines a negative outright, while this view checked only that the
        value was an int. A dial cannot show minus five thousand tokens, and
        handing it to the face as a number says it can.
        """
        view = host_settings.agent_settings_view({"autoCompactWindow": -5})

        assert view["auto_compact_window"] is None

    def test_a_window_of_zero_still_reads_as_zero(self, tmp_path) -> None:
        """
        The boundary the fix must not overshoot. Zero is a representable u64,
        so a file containing it reads back honestly — the refusal on zero
        belongs to the WRITE path, where the value is being created, not to the
        read that reports what is already there.
        """
        view = host_settings.agent_settings_view({"autoCompactWindow": 0})

        assert view["auto_compact_window"] == 0
