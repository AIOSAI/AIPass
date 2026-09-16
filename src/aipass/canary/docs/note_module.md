# The note module

An append-only note store: `note add` writes one line, `note list` reads them
back. `apps/modules/note.py` routes; `apps/handlers/notes/store.py` does the
reading and the appending.

It exists as a test subject, not as a feature. It was built blind as an exam for
the fleet's test standard — the brief never said it was being marked — and it
stays because the behaviour it pins is worth keeping around.

## The store

- **Where:** `docs.local/notes.jsonl`, inside this branch. `docs.local/` is
  ignored by the repository, and a test pins that by reading the ignore file
  itself rather than trusting the claim.
- **Format:** UTF-8 JSON Lines. Each record is exactly `{"text": ...,
  "timestamp": ...}`, an ISO-8601 local time with its UTC offset, terminated by
  a newline. Exactly those keys: a record carrying an extra key is not a record.
- **Append-only:** `add` parses the whole store first, then opens the file in
  append mode. No code path truncates, resets or rewrites it.

## The refusal

A store that exists but will not parse — not UTF-8, a line that is not a record,
a blank line, a final record with no terminator — is refused by file name with
exit 2, and the bytes and the modification time are left exactly as they were.
The refusal names the file and the line, says the store was left untouched, and
suggests inspecting or moving it by hand.

The other refusals are the same species: `add` with no text, `list` with
arguments, an unknown subcommand. All exit 2, all print to stderr.

## Why not the fleet json service

The shared json service is the right home for a config or a log document, and
the wrong home for this one. Its `ensure_json_exists` rebuilds an unreadable
document from the in-code default, and its `load_json` runs that before every
read — precisely the reset this store must never perform. Data that has to
survive one bad read cannot live there. The module still uses the service's
`log_operation` for its operation trail, which is what that service is for.

## What the tests actually measure

The corrupt-store cases are parametrised and assert bytes *and* modification
time, so "refuses loudly and truncates the store" cannot pass. Each carries a
valid-store control, so the suite cannot pass vacuously. The missing-store case
asserts the file was not created.

Mutation-checked before reporting, by hand: mutants for append-mode-to-truncate,
a deleted terminator guard, and a refusal printed to stdout with exit 0 all died.
One survived on the first pass — the terminator guard, because both unterminated
cases broke the JSON anyway once their final byte was dropped. A valid record
plus a trailing space with no newline convicts it now.

A later pass by the reviewer found the completeness gap that remains: the
exactly-these-two-keys half of the format rule has a missing-key case and a
not-a-record case, but no superset case, so a record carrying an extra key would
be accepted by a weakened check without any test going red. Recorded here rather
than repaired, because the gap is the finding.

[<- Back to the branch README](../README.md)
