# =================== META ====================
# Name: test_accepted_and_never_used_parameter_check.py
# Description: accepted_and_never_used_parameter_check — crack class M, a parameter the body never reads
# Version: 1.0.0
# Created: 2026-09-23
# Modified: 2026-09-23
# =============================================

"""Tests for apps/handlers/aipass_standards/accepted_and_never_used_parameter_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — applies_to_file's production/tests split; tests/test_applicability.py
# seedgo: no-test-needed(constant) — the prose of CURE; it is asserted by name

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import accepted_and_never_used_parameter_check as rule
from aipass.seedgo.apps.handlers.aipass_standards import skip_dirs
from aipass.seedgo.apps.modules import checklist

#: This checker's own source: a product file that must score 100, or the rule is wrong.
MODEL = Path(rule.__file__)

#: @backup's specimen, reduced to the shape — documented, accepted, never called.
SPECIMEN = (
    "def cleanup_deleted_files(backup_path, should_ignore, result):\n"
    '    """should_ignore: Callable(Path) -> bool for ignore check."""\n'
    "    for entry in backup_path.iterdir():\n"
    "        result.append(entry)\n"
)

#: The line that calls it, which is what makes the branch the owner of the signature.
CALLER = "from mirror import cleanup_deleted_files\n\n\ndef run():\n    cleanup_deleted_files(root, pred, [])\n"


def _branch(tmp_path, files):
    """A branch on disk: an apps/ tree and the .trinity/ that marks it a citizen."""
    (tmp_path / ".trinity").mkdir(exist_ok=True)
    apps = tmp_path / "apps"
    apps.mkdir(exist_ok=True)
    written = {}
    for name, body in files.items():
        path = apps / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        written[name] = path
    rule.branch_facts.cache_clear()
    return written


def _scored(tmp_path, files, subject="mirror.py"):
    """Just the (line, function, parameter) rows the rule charges against one file."""
    written = _branch(tmp_path, files)
    facts = rule.branch_facts(tmp_path)
    return rule.scan(written[subject].read_text(encoding="utf-8"), facts)[0]


class TestTheCheckersOwnSourcePasses:
    """A rule that convicts its own author is not ready to convict anybody else."""

    def test_this_checker_scores_100(self):
        assert rule.check_module(str(MODEL))["score"] == 100


class TestThePlantedSpecimen:
    """backup/apps/handlers/cleanup/mirror.py:92 — should_ignore, accepted and dropped."""

    def test_a_parameter_the_body_never_reads_is_convicted(self, tmp_path):
        assert _scored(tmp_path, {"mirror.py": SPECIMEN, "snapshot.py": CALLER}) == [
            (1, "cleanup_deleted_files", "should_ignore")
        ]

    def test_naming_it_in_the_docstring_does_not_clear_it(self, tmp_path):
        """The specimen documents the contract it never honours — that IS the defect."""
        rows = _scored(tmp_path, {"mirror.py": SPECIMEN, "snapshot.py": CALLER})

        assert "should_ignore" in SPECIMEN.splitlines()[1]
        assert [row[2] for row in rows] == ["should_ignore"]

    def test_reading_the_parameter_once_clears_it(self, tmp_path):
        """The cure, and the whole of it."""
        cured = SPECIMEN.replace("result.append(entry)", "result.append(entry) if not should_ignore(entry) else None")

        assert _scored(tmp_path, {"mirror.py": cured, "snapshot.py": CALLER}) == []

    def test_forwarding_it_by_keyword_clears_it(self, tmp_path):
        """Passing it on is using it."""
        cured = SPECIMEN.replace("result.append(entry)", "result.append(helper(entry, should_ignore=should_ignore))")

        assert _scored(tmp_path, {"mirror.py": cured, "snapshot.py": CALLER}) == []

    def test_the_call_site_is_not_the_one_convicted(self, tmp_path):
        """One defect, two lines: the verdict belongs where the cure lives."""
        assert _scored(tmp_path, {"mirror.py": SPECIMEN, "snapshot.py": CALLER}, subject="snapshot.py") == []


class TestHowYouTellAProtocol:
    """Four shapes that all say: somebody else owns this signature."""

    def test_a_function_the_branch_never_calls_is_acquitted(self, tmp_path):
        """pytest's hookspec, not the branch's, fixes pytest_runtest_logfinish."""
        body = "def pytest_runtest_logfinish(nodeid, location):\n    STATE.nodeid = '<session>'\n"

        assert _scored(tmp_path, {"mirror.py": body}) == []

    def test_a_name_handed_off_as_a_value_is_acquitted(self, tmp_path):
        """signal.signal(SIGINT, handler) — the consumer fixed the arity.

        The branch also CALLS it here, on purpose: without that call the
        never-called acquittal would carry the test on its own and the hand-off
        rule could be deleted without a single test noticing.
        """
        files = {
            "mirror.py": "def signal_handler(sig, frame):\n    raise SystemExit(0)\n",
            "snapshot.py": (
                "from mirror import signal_handler\n\n\n"
                "def arm():\n"
                "    signal.signal(2, signal_handler)\n"
                "    signal_handler(2, None)\n"
            ),
        }

        assert _scored(tmp_path, files) == []

    def test_an_import_alone_is_not_a_hand_off(self, tmp_path):
        """The discriminator the specimen depends on: importing only makes it callable."""
        assert _scored(tmp_path, {"mirror.py": SPECIMEN, "snapshot.py": CALLER}) != []

    def test_a_fallback_for_a_failed_import_is_acquitted(self, tmp_path):
        """@trigger's registry_should_dispatch returns True without reading its argument.

        That is what a no-op shim does: it stands in for the real module and must
        match its signature.
        """
        files = {
            "mirror.py": (
                "try:\n"
                "    from registry import should_dispatch\n"
                "except ImportError:\n"
                "    def should_dispatch(fingerprint):\n"
                "        return True\n"
            ),
            "snapshot.py": "from mirror import should_dispatch\n\n\ndef go():\n    should_dispatch('x')\n",
        }

        assert _scored(tmp_path, files) == []

    def test_a_name_defined_twice_in_the_branch_is_acquitted(self, tmp_path):
        """Two defs of one name are a shared shape with two implementations."""
        files = {
            "mirror.py": "def render(payload, width):\n    return payload\n",
            "snapshot.py": "def render(payload, width):\n    return payload[:width]\n\n\ndef go():\n    render(1, 2)\n",
        }

        assert _scored(tmp_path, files) == []


class TestTheOrdinaryExemptions:
    """Shapes nobody chose, and one Python has its own spelling for."""

    def test_self_and_cls_are_never_judged(self, tmp_path):
        body = "class Thing:\n    def run(self):\n        return 1\n\n\ndef go():\n    run()\n"

        assert _scored(tmp_path, {"mirror.py": body}) == []

    def test_star_args_and_kwargs_are_never_judged(self, tmp_path):
        """Not named parameters: a body that ignores them forwards a shape."""
        files = {
            "mirror.py": "def wrap(*args, **kwargs):\n    return 1\n",
            "snapshot.py": "from mirror import wrap\n\n\ndef go():\n    wrap()\n",
        }

        assert _scored(tmp_path, files) == []

    def test_an_underscore_prefixed_parameter_is_taken_at_its_word(self, tmp_path):
        """Python's own way of writing 'accepted and deliberately ignored'."""
        files = {
            "mirror.py": "def tick(_unused, value):\n    return value\n",
            "snapshot.py": "from mirror import tick\n\n\ndef go():\n    tick(1, 2)\n",
        }

        assert _scored(tmp_path, files) == []

    def test_a_decorated_function_is_acquitted(self, tmp_path):
        """The decorator may read the signature the body ignores."""
        files = {
            "mirror.py": "@app.route\ndef handle(request):\n    return 'ok'\n",
            "snapshot.py": "from mirror import handle\n\n\ndef go():\n    handle(1)\n",
        }

        assert _scored(tmp_path, files) == []

    @pytest.mark.parametrize("body", ["    pass", "    ...", "    raise NotImplementedError"])
    def test_a_stub_body_only_declares_a_shape(self, tmp_path, body):
        files = {
            "mirror.py": f"def measure(path, depth):\n{body}\n",
            "snapshot.py": "from mirror import measure\n\n\ndef go():\n    measure(1, 2)\n",
        }

        assert _scored(tmp_path, files) == []

    def test_a_dunder_signature_belongs_to_the_interpreter(self, tmp_path):
        body = "class Thing:\n    def __eq__(self, other):\n        return True\n\n\ndef go():\n    Thing()\n"

        assert _scored(tmp_path, {"mirror.py": body}) == []


class TestTheCorpusIsCodeNotProse:
    """A name written in a docstring is not the branch calling it."""

    def test_code_only_blanks_a_docstring(self):
        stripped = rule.code_only('def f():\n    """call g(1) here"""\n    return 2\n')

        assert "g(" not in stripped
        assert "return 2" in stripped

    def test_code_only_blanks_a_comment(self):
        assert "helper" not in rule.code_only("x = 1  # helper(2) is the shape\n")

    def test_prose_naming_a_function_does_not_make_the_branch_its_caller(self, tmp_path):
        """This checker's own docstring names pytest_runtest_logfinish — and convicted it."""
        files = {
            "mirror.py": "def pytest_runtest_logfinish(nodeid, location):\n    STATE.nodeid = 1\n",
            "snapshot.py": '"""Prose: pytest_runtest_logfinish(nodeid, location) is a hook."""\n',
        }

        assert _scored(tmp_path, files) == []

    def test_an_unreadable_file_degrades_to_the_raw_text(self):
        """A file caught mid-save raises IndentationError; the branch must survive it."""
        assert rule.code_only("def f(:\n") == "def f(:\n"


class TestTheEntryPoint:
    """check_module is the door the audit and the hook both come through."""

    def test_a_convicted_file_scores_zero_and_names_the_cure(self, tmp_path):
        written = _branch(tmp_path, {"mirror.py": SPECIMEN, "snapshot.py": CALLER})

        out = rule.check_module(str(written["mirror.py"]))

        assert out["score"] == 0
        assert out["passed"] is False
        assert rule.CURE in out["checks"][0]["message"]

    def test_every_hit_lands_on_one_check(self, tmp_path):
        """_format_failure prints the first failed check and hides the rest behind (+N more)."""
        body = "def run(alpha, beta, gamma):\n    return 1\n"
        written = _branch(tmp_path, {"mirror.py": body, "snapshot.py": "from mirror import run\n\nrun(1, 2, 3)\n"})

        out = rule.check_module(str(written["mirror.py"]))

        assert len(out["checks"]) == 1
        assert len(out["checks"][0]["message"].splitlines()) == 3

    def test_a_clean_file_counts_what_it_did_not_judge(self, tmp_path):
        written = _branch(tmp_path, {"mirror.py": "def orphan(alpha, beta):\n    return 1\n"})

        out = rule.check_module(str(written["mirror.py"]))

        assert out["score"] == 100
        assert "somebody else owns" in out["checks"][0]["message"]

    def test_a_file_with_no_branch_above_it_is_not_judged(self, tmp_path):
        """Who owns a signature cannot be answered without the branch."""
        loose = tmp_path / "loose.py"
        loose.write_text("def run(alpha):\n    return 1\n", encoding="utf-8")

        assert rule.check_module(str(loose))["score"] == 100

    def test_a_missing_file_fails_rather_than_passes_quietly(self, tmp_path):
        assert rule.check_module(str(tmp_path / "gone.py"))["score"] == 0

    def test_an_unparseable_file_yields_nothing(self, tmp_path):
        """ruff already convicts the syntax error; a second verdict misdirects."""
        written = _branch(tmp_path, {"mirror.py": "def run(:\n"})

        assert rule.check_module(str(written["mirror.py"]))["score"] == 100


class TestThroughTheCommand:
    """The door an agent actually meets the rule through: the PostToolUse lane."""

    @pytest.fixture(autouse=True)
    def _not_a_scratchpad(self, monkeypatch):
        """tmp_path lives under a temp root, and checklist skips those by design."""
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    def test_the_command_convicts_the_specimen(self, tmp_path, capsys):
        written = _branch(tmp_path, {"mirror.py": SPECIMEN, "snapshot.py": CALLER})

        checklist.handle_command("checklist", [str(written["mirror.py"])])

        out = capsys.readouterr().out
        assert "[FAIL] — accepted_and_never_used_parameter" in out
        assert "should_ignore" in out

    def test_the_command_stays_quiet_on_a_clean_file(self, tmp_path, capsys):
        """The standard still prints — as a tick. The absence to assert is the conviction."""
        written = _branch(tmp_path, {"mirror.py": "def run(value):\n    return value\n", "snapshot.py": CALLER})

        checklist.handle_command("checklist", [str(written["mirror.py"])])

        out = capsys.readouterr().out
        assert "✓ accepted_and_never_used_parameter" in out
