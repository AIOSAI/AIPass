# Fleet Inbox Sweep

How the inbox-sweep hand tool wakes owners of stale unread mail across the whole fleet.

[<- daemon README](../README.md)

---

Replies never wake their recipient, so a reply landing in a sleeping branch's inbox stays invisible until something looks. `inbox-sweep` is that something.

It reads every active branch's `.ai_mail.local/inbox.json`, finds mailboxes holding `new` (unread) mail older than the threshold, and wakes each owner via `wake_branch()` so the mail finally gets read.

**Scope: a citizen is a citizen.** The sweep looks wherever the fleet definition looks — `src/aipass/*` framework branches, `projects/*/` residents and the federated externals alike — because it walks discovery's active branch map and that map is @memory's `fleet.fleet_branches()`. Measured 2026-09-07: **28 citizens, 18 core + 4 under `projects/` + 6 external**; that morning's sweep listed @baud, @finch, @earmark, @aipass_site and @wren among its stale mailboxes. FPLAN-0460 widened this when it deleted daemon's private registry read; the module docstring and the introspection panel still said "AIPASS_REGISTRY.json" until 2026-09-07 and now say what the code does. Pinned by `TestSweepScopeIsTheWholeFleet`.

| Rule | Behaviour |
|------|-----------|
| Threshold | 24h by default (`--hours N` to override) |
| Once per branch | One wake per branch per sweep, never more |
| Managers | Never woken — reported as skipped, their mail lands live |
| Blocklist | `@devpulse` and anything in ai_mail's `WAKE_BLOCKLIST` is skipped |
| Cap | 5 wakes per pass (`--limit N`); entries are oldest-first, and deferred branches are named in the output, not silently dropped |
| Wake model | `sonnet`, staggered 2s apart |

**Not scheduled since 2026-09-10.** The daily 09:00 job is deleted (DPLAN-0337 R2): waking up to five agents every morning was, in the owner's words, nuisance token waste, and the nightly rounds now take each citizen's inbox to zero, one citizen a night. The command stays as a hand tool; `drone @daemon inbox-sweep --dry-run` shows who is sitting on stale mail without waking anyone.

---
