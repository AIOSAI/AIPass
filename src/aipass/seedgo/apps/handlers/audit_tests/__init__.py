# =================== AIPass ====================
# Name: __init__.py
# Description: audit-tests lane - language-neutral core
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
The `audit-tests` lane — language-neutral core.

Execution-based test-quality measurement, separate from the file-walk audit
engine by design (see docs.local/AUDIT_TESTS_LANE_DESIGN.md rev 4, the build
contract).

Nothing in this package defines `check_module` or `check_branch`, which is
what keeps it invisible to `discover_checkers()` — the shape gate of §2.1.
Adapters expose `run_group`; the core applies the laws.
"""
