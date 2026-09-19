[<- Back to the README](../README.md)

# Docs

Tracked public reference for the `PRAX` branch.

This README plus any finished, durable documentation meant to be read by other
branches or by a human — setup guides, architecture notes, policy write-ups. It
is committed, so write it as if it ships.

The depth behind the branch README lives here, one file per module or handler
group: the README is the face for strangers, these pages are what you open when
something breaks. Work in progress, research and dated one-offs belong in
`docs.local/`, never here.

## Index

- [logging_api.md](logging_api.md) — both import patterns, log levels, the
  mocking contract other branches' tests rely on, the lifecycle events.
- [monitor.md](monitor.md) — Mission Control: threads, multi-CLI session
  reading, the commons feed, the Telegram relay.
- [dashboard.md](dashboard.md) — refresh, template push and diff, and the
  write-through API services call.
- [dashboard_caps.md](dashboard_caps.md) — the subject cap and whole-file budget
  every dashboard section writer reads, including writers outside prax.
- [log_audit.md](log_audit.md) — health summaries, growth rates, truncation, and
  the weekly sweep the daemon runs.
- [discovery.md](discovery.md) — the scheduled scan behind the module registry,
  and the watcher's own events.
- [json_service.md](json_service.md) — the config/data/log triplet every branch
  writes through, and its test seam.
- [architecture.md](architecture.md) — how a command reaches a handler: router,
  unknown-argument gate, exit seam, help behaviour, status sync.
- [tests.md](tests.md) — how the suite is organised and how to run it.
