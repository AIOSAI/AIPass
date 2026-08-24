# =================== META ====================
# Name: scaffold(disabled).py
# Description: Parked spawn/seedgo template scaffold smoke test
# Version: 1.1.0
# Created: 2026-07-04
# Modified: 2026-08-18
# =============================================

"""Scaffold smoke test — proves pytest infrastructure works in this branch.

PARKED, not archived (DPLAN-0304 item 4 / tests/parked/README.md). Kept
verbatim for revival if this branch ever loses its own conftest; see the
park README for the ruling. Filename drops the `test_` prefix on purpose —
that is what keeps pytest from collecting it, not the `(disabled)` suffix
alone (see `tests/test_parked_is_not_collected.py`).
"""

import pytest


def test_conftest_fixtures_available(request):
    """Verify template conftest fixtures are wired and return expected types.

    Established branches replace the template conftest with their own suite
    fixtures (spawn update never overwrites .py files) — there this smoke test
    has nothing left to prove, so it skips instead of erroring.
    """
    try:
        temp_test_dir = request.getfixturevalue("temp_test_dir")
        sample_test_data = request.getfixturevalue("sample_test_data")
    except pytest.FixtureLookupError:
        pytest.skip("branch conftest replaced the template scaffold fixtures — real suite covers this")
    assert temp_test_dir.exists()
    assert isinstance(sample_test_data, dict)
