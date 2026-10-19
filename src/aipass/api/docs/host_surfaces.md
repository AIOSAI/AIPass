[<- Back to the README](../README.md)

# The host surfaces — scopes, verbs, the face, the fleet, the terminal, uploads and backup

**Branch** api · **Code** `apps/handlers/host/` (`verbs.py`, `face.py`, `fleet.py`, `attach.py`, `pump.py`, `uploads.py`, `backup.py`)

---

**Browsing is free; the terminal binds to the seat.** Every READ route serves any
project @baud's census knows — `files`, `dir`, `diff` and the fleet routes — so the
files under a card answer for the same project the card does. **Operate routes keep
their own rules** — attach is the only takeover.

The seat is the default *and the fast path*: an omitted `project`, or the seat's own
name in any case, resolves through the local citizen registry with no subprocess.
Anything else goes through @baud's census, source of the branch's real path — this
server never composes a filesystem path for a project it is not seated in. A foreign
name travels **verbatim**, so their census keeps the one ruling on how a name is
matched (case-sensitive there, the seat not — see the verb lane below for the third
variant; the three are not reconciled). The per-branch name fence is
unchanged: free browsing is free browsing of *branches*, not of the disk.

**`project` travels on every verb that names a target, and is never inferred** from
this server's seat — @baud's rule: a room name resolved against the wrong project
names a *different* room, and a verb sent there acts on it. Deliberately stricter
than the read lane, where an omitted project means the seated one. The seat is matched
case-insensitively: the wire says `AIPASS`, the directory `AIPass`, and a
case-sensitive check would refuse every verb the phone sends.

**The verbs reach any project too — one terminal, any agent**, wherever it lives: a
tenant in `projects/` or an external tree. `wake` and `kill` carry no seat check, and a
foreign branch resolves through the **read lane's** resolver — one implementation of
where a branch lives, inherited by the operate lane, not copied. Attach reaches external
projects through its own external door, pinned by regression tests. `lock` has no
project — it locks *this* machine.

**Requiring the project matters more because any project can be meant.** Reach widens
*who* can be reached, never *what a request may contain* — operate scope everywhere, garbage refused before
any spawn, unknown branch or project refused in the census's own words, per-branch path
fences untouched.

**The verb lane owns no mechanism.** `verbs.py` imports no subprocess machinery, so it
*cannot* run a program: every verb reaches its mechanism through a door the owning
branch published, and no path exists by which this server grows its own copy of
somebody else's verb on a night when a seam is missing.

**`admin` is unreachable, not merely unset.** `wake_branch()` takes an `admin` keyword
its own docstring calls "an ALREADY-DECIDED verdict" from a caller that ran a five-leg
grant check; a phone cannot run that check. Hardcoding `False` holds until someone
edits the line; `drone @ai_mail dispatch wake` holds structurally, parsing `--fresh`,
`--sender` and `--model` and nothing else. `--sender` is never forwarded either (it
reaches a privilege-bearing parameter behind a verified-caller check), and `--model`
never exists — the phone contract carries zero vendor words by ruling.

**Kill goes through the one door.** `room_kill` is the ONE door that ends a session, by
the owner's ruling, so the verb execs @baud's `baud --end-room <branch> --project <name>`
and never `tmux kill-session`: the flag and the desktop button reach the same kill, the
resolved project passed as an argument to the shared half.

**`ended` is a fact, not a success flag.** `ended: true`: a live session was ended.
`ended: false` with `ok: true`: nothing to end — the goal state, not a failure. Both
travel: the phone shows different sentences, and flattening them here would make that
impossible. A refusal is never nothing-to-end, and the two never share a shape: an
unknown branch is refused before the exec by `citizen_address`, leaving as a **400
`verb_refused`** with no `room` and no `ok` at all, while a refusal spoken by @baud's
own envelope comes back 200 with `ok: false` and their sentence in `detail`. Only the
second can be mistaken for nothing-to-end; there `ok` tells them apart.

The exec lives in `fleet.py`, which already owns @baud's binary — one resolution, one
cwd rule, one parser for their envelope, and what keeps `verbs.py` clean.
`verbs.KILL_SEAM_READY` remains an operational kill switch: closed means a 503 saying
the switch is closed, never a session quietly not ended and reported as fine.

**The face is served here, not cross-origin.** @baud's `dist-phone` bundle is served
from this server, so no CORS allow-list to publish and nothing to misconfigure — the
option with no configuration cannot be misconfigured. The page needs no token: a browser
doing a top-level navigation cannot send a bearer header, so gating it would mean a
second, weaker auth system guarding a public bundle that renders a token door and
nothing else. Every byte of data stays behind `/v1/*`. The bundle is served precisely —
`/assets` mounted, each bundle-root file routed by name — never a catch-all that could
shadow the API.

**Every stable-named file revalidates.** `phone.html` (the manifest's `start_url`), the
manifest and the icons are replaced in place by a build and carry `cache-control:
no-cache`; with no cache-control a browser guesses a heuristic freshness, and a stale
un-hashed entry fetches stale hashed assets. Those routes answer `If-None-Match` and
`If-Modified-Since` with starlette's own comparison, since `no-cache` only means "ask
first" when the server answers the question. `/assets` keeps its caching: a hashed name
cannot go stale.

**Where the face comes from.** An installed AIPass has no checkout to build
the phone in, so the directory is a setting: `face_dir` in the host config, set by `drone
@api host-api set-config --face-dir <dir>` or by @aipass's `aipass baud install` via
`config.set_face_dir()`. Unset, the server serves @baud's checkout build
(`projects/baud/app/dist-phone`) as always; `--face-dir default` clears it. Bind-rule
doctrine: refused before storing unless absolute, a directory, holding `phone.html`.
`host-api config` shows the effective dir, its source (`configured` or `checkout`),
whether `phone.html` is there. A configured dir emptied since is a 503 naming that dir
and its fixes, never a quiet fall back to the checkout build. **Known limit:** the face
resolves once, at app creation, so a running server needs a restart for a new dir —
deliberate: `/assets` mounts one bundle, and a `phone.html` re-resolved per request could
name assets that mount lacks.

**Why the feed cursor is a timestamp:** `notifications.jsonl` is trimmed 400→200 lines
and the trim replaces the file, so a line or byte offset goes stale under any reader —
the 10-hour Telegram outage's shape. The cursor clamps at both ends and re-delivers the
boundary event: a duplicate alert is a nuisance, a dropped one defeats the app.

**Names, not paths:** `/v1/files` has no path parameter. The client names a branch; the
server resolves it through the citizen registry, removing the traversal class, not
mitigating it. Containment is still checked underneath: a "name" can lie, a symlink can
point out of the tree.

**Fleet is a pipe, not a model.** `/v1/fleet` shells `baud --snapshot` and returns
@baud's envelope with no adapter: this server never computes what an agent's state means,
a second answer to "is this agent alive" eventually disagreeing with the desktop and
neither being trusted. `has_room` is filtered on, never derived; `live_agent_sessions` is
served raw, not joined to the branch list. Which BAUD binary runs is below.
`fleet.SNAPSHOT_READY` remains a kill switch: off means **503 with a reason**, never a
synthesised fleet.

**Which baud binary the host lanes exec.** The desktop `baud` links GTK and
webkit even for `--snapshot`, so a headless host has nothing to run; @baud's `baud-cli` is
the same crate's six verbs with no GTK. Every fleet, census, roster and room exec resolves
the binary **per request** — a config read and a few stats — so a binary installed while
the server runs is used on the next request, no restart (the face, by contrast, resolves
once). First hit wins:

1. `baud_bin` in the host config — `drone @api host-api set-config --baud-bin <path>`,
   or `aipass baud install` in-process. Validated before storing: absolute, exists,
   a regular file, executable. **If it is later gone or not executable the lane
   refuses by name** with the cure (`--baud-bin default`), never falling past it.
2. `~/.aipass/baud/bin/baud-cli`, where `aipass baud install` lands it.
3. The checkout's `projects/baud/app/src-tauri/target/release/baud-cli`.
4. The checkout's `.../release/baud`, the desktop binary the launcher execs.
5. `baud-cli` on PATH, then 6. `baud` on PATH.

An automatic location counts only when it holds an executable file. When nothing answers,
the 503 names every place it looked, in order, ending with `Install it: aipass baud
install.` `host-api config` shows `binary: <path>
(configured|installed|checkout|path|missing)` and whether it is executable.

**Aliveness is `live_agent_sessions`, and only that.** Three fleet fields, three questions:
`has_room` means a BAUD-named session *exists* (an empty room is `has_room: true`),
`outside_room` names a session BAUD did not create, `live_agent_sessions` is the
process-table read. Rendering "alive" from `has_room` puts a green circle over an empty
room. No aliveness signal is synthesised here: the only field a client can read it from is
the one that means it — pinned by test at @baud's request.

**The terminal lane gives you the room, not a picture of it.** `WS /v1/room/attach` spawns
a PTY running `tmux new-session -A -s baud-<branch>`, the desktop's argv. The phone becomes
a real tmux client: scrollback, colour, cursor position and full-screen programs all work
because nobody reimplements them. There is no capture-and-repaint polling — a repaint
shows a picture that updates, an attach shows the room. `-A` is
attach-*or-create*, so a phone and a desk never land in two rooms with one agent's name.
A room name outside `[A-Za-z0-9_-]`, or opening with `-`, is refused before tmux runs.

**A room born here matches one born at the desk.** The attach command chains `set-option -t
<room> mouse on` and `set-option -w -t <room> window-size smallest` — @baud's measured
settings, so the phone-only path does not get the worst geometry of the two doors. Every
chained command carries **its own `-t`**, pinned by a test: a `set-option` with no target
resolves against whatever tmux calls the current session, and parses and exits 0 either way.

**Disconnect is SIGHUP to the client, which is a detach.** The session, the agent inside it
and its scrollback survive — what makes closing a sheet on a phone free. This module never
calls `kill-session`, never reaches for `SIGKILL`, and a test *parses* it to prove no string
it evaluates contains "kill". Ending a room stays one door: `/v1/verbs/kill` → `baud
--end-room`.

**The child takes the PTY as its CONTROLLING terminal — that is what makes resize work at
all.** `TIOCSWINSZ` delivers `SIGWINCH` to the foreground process group of the *controlling*
tty, and inheriting an already-open descriptor never acquires one, so `start_new_session=True`
alone leaves the room deaf: every resize lands in the kernel and reaches nobody while `tmux
list-clients` sits at 80x24. The `preexec_fn` does the `setsid` itself, keeping that
flag's signal isolation and gaining the terminal. The initial size is stamped on the master
*before* the child exists: `openpty` hands back 0x0, and a client reading that has already
chosen its fallback.

**Binary frames are keystrokes, text frames are control** — a split that lets a resize ride
the same socket without being mistaken for something the operator typed. Bytes are forwarded
undecoded both ways: the room emits escape sequences and partial UTF-8 across chunk
boundaries, and decoding either end corrupts both. Two control verbs.
`{"type":"resize","cols":N,"rows":N}` is refused rather than clamped, never fatal — a bad
geometry must not drop a room the operator is working in. `{"type":"ping"}` is answered
`{"type":"pong"}` and nothing else: browsers cannot send a protocol-level ping, so without it
a phone whose peer vanished without a FIN reads its socket as OPEN forever. Anything else is
logged and dropped.

**Scope is `operate`, with no reading half.** An attached room is a shell prompt, so no
read-scope attach to offer. `kind=watch` is the exception and the reason the rule can stay
strict: a watch is `drone @prax monitor run` on a read-only PTY whose `write` refuses, so
observation is what the **read** scope *is* — demanding operate for it would make the read
token a lie.

**A watch with no branch is global mission control**, the one lane here where an absent
branch is a real answer, not the bug that killed a live session. `drone @prax monitor run`
with nothing after it watches every branch — the desktop's default pane — and names no
session to take over. The fence is mirrored from their `pty.rs` character for character
and still refuses the empty string; whether a target was *named at all* is a different
question, asked once before the fence is consulted. A target starting with `-` is refused besides:
past the fence it would reach drone as a flag, and `--relay` starts the Telegram relay. @prax also documents `run all` for the
same thing; this lane deliberately does not use it — the desktop's argv is what is mirrored.

**The bearer rides `Sec-WebSocket-Protocol`, never the query string.** A browser cannot set
an `Authorization` header on a WebSocket, and a token in a URL is a credential written to
access logs, proxy logs and browser history — three copies nobody chose. The client offers
`["aipass.bearer", <token>]` and the server echoes back only the sentinel: the accepted
protocol appears in the handshake *response*, where a token would just move the leak.

**Refusals split by who can fix them.** Auth fails *before* accept, so no PTY is spawned for
an unauthenticated caller. After auth, refusals ride an accepted socket with a close code and
a readable reason — `1008` theirs, `1011` ours — since a browser only surfaces a reason on an
established socket, and a pre-accept refusal would put a fixable sentence where the phone
cannot show it.

**The stream is never logged.** Room output is the operator's screen and client bytes may be
a password; attach and detach are recorded, their contents are not. Every detach names the
room, how long the socket lived and the code it closed on — `room ended` when the room ended
first (close `4000` to the client), a different detach from any a client can cause. Typing
into a read-only watch closes the socket `1008` and leaves a `host_api_input_refused` record.

**The pump waits for the FIRST direction to end, not both.** Waiting for both deadlocks on a
quiet room: the phone closes the sheet, the socket reader ends, and the PTY reader stays
parked in a blocking `os.read` until the room happens to print something — so the detach, the
SIGHUP and the executor thread all wait on output that may never come. The hangup runs first
in the teardown, closing the descriptor being what breaks the blocked reader out; cancelling
the task would not, a thread inside a syscall not noticing an asyncio cancellation.

**The photo lane is one route and no new mechanism.** `POST /v1/files/upload` writes an image
to `~/Pictures/BAUD/`, where the desktop's own captures land, and returns its absolute path.
That path is the entire product: the phone types it into the already-open attach socket
through @baud's existing `deliverPaths`, never appending Enter. Images by path, so the path is
the delivery.

**The server names the file; the client cannot.** An upload's filename is attacker-controlled
and no sanitiser is worth trusting against every form of `../`, so it is not sanitised — it is
never read. The name is a timestamp plus a random suffix, and the extension comes from the
**sniffed magic bytes**, not the declared `Content-Type`, so a `.png` on disk cannot hold
something that is not a PNG. Same ruling as the name fence in `reads.py`, one step further: a
parameter that does not exist cannot be exploited.

**The 25MB cap refuses and is checked twice** — against the declared `Content-Length`, so an
oversized body is refused before it is read, and against the running total while reading,
`Content-Length` being a claim and a chunked upload having none. A refused upload leaves no
partial file behind. Uploads are created `0o600` via `os.open`, not narrowed afterwards.

`python-multipart` is a second optional dependency inside the `[host]` extra. FastAPI raises
at route-registration time without it, so the import is guarded and the route registered
either way — answering 503 with the install hint, a 404 on a route that should exist reading
as "wrong URL".

**The backup door proxies @backup and owns no backup.** `POST /v1/backup/run`,
`POST /v1/backup/cancel`, `GET /v1/backup/job` and `GET /v1/backup/status` (`backup.py`,
hung on the app by `backup_route.py`) reach `drone @backup` through drone's router and
nothing else: a run is `drone @backup <lane> <root>` (`--quiet` on every lane but
`drive_sync`, which has no such flag); a cancel is `drone @backup stop <root> <lane>`;
status is `drone @backup status <root> --json [--sizes]`, passed through with `project`
and `root` added.
The root comes from the read lane's resolver, the seat in any case or a census name, so
@backup is handed a path this server did not compose and never a `@name`. A status answer
that is not one JSON object is a 503 saying `--json` is not on this machine; the Rich panel
is never scraped.

**A job is `{job, project, lane, state, started_at}`**; a finished one adds `finished_at`,
`exit` (`null` when the lane never answered), `summary` and `error`. Refusals ride the
`{error: {code, message}}` envelope: **400 `verb_refused`** (no or unknown lane or
project, the lane already running) says its sentence; **503 `verb_unavailable`** gives a
fixed sentence and a `ref` into this host's log.

**`running` is @backup's list** (its running files: terminal and daemon runs too), entry
for entry, each with `job`: this server's id for a run it started there under the entry's
`verb`, else `null`. No `running` key (older @backup): this server's in-flight jobs and one
log line. Not a list of objects: 503.

**Cancel never touches the job table.** `stop` runs on the request thread (60 s timeout,
over @backup's 30 s wait); the job closes when its lane exits.

**Start and poll, because a lane outlives a request.** A lane can take minutes and its
timeout is 30 minutes, longer than a phone keeps a request open. So the run answers **202** with the job at once and runs the lane on a worker
thread; the phone polls the job every few seconds. One job per project and lane runs at a
time, the second a 400 naming who started first and when; different lanes overlap and
@backup's own locks decide the rest. `summary` is the last 600 characters of the output,
verbatim. A job ends `done` (exit 0), `stopped` (130) or `failed` (anything else). A run that never reached @backup is a 503 and opens no job; one that died behind
the door is a `failed` job with drone's sentence in `error`.

**A restart forgets every job.** Jobs live in the server's memory, and a finished one is
dropped after an hour. A forgotten id is **404 `job_unknown`**, and the phone then reads
`/v1/backup/status`, whose answer comes from @backup's store and survives everything.

Requires the optional `[host]` extra (`fastapi`, `uvicorn`); commands fail with install
instructions if it is absent.

---

[← api README](../README.md)
