# =================== META ====================
# Name: test_branch_audit_scoring.py
# Description: audit_branch's all_files row — which files the average counts
# Version: 1.3.0
# Created: 2026-09-25
# Modified: 2026-09-25
# =============================================

"""Tests for apps/handlers/audit/branch_audit.py, the all_files row's average."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — the cache serving or re-running a row; tests/test_incremental_audit.py
# seedgo: no-test-needed(shared) — os.walk convictions themselves; tests/test_os_walk_onerror_check.py

import types
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import applicability, os_walk_onerror_check, skip_dirs
from aipass.seedgo.apps.handlers.audit import artifact, audit_display, branch_audit
from aipass.seedgo.apps.handlers.bypass import ignore_handler

WALKER = "import os\n\n\ndef files(root):\n    return [d for d, _, _ in os.walk(root)]\n"


def _checker(verdicts):
    """An all_files checker whose result for a file is looked up by its name."""
    return types.SimpleNamespace(
        AUDIT_SCOPE="all_files",
        check_module=lambda path, bypass_rules=None: verdicts.get(Path(path).name, PASS),
    )


PASS = {"passed": True, "score": 100, "checks": [{"passed": True, "message": "OK"}]}


@pytest.fixture
def audit(tmp_path, monkeypatch):
    """Audit a branch under tmp_path with only the given checkers."""
    # tmp_path sits under the system temp root, which the corpus drops as throwaway.
    monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])
    monkeypatch.setattr(branch_audit, "_load_diagnostics_checker", lambda: None)
    monkeypatch.setattr(branch_audit, "scan_branch", lambda path: None)

    def run(checkers, files):
        apps = tmp_path / "mybranch" / "apps"
        apps.mkdir(parents=True)
        (apps / "main.py").write_text("pass\n", encoding="utf-8")
        for name, body in files.items():
            (apps / name).write_text(body, encoding="utf-8")
        monkeypatch.setattr(branch_audit, "discover_checkers", lambda _pack=None: checkers)
        branch = {"name": "mybranch", "entry_file": str(apps / "main.py"), "path": str(apps.parent)}
        return branch_audit.audit_branch(branch, [])

    return run


class TestAFailingFileIsAlwaysAveraged:
    def test_a_failure_whose_message_says_skipped_scores_the_row_down(self, audit):
        """The shipped defect: os_walk_onerror's "is skipped in silence" read as not applicable."""
        out = audit({"os_walk_onerror": os_walk_onerror_check}, {"walker.py": WALKER})
        assert out["scores"]["os_walk_onerror"] == 50
        assert [v["file"] for v in out["os_walk_onerror_violations"]] == ["walker.py"]

    def test_a_failure_beside_a_declined_check_is_averaged(self, audit):
        mixed = {
            "passed": False,
            "score": 0,
            "checks": [
                {"passed": True, "declined": True, "message": "Bypassed - thin orchestration check skipped"},
                {"passed": False, "message": "Business logic in a module"},
            ],
        }
        out = audit({"modules": _checker({"bad.py": mixed})}, {"bad.py": "pass\n"})
        assert out["scores"]["modules"] == 50


class TestADeclinedFileStandsDown:
    def test_a_declined_check_without_the_word_leaves_the_average(self, audit):
        declined = {"passed": True, "score": 0, "checks": [{"passed": True, "declined": True, "message": "Not judged"}]}
        out = audit({"cli": _checker({"other.py": declined})}, {"other.py": "pass\n"})
        assert out["scores"]["cli"] == 100
        assert out["declined"] == {"cli": ["apps/other.py"]}

    @pytest.mark.parametrize("message", ["Not an entry point (skipped)", "No try/except blocks (not applicable)"])
    def test_a_passing_message_that_says_skipped_without_declining_is_averaged(self, audit, message):
        judged = {"passed": True, "score": 0, "checks": [{"passed": True, "message": message}]}
        out = audit({"cli": _checker({"other.py": judged})}, {"other.py": "pass\n"})
        assert out["scores"]["cli"] == 50
        assert out["declined"] == {}


class TestTheOutputNamesWhatARowDeclined:
    def test_the_summary_counts_the_declined_files_per_row(self, audit, capsys):
        declined = {"passed": True, "score": 100, "checks": [{"passed": True, "declined": True, "message": "n/a"}]}
        verdicts = {"a.py": declined, "b.py": declined}
        out = audit({"cli": _checker(verdicts), "meta": _checker({})}, {"a.py": "pass\n", "b.py": "pass\n"})
        capsys.readouterr()
        audit_display.print_branch_summary(out)
        printed = capsys.readouterr().out
        assert [line for line in printed.splitlines() if "declined" in line] == ["  Not judged: Cli 2 declined"]


#: A clean print_introspection(): with it, introspection's other checks pass, so
#: its three "(skipped)" sub-checks decide the file's stand-down on their own.
INTRO = (
    "from aipass.cli import console\n\n\n"
    "def print_introspection():\n"
    '    console.print("[bold]{0}[/bold] - run drone @{0} --help")\n'
)
MAIN = '\n\ndef main():\n    print_introspection()\n\n\nif __name__ == "__main__":\n    main()\n'

#: Planted files that reach the pack's stand-down paths: a package marker, an
#: empty module, a test file, a file that does not parse, a declarations-only
#: handler, the json package, routing and non-routing modules, an entry point,
#: a stream handler with no file logging, a file outside the three layers, a
#: test-named file under apps/, and
#: clean introspection files with no main(), no args gate and no handle_command().
PROBES = {
    "apps/__init__.py": "",
    "apps/modules/__init__.py": "",
    "apps/modules/empty.py": "",
    "apps/modules/router.py": "def handle_command(args):\n    return True\n",
    "apps/modules/broken.py": "def f(:\n    pass\n",
    "apps/handlers/constants.py": "LIMIT = 3\nNAMES = ('a', 'b')\n",
    "apps/handlers/json/json_handler.py": "def log_operation(name, data):\n    return True\n",
    "apps/handlers/plain.py": "def add(a, b):\n    return a + b\n",
    "apps/tools.py": "def tool():\n    return 1\n",
    "tests/test_plain.py": "def test_add():\n    assert 1 + 1 == 2\n",
    "apps/runner.py": "def main():\n    return 0\n",
    "apps/modules/nohandler.py": "def run():\n    return 1\n",
    "apps/handlers/json/helpers.py": "def shape(data):\n    return dict(data)\n",
    "apps/handlers/stream.py": "import logging\n\nhandler = logging.StreamHandler()\n",
    "apps/lib/helper.py": "def helper():\n    return 1\n",
    "apps/handlers/test_fixture.py": "def fixture():\n    return 1\n",
    "apps/nomain.py": INTRO.format("nomain"),
    "apps/withmain.py": INTRO.format("withmain") + MAIN,
    "apps/modules/nocommand.py": INTRO.format("nocommand"),
}

WORDS = ("skipped", "not applicable")


def _word_rule(checks):
    """The rule 2.4.1 read, kept here only to prove the migration changed no stand-down."""
    failed = [c for c in checks if not c.get("passed", False)]
    return bool(checks) and not failed and any(w in c.get("message", "").lower() for c in checks for w in WORDS)


def _field_rule(checks):
    failed = [c for c in checks if not c.get("passed", False)]
    return bool(checks) and not failed and any(c.get("declined") is True for c in checks)


class TestTheMigrationKeptEveryStandDown:
    def test_the_field_stands_down_exactly_what_the_word_did_on_planted_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])
        for rel, body in PROBES.items():
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_text(body, encoding="utf-8")
        pack = branch_audit.discover_checkers()
        per_file = {n: c for n, c in pack.items() if getattr(c, "AUDIT_SCOPE", "entry_point") == "all_files"}
        disagreements, declined = [], 0
        for name, checker in sorted(per_file.items()):
            for rel in PROBES:
                path = str(tmp_path / rel)
                if not applicability.applies_to_file(checker, path):
                    continue
                checks = checker.check_module(path, bypass_rules=[]).get("checks", [])
                declined += _field_rule(checks)
                if _word_rule(checks) != _field_rule(checks):
                    disagreements.append((name, rel))
        assert disagreements == []
        assert declined >= 40


#: The repository's own two gitignore lines this cure is about: the private driver layer,
#: and the blanket artifacts/ ignore with commons' source re-included beneath it.
GITIGNORE = (
    "*/apps/integrations/**\nartifacts/\n!mybranch/apps/handlers/artifacts/\n!mybranch/apps/handlers/artifacts/*.py\n"
)

FAIL = {"passed": False, "score": 0, "checks": [{"passed": False, "message": "judged"}]}

LAYOUT = {
    "apps/integrations/google/driver.py": "def drive():\n    return 1\n",
    "apps/handlers/integrations/call.py": "def call():\n    return 1\n",
    "apps/handlers/artifacts/trade_ops.py": "def trade():\n    return 1\n",
    "apps/handlers/test/fixture.py": "def fixture():\n    return 1\n",
    "apps/handlers/config.old.py": "def old():\n    return 1\n",
}


@pytest.fixture
def repo_audit(tmp_path, monkeypatch):
    """Audit a branch inside a planted git repository (a .git entry and a .gitignore)."""
    monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])
    monkeypatch.setattr(branch_audit, "_load_diagnostics_checker", lambda: None)
    monkeypatch.setattr(branch_audit, "scan_branch", lambda path: None)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    apps = tmp_path / "mybranch" / "apps"
    for rel, body in {"apps/main.py": "pass\n", **LAYOUT}.items():
        path = tmp_path / "mybranch" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    # Every file fails, so the violations list is exactly the set of files the row judged.
    judged = types.SimpleNamespace(AUDIT_SCOPE="all_files", check_module=lambda path, bypass_rules=None: FAIL)
    monkeypatch.setattr(branch_audit, "discover_checkers", lambda _pack=None: {"cli": judged})
    branch = {"name": "mybranch", "entry_file": str(apps / "main.py"), "path": str(apps.parent)}
    return lambda rules=(): branch_audit.audit_branch(branch, list(rules))


class TestTheIgnoreListRemovesOnlyWhatItWasWrittenFor:
    def test_tracked_source_under_a_like_named_directory_is_judged(self, repo_audit):
        """Mutant: the substring patterns back ("/integrations/", "/artifacts/", "/test/", ".old")."""
        out = repo_audit()
        root = Path(out["branch"]["path"])
        judged = {Path(v["path"]).relative_to(root).as_posix() for v in out["cli_violations"]}
        assert {
            "apps/handlers/integrations/call.py",
            "apps/handlers/artifacts/trade_ops.py",
            "apps/handlers/test/fixture.py",
            "apps/handlers/config.old.py",
        } <= judged

    def test_the_gitignored_driver_layer_is_removed_and_named(self, repo_audit):
        """Mutant: the removed-list not recorded."""
        out = repo_audit()
        assert out["ignored"] == {"/apps/integrations/": ["apps/integrations/google/driver.py"]}
        assert out["ignored_tracked"] == []

    def test_a_pattern_that_removes_tracked_source_is_convicted(self, repo_audit, monkeypatch):
        """Mutant: the checker blind to a tracked file (every removed file read as gitignored)."""
        # Unanchored, as the old substrings were: they reach tracked source under handlers/.
        monkeypatch.setattr(ignore_handler, "AUDIT_IGNORE_PATTERNS", ["integrations/", "artifacts/"])
        out = repo_audit()
        assert out["ignored_tracked"] == ["apps/handlers/artifacts/trade_ops.py", "apps/handlers/integrations/call.py"]

    def test_the_summary_and_the_artifact_name_what_the_list_removed(self, repo_audit, tmp_path, capsys):
        """Mutant: the removed-list not in the output."""
        out = repo_audit()
        capsys.readouterr()
        audit_display.print_branch_summary(out)
        printed = [line for line in capsys.readouterr().out.splitlines() if "Ignored" in line]
        assert printed == ["  Ignored by the audit list: /apps/integrations/ 1"]
        doc = artifact.build_artifact([out])
        assert doc["branches"][0]["ignored"] == {"/apps/integrations/": ["apps/integrations/google/driver.py"]}


#: One rule per way to be dead, then one live rule and the two blank-field forms.
RULES = [
    {"file": "apps/gone.py", "standard": "cli", "reason": "gone file"},
    {"file": "apps/main.py", "standard": "open_encoding", "reason": "retired standard"},
    {"file": "apps/main.py", "standard": "cli", "lines": [40], "reason": "past the end"},
    {"file": "apps/main.py", "standard": "cli", "lines": [1], "reason": "live"},
    {"file": "", "standard": "cli", "reason": "blank file"},
    {"file": "apps/gone.py", "standard": "", "reason": "blank standard"},
]


class TestADeadBypassRuleOrCommentIsNamed:
    def test_a_gone_file_an_unknown_standard_and_lines_past_the_end_are_dead(self, repo_audit):
        """Mutants: blind to a gone file; blind to an unknown standard; blind to lines past the end."""
        out = repo_audit(RULES[:4])
        assert [(d["index"], d["reason"]) for d in out["bypass_dead"]] == [
            (0, "gone file"),
            (1, "retired standard"),
            (2, "past the end"),
        ]

    def test_a_blank_field_rule_is_dead_and_named(self, repo_audit):
        """Mutant: blind to a blank field. A rule needs a file and a standard (owner, 2026-09-25 18:55)."""
        assert [(d["index"], d["why"]) for d in repo_audit(RULES[3:])["bypass_dead"]] == [
            (1, "blank file: a rule needs a file and a standard to be active"),
            (2, "blank standard: a rule needs a file and a standard to be active"),
        ]

    def test_every_inline_bypass_comment_in_the_corpus_is_named(self, repo_audit, tmp_path):
        """Mutant: blind to a marker. A string that only mentions the form is not one."""
        marked = tmp_path / "mybranch" / "apps" / "handlers" / "marked.py"
        marked.write_text(
            'X = "# seedgo:bypass in a string"\n# seedgo:bypass standard=cli reason="r"\nY = 1  # seedgo:bypass\n',
            encoding="utf-8",
        )
        assert repo_audit()["bypass_markers"] == ["apps/handlers/marked.py:2", "apps/handlers/marked.py:3"]

    def test_the_summary_and_the_artifact_name_each_dead_rule_and_comment(self, repo_audit, tmp_path, capsys):
        """Mutants: the warning lines dropped; the artifact fields dropped."""
        (tmp_path / "mybranch" / "apps" / "main.py").write_text("# seedgo:bypass standard=cli\n", encoding="utf-8")
        out = repo_audit(RULES[:1])
        capsys.readouterr()
        audit_display.print_branch_summary(out)
        captured = capsys.readouterr()
        printed = " ".join((captured.out + captured.err).split())
        assert "Dead bypass rule [0] apps/gone.py / cli: file 'apps/gone.py' matches no file on disk" in printed
        assert "Inline bypass comment, read by nothing: apps/main.py:1" in printed
        entry = artifact.build_artifact([out])["branches"][0]
        assert [(d["index"], d["file"], d["standard"]) for d in entry["bypass_dead"]] == [(0, "apps/gone.py", "cli")]
        assert entry["bypass_markers"] == ["apps/main.py:1"]
