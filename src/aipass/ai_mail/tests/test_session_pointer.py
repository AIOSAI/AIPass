# =================== AIPass ====================
# Name: test_session_pointer.py
# Description: Tests for the durable per-branch session pointer
# Version: 1.2.0
# Created: 2026-08-20
# Modified: 2026-10-28
# =============================================

"""Tests for apps/handlers/dispatch/session_pointer.py -- encoding, round trip, atomicity, resume."""

# Everything here runs against tmp_path. ``Path.home`` is monkeypatched wherever a
# test needs a transcript to exist, so no test can read or create anything under
# the real ``~/.claude`` or inside a live branch.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — _BYTES_PER_MB, the internal MB conversion factor

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import aipass.ai_mail.apps.handlers.dispatch.session_pointer as mod
from aipass.ai_mail.apps.handlers.dispatch.session_pointer import (
    mint_session_id,
    pointer_path,
    read_pointer,
    resolve_resume_target,
    transcript_dir,
    transcript_file,
    write_pointer,
)


@pytest.fixture(autouse=True)
def _suppress_logger(monkeypatch):
    """Suppress logger output during tests."""
    monkeypatch.setattr(mod, "logger", MagicMock())


@pytest.fixture(autouse=True)
def _suppress_log_operation(monkeypatch):
    """Prevent json_handler.log_operation from touching real files."""
    monkeypatch.setattr(mod, "json_handler", MagicMock())


@pytest.fixture
def branch(tmp_path):
    """A branch directory with no pointer yet."""
    path = tmp_path / "branch"
    path.mkdir()
    return path


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Point the home directory at tmp_path so transcript paths land under the sandbox."""
    # Path.home() reads HOME on POSIX and USERPROFILE on Windows: set both, leave pathlib alone.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert Path.home() == home, "this platform must answer Path.home() from the environment"
    return home


def _make_transcript(branch_path: Path, session_id: str, size_bytes: int = 64) -> Path:
    """Create a fake transcript for `session_id` under the (faked) home."""
    target = transcript_file(branch_path, session_id)
    assert target is not None, "fake_home names the home directory"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x" * size_bytes)
    return target


def test_mint_session_id_is_a_uuid_string():
    """Callers pass this straight to --session-id, so the shape is a contract."""
    import uuid

    minted = mint_session_id()
    assert isinstance(minted, str)
    assert uuid.UUID(minted)


def test_mint_session_id_is_unique():
    assert mint_session_id() != mint_session_id()


def test_transcript_dir_encodes_separators_underscores_and_dots(fake_home):
    """/ and _ and . all collapse to '-' -- the rule Claude itself uses."""
    result = transcript_dir("/srv/branches/my_repo/src.pkg")
    assert result is not None
    encoded = result.name
    assert encoded == "-srv-branches-my-repo-src-pkg"
    assert "_" not in encoded
    assert "." not in encoded
    assert "/" not in encoded


def test_transcript_dir_encodes_windows_paths(fake_home):
    """Backslash and drive colon collapse too: C:\\repo\\AIPass -> C--repo-AIPass."""
    result = transcript_dir("C:\\repo\\AIPass")
    assert result is not None and result.name == "C--repo-AIPass"


def test_transcript_dir_encodes_every_non_alphanumeric_as_claude_does(fake_home):
    """Claude Code encoded these characters this way on a live run, 2026-10-28; the old rule kept the space and +@()."""
    result = transcript_dir("/srv/aimail probe+x@y(z)_w.v")
    assert result is not None and result.name == "-srv-aimail-probe-x-y-z--w-v"


def test_transcript_dir_lives_under_claude_projects(fake_home, tmp_path):
    result = transcript_dir(str(tmp_path / "some" / "branch"))
    assert result is not None and result.parent == fake_home / ".claude" / "projects"


def test_transcript_dir_accepts_a_path_object(fake_home, tmp_path):
    sample = tmp_path / "some" / "branch"
    assert transcript_dir(sample) == transcript_dir(str(sample))


def test_transcript_file_appends_the_jsonl_name(fake_home, tmp_path):
    sample = str(tmp_path / "some" / "branch")
    result = transcript_file(sample, "abc-123")
    assert result is not None and result.name == "abc-123.jsonl"
    assert result.parent == transcript_dir(sample)


def test_pointer_path_sits_beside_the_dispatch_lock(branch):
    assert pointer_path(branch) == branch / ".ai_mail.local" / "session.json"


def test_round_trip_write_then_read(branch):
    assert write_pointer(branch, "sess-1", "wake") is True
    data = read_pointer(branch)
    assert data is not None
    assert data["session_id"] == "sess-1"
    assert data["set_by"] == "wake"
    assert data["cwd"] == str(branch.resolve())
    assert data["set_at"]


def test_write_pointer_creates_the_local_dir(tmp_path):
    """A branch that has never dispatched has no .ai_mail.local yet."""
    fresh = tmp_path / "never-dispatched"
    fresh.mkdir()
    assert not (fresh / ".ai_mail.local").exists()
    assert write_pointer(fresh, "sess-1", "wake") is True
    assert pointer_path(fresh).is_file()


def test_write_pointer_set_at_is_timezone_aware(branch):
    """A naive timestamp is unreadable across a DST change."""
    from datetime import datetime

    write_pointer(branch, "sess-1", "wake")
    data = read_pointer(branch)
    assert data is not None and data["session_id"] == "sess-1"
    stamp = datetime.fromisoformat(data["set_at"])
    assert stamp.tzinfo is not None


def test_write_pointer_overwrites_the_previous_session(branch):
    write_pointer(branch, "old", "wake")
    write_pointer(branch, "new", "dispatch_monitor")
    data = read_pointer(branch)
    assert data is not None
    assert data["session_id"] == "new"
    assert data["set_by"] == "dispatch_monitor"


def test_write_pointer_leaves_no_temp_files_behind(branch):
    write_pointer(branch, "sess-1", "wake")
    leftovers = [p.name for p in (branch / ".ai_mail.local").iterdir() if p.name != "session.json"]
    assert leftovers == []


def test_read_pointer_none_when_file_missing(branch):
    assert read_pointer(branch) is None


def test_read_pointer_none_when_dir_missing(tmp_path):
    assert read_pointer(tmp_path / "no-such-branch") is None


def test_read_pointer_none_on_malformed_json(branch):
    path = pointer_path(branch)
    path.parent.mkdir(parents=True)
    path.write_text("{not json at all", encoding="utf-8")
    assert read_pointer(branch) is None


def test_read_pointer_none_when_json_is_a_list(branch):
    path = pointer_path(branch)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps([{"session_id": "sess-1"}]), encoding="utf-8")
    assert read_pointer(branch) is None


def test_read_pointer_none_when_session_id_absent(branch):
    path = pointer_path(branch)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"set_by": "wake"}), encoding="utf-8")
    assert read_pointer(branch) is None


def test_read_pointer_none_when_session_id_blank(branch):
    path = pointer_path(branch)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"session_id": "   "}), encoding="utf-8")
    assert read_pointer(branch) is None


def test_read_pointer_none_when_session_id_is_not_a_string(branch):
    path = pointer_path(branch)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"session_id": 12345}), encoding="utf-8")
    assert read_pointer(branch) is None


def test_read_pointer_none_on_oserror(branch, monkeypatch):
    """An unreadable pointer degrades to no pointer -- it never raises."""
    write_pointer(branch, "sess-1", "wake")

    def _boom(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_text", _boom)
    assert read_pointer(branch) is None


def test_write_pointer_returns_false_on_oserror(branch, monkeypatch):
    """Permission denied is a False, never an exception."""

    def _boom(*args, **kwargs):
        raise PermissionError("read-only filesystem")

    monkeypatch.setattr(mod.tempfile, "mkstemp", _boom)
    assert write_pointer(branch, "sess-1", "wake") is False


def test_write_pointer_returns_false_when_mkdir_fails(branch, monkeypatch):
    def _boom(*args, **kwargs):
        raise OSError("cannot create directory")

    monkeypatch.setattr(Path, "mkdir", _boom)
    assert write_pointer(branch, "sess-1", "wake") is False


def test_write_pointer_survives_a_failing_op_log(branch, monkeypatch):
    """The audit trail is worth having, never worth failing a dispatch over."""
    broken = MagicMock()
    broken.log_operation.side_effect = OSError("op log unwritable")
    monkeypatch.setattr(mod, "json_handler", broken)

    assert write_pointer(branch, "sess-1", "wake") is True
    data = read_pointer(branch)
    assert data is not None
    assert data["session_id"] == "sess-1"


def test_failed_write_does_not_corrupt_an_existing_pointer(branch, monkeypatch):
    """Atomicity: a write that dies mid-flight leaves the OLD value readable."""
    assert write_pointer(branch, "good-session", "wake") is True

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(mod.os, "replace", _boom)
    assert write_pointer(branch, "doomed-session", "wake") is False

    data = read_pointer(branch)
    assert data is not None
    assert data["session_id"] == "good-session"


def test_failed_write_cleans_up_its_temp_file(branch, monkeypatch):
    """A failed replace must not litter .ai_mail.local with scratch files."""
    write_pointer(branch, "good-session", "wake")

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(mod.os, "replace", _boom)
    write_pointer(branch, "doomed-session", "wake")

    leftovers = [p.name for p in (branch / ".ai_mail.local").iterdir() if p.name != "session.json"]
    assert leftovers == []


def test_resolve_returns_none_with_no_pointer(branch, fake_home):
    session_id, reason = resolve_resume_target(branch)
    assert session_id is None
    assert "pointer" in reason
    assert "-c" in reason


def test_resolve_returns_the_id_when_pointer_and_transcript_are_valid(branch, fake_home):
    write_pointer(branch, "sess-live", "wake")
    _make_transcript(branch, "sess-live")

    session_id, reason = resolve_resume_target(branch)
    assert session_id == "sess-live"
    assert "sess-live" in reason
    assert "valid" in reason


def test_resolve_returns_none_when_transcript_missing(branch, fake_home):
    """The pointer is fine, but --resume on a missing transcript kills a dispatch."""
    write_pointer(branch, "sess-ghost", "wake")

    session_id, reason = resolve_resume_target(branch)
    assert session_id is None
    assert "transcript" in reason
    assert "sess-ghost" in reason


def test_resolve_returns_none_on_cwd_mismatch(branch, fake_home, tmp_path):
    """A moved or copied branch inherits a pointer aimed at the original."""
    write_pointer(branch, "sess-live", "wake")
    _make_transcript(branch, "sess-live")

    moved = tmp_path / "moved-branch"
    moved.mkdir()
    (moved / ".ai_mail.local").mkdir()
    # Straight copy of the pointer -- exactly what `cp -r` of a branch produces.
    (moved / ".ai_mail.local" / "session.json").write_text(
        pointer_path(branch).read_text(encoding="utf-8"), encoding="utf-8"
    )

    session_id, reason = resolve_resume_target(moved)
    assert session_id is None
    assert "cwd" in reason
    assert str(branch.resolve()) in reason


def test_resolve_returns_none_when_pointer_json_is_broken(branch, fake_home):
    path = pointer_path(branch)
    path.parent.mkdir(parents=True)
    path.write_text("}{", encoding="utf-8")

    session_id, reason = resolve_resume_target(branch)
    assert session_id is None
    assert reason == f"no usable pointer at {pointer_path(branch)} - falling back to -c"


def test_resolve_reason_is_always_populated(branch, fake_home):
    """Every verdict lands in a log line, so no verdict may be silent."""
    for setup in (
        lambda: None,
        lambda: write_pointer(branch, "sess-ghost", "wake"),
        lambda: (write_pointer(branch, "sess-live", "wake"), _make_transcript(branch, "sess-live")),
    ):
        setup()
        _, reason = resolve_resume_target(branch)
        assert isinstance(reason, str) and reason.strip()


def test_resolve_flags_an_oversize_transcript_but_still_resumes(branch, fake_home):
    """Detection only -- rotation is a human decision and is NOT armed here."""
    write_pointer(branch, "sess-big", "wake")
    _make_transcript(branch, "sess-big", size_bytes=3 * 1024 * 1024)

    session_id, reason = resolve_resume_target(branch, max_transcript_mb=1.0)
    assert session_id == "sess-big"
    assert "rotation" in reason
    assert "3.0MB" in reason
    assert "1.0MB" in reason


def test_resolve_does_not_flag_a_transcript_under_the_threshold(branch, fake_home):
    write_pointer(branch, "sess-small", "wake")
    _make_transcript(branch, "sess-small", size_bytes=1024)

    session_id, reason = resolve_resume_target(branch, max_transcript_mb=100.0)
    assert session_id == "sess-small"
    assert "rotation" not in reason


def test_resolve_ignores_size_when_no_threshold_given(branch, fake_home):
    write_pointer(branch, "sess-big", "wake")
    _make_transcript(branch, "sess-big", size_bytes=5 * 1024 * 1024)

    session_id, reason = resolve_resume_target(branch)
    assert session_id == "sess-big"
    assert "rotation" not in reason


def test_resolve_still_resumes_when_the_size_check_itself_fails(branch, fake_home, monkeypatch):
    """A stat failure must not cost the branch its session."""
    write_pointer(branch, "sess-live", "wake")
    _make_transcript(branch, "sess-live")

    real_stat = Path.stat
    real_is_file = Path.is_file

    def _boom_stat(self, *args, **kwargs):
        if self.suffix == ".jsonl":
            raise OSError("stat failed")
        return real_stat(self, *args, **kwargs)

    def _is_file(self, *args, **kwargs):
        # Only the SIZE read fails; the existence check must still pass.
        if self.suffix == ".jsonl":
            return True
        return real_is_file(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_file", _is_file)
    monkeypatch.setattr(Path, "stat", _boom_stat)
    session_id, reason = resolve_resume_target(branch, max_transcript_mb=1.0)
    assert session_id == "sess-live"
    assert "size unknown" in reason


def test_resolve_never_raises_on_a_nonsense_argument():
    """The dispatch hot path survives a caller's mistake."""
    session_id, reason = resolve_resume_target(object())  # type: ignore[arg-type]
    assert session_id is None
    # The error type is the interpreter's to choose, so only the form is pinned.
    assert reason.startswith("pointer unreadable (")
    assert reason.endswith(" - falling back to -c")


def test_resolve_survives_an_unstattable_transcript_dir(branch, fake_home, monkeypatch):
    write_pointer(branch, "sess-live", "wake")

    def _boom(self, *args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "is_file", _boom)
    session_id, reason = resolve_resume_target(branch)
    assert session_id is None
    assert "transcript" in reason


def test_write_then_read_survives_a_session_id_with_odd_characters(branch):
    """Whatever the CLI hands back round-trips intact -- we never reformat it."""
    weird = "a-b_c.D-0123456789"
    assert write_pointer(branch, weird, "manual") is True
    data = read_pointer(branch)
    assert data is not None
    assert data["session_id"] == weird


def test_pointer_file_is_valid_json_on_disk(branch):
    """Another tool (or a human with cat) has to be able to read this."""
    write_pointer(branch, "sess-1", "wake")
    raw = pointer_path(branch).read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert set(parsed) == {"session_id", "set_at", "set_by", "cwd", "provider", *mod.RUN_KEYS}
    assert parsed["provider"] == "claude"
    # Indented, not a blob: one newline after the brace and one after each of the eleven keys.
    assert raw.count("\n") == 12, raw


class TestTheMismatchMessageIsReadableOnBothPlatforms:
    """A mismatch message names both paths as stored: no repr-doubled Windows backslashes."""

    def test_a_windows_pointer_cwd_survives_into_the_message(self, branch, fake_home):
        """The reproduction, run on Linux: pointer cwd is read from JSON verbatim, nothing mocked."""
        windows_cwd = r"C:\Projects\AIPass\src\aipass\ai_mail"
        path = pointer_path(branch)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"session_id": "sess-live", "cwd": windows_cwd, "reason": "wake"}),
            encoding="utf-8",
        )

        _session_id, reason = resolve_resume_target(branch)

        assert "cwd" in reason, "premise: this must be the mismatch verdict"
        assert windows_cwd in reason, (
            "the pointer's own cwd must appear exactly as it is stored, so a human can "
            f"compare it against their directory. Got: {reason}"
        )
        assert "\\\\" not in reason, "no doubled separators - the reader cannot copy those"

    def test_an_empty_cwd_is_still_visible(self, branch, fake_home):
        """What ``!r`` was buying, kept: a blank value must not vanish; the quoting survives, the escaping does not."""
        path = pointer_path(branch)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"session_id": "s", "cwd": "", "reason": "wake"}), encoding="utf-8")

        _session_id, reason = resolve_resume_target(branch)

        assert "''" in reason, f"an empty cwd must still be visible as a quoted empty value. Got: {reason}"

    def test_a_posix_path_is_unchanged(self, branch, fake_home, tmp_path):
        """The original assertion still holds - this fix must not buy Windows with Linux."""
        moved = tmp_path / "moved-branch"
        (moved / ".ai_mail.local").mkdir(parents=True)
        write_pointer(branch, "sess-live", "wake")
        (moved / ".ai_mail.local" / "session.json").write_text(
            pointer_path(branch).read_text(encoding="utf-8"), encoding="utf-8"
        )

        _session_id, reason = resolve_resume_target(moved)

        assert str(branch.resolve()) in reason
        assert str(moved.resolve()) in reason


class TestAnUnnameableHomeDoesNotRaise:
    """Path.home() can raise on Windows (no USERPROFILE); the resume path must not.

    Reached only once a pointer exists and its cwd matches, so it is the happy path.
    """

    @staticmethod
    def _home_is_unnameable(monkeypatch):
        """Make Path.home() fail the way ntpath does with no USERPROFILE."""

        def _raise():
            raise RuntimeError("Could not determine home directory.")

        monkeypatch.setattr(mod.Path, "home", staticmethod(_raise))

    def test_resolve_degrades_to_a_reason_instead_of_raising(self, branch, fake_home, monkeypatch):
        """The contract: a broken machine costs a resume, never a dispatch."""
        write_pointer(branch, "sess-live", "wake")
        _make_transcript(branch, "sess-live")
        self._home_is_unnameable(monkeypatch)

        session_id, reason = resolve_resume_target(branch)

        assert session_id is None
        assert reason.startswith("cannot determine this machine's home directory"), (
            "every verdict lands in a log line, so none may be silent"
        )

    def test_the_reason_says_home_and_not_transcript_not_found(self, branch, fake_home, monkeypatch):
        """ "I cannot name home" and "there is no transcript" are different facts."""
        write_pointer(branch, "sess-live", "wake")
        _make_transcript(branch, "sess-live")
        self._home_is_unnameable(monkeypatch)

        _session_id, reason = resolve_resume_target(branch)

        assert "home" in reason.lower(), f"the reason must name the actual failure. Got: {reason}"

    def test_transcript_dir_reports_the_absence_rather_than_guessing(self, monkeypatch, tmp_path):
        """No home means no answer — not a plausible path that cannot exist."""
        self._home_is_unnameable(monkeypatch)

        somewhere = str(tmp_path / "anywhere")
        assert transcript_dir(somewhere) is None
        assert transcript_file(somewhere, "sess") is None


class TestTheProviderOnThePointer:
    """A pointer resumes only the provider that wrote it; Codex threads live under ~/.codex/sessions."""

    THREAD = "01a1746b-c9c8-7891-ae8e-666b368caf13"

    def _rollout(self, home: Path) -> Path:
        day = home / ".codex" / "sessions" / "2026" / "10" / "25"
        day.mkdir(parents=True)
        rollout = day / f"rollout-2026-10-25T11-56-24-{self.THREAD}.jsonl"
        rollout.write_text("{}\n", encoding="utf-8")
        return rollout

    def test_a_pointer_without_the_key_still_resumes_a_claude_wake(self, branch, fake_home):
        pointer_path(branch).parent.mkdir(parents=True)
        pointer_path(branch).write_text(
            json.dumps({"session_id": "sess-old", "cwd": str(branch.resolve())}), encoding="utf-8"
        )
        _make_transcript(branch, "sess-old")

        assert resolve_resume_target(branch)[0] == "sess-old"

    def test_a_claude_pointer_starts_a_codex_wake_fresh_and_says_why(self, branch, fake_home):
        write_pointer(branch, "sess-live", "wake")
        _make_transcript(branch, "sess-live")

        session_id, reason = resolve_resume_target(branch, provider="codex")

        assert session_id is None
        assert reason == "pointer is for claude, waking on codex - starting fresh"

    def test_a_codex_pointer_never_resumes_a_claude_wake(self, branch, fake_home):
        write_pointer(branch, self.THREAD, "monitor-codex", provider="codex")
        self._rollout(fake_home)

        session_id, reason = resolve_resume_target(branch)

        assert session_id is None
        assert "pointer is for codex, waking on claude" in reason

    def test_a_codex_pointer_resumes_when_its_rollout_file_exists(self, branch, fake_home):
        write_pointer(branch, self.THREAD, "monitor-codex", provider="codex")
        rollout = self._rollout(fake_home)

        session_id, reason = resolve_resume_target(branch, provider="codex")

        assert session_id == self.THREAD
        assert str(rollout) in reason
        assert (read_pointer(branch) or {}).get("provider") == "codex"

    def test_a_codex_pointer_with_no_rollout_starts_fresh_never_minus_c(self, branch, fake_home):
        write_pointer(branch, self.THREAD, "monitor-codex", provider="codex")

        session_id, reason = resolve_resume_target(branch, provider="codex")

        assert session_id is None
        assert "not found" in reason and reason.endswith("starting fresh")
        assert "falling back to -c" not in reason


class TestTheOpenCodePointer:
    """An OpenCode pointer resumes only when OpenCode's own store holds the session for this branch."""

    @pytest.fixture
    def store(self, tmp_path, monkeypatch):
        db = tmp_path / "opencode.db"

        def plant(rows):
            with sqlite3.connect(db) as conn:
                conn.execute("create table if not exists session_v2 (id text primary key, directory text)")
                conn.executemany("insert into session_v2 values (?, ?)", rows)
            conn.close()

        monkeypatch.setenv("OPENCODE_DB", str(db))
        return plant

    def test_a_pointer_whose_session_the_store_holds_for_this_branch_resumes(self, branch, store):
        store([("ses_live", str(branch.resolve()))])
        write_pointer(branch, "ses_live", "wake-fresh", provider="opencode")

        assert resolve_resume_target(branch, provider="opencode") == (
            "ses_live",
            "pointer valid - resuming opencode session ses_live",
        )

    def test_a_session_absent_from_the_store_starts_fresh_and_names_the_store(self, branch, store, tmp_path):
        store([("ses_other", str(branch.resolve()))])
        write_pointer(branch, "ses_live", "wake-fresh", provider="opencode")

        session_id, reason = resolve_resume_target(branch, provider="opencode")

        assert session_id is None
        assert reason == f"session ses_live not found in {tmp_path / 'opencode.db'} - starting fresh"

    def test_a_session_recorded_for_another_directory_starts_fresh(self, branch, store, tmp_path):
        store([("ses_live", str(tmp_path / "elsewhere"))])
        write_pointer(branch, "ses_live", "wake-fresh", provider="opencode")

        session_id, reason = resolve_resume_target(branch, provider="opencode")

        assert session_id is None and "belongs to" in reason and reason.endswith("starting fresh")

    def test_no_store_at_all_starts_fresh_and_never_creates_one(self, branch, tmp_path, monkeypatch):
        db = tmp_path / "missing.db"
        monkeypatch.setenv("OPENCODE_DB", str(db))
        write_pointer(branch, "ses_live", "wake-fresh", provider="opencode")

        session_id, reason = resolve_resume_target(branch, provider="opencode")

        assert session_id is None and "does not exist" in reason
        assert not db.exists()

    def test_an_opencode_pointer_never_resumes_a_claude_wake(self, branch, store):
        store([("ses_live", str(branch.resolve()))])
        write_pointer(branch, "ses_live", "wake-fresh", provider="opencode")

        session_id, reason = resolve_resume_target(branch)

        assert session_id is None and "pointer is for opencode, waking on claude" in reason


class TestTheRunRecord:
    """The pointer says which host ran, what was asked for, and what the runtime's own row reported."""

    def test_the_old_call_shape_defaults_to_pending_and_cli_default(self, branch):
        write_pointer(branch, "ses_x", "monitor-opencode", provider="opencode")

        data = read_pointer(branch) or {}

        assert data["host_cli"] == data["provider"] == "opencode"
        assert (data["model_provider"], data["model_observed"]) == ("pending", "pending")
        assert (data["model_requested"], data["selection_source"], data["observed_at"]) == (
            "cli_default",
            "cli_default",
            None,
        )

    def test_run_sets_only_known_keys(self, branch):
        write_pointer(branch, "s", "wake", run={"model_requested": "m1", "selection_source": "flag", "api_key": "k"})

        data = read_pointer(branch) or {}

        assert (data["model_requested"], data["selection_source"]) == ("m1", "flag")
        assert "api_key" not in data

    def test_record_run_keeps_the_session_and_resets_what_this_run_did_not_see(self, branch):
        write_pointer(branch, "ses_x", "monitor-opencode", provider="opencode", run={"model_observed": "old"})

        assert mod.record_run(branch, {"model_requested": "openai/gpt-6.1-sol", "selection_source": "flag"})

        data = read_pointer(branch) or {}
        assert (data["session_id"], data["set_by"], data["provider"]) == ("ses_x", "monitor-opencode", "opencode")
        assert data["model_observed"] == "pending"

    def test_record_run_with_no_pointer_writes_nothing(self, branch):
        assert mod.record_run(branch, {"model_requested": "m"}) is False
        assert not pointer_path(branch).exists()

    def test_opencode_is_observed_from_the_newest_assistant_row(self, tmp_path, monkeypatch, branch):
        db = tmp_path / "opencode.db"
        with sqlite3.connect(db) as conn:
            conn.execute("create table session_message (session_id text, type text, seq int, data text)")
            rows = [
                ("ses_x", "assistant", 1, json.dumps({"model": {"id": "old", "providerID": "opencode"}})),
                ("ses_x", "assistant", 2, json.dumps({"model": {"id": "gpt-6.1-sol", "providerID": "openai"}})),
                ("ses_x", "user", 3, json.dumps({"model": {"id": "asked", "providerID": "x"}})),
                ("ses_y", "assistant", 4, json.dumps({"model": {"id": "other", "providerID": "y"}})),
            ]
            conn.executemany("insert into session_message values (?, ?, ?, ?)", rows)
        conn.close()
        monkeypatch.setenv("OPENCODE_DB", str(db))

        assert mod.observe_model(branch, "ses_x", "opencode") == ("openai", "gpt-6.1-sol")
        assert mod.observe_model(branch, "ses_none", "opencode") == (None, None)

    def test_an_opencode_store_without_the_table_is_unobserved_not_a_raise(self, tmp_path, monkeypatch, branch):
        db = tmp_path / "opencode.db"
        sqlite3.connect(db).close()
        monkeypatch.setenv("OPENCODE_DB", str(db))

        assert mod.observe_model(branch, "ses_x", "opencode") == (None, None)

    def test_claude_is_observed_from_the_last_assistant_line(self, branch, fake_home):
        target = _make_transcript(branch, "sess-1")
        lines = [
            {"type": "user", "message": {"model": "asked"}},
            {"type": "assistant", "message": {"model": "claude-opus-5-5"}},
        ]
        target.write_text("\n".join(json.dumps(line) for line in lines) + "\nnot json\n", encoding="utf-8")

        assert mod.observe_model(branch, "sess-1", "claude") == ("anthropic", "claude-opus-5-5")
        assert mod.observe_model(branch, "sess-none", "claude") == (None, None)

    def test_codex_is_observed_from_turn_context_and_session_meta(self, branch, fake_home):
        thread = "01a1746b-c9c8-7891-ae8e-666b368caf13"
        day = fake_home / ".codex" / "sessions" / "2026" / "10" / "28"
        day.mkdir(parents=True)
        lines = [
            {"type": "session_meta", "payload": {"model_provider": "openai"}},
            {"type": "turn_context", "payload": {"model": "gpt-6.1-sol"}},
        ]
        (day / f"rollout-2026-10-28T13-00-00-{thread}.jsonl").write_text(
            "\n".join(json.dumps(line) for line in lines), encoding="utf-8"
        )

        assert mod.observe_model(branch, thread, "codex") == ("openai", "gpt-6.1-sol")

    def test_the_run_line_says_observed_only_when_seen(self):
        seen = {"host_cli": "opencode", "model_provider": "openai", "model_observed": "gpt-6.1-sol"}
        seen.update(selection_source="flag", session_id="ses_1", model_requested="openai/gpt-6.1-sol")
        unseen = {**seen, "model_observed": "pending", "host_cli": "codex", "model_requested": "gpt-6.1-sol"}

        assert mod.format_run_line(seen) == "run: opencode · openai/gpt-6.1-sol (observed; flag) session ses_1"
        assert (
            mod.format_run_line(unseen) == "run: codex · gpt-6.1-sol (requested, observed pending; flag) session ses_1"
        )
        assert mod.format_run_line(None) == "run: no pointer recorded"

    def test_record_run_never_pairs_one_hosts_run_with_anothers_session(self, branch, monkeypatch):
        warn = MagicMock()
        monkeypatch.setattr(mod.logger, "warning", warn)
        write_pointer(branch, "ses_x", "monitor-opencode", provider="opencode", run={"model_observed": "gpt"})

        assert mod.record_run(branch, {"host_cli": "claude", "model_requested": "opus"}) is False

        data = read_pointer(branch) or {}
        assert (data["session_id"], data["provider"], data["host_cli"]) == ("ses_x", "opencode", "opencode")
        assert (data["model_requested"], data["model_observed"]) == ("cli_default", "pending")
        warn.assert_called_once()
