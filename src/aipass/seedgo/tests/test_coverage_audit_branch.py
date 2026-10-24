# =================== AIPass ====================
# Name: test_coverage_audit_branch.py
# Description: audit coverage, orchestration phase: audit_branch's lanes, post/info/observe hooks, output fields
# Version: 1.0.1
# Created: 2026-10-08
# Modified: 2026-10-24
# =============================================

"""Tests for audit_branch in apps/handlers/audit/branch_audit.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that branch_audit.py parses and imports

import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import skip_dirs
from aipass.seedgo.apps.handlers.audit import branch_audit

pytestmark = pytest.mark.usefixtures("coverage_audit_seams")


def _setup_branch(tmp_path: Path) -> tuple:
    """Create minimal branch structure, return (branch_dict, path)."""
    branch_path = tmp_path / "mybranch"
    branch_path.mkdir()
    entry = branch_path / "apps" / "main.py"
    entry.parent.mkdir(parents=True)
    entry.write_text("pass", encoding="utf-8")
    branch = {
        "name": "mybranch",
        "entry_file": str(entry),
        "path": str(branch_path),
    }
    return branch, branch_path


def _make_checker(
    scope: str = "entry_point",
    check_module_result: dict | None = None,
    check_branch_result: dict | None = None,
    has_check_module: bool = True,
    has_check_branch: bool = False,
    has_post: bool = False,
    post_result: tuple | None = None,
    has_info: bool = False,
    info_result: list | None = None,
) -> MagicMock:
    """Build a mock checker with configurable behavior."""
    checker = MagicMock()
    checker.AUDIT_SCOPE = scope
    checker.INCLUDE_INIT_FILES = False

    if has_check_module:
        default_mod = {
            "passed": True,
            "score": 100,
            "checks": [],
        }
        checker.check_module = MagicMock(return_value=check_module_result or default_mod)
    else:
        del checker.check_module

    if has_check_branch:
        default_br = {
            "passed": True,
            "score": 100,
            "checks": [],
        }
        checker.check_branch = MagicMock(return_value=check_branch_result or default_br)
    else:
        del checker.check_branch

    if has_post:
        checker.check_branch_post = MagicMock(return_value=post_result or ([], []))
    else:
        del checker.check_branch_post

    if has_info:
        checker.check_branch_info = MagicMock(return_value=info_result if info_result is not None else [])
    else:
        del checker.check_branch_info

    return checker


def _real_module_checker(**hooks) -> types.SimpleNamespace:
    """A checker whose surface is REAL functions rather than MagicMocks.

    A MagicMock answers to any call signature, so a mock-based test can never
    pin the pipeline's actual calling convention: check_branch_post was called
    with bypass_rules= against an implementation that took one positional
    argument, and every mock in this file kept passing while the standard was
    dead in production. Contract tests use this instead.
    """
    checker = types.SimpleNamespace(
        AUDIT_SCOPE="entry_point",
        INCLUDE_INIT_FILES=False,
        check_module=lambda module_path, bypass_rules=None: {"passed": True, "score": 100, "checks": []},
    )
    for name, fn in hooks.items():
        setattr(checker, name, fn)
    return checker


class TestAuditBranch:
    """Tests for audit_branch."""

    @pytest.fixture(autouse=True)
    def _no_diagnostics(self, monkeypatch):
        """The real diagnostics loader runs pyright over the branch; silenced here.

        Its lane is pinned by test_diagnostics_checker_added and
        test_diagnostics_not_duplicated, which install a loader that answers.
        scan_branch is already silenced by the module's autouse fixture.
        """
        monkeypatch.setattr(branch_audit, "_load_diagnostics_checker", lambda: None)

    def test_basic_audit(self, tmp_path, monkeypatch):
        """Basic audit with one entry-point checker."""
        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker()
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": checker},
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["branch"] == branch
        assert "naming" in result["scores"]
        assert result["average"] == 100

    def test_branch_level_checker(self, tmp_path, monkeypatch):
        """Branch-level checker calls check_branch."""
        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker(
            scope="branch_level",
            has_check_module=False,
            has_check_branch=True,
            check_branch_result={
                "passed": True,
                "score": 85,
                "checks": [],
            },
        )
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"dead_code": checker},
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["scores"]["dead_code"] == 85

    def test_branch_level_checker_exception(self, tmp_path, monkeypatch):
        """Branch-level checker that raises produces score 0."""
        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker(
            scope="branch_level",
            has_check_module=False,
            has_check_branch=True,
        )
        checker.check_branch.side_effect = RuntimeError("boom")
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"broken": checker},
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["scores"]["broken"] == 0
        assert "error" in result["results"]["broken"]

    def test_entry_point_checker_exception(self, tmp_path, monkeypatch):
        """Entry-point checker that raises produces score 0."""
        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker()
        checker.check_module.side_effect = RuntimeError("crash")
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": checker},
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["scores"]["naming"] == 0
        assert "error" in result["results"]["naming"]

    def test_all_files_scope(self, tmp_path, monkeypatch):
        """all_files scope runs checker on every file."""
        branch, branch_path = _setup_branch(tmp_path)
        apps_dir = Path(branch_path) / "apps"
        (apps_dir / "other.py").write_text("pass", encoding="utf-8")

        checker = _make_checker(
            scope="all_files",
            check_module_result={
                "passed": True,
                "score": 80,
                "checks": [
                    {"passed": True, "message": "OK"},
                ],
            },
        )
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": checker},
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["scores"]["naming"] == 80

    def test_all_files_with_violations(self, tmp_path, monkeypatch):
        """all_files scope with failing checks updates results."""
        branch, branch_path = _setup_branch(tmp_path)
        apps_dir = Path(branch_path) / "apps"
        (apps_dir / "bad.py").write_text("pass", encoding="utf-8")

        def check_side_effect(path, bypass_rules=None):
            """Return different results based on path."""
            if "bad" in path:
                return {
                    "passed": False,
                    "score": 40,
                    "checks": [
                        {
                            "passed": False,
                            "message": "Bad naming",
                        }
                    ],
                }
            return {
                "passed": True,
                "score": 90,
                "checks": [
                    {"passed": True, "message": "OK"},
                ],
            }

        checker = _make_checker(scope="all_files")
        checker.check_module.side_effect = check_side_effect
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": checker},
        )

        result = branch_audit.audit_branch(branch, [])
        assert "naming_violations" in result

    def test_all_files_scope_include_init_files_opt_in(self, tmp_path, monkeypatch):
        """Checker with INCLUDE_INIT_FILES=True sees __init__.py; a normal checker does not."""
        branch, branch_path = _setup_branch(tmp_path)
        apps_dir = Path(branch_path) / "apps"
        (apps_dir / "__init__.py").write_text("pass", encoding="utf-8")

        import_checker = _make_checker(scope="all_files")
        import_checker.INCLUDE_INIT_FILES = True
        normal_checker = _make_checker(scope="all_files")

        # tmp_path lives under the system temp dir, which is_throwaway_path
        # filters out wholesale — empty its root list so the real predicate
        # sees the fixture's files, same as it would for a real branch on disk.
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"handlers": import_checker, "naming": normal_checker},
        )

        branch_audit.audit_branch(branch, [])

        import_checked_names = {Path(c.args[0]).name for c in import_checker.check_module.call_args_list}
        normal_checked_names = {Path(c.args[0]).name for c in normal_checker.check_module.call_args_list}
        assert "__init__.py" in import_checked_names
        assert "__init__.py" not in normal_checked_names

    def test_dynamic_post_check(self, tmp_path, monkeypatch):
        """check_branch_post discovered and called."""
        branch, _ = _setup_branch(tmp_path)
        post_violations = [
            {
                "path": "/extra.py",
                "score": 0,
                "issues": ["Extra issue"],
            }
        ]
        checker = _make_checker(
            has_post=True,
            post_result=(post_violations, [50]),
        )
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": checker},
        )

        result = branch_audit.audit_branch(branch, [])
        # Post check: (100 + 50) / 2 = 75
        assert result["scores"]["naming"] == 75
        assert len(result["naming_violations"]) == 1

    def test_post_check_raises_exception(self, tmp_path, monkeypatch):
        """check_branch_post that raises is caught."""
        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker(has_post=True)
        checker.check_branch_post.side_effect = RuntimeError("fail")
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": checker},
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["scores"]["naming"] == 100

    def test_post_check_crash_is_attributable_in_output(self, tmp_path, monkeypatch):
        """A crashed post-check reaches the audit OUTPUT, naming checker, branch and error.

        The lane used to swallow the exception into logger.info(): every audit
        printed a clean score while a piece of the measurement had not run at
        all, and nothing in the output said so. A failure only a log knows
        about is indistinguishable from a success — that is what this pins.
        """
        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker(has_post=True)
        checker.check_branch_post.side_effect = RuntimeError("boom")
        monkeypatch.setattr(branch_audit, "discover_checkers", lambda pack_path=None: {"naming": checker})

        result = branch_audit.audit_branch(branch, [])

        crashes = [v for v in result["naming_violations"] if "post-check" in v.get("message", "").lower()]
        assert crashes, "a crashed post-check must surface in the audit output, not only in a log line"
        message = crashes[0]["message"]
        assert "naming" in message, "which checker crashed"
        assert "mybranch" in message, "on which branch"
        assert "RuntimeError" in message and "boom" in message, "with which error"
        failed_checks = [c for c in result["results"]["naming"].get("checks", []) if not c.get("passed", True)]
        assert any("post-check" in c.get("message", "").lower() for c in failed_checks), (
            "same doctrine as the branch-level lane: the number arrives with its reason attached"
        )

    def test_post_check_contract_real_signature_is_invoked(self, tmp_path, monkeypatch):
        """The pipeline's actual calling convention, pinned with a REAL function.

        Every existing post-check test uses a MagicMock, which accepts any
        signature — so none of them could ever catch the mismatch that killed
        this lane in production. A real function object can.
        """
        branch, branch_path = _setup_branch(tmp_path)
        seen: list = []

        def check_branch_post(branch_path, bypass_rules=None):
            seen.append((branch_path, bypass_rules))
            return ([{"path": "/extra.py", "score": 0, "issues": ["Extra issue"]}], [50])

        checker = _real_module_checker(check_branch_post=check_branch_post)
        monkeypatch.setattr(branch_audit, "discover_checkers", lambda pack_path=None: {"naming": checker})

        result = branch_audit.audit_branch(branch, ["some-rule"])

        assert seen == [(str(branch_path), ["some-rule"])], "branch path positionally, bypass_rules by keyword"
        assert result["scores"]["naming"] == 75, "(100 + 50) / 2 — the post score blends"
        assert len(result["naming_violations"]) == 1

    def test_post_check_wrong_signature_fails_loudly(self, tmp_path, monkeypatch):
        """The live defect reproduced: a post-check that does not accept bypass_rules.

        log_structure_check shipped exactly this signature for months. The
        pipeline raised TypeError on every branch on every run and the bare
        except turned it into silence — the standard simply stopped running
        and no audit ever said so.
        """
        branch, _ = _setup_branch(tmp_path)

        def check_branch_post(branch_path):  # the pre-fix log_structure signature
            return ([], [50])

        checker = _real_module_checker(check_branch_post=check_branch_post)
        monkeypatch.setattr(branch_audit, "discover_checkers", lambda pack_path=None: {"naming": checker})

        result = branch_audit.audit_branch(branch, [])

        crashes = [v for v in result["naming_violations"] if "post-check" in v.get("message", "").lower()]
        assert crashes, "a signature mismatch must be loud — it means the standard did not run"
        assert "TypeError" in crashes[0]["message"]
        assert "bypass_rules" in crashes[0]["message"], "the report must name the argument that did not fit"
        assert result["scores"]["naming"] == 100, "a checker's own crash must not invent a number for the branch"

    def test_info_channel_collected_and_never_scored(self, tmp_path, monkeypatch):
        """check_branch_info lines reach output without touching the score."""
        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker(has_info=True, info_result=["custom_config: cadence_config.json"])
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": checker},
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["info_lines"] == [{"standard": "naming", "message": "custom_config: cadence_config.json"}]
        assert result["scores"]["naming"] == 100
        assert result["average"] == 100

    def test_info_check_raises_is_caught(self, tmp_path, monkeypatch):
        """check_branch_info that raises leaves the audit intact."""
        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker(has_info=True)
        checker.check_branch_info.side_effect = RuntimeError("fail")
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": checker},
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["info_lines"] == []
        assert result["scores"]["naming"] == 100

    def test_observe_lane_runs_with_bypass_rules_and_records(self, tmp_path, monkeypatch):
        """check_branch_observe runs on every audit and its readings reach the output.

        Driven by a REAL function, so the signature the pipeline uses is
        pinned by execution rather than by a mock that accepts anything.
        """
        branch, branch_path = _setup_branch(tmp_path)
        seen: list = []

        def check_branch_observe(branch_path, bypass_rules=None):
            seen.append((branch_path, bypass_rules))
            return [{"standard": "naming", "would_be_score": 50, "observed_at": "2026-08-14T00:00:00"}]

        checker = _real_module_checker(check_branch_observe=check_branch_observe)
        monkeypatch.setattr(branch_audit, "discover_checkers", lambda pack_path=None: {"naming": checker})

        result = branch_audit.audit_branch(branch, ["some-rule"])

        assert seen == [(str(branch_path), ["some-rule"])]
        assert result["observations"] == [
            {"standard": "naming", "would_be_score": 50, "observed_at": "2026-08-14T00:00:00"}
        ]

    def test_observe_lane_moves_no_score(self, tmp_path, monkeypatch):
        """Same branch, audited with and without the observe lane — identical numbers.

        This observation was de-scored because it reads live log files, so a
        branch's number moved with no code change. Observe mode is only
        honest if the lane's presence is invisible to every score.
        """
        branch, _ = _setup_branch(tmp_path)

        without = _real_module_checker()
        monkeypatch.setattr(branch_audit, "discover_checkers", lambda pack_path=None: {"log_structure": without})
        baseline = branch_audit.audit_branch(branch, [])

        def check_branch_observe(branch_path, bypass_rules=None):
            return [{"standard": "log_structure", "would_be_score": 50, "local_logs": 3, "system_logs": 0}]

        with_lane = _real_module_checker(check_branch_observe=check_branch_observe)
        monkeypatch.setattr(branch_audit, "discover_checkers", lambda pack_path=None: {"log_structure": with_lane})
        observed = branch_audit.audit_branch(branch, [])

        assert observed["observations"], "the lane really ran — otherwise this proves nothing"
        assert observed["scores"] == baseline["scores"]
        assert observed["scores"]["log_structure"] == baseline["scores"]["log_structure"]
        assert observed["average"] == baseline["average"]
        assert observed["log_structure_violations"] == baseline["log_structure_violations"]

    def test_observe_lane_crash_is_attributable_and_still_scoreless(self, tmp_path, monkeypatch):
        """A broken observe lane says so — and still cannot touch a score."""
        branch, _ = _setup_branch(tmp_path)

        def check_branch_observe(branch_path, bypass_rules=None):
            raise RuntimeError("observe boom")

        checker = _real_module_checker(check_branch_observe=check_branch_observe)
        monkeypatch.setattr(branch_audit, "discover_checkers", lambda pack_path=None: {"naming": checker})

        result = branch_audit.audit_branch(branch, [])

        errors = [o for o in result["observations"] if o.get("error")]
        assert errors, "a crashed observe lane must be visible in the reading, not silently absent"
        assert errors[0]["standard"] == "naming"
        assert "RuntimeError" in errors[0]["error"] and "observe boom" in errors[0]["error"]
        assert result["scores"]["naming"] == 100
        assert result["average"] == 100

    def test_checker_without_info_hook_skipped(self, tmp_path, monkeypatch):
        """A checker with no check_branch_info contributes no info lines."""
        branch, _ = _setup_branch(tmp_path)
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": _make_checker()},
        )

        assert branch_audit.audit_branch(branch, [])["info_lines"] == []

    def test_diagnostics_checker_added(self, tmp_path, monkeypatch):
        """Diagnostics checker loaded and added."""
        branch, _ = _setup_branch(tmp_path)
        diag_mod = MagicMock()
        diag_mod.check_branch = MagicMock(
            return_value={
                "passed": True,
                "score": 90,
                "checks": [],
                "total_errors": 0,
                "results": [],
            }
        )
        diag_mod.AUDIT_SCOPE = "branch_level"
        del diag_mod.check_module

        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {},
        )
        monkeypatch.setattr(
            branch_audit,
            "_load_diagnostics_checker",
            lambda: diag_mod,
        )

        result = branch_audit.audit_branch(branch, [])
        assert "diagnostics" in result["scores"]

    def test_deprecated_documents_dir(self, tmp_path, monkeypatch):
        """DOCUMENTS/ directory detected as deprecated."""
        branch, branch_path = _setup_branch(tmp_path)
        (Path(branch_path) / "DOCUMENTS").mkdir()

        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {},
        )

        result = branch_audit.audit_branch(branch, [])
        assert len(result["deprecated_patterns"]) == 1
        dep = result["deprecated_patterns"][0]
        assert dep["old"] == "DOCUMENTS/"

    def test_no_deprecated_without_documents(self, tmp_path, monkeypatch):
        """No deprecated patterns without DOCUMENTS/."""
        branch, _ = _setup_branch(tmp_path)
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {},
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["deprecated_patterns"] == []

    def test_scan_branch_exception(self, tmp_path, monkeypatch):
        """scan_branch exception caught, test_map is None."""
        branch, _ = _setup_branch(tmp_path)
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {},
        )
        monkeypatch.setattr(
            branch_audit,
            "scan_branch",
            MagicMock(side_effect=RuntimeError("scan fail")),
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["test_map"] is None

    def test_scan_branch_success(self, tmp_path, monkeypatch):
        """scan_branch success populates test_map."""
        branch, _ = _setup_branch(tmp_path)
        scan_result = {
            "total_functions": 10,
            "tested_functions": 5,
            "branch": "mybranch",
        }
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {},
        )
        monkeypatch.setattr(
            branch_audit,
            "scan_branch",
            MagicMock(return_value=scan_result),
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["test_map"] == scan_result

    def test_no_checkers_zero_average(self, tmp_path, monkeypatch):
        """No checkers returns average 0."""
        branch, _ = _setup_branch(tmp_path)
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {},
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["average"] == 0

    def test_implicit_branch_level(self, tmp_path, monkeypatch):
        """Checker without check_module treated as branch-level."""
        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker(
            scope="entry_point",
            has_check_module=False,
            has_check_branch=True,
            check_branch_result={
                "passed": True,
                "score": 75,
                "checks": [],
            },
        )
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"implicit": checker},
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["scores"]["implicit"] == 75

    def test_pack_path_forwarded(self, tmp_path, monkeypatch):
        """pack_path argument forwarded to discover_checkers."""
        branch, _ = _setup_branch(tmp_path)
        captured: dict = {}

        def mock_discover(pack_path=None):
            """Capture the pack_path argument."""
            captured["value"] = pack_path
            return {}

        monkeypatch.setattr(branch_audit, "discover_checkers", mock_discover)

        pack = tmp_path / "custom_standards"
        branch_audit.audit_branch(branch, [], pack_path=pack)
        assert captured["value"] == pack

    def test_diagnostics_not_duplicated(self, tmp_path, monkeypatch):
        """Existing diagnostics not overwritten by loader."""
        branch, _ = _setup_branch(tmp_path)
        existing = _make_checker(
            scope="branch_level",
            has_check_module=False,
            has_check_branch=True,
            check_branch_result={
                "passed": True,
                "score": 80,
                "checks": [],
                "total_errors": 0,
                "results": [],
            },
        )
        different = MagicMock()

        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"diagnostics": existing},
        )
        monkeypatch.setattr(
            branch_audit,
            "_load_diagnostics_checker",
            lambda: different,
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["scores"]["diagnostics"] == 80

    def test_branch_level_violations_extraction(self, tmp_path, monkeypatch):
        """Branch-level results have violations extracted."""
        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker(
            scope="branch_level",
            has_check_module=False,
            has_check_branch=True,
            check_branch_result={
                "passed": False,
                "score": 60,
                "checks": [
                    {
                        "name": "unused_check",
                        "passed": False,
                        "message": "Found unused",
                        "unused": [
                            {
                                "file": "/foo.py",
                                "name": "bar",
                                "line": 10,
                            },
                        ],
                    },
                ],
            },
        )
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"dead_code": checker},
        )

        result = branch_audit.audit_branch(branch, [])
        assert len(result["dead_code_violations"]) == 1

    def test_output_diagnostics_fields(self, tmp_path, monkeypatch):
        """Output includes type_errors and type_error_files."""
        branch, _ = _setup_branch(tmp_path)
        diag = _make_checker(
            scope="branch_level",
            has_check_module=False,
            has_check_branch=True,
            check_branch_result={
                "passed": True,
                "score": 90,
                "checks": [],
                "total_errors": 3,
                "results": [{"file": "a.py", "errors": 3}],
            },
        )
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"diagnostics": diag},
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["type_errors"] == 3
        assert result["type_error_files"] == [{"file": "a.py", "errors": 3}]

    def test_post_check_empty_scores(self, tmp_path, monkeypatch):
        """Post-check with empty scores does not change score."""
        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker(
            has_post=True,
            post_result=([], []),
        )
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": checker},
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["scores"]["naming"] == 100
