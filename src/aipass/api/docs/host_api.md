# The host API — Stage 0

**Branch** api · **Code** `apps/handlers/host/`, `apps/modules/host_api.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

---

The server the BAUD phone face talks to. **Bound to the tailnet since 2026-08-14**,
after the Phase 5 security review — the first network-listening service in AIPass.

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
| `GET /v1/roots` | read | Every place the file lane may stand: `home`, every project in @baud's census, this server's own repo. Rows of `{kind, name, label}`. No census, no roster — 503, never a short list |
| `GET /v1/files?branch=&file=&project=&root=` | read | Name by NAME, file relative to the root; 512KB cap **refuses**, never trims. `root` = `branch`\|`home`\|`project`\|`aipass`, absent = branch. Answers carry `floor` — the root's absolute path, so a copy-path button can paste into a terminal. Any project |
| `GET /v1/dir?branch=&dir=&project=&root=` | read | One directory level, the phone's file browser. Same optional `root`; `branch` carries the name WITHIN that kind — and a kind that names nothing may name *itself* (`branch=home&root=home`), any other name refused. Answers carry `floor`, and `floor` + an entry's path is that entry's real location |
| `GET /v1/diff?branch=&staged=&project=&path=&grain=&ref=` | read | One patch, through `drone @git`, never raw. `path` = ONE file (refused, not trimmed, over 512KB); `grain` = `branch`\|`repo`; `ref` = a commit. Any project |
| `GET /v1/git-changes?branch=&project=&grain=` | read | Changed files. `branch` grain (default) = @baud's desktop card contract; `repo` grain = the whole repository. The answer names its grain. `rows[]` carries git's own two-column code per path, untracked included **by name** |
| `GET /v1/git-log?branch=&project=&limit=` | read | Recent commits — sha + subject. **Always repo grain.** `limit` 1–50, outside is refused, never clamped |
| `GET /v1/commit?branch=&ref=&project=` | read | One commit: author, date, subject, message, files with ± counts. Its patch rides on `/v1/diff` |
| `GET /v1/git-remote?branch=&project=` | read | The repository's remote, for link-cards out to the forge. `url` as configured (password redacted), `web` browsable or `null`, `remote` names which one answered |
| `GET /v1/fleet?project=` | read | @baud's snapshot envelope, unchanged. `project` is case-sensitive |
| `GET /v1/rooms?project=` | read | A filter over that same snapshot — never a room judgment of its own |
| `GET /v1/projects` | read | @baud's project census — the switcher menu's rows, unchanged |
| `GET /v1/roster` | read | Every working agent in **every** project. Takes no parameters — any is a 400, never a silent drop |
| `GET /v1/machine` | read | @skills' `machine_vitals()`, **verbatim**: `ok`, `schema`, `sampled_at` and eight sections (cpu, load, memory, swap, temp, fan, network, processes), each carrying `available`/`reason`/`sentence`/`detail`. 1 s single-flight cache — the first read after a server start shows cpu and network `warming`. An absent reading is a **200** with the skill's section, never a zero; **503** only when the skill refused (`psutil_missing`, `switched_off`: the code in `error.reason`, its detail as the message) or its door failed (`machine_door_failed`). Takes no parameters — any is a 400 |
| `GET /v1/lock` | read | @skills' `lock_state()`, **verbatim**: `ok`, `locked`, `method`, `session`, `reason`, `detail`. 1 s single-flight cache. Cannot tell (`ok: false`, `locked: null`, the skill's code and sentence) is a **200** — the phone draws it unknown, never unlocked; **503** `lock_door_failed` only when the door raised or broke its shape (a boolean `ok`, a `locked` key, the two agreeing). Takes no parameters — any is a 400. Locking stays `POST /v1/verbs/lock`, operate scope |
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
identically. Note this is deliberately **not** the verb lane's rule (see
[host_surfaces.md](host_surfaces.md)): a
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

**This lane read a rendered surface until 08-18, and that was the bug.** Git is
drone-only, servers included, so it shells `drone @git status` — but it used to
read the *screen* output and pass the porcelain codes through verbatim, which
was faithful to a surface that had already flattened them. `get_branch_status()`
existed under `apps/handlers` and returning to it would have meant reaching into
another branch's internals, the layering mistake this package has made once
already, so the ask was for a `--json` instead. **It shipped**, and it took
every line of the parsing with it: the lane now reads
`{ok, branch, scope, files[{status, path, index, worktree}], total, message}`
and the two columns arrive as two columns. Asking for the right door beat
parsing the wrong one more carefully, which is the whole lesson of the round.

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

---

[← api README](../README.md)
