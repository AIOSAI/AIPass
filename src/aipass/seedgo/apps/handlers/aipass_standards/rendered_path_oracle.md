# Rendered Path Oracle Standards
**Status:** v1 (ADVISORY)
**Date:** 2026-10-13

---

## What It Is

A test that asserts a **whole path**, spelled inside an f-string, against output a console
**rendered**. It is green on Linux and red on Windows and macOS. Tests only.

The specimen is @aipass's `tests/test_aipass_main.py`,
`TestMain.test_a_crash_whose_log_cannot_be_written_still_ends_on_the_crash_not_a_traceback`
(PR #787, red on the Windows and macOS legs):

```python
log_home = tmp_path / "system_logs"
denied = PermissionError(13, "Permission denied", str(log_home))
...
_out, err = capsys.readouterr()
assert f"(this crash could not be written to the log: [Errno 13] Permission denied: '{log_home}')" in err
```

---

## Why it matters: two fragilities

**WRAP.** Rich wraps a line at the console width (the fleet conftest pins 200). A Windows tmp
path (`C:\Users\runneradmin\AppData\Local\Temp\pytest-of-runneradmin\pytest-0\popen-gw1\...`)
or macOS's `/private/var/folders/...` pushes the line past it, and the wrapped output no longer
holds the substring.

**REPR.** `str(OSError)` renders the filename with `%r`, so on Windows the backslashes are
doubled, and `'{log_home}'` (single backslashes) never matches, wrap or not. A fixed console
width does not cure this one.

---

## The cure

Assert a stable fragment: the message's words without the path, and the path's `.name`:

```python
assert "Permission denied:" in err
assert "system_logs" in err
```

or compare the path through a channel nothing renders: a returned value, the exception's
`.filename`.

---

## What is convicted

Inside one `def test_*`, one finding per offending `assert`:

| Part | Shapes |
|---|---|
| Needle | An f-string with a FormattedValue that is a path: the `tmp_path` parameter itself; a name bound in the test to `tmp_path`, `tmp_path_factory.mktemp(...)`, or an expression rooted at one (`/`, `.joinpath`, `.resolve()`, `.absolute()`, `.with_name/suffix/stem`, `.expanduser()`); a `Path(...)` / `PurePath(...)` (and Posix/Windows siblings) call or a name bound to one; `str(<path>)`; `<path>.parent` |
| Haystack | `out, err = capsys.readouterr()` (or `capfd`); `captured.out` / `.err` with `captured = capsys.readouterr()`; `capsys.readouterr().out` inline or bound to a name; `result.output` / `.stdout` / `.stderr` with `result` bound to a `CliRunner` `invoke` or a `subprocess.run`; a plain alias of any of these |
| Compare | `in`, `not in`, `==`, `!=` (needle on either side), anywhere inside the `assert` |

## What is acquitted

- `{path.name}`, `{path.stem}`, `{path.suffix}`: not a path, it is the cure.
- An f-string with no path in it.
- A path f-string compared against something nothing rendered: `str(exc)`, a returned value,
  a dict the product built.

## HELD (not judged)

Each needs a data flow the AST cannot settle in one function; guessing would convict cures.

- An f-string bound to a name first (`msg = f"..."` then `assert msg in err`).
- A haystack transformed before the compare (`said = " ".join(err.split())`, the specimen's
  own wrap cure, which is still REPR-fragile).
- `subprocess.check_output`'s return value; `tmpdir` (py.path); a path that reached the test
  through a helper or a fixture other than `tmp_path`.

---

## Fleet standing on arrival

Measured 2026-10-13 over 762 test files (`src/aipass/*/tests/**/*.py`). The specimen was
already cured by @aipass (it now collapses whitespace and stops before the path). **9 asserts
convict: @backup 8, @devpulse 1.** Because anything beyond the specimen convicts, the standard
lands **`ADVISORY = True`**: `branch_audit` keeps it out of the gating average, so no branch's
number moves. Advisory, then ratchet: gate it once the nine are cured.

---

## Bypass position

Standard bypass via `.seedgo/bypass.json` (`"standard": "rendered_path_oracle"`). A test that
genuinely must compare a full rendered path (a Linux-only test under a platform guard) is the
case for it; say why in the rule's reason.

---

## Known limits

**Only `def test_*` functions are read.** A helper that asserts on behalf of a test is not.

**A file Python cannot parse yields no findings.** `ruff` already convicts the syntax error.
