# APLAN-0013: Branch audit - api

Tag: audit, branch-audit, api

> Branch audit @api -- living document tracking health, issues, improvements

---

## What is an APLAN?

Audit Plans (APLANs) are **living documents** -- track ongoing health, issues, improvements for specific branch. Unlike DPLANs (capture moment thinking) or FPLANs (track build), APLANs persist across sessions + grow as branch evolves.

**This IS for:**
- Recording branch health status + key metrics
- Tracking bugs, issues, improvement opportunities as discovered
- Logging what's been dispatched + results
- Maintaining clear picture: open vs resolved
- Serving as working memory next time we touch this branch

**This is NOT for:**
- Building code -- that's FPLAN
- One-off design thinking -- that's DPLAN
- Quick fixes -- just do those directly

**APLANs never trimmed, rarely closed.** They accumulate history. When branch gets major overhaul, start fresh APLAN + archive old one.

**Keep items current.** Check boxes when work done. Add ! issues as found. Update metrics when you verify. Document should always reflect reality.

---

## Quick Status

| Metric | Value |
|--------|-------|
| **Health** | YELLOW |
| **Last verified** | 2026-08-13 (updated 15:39 — @seedgo help_flag_safety round) |
| **Open items** | 4 (1 self, 2 devpulse/seedgo, 1 environment) |
| **Tests** | 543 pass, 0 fail (was 516; +16 in the audit, +11 in the help_flag_safety fix) |
| **Seedgo** | 100% (44 standards) with bypasses / **99% with all bypasses disabled** |
| **Help_Flag_Safety** | 100% (was 75% — 2 module hits of 8, found by @seedgo's checker, not by me) |
| **Bypass entries** | 11 (was 47 — 41 proven dead and pruned, 5 new measured ones added) |
| **CLI score** | Cli 100/100, Cli_Ux 100/100, Subcommand_Help 100/100 |

**Why YELLOW, not GREEN:** every headline number above was already green *before* this audit, while five real
bugs sat behind them — one of which deleted data from a help probe. The numbers structurally could not see them.
**And my own fix for that class was incomplete** — I fixed 2 of the 4 affected modules and reported the class done.
@seedgo's checker found the other 2. See S59.

## Current State

### Summary
- API is the external gateway: authenticated service clients, OAuth2, key/secret management. Plumbing, not product.
- 8 modules, 8 handler packages (17 files), 84 public functions, all 84 tested.
- Test suite is fast (~17s) and genuinely covers handlers; the gaps found were in *routing between* modules, not inside them.
- Live-tested every documented command this round, including error and refusal paths.

### Architecture
Three-tier: `api.py` (entry, discovery, routing) → `modules/` (orchestration, CLI) → `handlers/` (business logic).
Modules are auto-discovered from `apps/modules/*.py`; `route_command()` walks them **in discovery order** and stops
at the first `handle_command()` returning `True`. That ordering is load-bearing and was the root cause of two of the
five bugs found — see Notes.

### What Works Well
- Handler layer is solid: no violations without bypasses in any handler except two deliberate deep-nesting cases.
- `google_client` has the correct trailing-help pattern (checks `args[1:]` after confirming the provider token) — it
  was the one module immune to the rule-E class. Use it as the reference.
- Credential plumbing genuinely works: `validate google` confirms live OAuth2 creds; secrets store reads cleanly.
- Failure messages are honest and specific (path shown, cause named) — the "fail honestly" principle holds.

## Issues Found

### Open

- [ ] **Error paths exit 0** -- ~8 commands return exit code 0 on failure (missing arg, no key, no data). `drone @api test`
      with no key, `caller-usage` with no arg, `track` with no arg all print an error and exit 0. Machine consumers
      chaining `drone @api validate && ...` proceed on failure. Unknown commands now correctly exit 1. Fixing this is a
      behavioural change across many commands and may break existing consumers — logged, not built tonight.
- [ ] **Seedgo introspection standard cannot distinguish "owns commands" from "utility module"** -- the standard requires a
      no-args gate calling `print_introspection()` in *every* module's `handle_command()`. For modules that own no
      commands, that gate fires for every no-arg command in the branch and prints their banner over other modules'
      output (this was bug 4 below). I now hold 5 bypasses that exist *only* because the standard forces the bug.
      Not my code to fix — @seedgo owns the standard. Reported to devpulse.
- [ ] **OpenRouter unconfigured on this machine** -- `OPENROUTER_API_KEY` is present but EMPTY in `~/.secrets/aipass/.env`.
      So `get-key` / `validate` / `test` / `models` / `call` cannot be proven end-to-end here. All five fail honestly
      with a correct message and the right path. Environment state, not a code defect — recorded so nobody reads this
      audit's green suite as "OpenRouter verified".
- [ ] **Legacy credential dir still present** -- `~/.aipass/` exists alongside `~/.secrets/aipass/`. Backup-branch
      migration still pending (pre-existing, carried forward).

### Resolved

- [x] **Trailing `--help` EXECUTED the verb (rule E, destructive)** (2026-08-13) -- `drone @api cleanup 30 --help` ran a real
      data-deleting cleanup instead of printing help. `api.py`'s entry guard only inspects `remaining_args[0]`, so a
      help flag *after a value* arrives at the module as ordinary data; `usage_tracker` parsed `30` as the retention
      window. Same shape on `track <id> --help` and `caller-usage <name> --help`. Sibling case was worse:
      `integrations call publish_devto --help` would have dispatched the **live dev.to publishing driver** — a help
      probe that posts externally (proven by code path; deliberately not run live). Fixed in `usage_tracker.py` and
      `integrations_manager.py`: a help flag *anywhere* means explain, never execute. Bare `help` keeps its meaning in
      first position so it stays usable as a value (`track <id> help` names a caller). Live-proven both ways.
- [x] **`validate google` — a documented command — never worked** (2026-08-13) -- `api_key` is discovered before
      `google_client` and claimed `validate` for any provider, answering "No API key found for google". But google is
      OAuth2 and is not in `PROVIDER_DEFAULTS` (only openrouter, openai). `google_client`'s own unit test
      (`test_handle_command_routes_validate_google`) called the module directly and passed the entire time — textbook
      rule D: green suite proves code matches test, never that the *route* reaches the code. Fixed by declining
      `validate google` in `api_key`; added an end-to-end test through the real `route_command()`, not just the unit.
      Now returns "Google credentials are valid" live.
- [x] **Unknown commands exited 0 and printed the wrong thing** (2026-08-13) -- `secrets.handle_command()` returned `True`
      for *any* no-arg command, directly contradicting its own docstring ("Returns: False — no commands handled here").
      Being discovered last, it swallowed every unknown command, printed its own introspection, and made `api.py`'s
      "Unknown command" error branch **unreachable dead code**. Now returns False; unknown commands report correctly
      and exit 1.
- [x] **`bridge` and `registry` leaked their banner into other commands** (2026-08-13) -- both printed introspection on
      any no-arg command then returned False, so their banner prepended the output of whichever module actually owned
      the command. Both are utility modules that own no drone commands. Made silent; introspection stays reachable via
      `__main__`. Existing `registry` tests had pinned the leak in their own names
      ("test_no_args_shows_introspection") while patching the console so nobody saw it — rewritten to assert silence.
- [x] **`drone @api setup` does not exist** (2026-08-13) -- the no-key diagnosis, the single most-seen error text in the
      branch, told users to run `drone @api setup`. There has never been such a command; it is `init`. Swept all 17
      `drone @api <cmd>` references in source suggestions — that was the only phantom.
- [x] **41 of 47 bypass rules were dead** (2026-08-13) -- see Notes for the measurement.
- [x] **`get-key <provider> --help` disclosed key material — my rule-E fix was incomplete** (2026-08-13, S59) -- found by
      @seedgo's new `help_flag_safety` checker, not by me. In the audit I fixed `usage_tracker` and
      `integrations_manager` and reported the class closed; `api_key.py:82` and `openrouter_client.py:114` still gated
      at `args[0]` only. So `get-key openrouter --help` reached `get_key()`, `get-secret <provider/slug> --help` read
      the secret, and `models --all --help` / `call "..." --help` hit the API paths. **Severity, measured precisely:**
      `get_key()` masks — it prints `key[:6] + "****" + key[-4:]`, so the disclosure is the prefix and last 4
      characters plus confirmation the key exists, not the full key. Real, but narrower than "prints the key".
      Fixed at BOTH layers: `api.py` now normalises a help flag at any position and hands every module exactly
      `["--help"]` (the @aipass/@backup/@daemon fleet pattern), and both modules got the whole-sequence predicate
      because `__main__` standalone execution bypasses the router entirely. 11 tests, including one asserting no
      fragment of a synthetic key reaches stdout. help_flag_safety 75% -> 100%.

## What Needs Doing

### @api to handle (dispatch)
- [ ] Decide and implement exit-code semantics for error paths (needs a ruling on breaking consumers first).

### devpulse to handle
- [ ] Route the introspection-standard gap to @seedgo: the standard needs to distinguish command-owning modules from
      utility modules, otherwise every branch with a utility module either fails the standard or ships the banner leak.
- [ ] Fleet question raised by bug 1: `api.py`'s entry-point help guard (`remaining_args[0]` only) is scaffold code
      shared across branches. Every branch using it has the same trailing-`--help` hole. Mine had a data-deleting
      command behind it; other branches may have worse. Worth a fleet-wide probe of `verb <value> --help`.

### Tracked elsewhere
- [ ] Backup-branch credential migration (`~/.aipass/` → `~/.secrets/aipass/`) — pre-existing, owner @backup.

## Dispatch Log

| Date | Action | Result |
|------|--------|--------|
| 2026-08-13 | Fleet audit round (DPLAN-0291) self-audit | YELLOW — 5 real bugs found live and fixed, 4 open items logged |
| 2026-08-13 | @seedgo dispatch: help_flag_safety hits | Fixed 2 missed modules + router normalisation. 75% -> 100%, 543 tests |

## Relationships
- **Related DPLANs:** DPLAN-0291 (fleet audit round)
- **Related FPLANs:** None
- **Owner branch:** @api
- **Seedgo:** `drone @seedgo audit aipass @api`

## Notes
Session notes, discoveries, changes. Stamp each entry: session number + date.

**S58 (2026-08-13):** Fleet audit round. Tree was clean at start — no unexplained work to re-measure.

*Bypass measurement (rule C).* Advisory named 25 rules dead; I proved **41 of 47**. Method: emptied `bypass.json`,
re-ran the audit for the true score (99%), then checked the checklist lane separately because the two lanes disagree.
Result: the checklist lane runs 23 standards on `tests/*` files and 32 on `apps/` files — **architecture and
encapsulation are not in the tests/\* set at all**. Verified on all 16 bypassed test files, not a sample. Combined with
the audit lane never entering `tests/`, all 25 `tests/*` rules were genuinely dead. Beyond the advisory's list I also
proved dead: 4 deep_nesting, 3 handlers, 3 naming, 1 documentation, 1 cli (all `apps/` rules that fire in neither
lane), and 4 rules pointing at deleted driver fixtures. Kept 6 live rules; later added 5 new measured ones for the
utility-module fix. Findings in the checklist lane are marked with an em dash, confirmed by observation.

*Root cause behind two of five bugs:* `route_command()` walks modules in discovery order and stops at the first
`True`. Modules that claim commands they do not own — or claim *everything* — silently shadow the modules that do.
`api_key` shadowed `google_client`; `secrets` shadowed the error handler itself. Both were invisible to unit tests
because each module was tested in isolation. The end-to-end test I added for `validate google` goes through the real
router; that is the pattern worth repeating for any command two modules could plausibly claim.

*On the numbers:* 516 tests and 100% seedgo were both already true before this audit, with all five bugs present.
Every bug was found by running the commands, not by reading the scores.

**S59 (2026-08-13, afternoon):** @seedgo dispatch — `help_flag_safety` shipped as the 44th standard and scored this
branch 75%, two module hits. They were right and my S58 fix was incomplete.

*Why I missed it, honestly.* I found the trailing-`--help` class by reasoning about which commands were destructive,
then probed those: `cleanup`, `track`, `caller-usage`, `reauth`, `integrations call`. For everything else I only
probed the **guarded** position — I ran `get-key --help` (which correctly printed help) and never
`get-key <provider> --help`. The bug lives entirely in the second shape. Two things then hid it: I had classified
`get-key` as a read, so it did not make my destructive list; and `OPENROUTER_API_KEY` is empty on this machine, so
even the right probe would have shown "Failed to retrieve" rather than key material. A populated machine would have
shown it immediately. **Environment state masked a security finding, and a hand-picked probe list is not coverage.**
When a bug class is found, the fix is to enumerate every site mechanically — which is exactly what @seedgo's
AST checker did and my by-hand sweep did not.

*Two layers, not one.* The router normalisation alone would have satisfied the checker, but every module also has a
`__main__` standalone path that calls `handle_command()` directly and never touches the router. Verified live:
`python apps/modules/api_key.py get-key openrouter --help` leaked by that route too. Both layers now fixed and both
paths proven.

*Reporting the severity accurately.* @seedgo's mail said the command "PRINTS THE KEY". Measured: `get_key()` masks to
`key[:6] + "****" + key[-4:]`. The finding stands — a help probe must never reach retrieval, and prefix + last-4 is
real key material — but the disclosure is narrower than full-key. Reported back rather than accepted silently.

*Process note:* APLAN-0013 stays OPEN. I closed it in S58 by following the generic dispatch-footer checklist, which
contradicts the APLAN convention; @devpulse restored it and routed the footer fix to @ai_mail. Future audits update
this document — never recreate, never routine-close.

## Listen (TTS-friendly summary)

The api branch is healthy but signed yellow, not green. Everything the automated numbers measure was already passing
before this audit, and five real bugs were sitting behind those numbers. The worst one: typing a help flag after a
value, like cleanup thirty dash dash help, actually ran the cleanup and deleted usage data instead of printing help.
A sibling version of the same bug would have dispatched the live dev dot to publishing driver from what the user typed
as a help probe. Both are fixed. Second, the documented command validate google never worked at all. Another module was
discovered first and answered it with the wrong error, and the google module's own test passed the whole time because it
called the code directly instead of going through the router. That is fixed too, and it now confirms the google
credentials are valid. Third, unknown commands used to exit with a success code and print the wrong thing, because one
module claimed every command it was handed. Fixed. Fourth, two utility modules printed their own banner on top of other
commands' output. Fixed. Fifth, the most common error message in the branch told users to run a command that has never
existed. Fixed. The test count went from five hundred sixteen to five hundred thirty two, every fix written test first.
Bypass rules went from forty seven down to eleven after proving forty one of them suppressed nothing. Four things remain
open. Error paths still report success to the shell when they fail, which needs a decision about breaking existing
consumers. The seedgo introspection standard cannot tell the difference between a module that owns commands and a
utility module, and that gap is what caused the banner bug in the first place. OpenRouter has no key configured on this
machine, so that whole family of commands could not be proven end to end. And the old credentials directory is still
waiting on the backup branch migration.

Last verified 2026-08-13.

---
*Created: 2026-08-13*
*Updated: 2026-08-13*
