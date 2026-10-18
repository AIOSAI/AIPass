# =================== AIPass ====================
# Name: __init__.py
# Description: seedgo CLI modules package - the refusal an entry point can act on
# Version: 1.0.0
# Created: 2026-09-07
# Modified: 2026-10-17
# =============================================

"""The seedgo CLI module layer.

`seedgo.py` turns every truthy `handle_command` answer into exit 0, so a refusal travels as a raised
value: an unknown command or argument fails, and a `bool | int` return would make every caller decide what 0 means.
"""


class CommandRefused(Exception):
    """A command was claimed, printed its refusal, and must not exit 0.

    `code` carries the exit-code vocabulary of `handlers/audit_tests/refusal.py`, so one command never
    means two things across the two lanes.
    """

    def __init__(self, code: int, token: str = ""):
        self.code = code
        self.token = token
        super().__init__(f"refused with exit code {code}" + (f": {token}" if token else ""))
