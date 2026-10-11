# Templates

The fleet's **test template**, housed here and distributed from here (owner 2026-09-20 22:50, DPLAN-0354). Seedgo is the gold source; the pattern is @memory's for the trinity files.

| file | what it is |
|---|---|
| `templates.json` | the gold manifest — `template_versions` is what every receipt is checked against |
| `test_template_v1.md` | the page. Items 1 to 23 plus the `conftest.py` section |
| `readme_update_model.py.txt` | the model, a frozen v1.0.0 copy of `tests/test_readme_update.py` |
| `.archive/` | the six April "Universal Test Template" files, and `POINTER.md` saying what replaced each |

**Nothing here is collected by pytest.** Two independent settings already say so — seedgo's `pytest.ini` pins `testpaths = tests`, the repo's `pyproject.toml` carries `norecursedirs = ["templates", ...]` — and the model carries a `.py.txt` suffix on top of that, the form @devpulse used in the dropbox.

The suffix is not only about collection. `applicability` decides production-vs-tests **by path**, so a `.py` here is read as production code and `drone @seedgo checklist` convicts the model for being a test file: architecture (not in the 3-layer structure), documentation (23 test functions with no docstring — v1 item 12 asks for exactly that), encapsulation (a handler imported directly — v1 item 8 asks for exactly that). Three standards convicting the gold model for obeying the gold page. The lintable, auditable, checklist-clean copy is **`tests/test_readme_update.py`** (25/25), which is the same bytes; this one is the frozen snapshot of what v1.0.0 shipped.

## Verbs

```
drone @seedgo tests template-status              # every branch's receipt against gold
drone @seedgo tests template bump                # dry run: who would be stamped
drone @seedgo tests template bump --confirm      # write the receipts and the page
drone @seedgo tests retired                      # what is in the retire lane
drone @seedgo tests restore <name>               # bring one retired file back
```

A branch's receipt is `tests/.template_version.json`. **A test body is never distributed** — the template ships the page, the model and the receipt; a branch's tests stay its own.
