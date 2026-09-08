# =================== AIPass ====================
# Name: __init__.py
# Description: seedgo CLI modules package - the refusal an entry point can act on
# Version: 1.0.0
# Created: 2026-09-07
# Modified: 2026-09-07
# =============================================

"""The seedgo CLI module layer.

WHY AN EXCEPTION AND NOT A RETURN VALUE. `handle_command` answers one question -
"is this command mine?" - and `seedgo.py` turns every truthy answer into exit 0.
That made a refusal indistinguishable from a success to anything reading the
exit code: `drone @seedgo audit not_a_real_pack` printed
`❌ Unknown pack: 'not_a_real_pack'` and exited 0, and `audit --bogus-flag`
printed `exit code: 7` in its own output while exiting 0 alongside it. Patrick's
standing ruling (fleet sweep 2026-09-07) is that an unknown command or argument
FAILS. Widening the return type to `bool | int` would have had every caller in
the fleet decide what `0` meant - the code that ran fine, or the module that
declined the command - so the refusal travels as a raised value that cannot be
mistaken for either.
"""

# =============================================================================
# REFUSAL
# =============================================================================


class CommandRefused(Exception):
    """A command was claimed, printed its refusal, and must not exit 0.

    `code` is the shell's answer. It carries the vocabulary already published
    by `handlers/audit_tests/refusal.py` so one command never means two things
    across the two lanes.
    """

    def __init__(self, code: int, token: str = ""):
        self.code = code
        self.token = token
        super().__init__(f"refused with exit code {code}" + (f": {token}" if token else ""))
