# Subprocess Text True Standards
**Status:** v1
**Date:** 2026-09-25

---

## What It Is

`subprocess.run(..., text=True)` with no `encoding=` decodes the child's stdout and stderr
(and encodes `input=`) with `locale.getpreferredencoding(False)`. That is UTF-8 on the
fleet's Linux and macOS hosts and cp1252 on Windows. A child that prints a box character or an
em dash raises UnicodeDecodeError in the Windows lane. That is a failure of the TEST, not of
the product. It is `named_encoding`'s hazard one pipe over, and `named_encoding` does not
see it: it judges the builtin `open`, `read_text` and `write_text` only.

The specimens are from @backup's `tests/test_dead_cwd_imports.py` at 7b51d118, lines 224, 706, 797 and 852.
Each is a `text=True` line:

```python
proc = subprocess.run(
    [sys.executable, "-c", _PROBE, world, ...],
    capture_output=True,
    text=True,          # :224 no encoding named; the child's report decodes as cp1252 on Windows
    timeout=180,
)
```

---

## The shape

A call to `subprocess.run`, `Popen`, `check_output`, `check_call` or `call` that has:

- `text=True` or `universal_newlines=True` (the literal `True`), and
- no `encoding=` keyword, or `encoding=None`, which is the locale again.

The hit is reported on the `text=` line. `errors=` alone is not a cure, because it names the error
handler and not the codec. Names resolve through the file's own imports, including imports
made inside a function. `import subprocess as sp` and `from subprocess import run` are both followed.

## What is not convicted

| case | why |
|---|---|
| `encoding=` with any other value | the encoding is named; it implies text mode on its own |
| `text=False`, or no flag | bytes, nothing to decode |
| `text=flag`, not a literal | whether it is text mode cannot be read from the statement |
| `**kwargs` | it can carry the encoding |
| `mock_run.assert_called_once_with(..., text=True)` | not a subprocess call |
| the callers of a helper that wraps subprocess | the helper's own call is judged, once |
| the words inside a string | not a call |
| `getoutput` / `getstatusoutput` | always text, no flag to read; zero in the fleet's tests |

---

## Check first

Measured 2026-09-25 over every test file the pack's applicability admits, before the rule landed.
`.archive` and `seedgo/.seedgo/fixtures` were excluded.

| | |
|---|---|
| test files judged | 598 |
| subprocess calls | 127 (run 118, Popen 9) |
| convicted | 115 hits in 52 files, all 18 branches |
| by call | `run` 115; `Popen`, `check_output`, `check_call`, `call` 0 |
| by flag | `text=True` 115; `universal_newlines=True` 0 |
| compliant | 1 call names an encoding (encoding only, no flag); 0 pair it with `text=True` |
| non-literal flag, `**kwargs` | 0, 0 |

| branch | files / hits |
|---|---|
| memory | 3 / 21 |
| aipass | 6 / 15 |
| skills | 3 / 10 |
| api, prax, spawn | 5 / 8, 4 / 8, 2 / 8 |
| drone | 5 / 7 |
| seedgo | 6 / 6 |
| ai_mail, flow, hooks | 2 / 5, 2 / 5, 3 / 5 |
| backup, devpulse | 1 / 4, 2 / 4 |
| cli | 3 / 3 |
| commons, daemon | 1 / 2, 2 / 2 |
| canary, trigger | 1 / 1, 1 / 1 |

A text grep for `text=True` under `tests/` finds 122 hits. The checker does not convict 7 of them.
Five are mock assertions (`assert_called_once_with(..., text=True)`) in @drone's
`test_git_access.py`. Two are in @memory's `tests/parked/.../manager(disabled).py`, which the pack's
applicability excludes. Production code (`apps/`) is outside this rule's scope. For
information only, the same scan convicts 220 calls in 80 files there.

@backup's four specimens are still on disk at lines 212, 608, 698 and 726. The template's model file,
`tests/test_readme_update.py`, scores 100.

## Scoring

Scored per file: 0 on any finding, else 100. Every hit goes on ONE check, as
`<file>:<line> subprocess.run(text=True) without encoding - <why>; <cure>`.

## The cure

Pass `encoding="utf-8"`. Add `errors=` if the child may print bytes that are not UTF-8.

---

[← Back to README](../../../README.md)
