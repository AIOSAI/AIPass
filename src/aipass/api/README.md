[← Back to AIPass](../../../README.md)

# API

> Centralized external API gateway — authenticated service clients for all external APIs

**Module:** `aipass.api` | **Role:** `api_gateway`
**Seedgo:** 100% (46/46) | **Tests:** 1625 pass | **Functions:** 240 public (218 tested)
**Last Updated:** 2026-08-27

*THE BOARD WAS RED FOR THIS BRANCH IN THREE PLACES AND ONE OF THEM ONLY
EXISTED IN CI. seedgo scored the file lane's statics module with 4 unresolved
imports that a local audit could not see, and the reason is one line of shared
configuration: `pyrightconfig.json` carries `.venv/lib/python3.12/site-packages`
on extraPaths, a directory that exists on a developer's machine and nowhere
else. CI installs `.[dev,memory]` and never `[host]`, so `fastapi` and
`starlette` resolve here and vanish there. `statics.py` was the only host module
importing the extra WITHOUT the suppression header every other one carries —
server.py, attach.py and google/auth.py all have it — so it was the only one
that failed. Reproduced before it was fixed, by running the checker against an
empty environment and getting the same four, then re-run to zero: a fix for a
failure you cannot reproduce is a guess with good intentions.*

*THE PUMP MOVED OUT, because 1534 lines is over a 1500-line cap and the ping
lane is what pushed it there. `pump.py` now holds the bidirectional socket and
its two control verbs; `server.py` keeps the routes and dropped `asyncio` and
`json` with them, since the pump was the only thing here that used either. A cap
is only a good reason to move code that was already separable, and this was —
these functions take everything they touch as arguments, which is why they had
already survived one move. Three tests read their source and now read it from the
new file; one asserted on a logger that no longer lives in the same module, which
is exactly the kind of quiet disconnection a move like this can leave behind, and
it failed loudly instead. Eight mutations, all bitten, across both files.*

*AND THE STANDARDS CHECKER ASKED THE NEW MODULE WHY IT LOGGED NO OPERATIONS,
which was a fair question with a real answer. Every socket refusal on this
surface leaves a structured record EXCEPT one: typing into a read-only watch
happens after the socket is live, so it never passes the route's audit gate. It
logged a warning, closed 1008, and told the trail nothing. It records the room
and the session's own sentence now. The cheap way to satisfy that checker was a
token log line; the honest way was to find the gap it was pointing at.*

*A PHONE COULD NOT TELL A LIVE ROOM FROM A CORPSE. When a socket's peer
vanishes without a FIN — a tunnel dropped, a laptop slept, a NAT entry expired —
the browser keeps rendering the last frame it received and the operator believes
they are looking at a live terminal. uvicorn pings from this side every 20
seconds, so the SERVER always finds out; the JS WebSocket API exposes no ping at
all, so the phone had no round-trip of its own and never did. So the control
channel gained a second verb: `{"type":"ping"}` is answered `{"type":"pong"}`,
on the text channel it arrived on, because a pong on the binary channel is
indistinguishable from room output and would paint itself across the terminal.
It is inert by construction — nothing typed, nothing resized, nothing logged; a
liveness probe every few seconds is not an event, and recording it would bury
the two lines that are. An inbound pong is an unknown frame, deliberately: the
server pongs, it does not ping, and answering one would be two sockets shouting
at each other on the wire the operator's keystrokes share.*

*AND THE ROOM LANE WROTE DOWN ARRIVALS BUT NOT DEPARTURES. Thirteen attaches to
one room in three minutes, and the log could not say whether thirteen sockets
came and went or came and stayed — an arrival count alone cannot tell a
reconnect loop from an operator opening sheets. Every detach now names the room,
how long the socket lived, and the code it closed on. When the ROOM ends first
the field says `room ended` rather than `None`: that is a different detach from
any a client can cause, and a bare `None` reads as a logging bug rather than as
the fact it is. Both fixes are @baud's r5 diagnosis of an incident on Patrick's
own seat, and neither is LIVE — the production server on 8787 still predates
them, along with the cache-control fixes below, until the restart window
@devpulse holds. Nine tests, six mutations, all bitten. The honest cost: +55
lines put `server.py` at 1533 against a 1500 cap, and the answer is a split
(the pump and its control handler are self-contained), not a trim.*

*Three findings arrived from other people's instruments in one night, and two
of them were the same defect wearing different clothes. THE PHONE FACE was
served with an etag, a last-modified and NO cache-control — which is not "do not
cache" but "guess", and RFC 9111's heuristic guess is ~10% of the age since
last-modified. The entry is un-hashed and NAMES the content-hashed bundles, so a
stale entry faithfully fetches OLD assets; Patrick's first reload served a
round-3 bundle and cost an acceptance round a false FAIL. Every stable-named
file revalidates now, including `/phone.html` — the manifest's own start_url,
which a narrow fix would have left stale for every installed phone while the
typed URL looked fixed. `/assets` keeps its caching: a hashed name cannot go
stale. And `no-cache` only means "ask first" if this server ANSWERS conditional
requests, which it never did — starlette's FileResponse sets an etag and ignores
If-None-Match — so that got closed too, with starlette's own comparison rather
than a copy of it.*

*THE GIT LANE was re-asking a question it already had the answer to, 720 times
an hour. A phone polls every 5 seconds; for an external project whose branch
carries no passport, drone refuses the caller before the door runs, and every
poll spawned a subprocess that was never going to work and warned in three
places across two branches' logs. What is remembered is drone's ANSWER, never
drone's rule — checking for a passport here would be reimplementing another
branch's authentication and drifting from it in the worst direction. A 60-second
window means a root that gains a passport recovers on its own.*

*AND THE SERVER GAINED A LIFETIME. `serve` routed through drone is a child of
drone's exec timeout, so the tailnet server was dying on a twelve-hour schedule;
the restarts cost more than the downtime, because uvicorn's access log goes to
stdout, stdout was a tmux pane, and a day of access history scrolled out of a
bounded scrollback right when it was needed. `serve --detach` gives the process
its own session and its output an appended file, with `status` and `stop`
because shipping the first without them is a nicer way to make orphans. It does
NOT restart anything — a dead server that stays dead and says so is the honest
failure. The first live start/stop found a bug twenty-two mocked tests could
not: a reaped-but-not-waited child is a zombie, and `os.kill(pid, 0)` says yes
to a corpse.*

*`--out` became OPTIONAL, and that is a security fix rather than a
convenience. The rule was never "make the caller name a file", it was S49's
"never print the raw value" — and the mandatory flag defended it badly, because
its own example said `--out ~/pixel.token`. Patrick found three raw bearer
receipts sitting in his home root on 2026-08-19, 43 bytes each, put there by
whoever read my help text and did what it said. The receipt lands beside the
hashed store now (`~/.secrets/aipass/host_api/<label>.token`, dir 0700, file
0600). That turns a free-form label into a FILENAME, which is the one thing it
could never reach before, so the label now goes through the same two-gate name
fence the routes use: refuse the sentence up front, check containment after
resolving. Refusing an existing receipt is the other half — the token it names
is still LIVE in the store, and truncating the file leaves a working credential
nobody holds and nobody thinks to revoke.*

*The name fence gained ROOTS (FPLAN-0443). It answered exactly one kind of
word — a citizen name — which is why the phone could only ever stand in
agent-land; it answers four now (`branch`, `home`, `project`, `aipass`) and
`GET /v1/roots` publishes the roster so the face renders what the server
holds rather than a list it guessed. The widening is the roster and not the
rule: the client still sends a NAME, the server still resolves it, and the
same containment runs under all four. A request that names no root gets the
branch answer it always got, key for key.*

*The read lane came OFF the event loop (DPLAN-0305). Every route was
`async def` and none of them awaited anything, so each blocking body — a
90ms `baud --snapshot`, a git exec, a registry walk — held the single
worker's loop and the whole phone froze behind it, terminal socket included.
The 18 routes that do work are plain `def` now and run in the threadpool;
`/v1/ping` and `/v1/whoami` stay async because they hold no blocking work,
and the write routes stay async DELIBERATELY — the loop is their only
serialization until settings grows a lock. The snapshot is coalesced (one
exec per question per 1.5s, and one exec per stampede, so `/v1/fleet` and
`/v1/rooms` stop paying twice for the same read), the registry is pinned
once at boot instead of re-walked per lookup, and the audit trail's caller
detection fetches ONE frame rather than building the whole stack. The find
while measuring: the socket pump used asyncio's default executor, which
sizes itself to eight threads on this host — the ninth terminal connected,
authenticated, and then silently never pumped. Its own pool now, and the cap
is a sentence instead of a blank screen.*

*The perf round's own tests then went red in CI, and three of the four were
tests measuring their runner rather than their subject. The caller-detection
pin demanded the name `test_host_perf` and got `conftest`, because the
repo-root conftest WRAPS `log_operation` to keep parallel runs off shared
files — so the caller of `log_operation` really is that wrapper. Measured
before blaming the change: `inspect.stack()[2]` returns the same frame, so
the old implementation named `conftest` too and this test was simply the
first thing in the tree ever to look. It pins AGREEMENT between the two
implementations now, plus the depth itself through a stand-in compiled under
another filename — a stand-in defined in the test file put frames 1 and 2 in
the same module, and the off-by-one mutation survived. The TTL test failed on
Windows only because `time.monotonic` advances there in ~15.6ms steps, so two
reads landed on one tick and `0.0 > 0.0` is false; it drives its own clock
now and sleeps not at all. The pump's POSIX-only machinery patches the
module-level `pty` name rather than an attribute on it (`pty` is None on
Windows), and the one test that genuinely needs SIGHUP skips where SIGHUP
does not exist — honestly, because `open_attach` refuses on that platform
long before a session exists to hang up. Verified against a probe that hides
`pty` and deletes `signal.SIGHUP`: 1463 pass, 36 POSIX skips, one of them
mine.*

*The park gained a real barrier on @memory's proof: `(disabled)` is a naming
habit and dropping the `test_` prefix is what actually keeps a file out of
collection — so `tests/parked/` now carries `collect_ignore_glob` and a pin
that drops a deliberately `test_`-named intruder in to prove it holds.*

*The gateway_boundary line is answered by a bypass entry with its own
retirement clause (no owner door exists at @aipass yet, ruling pending), so
the audit reads 100 with the standing exception on the record rather than
hidden.*

*The two long-standing exceptions before that are gone rather than
documented: the attach route's nesting went when the room resolution and the
PTY pump moved out of the app factory — both already took everything they
used as arguments, so there was never a closure holding them in — and
`settings.py`'s silent catches went when each one was given the honest answer
it was hiding (an unreadable settings file is a fault, not a blank document).*

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
| `host-api serve [--host IP] [--port N] [--detach]` | Run the host API (binds the configured address or refuses); `--detach` gives it its own session and a log file |
| `host-api autostart [--host IP] [--port N]` | Render the systemd user unit into `logs/` and print the host-side install steps — never installs anything itself |
| `host-api status` | Is a server running, **who holds it** (systemd or a hand-started detach), its pid, bind and log |
| `host-api stop` | Stop it through its owner — `systemctl --user stop` when supervised, SIGTERM when not, never SIGKILL |
| `host-api issue-token <label> [--scope read\|operate] [--out FILE]` | Mint a bearer token — raw value never printed, receipt defaults to `~/.secrets/aipass/host_api/<label>.token` |
| `host-api list-tokens` | List tokens — values are never shown |
| `host-api revoke-token <id>` | Revoke server-side, effective next request |
| `host-api config` / `set-config` | Show / set the bind address (validated first) |

---

## Architecture

```
api/
├── apps/
│   ├── api.py                         # Entry point — module discovery, command routing
│   ├── modules/                       # Orchestration layer (10 modules)
│   │   ├── api_key.py                 # Key retrieval, validation, provider listing
│   │   ├── secrets.py                 # Cross-branch secrets door (in-process API)
│   │   ├── openrouter_client.py       # OpenRouter client — calls, models, status
│   │   ├── google_client.py           # Google API services (Drive, Calendar, etc.)
│   │   ├── host_api.py                # Host API — server lifecycle, token admin
│   │   ├── usage_tracker.py           # Usage metrics — track, stats, cleanup
│   │   ├── bridge.py                  # Generic contract registry (register/resolve)
│   │   ├── integrations_manager.py    # Contract dispatch — integrations list/call
│   │   ├── registry.py               # Driver auto-discovery (load_drivers)
│   │   └── host_serve.py             # host_api sub-router — serve/--detach, status, stop
│   ├── handlers/                      # Business logic (8 packages, 35 files)
│   │   ├── module_root.py             # module_file() — the one guarded __file__ resolve (no import-time cwd read)
│   │   ├── auth/env.py, keys.py, secrets.py
│   │   ├── config/provider.py
│   │   ├── google/auth.py, service_factory.py, retry.py
│   │   ├── host/config.py, tokens.py, server.py, feed.py, fleet.py, face.py, verbs.py, attach.py, uploads.py
│   │   ├── host/statics.py (bundle cache policy), lifetime.py (detached serve), refusals.py (unreadable-root memory)
│   │   ├── host/reads.py (resolution, files, dirs), git_reads.py (the whole git surface): patch, changes, log, commit, remote
│   │   ├── host/pump.py (the attach socket's two directions), settings.py (the desktop's two gears), memory_config.py (@memory's limits, served)
│   │   ├── integrations/list.py, call.py
│   │   ├── json/json_handler.py
│   │   ├── openrouter/caller.py, client.py, models.py, provision.py
│   │   └── usage/aggregation.py, cleanup.py, tracking.py
│   └── integrations/                  # Private driver space (gitignored)
│       └── {project}/driver.py
└── tests/                             # 1634 collected across 50 files (parametrised)
    └── conformance/settings/       # 39 shared goldens both runtimes must satisfy
```

Three-tier: entry point routes to modules (orchestration), modules delegate to handlers (business logic). Modules auto-discovered from `apps/modules/*.py` via `handle_command()`. `host_serve.py` is a SUB-router: `host_api.py` offers it every `host-api` call first and owns everything it declines, so an unknown subcommand still reaches an error rather than a silent success.


### No module needs a working directory to be imported (2026-08-31)

`ntpath.realpath` reads `os.getcwd()` **unconditionally** — not only for relative paths, the way
`posixpath` does — and `Path.resolve()` routes through it. So on Windows every
`Path(__file__).resolve()` *reached at import* is an import-time cwd dependency: a process whose
working directory has been deleted cannot import the module at all. On POSIX the equivalent raise
happens earlier, inside a `try` that `inspect` already owns, which is why this was invisible on
Linux for as long as it existed.

The discriminator is **reached at import**, not written at module scope, so it is measured by
*running* the imports in a child interpreter, never by grepping for spellings.

Measured here on 2026-08-31, two denial worlds (A: realpath reads cwd, then cwd is denied — convicts
a raw `resolve()`; B: realpath denied directly, abspath left working — convicts `inspect.stack`):

| stage | modules red (of 61) |
|---|---|
| before | 61 — the handlers guard masked everything |
| after the guard cure | 49 — one line left: `json_handler.py`'s `API_ROOT` |
| after routing three sites through `module_file()` | 0 |

Two cures:

- `apps/handlers/__init__.py` walks frames with `sys._getframe` instead of `inspect.stack()`,
  skips pseudo-files and importlib frames *before* any resolve, guards the resolve with a
  raw-spelling fallback, and reads the import line with `linecache`. The second `inspect.stack()`
  walk in the caller-is-None branch is gone — it was a second copy of the same cwd dependency in
  service of a branch that returned either way.
- `apps/handlers/module_root.py` holds `module_file()`, the one guarded spelling. Three
  module-level constants route through it (`json/json_handler.py`, `usage/aggregation.py`,
  `usage/tracking.py`). Its diagnostics live inside their own protection: the world that reaches
  the fallback is the world where prax's logger may be down too, so `sys.stderr` is the last
  resort rather than a crash.

Pinned in `tests/test_dead_cwd_imports.py`. The behavioural pins cannot see the deleted
`inspect.stack()` walk — `apps/__init__` always supplies a real-file frame, so restoring the defect
leaves them green — so an **AST ban** convicts any `inspect.stack` call in the guard file. It is an
AST ban and not a string ban because the guard's own docstring names `inspect.stack` while
explaining the defect, and a spelling ban would convict the explanation.

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
drone @api host-api issue-token pixel-8 --scope read   # receipt -> ~/.secrets/aipass/host_api/
drone @api host-api serve              # binds the configured address
drone @api host-api serve --detach     # survives drone's exec timeout; log in logs/
drone @api host-api autostart          # renders the boot unit + prints the install steps
drone @api host-api status             # pid, bind, owner, and where to read it
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

### Autostart — the server comes back on its own (2026-08-27)

@baud's phone face went dark this morning. `host_api_serve.log` showed normal
traffic and then silence — no traceback, no shutdown line, which is exactly what
a reboot looks like from inside a log. A detached server dies with the machine
and nothing brought it back; Patrick ruled that a face which waits for a human
after every reboot is wrong.

**It is a systemd user unit, not a loop in this tree, and the reason is the scar
already written into `lifetime.py`.** That module refuses on principle to
restart anything — because the fourteen death-and-restart cycles @baud read out
of a pane on 2026-08-19 came FROM a supervisor, a shell loop somebody typed.
Answering a missing supervisor with a second home-grown one repeats the mistake
with better manners. The alternative on the table was a `@daemon` check-and-start
entry, which keeps everything inside AIPass conventions and is exactly that
second supervisor: it can only notice a crash at poll granularity, it has no
concept of boot ordering, and it would have to reimplement "do not restart what
an operator deliberately stopped" — the one rule this lane cannot get wrong.
systemd is already running here, already owns boot, and already knows that rule.

So `autostart.py` supervises nothing. It **renders** a unit, **answers** whether
the supervisor is holding the server, and **asks** it to stop. Every decision
about starting, restarting and boot ordering belongs to systemd.

**`autostart` writes into the tree and installs nothing.** The unit lands in
`logs/` — gitignored, deliberately: it necessarily carries this machine's
absolute paths and this machine's bind address, and a file like that committed to
a public repo is either a hardcoded path or somebody else's broken install. The
command then prints the five host-side steps. Installing means writing under a
home directory and enabling something that outlives every session; that is
outside this tree and stays the operator's to run.

**Two things make this safe rather than merely automatic, and both used to fail
silently.**

`status` was lying by construction. A unit-managed server writes no record file,
and `running()` only ever read that record — so a perfectly healthy server was
reported as *"No detached server is running"*, at exactly the moment an operator
needs the opposite. It asks the supervisor FIRST now, and a reboot's stale record
can no longer outrank the live process. Every record carries an `owner`, because
the two cases need different commands from whoever reads it.

`stop` would have been a trap. Signalling a supervised pid directly leaves the
restart policy free to start it again, so the command prints success and the
server is back before anyone finishes reading. A supervised stop goes through
`systemctl --user stop`, which outranks `Restart=` by definition. The pid is then
re-checked rather than trusted — the supervisor *accepting* a stop and the
process *being gone* are two facts, and this branch has already been caught once
believing the first implies the second.

**The unit's own details are each a silent failure avoided.** `StandardOutput=`
and `StandardError=` are `append:`, not `file:` — `file:` truncates on every
start, so the first restart after an outage would destroy the evidence of the
outage, and appending to the same `host_api_serve.log` is what made this morning
diagnosable at all. `Restart=on-failure`, never `always`, so a cleanly refused
bind stays refused instead of spinning. `StartLimitIntervalSec`/`Burst` sit under
`[Unit]`: systemd moved them there in v230 and **ignores** the old `[Service]`
spelling rather than erroring, so a rate limit in the wrong section is an absence
wearing a config's clothes. The window is deliberately generous — 60 attempts,
5s apart, inside 10 minutes — because at boot this server can come up before
tailscaled has assigned the address it binds, and that failure is indistinguishable
from a fatal misconfiguration: it exits non-zero immediately. Generous enough to
outlast a slow network, still finite, so an impossible bind ends as a unit in
`failed` that says so rather than retrying forever into a growing log.

The unit and `serve --detach` build their argv from one function, `serve_argv()`.
Two ways to start one server is how a fix lands in one of them and the other
keeps the bug — and the unit's copy is the one nobody re-reads, because it lives
in a file under somebody's home directory that this tree cannot see.

Lingering is reported, not assumed: without it a user unit waits for a login,
which on a headless reboot never comes — the exact failure this build exists to
end. It is set outside this tree and can be turned off by someone who never reads
this file.

---

**A probe that cannot answer is not a probe that answered "nothing" (2026-08-27).**
The Windows CI lane went red on this lane the day it shipped, and the failure was
worth more than the fix. `_systemctl` asks `is_supported()` before it runs
anything, so on a runner with no systemd the platform gate returned first and
every test that scripted `subprocess.run` never reached its mock. Five failed —
and **six more passed for the wrong reason**, because they assert `0` or
`(None, None)`, which is exactly what the untouched gate returns. Those six were
the real finding: a red test tells you it is broken, while a test that passes
without running its subject tells you nothing forever and looks like coverage
doing it.

Under it sat a live defect. `_systemctl` returned `None` for two different facts:
*this platform has no systemd*, and *this machine has one and it did not answer*.
Both became `supervised_pid() == 0`, "no unit is holding the server". **The
ruling, split in two because the question has two answers.** No systemd on the
platform still answers zero — a machine that cannot have a unit has no
uncertainty to report, so zero is the strongest available answer and `running()`
correctly falls through to the detached record, the only kind of server that can
exist there. But a probe that FAILED on a capable machine now raises
`SupervisorUnreachable`, because the tailnet host runs under a unit that writes
**no record file**: a swallowed probe sends `running()` down the record path and
prints "No server is running" about a server answering requests. Proven live
rather than argued — with the unit genuinely holding pid 227641, forcing the
probe to fail made the old path return `None`.

Each of the three callers wants that refusal: `status` says it cannot tell rather
than inventing an absence, `stop` will not signal into the dark where a restart
policy may undo it, and `serve` will not start a second listener on a port it
cannot see. Only `supervised_bind` swallows it, and only because the pid probe
has already established the verdict — losing the bind costs a status line its
address, not its truth.

---

### The git surface (DPLAN-0303)

*Where it lives: `git_reads.py`. The read lane started as one module and the
git surface grew until it crossed the 1500-line cap, so it split along the seam
that was already there — repository reads in `git_reads.py`, files and
directories and the name fence in `reads.py`. The remote lane lived apart in
`remotes.py` for one reason, that it shelled nothing at all; `drone @git remote
--json` retired that reason on 08-18 and it moved in with the other drone-door
readers. The dependency runs one way: the repository reads lean on the
resolution, never the reverse.*

**Every door here is asked in machine mode — and one of them had been lying.**
Since 08-18 the status, log, show and remote lanes ask `--json` and read the
document, with the document's own `ok` deciding refusals. That is not tidiness.
drone's rendered status line is built as `f"  {status.strip():>2} {path}"` —
their comment calls it *"for the screen only"* — which right-aligns a one-letter
porcelain code into the **second** column. So every index-only change reached
this server already dressed as a worktree one: `M ` arrived as ` M`, `A ` as
` A`, `D ` as ` D`. Measured against the shipped parser before the switch: of
six codes fed through drone's own renderer, **three came back as something git
never said**, and staged-vs-unstaged modify and staged-vs-unstaged delete were
each a single answer. No parsing could have recovered it — the columns were gone
before this process saw them. The refusal split follows the @memory config
precedent: `ok: false` is an **answer** and travels as a 400 in their words;
output that is not one JSON object is a 503, which is also the shape drone's
caller-verification refusal takes, since that one never reaches the door and
leaves its sentence on stderr.

**Measured shut, and said so rather than worked around:** `drone @git diff` has
no `--json` at all, so that half still reads an exit code. `drone @git show
--json` is an **envelope** — its `content` is git show's own text — so the
commit lane still parses that text on structure, and only its failure detection
moved. `drone @git show <ref> <path> --json` returns the file's *contents* at
that ref, not a per-file diff, so the per-file split stays server-side. The
brief for this round expected ~385 lines of scraping to retire; two of the three
doors did not carry what that assumed, and reporting the smaller true number was
cheaper than shipping against a shape nobody had measured.

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
  exactly `--staged` and `--all`; everything else in argv is ignored, `--json`
  included — re-measured 08-18, still the one door with no machine mode. So
  `path` is served by generating the patch and splitting it here, on the
  per-file headers — machine structure, which is the only thing this file still
  parses out of text anywhere. The consequence
  DPLAN-0303 needs to know: **context stays at three lines, not the `-U1` the
  design specified**, because context is baked in at generation time. Asked of
  @drone.
- **`drone @git log` is `--oneline` underneath, `--json` or not.** A row carries
  a sha and a subject and nothing else — no author, no relative date, however
  much a design asks for them; the document has exactly the two fields the
  rendered line had. Re-measured 08-18, and the door does not clamp either:
  asked for 99999 it answered with 1626, every commit in the repository, so this
  lane's own 1–50 refusal is the only thing between a phone and a whole history. Those live in `show`, one commit at a time, and fifty subprocesses each
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

**Status rides per row, in git's vocabulary and not a new one — and since
08-18 the data finally honours the contract.** @devpulse measured the first half
of the gap from the face: the lane read the porcelain code and then *discarded*
it, and untracked files never left the server as anything but a number. `rows[]`
carries every changed path with its code **verbatim and unstripped**, plus
`index` and `worktree` split out beside it. The second half was worse and took
the `--json` door to find: the code being passed through verbatim had *already*
been flattened by drone's screen rendering, so `A ` (staged new) and ` M`
(modified, unstaged) had been the same answer here for as long as rows existed.
All four VS Code chips (M/A/D/U) are derivable from `index` and `worktree` now,
and staged-vs-unstaged is a difference the phone can finally see. Which code means which chip is the face's decision, made once in their
`buildRows`; a letter invented here would be a second vocabulary for a fact git
has already stated. Untracked paths appear in `rows` by name and stay **out** of
`files` and `count` — additive, so @baud's desktop consumer parses exactly what
it always did, and untracked names leaking into the tracked list is the precise
disagreement this lane exists to avoid. Ignored paths are in no list at all.

### The remote lane (DPLAN-0303 phase 4)

*Where it lives: `git_reads.py`. It used to be `remotes.py`; that module is
archived under `apps/handlers/host/.archive/`, kept rather than deleted.*

Phase 4 goes links-first — zero-auth link-cards out to GitHub, built from
constructible URLs — so the face has to be told the repository's remote.

**There was no door for this, which is why the lane existed apart.** Measured
before anything was designed: not a verb on drone's git surface, not on their
public Python surface, and the fleet's own gate refused **both** raw readers,
which is the fleet declining to call them reads. So the lane shelled nothing at
all, read the repository's configuration as the INI file it is, and followed
`.git` pointer files by hand to find it in a worktree. It lived in its own
module so that boundary stayed visible rather than buried under the git roof.

**`drone @git remote --json` shipped on 08-18 and retired all of it** —
including the worktree pointer-following, because git resolves commondir itself.
127 lines of functions went outright: the INI parse, the pointer chase, the
remote selection off raw config. What replaced them is a door call like every
other lane's, so the pin inverted with it: the test that used to assert *no
subprocess is ever spawned here* now asserts this lane routes through drone in
machine mode, and a second pin watches `Path.open` across the whole call to
catch git's own resolution growing back by any spelling.

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

**Credentials never travel, which was not in the ask — and the doctrine
outlived the module that carried it.** drone redacts on their side too; this
lane redacts again on ours, because this process is the last one a URL passes
through before it crosses a network and a rule enforced only by somebody else's
code leaves silently the day their code changes. Every pin asserts what **this**
surface emits, never what upstream sent — including one that hands the lane a
document claiming `redacted: true` while still carrying the token. A remote URL
may carry `user:token@` — that is how a machine clones a private repository with
no human present — and this lane's entire job is handing that URL to a client
over a network. The password half is replaced and the user half survives, so an operator
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

Re-verified after the move to the door (08-18): 16 mutations across the whole
`--json` parse layer, all 16 biting under `PYTHONDONTWRITEBYTECODE`. **Two of
them survived the first pass and were real gaps, not harness noise.** One flagged
every userinfo as a credential and lived, because the only `git@` test used the
scp short form — which carries no `://` and leaves the redactor at its first
line, so it never reached the rule it was meant to pin; an explicit `ssh://git@`
case now does. The other dropped the log's object-name requirement and lived,
because nothing fed it a commit row without a sha. Both pins were added and both
mutations then bit.

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
sentences and flattening them here would make that impossible. A refusal is never
nothing-to-end, and the two never share a shape: an unknown branch is refused
before the exec by `citizen_address`, so it leaves as a **400 `verb_refused`**
carrying no `room` and no `ok` at all, while a refusal spoken by @baud's own
envelope comes back 200 with `ok: false` and their sentence in `detail`. Only
the second one can be mistaken for nothing-to-end, and there `ok` is what tells
them apart.

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
end corrupts both. There are two control verbs. `{"type":"resize","cols":N,
"rows":N}` is refused rather than clamped, and never fatal — a bad geometry must
not drop a room the operator is working in. `{"type":"ping"}` is answered
`{"type":"pong"}` and does nothing else: it exists because a browser cannot send
a protocol-level ping, so without it a phone whose peer vanished without a FIN
reads its socket as OPEN forever. Anything else is logged and dropped.

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

### The settings conformance corpus (FPLAN-0438)

The settings lane is a faithful mirror of @baud's `settings.rs`, and a mirror
drifts. @baud measured six real divergences in one night — by *running* both
implementations, not by reading each other's source — and every one was a place
where the two faces would have written the operator's own config differently
while each believed it was correct.

Prose cannot hold a mirror straight; shared **data** can. `tests/conformance/settings/`
holds 39 cases in plain JSON — starting file state, the operation, the expected
outcome — that each runtime proves it satisfies in its own suite. The python
runner is `tests/test_settings_conformance.py`; a rust `#[test]` walks the same
files with `serde` and no translation, which is the whole design constraint.

Cases carry a per-runtime verdict, so a divergence one side has not closed yet
is **skipped and reported**, never quietly passed. Two differences are recorded
rather than forced: the desktop still accepts a zero compaction window and still
drops unknown patch keys (both freeze-gated on their side), and file mode
genuinely differs — python stages through `mkstemp` and lands `0600` whatever
the umask is, rust inherits it.

**A runtime difference and a platform difference are two axes, and 08-18 proved
it.** Six cases went red the first time the corpus ran on Windows — python on
Windows and rust on Windows hit the identical wall, so a per-runtime verdict
cannot describe it. Cases now carry an optional `platform` block, and every
capability in it is **measured on the machine**, never read off `sys.platform`:

- `unreadable_files` — write a file, `chmod 000`, try to read it. Absent for
  root and on Windows, where the mode only sets a read-only attribute. A case
  that needs it is **skipped with the capability named**, because its starting
  state could not be built and running it would measure the harness.
- `posix_mode_bits` — create with `0600`, read the mode back. Absent on Windows,
  so the mode expectation drops there and the rest of the case still counts.
- `parent_is_a_file_is_distinguishable` — put a **file** where a directory
  belongs and look at what opening through it raises. Where an OS reports it as
  `FileNotFoundError`, the missing-file-reads-blank rule genuinely cannot tell a
  broken tree from a fresh branch, and the read answers blank. That is a **real
  per-platform semantic divergence**, recorded as the expectation for that
  world rather than papered over — verified by feeding the door a
  `FileNotFoundError` and watching it answer blank.

**Digests normalize line endings before hashing, and the manifest says so in a
`digest` field.** git rewrites text files to CRLF on a Windows checkout under
`core.autocrlf`, so a raw byte digest measures which OS ran the checkout rather
than whether a case changed — it went red on the Windows lane with nothing
wrong. A scoped `.gitattributes` pins `eol=lf` as well, but the normalization is
the contract, because a vendored copy in another repository carries its own
checkout rules.

The corpus guards itself, because the failure that matters reports as success: a
manifest pins every case by digest and by count, so an empty corpus and a stale
one are both loud. Two further guards were added when the platform axis landed —
a capability probe that stops finding things would turn cases into *skips*,
which read as green, so a POSIX machine that fails to measure all three is an
error; and the skip path itself is exercised by taking the capabilities away by
hand, because on a box that has them the whole block is unreachable and a
mutation deleting it survived. See its own README for the format.

### The module that must import where it cannot run

`host/attach.py` hosts a PTY running a tmux client. A PTY is a Unix object and
tmux does not run on Windows, so **nothing in that module can work there** —
which is fine, guarded by `PTY_AVAILABLE`, and tested. Failing to **import** is
a different failure, and on 08-18 it cost 22 collection errors on the Windows
lane from one line: `_setsid: Any = os.setsid` in a function signature.

A default argument is evaluated when the module is imported. The three other
POSIX-only names in that same signature were already fetched with `getattr`;
this one was reached for directly, so the platform guard forty lines above it
never got the chance to run — and `server` imports `attach`, `host_api` imports
`server`, so eleven host test files went down across two workers.

Fixed at the line, then pinned two ways rather than one. An AST test asserts no
default in that signature is a bare attribute access, so the *next* one is
caught instead of shipped. And `tests/test_windows_import.py` imports **every**
module under `apps/` in a disposable child interpreter with POSIX hidden — a
`meta_path` finder refuses `fcntl`/`pty`/`termios`/`grp`/`pwd`/`resource`/`tty`
and the POSIX-only `os` attributes are deleted. Verified to bite: restoring the
old line reproduces the exact cascade, three failures from one character of
syntax. The finder matters — patching `builtins.__import__` puts the test file
into the import stack, where the fleet's cross-branch import gate reads it and
blocks the sweep instead of measuring anything.

## Integration Contract System (DPLAN-0133)

Private drivers in `apps/integrations/{project}/driver.py` (gitignored) register named contracts via `bridge.register()`. Callers resolve by name — never referencing private projects directly. `registry.py` handles auto-discovery via importlib.

---

## Known Issues

- Error paths exit `0` — a failed command (missing arg, no key, no data) reports success to the shell, so `drone @api validate && ...` proceeds on failure. Unknown commands correctly exit `1`. See APLAN-0013.
- Google auth libraries are optional deps — commands fail with install instructions if missing
- Backup branch credential migration pending (`~/.aipass/` → `~/.secrets/aipass/`; legacy dir still present)
- No rate limiting on OpenRouter calls (S117 finding)

**Troubleshooting:** `openai`/Google auth `ModuleNotFoundError` despite a working venv → the `[llm]`/`[drive]` extras were added after the venv was last built; re-run `setup.sh` (installs `.[dev,memory,llm,drive]`) to resync, no code fix needed. Both import cleanly as of 2026-08-25 (`openai` 2.49.0, `google.auth` + `googleapiclient`), verified by import alone — no call goes out.

---

*Last Updated: 2026-08-25*

[← Back to AIPass](../../../README.md)
