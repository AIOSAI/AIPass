# =================== AIPass ====================
# Name: test_windows_compat.py
# Description: Tests for windows_compat_check.py
# Version: 1.3.0
# Created: 2026-05-14
# Modified: 2026-10-10
# =============================================

"""Tests for apps/handlers/aipass_standards/windows_compat_check.py."""

# Both arms: POSIX-import detection, and test-file skipif enforcement.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(stdlib) — ast.parse's parsing; the checker only walks the tree it returns

from unittest.mock import MagicMock

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import windows_compat_check
from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_branch_info, check_module
from aipass.seedgo.apps.handlers.bypass import utils as bypass_utils


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Patch the checker's edges: its logger, its operation log and its bypass-rule loader.

    The checker and is_bypassed stay real; only what they talk to is swapped.
    """
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    monkeypatch.setattr(windows_compat_check, "logger", MagicMock())
    monkeypatch.setattr(windows_compat_check, "json_handler", mock_json_handler)
    monkeypatch.setattr(windows_compat_check, "load_bypass_rules", MagicMock(return_value=[]))
    monkeypatch.setattr(bypass_utils, "json_handler", mock_json_handler)


# ===========================================================================
# Existing POSIX-import detection
# ===========================================================================


def test_clean_file_passes(tmp_path):
    f = tmp_path / "clean.py"
    f.write_text("import os\nx = os.path.join('a', 'b')\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is True
    assert result["score"] == 100


def test_unguarded_fcntl_import_fails(tmp_path):
    f = tmp_path / "bad.py"
    f.write_text("import fcntl\nfcntl.flock(0, 0)\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is False
    assert "import fcntl" in result["checks"][0]["message"]


def test_guarded_fcntl_import_passes(tmp_path):
    f = tmp_path / "guarded.py"
    f.write_text("import sys\ntry:\n    import fcntl\nexcept ImportError:\n    fcntl = None\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is True


def test_platform_guarded_os_kill_passes(tmp_path):
    f = tmp_path / "guarded_kill.py"
    f.write_text("import os, sys\nif sys.platform != 'win32':\n    os.kill(1, 9)\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is True


def test_unguarded_os_kill_fails(tmp_path):
    f = tmp_path / "bad_kill.py"
    f.write_text("import os\nos.kill(1, 9)\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is False
    assert "os.kill()" in result["checks"][0]["message"]


def test_init_file_skipped(tmp_path):
    f = tmp_path / "__init__.py"
    f.write_text("import fcntl\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is True
    assert result["checks"][0]["message"] == "File skipped (non-target)"


def test_posix_only_call_fork_fails(tmp_path):
    f = tmp_path / "forker.py"
    f.write_text("import os\npid = os.fork()\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is False
    assert "os.fork()" in result["checks"][0]["message"]


def test_posix_constant_wnohang_fails(tmp_path):
    f = tmp_path / "waiter.py"
    f.write_text("import os\nflags = os.WNOHANG\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is False
    assert "os.WNOHANG" in result["checks"][0]["message"]


# ===========================================================================
# Test-file skipif enforcement (new)
# ===========================================================================


def test_unguarded_chmod_in_test_file_fails(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_perms.py"
    f.write_text("import os\n\ndef test_permissions():\n    os.chmod('file', 0o600)\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is False
    assert "os.chmod()" in result["checks"][0]["message"]


def test_skipif_guarded_chmod_passes(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_perms.py"
    f.write_text(
        "import os, sys, pytest\n\n"
        '@pytest.mark.skipif(sys.platform == "win32", reason="no perms")\n'
        "def test_permissions():\n"
        "    os.chmod('file', 0o600)\n",
        encoding="utf-8",
    )
    result = check_module(str(f))
    assert result["passed"] is True


def test_unguarded_stat_imode_in_test_fails(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_perms.py"
    f.write_text(
        "import os, stat\n\n"
        "def test_file_mode():\n"
        "    mode = stat.S_IMODE(os.stat('file').st_mode)\n"
        "    assert mode == 0o600\n",
        encoding="utf-8",
    )
    result = check_module(str(f))
    assert result["passed"] is False
    assert "stat.S_IMODE()" in result["checks"][0]["message"]


def test_unguarded_stat_constant_in_test_fails(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_perms.py"
    f.write_text(
        "import stat\n\ndef test_check_bits():\n    expected = stat.S_IRUSR | stat.S_IWUSR\n", encoding="utf-8"
    )
    result = check_module(str(f))
    assert result["passed"] is False
    assert "stat.S_IRUSR" in result["checks"][0]["message"]


def test_unguarded_symlink_in_test_fails(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_links.py"
    f.write_text("import os\n\ndef test_symlink():\n    os.symlink('a', 'b')\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is False
    assert "os.symlink()" in result["checks"][0]["message"]


def test_unguarded_getuid_in_test_fails(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_user.py"
    f.write_text("import os\n\ndef test_uid():\n    uid = os.getuid()\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is False
    assert "os.getuid()" in result["checks"][0]["message"]


def test_class_level_skipif_guards_all_methods(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_perms.py"
    f.write_text(
        "import os, sys, pytest\n\n"
        '@pytest.mark.skipif(sys.platform == "win32", reason="unix only")\n'
        "class TestPermissions:\n"
        "    def test_chmod(self):\n"
        "        os.chmod('file', 0o600)\n"
        "    def test_getuid(self):\n"
        "        os.getuid()\n",
        encoding="utf-8",
    )
    result = check_module(str(f))
    assert result["passed"] is True


def test_method_level_skipif_in_unguarded_class(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_mixed.py"
    f.write_text(
        "import os, sys, pytest\n\n"
        "class TestMixed:\n"
        '    @pytest.mark.skipif(sys.platform == "win32", reason="unix")\n'
        "    def test_guarded(self):\n"
        "        os.chmod('file', 0o600)\n"
        "    def test_unguarded(self):\n"
        "        os.chmod('file', 0o700)\n",
        encoding="utf-8",
    )
    result = check_module(str(f))
    assert result["passed"] is False
    assert "os.chmod()" in result["checks"][0]["message"]


def test_pytest_mark_skip_unconditional_passes(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_skipped.py"
    f.write_text(
        "import os, pytest\n\n@pytest.mark.skip(reason=\"not yet\")\ndef test_perms():\n    os.chmod('file', 0o600)\n",
        encoding="utf-8",
    )
    result = check_module(str(f))
    assert result["passed"] is True


def test_non_test_file_ignores_chmod(tmp_path):
    f = tmp_path / "handler.py"
    f.write_text("import os\n\ndef set_perms():\n    os.chmod('file', 0o600)\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is True


def test_inline_platform_guard_in_test_passes(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_guarded_inline.py"
    f.write_text(
        "import os, sys\n\ndef test_perms():\n    if sys.platform != \"win32\":\n        os.chmod('file', 0o600)\n",
        encoding="utf-8",
    )
    result = check_module(str(f))
    assert result["passed"] is True


def test_os_name_skipif_passes(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_osname.py"
    f.write_text(
        "import os, pytest\n\n"
        '@pytest.mark.skipif(os.name != "posix", reason="posix only")\n'
        "def test_chmod():\n"
        "    os.chmod('file', 0o600)\n",
        encoding="utf-8",
    )
    result = check_module(str(f))
    assert result["passed"] is True


def test_non_test_function_in_test_file_ignored(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_helpers.py"
    f.write_text(
        "import os\n\ndef helper_setup():\n    os.chmod('file', 0o600)\n\ndef test_clean():\n    assert True\n",
        encoding="utf-8",
    )
    result = check_module(str(f))
    assert result["passed"] is True


def test_chown_in_test_fails(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_owner.py"
    f.write_text("import os\n\ndef test_ownership():\n    os.chown('file', 1000, 1000)\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is False
    assert "os.chown()" in result["checks"][0]["message"]


def test_getgid_in_test_fails(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_gid.py"
    f.write_text("import os\n\ndef test_group():\n    gid = os.getgid()\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is False
    assert "os.getgid()" in result["checks"][0]["message"]


# ===========================================================================
# start_new_session=True detection (gap #3)
# ===========================================================================


def test_unguarded_start_new_session_fails(tmp_path):
    f = tmp_path / "daemon.py"
    f.write_text("import subprocess\nsubprocess.Popen(['cmd'], start_new_session=True)\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is False
    assert "start_new_session" in result["checks"][0]["message"]


def test_guarded_start_new_session_passes(tmp_path):
    f = tmp_path / "daemon.py"
    f.write_text(
        "import subprocess, sys\nif sys.platform != 'win32':\n    subprocess.Popen(['cmd'], start_new_session=True)\n",
        encoding="utf-8",
    )
    result = check_module(str(f))
    assert result["passed"] is True


# ===========================================================================
# Hardcoded /tmp detection (gap #6)
# ===========================================================================


def test_hardcoded_tmp_path_fails(tmp_path):
    f = tmp_path / "writer.py"
    f.write_text("from pathlib import Path\nout = Path('/tmp/output.log')\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is False
    assert "/tmp" in result["checks"][0]["message"]


def test_tempfile_usage_passes(tmp_path):
    f = tmp_path / "writer.py"
    f.write_text("import tempfile\nout = tempfile.gettempdir()\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is True


def test_guarded_tmp_path_passes(tmp_path):
    f = tmp_path / "writer.py"
    f.write_text("import sys\nif sys.platform == 'linux':\n    path = '/tmp/cache'\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is True


# ===========================================================================
# aplay-only audio detection (gap #7)
# ===========================================================================


def test_aplay_only_audio_fails(tmp_path):
    f = tmp_path / "sound.py"
    f.write_text("import subprocess\nsubprocess.run(['aplay', 'beep.wav'])\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is False
    assert "play" in result["checks"][0]["message"]


def test_guarded_aplay_passes(tmp_path):
    f = tmp_path / "sound.py"
    f.write_text(
        "import subprocess, sys\nif sys.platform == 'linux':\n    subprocess.run(['aplay', 'beep.wav'])\n",
        encoding="utf-8",
    )
    result = check_module(str(f))
    assert result["passed"] is True


# ===========================================================================
# shell=True detection (gap #8)
# ===========================================================================


def test_shell_true_fails(tmp_path):
    f = tmp_path / "runner.py"
    f.write_text("import subprocess\nsubprocess.run('ls -la', shell=True)\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is False
    assert "shell=True" in result["checks"][0]["message"]


def test_guarded_shell_true_passes(tmp_path):
    f = tmp_path / "runner.py"
    f.write_text(
        "import subprocess, sys\nif sys.platform != 'win32':\n    subprocess.run('ls -la', shell=True)\n",
        encoding="utf-8",
    )
    result = check_module(str(f))
    assert result["passed"] is True


def test_shell_false_passes(tmp_path):
    f = tmp_path / "runner.py"
    f.write_text("import subprocess\nsubprocess.run(['ls', '-la'], shell=False)\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is True


# ===========================================================================
# cp1252 / Rich entry point detection (gap #1)
# ===========================================================================


def test_rich_entry_without_reconfigure_fails(tmp_path):
    f = tmp_path / "app.py"
    f.write_text(
        "from aipass.cli import console\n\n"
        "def main():\n"
        "    console.print('hello')\n\n"
        'if __name__ == "__main__":\n'
        "    main()\n",
        encoding="utf-8",
    )
    result = check_module(str(f))
    assert result["passed"] is False
    assert "reconfigure" in result["checks"][0]["message"]


def test_rich_entry_with_reconfigure_passes(tmp_path):
    f = tmp_path / "app.py"
    f.write_text(
        "import sys\n"
        "from aipass.cli import console\n\n"
        "sys.stdout.reconfigure(encoding='utf-8')\n\n"
        "def main():\n"
        "    console.print('hello')\n\n"
        'if __name__ == "__main__":\n'
        "    main()\n",
        encoding="utf-8",
    )
    result = check_module(str(f))
    assert result["passed"] is True


def test_rich_entry_with_getattr_reconfigure_passes(tmp_path):
    f = tmp_path / "app.py"
    f.write_text(
        "import sys\n"
        "from aipass.cli import console\n\n"
        "for _stream in (sys.stdout, sys.stderr):\n"
        "    _reconfigure = getattr(_stream, 'reconfigure', None)\n"
        "    if _reconfigure is not None:\n"
        "        _reconfigure(encoding='utf-8', errors='replace')\n\n"
        "def main():\n"
        "    console.print('hello')\n\n"
        'if __name__ == "__main__":\n'
        "    main()\n",
        encoding="utf-8",
    )
    result = check_module(str(f))
    assert result["passed"] is True


def test_rich_non_entry_passes(tmp_path):
    f = tmp_path / "helper.py"
    # The console is built at call time: a module-level Console() is the import-time colour row below.
    f.write_text("from rich.console import Console\n\ndef show():\n    Console().print('hi')\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is True


# ===========================================================================
# os.kill(pid, 0) signal-0 detection (#682)
# ===========================================================================


def test_os_kill_signal0_unguarded_fails(tmp_path):
    f = tmp_path / "probe.py"
    f.write_text("import os\nos.kill(pid, 0)\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is False
    assert "os.kill(pid, 0)" in result["checks"][0]["message"]


def test_os_kill_sigterm_not_flagged_by_signal0(tmp_path):
    f = tmp_path / "killer.py"
    f.write_text(
        "import os, signal\ntry:\n    os.kill(pid, signal.SIGTERM)\nexcept OSError:\n    pass\n", encoding="utf-8"
    )
    result = check_module(str(f))
    assert result["passed"] is True


def test_os_kill_signal0_platform_guarded_passes(tmp_path):
    f = tmp_path / "probe.py"
    f.write_text("import os, sys\nif sys.platform != 'win32':\n    os.kill(pid, 0)\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is True


def test_os_kill_signal0_try_except_still_fails(tmp_path):
    f = tmp_path / "probe.py"
    f.write_text("import os\ntry:\n    os.kill(pid, 0)\nexcept OSError:\n    pass\n", encoding="utf-8")
    result = check_module(str(f))
    assert result["passed"] is False
    assert "os.kill(pid, 0)" in result["checks"][0]["message"]


def test_os_kill_signal0_early_return_guard_passes(tmp_path):
    f = tmp_path / "probe.py"
    f.write_text(
        "import os, sys\n\n"
        "def _is_pid_alive(pid):\n"
        "    if sys.platform == 'win32':\n"
        "        return _pid_alive_windows(pid)\n"
        "    try:\n"
        "        os.kill(pid, 0)\n"
        "        return True\n"
        "    except ProcessLookupError:\n"
        "        return False\n",
        encoding="utf-8",
    )
    result = check_module(str(f))
    assert result["passed"] is True


def test_os_kill_signal0_try_except_no_platform_check_fails(tmp_path):
    f = tmp_path / "probe.py"
    f.write_text(
        "import os\n\n"
        "def _is_pid_alive(pid):\n"
        "    try:\n"
        "        os.kill(pid, 0)\n"
        "        return True\n"
        "    except ProcessLookupError:\n"
        "        return False\n",
        encoding="utf-8",
    )
    result = check_module(str(f))
    assert result["passed"] is False
    assert "os.kill(pid, 0)" in result["checks"][0]["message"]


# ===========================================================================
# ADVISORY: exclusive creates that lose the Windows delete-pending race
# (CI 35192484222 — api's token store lock caught FileExistsError only)
# ===========================================================================

_INCIDENT_LOCK = (
    "import os, time\n\n"
    "def _store_lock(path):\n"
    "    descriptor = None\n"
    "    while descriptor is None:\n"
    "        try:\n"
    "            descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)\n"
    "        except FileExistsError:\n"
    "            time.sleep(0.05)\n"
    "    return descriptor\n"
)


def _advisory_findings(root, source, rel, label):
    """(line, description) pairs for one file, read back from check_branch_info's advisory lines."""
    _advisory_branch(root, source, rel=rel)
    prefix = f"{label}: {rel}:"
    found = []
    for line in check_branch_info(str(root)):
        assert line.startswith(prefix), line
        lineno, _, desc = line[len(prefix) :].partition(" ")
        found.append((int(lineno), desc))
    return found


def _races(root, source):
    return _advisory_findings(root, source, "apps/handlers/lock.py", "windows_compat lock race (advisory)")


def _advisory_branch(root, source, rel="apps/handlers/lock.py"):
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    return root


def test_lock_race_incident_shape_escapes(tmp_path):
    races = _races(tmp_path, _INCIDENT_LOCK)
    assert [line for line, _ in races] == [7]
    assert "_store_lock()" in races[0][1] and "escapes" in races[0][1]


def test_lock_race_permission_error_polled_is_clean(tmp_path):
    cured = _INCIDENT_LOCK.replace(
        "    return descriptor\n",
        "        except PermissionError:\n            time.sleep(0.05)\n    return descriptor\n",
    )
    assert _races(tmp_path, cured) == []


def test_lock_race_oserror_giving_up_inside_retry_loop_flagged(tmp_path):
    source = (
        "import os, time\n\n"
        "def _acquire_lock(lock_path):\n"
        "    for attempt in range(10):\n"
        "        try:\n"
        "            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)\n"
        "            return True\n"
        "        except FileExistsError:\n"
        "            time.sleep(0.01)\n"
        "        except OSError:\n"
        "            return False\n"
        "    return False\n"
    )
    races = _races(tmp_path, source)
    assert [line for line, _ in races] == [6]
    assert "gives up" in races[0][1] and "L10" in races[0][1]


def test_lock_race_single_shot_oserror_same_outcome_is_clean(tmp_path):
    source = (
        "import os\n\n"
        "def _acquire_lock(lock_file):\n"
        "    try:\n"
        "        fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)\n"
        "    except FileExistsError:\n"
        "        return False\n"
        "    except OSError:\n"
        "        return False\n"
        "    return True\n"
    )
    assert _races(tmp_path, source) == []


def test_lock_race_fresh_name_per_attempt_is_clean(tmp_path):
    source = (
        "import os\n\n"
        "def _stage(directory, serial):\n"
        "    for attempt in range(8):\n"
        "        temp_path = str(directory / f'.{next(serial)}.tmp')\n"
        "        try:\n"
        "            fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)\n"
        "            break\n"
        "        except FileExistsError:\n"
        "            if attempt == 7:\n"
        "                raise\n"
        "    return fd\n"
    )
    assert _races(tmp_path, source) == []


def test_lock_race_platform_guarded_is_clean(tmp_path):
    source = (
        "import os, sys, time\n\n"
        "def _store_lock(path):\n"
        "    if sys.platform != 'win32':\n"
        "        while True:\n"
        "            try:\n"
        "                return os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)\n"
        "            except FileExistsError:\n"
        "                time.sleep(0.05)\n"
    )
    assert _races(tmp_path, source) == []


def test_lock_race_outer_try_catching_oserror_is_clean(tmp_path):
    source = (
        "import os\n\n"
        "def acquire(lock):\n"
        "    try:\n"
        "        try:\n"
        "            os.open(lock, os.O_CREAT | os.O_EXCL)\n"
        "        except FileExistsError:\n"
        "            return False\n"
        "    except OSError:\n"
        "        return False\n"
        "    return True\n"
    )
    assert _races(tmp_path, source) == []


def test_lock_race_open_x_mode_escapes(tmp_path):
    source = (
        "def write_pid(pid_file, pid):\n"
        "    try:\n"
        "        with open(pid_file, 'x', encoding='utf-8') as fh:\n"
        "            fh.write(str(pid))\n"
        "    except FileExistsError:\n"
        "        return False\n"
        "    return True\n"
    )
    assert [line for line, _ in _races(tmp_path, source)] == [3]


def test_lock_race_create_without_exists_handler_is_ignored(tmp_path):
    source = "import os\n\ndef create(p):\n    return os.open(p, os.O_CREAT | os.O_EXCL)\n"
    assert _races(tmp_path, source) == []


def test_lock_race_advisory_line_never_reaches_the_score(tmp_path):
    branch = _advisory_branch(tmp_path, _INCIDENT_LOCK)
    assert check_branch_info(str(branch)) == [
        "windows_compat lock race (advisory): apps/handlers/lock.py:7 exclusive create in _store_lock() catches "
        "FileExistsError only - a Windows delete-pending PermissionError escapes where 'exists' is handled"
    ]
    result = check_module(str(branch / "apps" / "handlers" / "lock.py"))
    assert result["score"] == 100 and result["passed"] is True


def test_lock_race_advisory_corpus_is_apps_only(tmp_path):
    for rel in ("tests/lock_probe.py", "apps/handlers/.archive/old_lock.py", "tools/lock_tool.py"):
        _advisory_branch(tmp_path, _INCIDENT_LOCK, rel=rel)
    assert check_branch_info(str(tmp_path)) == []


def test_lock_race_advisory_respects_line_bypass(tmp_path, monkeypatch):
    branch = _advisory_branch(tmp_path, _INCIDENT_LOCK)
    rules = MagicMock(
        return_value=[{"file": "apps/handlers/lock.py", "standard": "windows_compat", "lines": [7], "reason": "test"}]
    )
    monkeypatch.setattr(windows_compat_check, "load_bypass_rules", rules)
    assert check_branch_info(str(branch)) == []
    rules.assert_called_once_with(str(branch))


# ===========================================================================
# ADVISORY: a path asserted against the repr of a mock call
# (CI 35416653326 — three flow tests: str(lock) in " ".join(str(c) for c in ...))
# ===========================================================================

_INCIDENT_REPR = (
    "def test_denial(tmp_path, mock_logger):\n"
    "    central_dir = tmp_path / '.ai_central'\n"
    "    lock = (central_dir / 'PLANS.central.json').with_suffix('.lock')\n"
    "    logged = ' '.join(str(c) for c in mock_logger.error.call_args_list)\n"
    "    assert str(lock) in logged\n"
    "    assert '3 attempts' in logged\n"
)


def _repr_paths(root, source):
    return _advisory_findings(root, source, "tests/test_probe.py", "windows_compat mock repr path (advisory)")


def _test_fn(*body):
    return "def test_x(tmp_path, m):\n    p = tmp_path / 'a.lock'\n" + "".join(f"    {line}\n" for line in body)


def test_mock_repr_incident_shape_flagged_once(tmp_path):
    found = _repr_paths(tmp_path, _INCIDENT_REPR)
    assert [line for line, _ in found] == [5]
    assert "red on Windows" in found[0][1]


def test_mock_repr_flow_cure_reading_the_real_args_is_clean(tmp_path):
    cured = _INCIDENT_REPR.replace(
        "str(c) for c in mock_logger.error.call_args_list",
        "str(arg) for c in mock_logger.error.call_args_list for arg in c.args",
    )
    assert _repr_paths(tmp_path, cured) == []


def test_mock_repr_real_message_one_level_inside_args_is_clean(tmp_path):
    source = _test_fn(
        "assert str(p) in m.call_args[0][0]",
        "assert str(p) in m.call_args.args[0]",
        "assert str(p) in m.call_args_list[0].kwargs['msg']",
        "assert any(str(p) in c.args[0] for c in m.call_args_list)",
        "assert str(p) in str(m.call_args[0][0])",
    )
    assert _repr_paths(tmp_path, source) == []


def test_mock_repr_record_and_container_reprs_flagged(tmp_path):
    source = _test_fn(
        "assert f'{tmp_path}' in str(m.call_args)",
        "assert str(p) in str(m.call_args.args)",
        "assert str(p.parent) in repr(m.call_args_list)",
        "args, kwargs = m.call_args",
        "assert str(p) in str(args)",
    )
    assert [line for line, _ in _repr_paths(tmp_path, source)] == [3, 4, 5, 7]


def test_mock_repr_loop_and_comprehension_elements_flagged(tmp_path):
    source = _test_fn(
        "printed = [str(c) for c in m.print.call_args_list]",
        "assert any(str(p) in s for s in printed)",
        "for c in m.call_args_list:",
        "    assert str(p) in str(c)",
        "assert any(os.fspath(p) in f'{c}' for c in m.mock_calls)",
        "for line in printed:",
        "    assert str(p) in line",
    )
    assert [line for line, _ in _repr_paths(tmp_path, source)] == [4, 6, 7, 9]


def test_mock_repr_not_in_is_vacuous_and_search_methods_flagged(tmp_path):
    source = _test_fn(
        "text = ' '.join(map(str, m.call_args_list)).lower()",
        "assert str(p) not in text",
        "assert text.count(str(p)) == 1",
        "assert text == str(p)",
    )
    found = _repr_paths(tmp_path, source)
    assert [line for line, _ in found] == [4, 5, 6]
    assert "vacuous on Windows" in found[0][1]
    assert ".count()" in found[1][1]


def test_mock_repr_path_sides_repr_cannot_change_are_clean(tmp_path):
    source = _test_fn(
        "logged = ' '.join(str(c) for c in m.call_args_list)",
        "assert p.name in logged",
        "assert p.as_posix() in logged",
        "assert str(Path('single.lock')) in logged",
        "assert repr(str(p)) in logged",
        "assert str(p).replace('\\\\', '\\\\\\\\') in logged",
        "assert str(p) in logged.replace('\\\\\\\\', '\\\\')",
        "assert 'files ready' in logged",
    )
    assert _repr_paths(tmp_path, source) == []


def test_mock_repr_platform_skips_are_clean(tmp_path):
    source = (
        "import sys, pytest\n\n"
        "@pytest.mark.skipif(sys.platform == 'win32', reason='posix paths')\n"
        + _test_fn("assert str(p) in str(m.call_args)")
        + "\n@pytest.mark.skipif(os.name == 'nt', reason='posix paths')\n"
        "class TestPosix:\n"
        "    def test_y(self, tmp_path, m):\n"
        "        assert str(tmp_path) in str(m.call_args)\n"
        "\ndef test_z(tmp_path, m):\n"
        "    if sys.platform != 'win32':\n"
        "        assert str(tmp_path) in str(m.call_args)\n"
    )
    assert _repr_paths(tmp_path, source) == []


def test_mock_repr_advisory_line_reads_tests_and_never_scores(tmp_path):
    branch = _advisory_branch(tmp_path, _INCIDENT_REPR, rel="tests/test_lock.py")
    _advisory_branch(tmp_path, _INCIDENT_REPR, rel="apps/handlers/helper.py")
    _advisory_branch(tmp_path, _INCIDENT_REPR, rel="tests/.archive/test_old.py")
    assert check_branch_info(str(branch)) == [
        "windows_compat mock repr path (advisory): tests/test_lock.py:5 a path is searched for in a mock call's "
        "repr - repr doubles each Windows backslash, red on Windows"
    ]
    assert check_module(str(branch / "tests" / "test_lock.py"))["score"] == 100


def test_mock_repr_advisory_respects_line_bypass(tmp_path, monkeypatch):
    branch = _advisory_branch(tmp_path, _INCIDENT_REPR, rel="tests/test_lock.py")
    rules = MagicMock(
        return_value=[{"file": "tests/test_lock.py", "standard": "windows_compat", "lines": [5], "reason": "test"}]
    )
    monkeypatch.setattr(windows_compat_check, "load_bypass_rules", rules)
    assert check_branch_info(str(branch)) == []


# CI 35426157867 — memory's marker-7 test: the paths came back from a helper
# (home, foreign = self._fenced_world(tmp_path, ...)), which the flow pass read
# as opaque, so the advisory nominated nothing.
_HELPER_RETURN = (
    "from unittest.mock import MagicMock\n"
    "\n"
    "class TestFence:\n"
    "    @staticmethod\n"
    "    def _world(tmp_path, monkeypatch):\n"
    "        home = tmp_path / 'aipass'\n"
    "        foreign = tmp_path / 'other_root' / 'local.json'\n"
    "        return home, foreign\n"
    "\n"
    "    def test_refused(self, tmp_path, monkeypatch):\n"
    "        home, foreign = self._world(tmp_path, monkeypatch)\n"
    "        said = MagicMock()\n"
    "        errors = ' '.join(str(call) for call in said.error.call_args_list)\n"
    "        assert str(foreign.resolve()) in errors and str(home.resolve()) in errors, errors\n"
)


def test_mock_repr_path_returned_by_a_same_module_helper_flagged(tmp_path):
    found = _repr_paths(tmp_path, _HELPER_RETURN)
    assert [line for line, _ in found] == [14]
    assert "red on Windows" in found[0][1]


def test_mock_repr_helper_cure_joining_the_rendered_args_is_clean(tmp_path):
    cured = _HELPER_RETURN.replace("str(call) for call in", "str(arg) for call in").replace(
        "call_args_list)", "call_args_list for arg in call.args)"
    )
    assert _repr_paths(tmp_path, cured) == []


def test_mock_repr_helper_returns_read_by_kind_not_by_call(tmp_path):
    source = (
        "def _lock(tmp_path):\n"
        "    return tmp_path / 'a.lock'\n"
        "\n"
        "def _word():\n"
        "    return 'refused'\n"
        "\n"
        "def _logged(m):\n"
        "    return ' '.join(str(c) for c in m.call_args_list)\n"
        "\n"
        "def _either(tmp_path, flag):\n"
        "    if flag:\n"
        "        return tmp_path / 'x'\n"
        "    return 'x'\n"
        "\n"
        "def test_x(tmp_path, m):\n"
        "    lock = _lock(tmp_path)\n"
        "    logged = ' '.join(str(c) for c in m.call_args_list)\n"
        "    assert str(lock) in logged\n"
        "    assert _word() in logged\n"
        "    assert str(tmp_path) in _logged(m)\n"
        "    assert str(_either(tmp_path, True)) in logged\n"
        "    a, b = tmp_path / 'a', 'word'\n"
        "    assert b in logged\n"
        "    assert str(a) in logged\n"
        "    assert str(obj._lock(tmp_path)) in logged\n"
    )
    assert [line for line, _ in _repr_paths(tmp_path, source)] == [18, 20, 24]


# ===========================================================================
# Deferred platform-only import (devpulse a831fe55, PR #774 CI run 38068553235)
# ===========================================================================

# Minimised from devpulse apps/handlers/watchdog/registry.py 1.1.0 (_FileLock):
# fcntl imported at call time under sys.platform != 'win32'; a test that pretends
# darwin made the Windows runner import a module it does not have.
_DEFERRED_FCNTL = (
    "import sys\n"
    "\n"
    "class _FileLock:\n"
    "    def __enter__(self):\n"
    "        if sys.platform != 'win32':\n"
    "            import fcntl\n"
    "\n"
    "            self._fh = open(self._lock_path, 'a+', encoding='utf-8')\n"
    "            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)\n"
    "        return self\n"
    "\n"
    "    def __exit__(self, exc_type, exc, tb):\n"
    "        if sys.platform != 'win32' and self._fh is not None:\n"
    "            import fcntl\n"
    "\n"
    "            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)\n"
)

# registry.py 1.1.1, the cure: one module-level binding, None (logged) where absent.
_BOUND_FCNTL = (
    "import logging\n"
    "\n"
    "logger = logging.getLogger(__name__)\n"
    "\n"
    "try:\n"
    "    import fcntl\n"
    "except ImportError as exc:\n"
    "    fcntl = None\n"
    "    logger.info('fcntl absent: %s', exc)\n"
    "\n"
    "class _FileLock:\n"
    "    def __enter__(self):\n"
    "        if fcntl is not None:\n"
    "            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)\n"
    "        return self\n"
)


def _module_result(tmp_path, source, name="registry.py"):
    f = tmp_path / name
    f.write_text(source, encoding="utf-8")
    return check_module(str(f))


def test_deferred_platform_import_under_a_platform_condition_convicted(tmp_path):
    result = _module_result(tmp_path, _DEFERRED_FCNTL)
    message = result["checks"][0]["message"]
    assert result["passed"] is False
    assert message.startswith("2 unguarded POSIX pattern(s)"), message
    assert "L6: import fcntl inside __enter__()" in message
    assert "L14: import fcntl inside __exit__()" in message


def test_deferred_platform_import_cure_module_level_binding_is_acquitted(tmp_path):
    result = _module_result(tmp_path, _BOUND_FCNTL)
    assert result["passed"] is True, result["checks"][0]["message"]


def test_module_level_platform_gated_import_stays_acquitted(tmp_path):
    source = "import sys\nif sys.platform == 'win32':\n    import msvcrt\nelse:\n    import fcntl\n"
    result = _module_result(tmp_path, source, "inbox_lock.py")
    assert result["passed"] is True, result["checks"][0]["message"]


def test_windows_only_module_deferred_into_a_function_convicted(tmp_path):
    source = (
        "def _try_lock_win32(lock_file, msvcrt_module=None):\n"
        "    if msvcrt_module is None:\n"
        "        import msvcrt as msvcrt_module\n"
        "    return msvcrt_module\n"
        "\n"
        "def _hive():\n"
        "    from winreg import HKEY_CURRENT_USER\n"
        "    return HKEY_CURRENT_USER\n"
    )
    message = _module_result(tmp_path, source, "config.py")["checks"][0]["message"]
    assert "L3: import msvcrt inside _try_lock_win32()" in message
    assert "L7: from winreg import ... inside _hive()" in message


def test_deferred_platform_import_inside_try_importerror_is_acquitted(tmp_path):
    source = (
        "import sys\n"
        "\n"
        "def lock(fh):\n"
        "    if sys.platform != 'win32':\n"
        "        try:\n"
        "            import fcntl\n"
        "        except ImportError:\n"
        "            return\n"
        "        fcntl.flock(fh, fcntl.LOCK_EX)\n"
    )
    assert _module_result(tmp_path, source)["passed"] is True


def test_unguarded_function_level_fcntl_reported_once(tmp_path):
    message = _module_result(tmp_path, "def lock(fh):\n    import fcntl\n    fcntl.flock(fh, 2)\n")["checks"][0][
        "message"
    ]
    assert message == "1 unguarded POSIX pattern(s): L2: import fcntl"


# ===========================================================================
# Console colour pinned at import (cli b6655280, PR #774 CI run 38068553235)
# ===========================================================================

# Minimised from cli apps/modules/display.py 0.5.2: isatty() read once at import,
# and both consoles built from it. A conftest imported display while pytest's
# capture was suspended; on a Windows xdist worker stdout is NUL, isatty() said
# True, and every later capture carried escape codes (380 of 518 Windows rows).
_PINNED_DISPLAY = (
    "import sys\n"
    "from rich.console import Console\n"
    "\n"
    "_IS_TTY = sys.stdout.isatty()\n"
    "\n"
    "CONSOLE = Console(force_terminal=_IS_TTY)\n"
    "console = CONSOLE\n"
    "err_console = Console(stderr=True, force_terminal=sys.stderr.isatty())\n"
)

# display.py 0.5.3, the cure: a Console subclass that re-detects colour per print.
_LIVE_DISPLAY = (
    "from rich.console import Console\n"
    "\n"
    "class _LiveConsole(Console):\n"
    "    @property\n"
    "    def _color_system(self):\n"
    "        return self._detect_color_system()\n"
    "\n"
    "    @_color_system.setter\n"
    "    def _color_system(self, _value):\n"
    "        pass\n"
    "\n"
    "CONSOLE = _LiveConsole()\n"
    "console = CONSOLE\n"
    "err_console = _LiveConsole(stderr=True)\n"
)


def _stream_rows(tmp_path, source, name="display.py"):
    return _module_result(tmp_path, source, name)["checks"][0]["message"]


def test_console_pinned_at_import_incident_shape_convicted(tmp_path):
    result = _module_result(tmp_path, _PINNED_DISPLAY, "display.py")
    message = result["checks"][0]["message"]
    assert result["passed"] is False
    assert message.startswith("3 unguarded POSIX pattern(s)"), message
    assert "L4: isatty() read at import" in message
    assert "L6: module-level Console() fixes its colour at import" in message
    assert "L8: module-level Console() fixes its colour at import" in message


def test_console_deciding_colour_per_print_cure_is_acquitted(tmp_path):
    result = _module_result(tmp_path, _LIVE_DISPLAY, "display.py")
    assert result["passed"] is True, result["checks"][0]["message"]


def test_plain_module_level_console_convicted(tmp_path):
    """Rich runs _detect_color_system() in __init__: an unset force_terminal still pins it."""
    source = "from rich.console import Console as _Console\n\nconsole = _Console()\n"
    assert "L3: module-level _Console() fixes its colour" in _stream_rows(tmp_path, source, "diagnostics_check.py")


def test_console_subclass_that_keeps_the_init_answer_convicted(tmp_path):
    source = "import rich.console\n\nclass Quiet(rich.console.Console):\n    pass\n\nOUT = Quiet()\n"
    assert "L6: module-level Quiet() fixes its colour" in _stream_rows(tmp_path, source)


def test_console_with_an_explicit_colour_decision_is_acquitted(tmp_path):
    source = (
        "import io\n"
        "from rich.console import Console\n"
        "\n"
        "BUFFER = Console(file=io.StringIO())\n"
        "PLAIN = Console(force_terminal=False)\n"
        "NO_COLOUR = Console(color_system=None)\n"
    )
    assert _module_result(tmp_path, source)["passed"] is True


def test_console_bound_to_the_import_time_stream_convicted(tmp_path):
    source = "import sys\nfrom rich.console import Console\n\nOUT = Console(file=sys.stdout)\n"
    assert "L4: module-level Console() fixes its colour" in _stream_rows(tmp_path, source)


def test_console_built_at_call_time_fallback_or_main_is_acquitted(tmp_path):
    """A function body, a cross-branch ImportError fallback and a script's main run no Console at import."""
    source = (
        "try:\n"
        "    from aipass.cli.apps.modules import console\n"
        "except ImportError:\n"
        "    from rich.console import Console\n"
        "    console = Console()\n"
        "\n"
        "def render():\n"
        "    from rich.console import Console\n"
        "    return Console()\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    import sys\n"
        "    from rich.console import Console\n"
        "    sys.stdout.reconfigure(encoding='utf-8')\n"
        "    Console().print('demo')\n"
    )
    assert _module_result(tmp_path, source, "feed.py")["passed"] is True


def test_terminal_size_cached_into_a_constant_convicted(tmp_path):
    source = (
        "import shutil\n"
        "\n"
        "WIDTH = shutil.get_terminal_size().columns\n"
        "\n"
        "def width():\n"
        "    return shutil.get_terminal_size()\n"
    )
    message = _stream_rows(tmp_path, source, "layout.py")
    assert message == "1 unguarded POSIX pattern(s): L3: get_terminal_size() read at import -- read it when you print"


def test_console_pinned_at_import_not_read_in_tests(tmp_path):
    (tmp_path / "tests").mkdir()
    assert _module_result(tmp_path / "tests", _PINNED_DISPLAY, "conftest.py")["passed"] is True


# ===========================================================================
# Test-file arm: a tmp_path name holding a backslash, written to disk
# ===========================================================================
# seedgo's own tests/test_checkers_batch7.py (PR #774, CI round three) wrote
# tmp_path / "aipass\\memory\\apps\\modules\\door_entry_limits.py": one file on
# POSIX, a tree with no parents on Windows, so write_text raised there before
# the checker under test ran. The specimens below are minimised from it.

_BACKSLASHED_DOOR = (
    "def test_a_door_under_a_backslashed_modules_path_passes(tmp_path):\n"
    '    door = tmp_path / "aipass\\\\memory\\\\apps\\\\modules\\\\door_entry_limits.py"\n'
    '    door.write_text("x", encoding="utf-8")\n'
)


def _test_file_rows(tmp_path, source):
    (tmp_path / "tests").mkdir()
    result = _module_result(tmp_path / "tests", source, "test_doors.py")
    return result["passed"], result["checks"][0]["message"]


def test_a_backslashed_tmp_path_name_written_is_convicted(tmp_path):
    """Mutant: _find_backslashed_tmp_writes returns no rows in windows_compat_check.py — killed."""
    passed, message = _test_file_rows(tmp_path, _BACKSLASHED_DOOR)
    assert passed is False
    assert message == (
        "1 unguarded POSIX pattern(s): L3: tmp_path name 'aipass\\\\memory\\\\apps\\\\modules\\\\door_entry_limits.py'"
        " holds a backslash -- one file on POSIX, a tree on Windows"
    )


def test_a_backslashed_name_written_in_place_is_convicted(tmp_path):
    source = (
        "def test_one(tmp_path):\n"
        '    (tmp_path / "sub" / "a\\\\b.txt").write_text("x", encoding="utf-8")\n'
        '    tmp_path.joinpath("c\\\\d").mkdir()\n'
        '    with open(tmp_path / "e\\\\f.txt", "w", encoding="utf-8") as fh:\n'
        '        fh.write("x")\n'
    )
    passed, message = _test_file_rows(tmp_path, source)
    assert passed is False
    assert message.startswith("3 unguarded POSIX pattern(s): L2: tmp_path name 'a\\\\b.txt'"), message
    assert "L3: tmp_path name 'c\\\\d'" in message and "L4: tmp_path name 'e\\\\f.txt'" in message


def test_the_cured_door_is_acquitted(tmp_path):
    """The cure: a real tree written, its Windows spelling handed over as a string."""
    source = (
        "from pathlib import PureWindowsPath\n\n"
        "def test_a_door_under_a_backslashed_modules_path_passes(tmp_path):\n"
        '    door = tmp_path.joinpath("aipass", "memory", "apps", "modules", "door_entry_limits.py")\n'
        "    door.parent.mkdir(parents=True, exist_ok=True)\n"
        '    door.write_text("x", encoding="utf-8")\n'
        "    assert str(PureWindowsPath(door))\n"
    )
    assert _test_file_rows(tmp_path, source) == (True, "No unguarded POSIX-only patterns found")


def test_a_backslashed_name_never_written_is_acquitted(tmp_path):
    """A name only read or handed on means the same missing file on both hosts."""
    source = (
        "def test_missing(tmp_path):\n"
        '    missing = tmp_path / "a\\\\b.py"\n'
        "    assert not missing.exists()\n"
        '    with open(tmp_path / "c\\\\d.txt", encoding="utf-8") as fh:\n'
        "        fh.read()\n"
    )
    assert _test_file_rows(tmp_path, source) == (True, "No unguarded POSIX-only patterns found")


def test_a_backslashed_name_in_a_posix_only_test_is_acquitted(tmp_path):
    """A test that means the POSIX file name, skipped on Windows, says so."""
    source = (
        "import sys\n\nimport pytest\n\n"
        '@pytest.mark.skipif(sys.platform == "win32", reason="a backslash is a separator there")\n' + _BACKSLASHED_DOOR
    )
    assert _test_file_rows(tmp_path, source) == (True, "No unguarded POSIX-only patterns found")


def test_a_name_rebound_to_a_clean_path_is_not_guessed_at(tmp_path):
    source = (
        "def test_rebound(tmp_path):\n"
        '    door = tmp_path / "a\\\\b.py"\n'
        '    door = tmp_path / "b.py"\n'
        '    door.write_text("x", encoding="utf-8")\n'
    )
    assert _test_file_rows(tmp_path, source) == (True, "No unguarded POSIX-only patterns found")
