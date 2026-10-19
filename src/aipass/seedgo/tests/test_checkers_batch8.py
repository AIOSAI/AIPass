# =================== META ====================
# Name: test_checkers_batch8.py
# Description: Unit tests for handlers, log_handler, log_level, log_structure, meta, naming, permission_flags
# Version: 1.1.0
# Created: 2026-04-25
# Modified: 2026-10-18
# =============================================

"""Tests for apps/handlers/aipass_standards/handlers_check.py and six sibling checkers (batch 8)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the seven checker modules under test parse and import
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(stdlib) — ast.parse's parsing; the checkers only walk the tree it returns

from typing import List

import pytest

from aipass.seedgo.apps.handlers.aipass_standards.handlers_check import (
    _branch_before,
    check_auto_detection,
    check_handler_independence,
    check_no_orchestration,
)
from aipass.seedgo.apps.handlers.aipass_standards.log_handler_check import (
    check_no_raw_file_handler,
    check_no_raw_stream_handler,
)
from aipass.seedgo.apps.handlers.aipass_standards.log_level_check import (
    check_command_routing_level,
    check_error_not_user_input,
)
from aipass.seedgo.apps.handlers.aipass_standards import log_structure_check
from aipass.seedgo.apps.handlers.aipass_standards.log_structure_check import check_branch_info
from aipass.seedgo.apps.handlers.aipass_standards.meta_check import (
    check_meta_placement,
    check_meta_presence,
    check_required_fields,
)
from aipass.seedgo.apps.handlers.aipass_standards.naming_check import (
    PYTEST_CONTRACT_GLOBALS,
    check_class_naming,
    check_constant_naming,
    check_file_naming,
    check_function_naming,
)
from aipass.seedgo.apps.handlers.aipass_standards.permission_flags_check import check_no_dangerous_flags


def _lines(text: str) -> List[str]:
    """Split text into lines, widening LiteralString to str for pyright."""
    return text.split("\n")


def test_handler_independence_clean(tmp_path):
    """Handler with no cross-handler imports passes."""
    content = (
        '"""Clean handler."""\n'
        "from aipass.seedgo.apps.handlers.json import json_handler\n"
        "\ndef do_work():\n    return True\n"
    )
    handler_path = str(tmp_path / "seedgo" / "apps" / "handlers" / "audit" / "clean.py")

    result = check_handler_independence(content, _lines(content), handler_path)
    assert result["passed"] is True


def test_handler_independence_cross_branch_import_fails():
    """Another BRANCH's handlers are private - importing them is the violation."""
    content = (
        '"""Cross branch import."""\n'
        "from aipass.memory.apps.handlers.error import error_handler\n"
        "\ndef do_work():\n    return True\n"
    )
    handler_path = "src/aipass/seedgo/apps/handlers/audit/cross.py"

    result = check_handler_independence(content, _lines(content), handler_path)
    assert result["passed"] is False
    assert "Cross-branch handler imports" in result["message"]


@pytest.mark.parametrize(
    "call",
    [
        'importlib.import_module("aipass.memory.apps.handlers.json.entry_limits")',
        '_import_module("aipass.memory.apps.handlers.json.entry_limits")',
        'pkgutil.resolve_name("aipass.memory.apps.handlers.json.entry_limits")',
        'patch("aipass.memory.apps.handlers.json.entry_limits.load")',
        'monkeypatch.setattr("aipass.memory.apps.handlers.json.entry_limits.load", None)',
        "importlib.import_module(_RAIL)",
    ],
)
def test_handler_independence_reads_a_string_import_of_another_branch(call):
    """A handler named as a call's string reaches the other branch like an import (DPLAN-0404 leg 1)."""
    content = f'_RAIL = "aipass.memory.apps.handlers.json.entry_limits"\n\ndef go():\n    return {call}\n'
    handler_path = "src/aipass/hooks/apps/handlers/security/edit_gate.py"

    result = check_handler_independence(content, _lines(content), handler_path)
    assert result["passed"] is False
    assert f"line 4: return {call} (string import)" in result["message"]


def test_handler_independence_leaves_prose_and_its_own_branch_strings_alone():
    """A docstring example and a same-branch string target are not cross-branch imports."""
    content = (
        '"""Example: importlib.import_module("aipass.memory.apps.handlers.json.entry_limits")."""\n'
        'NOTE = "aipass.memory.apps.handlers.json.entry_limits"\n'
        'logger.info("aipass.memory.apps.handlers.json is memory\'s")\n'
        'mod = importlib.import_module("aipass.hooks.apps.handlers.config.loader")\n'
        'patch.object(holder, "aipass.memory.apps.handlers.json")\n'
    )
    handler_path = "src/aipass/hooks/apps/handlers/security/edit_gate.py"

    result = check_handler_independence(content, _lines(content), handler_path)
    assert result == {
        "name": "Handler independence",
        "passed": True,
        "message": "No forbidden cross-branch handler imports",
    }


def test_handler_independence_same_package(tmp_path):
    """Handler importing from same package passes."""
    content = (
        '"""Same package import."""\n'
        "from aipass.seedgo.apps.handlers.audit import audit_helper\n"
        "\ndef do_work():\n    return True\n"
    )
    handler_path = str(tmp_path / "seedgo" / "apps" / "handlers" / "audit" / "same.py")

    result = check_handler_independence(content, _lines(content), handler_path)
    assert result["passed"] is True


# Same-branch imports are ALLOWED, even across packages: the standard's own documented example does it.


def test_handler_independence_allows_the_standards_own_documented_example():
    """`drone @seedgo standard handlers` prints this exact import as ALLOWED."""
    content = "from aipass.flow.apps.handlers.registry.load import load_registry\n"
    handler_path = "src/aipass/flow/apps/handlers/plan/create.py"

    result = check_handler_independence(content, _lines(content), handler_path)
    assert result["passed"] is True, "Checker rejects the standard's own ALLOWED example"


def test_handler_independence_root_level_file_can_pass():
    """A handler at the handlers/ ROOT is judged by branch, not by its filename."""
    content = (
        "from aipass.trigger.apps.handlers.error_registry import normalize_message\n"
        "from aipass.trigger.apps.handlers import medic_state\n"
    )
    handler_path = "src/aipass/trigger/apps/handlers/escalation.py"

    result = check_handler_independence(content, _lines(content), handler_path)
    assert result["passed"] is True


def test_handler_independence_same_branch_across_packages():
    """Sibling packages inside one branch import each other freely."""
    content = "from aipass.trigger.apps.handlers.medic.state import load\n"
    handler_path = "src/aipass/trigger/apps/handlers/escalation/runner.py"

    result = check_handler_independence(content, _lines(content), handler_path)
    assert result["passed"] is True


def test_handler_independence_cross_branch_json_handler_is_not_exempt():
    """The default-handler exemption must not smuggle a cross-branch import in."""
    content = "from aipass.memory.apps.handlers.json import json_handler\n"
    handler_path = "src/aipass/trigger/apps/handlers/escalation.py"

    result = check_handler_independence(content, _lines(content), handler_path)
    assert result["passed"] is False


def test_handler_independence_absolute_path_resolves_branch(tmp_path):
    """The PostToolUse hook passes absolute paths - branch detection must survive it."""
    content = "from aipass.trigger.apps.handlers.error_registry import n\n"
    handler_path = str(tmp_path / "Projects/AIPass/src/aipass/trigger/apps/handlers/escalation.py")

    result = check_handler_independence(content, _lines(content), handler_path)
    assert result["passed"] is True


def test_handler_independence_unknown_layout_says_so(tmp_path):
    """A path with no branch is reported as not-evaluated, not silently passed."""
    content = "from aipass.memory.apps.handlers.error import error_handler\n"

    result = check_handler_independence(content, _lines(content), str(tmp_path / "random/path/handler.py"))
    assert result["passed"] is True
    assert "could not be determined" in result["message"]


def test_handler_independence_fstring_guard_text_not_flagged(tmp_path):
    """An f-string that mentions apps.handlers as help text is not a real import."""
    content = (
        "def guard():\n"
        "    raise ImportError(\n"
        '        f"    from aipass.seedgo.apps.handlers.error import error_handler\\n"\n'
        "    )\n"
    )
    handler_path = str(tmp_path / "apps" / "handlers" / "audit" / "guard.py")

    result = check_handler_independence(content, _lines(content), handler_path)
    assert result["passed"] is True


def test_handler_independence_flags_real_import_alongside_guard_text(tmp_path):
    """A real cross-handler import is still caught even when guard text sits nearby."""
    content = (
        "from aipass.seedgo.apps.handlers.error import error_handler\n"
        "\n"
        "def guard():\n"
        "    raise ImportError(\n"
        '        f"    from aipass.seedgo.apps.handlers.error import error_handler\\n"\n'
        "    )\n"
    )
    handler_path = str(tmp_path / "apps" / "handlers" / "audit" / "mixed.py")

    result = check_handler_independence(content, _lines(content), handler_path)
    assert result["passed"] is False
    assert "line 1" in result["message"]


def test_auto_detection_not_needed():
    """No module_name parameter means auto-detection is not needed (returns None)."""
    content = "def do_work(file_path):\n    return True\n"

    result = check_auto_detection(content)
    assert result is None


def test_auto_detection_present():
    """Handler with module_name and inspect.stack() passes."""
    content = "import inspect\ndef do_work(module_name=None):\n    frame = inspect.stack()\n    return True\n"

    result = check_auto_detection(content)
    assert result is not None
    assert result["passed"] is True


def test_auto_detection_missing():
    """Handler with module_name but no inspect.stack() fails."""
    content = "def do_work(module_name=None):\n    return True\n"

    result = check_auto_detection(content)
    assert result is not None
    assert result["passed"] is False
    assert "never reads the caller frame" in result["message"]
    # Pinned as a refusal: inspect.stack() is the Windows dead-cwd defect, never a "clearer" instruction.
    assert "use sys._getframe" in result["message"]
    assert "NOT inspect.stack()" in result["message"]


def test_auto_detection_judges_an_unparseable_file_strictly():
    """An unparseable file that names module_name is CONVICTED, never acquitted (fleet green
    leg 15), and the finding says it did not parse."""
    content = "def do_work(module_name=None:\n    return True\n"

    result = check_auto_detection(content)
    assert result is not None
    assert result["passed"] is False
    assert result["message"].startswith("Does not parse"), result["message"]


def test_auto_detection_with_get_caller():
    """Handler with _get_caller_module_name passes auto-detection."""
    content = "def _get_caller_module_name():\n    pass\ndef do_work(module_name=None):\n    return True\n"

    result = check_auto_detection(content)
    assert result is not None
    assert result["passed"] is True


def test_no_orchestration_clean():
    """Handler with no module imports passes."""
    content = '"""Clean handler."""\n\ndef do_work():\n    return True\n'

    result = check_no_orchestration(content, _lines(content))
    assert result is not None
    assert result["passed"] is True


def test_no_orchestration_module_import():
    """Handler importing from apps.modules fails."""
    content = (
        '"""Bad handler."""\nfrom aipass.seedgo.apps.modules import audit_module\n\ndef do_work():\n    return True\n'
    )

    result = check_no_orchestration(content, _lines(content))
    assert result is not None
    assert result["passed"] is False
    assert "orchestration" in result["message"]


def test_branch_before_says_none_rather_than_guessing():
    """A missing marker returns None, never the whole string."""

    assert _branch_before("aipass.spawn.apps.modules", ".apps.handlers") is None
    assert _branch_before("aipass.spawn.apps.modules", ".apps.modules") == "spawn"
    assert _branch_before("aipass.seedgo.apps.handlers.json", ".apps.handlers") == "seedgo"
    assert _branch_before(".apps.handlers.x", ".apps.handlers") is None


def test_no_orchestration_allows_another_branchs_modules_gateway(tmp_path):
    """Consuming ANOTHER branch's modules/ is the sanctioned door, not orchestration."""
    content = '"""Handler."""\nfrom aipass.spawn.apps.modules import get_template_dir\n'

    result = check_no_orchestration(
        content, _lines(content), str(tmp_path / "repo/src/aipass/seedgo/apps/handlers/x/y.py")
    )
    assert result is not None
    assert result["passed"] is True, result["message"]


def test_no_orchestration_still_flags_own_branch_modules(tmp_path):
    """The real layering violation survives: a handler reaching up its OWN branch."""
    content = '"""Handler."""\nfrom aipass.seedgo.apps.modules import audit_module\n'

    result = check_no_orchestration(
        content, _lines(content), str(tmp_path / "repo/src/aipass/seedgo/apps/handlers/x/y.py")
    )
    assert result is not None
    assert result["passed"] is False
    assert "orchestration" in result["message"]


def test_no_orchestration_unknown_path_stays_strict():
    """No path means the branch is unknown -- flag, never assume cross-branch."""
    content = '"""Handler."""\nfrom aipass.spawn.apps.modules import get_template_dir\n'

    result = check_no_orchestration(content, _lines(content))
    assert result is not None
    assert result["passed"] is False


def test_no_orchestration_in_docstring():
    """Module import inside docstring is not flagged."""
    content = (
        '"""\nExample: from aipass.seedgo.apps.modules import audit_module\n"""\n\ndef do_work():\n    return True\n'
    )

    result = check_no_orchestration(content, _lines(content))
    assert result is not None
    assert result["passed"] is True


def test_no_orchestration_fstring_guard_text_not_flagged():
    """An import-guard error message built from an f-string is not a real import."""
    content = (
        "MY_BRANCH = 'aipass.seedgo'\n"
        "def guard():\n"
        "    raise ImportError(\n"
        '        f"    from {MY_BRANCH}.apps.modules.<module> import <function>\\n"\n'
        "    )\n"
    )

    result = check_no_orchestration(content, _lines(content))
    assert result is not None
    assert result["passed"] is True


def test_no_orchestration_flags_real_import_alongside_guard_text():
    """A real module import is still caught even when guard text sits nearby."""
    content = (
        "from aipass.seedgo.apps.modules.scanner import scan_all\n"
        "\n"
        "def guard():\n"
        "    raise ImportError(\n"
        '        f"    from aipass.seedgo.apps.modules.<module> import <function>\\n"\n'
        "    )\n"
    )

    result = check_no_orchestration(content, _lines(content))
    assert result is not None
    assert result["passed"] is False
    assert "line 1" in result["message"]


def test_no_raw_file_handler_clean(tmp_path):
    """File without logging.FileHandler passes."""
    lines: List[str] = [
        '"""Clean module."""',
        "import logging",
        "logger = logging.getLogger(__name__)",
        "",
    ]

    result = check_no_raw_file_handler(lines, str(tmp_path / "fake/path.py"))
    assert result["passed"] is True


def test_no_raw_file_handler_violation(tmp_path):
    """File with logging.FileHandler fails."""
    lines: List[str] = [
        '"""Bad module."""',
        "import logging",
        'handler = logging.FileHandler("app.log")',
        "",
    ]

    result = check_no_raw_file_handler(lines, str(tmp_path / "fake/path.py"))
    assert result["passed"] is False
    assert "FileHandler" in result["message"]


def test_no_raw_stream_handler_no_file_logging(tmp_path):
    """No file-based logging means stream handler check not applicable."""
    lines: List[str] = [
        "import logging",
        "logger = logging.getLogger(__name__)",
        "",
    ]
    content = "\n".join(lines)

    result = check_no_raw_stream_handler(lines, str(tmp_path / "fake/path.py"), content)
    assert result["passed"] is True
    assert "not applicable" in result["message"]


def test_no_raw_stream_handler_violation(tmp_path):
    """StreamHandler with file logging is a violation."""
    lines: List[str] = [
        "import logging",
        'handler = logging.FileHandler("app.log")',
        "stream = logging.StreamHandler()",
        "",
    ]
    content = "\n".join(lines)

    result = check_no_raw_stream_handler(lines, str(tmp_path / "fake/path.py"), content)
    assert result["passed"] is False
    assert "StreamHandler" in result["message"]


def test_no_raw_stream_handler_clean(tmp_path):
    """File logging present but no StreamHandler passes."""
    lines: List[str] = [
        "import logging",
        'handler = logging.FileHandler("app.log")',
        "",
    ]
    content = "\n".join(lines)

    result = check_no_raw_stream_handler(lines, str(tmp_path / "fake/path.py"), content)
    assert result["passed"] is True


def test_error_not_user_input_clean(tmp_path):
    """ERROR used for system failures passes."""
    lines: List[str] = [
        '"""Module."""',
        'logger.error("System crash: %s", error)',
        "",
    ]

    result = check_error_not_user_input(lines, str(tmp_path / "fake/path.py"))
    assert result["passed"] is True


def test_error_not_user_input_violation(tmp_path):
    """ERROR used for user-input pattern fails."""
    lines: List[str] = [
        '"""Module."""',
        'logger.error("Unknown command: %s", cmd)',
        "",
    ]

    result = check_error_not_user_input(lines, str(tmp_path / "fake/path.py"))
    assert result["passed"] is False
    assert "user input" in result["message"]


def test_error_not_user_input_in_docstring(tmp_path):
    """ERROR pattern inside a docstring is ignored."""
    lines: List[str] = [
        '"""',
        'logger.error("Unknown command: %s", cmd)',
        '"""',
        "pass",
        "",
    ]

    result = check_error_not_user_input(lines, str(tmp_path / "fake/path.py"))
    assert result["passed"] is True


def test_command_routing_level_no_routing(tmp_path):
    """File without command routing returns None."""
    content = "def do_work():\n    pass\n"

    result = check_command_routing_level(content, _lines(content), str(tmp_path / "fake/path.py"))
    assert result is None


def test_command_routing_level_clean(tmp_path):
    """Command routing with proper WARNING level passes."""
    content = 'def route_command(cmd):\n    logger.warning("Unknown command: %s", cmd)\n'

    result = check_command_routing_level(content, _lines(content), str(tmp_path / "fake/path.py"))
    assert result is not None
    assert result["passed"] is True


def test_command_routing_level_violation(tmp_path):
    """Command routing with ERROR for user-input pattern fails."""
    content = 'def route_command(cmd):\n    logger.error("Unknown command: %s", cmd)\n'

    result = check_command_routing_level(content, _lines(content), str(tmp_path / "fake/path.py"))
    assert result is not None
    assert result["passed"] is False
    assert result["message"] == "Command routing failures logged as ERROR on lines [2] - should be WARNING"


# Local logs without system_logs are reported through check_branch_info(), never scored: @cli's healthy
# zero is the success case (prax cannot be imported there), and a score read off live log files moves
# with rotation, not with the code.


def _branch_with_local_logs(tmp_path, name="mybranch", local_logs=1):
    """A branch root with local logs/ under a repo root carrying system_logs/."""
    branch = tmp_path / name
    branch.mkdir()
    logs_dir = branch / "logs"
    logs_dir.mkdir()
    for i in range(local_logs):
        (logs_dir / f"app{i}.log").write_text("log line", encoding="utf-8")
    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    (tmp_path / "system_logs").mkdir()
    return branch


def test_system_log_observation_carries_no_score():
    """The branch-level scoring surface is gone -- runtime log state cannot move a score."""

    assert not hasattr(log_structure_check, "check_branch_post"), (
        "log_structure must expose no branch-level scoring surface: the only thing it scored "
        "was a count of live log files, which changes with no code change"
    )


def test_error_path_only_branch_is_not_penalised(tmp_path):
    """@cli's shape: local logs, zero system logs, and nothing scored for it."""
    branch = _branch_with_local_logs(tmp_path, local_logs=3)
    module = branch / "apps" / "cli.py"
    module.parent.mkdir(parents=True)
    module.write_text('"""Entry."""\nlogger.error("module load failed")\n', encoding="utf-8")

    before = log_structure_check.check_module(str(module))
    # A system log appears (or rotates away) -- the same code, a different
    # moment. The score must not notice.
    (tmp_path / "system_logs" / "mybranch_cli.log").write_text("system", encoding="utf-8")
    after = log_structure_check.check_module(str(module))

    assert before["score"] == 100
    assert after["score"] == before["score"]
    assert [c["name"] for c in after["checks"]] == [c["name"] for c in before["checks"]]


def test_observe_lane_accepts_the_kwarg_the_pipeline_passes(tmp_path):
    """The exact defect that killed this observation must not recur."""
    branch = _branch_with_local_logs(tmp_path, local_logs=3)

    observe = getattr(log_structure_check, "check_branch_observe")
    records = observe(str(branch), bypass_rules=[])

    assert isinstance(records, list) and records, "the observe lane reports one reading per branch, always"


def test_observe_records_would_be_score_and_when(tmp_path):
    """The reading carries the score it WOULD have given, and the moment it was taken."""
    from datetime import datetime

    branch = _branch_with_local_logs(tmp_path, local_logs=3)

    observe = getattr(log_structure_check, "check_branch_observe")
    record = observe(str(branch), bypass_rules=[])[0]

    assert record["standard"] == "log_structure"
    assert record["branch"] == "mybranch"
    assert record["local_logs"] == 3
    assert record["system_logs"] == 0
    assert record["would_be_score"] == 50, "the old check_branch_post scored exactly this"
    datetime.fromisoformat(record["observed_at"])


def test_observe_reads_100_when_system_logs_are_present(tmp_path):
    """The healthy reading — same shape, so 'never fired' is provable, not inferred."""
    branch = _branch_with_local_logs(tmp_path, local_logs=3)
    (tmp_path / "system_logs" / "mybranch_cli.log").write_text("system", encoding="utf-8")

    observe = getattr(log_structure_check, "check_branch_observe")
    record = observe(str(branch))[0]

    assert record["system_logs"] == 1
    assert record["would_be_score"] == 100


def test_observe_excludes_mail_lane_artifacts(tmp_path):
    """dispatch_*.log is @ai_mail's delivery artifact, not the branch's log."""
    branch = _branch_with_local_logs(tmp_path, local_logs=0)
    (branch / "logs" / "dispatch_20260814.log").write_text("delivery", encoding="utf-8")

    observe = getattr(log_structure_check, "check_branch_observe")
    record = observe(str(branch))[0]

    assert record["local_logs"] == 0, "a mail-lane artifact is not a branch log"
    assert record["would_be_score"] == 100


def test_observe_reports_unobservable_branch_without_a_number(tmp_path):
    """No repo root / no system_logs/ — the old check produced no score, nor does this."""
    branch = tmp_path / "orphan"
    (branch / "logs").mkdir(parents=True)
    (branch / "logs" / "app.log").write_text("log", encoding="utf-8")

    observe = getattr(log_structure_check, "check_branch_observe")
    record = observe(str(branch))[0]

    assert record["would_be_score"] is None
    assert record["observable"] is False


def test_observe_honours_a_branch_bypass(tmp_path):
    """bypass_rules is not decoration — a bypassed branch reads as bypassed."""
    branch = _branch_with_local_logs(tmp_path, local_logs=3)

    rules = [{"file": "mybranch", "standard": "log_structure", "reason": "test"}]
    observe = getattr(log_structure_check, "check_branch_observe")
    record = observe(str(branch), bypass_rules=rules)[0]

    assert record["bypassed"] is True
    assert record["would_be_score"] is None


def test_check_branch_info_reports_missing_system_logs(tmp_path):
    """The observation survives -- as an info line, on the channel that carries no score."""
    branch = _branch_with_local_logs(tmp_path, local_logs=3)

    # Resolved off the module exactly as branch_audit does (getattr on a
    # dynamically discovered checker, called positionally with the branch path),
    # so this pins the runtime call form the pipeline uses.
    info = getattr(log_structure_check, "check_branch_info")
    lines = info(str(branch))

    assert len(lines) == 1
    assert all(isinstance(line, str) for line in lines), "info lines are plain strings, never scored dicts"
    assert "mybranch" in lines[0]
    assert "system log" in lines[0].lower()
    assert "3" in lines[0]


def test_dispatch_artifacts_are_not_the_branchs_logs(tmp_path):
    """logs/dispatch_*.log belongs to @ai_mail's lane, not the branch's logging."""
    branch = _branch_with_local_logs(tmp_path, local_logs=0)
    logs = branch / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    for name in ("dispatch_stderr.log", "dispatch_stdout.log", "dispatch_wake.log"):
        (logs / name).write_text("mail lane", encoding="utf-8")

    assert check_branch_info(str(branch)) == []


def test_real_logs_still_counted_alongside_dispatch_artifacts(tmp_path):
    """Control -- a branch's own log still reports, and the count excludes the artifacts."""
    branch = _branch_with_local_logs(tmp_path, local_logs=1)
    (branch / "logs" / "dispatch_wake.log").write_text("mail lane", encoding="utf-8")

    lines = check_branch_info(str(branch))
    assert len(lines) == 1
    assert "1 local log(s)" in lines[0]


def test_check_branch_info_silent_when_system_logs_exist(tmp_path):
    """Nothing to signpost when prax is dispatching for the branch."""
    branch = _branch_with_local_logs(tmp_path)
    (tmp_path / "system_logs" / "mybranch_module.log").write_text("system log", encoding="utf-8")

    assert check_branch_info(str(branch)) == []


def test_check_branch_info_silent_without_local_logs(tmp_path):
    """No local logs means the branch has not logged at all -- nothing to compare."""
    branch = tmp_path / "mybranch"
    branch.mkdir()
    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    (tmp_path / "system_logs").mkdir()

    assert check_branch_info(str(branch)) == []


def test_check_branch_info_silent_outside_a_repo(tmp_path):
    """No AIPASS_REGISTRY.json / system_logs/ above the branch -- nothing to observe."""
    branch = tmp_path / "mybranch"
    (branch / "logs").mkdir(parents=True)
    (branch / "logs" / "app.log").write_text("log line", encoding="utf-8")

    assert check_branch_info(str(branch)) == []


def test_meta_presence_valid():
    """Content with both header and footer markers passes."""
    content = (
        "# =================== AIPass ====================\n"
        "# Name: test.py\n"
        "# Description: Test file\n"
        "# Version: 1.0.0\n"
        "# Created: 2026-01-01\n"
        "# Modified: 2026-01-01\n"
        "# =============================================\n"
    )

    result = check_meta_presence(content)
    assert result["passed"] is True


def test_meta_presence_missing_header():
    """Content without header marker fails."""
    content = "# Name: test.py\n# =============================================\n"

    result = check_meta_presence(content)
    assert result["passed"] is False
    assert "header" in result["message"]


def test_meta_presence_legacy_header():
    """Content with legacy META header passes."""
    content = (
        "# =================== META ====================\n"
        "# Name: test.py\n"
        "# =============================================\n"
    )

    result = check_meta_presence(content)
    assert result["passed"] is True


def test_meta_placement_at_top():
    """META block at line 1 passes."""
    content = "# =================== AIPass ====================\nrest of file\n"

    result = check_meta_placement(content)
    assert result["passed"] is True


def test_meta_placement_not_at_top():
    """META block not at line 1 fails."""
    content = '"""Docstring first."""\n# =================== AIPass ====================\n'

    result = check_meta_placement(content)
    assert result["passed"] is False
    assert "first line" in result["message"]


def test_required_fields_all_present():
    """All required META fields present passes."""
    content = (
        "# =================== AIPass ====================\n"
        "# Name: test.py\n"
        "# Description: Test file\n"
        "# Version: 1.0.0\n"
        "# Created: 2026-01-01\n"
        "# Modified: 2026-01-01\n"
        "# =============================================\n"
    )

    results = check_required_fields(content, "test.py")
    assert all(r["passed"] for r in results)


def test_required_fields_missing_version():
    """Missing Version field fails."""
    content = (
        "# =================== AIPass ====================\n"
        "# Name: test.py\n"
        "# Description: Test file\n"
        "# Created: 2026-01-01\n"
        "# Modified: 2026-01-01\n"
        "# =============================================\n"
    )

    results = check_required_fields(content, "test.py")
    version_result = [r for r in results if "Version" in r["name"]]
    assert len(version_result) == 1
    assert version_result[0]["passed"] is False


def test_required_fields_wrong_name():
    """Name field not matching filename fails."""
    content = (
        "# =================== AIPass ====================\n"
        "# Name: wrong_name.py\n"
        "# Description: Test file\n"
        "# Version: 1.0.0\n"
        "# Created: 2026-01-01\n"
        "# Modified: 2026-01-01\n"
        "# =============================================\n"
    )

    results = check_required_fields(content, "test.py")
    name_result = [r for r in results if "Name" in r["name"]]
    assert len(name_result) == 1
    assert name_result[0]["passed"] is False
    assert "wrong_name.py" in name_result[0]["message"]


def test_file_naming_snake_case(tmp_path):
    """Snake_case filename passes."""
    f = tmp_path / "good_module.py"
    f.write_text("pass", encoding="utf-8")

    result = check_file_naming(str(f), f)
    assert result["passed"] is True


def test_file_naming_bad_case(tmp_path):
    """Uppercase filename fails."""
    f = tmp_path / "BadModule.py"
    f.write_text("pass", encoding="utf-8")

    result = check_file_naming(str(f), f)
    assert result["passed"] is False
    assert "invalid characters" in result["message"]


def test_file_naming_redundant_prefix(tmp_path):
    """Filename with redundant parent dir prefix fails."""
    parent = tmp_path / "audit"
    parent.mkdir()
    f = parent / "audit_ops.py"
    f.write_text("pass", encoding="utf-8")

    result = check_file_naming(str(f), f)
    assert result["passed"] is False
    assert "redundant prefix" in result["message"]


def test_file_naming_init(tmp_path):
    """__init__.py passes (Python-reserved)."""
    f = tmp_path / "__init__.py"
    f.write_text("", encoding="utf-8")

    result = check_file_naming(str(f), f)
    assert result["passed"] is True


def test_function_naming_all_snake():
    """All snake_case functions pass."""
    content = "def do_work():\n    pass\n\ndef get_data():\n    pass\n"

    result = check_function_naming(content)
    assert result is not None
    assert result["passed"] is True


def test_function_naming_camel_case():
    """CamelCase function fails."""
    content = "def DoWork():\n    pass\n"

    result = check_function_naming(content)
    assert result is not None
    assert result["passed"] is False
    assert "DoWork" in result["message"]


def test_function_naming_no_functions():
    """No functions returns None."""
    content = "X = 42\n"

    result = check_function_naming(content)
    assert result is None


def test_function_naming_dunder_skipped():
    """Dunder methods are skipped from violation checks but still counted."""
    content = "class Foo:\n    def __init__(self):\n        pass\n"

    result = check_function_naming(content)
    # __init__ is found but skipped from violation checks, so it passes
    assert result is not None
    assert result["passed"] is True


@pytest.mark.parametrize("name", ["visit_Call", "visit_ImportFrom", "setUp", "tearDownClass", "asyncSetUp"])
def test_function_naming_a_name_an_inherited_protocol_requires_passes(name):
    """ast.NodeVisitor dispatches on visit_<Node>; unittest calls setUp by that spelling (seedgo, fleet green leg 9)."""
    result = check_function_naming(f"class V(ast.NodeVisitor):\n    def {name}(self, node):\n        pass\n")

    assert result is not None
    assert result["message"] == "1 functions checked - all snake_case"


@pytest.mark.parametrize(
    "name", ["visit_NotANode", "visit_Thing", "visit_NodeVisitor", "visit_NodeTransformer", "SetUp", "setup_Data"]
)
def test_function_naming_a_lookalike_of_a_protocol_name_still_fails(name):
    """The control: only a real ast node class after visit_, and only unittest's own spellings."""
    result = check_function_naming(f"def {name}(self):\n    pass\n")

    assert result is not None
    assert result["message"] == f"Non-snake_case functions: {name}"


def test_constant_naming_upper():
    """UPPER_CASE constants pass."""
    content = 'MY_CONST = "hello"\nANOTHER = 42\n'

    result = check_constant_naming(content)
    assert result is not None
    assert result["passed"] is True


def test_constant_naming_lowercase():
    """Lowercase constants fail."""
    content = 'my_const = "hello"\n'

    result = check_constant_naming(content)
    assert result is not None
    assert result["passed"] is False
    assert "my_const" in result["message"]


def test_constant_naming_function_call_ignored():
    """Constants assigned via function call are ignored."""
    content = "logger = logging.getLogger(__name__)\n"

    result = check_constant_naming(content)
    # Function call assignment is skipped, no constants to check
    assert result is None


def test_constant_naming_exempts_the_pytest_contract_globals():
    """The names pytest reads by their exact spelling are not style."""

    # Floor: the set itself is the contract, so name it. An empty or shrunken
    # set would make the loop below a silent pass on the exemption it guards.
    assert sorted(PYTEST_CONTRACT_GLOBALS) == [
        "collect_ignore",
        "collect_ignore_glob",
        "pytest_plugins",
        "pytestmark",
    ]

    for name in sorted(PYTEST_CONTRACT_GLOBALS):
        content = f'{name} = ["x"]\n'
        assert check_constant_naming(content) is None, (
            f"{name} is read by pytest under that spelling and must not be nominated"
        )


def test_the_exemption_is_a_named_set_and_not_a_lowercase_amnesty():
    """The control that keeps the cure narrow."""

    result = check_constant_naming('collect_ignore_glob = ["x"]\nmy_helper = 3\n')
    assert result is not None, "the non-contract name was swallowed with the exempt one"
    assert result["passed"] is False
    assert "my_helper" in result["message"]
    assert "collect_ignore_glob" not in result["message"]


def test_the_real_conftest_that_reported_it_is_no_longer_nominated():
    """Reproduced against the actual file, not a synthetic string."""
    from pathlib import Path

    conftest = Path(__file__).resolve().parents[2] / "conftest.py"
    if not conftest.is_file():
        pytest.skip(f"the reported file is not at {conftest} on this checkout")
    result = check_constant_naming(conftest.read_text(encoding="utf-8"))
    # Measured on this checkout: every lowercase global in that file is a
    # pytest-contract name, so nothing is nominated at all and the checker
    # returns no verdict -- not a verdict that happens to pass.
    assert result is None, f"the file that produced the counterexample still fails: {result}"


def test_class_naming_pascal():
    """PascalCase class passes."""
    content = "class MyClass:\n    pass\n"

    result = check_class_naming(content)
    assert result is not None
    assert result["passed"] is True


def test_class_naming_snake():
    """snake_case class fails."""
    content = "class my_class:\n    pass\n"

    result = check_class_naming(content)
    assert result is not None
    assert result["passed"] is False
    assert "my_class" in result["message"]


def test_class_naming_no_classes():
    """No classes returns None."""
    content = "def do_work():\n    pass\n"

    result = check_class_naming(content)
    assert result is None


def test_class_naming_private_pascal_passes():
    """PEP 8 sanctions a single leading underscore on an internal PascalCase class."""
    content = "class _LivenessState:\n    pass\n"

    result = check_class_naming(content)
    assert result is not None
    assert result["passed"] is True


def test_class_naming_private_snake_still_fails():
    """A leading underscore does not excuse a non-PascalCase body."""
    content = "class _foo_bar:\n    pass\n"

    result = check_class_naming(content)
    assert result is not None
    assert result["passed"] is False
    assert "_foo_bar" in result["message"]


def test_no_dangerous_flags_clean(tmp_path):
    """File with only approved permission flags passes."""
    lines: List[str] = [
        '"""Clean module."""',
        '"--permission-mode bypassPermissions"',
        "",
    ]

    result = check_no_dangerous_flags(lines, str(tmp_path / "fake/path.py"))
    assert result["passed"] is True


def test_no_dangerous_flags_violation(tmp_path):
    """File with prohibited permission bypass flag fails."""
    lines: List[str] = [
        '"""Module."""',
        'cmd = "--dangerously-skip-permissions"',
        "",
    ]

    result = check_no_dangerous_flags(lines, str(tmp_path / "fake/path.py"))
    assert result["passed"] is False
    assert "Dangerous" in result["message"]


def test_no_dangerous_flags_in_docstring(tmp_path):
    """Prohibited flag inside docstring is ignored."""
    lines: List[str] = [
        '"""',
        "Use --dangerously-skip-permissions for testing",
        '"""',
        "pass",
        "",
    ]

    result = check_no_dangerous_flags(lines, str(tmp_path / "fake/path.py"))
    assert result["passed"] is True


def test_no_dangerous_flags_skip_permissions(tmp_path):
    """File with --skip-permissions fails."""
    lines: List[str] = [
        '"""Module."""',
        'cmd = "--skip-permissions"',
        "",
    ]

    result = check_no_dangerous_flags(lines, str(tmp_path / "fake/path.py"))
    assert result["passed"] is False


def test_no_dangerous_flags_bypass_rule(tmp_path):
    """Prohibited flag bypassed by rule passes."""
    lines: List[str] = [
        '"""Module."""',
        'cmd = "--dangerously-skip-permissions"',
        "",
    ]
    bypass_rules = [{"standard": "permission_flags", "file": str(tmp_path / "fake/path.py")}]

    result = check_no_dangerous_flags(lines, str(tmp_path / "fake/path.py"), bypass_rules=bypass_rules)
    assert result["passed"] is True


# -- prose lines: docstrings and comment lines are never read as code --------


def test_no_dangerous_flags_reads_code_after_a_docstring_quoting_the_other_delimiter(tmp_path):
    lines = _lines('"""Quotes \'\'\' in prose."""\ncmd = "--dangerously-skip-permissions"\n')
    result = check_no_dangerous_flags(lines, str(tmp_path / "fake/path.py"))
    assert result["message"].startswith("Dangerous permission bypass flags on lines [2]")


def test_no_dangerous_flags_reads_a_triple_quoted_literal_in_code(tmp_path):
    lines = _lines('cmd = """--dangerously-skip-permissions"""\n')
    result = check_no_dangerous_flags(lines, str(tmp_path / "fake/path.py"))
    assert result["message"].startswith("Dangerous permission bypass flags on lines [1]")


def test_no_dangerous_flags_ignores_flag_words_in_a_docstring_holding_the_other_delimiter(tmp_path):
    lines = _lines('"""\n\'\'\'\nUse --dangerously-skip-permissions never.\n"""\nx = 1\n')
    result = check_no_dangerous_flags(lines, str(tmp_path / "fake/path.py"))
    assert result["passed"] is True


def test_no_raw_file_handler_ignores_a_one_line_docstring_naming_it(tmp_path):
    lines = _lines('"""Never logging.FileHandler("x.log") here."""\nimport logging\n')
    result = check_no_raw_file_handler(lines, str(tmp_path / "fake/path.py"))
    assert result["passed"] is True


def test_no_raw_file_handler_ignores_a_multi_line_docstring_naming_it(tmp_path):
    lines = _lines('def f():\n    """Avoid\n    logging.FileHandler("x.log")\n    """\n    return 1\n')
    result = check_no_raw_file_handler(lines, str(tmp_path / "fake/path.py"))
    assert result["passed"] is True


def test_no_raw_stream_handler_ignores_a_docstring_naming_it(tmp_path):
    content = '"""\nlogging.StreamHandler() beside system_logs.\n"""\nimport logging\n'
    result = check_no_raw_stream_handler(_lines(content), str(tmp_path / "fake/path.py"), content)
    assert result["passed"] is True


def test_error_not_user_input_reads_code_after_a_docstring_quoting_the_other_delimiter(tmp_path):
    lines = _lines('"""Quotes \'\'\' in prose."""\nlogger.error("Unknown command: %s", cmd)\n')
    result = check_error_not_user_input(lines, str(tmp_path / "fake/path.py"))
    assert result["message"].startswith("ERROR level used for user input on lines [2]")


def test_error_not_user_input_reads_a_triple_quoted_literal_in_code(tmp_path):
    lines = _lines('logger.error("""Unknown command: %s""", cmd)\n')
    result = check_error_not_user_input(lines, str(tmp_path / "fake/path.py"))
    assert result["message"].startswith("ERROR level used for user input on lines [1]")


def test_constant_naming_reads_the_line_opening_a_triple_quoted_literal():
    result = check_constant_naming('bad_name = """\nbody\n"""\n')
    assert result is not None
    assert result["message"] == "Non-UPPER_CASE constants: bad_name"


def test_constant_naming_never_reads_a_literal_body_as_an_assignment():
    result = check_constant_naming('TEXT = """\nfoo = 1\n"""\n')
    assert result is not None
    assert result["passed"] is True


def test_constant_naming_reads_code_after_a_docstring_holding_the_other_delimiter():
    result = check_constant_naming("'''\n\"\"\"\n'''\nlower_x = 1\n")
    assert result is not None
    assert result["message"] == "Non-UPPER_CASE constants: lower_x"
