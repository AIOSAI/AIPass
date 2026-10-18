[<- Back to the README](../README.md)

# Sender identity, project boundaries and the registry walk

**Branch** ai_mail · **Code** `apps/handlers/users/branch_detection.py`, `apps/handlers/email/delivery.py`, `apps/handlers/paths.py`, `apps/handlers/users/verified_caller.py`, `apps/handlers/registry/read.py`, `apps/handlers/dispatch/wake.py`, `apps/handlers/email/reply.py`, `apps/handlers/email/contacts.py`, `apps/handlers/__init__.py`

---

## Sender Identity

Branch identity detection runs in `detect_branch_from_pwd()`. It is **not** a flat
waterfall — a fence runs first, and the env-var lane and the walk-up lane are
alternatives, not neighbours.

**0. The identity fence.** `AIPASS_CALLER_CWD` set but standing outside any branch →
refused outright, *unless* `AIPASS_CALLER_IDENTITY_SOURCE` is `assigned` or `passport`.
@drone stamps which kind of evidence named the caller, and a credential travels where a
location does not. `project` — a registry-derived *project* name — answers "which project
am I in", never "who am I", and stays refused: drone standing at the repo root stamps
`aipass` the directory, which spells the same as `@aipass` the citizen. An **absent** `AIPASS_CALLER_CWD` is not contradicting evidence and
leaves everything below untouched — in-process callers depend on that.

**1. `AIPASS_CALLER_BRANCH` is set** → registry lookup by name, **then** contacts, then an
identity synthesized from the env vars alone (recorded `unverified` — no passport, no
registry row).

> **The registry is asked before contacts.** `AIPASS_REGISTRY.json` is the authoritative
> catalog; `contacts.json` is a learned, writable cache, and a poisoned cache row must not
> outrank the catalog for a citizen the catalog knows. An `is_dir()` staleness check
> cannot catch that case: the wrong root is a live branch with a real mailbox. Contacts
> resolve external callers the registry has never heard of.

**2. No `AIPASS_CALLER_BRANCH` at all** → walk up `AIPASS_CALLER_CWD` (or, with no caller
env, this process's `Path.cwd()`) for `.trinity/passport.json`, then registry lookup by
path. The `Path.cwd()` leg is recorded `unverified` deliberately: it is correct for a
dispatched agent standing in its own tree and silently wrong anywhere else.

Every exit is stamped by `_record_resolution()` with the winning strategy and a
confidence, so a wrong sender can be traced to the path that produced it. If all fail,
detection returns `None` and the operation fails loudly. Wrong identity is worse than no
identity.

The `--from @branch` flag on send/email commands provides an explicit sender override for callers outside branch directories.

### Registry Rows Leave the Reader Absolute

**A registry row's `path` is relative to THE REGISTRY THAT HOLDS IT.** Returned raw it
carries no memory of which registry answered, and every consumer then joins it to the
AIPass repo root — right for AIPass citizens by coincidence, wrong for every project
citizen.

`_rooted()` absolutises a row against its own registry at the point of read, in both lanes
of `_lookup_branch_by_name()` and both of `get_branch_info_from_registry()`. Rows already
absolute pass through untouched. It lives at the reader rather than at the call sites
that join a registry path, because a consumer cannot re-derive a root it was never given —
and copies of that join is how they drift.

A row joined to the wrong root does not fail: `projects/baud` + row `src/baud/baud`
joined to the AIPass root names `<aipass>/src/baud/baud`, a path inside the AIPass tree,
and the mail lane would create a mailbox there that belongs to no citizen.

The caller-registry fallback in `_lookup_branch_by_name()` is **not** admin-gated, and is
a different question from the admin-only cross-project sweep above: it resolves a citizen
of the caller's *own* project. It cannot reach @baud from a fleet seat — walking up from a
fleet citizen's `AIPASS_CALLER_CWD` finds `AIPASS_REGISTRY.json` first, which does not
list him.

### Verified-Caller Rail

`--from` and `--sender` are **claims, not credentials**. Both land on
`wake_branch(sender=...)`, and that value is not only a bounce address — a
sender in `PRIVILEGED_SENDERS` unlocks a wake lane, so an unchecked claim would let any
citizen run `dispatch @manager --from @daemon` and wake a manager.

`handlers/users/verified_caller.py` draws the line:

| | claimed identity (`--from` / `--sender`) | verified identity |
|---|---|---|
| source | a CLI string | `AIPASS_CALLER_BRANCH`, else a passport walk up `AIPASS_CALLER_CWD` |
| authors the mail | yes | — |
| gates a privilege | **never** | yes |

- **`resolve_verified_caller()`** — `@branch`, or `""` when unprovable. There is
  deliberately **no `Path.cwd()` fallback**: drone runs a routed module with
  `cwd=<target branch>` and a dispatched agent with `cwd=<its own tree>`, so this
  process's directory says nothing about who called.
- **`sender_claim_refusal(claimed)`** — a reason string when the claim is
  privilege-bearing and doesn't match the verified caller (including when there
  is no caller to match: unprovable is refused, not assumed). Refusal happens
  **before the send**, so a spoof attempt leaves no delivered email behind, and
  exits `2`.
- **`resolve_wake_sender(claimed)`** — verified caller first, the claim only as a
  fallback, which the refusal has already guaranteed is not privilege-bearing.
  So `--from @spawn` from @seedgo's seat still authors the mail as `@spawn` while
  the wake — and therefore wake-back — is attributed to `@seedgo`.
- **`PRIVILEGED_SENDERS`** lives at the boundary that enforces it, because
  `wake_branch` cannot: its in-process callers (@daemon's `run.py`) have no
  caller env and are trusted by import instead. A test scans `wake.py` for
  `sender == "@x"` gates and fails if one is missing from the set.

### A Credential Is Not an Ambiguity

`_record_resolution()` warns when `AIPASS_CALLER_BRANCH` and `AIPASS_CALLER_CWD`
name different branches — the one disagreement visible from inside this process.
It logs that at **debug** when the env var carries a credential provenance
(`assigned` / `passport`) *and* actually resolved against a catalog.

A credential travels and a location does not: an agent that cds into another
branch is still itself. So `assigned` naming one branch while the cwd sits in
another is the designed precedence working, not a conflict, and a warning that fires on
the known-good case buries the one it exists for.

Three cases deliberately keep the warning, because none is proven good:

| Case | Why it stays loud |
|---|---|
| provenance `project` | a registry-derived **directory** name — @aipass the directory and @aipass the citizen spell the same |
| provenance missing / `unknown` | unprovable is not proven; this lane fails toward noise, not silence |
| resolved via `caller_branch:synthesized` | the name resolved against nothing — provenance says who *stamped* it, never that anything vouched for it |

### Address Derivation Hazard

A branch with no explicit `email` field in the registry gets one derived by
`registry/read.py:_derive_email_from_branch_name()`, which splits the name and
keeps **one token**:

| Branch name | Rule | Address |
|---|---|---|
| `AIPASS.admin` | after the dot | `@admin` |
| `Glass House` | first word | `@glass` |
| `AIPASS-HELP` | after the hyphen (AIPASS prefix only) | `@help` |
| `flight-deck` | before the hyphen | `@flight` |

So a multi-word branch name silently loses everything after the first token, and
resolution downstream is exact-match (`delivery.py`, `contacts.py`) with no fuzzy
or prefix fallback anywhere — a truncated address never self-corrects, it just
fails to route. **Set an explicit `email` in the registry for any branch whose
name contains a space, dot or hyphen.**

## Cross-Project Email

External projects (outside the AIPass repo) can send to AIPass branches. On delivery, `delivery.py` stores a `reply_path` on the message (the sender's `inbox.json` path, resolved from `AIPASS_CALLER_CWD`). Replies use `_deliver_via_reply_path()` to write directly to the external inbox without needing registry lookup.

The contacts system (`contacts.py`) maintains an address book at `.ai_mail.local/contacts.json`, auto-registering branches on every send/receive. This enables fast sender detection for known branches without CWD walking or registry lookups.

### Waking a citizen outside this repo — the external tier

`wake.resolve_branch()` checks four sources, in strict precedence. **Local always wins:** the first three all resolve inside AIPass home, and only the fourth leaves it.

| # | Source | Gated by |
|---|---|---|
| 1 | `AIPASS_REGISTRY.json` — core branches | — |
| 2 | The caller's project registry, via `AIPASS_CALLER_CWD` | — |
| 3 | The `projects/*` sweep — the cross-project bridge | verified admin only |
| 4 | The declared-roots **external tier** | — (declaration is the credential) |

Step 4 consumes @memory's public gateway, `aipass.memory.apps.modules.fleet.external_branches()`, which reads the machine anchor `AIPASS_ROOTS.json` at AIPass home. Nothing here re-reads that file — one anchor, one reader. No anchor means no external roots, which is the ordinary state of a fresh clone, and resolution then uses the first three sources only.

There is no admin gate on step 4: @daemon fires scheduled wakes unverified, and the anchor is a machine-managed file the owner blessed, so an external root is already an authorised destination. The admin sweep keeps its position *above* the tier — moving it below would let a sibling repo shadow a citizen living in our own `projects/`.

**Collisions break by declaration order, and are logged anyway.** When two declared roots claim one address, the first-*declared* root wins and an error line names every losing claimant. The order is @memory's gateway's; this branch never re-reads the anchor to derive it. A correct tie-break does not make a collision expected, so the error line stays.

### Mailing a citizen outside this repo — the last wall (#754)

Delivery reads the same external tier, last. Once it answers, the address map refuses nothing, so `_check_cross_project_boundary()` is the only wall left — and only the resolver knows which tier answered, so it passes `external_tier=True` rather than the check re-deriving it.

A sender that cannot be placed in a project — no `AIPASS_CALLER_CWD` (drone omits it when it cannot read the cwd; @trigger's in-process sends never carry one), or a cwd with no registry above it — is **refused** for an external-tier recipient, and the reason names the wall. The same sender to a fleet branch still lands, so @trigger's mail to owners is untouched. The verified-admin grant still crosses, checked last. A reply stamp does not: a reply's proof only counts inside the sender's own project, and with none a stamped `reply_path` could name any mailbox on disk.

## The Handlers Fence

`apps/handlers/__init__.py` is an import-time fence: code outside this branch reaches
the handlers through `apps/modules`, and a foreign importer gets an `ImportError` naming
the caller, the file and the line. It reads the stack once, at the first import of the
package, and sorts each frame into one of three kinds:

| Kind | Frames |
|---|---|
| kin | a file under this branch's root |
| transport | importlib and the frozen bootstrap, the standard library (`unittest.mock`, `pkgutil`, `runpy`), third-party code under `site-packages` |
| foreign | everything else — another branch, a project, a script |

The first foreign frame decides. It is refused when no kin frame stands between it and
the fence, or when its own source line names these handlers; it is allowed when kin code
asked for the import on its behalf. `apps/__init__.py` imports nothing, so the importer
the fence sees is the real one.

**No filesystem at import.** The walk uses `sys._getframe` (`co_filename` is already a
string) and `linecache` for the import line, never `inspect.stack()`: on Windows
`inspect` reaches `ntpath.realpath`, which calls `os.getcwd()` unconditionally, so a
handler import would need a readable cwd. A pseudo filename (`<frozen ...>`, `<string>`)
is never resolved — relative, it would resolve against the cwd and read as kin — and
every `Path.resolve()` falls back to the raw spelling on `OSError`.
`tests/test_handlers_fence.py` pins the fence.

**A limit.** The fence fires on the first import in a process. Once kin code has
imported the package, a later foreign import is served from `sys.modules`. The write-time
rule (`drone @seedgo audit`: handlers and encapsulation) is the wall.

## Registry Globs Are Re-Checked in Python

`pathlib` delegates glob matching to the filesystem, so on Windows and default
macOS `*_REGISTRY.json` **also matches** `*_registry.json`. This repo is full of
bait: `drone_command_registry.json` sits directly beside drone's tree, every branch
carries `.spawn/.template_registry.json` (pathlib `*` matches dotfiles, unlike the
`glob` module), and @flow keeps `flow_json/*_registry.json` plan counters.

**Every registry walk in this branch goes through `paths.registries_in()`.** The
glob still does the walking — only the filesystem knows where files are — but it
is not trusted with the *answer*: the name is compared again in Python with
`str.endswith(REGISTRY_SUFFIX)`, where case means what it says. Refusals are
logged, so on Windows there is a record that the filesystem returned something the
pattern never asked for.

**Suffix, never the stem.** External projects name registries after themselves —
`Vera-Studio_REGISTRY.json`, `vera_studio_REGISTRY.json`, `feel_good_app_REGISTRY.json`.
A filter keyed on the stem would refuse real citizens along with the counter files, so
all three spellings are pinned as must-survive.

| Site | What it decides | Reached via |
|---|---|---|
| `paths.find_project_root` | which project this is, for the delivery fence | walk up |
| `users/branch_detection._find_caller_registry` | which registry names the caller | walk up |
| `email/reply._validate_reply_path` | may a reply leave toward this inbox | ancestors |
| `registry/read.resident_registry_paths` | the resident roster | `projects/*/` |
| `registry/read.get_project_tree_branches` | the verified-admin bridge roster | `projects/*/` |
| `registry/read.get_caller_project_branches` | the caller's citizens | walk up |
| `email/delivery._project_name` | the project a delivered mail's feed event names | the project root |

Unfiltered, a counter file would end a walk-up (the walk-up sites stop at the first
registry they meet, so a genuine external caller resolves to nothing), would make
`find_project_root` answer a branch directory as a project root and change the
cross-project fence's answer, and, given a `branches` key, would name citizens.

**The ban is structural.** `test_registry_case_sweep.py` AST-walks `apps/` and
fails on any `.glob()`/`.rglob()` reaching for a registry pattern outside the one
reader — a **named constant** as well as a literal.


## Related

- [wake_lanes.md](wake_lanes.md)
