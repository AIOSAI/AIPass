# Known issues and the bypass registry

**Branch** ai_mail · **Code** `apps/modules/email.py`, `apps/modules/dispatch.py`, `apps/handlers/email/reply.py`, `apps/handlers/email/delivery.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

The open defects live in **APLAN-0006** — that plan is the register, this page is the
explanation. A count of what is open belongs to `drone @flow` and the plan, never here.

---

## The bypass registry

`.seedgo/bypass.json`, per branch, is the documented-exception list: each entry names a
file, a standard, optional line numbers and a **required reason**. Read the live file for
what is in it; a number written down here is stale the next time a rule is added or
retired.

It once held far more rules than it does now. The 2026-08-13 audit measured every rule in
**both** lanes — the audit lane (`audit aipass @ai_mail --full`, which walks `apps/`) and
the checklist lane (what the PostToolUse hook runs per file) — with the registry emptied.
The rules that suppressed nothing in either lane were removed, and the score was 100%
before and after, which is the proof. Each dead class had a cause, not just an absence:

| Class | Why it went dead |
|---|---|
| `handlers`, same-branch | The standard now flags only **cross-branch** handler imports and handler→modules. The imports the reasons describe are still in the code and now pass. |
| `documentation` | The AST detector's multiline-signature miss was fixed upstream; the signatures are unchanged. |
| `deep_nesting`, depth 4 | The limit is now 5. Every surviving rule names a depth-5+ function. |
| `naming`, local variables | Plain locals are no longer read as module constants. Lazy-import *function references* still are — those rules stayed. |
| `modules` | A helper module without `handle_command()` no longer violates. |
| file no longer exists | `email/identity.py`, gone from the tree with no archive and no references. |

Measured, not assumed: this branch has **no `tests/*` rules**, which is the class that made
the naive audit-lane-only signal wrong five times in six for @seedgo. Here the two lanes
agreed on every rule. Do not reuse that conclusion for a branch that has `tests/*` rules —
re-measure per lane.

---

## Open issues

Each of these was reproduced when it was last written down; all are open in APLAN-0006.

- **No per-subcommand help.** `view --help`, `reply --help`, `close --help`, `sent --help`,
  `contacts --help` and `inbox --help` all print the same email-module help. The
  `subcommand_help` standard scores 100% on it, which is why the standard did not catch it.
- **`--model` help names retired models.** `dispatch --help` names model versions that have
  moved on. The aliases themselves (`opus`, `sonnet`, `haiku`, `fable`) are passed to the
  claude CLI, which resolves latest-in-class — it is the help prose that is dated, not the
  behaviour.
- **`dispatch status` reports "No dispatches recorded yet." while dispatches are running.**
  First reproduced 2026-08-25 with two live entries, and again on 2026-09-05 while
  `dispatch register` listed live rows, including the dispatch running at the time. The
  register is the trustworthy view; `status` reads a different log and its empty answer is
  a false negative, not an empty state.
- **`dispatch wake` prints "see step status above"** when the step status prints below it
  (`apps/modules/dispatch.py`). See [cli_contract.md](cli_contract.md), *Output ordering*.
- **`tests/test_dispatch_monitor.py` carries duplicate test pairs** — pairs of
  differently-named functions whose bodies are identical after the docstring. An opus judge
  reported three on 2026-09-05; an AST comparison of every top-level test body in the file
  found eight, so the report understated it. Not a correctness bug — the file is green —
  but the suite reports more passing tests than it has distinct assertions. Recorded, not
  fixed: merging tests is Patrick's call.

  | | line | line |
  |---|---|---|
  | `kill_process_terminate_succeeds` / `kill_process_sigterm_success` | 624 | 1262 |
  | `kill_process_terminate_timeout_falls_back_to_sigkill` / `kill_process_sigkill_fallback` | 638 | 1276 |
  | `stdout_rotation_on_large_file` / `stdout_rotation` | 736 | 1375 |
  | `lock_cleanup_on_success` / `lock_cleaned_on_success` | 782 | 1420 |
  | `lock_cleanup_on_failure` / `lock_cleaned_on_failure` | 801 | 1439 |
  | `rotate_attempt_stdout_skips_empty` / `rotate_attempt_stdout_empty_file_noop` | 845 | 2590 |
  | `cleanup_own_lock_deletes_when_owner` / `cleanup_own_lock_deletes_when_pid_matches` | 945 | 2752 |
  | `cleanup_own_lock_missing_noop` / `cleanup_own_lock_missing_file_noop` | 975 | 2775 |

- **The notification gap (DPLAN-0138).** `send_notification` is called from exactly one
  place, inside `deliver_email_to_branch` in `email/delivery.py`. Neither
  `deliver_to_inbox_file()` nor `email/reply.py` calls it, so a cross-project reply lands in
  the recipient's inbox with **no feed line** — BAUD's bell never rings for it. See
  [dispatch_register_and_feed.md](dispatch_register_and_feed.md).

### Corrected, kept here so the correction is not lost

- **`_deliver_via_reply_path()` does lock.** The DPLAN-0138 audit entry saying otherwise was
  wrong. It lives in `email/reply.py`, validates the stored path through
  `_validate_reply_path()` first, then delegates to `delivery.deliver_to_inbox_file()`,
  which takes the same `_get_inbox_lock()` every other write takes and mints a `uuid4[:8]`
  id. "Detectable by non-UUID ID format" does not apply to that route either.

### Carried forward, never re-measured

Named because an unverified claim that looks measured is the worse kind:

- **Ad-hoc direct writes detectable by non-UUID ID format** — the other half of the
  DPLAN-0138 audit entry, not re-measured since.
- **Caller detection** — `BRANCH DETECTION FAILED` when callers do not set
  `AIPASS_CALLER_BRANCH`. Low severity, caller-side fix: use `--from`.
- **Cross-branch writes** — ai_mail is not in the trusted cross-writers list for `system-pr`.
  That list lives in @hooks' `security/edit_gate.py`, another branch's tree, so it is not
  measurable from here.

---

## Related

- [cli_contract.md](cli_contract.md) — the help-flag and exit-code contract these defects sit against
- [dispatch_register_and_feed.md](dispatch_register_and_feed.md) — the register that `dispatch status` disagrees with
- [sending_and_delivery.md](sending_and_delivery.md) — the delivery pipeline the notification gap is in
