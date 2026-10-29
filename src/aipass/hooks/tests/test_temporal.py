# =================== AIPass ====================
# Name: test_temporal.py
# Version: 1.1.0
# Description: Tests for temporal prompt handler
# Branch: hooks
# Created: 2026-07-21
# Modified: 2026-10-28
# =============================================

"""Tests for apps/handlers/prompt/temporal.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — datetime.strftime and datetime.astimezone, the source of every field on the line
# seedgo: no-test-needed(generated) — logger.info on the except path; its text is the exception's own

from datetime import datetime, timedelta, timezone

import pytest

from aipass.hooks.apps.handlers.prompt import temporal
from aipass.hooks.apps.handlers.prompt.temporal import _format_line, _part_of_day, handle

_PDT = timezone(timedelta(hours=-7), "PDT")
_UTC = timezone(timedelta(hours=0), "UTC")


class TestPartOfDay:
    def test_morning_lower_bound(self):
        assert _part_of_day(5) == "morning"

    def test_morning_upper_bound(self):
        assert _part_of_day(11) == "morning"

    def test_afternoon_lower_bound(self):
        assert _part_of_day(12) == "afternoon"

    def test_afternoon_upper_bound(self):
        assert _part_of_day(16) == "afternoon"

    def test_evening_lower_bound(self):
        assert _part_of_day(17) == "evening"

    def test_evening_upper_bound(self):
        assert _part_of_day(21) == "evening"

    def test_night_wraps_midnight_upper(self):
        assert _part_of_day(22) == "night"

    def test_night_wraps_midnight_lower(self):
        assert _part_of_day(0) == "night"

    def test_night_upper_bound(self):
        assert _part_of_day(4) == "night"

    @pytest.mark.parametrize("hour", range(24))
    def test_every_hour_has_exactly_one_bucket(self, hour):
        assert _part_of_day(hour) in {"morning", "afternoon", "evening", "night"}


class TestFormatLine:
    def test_shape_with_tz(self):
        line = _format_line(datetime(2026, 7, 21, 9, 42, tzinfo=_PDT))
        assert line == "Temporal: Tue 2026-07-21 09:42 PDT (morning)"

    def test_afternoon_example_different_tz(self):
        line = _format_line(datetime(2026, 7, 21, 14, 5, tzinfo=_UTC))
        assert line == "Temporal: Tue 2026-07-21 14:05 UTC (afternoon)"

    def test_night_example_after_midnight(self):
        line = _format_line(datetime(2026, 7, 22, 0, 30, tzinfo=_PDT))
        assert line == "Temporal: Wed 2026-07-22 00:30 PDT (night)"

    def test_naive_datetime_omits_tz(self):
        line = _format_line(datetime(2026, 7, 21, 9, 42))
        assert line == "Temporal: Tue 2026-07-21 09:42 (morning)"

    def test_is_a_single_line(self):
        line = _format_line(datetime(2026, 7, 21, 9, 42, tzinfo=_PDT))
        assert "\n" not in line


class TestHandle:
    def test_injects_temporal_line_every_call(self):
        result = handle({})
        assert result["exit_code"] == 0
        assert result["stdout"].startswith("Temporal: ")
        assert result["sound"] == "temporal"

    def test_uses_host_local_tz_not_a_hardcoded_one(self):
        # A clone in another zone must see its own local time, never a hardcoded one.
        expected_tz = datetime.now().astimezone().strftime("%Z")
        result = handle({})
        # Asserted, not guarded: an empty zone would compare nothing and pass silently.
        assert expected_tz != ""
        assert expected_tz in result["stdout"]

    def test_no_cadence_gating_fires_on_repeated_calls(self):
        first = handle({"session_id": "s1"})
        second = handle({"session_id": "s1"})
        assert first["stdout"] != ""
        assert second["stdout"] != ""

    def test_never_raises_on_unexpected_error(self, monkeypatch):
        def _boom(*_args, **_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(temporal, "_format_line", _boom)
        result = temporal.handle({"session_id": "s-err"})
        assert result == {"stdout": "", "exit_code": 0}

    def test_a_smoke_nonce_in_the_prompt_comes_back_as_an_ack_the_prompt_does_not_carry(self):
        prompt = "Reply ok. aipass-smoke:0123456789abcdef"
        line = handle({"prompt": prompt})["stdout"]
        assert line.startswith("Temporal: ")
        assert line.endswith(" · smoke-ack:0123456789abcdef")
        assert "smoke-ack:" not in prompt

    def test_a_prompt_without_the_nonce_or_with_a_short_one_gets_no_ack(self):
        assert "smoke-ack" not in handle({"prompt": "aipass-smoke:abc"})["stdout"]
        assert "smoke-ack" not in handle({"prompt": "hello"})["stdout"]
        assert "smoke-ack" not in handle({"prompt": None})["stdout"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
