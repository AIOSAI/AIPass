[<- Back to the README](../README.md)

# The host API — Stage 0

**Branch** api · **Code** `apps/handlers/host/`, `apps/modules/host_api.py`

---

The server the BAUD phone face talks to, **bound to the tailnet** — the first
network-listening service in AIPass.

```bash
drone @api host-api issue-token pixel-8 --scope read   # receipt -> ~/.secrets/aipass/host_api/
drone @api host-api serve              # binds the configured address
drone @api host-api serve --detach     # survives drone's exec timeout; log in logs/
drone @api host-api autostart          # renders the boot unit + prints the install steps
drone @api host-api status             # pid, bind, owner, and where to read it
drone @api host-api set-config --host <ip>   # validated before it is stored
drone @api host-api set-config --face-dir <dir>   # an installed phone face; 'default' clears it
drone @api host-api set-config --baud-bin <path>  # the binary the fleet lanes exec; 'default' = automatic
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
`token_unrecognised` (with none), so the log can say whether a refused device
presented a credential this host once issued or garbage.

**The store answers three questions about every credential:** `minted_by`
(best-effort, from the branch drone names in the child environment —
**provenance, never permission**, since the value comes from the caller's own
environment), `revoked_at`, and `last_used`, which separates a live token from one
that is merely un-revoked. `drone @api host-api list-tokens` prints all three.

`last_used` means a write on every authenticated request, so the store is written
atomically (temp file, `fsync`, `os.replace`, created `0o600` rather than
chmod'd after) behind a cross-platform lock with stale-lock breaking. Two rules
hold it together: **telemetry never undoes security** — the touch re-reads inside
the lock, so a stale record list can never write a revoked token back to life, and
a lock it cannot take means the timestamp is dropped, never raised — and writes
are coalesced to one per minute per token, so feed polling does not rewrite the
store every few seconds. The envelope is versioned; records predating the fields
still verify, and read back as `unknown`.

**A raw token is never printed.** `issue-token` writes its receipt to
`~/.secrets/aipass/host_api/<label>.token` (dir `0700`, file `0600`; `--out`
overrides). The label is a filename, so it passes the routes' two-gate name fence.
An existing receipt is refused, never truncated: its token is still live in the store.

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
| `POST /v1/pair` | none | `{"code"}` → **200** `{token, id, label, scope}` for a live one-use pairing code. **401** `pairing_refused` for unknown, expired and used alike; **429** after 10 attempts a minute per address; **400** without a string code. See [Pairing](#pairing) |
| `GET /v1/feed?since=&limit=` | read | Cursor is a **timestamp**, clamped both ends, `gap` flagged |
| `GET /v1/roots` | read | Every place the file lane may stand: `home`, every project in @baud's census, this server's own repo. Rows of `{kind, name, label}`. No census, no roster — 503, never a short list |
| `GET /v1/files?branch=&file=&project=&root=` | read | Name by NAME, file relative to the root; 512KB cap **refuses**, never trims. `root` = `branch`\|`home`\|`project`\|`aipass`, absent = branch. Answers carry `floor` — the root's absolute path, so a copy-path button can paste into a terminal. Any project |
| `GET /v1/dir?branch=&dir=&project=&root=&offset=` | read | One directory level, the phone's file browser. Same optional `root`; `branch` carries the name WITHIN that kind — and a kind that names nothing may name *itself* (`branch=home&root=home`), any other name refused. Answers carry `floor`, and `floor` + an entry's path is that entry's real location. Pages of 400 from `offset` (int ≥ 0, default 0, else 400 `read_refused`); `total` counts past the noise filter, `truncated` while `offset` + page < `total`, past the end `[]`; audited |
| `GET /v1/diff?branch=&staged=&project=&path=&grain=&ref=` | read | One patch, through `drone @git`, never raw. `path` = ONE file (refused, not trimmed, over 512KB), branch-local at `branch` grain; one the worktree patch lacks comes from the index (`staged: true`). `grain` = `branch`\|`repo`; `ref` = a commit. Any project |
| `GET /v1/git-changes?branch=&project=&grain=` | read | Changed files. `branch` grain (default) = @baud's desktop card contract; `repo` grain = the whole repository. The answer names its grain. `rows[]` carries git's own two-column code per path, untracked included **by name** |
| `GET /v1/git-log?branch=&project=&limit=` | read | Recent commits — sha + subject. **Always repo grain.** `limit` 1–50, outside is refused, never clamped |
| `GET /v1/commit?branch=&ref=&project=` | read | One commit: author, date, subject, message, files with ± counts. Its patch rides on `/v1/diff` |
| `GET /v1/git-remote?branch=&project=` | read | The repository's remote, for link-cards out to the forge. `url` as configured (password redacted), `web` browsable or `null`, `remote` names which one answered. No remote: 200, all three `null` |
| `GET /v1/fleet?project=` | read | @baud's snapshot envelope, unchanged. `project` is case-sensitive |
| `GET /v1/rooms?project=` | read | A filter over that same snapshot — never a room judgment of its own |
| `GET /v1/projects` | read | @baud's project census — the switcher menu's rows, unchanged |
| `GET /v1/roster` | read | Every working agent in **every** project. Takes no parameters — any is a 400, never a silent drop |
| `GET /v1/machine` | read | @skills' `machine_vitals()`, **verbatim**: `ok`, `schema`, `sampled_at` and nine sections (cpu, load, memory, swap, temp, fan, network, processes, battery), each carrying `available`/`reason`/`sentence`/`detail`. 1 s single-flight cache — the first read after a server start shows cpu and network `warming`. An absent reading is a **200** with the skill's section, never a zero; **503** only when the skill refused (`psutil_missing`, `switched_off`: the code in `error.reason`, its detail in this host's log) or its door failed (`machine_door_failed`). Takes no parameters — any is a 400 |
| `GET /v1/machine/processes?limit=20` | read | @skills' `machine_processes(limit)`, **verbatim**. A real ~0.5 s CPU sample, uncached: ask on open, never poll. `limit` as sent (the skill clamps); not a number is a 400. Refusals as `/v1/machine` |
| `GET /v1/lock` | read | @skills' `lock_state()`, **verbatim**: `ok`, `locked`, `method`, `session`, `reason`, `detail`. 1 s single-flight cache. Cannot tell (`ok: false`, `locked: null`, the skill's code and sentence) is a **200** — the phone draws it unknown, never unlocked; **503** `lock_door_failed` only when the door raised or broke its shape (a boolean `ok`, a `locked` key, the two agreeing). Takes no parameters — any is a 400. Locking stays `POST /v1/verbs/lock`, operate scope |
| `GET /v1/memory-config?branch=` | read | @memory's limits. No branch = the fleet view; a branch = that one |
| `POST /v1/memory-config/set` | operate | `{branch, type, count}` — one branch's override. 1–100 |
| `POST /v1/memory-config/set-default` | operate | `{type, count}` — the default only. **Does not reach any branch** |
| `POST /v1/memory-config/push` | operate | Empty body. What actually delivers a default everywhere |
| `POST /v1/verbs/wake` | operate | `{branch, project, message?, fresh?}` → `@ai_mail dispatch wake` |
| `POST /v1/verbs/kill` | operate | `{branch, project}` → `baud --end-room`. Returns `room` and `ended` |
| `POST /v1/verbs/lock` | operate | Empty body. Proxied to `@skills`' screen_lock. Never gated |
| `POST /v1/verbs/new-project` | operate | `{name, template?}` → `aipass new` + its agent. 200 `{ok, name, project, target, template, agent, agent_home, detail}`; 400 `project_name_refused`/`template_refused`/`project_refused`, 409 `project_exists`, 503 `project_door_failed` |
| `POST /v1/backup/run` | operate | `{project, lane}` → **202** the running job. Lanes `snapshot`, `versioned`, `all`, `drive_sync`. Same lane already running: **400**. See [host_surfaces.md](host_surfaces.md) |
| `POST /v1/backup/cancel` | operate | `{project, lane}` → `drone @backup stop <root> <lane>`. **200** `{project, lane, stopped, message}`, stop's line verbatim. Nothing running: **404** `not_running`, @backup's line |
| `GET /v1/backup/job?id=` | read | One job, `running`/`done`/`stopped` (exit 130)/`failed`, `summary` the output's tail. Forgotten: **404** `job_unknown` |
| `GET /v1/backup/status?project=&sizes=` | read | `drone @backup status --json` passed through; each `running` entry gains `job` (this server's id, else `null`). No `--json` on this machine: **503** |
| `GET /v1/agent-settings?branch=` | read | One branch's three owned claude settings — an absent key reads `null` |
| `POST /v1/agent-settings` | operate | Patch those three. Three-state by JSON's nature: absent touches nothing, `null` removes, a value sets |
| `GET /v1/baud-settings` | read | BAUD's own document for the seat, whole and opaque |
| `POST /v1/baud-settings` | operate | Shallow-merge into it — `null` removes, a nested object replaces |
| `GET /v1/hooks-sound` | read | @hooks' mute switch, read live through their own `is_muted()` |
| `POST /v1/hooks-sound` | operate | Flip machine-wide hook sounds through @hooks' own command. Idempotent both directions |
| `POST /v1/files/upload` | operate | Multipart image. The SERVER names the file; returns its absolute path |
| `WS /v1/room/attach?branch=&project=&kind=` | operate\* | A real PTY. Bearer on the subprotocol. `kind=watch` is **read** scope; a watch with **no branch** is global mission control. Control frames: `resize`, `ping` |
| `GET /` | none | @baud's phone face, served from this same origin |

**Verbs answer `{ok, detail}` at 200, and the line matters:** `ok: false` means the
mechanism **ran and said no**, with the owning branch's own sentence in `detail`
(the phone renders it verbatim, because a sentence beats a status word). If the
mechanism was never reached — seam missing, door unreachable — that is a status
code, not an `ok`. A wake refused by @ai_mail's blocklist is `200 {ok: false}`;
a kill whose seam does not exist is 503.

**New-project calls @aipass's `create_project`.** A name is a letter then up to 63
letters, digits, `_` or `-`; `template` is `empty` (default) or `python`; `project` is
the census name the switcher keys on. The name, template and exists refusals say their
sentence; `project_refused` and `project_door_failed` give a fixed one and a `ref`.

**An exception's words never reach the client.** They can carry a host path,
another program's stderr or another branch's JSON, so a denial caused by a caught
exception answers `{code, message, ref}`: the code's fixed sentence from
`denials.py`, and a `ref` that names the host-log line holding the words and the
traceback (CodeQL `py/stack-trace-exposure`). Branch on `code`, read the log by `ref`.

**The memory-config lane reads a document, not a screen.** @memory's five config
verbs answer `--json`, and nothing here reads a glyph, a marker or a column
position: every command is sent with `--json` appended in **one** place, and the
verdict is the `ok` boolean they emit. `raw` still rides on every response —
their payload verbatim — so a caller is never trapped behind my reading of it.

Two of their conventions remain load-bearing: their refusals **exit 0**, so the
exit code is still never the verdict here; and `set-default` **changes only the
default** — until `push` runs, all 17 branches keep their existing values. That
surprise is @memory's design and is passed through untouched, and *reported*:
`pushed` comes from their payload, as does the `branches` count a push answers with.

**What is not one parseable object is `503`, never a verdict.** If `--json` ever
stops being honoured — an older @memory on a fresh clone, a renamed flag, a
banner ahead of the payload — this lane gets prose back and says it could not
tell. After a write that is the honest answer, and a `200` would be a guess about
the owner's configuration.

**A refusal has one shape on this lane, wherever it was decided:** `400
memory_config_refused`, the code's fixed sentence and a `ref`; their sentence,
remedy line and whole payload go to this host's log under that ref. An argument
this server rejects before routing and a refusal @memory *speaks* answer
identically, so a client learns one fact from one status code. Note this is deliberately **not** the verb lane's rule (see
[host_surfaces.md](host_surfaces.md)): a
refused wake is a normal outcome of asking and the phone renders it, but a
refused write to fleet configuration is a caller error.

**The git-changes lane answers @baud's question, not a second one.** The
contract is theirs, read from their tree rather than invented here:
`GitChanges { files, count }`, filled by `git diff HEAD --relative --name-only
-- .`. Two consequences are reproduced deliberately. **Tracked files only** — a
brand-new module does not move a card's badge, because `diff HEAD` cannot see a
file git has never seen; counting it here would make the phone disagree with the
desktop about the same branch at the same moment, with the phone being wrong.
And **branch-local names**, because every `src/aipass` branch shares one repo and
a repo-relative row would push the part that differs off a phone screen.

`untracked` rides alongside as a separate count, never folded into theirs.
Matching a contract is not a reason to discard something already measured —
@baud's own argument for their whole-project total is that a count hiding a new
module reads as false calm, and that does not stop being true here.

**It reads drone's document, never its screen.** Git is drone-only, servers
included, so the lane shells `drone @git status --json` and reads
`{ok, branch, scope, files[{status, path, index, worktree}], total, message}`;
the two porcelain columns arrive as two columns. It does not reach into another
branch's `apps/handlers` for a status function: that is the layering mistake an
owned `--json` door exists to prevent.

**It serves foreign projects.** drone verifies its caller by finding a passport in
the cwd hierarchy, and every census-known branch carries its own passport, so the
caller check passes for any project in @baud's census. What drone cannot do is be
invoked *from* a cwd with no passport above it, which affects agents working inside
external trees, not this lane.

Paths are stripped against the repository **discovered** by walking up from the
branch for a `.git` marker (a directory, or the file a worktree carries), which is
the only root guaranteed to match what drone printed; the seat's repo root is a
fallback. Stripping against the seat first would be wrong for every foreign branch
(`src/vera_studio/vera/CLAUDE.md` where the contract says `CLAUDE.md`) and silently
wrong for nested tenants: `projects/baud` carries its own `.git`, so the
seat-relative prefix *resolves cleanly* and is still the wrong one.

A genuinely unreachable project still refuses honestly: a non-git one answers
`503` with git's own sentence, *not a git repository*. An empty change list
would paint it clean when nothing was measured.

**A root that cannot be read is not re-asked every poll.** A phone polls every
5 seconds, and for an external project whose branch carries no passport drone
refuses the caller before the door runs. `refusals.py` remembers that refusal per
root and lane for 60 seconds. What is kept is drone's **answer**, never drone's
rule — checking for a passport here would reimplement another branch's
authentication and drift from it. The window is the recovery: a root that gains a
passport works again within a minute.

---

## The read lane and its cache

**Blocking routes are plain `def`** and run in the threadpool, so a slow read never
freezes the single worker's loop. `/v1/ping` and `/v1/whoami` stay `async` (no
blocking work); write routes stay `async` deliberately, the loop being their only
serialization. The citizen registry is pinned once at boot.

**Expensive reads are single-flight with a short TTL** (`read_cache.py`: the change
list at 1.5 s, machine vitals, lock state): N concurrent callers share one
subprocess, a re-poll hits the TTL, and a failure is never cached. `fleet.py`
coalesces @baud's snapshot the same way, one exec per 1.5 s for `/v1/fleet` and
`/v1/rooms`.

**Terminal sockets pump on their own 16-thread pool** (`PUMP_WORKERS`, `attach.py`);
attach seventeen is refused with a sentence naming the cap.

---

## Pairing

**A receipt file the user has to carry is a credential typed by eye or mailed**,
so the token's hop to the phone is a QR.

`host-api pair <label> [--scope read|operate] [--ttl SECONDS]` mints a one-use
code (`pairings.py`), stores only its sha256 in `host_api/pairings.json` beside
the token store, under the token store's own lock and atomic owner-only write,
and prints the QR of `http://<bind>/#pair=<code>`, the URL, and the expiry. The
fragment never leaves the browser. The face strips it from the address bar and
posts it to `POST /v1/pair`, the one route with no bearer: the code is the
credential, once, for five minutes.

- **Used before minted.** A redeem marks the row used, releases the lock, then
  calls `issue_token()`. A failure between the two burns the code rather than
  leaving it live for a second phone.
- **One answer.** Unknown, expired and used share the 401 sentence; which it
  was goes to the log with the caller's address.
- **Swept.** Every mint and redeem drops rows that are used or past their
  expiry; the row spent just now stays until the next one, so a second try is
  logged as `used`, not `unknown`.
- **No receipt.** The paired token is listed and revoked like any other.
- **An address a phone can open.** `mint_pairing` refuses an unset or wildcard
  bind; the verb also refuses loopback, before anything is minted.
- **A server that answers.** `mint_pairing` sends one GET to the bind's `/`
  before it stores anything: a serve record can name a pid that died. Nothing
  answering refuses with the two commands that fix it (`serve --detach`, then
  the same `pair`); an error status refuses and names `host-api status`. In the
  door, so the installer's mint has it too.

The module door: `mint_pairing(label, scope="read", ttl_seconds=300) -> dict`,
`render_qr(text) -> str` and `PairingError` (a `TokenError`), on
`aipass.api.apps.modules.host_api`.

---

[← api README](../README.md)
