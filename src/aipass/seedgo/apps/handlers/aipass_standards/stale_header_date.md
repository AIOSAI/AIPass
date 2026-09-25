# Stale Header Date Standards
**Status:** v1
**Date:** 2026-09-25

---

## What It Is

Test template v1 item 5 puts the META header on top of every test file, and the header says
`# Modified: <date>`. The date is a claim about the file. It goes stale the moment a change
lands without moving it. The 2026-09-24 review of @backup's tests found 14 of 14 headers
reading `2026-09-22` after b92e0361 rewrote every one of them on 2026-09-23.

```python
# Modified: 2026-09-22      # last commit touching this file: 2026-09-23
```

A file with no `Modified:` line is not this rule's business: item 5 owns the header, and
`file_top` convicts its absence.

---

## The date of truth

The author date of the last commit that touched the file (`git log --format=%as`). A file with
an uncommitted change, or one never committed, is judged as of **today**: its content is
newer than any commit. So a change that did not move the date is convicted at the edit, where
the checklist hook already runs, and a change that moved it passes at once.

That choice also keeps a verdict stable across the commit that follows. The audit's
incremental cache keys a file's result on `(mtime, size)`, and a commit changes neither. One
edge remains and is stated rather than hidden: a change dated one evening and committed after
midnight carries the next day's author date, so CI convicts it while a local cached audit
still shows the pass until the file next changes.

## The first checker to read git

It reads only: `rev-parse --is-shallow-repository`, `log`, `diff --name-only HEAD` and
`ls-files --others`, one batch per directory, cached for the process. Measured over the
fleet's 594 test files: **5.5 s**.

Where history cannot answer, the rule **declines** — the file is reported not applicable and
stays out of the average. A 100 would claim a measurement that never happened.

| where | why it declines |
|---|---|
| no git on `PATH`, or not a work tree | an installed wheel or a tarball has no history |
| a **shallow** clone | every file's last commit is the one HEAD commit, so the rule would convict everything or nothing |
| a file git neither tracks nor lists as changed | ignored; there is no history to read |

CI's `seedgo-audit` job checks out with `fetch-depth: 0` (`.github/workflows/ci.yml`), so the
gate sees full history and matches a local audit. Any other shallow checkout declines.

---

## Check first

Measured 2026-09-25 over the fleet's test files, before the rule landed.

| | |
|---|---|
| test files | 594 |
| carrying a `Modified:` line and judged | 433 |
| stale | **326** |
| current | 107 |
| declined (no `Modified:` line, or no history) | 161 |

Of the stale files whose last commit is known, 182 are more than 30 days behind. Mechanical
sweeps account for some: tonight's RUF100 commit (7cbe39e5) alone made 16 stale, and a
comment sweep on 2026-09-19 (30f25cb5) 35. A sweep modifies the file, so its date is stale
too; nothing is tuned to exempt one.

## Why it cannot be satisfied by accident

The header and the history are two statements about the same file. There is no threshold and
nothing to tune.

## Scoring

Scored, per file: 0 when stale, 100 when current, left out of the average when declined.

## The cure

Move `Modified:` to the date of the change.

---

[← Back to README](../../../README.md)
