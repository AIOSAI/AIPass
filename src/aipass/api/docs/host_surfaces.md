# The host surfaces — scopes, verbs, the face, the fleet, the terminal and uploads

**Branch** api · **Code** `apps/handlers/host/` (`verbs.py`, `face.py`, `fleet.py`, `attach.py`, `pump.py`, `uploads.py`)
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

---

**Browsing is free; the terminal binds to the seat.** Every READ route serves any
project @baud's census knows — `files`, `dir`, `diff`, and the fleet routes that
already did. It used to refuse all but the seated project: `/v1/fleet?project=BAUD`
painted the cards; every file under them then refused with *"This server is seated in
AIPass and does not serve project BAUD"* — one surface answering two questions about
the same project. The owner's ruling, 2026-08-16: *"I should be able to open another
project via the project tab drop down, and view other agent project files, open any
passport and view watch read files. no restriction."* **Operate routes are untouched**
— attach is the only takeover, and binds to the seat.

The seat is the default *and the fast path*: an omitted `project`, or the seat's own
name in any case, resolves through the local citizen registry with no subprocess.
Anything else goes through @baud's census, source of the branch's real path — this
server never composes a filesystem path for a project it is not seated in. A foreign
name travels **verbatim**, so their census keeps the one ruling on how a name is
matched (case-sensitive there, the seat not — see the verb lane below for the third
variant, and no, those three have not been reconciled). The per-branch name fence is
unchanged: free browsing is free browsing of *branches*, not of the disk.

**`project` travels on every verb that names a target, and is never inferred** from
this server's seat — @baud's rule, paid for with a killed session: a room name
resolved against the wrong project names a *different* room. Deliberately stricter
than the read lane, where an omitted project means the seated one. The seat is matched
case-insensitively: the wire says `AIPASS`, the directory `AIPass`, and a
case-sensitive check would refuse every verb the phone sends.

**The verbs reach any project too — one terminal, any agent.** The owner's ruling,
2026-08-16: *"the flow is ONE terminal; it hosts the agent I choose, no matter where I
spawn it… Baud is an aipass tenant in `projects/`, vera is outside, external - that
should NOT matter. When you block you create friction."* So the seat check is gone from
`wake` and `kill`, and a foreign branch resolves through the **read lane's** resolver —
one implementation of where a branch lives, inherited by the operate lane, not copied.
**Attach already did this**: its external door shipped with the attach train, so that
half was regression pins, not a fix. `lock` has no project — it locks *this* machine.

**Requiring the project got MORE important, not less:** an inferred seat was merely
sloppy when only one project could be meant. The ruling widens *who* can be reached,
never *what a request may contain* — operate scope everywhere, garbage refused before
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

**Kill goes through the one door, and the gate is why.** For one day this verb answered
503 naming a seam that did not exist: @baud's binary opted into headless mode for
`--snapshot` and nothing else, and `tmux kill-session` was one line away. The owner ruled
`room_kill` the ONE door that ends a session, so it waited. @baud shipped `baud
--end-room <branch> --project <name>` the same evening, proving the single-mechanism
claim instead of asking to be trusted on it: the flag and the desktop button reach the
same kill, the resolved project passed as an argument to the shared half.

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

**Where the face comes from (FPLAN-0587).** An installed AIPass has no checkout to build
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

**Which baud binary the host lanes exec (FPLAN-0589).** The desktop `baud` links GTK and
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
because nobody reimplements them. A first build, capture-and-repaint polling, was cut before
shipping — a repaint shows a picture that updates, an attach shows the room. `-A` is
attach-*or-create*, so a phone and a desk never land in two rooms with one agent's name.

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
left the room deaf: every resize landed in the kernel and reached nobody while `tmux
list-clients` sat at 80x24 forever. The `preexec_fn` does the `setsid` itself, keeping that
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
session to take over. Until 2026-08-16 that form was *unreachable*: the charset fence refused
an empty string and the argv builder always appended a target, so @baud shipped the phone's
door **disabled** rather than aiming it at one branch's monitor, which would have rendered
perfectly and been a lie. The fence is mirrored from their `pty.rs` character for character
and still refuses the empty string; whether a target was *named at all* is a different
question, asked once before the fence is consulted. @prax also documents `run all` for the
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
a password; attach and detach are recorded, their contents are not.

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

Push (`/v1/notify`) is reserved, not built. See FPLAN-0411.

Requires the optional `[host]` extra (`fastapi`, `uvicorn`); commands fail with install
instructions if it is absent.

---

---

[← api README](../README.md)

---

[← api README](../README.md)
