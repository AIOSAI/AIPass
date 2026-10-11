# =================== AIPass ====================
# Name: test_checkers_batch7_error_handling.py
# Description: error_handling_check ruling (split from test_checkers_batch7.py) + exception_text_in_response_check
# Version: 1.1.0
# Created: 2026-10-08
# Modified: 2026-10-10
# =============================================

"""Tests for apps/handlers/aipass_standards/error_handling_check.py and exception_text_in_response_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that each checker in handlers/aipass_standards/ parses and imports

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import error_handling_check, exception_text_in_response_check

pytestmark = pytest.mark.usefixtures("_pin_bypass_log")


class TestErrorHandlingSharesTheDiagnosticGuardClause:
    """Two checkers, one question, one implementation — @canary's point that a
    single discriminator clears both findings. Shared rather than copied so the
    two cannot drift into disagreeing about the same handler.
    """

    def _passed(self, tmp_path, source):
        target = tmp_path / "probe.py"
        target.write_text(source, encoding="utf-8")
        return error_handling_check.check_module(str(target))["checks"][0]["passed"]

    def test_a_pass_guarding_a_report_is_not_a_silent_failure(self, tmp_path):
        source = "def f(logger, exc):\n    try:\n        logger.debug('x', exc)\n    except Exception:\n        pass\n"
        assert self._passed(tmp_path, source) is True

    def test_a_pass_over_real_work_is_still_a_silent_failure(self, tmp_path):
        """error_handling's own finding names the file and the handler's line.

        It was the same body as silent_catch's
        test_a_pass_guarding_real_work_keeps_its_finding; the property this
        checker adds is where it points (seedgo, fleet green leg 8).
        """
        source = "def f(path):\n    try:\n        path.unlink()\n    except OSError:\n        pass\n"
        target = tmp_path / "probe.py"
        target.write_text(source, encoding="utf-8")
        check = error_handling_check.check_module(str(target))["checks"][0]
        assert check["passed"] is False
        assert check["message"] == (
            f"Silent failure detected (except: pass) in {target.name} at line 4 - errors should log/return"
        )


# Minimised from @api apps/handlers/host/server.py at 38166f35: _deny (:225) and the
# git-changes (:847-852), machine (:973-978) and lock (:994-997) route bodies.
ROUTE_HEAD = (
    "from fastapi import HTTPException\n"
    "\n"
    "def _deny(status, code, message, **extra):\n"
    '    return HTTPException(status_code=status, detail={"error": {"code": code, "message": message}})\n'
    "\n"
    "def build(app, host, logger):\n"
    '    @app.get("/v1/machine")\n'
    "    def machine():\n"
    "        try:\n"
    "            return host.read_machine()\n"
)


def _route(handler_lines):
    """The route above with one except clause; its first handler line is line 11."""
    return ROUTE_HEAD + "".join(f"        {line}\n" for line in handler_lines)


class TestExceptionTextInResponseConvictsTheLeak:
    """CodeQL py/stack-trace-exposure, PR #774 round seven: exception text in an HTTP body."""

    def _check(self, tmp_path, source):
        target = tmp_path / "server.py"
        target.write_text(source, encoding="utf-8")
        return exception_text_in_response_check.check_module(str(target))

    @pytest.mark.parametrize(
        "handler",
        [
            ["except ReadRefused as e:", '    raise _deny(400, "read_refused", str(e)) from e'],
            [
                "except MachineRefused as e:",
                '    raise _deny(503, "machine_refused", e.detail, reason=e.reason) from e',
            ],
            ["except DoorFailed as exc:", '    raise HTTPException(status_code=503, detail=f"door failed: {exc}")'],
            ["except DoorFailed as exc:", "    raise HTTPException(503, repr(exc))"],
            ["except DoorFailed as exc:", '    return JSONResponse(content={"error": exc.args[0]}, status_code=503)'],
            ["except DoorFailed as exc:", '    return {"ok": False, "detail": str(exc)}'],
            ["except DoorFailed as exc:", '    message = "failed: %s" % exc', "    return message"],
            ["except DoorFailed:", '    return {"trace": traceback.format_exc()}'],
        ],
    )
    def test_exception_text_reaching_the_body_is_a_row_on_the_sink_line(self, tmp_path, handler):
        result = self._check(tmp_path, _route(handler))
        check = result["checks"][0]
        assert (result["passed"], result["score"], check["passed"]) == (False, 0, False)
        sink_line = 10 + len(handler)
        assert check["message"].startswith(f"server.py:{sink_line} exception text reaches an HTTP response")

    @pytest.mark.parametrize(
        "handler",
        [
            [
                "except ReadRefused as e:",
                '    logger.error("read refused: %s", e, exc_info=True)',
                '    raise _deny(400, "read_refused", "the read was refused") from e',
            ],
            ["except DoorFailed as exc:", '    raise _deny(503, "door_failed", type(exc).__name__) from exc'],
            ["except DoorFailed as exc:", "    raise DoorDown(str(exc)) from exc"],
            [
                "except DoorFailed as exc:",
                '    message = f"{exc}"',
                '    message = "door failed"',
                "    return message",
            ],
        ],
    )
    def test_text_that_goes_only_to_the_log_or_a_class_name_is_not_a_row(self, tmp_path, handler):
        result = self._check(tmp_path, _route(handler))
        assert (result["passed"], result["score"]) == (True, 100)
        assert result["checks"][0].get("declined") is not True

    def test_a_module_with_no_web_framework_and_no_route_declines(self, tmp_path):
        source = (
            "def read(door):\n"
            "    try:\n"
            "        return door()\n"
            "    except OSError as e:\n"
            '        return {"detail": str(e)}\n'
        )
        result = self._check(tmp_path, source)
        assert (result["passed"], result.get("not_applicable"), result["checks"][0]["declined"]) == (True, True, True)

    def test_a_route_decorator_alone_puts_a_module_in_scope(self, tmp_path):
        source = (
            '@app.route("/v1/x")\n'
            "def x():\n"
            "    try:\n"
            "        return read()\n"
            "    except OSError as e:\n"
            '        return {"detail": str(e)}\n'
        )
        assert self._check(tmp_path, source)["checks"][0]["message"].startswith("server.py:6 ")
