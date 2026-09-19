# Wake lanes: admin, cross-project, @all, and the daemon

**Branch** ai_mail · **Code** `apps/handlers/dispatch/wake.py`, `apps/modules/dispatch.py`, `apps/handlers/dispatch/daemon.py`, `apps/handlers/email/delivery.py`, `apps/handlers/users/verified_caller.py`, `apps/handlers/email/reply.py`, `apps/handlers/registry/read.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

---

## Admin Lane (`admin=True`)

The owner's ruling (DPLAN-0288): @devpulse — and only @devpulse — holds an admin
grant that lets a dispatch wake **manager-class** citizens. `wake_branch` takes a
keyword-only `admin` flag that is an *already-decided verdict*, never a request:

```python
status, ok = wake_branch(target, sender=..., admin=is_admin)
```

- **The check runs in `dispatch.py`, not here.** Leg 1 of the contract needs
  `AIPASS_CALLER_*`, and `wake_branch`'s in-process callers don't carry it — a
  `wake_branch` that verified its own caller would be verifying nobody.
- **Five legs, all or nothing** (FPLAN-0401 THE CONTRACT): verified caller is
  devpulse · cert path resolved from the *registry* entry, never caller-supplied ·
  cert content (`owner`, `type`, `privileges.admin`) · HMAC-SHA256 signature over
  the canonical cert-minus-signature payload · registry `admin: true`.
  `verified_caller.verify_admin_caller()` delegates to @devpulse's reference
  implementation rather than mirroring it — one contract, one home, no drift.
- **Lane dark by default.** The signing key lives at `~/.aipass/admin_grant.key`,
  outside every repo, and does not exist until the ceremony. No key → leg 4 fails
  → today's behavior exactly. An import failure of the reference is *also* dark,
  and a verifier that raises is caught: a privilege path never takes mail down.
- **`WAKE_BLOCKLIST` still refuses.** Admin raises the stakes, not the fence —
  @devpulse stays undispatchable even by a verified admin, checked before the
  passport read alongside the scheduled lane.
- **Non-holders pay nothing.** The verifier only runs when the rail already says
  the caller is the grant holder; everyone else's dispatch is byte-identical, with
  no key read and no file I/O.
- `status.find_step("admin")` marks the lane; when both flags are set the
  scheduled lane wins and reports itself, so a 5am rotation is never logged as an
  admin dispatch.

## Cross-Project Bridge (verified-admin only)

Citizens under `projects/*` (e.g. @baud) sit behind two walls, and phase 5 of
FPLAN-0401 puts one door in each — openable only with the grant:

- **Resolution.** `resolve_branch(email, admin=False)` gains a third step: an
  `admin`-only sweep of `projects/*/*_REGISTRY.json` under the repo root. It runs
  **last**, so a local branch always wins and the sweep is a fallback, never a
  preempt. Left at its default the function behaves exactly as it did before —
  there is no resolution widening for anyone unverified.
- **Delivery.** `_check_cross_project_boundary()` gains a verified-admin
  exemption, and the branch map gains the same sweep. The exemption is checked
  **last**, once a refusal is otherwise certain, so ordinary same-project mail
  never reads the grant.
- **One boolean, no cache.** Both halves consult
  `verified_caller.is_verified_admin_caller()` — rail says holder, then all five
  legs. Deliberately uncached: a per-process cache would keep a revoked grant
  alive until restart, which is failing open. A raising verifier is a refusal.
- **Dark today.** No key → no bridge, end to end: @baud does not resolve and the
  boundary refuses with the same wording as before. Vera-Studio (a separate repo)
  is out of scope — this reads the projects the repo already hosts, and is not a
  multi-root discovery layer.

## `@all` Scope: Fleet, Plus Residents for a Verified Admin

`@all` resolves the core citizens. A **verified-admin** `@all` also reaches the
resident projects — baud, earmark, finch, aipass_site (ruled 2026-08-27,
DPLAN-0318 circle close). Ordinary citizens' `@all` is byte-identical to what it
was: the widening rides the same five-leg verification that already permits
admin-initiated direct mail into projects, and grants no new authority — every
recipient still passes the per-delivery boundary check.

The case that decided it: the fleet-push announcement had to be hand-sent to the
four residents in four separate admin sends, because `@all` could not carry it.
An announcement every citizen should hear is exactly what the asymmetry was
built for.

- **Residency is DECLARED, not listed** (2026-08-28, DPLAN-0319 wave 3).
  `get_resident_branches()` no longer carries a hardcoded four-name tuple. It
  discovers `projects/<name>/*_REGISTRY.json` one level down, then reads
  `citizenship.residency` from each listed branch's own passport. Both keys are
  required: the registry must say `active` **and** the passport must say
  `resident`. That asymmetry is the point — a passport can never *add* scope (a
  self-declared resident that no registry lists is unreachable by construction),
  and a stale registry field can never *carry* one (marketstand's registry still
  says `active`; its passport does not say `resident`, so it is refused and named
  at error level).
- **Two exclusion layers, each load-bearing alone.** `pathlib` globs match hidden
  directories — unlike a shell — so `.archive` needs an *explicit* dot filter, and
  the one-level depth rule is separate from it. On the live tree they overlap
  (`projects/.archive/marketstand(on _hold)/` is caught by both), which is exactly
  how a single-layer regression hides. Each layer therefore has a fixture that
  only *it* refuses.
- **Broadcast scope and resolution scope are different questions.**
  `get_project_tree_branches()` still globs, and should: a held project's citizen
  legitimately has an *address*. Being reachable is not the same as being on the
  announcement list. It does, however, lack the dot filter — a registry planted
  directly at `projects/.archive/X_REGISTRY.json` resolves. Masked today only
  because the real held projects sit a level deeper. Reported to @devpulse
  2026-08-28, deliberately not refactored under this dispatch.
- **The semantics are mirrored, the code is mine.** @memory's
  `registry_scope.accepted_resident_paths()` is the fleet definition; this reads
  the same passport field with its own code. No runtime import — `@all` must not
  need @memory to know who it is talking to. The old drift pin AST-parsed
  @memory's constant; when the constant went, the pin went with it, replaced by
  behavioural pins of this branch's own resolution. Pinning another branch's
  source text was never the check it looked like.
- **Fails closed in both directions.** An unverified caller widens nothing, and a
  verifier that *raises* is a refusal, not an opening.
- **One inbox, one copy** — a resident already in the core registry is not added
  twice.

## Out-of-Scope Addresses Are Explained, Not Denied

An address can fail to resolve for two different reasons, and reporting both as
"unknown" is a lie in one of them. `@baud` is a registered citizen of `projects/baud`
that @devpulse reaches through the admin lane; telling a fleet branch it does not exist
sent @api hunting an addressing bug that did not exist and left two stray pings in
@baud's inbox (2026-08-14).

```
Out of scope: @baud is a citizen of hosted project 'baud', not the AIPass fleet
(17 branches in scope). Fleet-to-project mail is replies-only by ruling
(DPLAN-0288) — only @devpulse's verified-admin lane may initiate. Reply to an
existing message from @baud, or use the feedback channel.
```

The branch count is **computed, not written** — `len(branches)` for the caller's own
scope, handed to `_describe_unresolved_address()`. It reads 18 today and drifts with the
fleet; the number above is an example of the shape, never a constant.

- **The refusal is unchanged — only the reason is now true.** Fleet→project initiation
  stays walled for every non-admin caller, exit `2`, sent record stamped `refused`.
- **`_describe_unresolved_address()` runs on the failure path only**, so a successful
  send never pays for the registry read.
- **Explaining the wall must not open it.** The diagnostic returns a *string*; the branch
  map is never updated from it. A test asserts delivery still fails and no inbox is
  written — that is the load-bearing test in this fix, not the wording ones.
- **Exact match**, so `@bau` is still an honest "unknown", not a near-miss guess.
- A hosted registry that is missing or unreadable falls back to the plain unknown
  message; a refusal never becomes a crash.

Naming the project is not a disclosure: `projects/` is in the same public repo, and the
caller can list it. What was secret was the *policy*, which is exactly what a wall should
say out loud.

**Two walls, and they used to disagree.** Resolution is the outer wall;
`_check_cross_project_boundary()` is the inner one. The inner wall already named both
projects and said "cross-project mail refused". Anyone stopped by the outer wall never
learned a policy existed at all.

## Reply Return Path

The bridge opened one-way — admin mail got in, the targets' replies could not get
out (live proof, 2026-08-12: exempted 17:44, refused 17:46). Phase 5b closes it
with a second boundary exemption, narrower than the first:

- **A reply is answering, not initiating.** The referenced message sitting in the
  sender's *own* mailbox is the proof the channel was sanctioned. Initiation
  across projects stays admin-only and inbound-only.
- **`_is_sanctioned_reply(email_data, to_branch)`** allows delivery only when the
  outbound mail carries an `in_reply_to`, that id is present in the sender's
  mailbox, and the destination matches that message's `from` **or** its
  `reply_to`. Both are fields only the *original sender* could have written —
  the replier never picks them, so a new recipient cannot be laundered through a
  reply. Matching `reply_to` as well is required, not generous: `reply.py` routes
  to `reply_to or from`, so a `from`-only exemption would refuse the very replies
  it exists to allow.
- **Inbox-only lookup, mirroring `reply.py`.** `get_email_by_id()` reads the
  inbox, and delivery failure returns *before* the auto-close — so during a real
  reply the original is always still there. Checking anywhere else would accept
  proof `reply.py` itself would not.
- **Fails closed everywhere else:** forged or unknown `in_reply_to`, no mailbox,
  unreadable mailbox, or no `in_reply_to` at all → today's refusal, unchanged.

## Daemon

The polling daemon (`daemon.py`) watches inboxes for `auto_execute` dispatch emails and spawns agents automatically. It also runs the AIPASS-TEST token protocol: `scan_and_ack_test_emails()` intercepts ping-test messages and auto-replies with "ack" before dispatch processing.

## Related

- [wake_pipeline.md](wake_pipeline.md)
- [identity_and_boundaries.md](identity_and_boundaries.md)
- [sending_and_delivery.md](sending_and_delivery.md)
- [known_issues.md](known_issues.md)
