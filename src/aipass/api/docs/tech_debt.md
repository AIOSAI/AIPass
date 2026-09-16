# Status and known issues

**Branch** api · **Code** the standing record; plans carry the fixes
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

---

**Measured 2026-09-05:** seedgo audit 100% on all 47 categories · 1463 test
functions across 47 files, pytest expands to 1561 cases, 1561 pass / 0 skipped
(137s) · 240 public functions, 217 tested · 45 production files in the audit
corpus · ruff, format and pyright clean.

- **Two working command families are absent from `drone @api --help`: `host-api` and
  `integrations`.** Both run — `host-api status` returned a live server tonight and
  `integrations list` printed two registered contracts — but neither appears in the help
  table or the trailing `Commands:` line, which lists 14 and omits these. The `host-api`
  half was found by @devpulse 2026-09-05; checking every README command against `--help`
  the same night turned up `integrations` as the same defect. So the largest surface on
  this branch is undiscoverable from the front door, and this README is the only place
  that documents it. Code fix, not a docs fix; deliberately not made in this docs-only
  pass. Everything `--help` *does* list was run tonight and matches its description.
- **`openai` is a provider name with no provider behind it.** `list-providers` prints it
  and `PROVIDER_DEFAULTS` carries an `api.openai.com` base URL and an `sk-` validation
  rule, but nothing reads that base URL: `create_client()` is hardcoded to
  `OPENROUTER_BASE_URL`, and `PROVIDER_DEFAULTS` is consumed only by the listing itself
  (`api_key.py:164`). So `get-key openai` and `validate openai` reach a key store that is
  never used to call anything. The OpenAI SDK here is transport for OpenRouter, not an
  OpenAI integration.
- **Google auth libraries are optional deps** — commands fail with install instructions if
  missing. Verified importable tonight (`google.auth`, `googleapiclient`).
- **No rate limiting on OpenRouter calls** (S117 finding). Verified tonight: zero
  rate-limit, throttle or backoff code in `handlers/openrouter/` or `openrouter_client.py`.

*Fixed 2026-09-08 (FPLAN-0492, canary's fleet refusal sweep):*

- **Error paths no longer exit `0`.** This item stood from 2026-08-13 and was re-measured
  six-for-six on 08-28. `main()` now clears cli's process-level failure flag before
  routing and returns `resolve_exit(handled)`: **1** unrecognised, **2**
  recognised-and-refused, **0** only when nothing printed an error. Measured after, from
  the shell, status read from the command itself:

  | command | before | after |
  |---|---|---|
  | `drone @api caller-usage` | 0 | **2** |
  | `drone @api track` | 0 | **2** |
  | `drone @api get-key` | 0 | **2** |
  | `drone @api validate` | 0 | **2** |
  | `drone @api get-secret` | 0 | **2** |
  | `drone @api models` | 0 | **2** |
  | `drone @api host-api revoke-token <unknown>` | 0 | **2** |
  | `drone @api definitelynotacommand` | 1 | 1 |
  | `list-providers` · `stats` · `session` · `--help` · bare | 0 | 0 |

  `revoke-token` on an unknown id was the branch's one `warning()`-channel refusal
  (canary's sweep row) and is an `error()` naming the id now. All 63 `error()` call sites
  were read before the seam went in, looking for one that prints a failure on a path that
  still succeeds; there were none, which is the only reason this was a one-line change.
  Five mutations, each red.

*Fixed 2026-09-07 (FPLAN-0492 wave 4), both from one night's incidents:*

- **A refused bind now exits `1`.** All three refusal sites in `host_serve.py` —
  foreground, detached, and the launcher — call `sys.exit(1)`. The unit is
  `Restart=on-failure` with a 60-attempt window built for exactly the boot race where
  tailscaled has not yet assigned the address, and a zero exit had silently disarmed all
  sixty: measured 09-07, the unit gave up at 12:19:16 and the address arrived at 12:19:22.
  Two of the last six boots died that way. The README had claimed this path "exits
  non-zero immediately", which is why nobody checked the mechanism.
- **The git-changes lane coalesces.** `read_cache.py` holds the single-flight + TTL
  mechanism (1.5s, keyed on `(branch, project, grain)`); `git_reads.py` asks the question
  and owns the key, and `fleet.py` still carries its own copy of the same shape for
  @baud's snapshot — folding that one in is the obvious follow-up, not done here. Before:
  every `/v1/git-changes?branch=<X>` spawned its own `drone @git status --json`, and on
  09-07 at 12:17 thirty-one hit the lane's 30s timeout in the same second. Measured that
  day: one call alone 0.5s, 20 concurrent 13.8s median, 31 concurrent 17.9s on an idle
  machine — 60% of the budget at rest, which is why boot-window load pushed it over. The
  cure was coalescing, never a longer timeout: raising the ceiling only makes a slow
  screen slower while leaving the N execs in place.

*Retired 2026-09-05:* this list carried "backup branch credential migration pending
(`~/.aipass/` → `~/.secrets/aipass/`, legacy dir still present)" for months. It is
**wrong**: `~/.aipass/` holds live fleet state — `commons.db`, `daemon-tick.log`,
`trusted_projects.json`, `admin_grant.key`, `skills/`, `telegram_bots/` — and not one
api credential. There is nothing here to migrate, and acting on the item as written
would have deleted state other branches depend on. Closed once already in the 08-28
audit refresh; the README kept it standing until tonight.

**Troubleshooting:** `openai`/Google auth `ModuleNotFoundError` despite a working venv → the `[llm]`/`[drive]` extras were added after the venv was last built; re-run `setup.sh` (installs `.[dev,memory,llm,drive]`) to resync, no code fix needed. Both import cleanly as of 2026-08-25 (`openai` 2.49.0, `google.auth` + `googleapiclient`), verified by import alone — no call goes out.

---

*Last Updated: 2026-09-10*

[← Back to AIPass](../../../README.md)

---

[← api README](../README.md)
