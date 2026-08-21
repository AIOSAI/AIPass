# =================== AIPass ====================
# Name: test_session_pointer.py
# Description: Tests for the durable per-branch session pointer
# Version: 1.0.0
# Created: 2026-08-20
# Modified: 2026-08-20
# =============================================

"""Tests for session_pointer -- encoding, round trip, atomicity, resume verdicts.

Everything here runs against tmp_path. ``Path.home`` is monkeypatched wherever a
test needs a transcript to exist, so no test can read or create anything under
the real ``~/.claude`` or inside a live branch.
"""

import json
import os
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


# --- Fixtures --------------------------------------------------------


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
    """Point Path.home at tmp_path so transcript paths land under the sandbox."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def _make_transcript(branch_path: Path, session_id: str, size_bytes: int = 64) -> Path:
    """Create a fake transcript for `session_id` under the (faked) home."""
    target = transcript_file(branch_path, session_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x" * size_bytes)
    return target


# --- mint_session_id -------------------------------------------------


def test_mint_session_id_is_a_uuid_string():
    """Callers pass this straight to --session-id, so the shape is a contract."""
    import uuid

    minted = mint_session_id()
    assert isinstance(minted, str)
    assert uuid.UUID(minted)


def test_mint_session_id_is_unique():
    assert mint_session_id() != mint_session_id()


# --- transcript_dir / transcript_file --------------------------------


def test_transcript_dir_encodes_separators_underscores_and_dots(fake_home):
    """/ and _ and . all collapse to '-' -- the rule Claude itself uses."""
    encoded = transcript_dir("/srv/branches/my_repo/src.pkg").name
    assert encoded == "-srv-branches-my-repo-src-pkg"
    assert "_" not in encoded
    assert "." not in encoded
    assert "/" not in encoded


def test_transcript_dir_encodes_windows_paths(fake_home):
    """Backslash and drive colon collapse too: C:\\repo\\AIPass -> C--repo-AIPass."""
    assert transcript_dir("C:\\repo\\AIPass").name == "C--repo-AIPass"


def test_transcript_dir_lives_under_claude_projects(fake_home):
    result = transcript_dir("/some/branch")
    assert result.parent == fake_home / ".claude" / "projects"


def test_transcript_dir_accepts_a_path_object(fake_home):
    assert transcript_dir(Path("/some/branch")) == transcript_dir("/some/branch")


def test_transcript_file_appends_the_jsonl_name(fake_home):
    result = transcript_file("/some/branch", "abc-123")
    assert result.name == "abc-123.jsonl"
    assert result.parent == transcript_dir("/some/branch")


def test_transcript_dir_matches_dispatch_monitors_encoding(fake_home):
    """The two implementations must never disagree while both exist."""
    from aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor import _get_jsonl_projects_dir

    cwd = "/srv/branches/AIPass/src/aipass/ai_mail"
    assert transcript_dir(cwd) == _get_jsonl_projects_dir(cwd)


# --- pointer_path ----------------------------------------------------


def test_pointer_path_sits_beside_the_dispatch_lock(branch):
    assert pointer_path(branch) == branch / ".ai_mail.local" / "session.json"


# --- write_pointer / read_pointer round trip -------------------------


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
    assert data is not None
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


# --- read_pointer refusals -------------------------------------------


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


# --- write_pointer failure paths -------------------------------------


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


# --- resolve_resume_target -------------------------------------------


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
    assert reason


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


# --- resolve_resume_target: oversize transcript ----------------------


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
        # The existence check must still pass -- only the SIZE read fails,
        # which is the narrow case this test pins.
        if self.suffix == ".jsonl":
            return True
        return real_is_file(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_file", _is_file)
    monkeypatch.setattr(Path, "stat", _boom_stat)
    session_id, reason = resolve_resume_target(branch, max_transcript_mb=1.0)
    assert session_id == "sess-live"
    assert "size unknown" in reason


# --- never raises ----------------------------------------------------


def test_resolve_never_raises_on_a_nonsense_argument():
    """The dispatch hot path survives a caller's mistake."""
    session_id, reason = resolve_resume_target(object())  # type: ignore[arg-type]
    assert session_id is None
    assert reason


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
    assert set(parsed) == {"session_id", "set_at", "set_by", "cwd"}
    assert os.linesep in raw or "\n" in raw  # indented, not a single blob
