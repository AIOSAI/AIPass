# Tests

Pytest unit tests for `DAEMON`.

- `conftest.py` — Shared fixtures (temp dirs, mocks, sample data).
- `test_*.py` — Test files. Standard tests cover JSON handler, CLI routing, and error resilience. Custom tests cover branch-specific domain logic.
