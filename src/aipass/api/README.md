[← Back to AIPass](../../../README.md)

# API

> Centralized external API gateway — authenticated service clients for all external APIs

**Module:** `aipass.api` | **Role:** `api_gateway`
**Seedgo:** 99% (42/44 at 100%) | **Tests:** 1298 pass | **Functions:** 201 public (179 tested)
**Last Updated:** 2026-08-17

*The two categories under 100% are both in the host lane and both known:
`server.py`'s attach route is genuinely deeply nested (a PTY pump inside a
WebSocket handler inside the app factory), and `settings.py` is in-flight work
carrying three silent catches. Neither is bypassed — a bypass would hide them.*

---

## Invoke

```bash
drone @api <command> [args]
```

---

## Quick Start

```bash
# Validate your API key
drone @api validate

# Test the connection
drone @api test

# List available models
drone @api models

# Make an API call
drone @api call "Hello, world" --model anthropic/claude-3.5-sonnet

# Check usage stats
drone @api stats
```

---

## Commands

| Command | Description |
|---|---|
| `get-key [provider]` | Retrieve API key (default: openrouter) |
| `validate [provider]` | Validate API key (default: openrouter) |
| `validate google` | Validate Google OAuth2 credentials |
| `reauth google` | Re-authenticate Google OAuth2 |
| `get-secret <provider/slug> [--out FILE] [--json] [--list]` | Secret access (masked summary; --out writes to file) |
| `list-providers` | List available API providers |
| `init` | Initialize .env template at ~/.secrets/aipass/ |
| `test` | Test OpenRouter connection status |
| `models [--all]` | List available models (default: top 10) |
| `status` | Check OpenRouter client status (key, SDK, cache) |
| `call "prompt" --model MODEL` | Make API call to model |
| `track <gen_id> [caller]` | Track API usage for a generation |
| `stats` | Display overall usage statistics |
| `session` | Show current session usage |
| `caller-usage <caller>` | Show usage by caller module |
| `cleanup [days]` | Clean up data older than N days (default: 30) |
| `integrations list` | List registered contracts |
| `integrations call <contract> [args...]` | Call a registered contract |
| `host-api serve [--host IP] [--port N]` | Run the host API (binds the configured address or refuses) |
| `host-api issue-token <label> --out FILE` | Mint a bearer token (raw value never printed) |
| `host-api list-tokens` | List tokens — values are never shown |
| `host-api revoke-token <id>` | Revoke server-side, effective next request |
| `host-api config` / `set-config` | Show / set the bind address (validated first) |

---

## Architecture

```
api/
├── apps/
│   ├── api.py                         # Entry point — module discovery, command routing
│   ├── modules/                       # Orchestration layer (9 modules)
│   │   ├── api_key.py                 # Key retrieval, validation, provider listing
│   │   ├── secrets.py                 # Cross-branch secrets door (in-process API)
│   │   ├── openrouter_client.py       # OpenRouter client — calls, models, status
│   │   ├── google_client.py           # Google API services (Drive, Calendar, etc.)
│   │   ├── host_api.py                # Host API — server lifecycle, token admin
│   │   ├── usage_tracker.py           # Usage metrics — track, stats, cleanup
│   │   ├── bridge.py                  # Generic contract registry (register/resolve)
│   │   ├── integrations_manager.py    # Contract dispatch — integrations list/call
│   │   └── registry.py               # Driver auto-discovery (load_drivers)
│   ├── handlers/                      # Business logic (9 packages, 35 files)
│   │   ├── auth/env.py, keys.py, secrets.py
│   │   ├── config/provider.py
│   │   ├── google/auth.py, service_factory.py, retry.py
│   │   ├── host/config.py, tokens.py, server.py, feed.py, reads.py, fleet.py, face.py, verbs.py, attach.py, uploads.py
│   │   ├── integrations/list.py, call.py
│   │   ├── json/json_handler.py
│   │   ├── openrouter/caller.py, client.py, models.py, provision.py
│   │   └── usage/aggregation.py, cleanup.py, tracking.py
│   └── integrations/                  # Private driver space (gitignored)
│       └── {project}/driver.py
└── tests/                             # 1240 test functions across 43 files
```

Three-tier: entry point routes to modules (orchestration), modules delegate to handlers (business logic). Modules auto-discovered from `apps/modules/*.py` via `handle_command()`.

---

## Cross-Branch API

```python
from aipass.api.apps.modules.openrouter_client import get_response
response = get_response(prompt="...", model="anthropic/claude-3.5-sonnet", caller="flow")

from aipass.api.apps.modules.google_client import get_drive_service
service = get_drive_service()                   # Single-threaded
service = get_drive_service(thread_safe=True)   # For concurrent workers

from aipass.api.apps.modules.google_client import get_google_service
service = get_google_service("calendar", "v3")

from aipass.api.apps.modules.secrets import get_secret, set_secret, list_secrets
token = get_secret("telegram", "bot")               # Returns bot_token string
config = get_secret("telegram", "bot", as_json=True) # Returns full dict
set_secret("telegram", "newbot", cfg, as_json=True)  # Writes ~/.secrets/aipass/telegram/newbot.json
slugs = list_secrets("telegram")                     # Returns ["bot", "newbot", ...]
# Values never reach stdout — use the Python API above for programmatic access
```

---

## Integration Points

**Depends On:**
- `aipass.prax` — structured logging via `system_logger`
- `aipass.cli` — Rich console output formatting

**Provides To:**
- All branches — authenticated API clients (`get_response()`, `get_drive_service()`, `get_google_service()`)
- System-wide API key management and credential validation

**Credentials** (`~/.secrets/aipass/`, 0o700 dir, 0o600 files):
- `.env` — API keys (OpenRouter, etc.)
- `google_creds.json` — Google OAuth2 tokens
- `google_client_secret.json` — Google OAuth app config

---

## Host API — Stage 0 (FPLAN-0411)

The server the BAUD phone face talks to. **Bound to the tailnet since 2026-08-14**,
after the Phase 5 security review — the first network-listening service in AIPass.

```bash
drone @api host-api issue-token pixel-8 --scope read --out ~/pixel.token
drone @api host-api serve              # binds the configured address
drone @api host-api set-config --host <ip>   # validated before it is stored
drone @api host-api revoke-token <id>  # effective next request, no restart
```

**Two auth layers** (neither trusted alone): the tailnet boundary, plus a bearer
token stored as a sha256 hash under `~/.secrets/aipass/host_api/`. Revocation is
a server-side file edit — a phone that keeps its token forever is inert once the
host stops honouring it. Refused requests are audited with the peer address, so
"which device has been knocking" has an answer.

**A revoked token and an unknown one answer identically — and are logged
differently.** Both get the same 401 and the same sentence, because a response
that distinguished them would let a prober learn which of its guesses was once
real. The trail records `token_revoked` (with the token's id) or
`token_unrecognised` (with none). This was one line of aspiration in a comment
until 2026-08-16, when Patrick's phone was refused for nine minutes and the log
could not say whether it had presented a credential this host once issued or
garbage — the store was provably intact, so that missing distinction *was* the
gap between the evidence and an answer.

**The store answers three questions about every credential**, added after an
operate-scoped token appeared on this machine and nobody could say who minted it:
`minted_by` (best-effort, from the branch drone names in the child environment —
**provenance, never permission**, since the value comes from the caller's own
environment), `revoked_at`, and `last_used`, which separates a live token from one
that is merely un-revoked. `drone @api host-api list-tokens` prints all three, so
the question can be answered where it actually gets asked.

`last_used` means a write on every authenticated request, so the store is written
atomically (temp file, `fsync`, `os.replace`, created `0o600` rather than
chmod'd after) behind a cross-platform lock with stale-lock breaking. Two rules
hold it together: **telemetry never undoes security** — the touch re-reads inside
the lock, so a stale record list can never write a revoked token back to life, and
a lock it cannot take means the timestamp is dropped, never raised — and writes
are coalesced to one per minute per token, so feed polling does not rewrite the
store every few seconds. The envelope is versioned; records predating the fields
still verify, and read back as `unknown`.

**The bind rule:** the server binds the address it was configured for or refuses
to start. No fallback, ever. Wildcards (`0.0.0.0`, `::`), hostnames, and addresses
this machine does not hold are all refused — and those refusals are **independent
of the loopback flag**, so opening the server to one real address never opens it
to every address. Anything beyond the tailnet is a standing NO-GO: that needs TLS,
which this server does not have (confidentiality on the wire is WireGuard's).

**Endpoints live today:**

| Endpoint | Scope | Notes |
|---|---|---|
| `GET /v1/ping` | none | 204, no body — separates "tunnel down" from "token bad" |
| `GET /v1/whoami` | read | Enrollment check; returns only what the caller already holds |
| `GET /v1/feed?since=&limit=` | read | Cursor is a **timestamp**, clamped both ends, `gap` flagged |
| `GET /v1/files?branch=&file=&project=` | read | Branch by NAME, file relative to it; 512KB cap **refuses**, never trims. Any project |
| `GET /v1/dir?branch=&dir=&project=` | read | One directory level, the phone's file browser. Any project |
| `GET /v1/diff?branch=&staged=&project=&path=&grain=&ref=` | read | One patch, through `drone @git`, never raw. `path` = ONE file (refused, not trimmed, over 512KB); `grain` = `branch`\|`repo`; `ref` = a commit. Any project |
| `GET /v1/git-changes?branch=&project=&grain=` | read | Changed files. `branch` grain (default) = @baud's desktop card contract; `repo` grain = the whole repository. The answer names its grain. `rows[]` carries git's own two-column code per path, untracked included **by name** |
| `GET /v1/git-log?branch=&project=&limit=` | read | Recent commits — sha + subject. **Always repo grain.** `limit` 1–50, outside is refused, never clamped |
| `GET /v1/commit?branch=&ref=&project=` | read | One commit: author, date, subject, message, files with ± counts. Its patch rides on `/v1/diff` |
| `GET /v1/git-remote?branch=&project=` | read | The repository's remote, for link-cards out to the forge. `url` as configured (password redacted), `web` browsable or `null`, `remote` names which one answered |
| `GET /v1/fleet?project=` | read | @baud's snapshot envelope, unchanged. `project` is case-sensitive |
| `GET /v1/rooms?project=` | read | A filter over that same snapshot — never a room judgment of its own |
| `GET /v1/projects` | read | @baud's project census — the switcher menu's rows, unchanged |
| `GET /v1/roster` | read | Every working agent in **every** project. Takes no parameters — any is a 400, never a silent drop |
| `GET /v1/memory-config?branch=` | read | @memory's limits. No branch = the fleet view; a branch = that one |
| `POST /v1/memory-config/set` | operate | `{branch, type, count}` — one branch's override. 1–100 |
| `POST /v1/memory-config/set-default` | operate | `{type, count}` — the default only. **Does not reach any branch** |
| `POST /v1/memory-config/push` | operate | Empty body. What actually delivers a default everywhere |
| `POST /v1/verbs/wake` | operate | `{branch, project, message?, fresh?}` → `@ai_mail dispatch wake` |
| `POST /v1/verbs/kill` | operate | `{branch, project}` → `baud --end-room`. Returns `room` and `ended` |
| `POST /v1/verbs/lock` | operate | Empty body. Proxied to `@skills`' screen_lock. Never gated |
| `GET /v1/agent-settings?branch=` | read | One branch's three owned claude settings — an absent key reads `null` |
| `POST /v1/agent-settings` | operate | Patch those three. Three-state by JSON's nature: absent touches nothing, `null` removes, a value sets |
| `GET /v1/baud-settings` | read | BAUD's own document for the seat, whole and opaque |
| `POST /v1/baud-settings` | operate | Shallow-merge into it — `null` removes, a nested object replaces |
| `GET /v1/hooks-sound` | read | @hooks' mute switch, read live — the flag file is the only truth |
| `POST /v1/hooks-sound` | operate | Flip machine-wide hook sounds. Idempotent both directions |
| `POST /v1/files/upload` | operate | Multipart image. The SERVER names the file; returns its absolute path |
| `WS /v1/room/attach?branch=&project=&kind=` | operate\* | A real PTY. Bearer on the subprotocol. `kind=watch` is **read** scope; a watch with **no branch** is global mission control |
| `GET /` | none | @baud's phone face, served from this same origin |

**Verbs answer `{ok, detail}` at 200, and the line matters:** `ok: false` means the
mechanism **ran and said no**, with the owning branch's own sentence in `detail`
(the phone renders it verbatim, because a sentence beats a status word). If the
mechanism was never reached — seam missing, door unreachable — that is a status
code, not an `ok`. A wake refused by @ai_mail's blocklist is `200 {ok: false}`;
a kill whose seam does not exist is 503.

**The memory-config lane reads a document, not a screen.** It shipped scraping
@memory's rendered text, because their config verbs had no machine surface — the
most fragile handler in this branch, where a heading they reworded was a field it
lost. It asked them for one; they shipped `--json` on all five verbs the same
evening. The scraper is gone: nothing here reads a glyph, a marker or a column
position, every command is sent with `--json` appended in **one** place, and the
verdict is the `ok` boolean they emit. `raw` still rides on every response —
their payload verbatim — so a caller is never trapped behind my reading of it.

Two of their conventions remain load-bearing: their refusals **exit 0**, so the
exit code is still never the verdict here; and `set-default` **changes only the
default** — until `push` runs, all 17 branches keep their existing values. That
surprise is @memory's design and is passed through untouched. It is now also
*reported* rather than remembered: `pushed` comes from their payload, as does
the `branches` count a push answers with. This lane used to hardcode
`pushed: false`, which was a fact about their branch pinned in mine.

**What is not one parseable object is `503`, never a verdict.** If `--json` ever
stops being honoured — an older @memory on a fresh clone, a renamed flag, a
banner ahead of the payload — this lane gets prose back and says it could not
tell. After a write that is the honest answer, and a `200` would be a guess about
Patrick's configuration.

**A refusal has one shape on this lane, wherever it was decided:** `400
memory_config_refused`, their sentence in `message`, their remedy line in
`suggestion` (present and `null` where there is none), their whole payload in
`raw`. It shipped with two — an argument this server rejected before routing was
a 400, while a refusal @memory *spoke* came back `200 {ok: false}` — so a client
had to check the status code **and** a flag to learn one fact. @baud found it
reading the handler, devpulse confirmed it on the wire, and both now answer
identically. Note this is deliberately **not** the verb lane's rule below: a
refused wake is a normal outcome of asking and the phone renders it, but a
refused write to fleet configuration is a caller error.

**The git-changes lane answers @baud's question, not a second one.** The
AgentSheet git tile had never made a network request — the phone transport
listed `git_changes` in its not-yet table and threw before reaching the wire.
The contract is theirs, read from their tree rather than invented here:
`GitChanges { files, count }`, filled by `git diff HEAD --relative --name-only
-- .`. Two consequences are reproduced deliberately. **Tracked files only** — a
brand-new module does not move a card's badge, because `diff HEAD` cannot see a
file git has never seen; counting it here would make the phone disagree with the
desktop about the same branch at the same moment, with the phone being wrong.
And **branch-local names**, because every `src/aipass` branch shares one repo and
a repo-relative row would push the part that differs off a phone screen.
Verified against a real branch: 14 files, identical to their command's own
output, name for name.

`untracked` rides alongside as a separate count, never folded into theirs.
Matching a contract is not a reason to discard something already measured —
@baud's own argument for their whole-project total is that a count hiding a new
module reads as false calm, and that does not stop being true here.

**This lane reads a rendered surface, and says so.** Git is drone-only, servers
included, so it shells `drone @git status` and reads the porcelain codes drone
passes through verbatim — keyed on that structure, never on the prose drone
frames the list with. drone already has `get_branch_status()` returning
`{ok, files, total}`, but only under `apps/handlers`, not on its public package
surface, and reaching into another branch's internals is the layering mistake
this package has made once already. A `--json` on `drone @git status`, or that
function published, retires every line of the parsing. It has been asked for.

**It serves foreign projects, and a wrong belief here hid a real bug.** This
section previously said no drone-routed lane could measure a foreign project:
drone verifies its caller by finding a passport in the cwd hierarchy, and a
refusal had been measured in `projects/baud/src/baud`. @baud's live sweep then
served five foreign projects with real data. The reconciliation is that the
probe path was never a census-known **branch** — the registered one sits a level
deeper and, like every census branch, carries its own passport, so the caller
check passes. The command measurement was true; the inference from it to the
route was not. What remains true is narrower: drone cannot be invoked *from* a
cwd with no passport above it, which affects agents working inside external
trees, not this lane.

The bug that belief concealed: paths were stripped against **the seat's** repo
root, so a foreign branch fell out of `relative_to` and its rows kept the prefix
drone printed — `src/vera_studio/vera/CLAUDE.md` where the contract says
`CLAUDE.md`. Nested tenants were wrong the same way and worse: `projects/baud`
carries its own `.git`, so the seat-relative prefix *resolves cleanly* and is
still the wrong one — nothing raises, and every row silently keeps its prefix.
The prefix is now the repository **discovered** by walking up for a `.git`
marker, which is the only one guaranteed to match what was printed; the seat is
a fallback. Verified against a real foreign tree: 7 files, identical to @baud's
own command. Two mutations — restoring seat-first, and requiring the marker to
be a directory rather than the file a worktree carries — survived the suite
before the tests that now catch them.

A genuinely unreachable project still refuses honestly: a non-git one answers
`503` with git's own sentence, *not a git repository*. An empty change list
would paint it clean when nothing was measured.

### The git surface (DPLAN-0303)

Patrick, on the phone's git screen: *"git diffs are pretty much useless. we need
a real diff setup."* The wall of text was one 308KB response. Tapping one file
in the same repository is now 5.8KB — **53× less**, measured on a real tree.

**Two grains, and every answer names its own.** The card's git tile is per-branch;
the git *app* is per-repository (Patrick's ruling, 08-17). Both are honest and
they are not the same number, so `grain` is a parameter *and* a response field —
a file list that does not state its scope is one a client can silently read at
the wrong one. `grain=branch` keeps @baud's card contract untouched, including
its branch-local names. `grain=repo` reaches every branch in the repository and
**keeps the repo-relative names**, because there the prefix *is* the part that
distinguishes one branch's file from another's. A typo'd grain is refused naming
both, before any subprocess exists — falling back to a scope nobody asked for is
how a phone shows one branch while believing it shows a repository.

**A commit is always repo-wide, and the answer says so rather than obeying.**
Asking `/v1/git-log` or a `ref` for branch grain is *refused*, not silently
ignored: drone's log door runs from the repo root with no pathspec, so a branch
names *which repository*, never which history. Silently ignoring a parameter is
a lie told by omission.

**Two doors were measured shut, and neither is worked around in silence:**

- **`drone @git diff` takes no path and no `-U`.** `_handle_diff` recognises
  exactly `--staged` and `--all`; everything else in argv is ignored, the same
  trap as `status --json`. So `path` is served by generating the patch and
  splitting it here, on the per-file headers — machine structure, the same
  doctrine that keeps the status parser off drone's prose. The consequence
  DPLAN-0303 needs to know: **context stays at three lines, not the `-U1` the
  design specified**, because context is baked in at generation time. Asked of
  @drone.
- **`drone @git log` is `--oneline`.** A row carries a sha and a subject and
  nothing else — no author, no relative date, however much a design asks for
  them. Those live in `show`, one commit at a time, and fifty subprocesses each
  dragging a whole patch is not a list lane. `/v1/git-log` ships what exists;
  `/v1/commit` carries the author and date for the one commit being looked at.
  Asked of @drone.

**The 512KB cap changes meaning per file, deliberately.** The whole-tree case
still truncates and *reports* it, because a wall of text degrades into a shorter
wall. One file cannot: half a patch is not a small patch, it is a severed hunk
that renders as nonsense, so an over-cap single file is **refused** with its
size and the cap in words. A file with no changes in the patch is likewise
refused naming it — an empty string would read as "no changes, rendered fine",
and a tap on a stale list is a real event.

**± counts come from inside the hunks only.** The two file-header lines start
with the same characters as a changed line; counting them adds one phantom
addition and one phantom deletion to *every file in every commit*. Verified
against `git show --numstat` on a real 20-file commit: **20 of 20 rows
identical**. The same ordering rule protects filenames — a block's header is
emitted before its first hunk, so a deletion of a line reading `-- x` (which
produces exactly `--- x`) can never be read as the file's name. A guard at the
hunk boundary was written for that and then **deleted**: no mutation could kill
it, which is what proved it unreachable rather than careful.

**Status rides per row, in git's vocabulary and not a new one.** @devpulse
measured the gap from the face while this was building: the lane read the
porcelain code and then *discarded* it, and untracked files never left the server
as anything but a number. So of the four VS Code chips (M/A/D/U) only two were
derivable, and a staged-new file was indistinguishable from a modified one.
`rows[]` now carries every changed path with its code **verbatim and unstripped**
— the two columns are index-then-worktree, so `A ` (staged new) and ` M`
(modified, unstaged) stay two different answers instead of collapsing into one
letter. Which code means which chip is the face's decision, made once in their
`buildRows`; a letter invented here would be a second vocabulary for a fact git
has already stated. Untracked paths appear in `rows` by name and stay **out** of
`files` and `count` — additive, so @baud's desktop consumer parses exactly what
it always did, and untracked names leaking into the tracked list is the precise
disagreement this lane exists to avoid. Ignored paths are in no list at all.

### The remote lane (DPLAN-0303 phase 4)

Phase 4 goes links-first — zero-auth link-cards out to GitHub, built from
constructible URLs — so the face has to be told the repository's remote.

**There is no door for this, and that was measured before anything was designed.**
Not a verb on drone's git surface. Not on drone's public Python surface (checked
directly — the module exports branch resolution and routing, nothing about
configuration). And the fleet's own gate refuses **both** raw readers: neither is
in its read-only allowlist, which is the fleet declining to call them reads. So
this lane **shells nothing at all** and reads the repository's configuration as
the INI file it is. That leaves the drone-only rule this file documents intact
instead of quietly carving an exception into it for one lane — a test asserts no
subprocess is ever spawned here, so a future one would be a decision somebody has
to make on purpose. A verb on drone retires every line of it, and it has been
asked for.

**Two fields because they are two facts.** `url` is what was configured,
verbatim; `web` is what a browser can open. Collapsing them would make the lane
lie about one of the two. `web` drops the clone suffix, because `/pulls` appended
to a URL ending in `.git` is a 404 on every forge there is; the ssh forms
(scp-short, `ssh://`, `git://`) convert to `https` because they have no browsable
shape of their own, while **`http` is left exactly as configured** — upgrading it
would be this lane deciding something about a host it cannot know. A
filesystem-path remote gets `web: null`, since a directory is not a page. The
trap in that parsing: a Windows path carries a colon exactly like `host:path`, so
both halves are checked — reading `C:\repos\thing` as a remote would emit a link
card pointing at a machine named C.

**Which remote answered is part of the answer.** `origin` wins by convention when
several exist, but the `remote` field travels either way — refusing a repository
that simply named its remote something else would be inventing a rule that does
not exist, and choosing silently would hide the choice from the caller.

**A repository with no remote is refused in words, and that is not hypothetical:
two projects in the real tree have none.** Verified live against the real
Sentinel repo, which answers `400 read_refused` with the sentence. An empty
string would render as a link card pointing nowhere.

**Credentials never travel, which was not in the ask.** A remote URL may carry
`user:token@` — that is how a machine clones a private repository with no human
present — and this lane's entire job is handing that URL to a client over a
network. The password half is replaced and the user half survives, so an operator
still recognises their own configuration, and `redacted` is what stops the change
being silent. The browsable form carries no userinfo at all. A bare `git@` is the
standard ssh user and is **not** flagged: an alarm that fires on the commonest
remote form there is would be an alarm nobody reads. The URL also never reaches
an audit line — the log records which remote answered and whether redaction
fired, and nothing else.

Verified live: the seat and a foreign project (`AIPL`, resolved through @baud's
census) both return their GitHub URLs; Sentinel refuses; eight mutations against
this lane all bite. One of those eight first appeared to survive — its anchor had
not matched, so the mutation never applied and the green run proved nothing. It
was re-run properly before being counted.

Sixteen mutations were run against the finished lanes and all sixteen bite,
`PYTHONDONTWRITEBYTECODE` set so a same-length mutation cannot serve a stale
`.pyc`. Live-verified end to end: repo grain identical to raw porcelain **path
and code**, 15 of 15; log shas identical to raw; one file of one commit carrying
no commit header; and an untracked probe file arriving named with `??` at both
grains while staying out of the tracked list. One probe first came back invisible
and the cause was checked rather than assumed — `.tmp` is gitignored here, so the
lane was right to drop it.

**The one sentence this lane writes itself** is a write's `detail`. @memory's
refusals carry prose and it travels verbatim; their success payloads carry facts
and no prose, so `detail` is composed here out of the values *they just
returned* — never out of the values sent to them. A `detail` field on their side
retires it, and has been asked for.

**Every error answers `{"error": {"code", "message"}}` — including the ones this
server does not raise.** Validation fires in *front* of every handler, so it used
to emit FastAPI's own `{"detail": [...]}` and a client coding to the documented
shape lost the sentence on every validation error, on every route. @baud found it
the way these things get found: Patrick's phone read "HTTP 422" while that same
response body named the exact field. Validation is now normalised into the
envelope — `{"code": "invalid_request", "message": "image: Field required",
"fields": [...]}` — with the structured original kept beside the sentence, so the
envelope got wider and nothing was taken away.

**Browsing is free; the terminal binds to the seat.** Every READ route serves
any project @baud's census knows — `files`, `dir`, `diff`, and the fleet routes
that already did. This lane used to refuse anything but the seated project, so
`/v1/fleet?project=BAUD` painted the cards and then every file under them
refused with *"This server is seated in AIPass and does not serve project
BAUD"* — one surface answering two different questions about the same project.
Patrick's ruling, 2026-08-16: *"I should be able to open another project via the
project tab drop down, and view other agent project files, open any passport and
view watch read files. no restriction."* **Operate routes are untouched by this**
— attach is the only takeover, and it still binds to the seat.

The seat stays the default *and the fast path*: an omitted `project`, or the
seat's own name in any case, resolves through the local citizen registry with no
subprocess. Anything else resolves through @baud's census, which is where the
branch's real path comes from — this server never composes a filesystem path for
a project it is not seated in. A foreign project name travels **verbatim**, so
their census keeps the one ruling on how a name is matched (which means it is
case-sensitive there, while the seat is not — see the note on the verb lane
below for the third variant, and no, those three have not been reconciled).
The per-branch name fence is unchanged: free browsing is free browsing of
*branches*, not of the disk.

**`project` travels on every verb that names a target, and is never inferred**
from this server's seat — @baud's rule, paid for with a killed session: a room
name resolved against the wrong project names a *different* room. Deliberately
stricter than the read lane, where an omitted project means the seated one.
The seat is still matched case-insensitively; the wire says `AIPASS`, the
directory says `AIPass`, and a case-sensitive check would refuse every verb the
phone sends.

**The verbs reach any project too — one terminal, any agent.** Patrick's ruling,
2026-08-16: *"the flow is ONE terminal; it hosts the agent I choose, no matter
where I spawn it… Baud is an aipass tenant in `projects/`, vera is outside,
external - that should NOT matter. When you block you create friction."* So the
seat check is gone from `wake` and `kill`, and a foreign branch resolves through
the **read lane's** resolver — one implementation of where a branch lives, which
the operate lane inherited rather than copying. **Attach already did this**: its
external door shipped with the attach train, so that half was a set of regression
pins, not a fix. `lock` has no project at all — it locks *this* machine.

**Requiring the project got MORE important, not less.** When only one project
could be meant, an inferred seat was sloppy; now that any project can be meant,
an inferred one silently names a different room. The ruling widens *who* can be
reached and never *what a request may contain* — operate scope everywhere,
garbage refused before any spawn, unknown branch or project refused in the
census's own words, per-branch path fences untouched.

**The verb lane owns no mechanism.** `verbs.py` imports no subprocess machinery
at all, so it *cannot* run a program — every verb reaches its mechanism through a
door the owning branch published, and there is no path by which this server grows
its own copy of somebody else's verb on a night when a seam is missing.

**`admin` is unreachable, not merely unset.** `wake_branch()` takes an `admin`
keyword its own docstring calls "an ALREADY-DECIDED verdict" from a caller that
ran a five-leg grant check. A phone cannot run that check. Hardcoding `False`
would hold until someone edited the line; routing through `drone @ai_mail
dispatch wake` holds structurally, because that command parses `--fresh`,
`--sender` and `--model` and nothing else. `--sender` is never forwarded either
(it reaches a privilege-bearing parameter behind a verified-caller check), and
`--model` never exists — the phone contract carries zero vendor words by ruling.

**Kill goes through the one door, and the gate is why.** For one day this verb
answered 503 naming a seam that did not exist: @baud's binary opted into headless
mode for `--snapshot` and nothing else, and `tmux kill-session` was one line away.
Patrick ruled `room_kill` is the ONE door that ends a session, so it waited.
@baud shipped `baud --end-room <branch> --project <name>` the same evening — and
proved the single-mechanism claim rather than asking to be trusted on it: the flag
and the desktop button reach the same kill, with the resolved project passed as an
argument to the shared half.

**`ended` is a fact, not a success flag.** `ended: true` means a live session was
ended; `ended: false` with `ok: true` means there was nothing to end, which is the
goal state rather than a failure. Both travel, because the phone shows different
sentences and flattening them here would make that impossible. An unknown branch
is a *refusal*, never nothing-to-end — both show `room: null` and they are
opposite facts, so `ok` is what tells them apart.

The exec lives in `fleet.py`, which already owns @baud's binary — one resolution,
one cwd rule, one parser for their envelope. That is what lets the verb lane keep
importing no subprocess machinery at all. `verbs.KILL_SEAM_READY` remains as an
operational kill switch: closed means a 503 that says the switch is closed, never
a session quietly not ended and reported as fine.

**The face is served here, not cross-origin.** @baud's `dist-phone` bundle is
served from this server, so there is no CORS allow-list to publish and nothing to
misconfigure — the option with no configuration cannot be misconfigured. The page
itself needs no token: a browser doing a top-level navigation cannot send a bearer
header, so gating it would mean a second, weaker auth system guarding a public
bundle that renders a token door and nothing else. Every byte of data stays behind
`/v1/*`. The bundle is served precisely — `/assets` mounted, each bundle-root file
routed by name — never as a catch-all that could shadow the API.

**Why the feed cursor is a timestamp:** `notifications.jsonl` is trimmed 400→200
lines and the trim replaces the file, so a line or byte offset goes stale under
any reader — the same shape as the 10-hour Telegram outage. The cursor clamps at
both ends and re-delivers the boundary event: a duplicate alert is a nuisance, a
dropped one defeats the app.

**Names, not paths:** `/v1/files` has no path parameter. The client names a branch
and the server resolves it through the citizen registry, which removes the
traversal class rather than mitigating it. Containment is still checked underneath,
because a "name" can lie and a symlink can point out of the tree.

**Fleet is a pipe, not a model.** `/v1/fleet` shells `baud --snapshot` and returns
@baud's envelope with no adapter — this server never computes what an agent's
state means, because a second answer to "is this agent alive" would eventually
disagree with the desktop and neither would be trusted. `has_room` is filtered on,
never derived, and `live_agent_sessions` is served raw rather than joined to the
branch list. BAUD's binary is resolved to the same built release path the desktop
launcher execs. `fleet.SNAPSHOT_READY` remains as a kill switch: switched off
means **503 with a reason**, never a synthesised fleet.

**Aliveness is `live_agent_sessions`, and only that.** The three fleet fields
answer three different questions: `has_room` means a BAUD-named session *exists*
(an empty room is `has_room: true`), `outside_room` names a session BAUD did not
create, and `live_agent_sessions` is the process-table read. Rendering "alive"
from `has_room` puts a green circle over an empty room. This server never
synthesises an aliveness signal, so the only field a client can read it from is
the one that means it — pinned by test at @baud's request.

**The terminal lane does not show you a picture of the room — it gives you the
room.** `WS /v1/room/attach` spawns a PTY running `tmux new-session -A -s
baud-<branch>`, the same argv the desktop runs. The phone becomes a real tmux
client, so scrollback, colour, cursor position and full-screen programs all work
because nobody is reimplementing them. The lane was first built as
capture-and-repaint polling and cut before it shipped: a repaint shows a picture
that updates, an attach shows the room. `-A` is attach-*or-create*, which is what
stops a phone and a desk from landing in two rooms with one agent's name on them.

**A room born here matches one born at the desk.** The attach command chains
`set-option -t <room> mouse on` and `set-option -w -t <room> window-size
smallest` — @baud's measured settings, so the phone-only path does not get the
worst geometry of the two doors. Every chained command carries **its own `-t`**,
pinned by a test: a `set-option` with no target resolves against whatever tmux
calls the current session, and it parses and exits 0 either way.

**Disconnect is SIGHUP to the client, which is a detach.** The session, the agent
inside it and its scrollback all survive — that is what makes closing a sheet on
a phone free. This module never calls `kill-session`, never reaches for `SIGKILL`,
and a test *parses* it to prove no string it evaluates contains "kill". Ending a
room stays exactly one door: `/v1/verbs/kill` → `baud --end-room`.

**The child takes the PTY as its CONTROLLING terminal, and that is what makes
resize work at all.** `TIOCSWINSZ` delivers `SIGWINCH` to the foreground process
group of the *controlling* tty, and inheriting an already-open descriptor never
acquires one — so `start_new_session=True` left the room deaf: every resize
landed in the kernel and reached nobody, while `tmux list-clients` sat at 80x24
forever. The `preexec_fn` does the `setsid` itself, so the signal isolation that
flag bought is kept and the terminal is gained. The initial size is stamped on
the master *before* the child exists, because `openpty` hands back 0x0 and a
client that reads that has already chosen its own fallback.

**Binary frames are keystrokes, text frames are control.** That split lets a
resize ride the same socket without ever being mistaken for something the
operator typed. Bytes are forwarded undecoded in both directions — the room emits
escape sequences and partial UTF-8 across chunk boundaries, and decoding either
end corrupts both. Resize is the only control verb: `{"type":"resize","cols":N,
"rows":N}`, refused rather than clamped, and never fatal — a bad geometry must not
drop a room the operator is working in.

**Scope is `operate`, with no reading half.** An attached room is a shell prompt,
so there is no read-scope attach to offer. `kind=watch` is the exception and the
reason the rule can stay strict: a watch is `drone @prax monitor run` on a
read-only PTY whose `write` refuses, so observation is what the **read** scope
*is* — demanding operate for it would make the read token a lie.

**A watch with no branch is global mission control**, and it is the one lane on
this surface where an absent branch is a real answer rather than the bug that
killed a live session. `drone @prax monitor run` with nothing after it watches
every branch — the desktop's own default pane — and it names no session to take
over. Until 2026-08-16 that form was *unreachable*: the charset fence refused an
empty string and the argv builder always appended a target, so @baud shipped the
phone's door **disabled** rather than pointing it at one branch's monitor, which
would have rendered perfectly and been a lie. The fence is mirrored from their
`pty.rs` character for character and still refuses the empty string; whether a
target was *named at all* is a different question, asked once before the fence is
consulted. @prax also documents `run all` for the same thing and this lane
deliberately does not use it — the desktop's argv is what is being mirrored.

**The bearer rides `Sec-WebSocket-Protocol`, never the query string.** A browser
cannot set an `Authorization` header on a WebSocket, and a token in a URL is a
credential written to access logs, proxy logs and browser history — three copies
nobody chose. The client offers `["aipass.bearer", <token>]`; the server echoes
back only the sentinel, because the accepted protocol appears in the handshake
*response* and a token there would just move the leak.

**Refusals split by who can fix them.** Auth fails *before* accept, so no PTY is
ever spawned for an unauthenticated caller. Everything after auth is refused on an
accepted socket with a close code and a readable reason — `1008` theirs, `1011`
ours — because a browser only surfaces a reason on an established socket, and
refusing pre-accept would put a fixable sentence where the phone cannot show it.

**The stream is never logged.** Room output is whatever is on the operator's
screen and client bytes may be a password; the attach and detach are recorded,
their contents are not.

**The pump waits for the FIRST direction to end, not both.** Waiting for both
deadlocks on a quiet room: the phone closes the sheet, the socket reader ends,
and the PTY reader is still parked in a blocking `os.read` that will not return
until the room happens to print something — so the detach, the SIGHUP and the
executor thread all wait on output that may never come. The hangup runs first in
the teardown, because closing the descriptor is what breaks the blocked reader
out; cancelling the task alone would not, since a thread inside a syscall does
not notice an asyncio cancellation.

**The photo lane is one route and no new mechanism.** `POST /v1/files/upload`
writes an image to `~/Pictures/BAUD/` — the same folder the desktop's own
captures land in — and returns its absolute path. That path is the entire
product: the phone types it into the already-open attach socket through @baud's
existing `deliverPaths`, and never appends Enter. Images by path, so the path is
the delivery.

**The server names the file; the client cannot.** An upload's filename is
attacker-controlled and no sanitiser is worth trusting against every form of
`../`, so it is not sanitised — it is never read. The name is a timestamp plus a
random suffix, and the extension comes from the **sniffed magic bytes** rather
than the declared `Content-Type`, so a `.png` on disk cannot hold something that
is not a PNG. Same ruling as the name fence in `reads.py`, one step further: a
parameter that does not exist cannot be exploited.

**The 25MB cap refuses and is checked twice** — once against the declared
`Content-Length` so an oversized body is refused before it is read, and again
against the running total while reading, because `Content-Length` is a claim and
a chunked upload has none. A refused upload leaves no partial file behind.
Uploads are created `0o600` via `os.open` rather than narrowed afterwards.

`python-multipart` is a second optional dependency inside the `[host]` extra.
FastAPI raises at route-registration time without it, so the import is guarded
and the route is registered either way — answering 503 with the install hint,
because a 404 on a route that should exist reads as "wrong URL".

Push (`/v1/notify`) is reserved, not built. See FPLAN-0411.

Requires the optional `[host]` extra (`fastapi`, `uvicorn`); commands fail with
install instructions if it is absent.

---

## Integration Contract System (DPLAN-0133)

Private drivers in `apps/integrations/{project}/driver.py` (gitignored) register named contracts via `bridge.register()`. Callers resolve by name — never referencing private projects directly. `registry.py` handles auto-discovery via importlib.

---

## Known Issues

- Error paths exit `0` — a failed command (missing arg, no key, no data) reports success to the shell, so `drone @api validate && ...` proceeds on failure. Unknown commands correctly exit `1`. See APLAN-0013.
- Google auth libraries are optional deps — commands fail with install instructions if missing
- Backup branch credential migration pending (`~/.aipass/` → `~/.secrets/aipass/`; legacy dir still present)
- No rate limiting on OpenRouter calls (S117 finding)

**Troubleshooting:** `openai`/Google auth `ModuleNotFoundError` despite a working venv → the `[llm]`/`[drive]` extras were added after the venv was last built; re-run `setup.sh` (installs `.[dev,memory,llm,drive]`) to resync, no code fix needed. Both import cleanly as of 2026-08-13.

---

*Last Updated: 2026-08-14*

[← Back to AIPass](../../../README.md)
