# Discarded Patch Standards
**Status:** v1
**Date:** 2026-09-22

---

## What It Is

Crack class **R** from the 2026-09-22 eyes-on review of @backup's tests. A test replaces a
function **in its own branch** with a mock, hands the mock nothing, binds it to nothing, and
asserts nothing about it.

The replacement is pure silence. The product's call to that function is then unpinned, and
the call can be deleted with the suite green.

---

## The shape, in one file

`test_ceiling_guard.py` wraps every `check_ceiling` call in the same line:

```python
with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
    breach = check_ceiling(files, {"max_backup_files": 5})
    assert breach is not None
```

The reviewer's finding on that file: **delete `_log_breach` (ceiling.py:168-179) entirely
and all 21 tests pass.** The refusal's ops-log entry is the only forensic trace of a runaway
refusal, and nothing in the suite pins it.

The cure is one line, and the same file already writes it — at 278:

```python
with ExitStack() as stack:
    snap = stack.enter_context(patch.object(all_module, "run_snapshot"))
    ...
snap.assert_not_called()          # <- named, asked, acquitted
```

---

## The four acquittals, each a measured cut

**Another branch, a gateway, the clock, the network.** That is an edge, and sealing an edge
is what a test is supposed to do. Only a target inside the test file's **own** branch is
judged — the branch is read from the file's path, the target from an `aipass.<branch>.`
string or a name imported from that package.

**A replacement handed over.** `patch(target, tmp_path)` redirects a path constant at a
test-owned directory. `return_value=`, `side_effect=`, `new=`, `new_callable=`, `wraps=`,
`spec=` and `autospec=` all drive or shape what the product gets. That is a seam doing work,
not a mock thrown away.

```python
patch("aipass.flow.apps.handlers.paths.FLOW_JSON_DIR", tmp_path)   # legal
```

The second **positional** argument is the replacement, exactly as `new=` is — `patch` takes
it at index 1, `patch.object` at index 2. Reading only the keyword cost 333 hits.

**An `as` binding that is referenced**, and a `@patch` parameter that is referenced. Asking
the mock anything is the whole cure — and **the question is very often asked after the
`with` block closes**, as at 278 above.

**A patch in a fixture or a helper.** The branch conftest's seam is the sanctioned place to
silence infrastructure; a patch in a test body that duplicates it is the defect. Only
`def test_*` bodies are judged.

---

## The third spelling: `monkeypatch.setattr`

The dispatch named it, and it needed its own rule. `monkeypatch.setattr` has **no bare-mock
form** — the replacement is a required argument — so the handed-over acquittal above lets
every one of the fleet's **1,838** own-branch calls through untouched.

**222 of them hand over something anonymous:**

```python
monkeypatch.setattr(ops, "_write_index", lambda *a, **k: None)   # convicted
monkeypatch.setattr(ops, "_write_index", Mock())                 # convicted
monkeypatch.setattr(ops, "_write_index", recorder)               # acquitted — named
monkeypatch.setattr(ops, "_write_index", lambda *a: ran.append(a))  # acquitted — records
```

Nothing binds the first two, they record nothing, and the silenced call is exactly as
unpinned as a discarded `patch`.

A **named** replacement is acquitted even when nothing asks it: the name is read at the
`setattr` call itself, so no name set can tell an asked mock from an ignored one. A
**recorder** lambda is acquitted by its body — which is precisely why `test_share.py` stays
clean.

---

## Five cuts, 6,401 → 309

| cut | files | hits |
|---|---|---|
| any patch with an unused binding | 250 | 6,401 |
| own-branch targets only | 203 | 3,547 |
| nothing handed over (keywords) | 111 | 1,025 |
| ...second positional counts too | 97 | 692 |
| test bodies only, plus `@patch` | 110 | 786 |
| **assertions after the `with` block** | **47** | **309** |
| plus anonymous `monkeypatch.setattr` | **73** | **529** |

The last row is the correction that matters. Searching only the `with` node's own body
convicted **51 files and 331 hits that are perfectly sound** — more than the surviving count.
The read-name set has to be the whole test's, not the block's.

---

## Fleet standing on arrival

Measured 2026-09-22 over 561 test files.

| | value |
|---|---|
| convicted | **73 (13%)** |
| hits | **529** |
| runtime | **6.4s** |

| spelling | files | hits |
|---|---|---|
| `patch` / `patch.object` | 47 | 309 |
| `monkeypatch.setattr` | 26 | 220 |

| branch | files |
|---|---|
| seedgo | 12 |
| commons | 10 |
| api | 7 |

**My own branch is worst, and it stays worst until it is cured.** Worst single file:
@ai_mail's `test_dispatch_monitor.py` at 65, then @seedgo's `test_coverage_audit.py` at 56
and @flow's `test_close_ops.py` at 36.

---

## Why it cannot be satisfied by accident

If you never name the mock and never ask it anything, the only effect your patch has on the
test's verdict is to make one of the product's calls unobservable. **There is no threshold
and nothing to tune.**

---

## What it declines, and why

| evidence line | verdict | reason |
|---|---|---|
| `test_ceiling_guard.py` ×14 | **convicted** | the reviewer's own finding 5 |
| `test_ceiling_guard.py:278` | acquitted | two patchers, `assert_not_called` on both |
| `test_handlers_filesystem.py` 71, 89 | **convicted** | the `log_operation` halves |
| `test_handlers_filesystem.py` 68, 83 | **declined** | see below |
| `test_share.py` 100, 112, 122 | **declined** | see below |

**68 and 83** patch `whitelist.config.load_project_config`, and the reviewer is right that
a defect is there — but it is not this one. Their verdict is OUT-OF-PLACE because
`filter_paths` **never reaches** the patched function. A dead patch, not a discarded one,
and telling them apart needs the product's call graph; one file's AST cannot see it. Both
also carry `return_value=`, so the mock is answering rather than silent.

**100, 112 and 122** are `monkeypatch.setattr(share_module, "run_share", lambda ...:
ran.append(...))` followed by `assert ran == []`. The reviewer marked them **SOUND** —
"recorder proves run_share unreached". A recorder that is asserted is the cure.

---

## Known limits

**A dead patch is invisible**, as above — that is the 68/83 hole, and it is a call-graph
question by nature.

**`patch.dict`, `patch.multiple` and `mock.patch` spelled through an alias** are not read.
Only `patch` and `patch.object` carry a single readable target.

**`monkeypatch` must be spelled `monkeypatch`.** The rule reads the fixture name pytest
injects; `self.monkeypatch` or a renamed fixture is not judged.

**A named `monkeypatch` replacement is never convicted**, per the acquittal above. That is
a deliberate hole with a stated reason, not an oversight.

**A target built at runtime** — an f-string, a variable — is not resolved, so it is not
judged. The rule only convicts what it can name.

**A file outside any branch scores 100.** It has no own code to discard a patch of.

**A file Python cannot parse yields no findings.** `ruff` already convicts the syntax error.

---

## Provenance

Crack class R of the owner's 2026-09-22 ruling on the eyes-on review of @backup's tests,
built on @devpulse's dispatch eb5602d0 (DPLAN-0354). The brief is
`dropbox/test_review_cracks_brief_2026-09-22.md`; the nine reviewer reports are in
`dropbox/test_review_reports_2026-09-22/`. The model file `tests/test_readme_update.py`
passes clean.
