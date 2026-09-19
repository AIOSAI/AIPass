[← Back to the cli README](../README.md)

# Testing display output

Never assert on raw captured bytes. Build the console with
`make_capture_console()` from `tests/conftest.py` and assert through its
`get_output()`, which strips ANSI. Rich decides whether to emit escapes by
probing the environment, so a raw-bytes assert makes the suite a function of the
shell — `FORCE_COLOR=3` renders `created: 5` as `created: \x1b[1m5\x1b[0m` and a
plain substring check fails on output a human reads as correct. Assert what is
VISIBLE.

That helper is the one capture seam for this branch: a suite that builds its own
console re-acquires the environment dependency the helper exists to remove.

Two failure shapes this rule prevents, both found here by mutation runs rather
than by reading:

- A test named for a behaviour it never exercises holds the slot the real one
  wants. Check the test name against the call it actually makes.
- `try: f() / except X as e: assert ... in str(e)` passes vacuously when nothing
  raises. Use `pytest.raises`.

Under pytest, json writes are redirected by the `AIPASS_TEST_LOG_DIR` seam that
`conftest.mock_infrastructure` sets — see [the json handler](json_handler.md).

---
[← Back to the cli README](../README.md)
