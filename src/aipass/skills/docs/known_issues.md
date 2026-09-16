[← Back to the skills README](../README.md)

# Known Issues And Measurements

What this branch could not exercise, what it carries knowingly, and what is closed. Every figure here is dated; re-measure before quoting one.

Everything below was measured on this branch on 2026-09-07. Anything this
branch could not exercise is marked unverified rather than left standing green.

**Working, exercised tonight:** `list`, `info`, `validate`, `switch`, `run`,
`--help`, `--version`. The off-switch's three doors were exercised, not just
read: `drone @skills run telegram` refuses with the OFF message while the units
stay masked. Suite 404 passing and 1114 telegram cases skipped (re-counted 2026-09-14), identical from the
branch root and the repo root. seedgo audit 100 on every CI-scored category.

**Known issue — one bypass carried, not a clean 100.**
`.seedgo/bypass.json` waives `json_structure` for
`apps/handlers/module_paths.py`. That helper is stdlib-only on purpose and must
never import the json seam; seedgo's `_is_prelogging_bootstrap` used to exempt
it automatically, because the exemption is granted to whatever the logging
substrate imports and the *old* json_handler imported it. The canonical shim
imports nothing branch-local, so the chain now stops at the shim and the
exemption lapsed. skills is the only branch in the fleet carrying a
`module_paths.py`, so no other branch is affected. The bypass carries the full
measurement and comes out when seedgo's clause learns a module-scope importer.

**Closed 2026-09-06 — the CI hang.** On 2026-09-04 the Linux 3.10 leg stalled
inside `lib/telegram/tests/test_suspend.py` and was cancelled at the 30-minute
cap; the same leg had passed in 8 minutes an hour earlier. Cause: those tests
patched `base_bot.time.time`, and because `base_bot.time` *is* the stdlib
`time` module, the fake clock was process-global. It returns epoch 1000.0, so
any deadline another thread captured beforehand read ~56 years away and that
thread waited forever. Cured with a seam — `from time import time as _now` —
and all 32 wall-clock reads in `base_bot.py` moved onto it, so the 23 test
patch sites now reach one module and nothing else.

---

*Owned by the skills branch. The face is [../README.md](../README.md).*
