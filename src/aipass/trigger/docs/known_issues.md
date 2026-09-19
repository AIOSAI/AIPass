# Known issues and compliance

**Branch** trigger · **Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

Open defects this branch owns, each with the measurement behind it, plus what the standards
audit says about this tree. Live state is never written down here — the commands below print
it, and a written copy would be wrong by morning.

```bash
drone @trigger medic status                 # medic state, the live watcher, every mute
drone @trigger errors stats                 # registry totals, silenced count, breaker state
drone @trigger escalation status            # lane settings, tracked signatures, digests sent
drone @seedgo audit aipass @trigger         # the standards score, bypasses and all
```

---

## Open

| Issue | Where | State |
|---|---|---|
| **A reload nobody authored.** The service reloaded at 2026-09-12 10:07:55 with no source edit behind it. The sentinel fires only on a `.py` added, removed or changed under `apps/handlers` or `apps/modules`, and `apps/modules` carried a directory mtime of 10:07:40 — something created or removed an entry in it. Nothing was left behind | `apps/modules/` | **Reported, not attributed.** @devpulse asked to be mailed the timestamp if the directory mtime moves again without one of my edits |
| `memory_template_updated` has a registered handler, no firer anywhere in the fleet, and the handler is a stub whose docstring claims a `push_templates()` call it does not make | `apps/handlers/events/memory_template_updated.py` | **Open, mine.** The real build is DPLAN-0318 |
| `drone @trigger status` always reports `Active: False` — it describes the CLI process you just started, never the systemd watcher. `medic status` is the command that reads the service | `apps/modules/branch_log_events.py` | **Open, mine.** Documented in [log_watching.md](log_watching.md); it is a wording-and-wiring fix, not a watcher fault |
| Stray `tmp*.tmp` files sit in `trigger_json/` — staged temp files whose rename never landed. Re-measured 2026-09-15: three, all zero-byte, all dated 09-10 | `trigger_json/` | **Open, mine, shrinking.** @prax's weekly sweep clears the class fleet-wide, but the sweep still belongs in the writer rather than in a cron |

## Closed, kept because the reasoning is the record

| Issue | Where | Outcome |
|---|---|---|
| **Unexplained work in my own tree** — on 2026-09-07 `test_json_handler.py` was archived and four test functions left `test_error_detected.py` and `test_log_watcher.py`, with no author on the files | `tests/` | **Closed 2026-09-15, attributed.** Commit c1e0eeed (DPLAN-0323 sealed, FPLAN-0491): the owner's ruling on the 2026-09-05 contested band, @seedgo owning the pack, @devpulse landing — no citizen edited this tree by hand. The shim pins now live once in @seedgo's json_handler contract tests. Reported first, never reverted |
| `error_logged` was advertised as a real event by `log_events --help` and two docstrings, and nothing fires it anywhere in the fleet | `apps/modules/log_events.py`, `apps/handlers/watchers/log_watcher.py` | **Closed 2026-09-15.** Known since 2026-08-25 and cured in three passes: `events/startup.py` 2026-09-12, then the help page and both docstrings tonight. The watchers fire `error_detected` and `warning_logged`, and nothing else |
| `memory_pool_auto_processed` had a registered handler and no firer | `apps/handlers/events/memory_pool.py` | **Closed 2026-09-05.** Found here, confirmed by @hooks, cured by @memory — the fire belongs at the child's own completion point, not where a PID first exists |
| `apps/json_templates/default/` still shipped `config.json`, `data.json` and `log.json` after the json service moved its defaults into code | `apps/.archive/json_templates/` | **Closed 2026-09-07.** Measured at zero references outside its own directory, then archived rather than deleted |
| The branch prompt still described fourteen events and a module layout that predated the retirements | `.aipass/aipass_local_prompt.md` | **Closed 2026-09-15.** Rewritten in the README diet, with the tree re-derived from the real tree rather than copied forward |

---

## Compliance

`drone @seedgo audit aipass @trigger` is the live answer; the shape of it is worth knowing
before you read a number.

The branch publishes **two** scores — with bypasses and without — and the difference is
deliberate. Each bypass rule in `.seedgo/bypass.json` suppresses exactly one real violation,
matched one-to-one by running the audit with `--no-bypass` and pairing each surviving
violation to its rule: no violation left un-bypassed, no rule left dead (the standing check
is APLAN-0008, closed 2026-09-13). The registry holds no `tests/*` rule, so the
checklist-lane trap that bit other branches — a rule that reads dead in the audit lane while
still suppressing findings in the PostToolUse hook — does not apply here.

The `handlers` deduction on `handlers/escalation.py` that this section described until
2026-09-08 is gone: @seedgo cured a check that could never match its own standard's
documented ALLOWED example. The question was raised rather than restructured around, and the
answer landed upstream.

---

## Related

- [log_watching.md](log_watching.md) — the `status` gotcha in context
- [events.md](events.md) — the events with nothing behind them
- [state_and_durability.md](state_and_durability.md) — the temp-file class and where it comes from
