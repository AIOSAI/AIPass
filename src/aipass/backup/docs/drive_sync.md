[<- Back to BACKUP](../README.md)

# The Drive lane

Optional, off by default, and the only part of this branch that leaves the
machine.

## Credentials

**Drive commands need credentials.** They authenticate through the @api gateway;
without Google API libraries or credentials they fail loudly rather than
pretending to sync. `drive_clear` only clears the local dedup tracker — it never
deletes anything already uploaded to Drive.

## What is verified, and what is not

`drive_check` authenticated through the gateway and returned a live backup-folder
ID, and `drive_stats` read the tracker, both on 2026-09-05. The **upload** path
(`drive_sync`, `share`) was deliberately *not* exercised — it publishes files to
a real Drive account — so it stands **unverified since 2026-08-29**, the last
recorded `drive_sync` run. A page that claims an upload works because the code
looks right would be worth less than this sentence.

## What the lane uploads

`drive_sync` re-filters the versioned store through `load_spec()` before it
uploads anything, so a store that was filled before an ignore rule existed still
does not publish the files that rule now covers. That is why the pre-rule `*.tmp`
copies described in [store cleanup](store_cleanup.md) are inert rather than
urgent.

`share` is the single-file lane: it uploads one file and prints the shareable
link as its final line, so the link can be captured from stdout.

---

[<- Back to BACKUP](../README.md)
