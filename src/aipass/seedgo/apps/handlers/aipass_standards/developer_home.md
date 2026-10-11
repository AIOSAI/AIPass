# Developer Home Standard
**Status:** v1
**Date:** 2026-10-04

---

## What This Standard Is

AIPass is a public repo. No tracked text file may contain a developer's home directory —
`/home/<login>`, `/Users/<login>` or `<drive>:\Users\<login>` — where `<login>` could be a
real person's login. A home directory names a person the same way a name does. The owner's
ruling, 2026-10-04.

---

## Why It Matters

- **It names a person.** A login in a home path is a username anyone can read, search and
  tie back to its owner.
- **It tells a reader who their user is, wrongly.** A seat that reads somebody else's home
  in a prompt or a doc on another machine is told whose machine it is on.
- **It is not `hardcoded_path`.** That standard is about the portability of code, so it skips
  comments and docstrings. This one is about naming a person, and prose names a person
  exactly as code does: nothing is skipped.

---

## What the Checker Scans For

Every line of a text file: suffix `.py .md .json .toml .yml .yaml .sh .txt`, or no suffix at
all (extensionless scripts, dotfiles). Any other kind is declined unread, and so is a file
holding a NUL byte (binary). Text is decoded as UTF-8 with undecodable bytes replaced.

| Spelling | Shape |
|---|---|
| POSIX | `/home/<login>`, trailing slash or not |
| macOS | `/Users/<login>` |
| Windows | a drive letter, `:`, then one backslash, two (as source and JSON carry them) or a slash, `Users` in any case, a separator, `<login>` |

The POSIX and macOS spellings need a non-word, non-dot character before the slash, so a home
inside a URL (`example.com` followed by a home path) is not a home.

### What Passes

- **A segment that names nobody** — `NEUTRAL_SEGMENTS`, compared lower-cased after trailing
  `. , ! ? …` are stripped: generic logins (`user`, `username`, `someone`, `somebody`), the
  example cast (`carol`, `alice`, `bob`, `dave`, `eve`), fill-ins (`you`, `yourname`, `me`,
  `name`), sample words (`example`, `test`, `tester`), the project (`aipass`), `x`, `...`, and
  GitHub's runner accounts (`runner`, `runneradmin`, `runner~1`).
- **Any single-character segment** — an initial names nobody findable.
- **Any segment containing `<`, `{`, `$`, `%` or `*`** — a template slot: `<user>`, `{name}`,
  `$USER`, `%USERNAME%`.
- A pytest temp path (`/tmp/pytest-of-...`) is not a home path at all.

---

## Code Examples

### Violation

The same path as below with a real login where `<user>` stands, in code, a comment, a
docstring, a markdown page or a JSON value.

### Fix

```python
ROOT = Path.home() / "Projects" / "AIPass"     # built at run time
EXAMPLE = "/home/<user>/Projects/AIPass"        # a placeholder in prose
```

---

## Scoring

- **Check:** one per file — "Developer home"
- **Pass:** no hit after line bypasses; **Fail:** any hit, message
  `N developer home path(s): L12: <matched>; ...` (up to three shown)
- **Score:** 100 or 0
- **Missing or unreadable file:** fails, with the reason

---

## Where It Runs

- **Checklist** (`drone @seedgo checklist <file>`): `TEXT_FILES = True` lets the per-file lane
  judge a non-`.py` text file with this checker — only with checkers that declare it.
- **Audit** (`drone @seedgo audit aipass`): `AUDIT_SCOPE = all_files`, `APPLIES_TO = everywhere`,
  over the audit's own `.py` corpus.
- **The tracked tree** (`drone @seedgo home-paths scan`): every file `git ls-files` lists, each
  branch's bypass rules applied to its own files. A tree git cannot list is red, never clean.
  CI runs it from the repo root as `python -m aipass.seedgo.apps.seedgo home-paths scan`: exit
  0 clean, 1 a hit, 2 could not measure, 7 an unknown argument.

---

## Bypass

A line rule in the owning branch's `.seedgo/bypass.json`, with the reason — only for a file
whose home paths ARE the input under test (this standard's own tests), never for a real home:

```json
{
    "standard": "developer_home",
    "file": "tests/test_checkers_batch10.py",
    "lines": [1601],
    "reason": "the checker's own inputs; the login names nobody"
}
```

A file-wide rule (no `lines`) acquits the whole file.

---

## Reference

- Checker: `developer_home_check.py`
- CLI verb: `apps/modules/home_paths.py`
- Prior art: `apps/handlers/context_standards/name_ratchet.py` (the `home_path` rule)
