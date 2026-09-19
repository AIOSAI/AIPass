# =================== AIPass ====================
# Name: test_windows_compat.py
# Description: Tests for windows_compat_check.py
# Version: 1.0.0
# Created: 2026-05-14
# Modified: 2026-09-17
# =============================================

"""Tests for windows_compat_check — both POSIX-import detection and test-file skipif enforcement."""

import pytest
from unittest.mock import MagicMock


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    import sys

    mock_logger = MagicMock()
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json.json_handler", json_mod)

    bypass_pkg = MagicMock()
    bypass_ignore = MagicMock()
    bypass_ignore.get_template_ignore_patterns = MagicMock(return_value=[])
    from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed as real_is_bypassed

    bypass_utils = MagicMock()
    bypass_utils.is_bypassed = real_is_bypassed
    bypass_pkg.utils = bypass_utils
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass", bypass_pkg)
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass.ignore_handler", bypass_ignore)
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass.utils", bypass_utils)
    bypass_handler = MagicMock()
    bypass_handler.load_bypass_rules = MagicMock(return_value=[])
    bypass_pkg.bypass_handler = bypass_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass.bypass_handler", bypass_handler)

    for mod_name in ["aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check"]:
        monkeypatch.delitem(sys.modules, mod_name, raising=False)


# ===========================================================================
# Existing POSIX-import detection
# ===========================================================================


def test_clean_file_passes(tmp_path):
    f = tmp_path / "clean.py"
    f.write_text("import os\nx = os.path.join('a', 'b')\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is True
    assert result["score"] == 100


def test_unguarded_fcntl_import_fails(tmp_path):
    f = tmp_path / "bad.py"
    f.write_text("import fcntl\nfcntl.flock(0, 0)\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is False
    assert "import fcntl" in result["checks"][0]["message"]


def test_guarded_fcntl_import_passes(tmp_path):
    f = tmp_path / "guarded.py"
    f.write_text("import sys\ntry:\n    import fcntl\nexcept ImportError:\n    fcntl = None\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is True


def test_platform_guarded_os_kill_passes(tmp_path):
    f = tmp_path / "guarded_kill.py"
    f.write_text("import os, sys\nif sys.platform != 'win32':\n    os.kill(1, 9)\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is True


def test_unguarded_os_kill_fails(tmp_path):
    f = tmp_path / "bad_kill.py"
    f.write_text("import os\nos.kill(1, 9)\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is False
    assert "os.kill()" in result["checks"][0]["message"]


def test_init_file_skipped(tmp_path):
    f = tmp_path / "__init__.py"
    f.write_text("import fcntl\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is True
    assert result["checks"][0]["message"] == "File skipped (non-target)"


def test_posix_only_call_fork_fails(tmp_path):
    f = tmp_path / "forker.py"
    f.write_text("import os\npid = os.fork()\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is False
    assert "os.fork()" in result["checks"][0]["message"]


def test_posix_constant_wnohang_fails(tmp_path):
    f = tmp_path / "waiter.py"
    f.write_text("import os\nflags = os.WNOHANG\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

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
    f.write_text("import os\n\ndef test_permissions():\n    os.chmod('file', 0o600)\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

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
        "    os.chmod('file', 0o600)\n"
    )
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

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
        "    assert mode == 0o600\n"
    )
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is False
    assert "stat.S_IMODE()" in result["checks"][0]["message"]


def test_unguarded_stat_constant_in_test_fails(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_perms.py"
    f.write_text("import stat\n\ndef test_check_bits():\n    expected = stat.S_IRUSR | stat.S_IWUSR\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is False
    assert "stat.S_IRUSR" in result["checks"][0]["message"]


def test_unguarded_symlink_in_test_fails(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_links.py"
    f.write_text("import os\n\ndef test_symlink():\n    os.symlink('a', 'b')\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is False
    assert "os.symlink()" in result["checks"][0]["message"]


def test_unguarded_getuid_in_test_fails(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_user.py"
    f.write_text("import os\n\ndef test_uid():\n    uid = os.getuid()\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

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
        "        os.getuid()\n"
    )
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

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
        "        os.chmod('file', 0o700)\n"
    )
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is False
    assert "os.chmod()" in result["checks"][0]["message"]


def test_pytest_mark_skip_unconditional_passes(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_skipped.py"
    f.write_text(
        "import os, pytest\n\n@pytest.mark.skip(reason=\"not yet\")\ndef test_perms():\n    os.chmod('file', 0o600)\n"
    )
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is True


def test_non_test_file_ignores_chmod(tmp_path):
    f = tmp_path / "handler.py"
    f.write_text("import os\n\ndef set_perms():\n    os.chmod('file', 0o600)\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is True


def test_inline_platform_guard_in_test_passes(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_guarded_inline.py"
    f.write_text(
        "import os, sys\n\ndef test_perms():\n    if sys.platform != \"win32\":\n        os.chmod('file', 0o600)\n"
    )
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

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
        "    os.chmod('file', 0o600)\n"
    )
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is True


def test_non_test_function_in_test_file_ignored(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_helpers.py"
    f.write_text(
        "import os\n\ndef helper_setup():\n    os.chmod('file', 0o600)\n\ndef test_clean():\n    assert True\n"
    )
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is True


def test_chown_in_test_fails(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_owner.py"
    f.write_text("import os\n\ndef test_ownership():\n    os.chown('file', 1000, 1000)\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is False
    assert "os.chown()" in result["checks"][0]["message"]


def test_getgid_in_test_fails(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_gid.py"
    f.write_text("import os\n\ndef test_group():\n    gid = os.getgid()\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is False
    assert "os.getgid()" in result["checks"][0]["message"]


# ===========================================================================
# start_new_session=True detection (gap #3)
# ===========================================================================


def test_unguarded_start_new_session_fails(tmp_path):
    f = tmp_path / "daemon.py"
    f.write_text("import subprocess\nsubprocess.Popen(['cmd'], start_new_session=True)\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is False
    assert "start_new_session" in result["checks"][0]["message"]


def test_guarded_start_new_session_passes(tmp_path):
    f = tmp_path / "daemon.py"
    f.write_text(
        "import subprocess, sys\nif sys.platform != 'win32':\n    subprocess.Popen(['cmd'], start_new_session=True)\n"
    )
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is True


# ===========================================================================
# Hardcoded /tmp detection (gap #6)
# ===========================================================================


def test_hardcoded_tmp_path_fails(tmp_path):
    f = tmp_path / "writer.py"
    f.write_text("from pathlib import Path\nout = Path('/tmp/output.log')\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is False
    assert "/tmp" in result["checks"][0]["message"]


def test_tempfile_usage_passes(tmp_path):
    f = tmp_path / "writer.py"
    f.write_text("import tempfile\nout = tempfile.gettempdir()\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is True


def test_guarded_tmp_path_passes(tmp_path):
    f = tmp_path / "writer.py"
    f.write_text("import sys\nif sys.platform == 'linux':\n    path = '/tmp/cache'\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is True


# ===========================================================================
# aplay-only audio detection (gap #7)
# ===========================================================================


def test_aplay_only_audio_fails(tmp_path):
    f = tmp_path / "sound.py"
    f.write_text("import subprocess\nsubprocess.run(['aplay', 'beep.wav'])\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is False
    assert "play" in result["checks"][0]["message"]


def test_guarded_aplay_passes(tmp_path):
    f = tmp_path / "sound.py"
    f.write_text("import subprocess, sys\nif sys.platform == 'linux':\n    subprocess.run(['aplay', 'beep.wav'])\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is True


# ===========================================================================
# shell=True detection (gap #8)
# ===========================================================================


def test_shell_true_fails(tmp_path):
    f = tmp_path / "runner.py"
    f.write_text("import subprocess\nsubprocess.run('ls -la', shell=True)\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is False
    assert "shell=True" in result["checks"][0]["message"]


def test_guarded_shell_true_passes(tmp_path):
    f = tmp_path / "runner.py"
    f.write_text("import subprocess, sys\nif sys.platform != 'win32':\n    subprocess.run('ls -la', shell=True)\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is True


def test_shell_false_passes(tmp_path):
    f = tmp_path / "runner.py"
    f.write_text("import subprocess\nsubprocess.run(['ls', '-la'], shell=False)\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

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
        "    main()\n"
    )
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

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
        "    main()\n"
    )
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

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
        "    main()\n"
    )
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is True


def test_rich_non_entry_passes(tmp_path):
    f = tmp_path / "helper.py"
    f.write_text("from rich.console import Console\nc = Console()\nc.print('hi')\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is True


# ===========================================================================
# os.kill(pid, 0) signal-0 detection (#682)
# ===========================================================================


def test_os_kill_signal0_unguarded_fails(tmp_path):
    f = tmp_path / "probe.py"
    f.write_text("import os\nos.kill(pid, 0)\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is False
    assert "os.kill(pid, 0)" in result["checks"][0]["message"]


def test_os_kill_sigterm_not_flagged_by_signal0(tmp_path):
    f = tmp_path / "killer.py"
    f.write_text("import os, signal\ntry:\n    os.kill(pid, signal.SIGTERM)\nexcept OSError:\n    pass\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is True


def test_os_kill_signal0_platform_guarded_passes(tmp_path):
    f = tmp_path / "probe.py"
    f.write_text("import os, sys\nif sys.platform != 'win32':\n    os.kill(pid, 0)\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

    result = check_module(str(f))
    assert result["passed"] is True


def test_os_kill_signal0_try_except_still_fails(tmp_path):
    f = tmp_path / "probe.py"
    f.write_text("import os\ntry:\n    os.kill(pid, 0)\nexcept OSError:\n    pass\n")
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

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
        "        return False\n"
    )
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

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
        "        return False\n"
    )
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_module

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


def _races(source):
    import ast

    from aipass.seedgo.apps.handlers.aipass_standards.exclusive_create_race import find_exclusive_create_races
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import _platform_guarded_lines

    tree = ast.parse(source)
    return find_exclusive_create_races(tree, _platform_guarded_lines(tree))


def _advisory_branch(root, source, rel="apps/handlers/lock.py"):
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    return root


def test_lock_race_incident_shape_escapes():
    races = _races(_INCIDENT_LOCK)
    assert [line for line, _ in races] == [7]
    assert "_store_lock()" in races[0][1] and "escapes" in races[0][1]


def test_lock_race_permission_error_polled_is_clean():
    cured = _INCIDENT_LOCK.replace(
        "    return descriptor\n",
        "        except PermissionError:\n            time.sleep(0.05)\n    return descriptor\n",
    )
    assert _races(cured) == []


def test_lock_race_oserror_giving_up_inside_retry_loop_flagged():
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
    races = _races(source)
    assert [line for line, _ in races] == [6]
    assert "gives up" in races[0][1] and "L10" in races[0][1]


def test_lock_race_single_shot_oserror_same_outcome_is_clean():
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
    assert _races(source) == []


def test_lock_race_fresh_name_per_attempt_is_clean():
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
    assert _races(source) == []


def test_lock_race_platform_guarded_is_clean():
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
    assert _races(source) == []


def test_lock_race_outer_try_catching_oserror_is_clean():
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
    assert _races(source) == []


def test_lock_race_open_x_mode_escapes():
    source = (
        "def write_pid(pid_file, pid):\n"
        "    try:\n"
        "        with open(pid_file, 'x', encoding='utf-8') as fh:\n"
        "            fh.write(str(pid))\n"
        "    except FileExistsError:\n"
        "        return False\n"
        "    return True\n"
    )
    assert [line for line, _ in _races(source)] == [3]


def test_lock_race_create_without_exists_handler_is_ignored():
    source = "import os\n\ndef create(p):\n    return os.open(p, os.O_CREAT | os.O_EXCL)\n"
    assert _races(source) == []


def test_lock_race_advisory_line_never_reaches_the_score(tmp_path):
    branch = _advisory_branch(tmp_path, _INCIDENT_LOCK)
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_branch_info, check_module

    assert check_branch_info(str(branch)) == [
        "windows_compat lock race (advisory): apps/handlers/lock.py:7 exclusive create in _store_lock() catches "
        "FileExistsError only - a Windows delete-pending PermissionError escapes where 'exists' is handled"
    ]
    result = check_module(str(branch / "apps" / "handlers" / "lock.py"))
    assert result["score"] == 100 and result["passed"] is True


def test_lock_race_advisory_corpus_is_apps_only(tmp_path):
    for rel in ("tests/lock_probe.py", "apps/handlers/.archive/old_lock.py", "tools/lock_tool.py"):
        _advisory_branch(tmp_path, _INCIDENT_LOCK, rel=rel)
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_branch_info

    assert check_branch_info(str(tmp_path)) == []


def test_lock_race_advisory_respects_line_bypass(tmp_path):
    import sys

    branch = _advisory_branch(tmp_path, _INCIDENT_LOCK)
    handler = sys.modules["aipass.seedgo.apps.handlers.bypass.bypass_handler"]
    handler.load_bypass_rules.return_value = [
        {"file": "apps/handlers/lock.py", "standard": "windows_compat", "lines": [7], "reason": "test"}
    ]
    from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import check_branch_info

    assert check_branch_info(str(branch)) == []
    handler.load_bypass_rules.assert_called_once_with(str(branch))
