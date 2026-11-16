[<- Back to the README](../README.md)

# Mail kinds

Every delivered mail carries a `kind`, set once at delivery by one pure function,
`apps/handlers/email/mail_kind.py`. @hooks (the mail line), @api and BAUD (the chat box)
read it. A change to this contract is mailed to @devpulse first.

## The contract

- The field is `kind` on the inbox message, and `mail_kind` beside `mail_id` on the
  `kind: "mail"` line of `.aipass/notifications.jsonl`.
- Values, exactly: `medic`, `rounds`, `job_failed`, `notice`, `mail`.
- A declared kind wins. `drone @ai_mail email ... --kind <kind>` declares it from the CLI;
  an in-process sender puts `"kind"` on the `email_data` it hands `deliver_email_to_branch()`
  or `post_to_inbox_file()`. An unknown declared value is refused at send (exit 2) and at
  delivery (`Refused: unknown mail kind ...`); it is never mapped to a known one.
- Undeclared, the kind is guessed from sender and subject. A mail with no decidable kind is `mail`.
- Messages stored before kinds existed are not rewritten. `aipass.ai_mail.mail_kind(message)`
  reads them: `notice` for the three notice subjects, `mail` for everything else. A stored
  value outside the five reads as `mail` and is logged.

## The classification, in order

| Kind | Rule | Declared today by |
|------|------|-------------------|
| declared | `kind` given by the sender | `Dispatch complete:` wake-back mail (dispatch monitor, `--kind notice`) |
| `medic` | from `@trigger` and the subject opens with a bracket tag: `[REPEAT]`, `[ROLL-UP]`, `[UNIT]`, `[CI RED]`, `[CI REVIEW]`, `[ERROR]`, `[LOG FIX]`, `[RUNAWAY]`, `[MEDIC]`, `[TRIGGER]` | guessed |
| `job_failed` | subject opens `Command job failed:` (any case; @daemon writes `FAILED`) | guessed |
| `notice` | subject opens `Dispatch complete:`, `Command job started:` or `Command job passed:` | guessed for @daemon |
| `rounds` | the word `rounds` in a subject that is not a reply (`RE:`) | guessed |
| `mail` | everything else: replies, fix reports, questions, briefs | default |

@trigger's own citizen mail (`RE: ...`, a brief) carries no bracket tag, so it is `mail`.

## The feed's rate limit

`_emit_notification_event()` keeps at most 3 feed lines per recipient per 30 s. The
counter lives in the delivering process, so a CLI send (one process per mail) never meets
it; a long-lived sender does: @trigger's log watcher service delivers in-process. The limit
drops only `notice` and `mail` lines, and names each drop in the log. A `medic`, `rounds`
or `job_failed` line is always written.

An upsert update writes no feed line, whatever its kind: a repeat signal updates the one
message instead of stacking lines.
