# =================== AIPass ====================
# Name: test_checkers_batch7_silent_catch.py
# Description: silent_catch_check: classify, report, guard, hand on, empty answer (split from test_checkers_batch7.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/aipass_standards/silent_catch_check.py and silent_catch_content.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that each checker in handlers/aipass_standards/ parses and imports

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import silent_catch_check
from aipass.seedgo.apps.handlers.aipass_standards.silent_catch_content import get_silent_catch_standards

pytestmark = pytest.mark.usefixtures("_pin_bypass_log")


class TestSilentCatchAllowsClassifyingAnExceptionIntoAValue:
    """@spawn's report (2026-08-31): `except FileNotFoundError: return "absent"`"""

    def _lines(self, tmp_path, source):
        target = tmp_path / "probe.py"
        target.write_text(source, encoding="utf-8")
        result = silent_catch_check.check_module(str(target))
        return result["checks"][0]["message"], result["checks"][0]["passed"]

    def test_a_named_exception_returning_a_constant_is_not_a_silent_catch(self, tmp_path):
        source = (
            "def final_state(path):\n"
            "    try:\n        return path.read_text()\n"
            "    except FileNotFoundError:\n        return 'absent'\n"
        )
        _message, passed = self._lines(tmp_path, source)
        assert passed is True

    def test_a_tuple_of_named_exceptions_still_qualifies(self, tmp_path):
        source = (
            "def verdict(run):\n"
            "    try:\n        return run()\n"
            "    except (AssertionError, ValueError):\n        return 'FAILED'\n"
        )
        _message, passed = self._lines(tmp_path, source)
        assert passed is True

    def test_a_dotted_exception_name_qualifies(self, tmp_path):
        """pytest.skip.Exception is the shape @spawn actually catches."""
        source = (
            "import pytest\n\n"
            "def verdict(run):\n"
            "    try:\n        return run()\n"
            "    except pytest.skip.Exception:\n        return 'SKIPPED'\n"
        )
        _message, passed = self._lines(tmp_path, source)
        assert passed is True

    def test_catching_exception_broadly_keeps_its_finding(self, tmp_path):
        """ "It failed" is not a classification: the type carries no meaning, so
        the caller learns nothing the return value could not have hidden."""
        source = "def f(run):\n    try:\n        return run()\n    except Exception:\n        return False\n"
        _message, passed = self._lines(tmp_path, source)
        assert passed is False

    def test_a_bare_except_keeps_its_finding(self, tmp_path):
        source = "def f(run):\n    try:\n        return run()\n    except:\n        return None\n"
        _message, passed = self._lines(tmp_path, source)
        assert passed is False

    def test_a_named_exception_that_only_passes_keeps_its_finding(self, tmp_path):
        """No value leaves the handler, so nothing was classified."""
        source = "def f(run):\n    try:\n        run()\n    except FileNotFoundError:\n        pass\n"
        _message, passed = self._lines(tmp_path, source)
        assert passed is False

    def test_a_named_exception_that_continues_keeps_its_finding(self, tmp_path):
        source = (
            "def f(items):\n    for i in items:\n        try:\n            i()\n"
            "        except FileNotFoundError:\n            continue\n"
        )
        _message, passed = self._lines(tmp_path, source)
        assert passed is False

    def test_extra_statements_before_the_return_keep_the_finding(self, tmp_path):
        """The shape is a CONVERSION, not a body that happens to end in one —
        work done on the way out is work the finding should still be read for."""
        source = (
            "def f(run, state):\n    try:\n        return run()\n"
            "    except FileNotFoundError:\n        state['seen'] = True\n        return 'absent'\n"
        )
        _message, passed = self._lines(tmp_path, source)
        assert passed is False

    def test_a_computed_return_is_not_a_constant(self, tmp_path):
        source = (
            "def f(run, fallback):\n    try:\n        return run()\n"
            "    except FileNotFoundError:\n        return fallback()\n"
        )
        _message, passed = self._lines(tmp_path, source)
        assert passed is False

    def test_a_return_carrying_the_caught_exception_qualifies(self, tmp_path):
        """`return ("FAILED", str(exc))` carries MORE than a constant does."""
        source = (
            "def verdict(run):\n"
            "    try:\n        return ('PASSED', '')\n"
            "    except AssertionError as exc:\n        return ('FAILED', str(exc))\n"
        )
        _message, passed = self._lines(tmp_path, source)
        assert passed is True

    def test_a_computed_return_that_never_mentions_the_exception_stays_flagged(self, tmp_path):
        """Binding `as exc` is not enough — the value has to carry it."""
        source = (
            "def f(run, fallback):\n    try:\n        return run()\n"
            "    except FileNotFoundError as exc:\n        return fallback()\n"
        )
        _message, passed = self._lines(tmp_path, source)
        assert passed is False

    def test_counting_the_exception_and_continuing_stays_flagged(self, tmp_path):
        """A counter may be asserted on later or may be read by nobody, and this
        checker cannot see which — so the finding stands and the reader rules."""
        source = (
            "def f(items):\n    missing = 0\n    for i in items:\n        try:\n            i()\n"
            "        except FileNotFoundError:\n            missing += 1\n            continue\n    return missing\n"
        )
        _message, passed = self._lines(tmp_path, source)
        assert passed is False


class TestSilentCatchAllowsAHandlerThatReportsToAStream:
    """@commons' report (2026-08-31): a handler that PRINTS the failure was
    flagged as swallowing it."""

    def _passed(self, tmp_path, source):
        target = tmp_path / "probe.py"
        target.write_text(source, encoding="utf-8")
        return silent_catch_check.check_module(str(target))["checks"][0]["passed"]

    def test_a_handler_writing_to_stderr_is_not_silent(self, tmp_path):
        source = (
            "import sys\n\n"
            "try:\n    x = resolve()\n"
            "except OSError as exc:\n    sys.stderr.write(f'cannot resolve: {exc}\\n')\n"
        )
        assert self._passed(tmp_path, source) is True

    def test_a_handler_writing_to_stdout_is_not_silent_either(self, tmp_path):
        """The standard's word is 'silently', not 'stderr'. A report on stdout
        is a worse choice and a separate standard's argument, but it is still
        not silence, and this checker must not decide that question."""
        source = "import sys\n\ntry:\n    go()\nexcept OSError:\n    sys.stdout.write('failed\\n')\n"
        assert self._passed(tmp_path, source) is True

    def test_the_write_must_be_to_a_stream_not_any_write_method(self, tmp_path):
        """Negative control on the clause: ``handle.write(...)`` puts the
        failure in a file nobody is watching. Keying on the method name alone
        would have exempted every handler that quietly writes to disk."""
        source = "def f(handle):\n    try:\n        go()\n    except OSError:\n        handle.write('failed')\n"
        assert self._passed(tmp_path, source) is False

    def test_a_handler_that_reports_nothing_keeps_its_finding(self, tmp_path):
        source = "try:\n    go()\nexcept OSError:\n    pass\n"
        assert self._passed(tmp_path, source) is False

    def test_the_real_reported_shape_clears(self, tmp_path):
        """@commons' own block, transcribed. The pin the report actually earns."""
        source = (
            "import sys\n"
            "from pathlib import Path\n\n"
            "_script_dirs = [str(Path(__file__).parent)]\n"
            "try:\n    _script_dirs.append(str(Path(__file__).resolve().parent))\n"
            "except OSError as _exc:\n"
            "    sys.stderr.write(f'[commons] Cannot resolve {__file__} ({type(_exc).__name__})\\n')\n"
        )
        assert self._passed(tmp_path, source) is True


class TestAHandlerThatGuardsItsOwnDiagnosticIsNotSilent:
    """@daemon and @canary, 2026-08-31, the same site from two sides."""

    def _passed(self, tmp_path, source):
        target = tmp_path / "probe.py"
        target.write_text(source, encoding="utf-8")
        return silent_catch_check.check_module(str(target))["checks"][0]["passed"]

    def test_a_pass_guarding_a_logger_call_is_not_silent(self, tmp_path):
        source = "def f(logger, exc):\n    try:\n        logger.debug('failed: %s', exc)\n    except Exception:\n        pass\n"
        assert self._passed(tmp_path, source) is True

    def test_a_pass_guarding_a_stream_report_is_not_silent(self, tmp_path):
        """@canary's shape: the write composes its message with type(exc), and
        counting THAT call as an effect would miss it."""
        source = (
            "import sys\n\n"
            "def f(name, exc, reported):\n"
            "    try:\n"
            "        if name not in reported:\n"
            "            reported.add(name)\n"
            "            sys.stderr.write(f'{name}: {type(exc).__name__}: {exc}\\n')\n"
            "    except OSError:\n        pass\n"
        )
        assert self._passed(tmp_path, source) is True

    def test_a_pass_guarding_real_work_keeps_its_finding(self, tmp_path):
        """The clause is on what the block DOES, not on the handler being empty."""
        source = "def f(path):\n    try:\n        path.unlink()\n    except OSError:\n        pass\n"
        assert self._passed(tmp_path, source) is False

    def test_a_report_standing_beside_real_work_does_not_buy_the_exemption(self, tmp_path):
        """The purity clause, pinned because a mutant walked through it."""
        source = (
            "def f(logger, path):\n    try:\n"
            "        logger.debug('about to unlink')\n        path.unlink()\n"
            "    except OSError:\n        pass\n"
        )
        assert self._passed(tmp_path, source) is False

    def test_a_file_handle_write_is_not_a_report(self, tmp_path):
        """The stream qualification, pinned on THIS clause rather than on
        silent_catch's own helper: a mutant accepting any ``.write`` survived until this negative control."""
        source = "def f(handle):\n    try:\n        handle.write('note')\n    except OSError:\n        pass\n"
        assert self._passed(tmp_path, source) is False

    def test_a_block_of_pure_bookkeeping_is_not_a_diagnostic(self, tmp_path):
        """Negative control: bookkeeping may sit BESIDE a report, never stand in
        for one. Without the at-least-one-report clause, every `seen.add(x)`"""
        source = "def f(seen, x):\n    try:\n        seen.add(x)\n    except OSError:\n        pass\n"
        assert self._passed(tmp_path, source) is False


class TestAHandlerThatHandsTheExceptionOnIsNotSilent:
    """@daemon's second shape, one level out from @spawn's classify-and-return:"""

    def _passed(self, tmp_path, source):
        target = tmp_path / "probe.py"
        target.write_text(source, encoding="utf-8")
        return silent_catch_check.check_module(str(target))["checks"][0]["passed"]

    def test_passing_the_exception_to_a_named_reporter_is_not_silent(self, tmp_path):
        source = (
            "def f(path, record):\n    try:\n        return path.resolve()\n"
            "    except OSError as exc:\n        record(path, exc)\n        return path\n"
        )
        assert self._passed(tmp_path, source) is True

    def test_retaining_the_exception_in_a_list_is_not_silent(self, tmp_path):
        source = "def f(kept):\n    try:\n        go()\n    except OSError as exc:\n        kept.append(str(exc))\n"
        assert self._passed(tmp_path, source) is True

    def test_binding_the_exception_and_ignoring_it_keeps_its_finding(self, tmp_path):
        """The clause is that the object LEAVES. Binding `as exc` and dropping it
        is the defect wearing the exemption's syntax."""
        source = "def f(cleanup):\n    try:\n        go()\n    except OSError as exc:\n        cleanup()\n"
        assert self._passed(tmp_path, source) is False

    def test_an_unbound_handler_cannot_borrow_the_clause(self, tmp_path):
        """No `as` means no exception object to hand on, however many calls the
        body makes. Without this, `except OSError: cleanup(path)` would pass."""
        source = "def f(path, cleanup):\n    try:\n        go()\n    except OSError:\n        cleanup(path)\n"
        assert self._passed(tmp_path, source) is False


class TestTheEmptyAnswerIsAConstantWhateverItsType:
    """Caught by dogfooding: my own new cli_check helper scored 0 on
    silent_catch for ``except SyntaxError: return set()``."""

    def _judge(self, tmp_path, body):
        """check_module flags the handler returning ``body``. Mutant: _judge_handler bypassed in silent_catch_check.py — killed."""
        source = f"def f(c):\n    try:\n        return parse(c)\n    except SyntaxError:\n        {body}\n"
        target = tmp_path / "probe.py"
        target.write_text(source, encoding="utf-8")
        return silent_catch_check.check_module(str(target))["checks"][0]["passed"] is False

    @pytest.mark.parametrize("body", ["return []", "return {}", "return ()", "return set()", "return frozenset()"])
    def test_an_empty_container_is_the_same_answer_as_an_empty_string(self, tmp_path, body):
        assert self._judge(tmp_path, body) is False, body

    def test_the_scalar_spellings_still_pass(self, tmp_path):
        """Control: the clause this widens must keep working."""
        assert self._judge(tmp_path, 'return ""') is False
        assert self._judge(tmp_path, "return 0") is False

    @pytest.mark.parametrize("body", ["return [1, 2]", "return {'a': 1}", "return {'x'}"])
    def test_a_non_empty_literal_keeps_its_finding(self, tmp_path, body):
        """The boundary, and the reason the clause is not just "any literal": a
        handler that invents content is not reporting an absence; the same container emptied passes."""
        emptied = {"return [1, 2]": "return []", "return {'a': 1}": "return {}", "return {'x'}": "return set()"}
        assert self._judge(tmp_path, body) is True, body
        assert self._judge(tmp_path, emptied[body]) is False, body

    @pytest.mark.parametrize("body", ["return list(c)", "return dict(a=1)", "return set(c)"])
    def test_a_builtin_called_with_arguments_keeps_its_finding(self, tmp_path, body):
        """Negative control for the call form. ``set()`` is the empty set;
        ``set(c)`` is a computed answer wearing the same name."""
        assert self._judge(tmp_path, body) is True, body
        assert self._judge(tmp_path, body.split("(")[0] + "()") is False, body

    def test_a_computed_return_still_keeps_its_finding(self, tmp_path):
        assert self._judge(tmp_path, "return compute(c)") is True

    @pytest.mark.parametrize("body", ["return compute()", "return build_default()", "return Path()"])
    def test_a_zero_argument_call_to_anything_else_keeps_its_finding(self, tmp_path, body):
        """Mutation control (M4, survived the first run). Dropping the builtin
        name check exempted every no-argument call; the clause is the NAME and the emptiness together."""
        assert self._judge(tmp_path, body) is True, body
        assert self._judge(tmp_path, "return list()") is False

    def test_a_broad_except_gains_nothing_from_this(self, tmp_path):
        """The specific-exception clause is what makes the returned value
        meaningful. ``except Exception`` learns the caller nothing, so an empty
        list from it is still a swallow."""
        source = "def f(c):\n    try:\n        return parse(c)\n    except Exception:\n        return []\n"
        target = tmp_path / "probe.py"
        target.write_text(source, encoding="utf-8")
        result = silent_catch_check.check_module(str(target))
        assert result["checks"][0]["passed"] is False
        assert result["checks"][0]["message"].startswith("1 silent catch(es) on lines 4 ")

    def test_my_own_helper_is_the_case_that_found_this(self):
        """End-to-end on the live file, because dogfooding is what surfaced it
        and a synthetic-only pin would not have."""
        from pathlib import Path

        target = Path(__file__).resolve().parents[1] / "apps" / "handlers" / "aipass_standards" / "cli_check.py"
        assert target.exists(), target
        assert "_stderr_directed_print_lines" in target.read_text(encoding="utf-8")
        assert silent_catch_check.check_module(str(target))["score"] == 100

    def test_the_empty_answer_ruling_is_published_too(self):
        """@commons' point, applied to my own new clause the same day: a rule
        that lives only in the checker makes every branch discover it by
        failing."""
        content = get_silent_catch_standards()
        assert "EMPTY ANSWER" in content
        assert "return set()" in content
        assert "return set(c)" in content
