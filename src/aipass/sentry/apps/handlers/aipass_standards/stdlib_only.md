# Stdlib Only Standard
**Status:** v1
**Date:** 2026-11-17

---

## The Situation It Exists For

Most branch files import their branch's json shim and log their operations (`json_structure`). A few files
cannot: other branches import them before any aipass service runs, so the shim, the logger and the registry
are not there yet. Drone's `apps/handlers/registry_name.py` is one: the registry file name predicate, imported
by other branches at start-up.

The standards fit most files, not all of them. When a branch's need falls outside the structure, the branch
asks for a custom standard rather than a bypass row: a bypass waives a check, a custom standard replaces it
with one that proves what the file promises instead.

---

## How a Branch Asks

Mail @sentry the file and why it must load before aipass services. Sentry adds the file's path under
`src/aipass` to `CLAIMS` in `stdlib_only_check.py`. The list is a claim, not a pass: the check below decides.

---

## What the Check Proves, per Listed File

| Promise | Broken by |
|---|---|
| Standard library only | an import whose top name is not in `sys.stdlib_module_names`; a relative import; an `aipass` import |
| No I/O modules | importing `subprocess`, `shutil`, `socket`, `tempfile`, `glob`, `multiprocessing`, `pty`, `fileinput` |
| No disk | a call to `open`, `input`, any `read_*` / `write_*`, `iterdir`, `listdir`, `scandir`, `walk`, `glob`, `rglob`, `stat`, `lstat`, `exists`, `is_file`, `is_dir`, `touch`, `mkdir`, `makedirs`, `rmdir`, `unlink`, `remove`, `rename`, `chmod`, `symlink_to` |
| No environment | `environ` / `environb` read as an attribute or imported by name; `getenv`, `putenv`, `unsetenv` |
| No processes | `system`, `popen`, `fork`, the `exec*` and `spawn*` families |
| No run-time import | `__import__`, `import_module`, `exec`, `eval`: each could load an aipass module the imports never show |

A name imported from a module (`from os import environ`, `from os import system`) breaks the promise as its
call would. A listed path that does not exist fails, and so does a file Python cannot parse.

The reading is by name, so a pure method that shares a name (`.exists()` on your own class) also breaks it;
rename it.

---

## What a Proven Claim Buys

`json_structure` stands down for a listed file whose claim is proven, and says so in its output. A listed file
that breaks its promise gets no relief, and an unlisted file gets none however clean it is.

---

## Scoring

- **Scope:** `branch_level`, `APPLIES_TO = production`.
- **Score:** 100 when every claim the branch holds is proven, else 0, one message per claim naming each line
  and what breaks.
- **A branch with no claim:** not applicable; the row holds its slot without a score.

---

## Reference

- Checker: `stdlib_only_check.py` (`CLAIMS` is the list)
- Content: `stdlib_only_content.py`
- The relief: `json_structure_check.py`
