# =================== AIPass ====================
# Name: support_session_boot.py
# Description: Helpers shared by the session_boot test files: patch target, env redirects, transcripts, pointers
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Helpers for the session_boot tests (no test_ prefix: never collected)."""

# Shared by test_session_boot.py, test_session_boot_lookups.py and
# test_session_boot_doors.py, all of apps/handlers/lifecycle/session_boot.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import os
from pathlib import Path

from aipass.ai_mail.apps.modules import door_session_pointer as sp

_MOD = "aipass.hooks.apps.handlers.lifecycle.session_boot"


def _kept_redirect() -> dict[str, str]:
    """The json redirect a clear=True wipe must hand back, or the loggers write the live hooks_json."""
    return {"AIPASS_TEST_LOG_DIR": os.environ["AIPASS_TEST_LOG_DIR"]}


def make_transcript(projects_root, cwd, session_id, title, messages, age_seconds=0):
    """Write a CC-shaped transcript so the picker has a real chat to find."""
    import json as _json
    import os as _os
    import re as _re

    directory = projects_root / _re.sub(r"[^A-Za-z0-9]", "-", str(Path(cwd).resolve()))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{session_id}.jsonl"
    lines = [_json.dumps({"type": "ai-title", "aiTitle": title, "sessionId": session_id})]
    for i in range(messages):
        lines.append(_json.dumps({"type": "user", "message": {"content": f"turn {i}"}}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if age_seconds:
        stamp = path.stat().st_mtime - age_seconds
        _os.utime(path, (stamp, stamp))
    return path


def home_env(home) -> dict[str, str]:
    """The environment that redirects home resolution on BOTH platforms.

    `Path.home()` asks `os.path.expanduser`, and the two implementations read
    different variables: POSIX honours $HOME (falling back to the pwd database
    when it is unset), while Windows reads %USERPROFILE% and has no pwd to fall
    back to. Setting HOME alone therefore redirects home on Linux and does
    nothing at all on Windows.

    That gap is not cosmetic under `patch.dict(..., clear=True)`. Clearing the
    environ strips the runner's real USERPROFILE, so Windows expanduser returns
    "~" unchanged and pathlib raises RuntimeError("Could not determine home
    directory.") — four of these tests died exactly that way on the
    windows-setup CI job (PR 739, 2026-08-22). Their siblings survived only by
    returning before any home lookup, which made the split look like a bug in
    the pointer code rather than a POSIX-only fixture.

    Setting both keys is the portable redirect, so this is deliberately NOT a
    skipif: nothing about pointing home at a temp directory is POSIX-only, and
    these doors ship to Windows users too.
    """
    return {**_kept_redirect(), "HOME": str(home), "USERPROFILE": str(home)}


def set_home(monkeypatch, home) -> str:
    """Point home resolution at `home` for the current test, both platforms.

    The monkeypatch half of `home_env` — same reasoning, same two keys. Returns
    the path as a string, which is what the `patch.dict` callers pass on.
    """
    for key, value in home_env(home).items():
        monkeypatch.setenv(key, value)
    return str(home)


def plant_pointer(tmp_path, monkeypatch, session_id):
    """A real session pointer plus the transcript that makes it trustworthy.

    Written through session_pointer itself — the FPLAN-0447 store is the only
    production writer, so the tests speak its format by calling it, never by
    spelling the JSON. Home is redirected first because the transcript check
    walks <home>/.claude/projects; the caller must keep that redirect in place
    inside boot() by spreading `home_env(...)` into its `patch.dict`. A cleared
    environ resolves to the REAL home on POSIX (pwd fallback) and to no home at
    all on Windows — a silent miss on one platform, a RuntimeError on the other.
    """
    home = tmp_path / "home"
    set_home(monkeypatch, home)
    tdir = sp.transcript_dir(tmp_path)
    # None means session_pointer could not name the home directory, which here
    # can only mean set_home above failed to take — assert it rather than dying
    # on NoneType later, so a broken redirect names itself.
    assert tdir is not None, "home redirect did not take: session_pointer cannot resolve a home"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / f"{session_id}.jsonl").write_text("{}\n", encoding="utf-8")
    assert sp.write_pointer(Path(tmp_path), session_id, "test")
    return str(home)
