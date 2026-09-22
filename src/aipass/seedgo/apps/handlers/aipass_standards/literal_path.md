# Literal Absolute Path Standards
**Status:** v1
**Date:** 2026-09-22

---

## What It Is

Test template v1, **item 22**: paths in a test are built from `tmp_path`, never written as a literal `/...`.

```python
result = classify(Path("/fake/repo/apps/entry.py"))   # convicted
adopt.run("/fake/aipass/home")                        # convicted
```

The path is a fact about one host, written into a file that has to run on three.

---

## Why this is not `hardcoded_path`

`hardcoded_path` hunts one species — a **home directory**, `/home/<user>/`, `/Users/<user>/`, `C:\Users\<user>` — by regex over every line of every file in the fleet. Item 22's own example, `Path("/nonexistent/path")`, has no home in it, and `hardcoded_path` cannot see it.

Measured 2026-09-22 over the fleet's test files:

| | count |
|---|---|
| literal absolute paths in test files | 2,491 |
| of those, home-rooted (`hardcoded_path` reaches them) | 164 |
| **the rest, with no checker until this one** | **2,327** |

The two standards split cleanly: `hardcoded_path` keeps the production half and the home species everywhere; `literal_path` takes the test half of every other absolute path. A line is never charged by both.

---

## The restriction to an argument IS the rule

`host_portability` ARM A settled this shape for `/proc`, and the same split does the work here. A literal that merely **sits** somewhere is data; only a literal **handed to a call** is a path the test uses. That one restriction takes 2,327 nominations down to 874.

The positions it throws out are the ones that would have made the rule a nuisance:

```python
table = {"/srv/data/x.json": 1}          # a mock TABLE, keyed by path
assert result == "/fake/repo"            # the ORACLE, not an input
mock.which.return_value = "/usr/bin/tmux"  # what a STUB returns
```

A **name bound only to such a literal** is the same habit, and is judged where the name is **used** — aipass `test_adopt.py` binds `fake_home` once and hands it to three calls. A name assigned anything else anywhere in the file is dropped: which value reaches the call is a question one pass cannot answer.

---

## What the checker scans for

| Shape | Convicted |
|---|---|
| `Path("/nonexistent/path")` — the template's own example | yes |
| `register_contact("/some/inbox.json")` — any product call | yes |
| `audit(file_path="/fake/apps/entry.py")` — a keyword argument | yes |
| `p = "/fake/one"` then `run(p)` — bound, then used | yes |
| `{"/srv/data/x.json": 1}`, `assert r == "/fake/repo"` | **no** — data, not use |
| `Path("/home/user/x.py")` | **no** — `hardcoded_path` owns it |
| `mock.return_value = "/usr/bin/tmux"`, `parametrize(...)` | **no** — a stub's data |
| `client.get("/v1/whoami")` | **no** — a route, not a file |
| `read_file("/etc/passwd")`, `setenv("SHELL", "/bin/bash")` | **no** — a real host file |
| `PureWindowsPath("/x/a.py")` | **no** — string algebra, no filesystem |
| `value.startswith("/proc")` | **no** — a comparison operand |
| `r"C:\proj\AIPass"` | **no** — counted, see below |
| `Path("/")`, `walk("//")` | **no** — a root separator carries no host |

Every carve-out carries its measured count (over 578 fleet test files):

| acquitted | count |
|---|---|
| mock data | 200 |
| URL path | 188 |
| home-rooted (`hardcoded_path`) | 78 |
| system root | 60 |
| pure path class | 26 |
| drive-rooted (counted) | 29 |
| string operation | 10 |

---

## A drive-rooted literal is counted, never convicted

```python
assert _spell(_WindowsFlavour(r"C:\proj\AIPass")) == "../wren"
```

On a POSIX host `tmp_path` cannot produce `C:\proj\AIPass`. A rule that convicted memory's `test_roots_lifecycle` would be demanding a cross-OS test lie about its own subject. All 15 sites in 8 files are that shape. They are counted and the count rides in the file's **passing** message:

```
Every path in use is built, not written (1 drive-rooted path is counted, which the rule allows)
```

Same device `named_encoding` uses for latin-1: visible in the numbers, never a verdict.

---

## How to fix a violation

Build it from `tmp_path`. The fixture is already in every test's signature, and a path built from it exists, is writable, and is cleaned up.

```python
# before
result = classify(Path("/fake/repo/apps/entry.py"))

# after
entry = tmp_path / "apps" / "entry.py"
result = classify(entry)
```

---

## Scope, and how it scores

`APPLIES_TO = "tests"`, `AUDIT_SCOPE = "all_files"`. It declares `tests` rather than `everywhere` because its cure is `tmp_path`, a fixture that exists only in a test: production code builds its paths from config, and a rule telling it to use a pytest fixture would be nonsense.

Measured 2026-09-22 over 578 fleet test files — **874 hits in 117 files**, 281 of them the template's own `Path("/...")`:

| branch | hits | files | branch | hits | files |
|---|---|---|---|---|---|
| seedgo | 324 | 24 | memory | 23 | 8 |
| ai_mail | 125 | 14 | flow | 17 | 6 |
| prax | 88 | 10 | daemon | 16 | 3 |
| hooks | 74 | 16 | drone | 15 | 4 |
| trigger | 72 | 9 | devpulse | 7 | 3 |
| aipass | 70 | 8 | skills | 5 | 2 |
| api | 32 | 7 | spawn | 3 | 1 |
| | | | backup | 2 | 1 |
| | | | cli | 1 | 1 |

canary and commons carry none.

Two branches were audited for real on the day it landed:

| branch | overall before | overall after | `literal_path` |
|---|---|---|---|
| memory | 96% | 96% | 81% |
| aipass | 96% | 95% | 72% |

---

## Known limits

**A literal containing whitespace is not a path.** hooks `test_hook_test.py` binds a two-sentence refusal message that opens with `/proj/...`; without this guard the rule convicts the prose. One site fleet-wide.

**A literal that is never handed to a call is not convicted** — a default argument, a bare return, an element of a list that is not itself an argument. It is data until something uses it, and ARM A's measurement is why that line sits where it does.

**The system-root list is curated, not inferred.** `/bin`, `/sbin`, `/usr`, `/etc`, `/proc`, `/sys`, `/dev`, `/var/run`, `/opt`, `/Library`, `/System`, `/Applications`. `/tmp` is deliberately absent: a test that hands `/tmp/proj` to the product is doing exactly what `tmp_path` is for.

---

## Provenance

`templates/test_template_v1.md` item 22, built 2026-09-22 on @devpulse's dispatch cfcb4191 (DPLAN-0354). Sixth checker in the per-item series, after `router_assert`, `oversize_test_file`, `import_site`, `through_the_command` and `named_encoding`. The check-first question the dispatch asked — *is this `hardcoded_path` plus todo 143?* — was answered by reading `hardcoded_path`'s five regexes and counting: it reaches 164 of 2,491, so a real gap remained.
