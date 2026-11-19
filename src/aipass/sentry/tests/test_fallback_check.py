# =================== AIPass ====================
# Name: test_fallback_check.py
# Description: fallback_check — a failure answered with a stand-in, one test per shape on a true corpus site
# Version: 1.3.0
# Created: 2026-11-14
# Modified: 2026-11-17
# =============================================

"""Tests for apps/handlers/aipass_standards/fallback_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(shared) — matching_rule's own file and scope matching; tests/test_bypass.py
# sentry: no-test-needed(constant) — the prose of CURE; its presence in the message is asserted

import pytest

from aipass.sentry.apps.handlers.aipass_standards import fallback_check as checker
from aipass.sentry.apps.handlers.aipass_standards import skip_dirs
from aipass.sentry.apps.modules import checklist

# drone/apps/handlers/command_registry/formatters.py:14-20 (fb_core: "@cli console ImportError -> bare Rich console")
IMPORT_STAND_IN = """from aipass.prax import logger

try:
    from aipass.cli.apps.modules import console
except ImportError:
    logger.warning("CLI console not available, falling back to default Rich Console")
    from rich.console import Console

    console = Console()
"""

# hooks/apps/handlers/config/trust_registry.py:44-56 (fb_hooks finding 1: corrupt registry -> every enrollment lost)
UNREADABLE_READ = """import json

from aipass.prax import logger


def read_registry(path):
    if not path.exists():
        return {"version": 1, "projects": {}}
    try:
        data = json_files.read_json_file(path)
        if not isinstance(data.get("projects"), dict):
            return {"version": 1, "projects": {}}
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("[HOOKS] bad trust registry %s: %s", path, exc)
        return {"version": 1, "projects": {}}
"""

# spawn/apps/handlers/registry.py:50-72 (fb_core: "SAFETY CHECK: registry unreadable -> 'not protected'")
GATE_READS_PASSED = """from aipass.prax import logger


def is_protected(branch_name, rp):
    try:
        for entry in branches_as_list(rp):
            if entry.get("owner") is True:
                return True, "registry owner"
    except (KeyError, TypeError) as exc:
        logger.info("[is_protected] Registry lookup failed for %s: %s", branch_name, exc)
    return False, ""
"""

# drone/apps/handlers/git/commit_handler.py:79-104 (fb_core finding 1: the commit lint gate passes when ruff is missing)
MISSING_TOOL = """import shutil


def _ruff_bin(repo_root):
    venv_ruff = repo_root / ".venv" / "bin" / "ruff"
    return shutil.which("ruff") or (str(venv_ruff) if venv_ruff.exists() else None)


def _lint_gate(repo_root):
    ruff_bin = _ruff_bin(repo_root)
    targets = [p for p in ("src", "tests") if (repo_root / p).is_dir()]
    if not ruff_bin or not targets:
        return None, []
    return run(ruff_bin, targets)
"""

# backup/apps/handlers/cleanup/mirror.py:18-26 (a handler that names itself best-effort and logs a warning)
DISGUISED = """from aipass.prax import logger


def _make_writable(path):
    try:
        path.chmod(0o700)
    except OSError as exc:
        logger.warning("[mirror] best-effort chmod failed on %s: %s", path, exc)
"""

# aipass/apps/handlers/admin_lane.py:115-120 (fb_core: "logger.info/debug only")
QUIET = """from aipass.prax import logger


def admin_lane_state():
    try:
        entry = _holder_entry()
    except _Unreadable as exc:
        logger.info("[admin_lane] registry already named unreadable: %s", exc)
        entry = None
    return bool(entry and entry.get("admin") is True)
"""

# aipass/apps/handlers/sandbox_check/sandbox_checker.py:69-76 (fb_core LOUD: "failure carried to user")
CARRIED = """from aipass.prax import logger


def check_bwrap_functional():
    try:
        return run_bwrap()
    except OSError as exc:
        logger.warning("[sandbox_check] bwrap functional test error: %s", exc)
        return {"ok": False, "detail": str(exc), "sysctl_value": None}
"""

# trigger/apps/handlers/log_watcher.py:240-247 (a format loop: the next candidate is tried, nothing stands in)
NEXT_CANDIDATE = """from datetime import datetime


def parse(body, formats):
    for fmt in formats:
        try:
            return datetime.strptime(body, fmt)
        except ValueError:
            continue
    raise ValueError(body)
"""


# aipass/apps/modules/doctor.py:186-198 (fb_core LOUD: the reason rides inside the check row it returns)
REASON_IN_A_RECORD = """import json

from aipass.prax import logger


def _check_global_aipass_home(settings_path):
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.info("[doctor] global settings.json unreadable: %s", exc)
        return [CheckResult("global settings", GLYPH_FAIL, "global settings.json unreadable", "Repair its JSON")]
    return [CheckResult("global settings", GLYPH_PASS, str(data), "")]
"""

# sentry/apps/handlers/aipass_standards/logged_fallback_check.py:225-229 (fb_rest LOGGED: unparseable scores 100)
SUCCESS_WITH_A_NOTE = """import ast

from aipass.prax import logger


def check_module(module_path, source):
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        logger.info("[logged_fallback] Unparseable %s: %s", module_path, exc)
        return _result(True, _one_check(True, "Not judged: the file does not parse (ruff convicts that)"), 100)
    return tree
"""

# drone/apps/handlers/scanning/scanner.py:84-92 (fb_core LOUD: the unreadable module is skipped with a warning)
WARNED_SKIP = """from aipass.prax import logger


def scan_module_files(modules_dir):
    for py_file in sorted(modules_dir.glob("*.py")):
        try:
            source = py_file.read_text(encoding="utf-8")
        except OSError:
            logger.warning("scan_module_files: could not read %s", py_file)
            continue
        yield source
"""

# drone/apps/handlers/broker/daemon.py:239-243 (fb_core LOGGED: "logger.info/debug only")
INFO_SKIP = """from aipass.prax import logger


def _delete(bases, agent_path):
    for base in bases:
        try:
            parent_fd, name, resolved = open_parent_beneath(base, agent_path)
        except OSError as exc:
            logger.info("broker: base %s skipped for %s: %s", base, agent_path, exc)
            continue
        yield resolved
"""

# drone/apps/modules/git_module.py:695-700 (fb_core LOUD: the missing plugin comes back as stderr and exit 1)
IMPORT_FAILURE_RETURNED = """from aipass.prax import logger


def _handle_merge(pr, caller):
    try:
        from aipass.drone.apps.plugins.devpulse_ops.merge_plugin import merge_pr
    except ImportError as exc:
        logger.error("Failed to import devpulse_ops merge plugin: %s", exc)
        return {"stdout": "", "stderr": f"devpulse_ops plugin not available: {exc}", "exit_code": 1}
    return merge_pr(pr, caller)
"""

# memory/apps/handlers/monitor/memory_watcher.py:25-34 (fb_data SILENT: watchdog missing -> Observer=None)
IMPORT_FLAG = """import logging

logger = logging.getLogger(__name__)

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEventHandler = object
    logger.info("Optional dependency 'watchdog' not available")
"""

# hooks/apps/hooks.py:47-51 (fb_hooks LOGGED: a module raising at import is skipped, its command vanishes)
IMPORT_SKIPPED = """import importlib

from aipass.prax import logger


def discover_modules(names):
    modules = []
    for module_name in names:
        try:
            module = importlib.import_module(module_name)
        except Exception as e:
            logger.error("[HOOKS] Failed to load module %s: %s", module_name, e)
            continue
        modules.append(module)
    return modules
"""

# aipass/apps/handlers/init/scaffold_manifest.py:159-168 (fb_core LOUD: absent is [], unreadable raises)
ABSENT_FILE = """from aipass.prax import logger


def read_ignore(path):
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("[scaffold] %s is there but cannot be read: %s", path, exc)
        raise UpdateIgnoreUnreadable(f"{path} is there but cannot be read ({exc})") from exc
    return raw.splitlines()
"""

# drone/apps/handlers/rm_handler.py:528-539 (fb_core LOGGED: "logger.info/debug only"; lstat is no read)
VANISHED_DEBUG_SKIP = """from aipass.prax import logger


def stale_files(here, filenames):
    for name in filenames:
        path = here / name
        try:
            info = path.lstat()
        except FileNotFoundError:
            logger.debug("rm --stale: %s vanished before it could be read", path)
            continue
        except OSError as exc:
            _unreadable(exc)
            continue
        yield path, info
"""


# daemon/apps/handlers/schedule/command_job.py:138-145 (signal_group)
GROUP_ALREADY_GONE = """import os

from aipass.prax import logger


def signal_group(pid, sig):
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        logger.info("process group %s already gone before signal %s", pid, sig)
"""

# ai_mail/apps/handlers/dispatch/pid_lock.py:203-209 (check_pid_alive)
PROBE_ANSWERS_DEAD = """import os

from aipass.prax import logger


def check_pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError as exc:
        logger.warning("PID %s not found: %s", pid, exc)
        return False
    return True
"""

# hooks/apps/handlers/parity/runner.py:244-248 (_pointer_stamp: an absent pointer is 0.0, never written)
STAMP_ABSENT = """def pointer_stamp(branch):
    try:
        return (branch / "session.json").stat().st_mtime
    except FileNotFoundError:
        return 0.0
"""

# hooks/apps/modules/protected_paths.py:131-139 (_by_identity: a file not yet written has one name)
NOT_YET_WRITTEN = """import os

from aipass.prax import logger


def by_identity(target):
    info = None
    try:
        info = os.stat(target)
    except FileNotFoundError as exc:
        logger.debug("no file at %s: %s", target, exc)
    if info is None or info.st_nlink < 2:
        return None
    return info.st_ino
"""

# hooks/apps/modules/cadence.py:129-138 (transcript size: absent on turn 0, any other stat failure warns)
NO_TRANSCRIPT_YET = """import os

from aipass.prax import logger


def transcript_size(tp):
    try:
        return os.path.getsize(tp)
    except FileNotFoundError:
        logger.debug("no transcript yet (turn 0): %s", tp)
        return -1
    except OSError as exc:
        logger.warning("transcript stat failed: %s", exc)
        return -1
"""


def _plant(tmp_path, source, name="site.py"):
    """The path of ``source`` written under apps/."""
    apps = tmp_path / "apps"
    apps.mkdir(exist_ok=True)
    path = apps / name
    path.write_text(source, encoding="utf-8")
    return str(path)


def _message(tmp_path, source, rules=None):
    """(score, the one check's message) for a planted file."""
    result = checker.check_module(_plant(tmp_path, source), bypass_rules=rules)
    return result["score"], result["checks"][0]["message"]


class TestEachShapeIsFlaggedOnItsCorpusSite:
    def test_an_import_failure_stand_in_is_flagged_even_with_a_warning(self, tmp_path):
        score, message = _message(tmp_path, IMPORT_STAND_IN)
        assert score == 0
        assert message.startswith("site.py:5 import-failure stand-in - ")

    def test_a_corrupt_registry_served_as_empty_is_flagged_even_with_an_error_log(self, tmp_path):
        score, message = _message(tmp_path, UNREADABLE_READ)
        assert score == 0
        assert message.startswith("site.py:14 unreadable file read as a default - ")

    def test_a_safety_check_that_cannot_look_and_answers_not_protected_is_flagged(self, tmp_path):
        score, message = _message(tmp_path, GATE_READS_PASSED)
        assert score == 0
        assert message.startswith("site.py:9 check that cannot run reads as passed (is_protected) - ")

    def test_a_lint_gate_that_passes_when_ruff_is_missing_is_flagged(self, tmp_path):
        score, message = _message(tmp_path, MISSING_TOOL)
        assert score == 0
        assert message.startswith("site.py:12 a missing tool reads as passed - ")

    def test_a_handler_that_calls_itself_best_effort_is_flagged_despite_its_warning(self, tmp_path):
        score, message = _message(tmp_path, DISGUISED)
        assert score == 0
        assert message.startswith("site.py:7 fallback disguised as 'best-effort' - ")

    def test_an_info_only_handler_that_stands_in_none_is_flagged(self, tmp_path):
        score, message = _message(tmp_path, QUIET)
        assert score == 0
        assert message == f"site.py:7 default with no warning-level log - {checker.CURE}"


class TestWhatIsNotAFallback:
    def test_a_handler_returning_the_failure_as_a_reason_passes(self, tmp_path):
        assert _message(tmp_path, CARRIED) == (100, "No unwaived fallback")

    def test_a_loop_that_tries_its_next_format_passes(self, tmp_path):
        assert _message(tmp_path, NEXT_CANDIDATE) == (100, "No unwaived fallback")

    def test_a_handler_that_re_raises_passes(self, tmp_path):
        source = QUIET.replace("        entry = None\n", "        raise\n")
        assert _message(tmp_path, source) == (100, "No unwaived fallback")

    def test_a_reason_inside_the_record_a_check_returns_passes(self, tmp_path):
        assert _message(tmp_path, REASON_IN_A_RECORD) == (100, "No unwaived fallback")

    def test_a_record_that_claims_success_with_a_note_still_flags(self, tmp_path):
        score, message = _message(tmp_path, SUCCESS_WITH_A_NOTE)
        assert score == 0
        assert message.startswith("site.py:9 unreadable file read as a default - ")

    def test_a_loop_that_warns_and_skips_an_unreadable_file_passes(self, tmp_path):
        assert _message(tmp_path, WARNED_SKIP) == (100, "No unwaived fallback")

    def test_a_skip_logged_only_at_info_still_flags(self, tmp_path):
        score, message = _message(tmp_path, INFO_SKIP)
        assert score == 0
        assert message.startswith("site.py:8 default with no warning-level log - ")

    def test_an_import_failure_returned_to_the_caller_as_stderr_passes(self, tmp_path):
        assert _message(tmp_path, IMPORT_FAILURE_RETURNED) == (100, "No unwaived fallback")

    def test_an_import_failure_answered_with_an_availability_flag_still_flags(self, tmp_path):
        score, message = _message(tmp_path, IMPORT_FLAG)
        assert score == 0
        assert message.startswith("site.py:10 import-failure stand-in - ")

    def test_a_module_skipped_at_import_with_an_error_log_still_flags(self, tmp_path):
        score, message = _message(tmp_path, IMPORT_SKIPPED)
        assert score == 0
        assert message.startswith("site.py:11 import-failure stand-in - ")

    def test_a_missing_file_read_as_empty_passes(self, tmp_path):
        assert _message(tmp_path, ABSENT_FILE) == (100, "No unwaived fallback")

    def test_a_file_not_found_around_neither_a_read_nor_a_stat_still_flags(self, tmp_path):
        assert _message(tmp_path, VANISHED_DEBUG_SKIP.replace("info = path.lstat()", "path.unlink()")) == (
            0,
            f"site.py:9 default with no warning-level log - {checker.CURE}",
        )

    def test_a_signal_to_a_group_already_gone_passes(self, tmp_path):
        """@daemon command_job.signal_group: the group exiting is what the kill was for."""
        assert _message(tmp_path, GROUP_ALREADY_GONE) == (100, "No unwaived fallback")

    def test_a_liveness_probe_that_answers_dead_passes(self, tmp_path):
        assert _message(tmp_path, PROBE_ANSWERS_DEAD) == (100, "No unwaived fallback")

    def test_a_signal_handler_that_also_swallows_os_error_still_flags(self, tmp_path):
        assert _message(
            tmp_path, GROUP_ALREADY_GONE.replace("except ProcessLookupError:", "except (ProcessLookupError, OSError):")
        ) == (
            0,
            f"site.py:9 default with no warning-level log - {checker.CURE}",
        )

    def test_a_lookup_error_around_no_signal_still_flags(self, tmp_path):
        assert _message(tmp_path, GROUP_ALREADY_GONE.replace("os.killpg(pid, sig)", "os.getpgid(pid)")) == (
            0,
            f"site.py:9 default with no warning-level log - {checker.CURE}",
        )


class TestAMissingFileIsTheAnswerToAStat:
    def test_a_path_stat_caught_as_file_not_found_alone_passes(self, tmp_path):
        assert _message(tmp_path, STAMP_ABSENT) == (100, "No unwaived fallback")

    def test_an_os_stat_caught_as_file_not_found_with_a_debug_line_passes(self, tmp_path):
        assert _message(tmp_path, NOT_YET_WRITTEN) == (100, "No unwaived fallback")

    def test_an_lstat_skipped_when_the_file_vanished_passes(self, tmp_path):
        assert _message(tmp_path, VANISHED_DEBUG_SKIP) == (100, "No unwaived fallback")

    def test_a_getsize_answered_beside_a_warning_os_error_handler_passes(self, tmp_path):
        assert _message(tmp_path, NO_TRANSCRIPT_YET) == (100, "No unwaived fallback")

    def test_a_stat_in_a_check_named_function_passes(self, tmp_path):
        assert _message(tmp_path, NOT_YET_WRITTEN.replace("def by_identity", "def is_protected")) == (
            100,
            "No unwaived fallback",
        )

    @pytest.mark.parametrize(
        "caught", ["except OSError:", "except Exception:", "except:", "except (FileNotFoundError, PermissionError):"]
    )
    def test_a_stat_caught_wider_than_file_not_found_still_flags(self, tmp_path, caught):
        assert _message(tmp_path, STAMP_ABSENT.replace("except FileNotFoundError:", caught)) == (
            0,
            f"site.py:4 default with no warning-level log - {checker.CURE}",
        )

    def test_a_stat_followed_by_more_work_in_the_try_still_flags(self, tmp_path):
        probe = "info = os.stat(target)\n"
        source = NOT_YET_WRITTEN.replace(probe, probe + "        os.remove(target)\n")
        assert _message(tmp_path, source) == (0, f"site.py:11 default with no warning-level log - {checker.CURE}")

    def test_two_stats_under_one_catch_still_flag(self, tmp_path):
        probe = "info = os.stat(target)\n"
        source = NOT_YET_WRITTEN.replace(probe, probe + "        info = os.stat(target.parent)\n")
        assert _message(tmp_path, source) == (0, f"site.py:11 default with no warning-level log - {checker.CURE}")

    def test_a_loop_of_stats_under_one_catch_still_flags(self, tmp_path):
        loop = "for each in target:\n            info = os.stat(each)"
        source = NOT_YET_WRITTEN.replace("info = os.stat(target)", loop)
        assert _message(tmp_path, source) == (0, f"site.py:11 default with no warning-level log - {checker.CURE}")

    def test_a_stat_of_a_path_another_call_computes_still_flags(self, tmp_path):
        source = NOT_YET_WRITTEN.replace("os.stat(target)", "os.stat(os.readlink(target))")
        assert _message(tmp_path, source) == (0, f"site.py:10 default with no warning-level log - {checker.CURE}")


class TestWaiversAreOneRowPerSite:
    def test_a_row_pinned_to_the_line_waives_that_site(self, tmp_path):
        rules = [{"file": "apps/site.py", "standard": "fallback", "lines": [14], "reason": "r"}]
        assert _message(tmp_path, UNREADABLE_READ, rules) == (100, "No unwaived fallback")

    def test_a_row_pinned_to_the_function_waives_that_site(self, tmp_path):
        rules = [{"file": "apps/site.py", "standard": "fallback", "functions": ["read_registry"], "reason": "r"}]
        assert _message(tmp_path, UNREADABLE_READ, rules) == (100, "No unwaived fallback")

    def test_a_whole_file_row_waives_nothing(self, tmp_path):
        rules = [{"file": "apps/site.py", "standard": "fallback", "reason": "r"}]
        score, message = _message(tmp_path, UNREADABLE_READ, rules)
        assert score == 0
        assert message.startswith("site.py:14 ")

    def test_a_row_pinned_to_another_line_leaves_the_site_flagged(self, tmp_path):
        rules = [{"file": "apps/site.py", "standard": "fallback", "lines": [13], "reason": "r"}]
        assert _message(tmp_path, UNREADABLE_READ, rules)[0] == 0


class TestTheStandardIsAdvisory:
    @pytest.fixture(autouse=True)
    def _let_tmp_path_be_audited(self, monkeypatch):
        """tmp_path lives under a temp root the checklist skips by default."""
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    def test_the_audit_keeps_it_out_of_the_branch_average(self):
        assert checker.ADVISORY is True

    def test_the_checklist_prints_a_hit_as_advisory_never_as_a_fail(self, tmp_path, capsys):
        checklist.handle_command("checklist", [_plant(tmp_path, QUIET)])
        out, _ = capsys.readouterr()
        assert f"{checklist.ADVICE_MARKER} — fallback: site.py:7 default with no warning-level log" in out
        assert "[FAIL] — fallback" not in out
