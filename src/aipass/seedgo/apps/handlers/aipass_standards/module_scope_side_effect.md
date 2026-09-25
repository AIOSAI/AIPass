# Module Scope Side Effect Standards
**Status:** v1
**Date:** 2026-09-25

---

## What It Is

Module-level code in a `test_*.py` file runs at COLLECTION: once, before any test, in
whatever order pytest happens to import files. A side effect there leaks into every test in
the session, and a failure there takes the whole file — sometimes the whole session — down
before one test has run.

The specimens, @backup's `tests/test_cli_routing.py` at 7cbe39e5:

```python
_SECRETS_ROOT = str(Path.home() / ".secrets")   # :443 host read at import; a RuntimeError takes all 99 tests
_SECRETS_TOUCHED: list[str] | None = None        # :444 a global recorder functions rebind via `global`
sys.addaudithook(_secrets_audit_hook)            # :457 installed for the session, can never be removed
```

`state_leak` is the other half: it judges writes at TEST time and never one at import.

---

## What is module scope

Code that runs when the module is imported:

- top-level statements, including inside top-level `if` / `try` / `with` / `for` blocks —
  but not under `if __name__ == "__main__":` (whose `else` does run);
- class bodies, not method bodies;
- decorator expressions on top-level functions, classes and methods;
- default-argument expressions of any `def` (or `lambda`) reached at import.

Function, method and lambda BODIES are not module scope. Names are resolved through the
file's own imports: `from os import environ` and `from pathlib import Path as P` are followed.

## The eight shapes

| shape | what |
|---|---|
| `audit_hook` | `sys.addaudithook(...)` |
| `host_read` | `Path.home()`, `Path.cwd()`, `os.path.expanduser(...)`, `os.getcwd()`, `Path(...).expanduser()` |
| `environ_write` | `os.environ[k] = v`, `.setdefault/.update/.pop/.popitem/.clear`, `del os.environ[k]`, `os.putenv`, `os.unsetenv` |
| `sys_modules_write` | `sys.modules[k] = v`, `.setdefault/.update/.pop/.popitem/.clear`, `del sys.modules[k]` |
| `sys_path_write` | `sys.path.insert/append/extend/remove/pop/clear`, `sys.path[...] =`, `sys.path = ...` |
| `module_attr_write` | `X.attr = v` or `setattr(X, ...)` where X is bound by an import in this file |
| `cwd_change` | `os.chdir(...)` |
| `global_recorder` | a module-level name any function in the file rebinds through `global` |

Anything else — constants, `pytestmark`, fixture definitions, imports, typing — is not judged.

## What is not judged

`conftest.py` is exempt. Its module scope is the declared, once-per-session harness: test
template v1 conftest C0 even REQUIRES setting `AIPASS_TEST_LOG_DIR` in `os.environ` above
the imports there. In a `test_*.py` the same code is session state smuggled in by
collection order. Other files under `tests/` that pytest does not collect (helpers,
fixture modules) are not judged either.

---

## Check first

Measured 2026-09-25 over the fleet's test files, before the rule landed.

| | |
|---|---|
| `test_*.py` files judged | 557 (18 branches) |
| files convicted | 15 — commons 3, skills 4, api 2, hooks 2, prax 1, backup 1, ai_mail 1, seedgo 1 |
| hits | 32 — commons 15, skills 4, prax 4, backup 3, api 2, hooks 2, ai_mail 1, seedgo 1 |

| shape | hits |
|---|---|
| `sys_modules_write` | 16 |
| `host_read` | 6 |
| `global_recorder` | 5 |
| `sys_path_write` | 4 |
| `audit_hook` | 1 |
| `environ_write`, `module_attr_write`, `cwd_change` | 0 |

**The price of the conftest exemption.** Judged, all 18 of the fleet's 18 `conftest.py` files
would score 0, on 21 hits: 18 are the C0 `AIPASS_TEST_LOG_DIR` line the template requires,
and three are not (@api's and @backup's `sys.modules` handler stubs, @daemon's
`Path.home()`). Those three are real collection-time state the exemption lets through.

`import_site` convicts a module-level `sys.modules[...] = stub` naming an aipass module by
literal. None of this rule's 16 `sys_modules_write` hits is convicted there (they are
`setdefault` calls and variable keys), so no line gets two verdicts today.

@backup's three specimens are still on disk, under live edit. The template's model file,
`tests/test_readme_update.py`, scores 100.

## Scoring

Scored, per file: 0 on any finding, else 100. Every hit on ONE check, as
`<file>:<line> <shape>: <snippet> - <why>`.

## The cure

Move it into a fixture (`monkeypatch` / `tmp_path`) or into the test that needs it.

---

[← Back to README](../../../README.md)
