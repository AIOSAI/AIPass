# Admin setup

*How the admin lane works, and how to light it on your machine.*

**You probably don't need this.** AIPass runs fine with the admin lane dark —
that's how every fresh install starts. Admin actions simply refuse. Read on only
if you want one agent able to dispatch *any* other agent on this machine.

---

## What admin is

Admin is a single privilege, held by exactly one citizen: **`devpulse`**.

It lets `devpulse` dispatch **any** agent, including manager-class citizens that
would otherwise only be emailed. That's the whole privilege — it is not a
superuser mode, it does not bypass the edit gate, and it grants nothing outside
the dispatch lane.

Three things worth knowing up front:

- **It's per-machine.** The grant is signed with a key that lives outside every
  repo, so cloning AIPass never carries an admin grant with it. Each
  installation lights its own lane, or leaves it dark.
- **It's optional.** A dark lane is a correct, fail-closed install.
- **It's single-seat and bolted to `devpulse`.** `mint` refuses any certificate
  that isn't devpulse's. There is deliberately **no transfer ceremony** — if you
  want a different holder, that's a design conversation, not a command.

---

## The security model in two sentences

**Passports** (`.trinity/passport.json`) are *public profiles* — tracked in git,
readable by anyone, and **not a security layer**. The security layer is the
**birth certificate** (`<branch>/artifacts/birth_certificate.json`) — gitignored,
machine-unique, and for `devpulse` it carries a `privileges` block plus an
HMAC-SHA256 `signature` computed with a key at `~/.aipass/admin_grant.key` that
never leaves the machine and never enters a repo.

So: editing a passport grants nothing, and editing a certificate by hand breaks
its signature loudly rather than quietly succeeding.

---

## Fresh-install state

Every citizen is born with a plain birth certificate — no `privileges` block, no
`signature`. There is no key at `~/.aipass/admin_grant.key`. Every admin action
refuses.

That is the intended default. Only the ceremony below creates an admin.

---

## The ceremony

Run in this order. The owner-only steps must be run by the machine's owner.

| Step | Command | What it does |
|------|---------|--------------|
| 0 | `drone @devpulse admin_grant status` | Show lane state — key, cert, signature, verify |
| 1 | `drone @devpulse admin_grant keygen` | Generate the machine's signing key at `~/.aipass/admin_grant.key` *(owner)* |
| 2 | `drone @devpulse admin_grant mint` | Add + sign the admin privilege block on devpulse's certificate *(owner)* |
| 3 | `drone @spawn grant-admin` | Write `admin: true` onto the devpulse entry of the root registry |
| 4 | `drone @devpulse admin_grant verify` | Run the full 5-leg contract check |

`drone @spawn grant-admin` takes **no branch argument** — admin is a
devpulse-only privilege. It accepts an optional `--registry <path>`; by default
it discovers the registry from the current directory. The flag alone grants
nothing: all five legs below must pass.

### The five legs

`verify` passes only if **all** of these hold. Every refusal is named:

1. **caller** — the verified caller *is* `devpulse` (environment rail only, never a CLI flag)
2. **cert** — read from the path on the *registry entry*, never a caller-supplied path
3. **content** — `owner`, `type`, and `privileges.admin` are all correct
4. **signature** — HMAC-SHA256 over the canonical certificate-minus-signature payload
5. **registry** — the `devpulse` entry carries `admin: true`

A missing key means leg 4 cannot pass, so the lane is dark. That is a refusal,
not a crash.

---

## Revoking

There is no `revoke` verb. The revocation story is the key:

```
drone @devpulse admin_grant keygen --force
```

This regenerates the machine's signing key and **invalidates every existing
signature**, which takes the lane dark until you `mint` again.

---

## Checking state

Two ways, and they answer different questions:

- `aipass doctor` shows an **`admin lane`** row — `lit`, `dark`, or `partial`.
  This reports *presence* only (key file, grant block, signature, registry
  flag). It is informational: a dark lane is never an error.
- `drone @devpulse admin_grant verify` is the **authoritative** answer. It runs
  the real five-leg contract. Only `devpulse` can pass leg 1, so running it as
  another citizen correctly reports `leg1 caller`.

If those two ever disagree, believe `verify` — doctor observes, it does not
adjudicate.

---

## Honest threat model

Every agent on this machine shares one OS user, so a determined local process
could read the signing key. The signature's job is **tamper-evidence and
accident-proofing**, not defence against a compromised host: a JSON field can
change by drift, but forging an HMAC cannot happen by accident and is loud in
any transcript.

---

## Where the code lives

| Piece | Home |
|-------|------|
| Ceremony tooling + reference implementation of the contract | `@devpulse` — `apps/handlers/owner/admin_grant.py` |
| Registry flag ceremony | `@spawn` — `grant-admin` |
| Dispatch-lane enforcement (mirrors the same contract) | `@ai_mail` |
| This doc + the `aipass doctor` row | `@aipass` |

The contract has one home. If you need the definitive behaviour, read
`@devpulse`'s module or ask that branch — don't infer it from here.
