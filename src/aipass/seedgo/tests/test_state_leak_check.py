# =================== META ====================
# Name: test_state_leak_check.py
# Description: state_leak_check — test template v1 item 18, no test leaks state into the next
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""Tests for apps/handlers/aipass_standards/state_leak_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — that ast.parse builds the tree it documents
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — applies_to_file's production/tests split; tests/test_applicability.py
# seedgo: no-test-needed(constant) — the prose of CURES; the shapes and line numbers are asserted

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import skip_dirs, state_leak_check
from aipass.seedgo.apps.modules import checklist

#: The fleet's gold test file for this item, resolved from this file's own
#: location so the test reads the real thing on any host.
MODEL = Path(__file__).resolve().parent / "test_readme_update.py"

#: Every sample here imports a product module so the rule can see the base of an
#: attribute write at all. Spelled once.
IMPORT = "from aipass.trigger.apps.modules import log_watcher as lw\n"


def _write(tmp_path, body, name="test_thing.py"):
    """A test file on disk under a tests/ directory, which is what the rule scopes to."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    path = tests_dir / name
    path.write_text(body, encoding="utf-8")
    return path


def _found(source):
    """Just what each hit names, in line order."""
    return [what for _line, what, _cure in state_leak_check.scan(source)]


def _lines(source):
    """Just the line each hit sits on, in order."""
    return [line for line, _what, _cure in state_leak_check.scan(source)]


class TestADirectWriteToSharedState:
    """Shape (a): state the whole process shares, changed with nothing to put it back."""

    def test_an_environment_variable_is_a_hit(self):
        source = 'import os\n\ndef test_x():\n    os.environ["AIPASS_BRANCH"] = "spawn"\n'

        assert _found(source) == ["a write to os.environ with nothing to put it back"]

    def test_deleting_an_environment_variable_is_a_hit(self):
        source = 'import os\n\ndef test_x():\n    del os.environ["AIPASS_BRANCH"]\n'

        assert _lines(source) == [4]

    def test_popping_one_is_a_hit_too(self):
        """os.environ.pop() changes the same dict by another verb. 7 fleet sites."""
        source = 'import os\n\ndef test_x():\n    os.environ.pop("AIPASS_BRANCH", None)\n'

        assert _found(source) == ["os.environ.pop() with nothing to put it back"]

    def test_a_sys_path_write_is_a_hit(self):
        source = "import sys\n\ndef test_x():\n    sys.path.insert(0, '/opt/thing')\n"

        assert _found(source) == ["sys.path.insert() with nothing to put it back"]

    def test_a_product_module_attribute_is_a_hit(self):
        """@trigger's test_log_watcher.py alone carries 92 of these."""
        source = IMPORT + "\ndef test_x():\n    lw.WATCHDOG_AVAILABLE = False\n"

        assert _found(source) == ["a write to the product's lw.WATCHDOG_AVAILABLE"]

    def test_setattr_on_a_product_module_is_the_same_hit(self):
        source = IMPORT + '\ndef test_x():\n    setattr(lw, "_event_queue", None)\n'

        assert _found(source) == ["setattr on the product's lw._event_queue"]

    def test_the_line_number_is_the_write(self):
        source = IMPORT + "\ndef test_x():\n    value = 1\n    lw.FLAG = value\n"

        assert _lines(source) == [5]

    def test_every_write_in_one_function_is_its_own_hit(self):
        source = IMPORT + "\ndef test_x():\n    lw.A = 1\n    lw.B = 2\n"

        assert _lines(source) == [4, 5]


class TestAPatcherStartedAndNeverStopped:
    """Shape (b). Only the manual form can be left running -- `with` and `@patch` cannot."""

    def test_start_with_no_stop_is_a_hit(self):
        source = 'def test_x():\n    p = patch("aipass.x.y")\n    p.start()\n'

        assert _found(source) == ["p.start() with no stop()"]

    def test_start_with_a_stop_is_clean(self):
        source = 'def test_x():\n    p = patch("aipass.x.y")\n    p.start()\n    p.stop()\n'

        assert _found(source) == []

    def test_addcleanup_counts_as_stopping_it(self):
        source = 'def test_x(self):\n    p = patch("aipass.x.y")\n    p.start()\n    self.addCleanup(p.stop)\n'

        assert _found(source) == []

    def test_a_with_block_is_never_a_hit(self):
        """It restores on exit, which is the whole point of the context manager."""
        source = 'def test_x():\n    with patch("aipass.x.y"):\n        run()\n'

        assert _found(source) == []

    def test_a_start_on_something_that_is_not_a_patcher_is_not_a_hit(self):
        """28 fleet .start() calls are threads, observers and monitors."""
        source = "def test_x():\n    observer = Observer()\n    observer.start()\n"

        assert _found(source) == []


class TestOsChdir:
    """Shape (c). monkeypatch.chdir is the cure and the fleet uses it 257 times."""

    def test_chdir_with_no_restore_is_a_hit(self):
        source = "import os\n\ndef test_x():\n    os.chdir('/tmp')\n"

        assert _found(source) == ["os.chdir with no restore"]

    def test_chdir_in_a_function_that_also_monkeypatches_the_cwd_is_clean(self):
        """@drone does exactly this: monkeypatch.chdir first, then walk deeper."""
        source = (
            "import os\n\ndef test_x(monkeypatch, tmp_path):\n    monkeypatch.chdir(tmp_path)\n    os.chdir('sub')\n"
        )

        assert _found(source) == []


class TestWhatIsNeverConvicted:
    """Each carve-out carries its fleet count; none of them is a guess."""

    @pytest.mark.parametrize(
        "verb,write",
        [
            ("monkeypatch.setenv('K', 'v')", 'os.environ["K"] = "v"'),
            ("monkeypatch.setitem(sys.modules, 'x', None)", 'sys.modules["x"] = None'),
            ("monkeypatch.syspath_prepend('/x')", "sys.path.insert(0, '/x')"),
        ],
    )
    def test_a_function_that_uses_the_cure_is_credited_for_that_family(self, verb, write):
        """4,889 monkeypatch uses fleet-wide. They are the cure, not the offence."""
        source = f"import os\nimport sys\n\ndef test_x(monkeypatch):\n    {verb}\n    {write}\n"

        assert _found(source) == []

    def test_the_cure_credits_one_family_and_not_another(self):
        """setenv says nothing about sys.path, so the sys.path write still stands."""
        source = (
            "import os\nimport sys\n\ndef test_x(monkeypatch):\n"
            "    monkeypatch.setenv('K', 'v')\n    sys.path.insert(0, '/x')\n"
        )

        assert _found(source) == ["sys.path.insert() with nothing to put it back"]

    def test_an_autouse_restoring_fixture_covers_the_whole_file(self):
        source = (
            "import os\nimport pytest\n\n"
            "@pytest.fixture(autouse=True)\n"
            "def clean_env():\n"
            "    saved = dict(os.environ)\n"
            "    yield\n"
            "    os.environ.clear()\n"
            "    os.environ.update(saved)\n"
            "\n"
            'def test_x():\n    os.environ["K"] = "v"\n'
        )

        assert _found(source) == []

    def test_a_named_fixture_covers_only_the_tests_that_request_it(self):
        """@ai_mail's clean_env. Matching by REQUEST is what makes the 39 acquittals honest."""
        source = (
            "import os\nimport pytest\n\n"
            "@pytest.fixture\n"
            "def clean_env():\n"
            "    saved = dict(os.environ)\n"
            "    yield\n"
            "    os.environ.update(saved)\n"
            "\n"
            'def test_covered(clean_env):\n    os.environ["K"] = "v"\n'
            "\n"
            'def test_uncovered():\n    os.environ["K"] = "v"\n'
        )

        assert _lines(source) == [14]

    def test_a_fixture_with_no_teardown_credits_nothing(self):
        """No yield and no finally means it never runs after the test.

        Line 6 is the fixture's own write and line 9 is the test's: neither is
        covered, and a setup-only fixture leaks into the next file all by itself.
        """
        source = (
            "import os\nimport pytest\n\n"
            "@pytest.fixture(autouse=True)\n"
            "def setup_env():\n"
            '    os.environ["SEED"] = "1"\n'
            "\n"
            'def test_x():\n    os.environ["K"] = "v"\n'
        )

        assert _lines(source) == [6, 9]

    def test_a_try_finally_in_the_same_function_is_item_18_done_by_hand(self):
        """@drone's test_registry.py saves the entry, swaps it, and puts it back."""
        source = (
            "import sys\n\n"
            "def test_x():\n"
            '    saved = sys.modules.get("x")\n'
            "    try:\n"
            '        sys.modules["x"] = None\n'
            "        run()\n"
            "    finally:\n"
            '        sys.modules["x"] = saved\n'
        )

        assert _found(source) == []

    def test_a_sys_modules_stub_naming_an_aipass_module_belongs_to_import_site(self):
        """Item 8 already convicts it, and one habit is never charged twice."""
        source = 'import sys\n\ndef test_x():\n    sys.modules["aipass.prax"] = object()\n'

        assert _found(source) == []

    def test_a_sys_modules_write_naming_anything_else_is_a_hit(self):
        source = 'import sys\n\ndef test_x():\n    sys.modules["watchdog"] = object()\n'

        assert _found(source) == ["a write to sys.modules with nothing to put it back"]

    def test_a_write_to_something_the_test_built_is_not_shared_state(self):
        source = "def test_x():\n    holder = Thing()\n    holder.flag = True\n"

        assert _found(source) == []

    def test_a_nested_attribute_on_a_product_module_configures_an_object_not_the_module(self):
        """`mod.helper.return_value = x` is a Mock being set up. 45 fleet nominations."""
        source = IMPORT + "\ndef test_x():\n    lw.is_enabled.return_value = False\n"

        assert _found(source) == []

    def test_a_syntax_error_yields_nothing(self):
        """ruff already convicts it, and an invented line number is the wrong address."""
        assert state_leak_check.scan("def broken(:\n") == []


class TestTheImportTimeWriteIsCountedNotConvicted:
    """Item 18 is about one test leaking into the NEXT. 21 fleet sites, 19 files."""

    def test_a_module_level_write_is_not_a_hit(self):
        source = 'import os\n\nos.environ["AIPASS_TEST_LOG_DIR"] = "logs"\n\ndef test_x():\n    assert True\n'

        assert _found(source) == []

    def test_the_count_rides_in_the_passing_message(self, tmp_path):
        path = _write(tmp_path, 'import os\n\nos.environ["A"] = "1"\n')

        result = state_leak_check.check_module(str(path))

        assert result["score"] == 100
        assert "1 import-time write is counted" in result["checks"][0]["message"]

    def test_several_are_counted_in_the_plural(self, tmp_path):
        path = _write(tmp_path, 'import os\n\nos.environ["A"] = "1"\nos.environ["B"] = "2"\n')

        message = state_leak_check.check_module(str(path))["checks"][0]["message"]

        assert "2 import-time writes are counted" in message

    def test_a_file_with_none_says_only_that_everything_is_put_back(self, tmp_path):
        path = _write(tmp_path, "def test_x(monkeypatch):\n    monkeypatch.setenv('K', 'v')\n")

        message = state_leak_check.check_module(str(path))["checks"][0]["message"]

        assert message == "Every change this file makes is put back"
        assert "counted" not in message


class TestTheMessageAnAuthorReads:
    """Every hit on one check, because _format_failure shows the first and hides the rest."""

    def test_all_hits_share_one_check(self, tmp_path):
        source = "import os\nimport sys\n\ndef test_x():\n    os.environ['A'] = '1'\n    sys.path.insert(0, '/x')\n"
        path = _write(tmp_path, source)

        result = state_leak_check.check_module(str(path))

        assert len(result["checks"]) == 1
        assert result["checks"][0]["message"].count("test_thing.py:") == 2

    def test_the_message_names_the_file_the_line_and_the_cure(self, tmp_path):
        path = _write(tmp_path, "import os\n\ndef test_x():\n    os.environ['A'] = '1'\n")

        message = state_leak_check.check_module(str(path))["checks"][0]["message"]

        assert message == (
            "test_thing.py:4 a write to os.environ with nothing to put it back "
            "- monkeypatch.setenv / monkeypatch.delenv"
        )

    def test_each_family_names_its_own_cure(self, tmp_path):
        source = IMPORT + "\ndef test_x():\n    lw.FLAG = True\n"
        path = _write(tmp_path, source)

        assert "monkeypatch.setattr" in state_leak_check.check_module(str(path))["checks"][0]["message"]

    def test_a_missing_file_scores_zero_and_says_which(self, tmp_path):
        result = state_leak_check.check_module(str(tmp_path / "tests" / "gone.py"))

        assert result["score"] == 0
        assert "File not found" in result["checks"][0]["message"]


class TestTheModelFileHoldsTheLine:
    """tests/test_readme_update.py is the fleet's gold test file for this item."""

    def test_the_model_file_passes(self):
        assert state_leak_check.check_module(str(MODEL))["score"] == 100

    def test_the_model_file_with_a_product_attribute_write_is_convicted(self, tmp_path):
        """Not a hand-written sample: the real file, plus the one line item 18 names."""
        source = MODEL.read_text(encoding="utf-8")
        mutated = source + "\n\ndef test_a_leak():\n    readme_update.console = MagicMock()\n"
        path = _write(tmp_path, mutated, name="test_readme_update.py")

        result = state_leak_check.check_module(str(path))

        assert result["score"] == 0
        assert "a write to the product's readme_update.console" in result["checks"][0]["message"]

    def test_the_model_file_with_an_unstopped_patcher_is_convicted(self, tmp_path):
        source = MODEL.read_text(encoding="utf-8")
        mutated = source + '\n\ndef test_a_patcher():\n    p = patch("aipass.x.y")\n    p.start()\n'
        path = _write(tmp_path, mutated, name="test_readme_update.py")

        result = state_leak_check.check_module(str(path))

        assert result["score"] == 0
        assert "p.start() with no stop()" in result["checks"][0]["message"]

    def test_the_model_file_doing_the_same_through_monkeypatch_is_clean(self, tmp_path):
        """The cure, on the real file: the write is there and the rule says nothing."""
        source = MODEL.read_text(encoding="utf-8")
        mutated = source + (
            "\n\ndef test_no_leak(monkeypatch):\n    monkeypatch.setattr(readme_update, 'console', MagicMock())\n"
        )
        path = _write(tmp_path, mutated, name="test_readme_update.py")

        assert state_leak_check.check_module(str(path))["score"] == 100


class TestThroughTheChecklistCommand:
    """The door an agent actually meets the rule through: the PostToolUse lane."""

    @pytest.fixture(autouse=True)
    def _not_a_scratchpad(self, monkeypatch):
        """tmp_path lives under a temp root, and checklist skips those by design."""
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    def test_the_command_convicts_a_leak(self, tmp_path, capsys):
        path = _write(tmp_path, "import os\n\ndef test_x():\n    os.environ['A'] = '1'\n")

        checklist.handle_command("checklist", [str(path)])

        out = capsys.readouterr().out
        assert "[FAIL] — state_leak" in out
        assert "monkeypatch" in out

    def test_the_command_stays_quiet_on_a_clean_file(self, tmp_path, capsys):
        """The standard still prints — as a tick. The absence to assert is the conviction."""
        path = _write(tmp_path, "def test_x(monkeypatch):\n    monkeypatch.setenv('A', '1')\n")

        checklist.handle_command("checklist", [str(path)])

        out = capsys.readouterr().out
        assert "✓ state_leak" in out
        assert "[FAIL] — state_leak" not in out
