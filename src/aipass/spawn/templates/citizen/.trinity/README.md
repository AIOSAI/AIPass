# Identity & Memory

These files are your presence in the system. Without them, you're just a
directory with code.

- `passport.json` — Who you are. Role, purpose, principles, citizenship.
- `local.json` — Session history, key learnings, todos.
- `observations.json` — Collaboration patterns and what you learn about the user.

Anything else in here is machine-written — receipts, tracking, backups. Not yours
to edit.

## Hand-written memories in a machine-owned frame

You write the entry content: the summaries, the learnings, the notes. The
machinery owns everything around it — metadata blocks, section order, the
`*_meta` lines, the `_usage` text. Don't hand-edit the frame and don't invent
fields. A shape the checker cannot read is a violation, never a silent pass.

## The limits live in the meta lines

Each section's `*_meta` line says what that section keeps and how long an entry
may be. Those numbers are rendered from @memory's config — that is the one
source. Read the meta line before you write; an over-limit edit is rejected
whole, so draft short rather than trimming after. This file deliberately quotes
no numbers: numbers in prose go stale, meta lines don't.

## Rollover

Sections roll over. When one fills up its oldest entries are archived to @memory
as searchable vectors and dropped from the file — nothing is lost, it just moves
deeper. `drone @memory search "query"` brings it back. An entry you remember
writing but can't find here has almost certainly rolled; absence locally is not
absence.

`todos` never roll. They are operational — delete each one the moment it's done,
never leave it sitting as `status: done`.

## The shapes

The canonical shape of every section — required fields, ordering, numbering — is
the trinity standard, and it is what scores these files:

```
drone @seedgo standards_query aipass_standards trinity
```
