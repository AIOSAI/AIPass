# dev.local.md - SEEDGO
```
Branch: /home/coder/workspace/AIPass/src/aipass/seedgo
Created: 2026-03-07
```

## Issues

-

---

## Todos

### PLAN: Diagnostics Architecture Refactor
**Status:** completed

1. Move `aipass_standards/diagnostics_check.py` → `handlers/diagnostics/diagnostics_check.py` (shared orchestrator)
2. Move `aipass_standards/diagnostics_content.py` + `diagnostics.md` → `aipass_standards/.sorting_unprocessed/.archive/` (not a standard triplet)
3. Create `aipass_standards/diagnostics.json` — `{"python": true}` (per-pack config)
4. Update `diagnostics_check.py` to read pack's `diagnostics.json`, call enabled runners from `handlers/diagnostics/`
5. Update `branch_audit.py` — discover diagnostics from `handlers/diagnostics/` not from pack's `*_check.py`
6. Verify: `drone @seedgo audit aipass seedgo`

### Type_Check → Diagnostics Merge
**Status:** completed

- Removed separate `scores["type_check"]` from branch_audit.py
- Fixed undefined `diag` variable → now reads from `results["diagnostics"]`
- Verified: audit shows 23 standards, no Type_Check line, Diagnostics 100%

### Remaining for 100%
- Missing `docs/` directory (Architecture -7%)
- Missing `dropbox/` directory (Architecture)
- Readme score 83% (Readme standard)
