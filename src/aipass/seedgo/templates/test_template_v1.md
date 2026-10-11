# Test template v1

**Version 1.3.0** (1.2.0 → 1.3.0 on 2026-09-27: item 5's banner word is `AIPass`, the owner's ruling; 1.1.0 → 1.2.0 on 2026-09-25: rule 1, rule 3, red-first for its own reason, from the backup study, added to items 11 to 13; 1.0.0 → 1.1.0 on 2026-09-24: conftest C0, the log redirect above the imports, stated as item 8's one exception) · gold source: `src/aipass/seedgo/templates/` · model file: `readme_update_model.py.txt` · plan of record: DPLAN-0354.

Housed and distributed by @seedgo (owner 22:50: *"Seedgo will house the test template. It will distribute it fleetwide right, kinda like how memory houses and manages your trinity memory files."*). The machine-readable version lives in `templates.json` beside this page; a branch's receipt is `tests/.template_version.json`, written by `drone @seedgo tests template bump --confirm`.

Authored by @devpulse, 2026-09-20 22:35, amended 23:15. Every line below is either the owner's ruling (marked OWNER, with the time) or what the readme_update trial proved. **Items 1 to 23 are reproduced unchanged**, except the two sentences 1.2.0 added to each of items 11 to 13 and 1.3.0's banner sentence in item 5; the `conftest.py` section is seedgo's, added when the page was housed.

## Grain

1. **One test file per module.** `tests/test_<module>.py`. The module's handlers are exercised through it, the way a user reaches them. OWNER 20:51 "per module", 22:11 "we already agreed module not handlers".
2. **No product file is owed a test file.** Every test file names its subject. No subject demands a test. A handler with nothing reachable through its module and nothing worth pinning has no test, and that is correct.
3. **Seedgo is the one exception, handled in seedgo.** Its checkers are the unit a reader debugs, so seedgo tests per checker. That is seedgo's own layout, not a second kind of branch, and the fleet template says nothing about it. OWNER 22:11 "Seedgo is unique, its not a template."
4. **AIPass tests only its own files.** Never an external project's code. Projects house their own tests. OWNER 22:11.

## File shape, top to bottom

5. **The META header block first**, the same block product files carry. The banner word is `AIPass`, for test files as for product files (OWNER 2026-09-27); `file_top` applies `meta_check`'s banner rule, which still accepts the legacy `META` line. OWNER 22:06 "header on top".
6. **Then the module docstring: one line naming the subject as a path.** `"""Tests for apps/modules/readme_update.py and the handlers it drives."""`
7. **Then the declared pass**: what is NOT tested here and which seedgo standard, or `constant` / `stdlib` / `generated`, covers it. One marker per line, the gold standard's form. In the trial this slot is where six tests got dropped: writing it does the deciding.
8. **Product imports at the top of the file**, never inside a test. This is not tidiness. It removes the option of faking the unit under test. The trial showed it is the single biggest quality change: the old files stubbed `sys.modules` and re-imported per test, and two product mutants passed all 27 of them. Cost: one import per process, measured 0.12 s for the whole readme_update stack, paid once.
9. **One Test class per command or behaviour**, named for it.

## Each test

10. **Through the command.** A test reaches behaviour the way a user does: the module's commands and its public functions. An underscore helper is never called directly by a test. OWNER 22:28 "through the command". If a helper's logic cannot be reached through any command, that is a question about the product, not a reason for a direct test. When the only command route to a state is a filesystem permission (the trial's write-failure test needs a read-only README), the test says so in a comment and carries the platform guard of item 23, rather than weakening the oracle to avoid the route.
11. **The name states the behaviour and the failure it excludes.** `test_a_dry_run_reports_the_change_and_writes_nothing`. The name is the claim. A name may be narrower than the behaviour, never wider: every claim the name makes is a claim an assert in the body makes. A rename that adds a claim adds the assert, or does not happen.
12. **Docstring: none, or one line.** Never an essay. A cut keeps the line that defends code: when prose explains why an assert or a guard is there, the cut either removes the code it defended or keeps that one sentence. It never deletes the reason and keeps the code. If the test pins a shipped defect, the one line names it. OWNER 20:04 on 8-line test docstrings: "thats mental and probs only confusing readers with wrong info". 18 of the trial's 28 tests have no docstring and read better for it.
13. **Assert the effect.** What was printed, written, returned, called, or left untouched. Every oracle change is red-first: a product mutant the old assert survives and the new one kills, and the mutant breaks the behaviour the test is named for, not a coarser one. A mutant the new assert survives is a refused change, reported as HELD, never shipped. Never only that a router returned True (rule 1, `router_assert`, landed). A test with no effect to assert is a test that should not exist.
14. **The edge is real, not mocked: `capsys`.** The product's consoles write to `sys.stdout` and `sys.stderr` at print time, so pytest's own `capsys` captures them with no Rich import and no console built by the test. Read both channels, `out, err = capsys.readouterr()`, and assert on the one the module writes to: `out` for the console, `err` for `error()` and `warning()`. That also pins that errors go to stderr, which `drone` piping depends on. Never a MagicMock console: `console.print.called` is the weak oracle the gold standard names. OWNER 23:00 "whatever is easier... these must be cross os". Width is item 20's job. Amended 23:15; was a Rich `Console` on a `StringIO`.
15. **Mock only at the edge**: disk outside `tmp_path`, network, the clock, another branch. Never the unit under test. A recorder that replaces a sibling function to prove routing reached it is allowed; a MagicMock standing in for the thing being tested is not.
16. **Files go through `tmp_path`.** Shared fixtures live in `conftest.py`, never copied per file.
17. **No test depends on the live repo.** Not the real registry, not another branch's tree, not the working directory. Build what the test needs.
18. **No test leaks state into the next.** Every patch through `monkeypatch`, every file under `tmp_path`, nothing left in `sys.modules`. A leaking test makes an unrelated test lie, and alphabetical order hides it.
19. **Under 1,500 code lines** (rule 2, `oversize_test_file`, landed). When a module's file would pass the cap, split by behaviour, and the second file's header says why it exists.

## Cross-OS, from day one

OWNER 23:04 "We need to test and make sure the proposed template is cross os from day one." Each item below was proven on Linux by emulating the difference (page `test_template_cross_os_2026-09-20.md`); a real Windows and macOS run needs a runner, the owner's call.

20. **`conftest.py` pins the console width once**, session scope, on every console the product exports (`display.CONSOLE`, `display.err_console`), through Rich's public setter. Unpinned, Rich wraps at 80 on POSIX and 79 on Windows under pytest's capture, at the terminal's width under `-s`, at `COLUMNS` when exported. Measured: 4 of the trial's 31 tests flip at width 40, none with the pin. The same conftest calls `display.reset_command_state()` after every test, so `error()`'s process flag never leaks (item 18).
21. **Every file read or write in a test names `encoding="utf-8"`.** Windows' default for `open()` is not UTF-8 on Python 3.12, and the product's output is not ASCII (tree glyphs, the warning prefix). Proven under an ASCII locale, stricter than Windows' cp1252: 31 green.
22. **Paths are built from `tmp_path`, never written as a literal `/...`.** `Path("/nonexistent/path")` happens to work on Windows; it is still the habit that breaks the next test.
23. **Anything the OS does differently carries its guard in the test, with the reason stated.** A permission-bit test skips on Windows and root. No `fcntl`, `os.fork`, signals, symlinks, bare `os.geteuid`; no two names that differ only by case; text compared through `read_text`, never bytes, so CRLF on Windows round-trips.

## conftest.py

Four fixtures belong in a branch's `tests/conftest.py`, never copied per file (item 16). The first two are items 20 and 18 made real; the last two survived the judgement of the archived April conftest template (`.archive/POINTER.md` records what did not, and why).

**C0. The one stated exception to item 8: the log redirect comes before the first aipass import.** Added in 1.1.0 (2026-09-24, owner ruling 23:18). Item 8 puts product imports at the top of the file. In `conftest.py` exactly one thing goes above them: setting `AIPASS_TEST_LOG_DIR`. The fleet json service writes into the live `<branch>_json` folders unless that variable is already set when the aipass stack is imported, so it has to exist before the first `from aipass...` line runs, and the repo-root `conftest.py` raises rather than let a run reach the service without it. 18 of 18 branch conftests already do this. The shape a new branch copies:

```python
import os
import tempfile

if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

from aipass.prax import logger
```

The stdlib imports the block needs, then the environ block, then every aipass import. **No `# noqa` markers.** `E402` is ignored repo-wide in `pyproject.toml`, so a `# noqa: E402` there suppresses a rule that never fires, and since 1.1.0 ruff's `RUF100` convicts it at edit time, in `checklist` and in CI. This is the only exception, and it lives only in `conftest.py`. A test file that needs an import below code has a different problem, and item 8 is the answer to it.

**C1. `pinned_console_width`** — session scope, autouse. Item 20.

```python
@pytest.fixture(autouse=True, scope="session")
def pinned_console_width() -> None:
    """Rich sizes an unpinned console on every print: 80 on POSIX and 79 on Windows
    under pytest's capture, the terminal's width under -s, COLUMNS when exported."""
    for console in (display.CONSOLE, display.err_console):
        console.width = 200
```

**C2. `clean_command_state`** — autouse. Item 18.

```python
@pytest.fixture(autouse=True)
def clean_command_state() -> Generator[None, None, None]:
    """error() marks the process failed; a test must not hand that to the next."""
    yield
    display.reset_command_state()
```

**C3. `temp_test_dir`** — a real `tmp_path` directory with cleanup. Kept because it is the one sandbox fixture the whole fleet shares by name: `apps/handlers/pytest_quality_standards/fresh_clone_check.py` carries it as a named exception precisely because it resolves to `tmp_path`.

**C4. `host_state_snapshot`** — snapshot and restore around a test that must touch real host state. Kept because it carries the owner's 2026-09-08 narrowing: entering the host is allowed, *not restoring it* is not.

A branch whose product writes outside `tmp_path` adds its own redirect fixture, autouse, pointing that write into `tmp_path` — a **real** redirect, not a mock. Seedgo's `mock_infrastructure` (`AIPASS_TEST_LOG_DIR` into `tmp_path`) is the worked example.

## What the checkers will be

Every numbered item is a candidate checker, built one at a time, tests-only, in `aipass_standards`, files allowed to fail on arrival. OWNER 20:25: "we will create the standards and checkers. let all files fail decide plan of action later." None is built until the owner says which is next.

## The model file

`readme_update_model.py.txt` beside this page is the shipped article, not a sketch: it is byte-identical to `src/aipass/seedgo/tests/test_readme_update.py`, 31 tests, green on Ubuntu and macOS across Python 3.10 to 3.13 (PR#774). Read it next to this page — every item above has a line in it. The `.txt` suffix is there so pytest can never collect it and so the path-based `applicability` split never reads a test model as production code; the live, linted copy is the `tests/` one.
