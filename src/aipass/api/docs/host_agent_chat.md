[<- Back to the README](../README.md)

# The agent chat lane

**Branch** api · **Code** `apps/handlers/host/agent_route.py`, `agent_extras_route.py`, `agent_chat.py`,
`agent_transcript.py`, `agent_models.py`, `agent_usage.py`, `speech.py`

---

The routes a chat panel needs to talk to a live agent: read its transcript as chat lines, see whether it is
working or waiting on a permission prompt, type a line into its BAUD room, and press interrupt, allow or deny.
They are bearer-token routes on the host API ([host_api.md](host_api.md)); reads take `read` scope, anything
that types into a room takes `operate`. Refusals use the host's one error envelope, `{error: {code, message}}`.

## Who an agent is

`<project>/<name>` in the path is the pair `/v1/fleet` and `/v1/roster` name a row by (`AIPASS/devpulse`).
Both segments must be letters, digits, `_` or `-`, not starting with `-`, else **400** `agent_refused`
before any lookup. The agent is looked up in @baud's roster (`baud-cli --roster`, the same exec
`/v1/roster` relays), cached 5 s and single-flight. Not in the roster means not live: **404** `agent_not_live`.

## Routes

| Route | Scope | Request | Answer | Refusals |
|---|---|---|---|---|
| `GET /v1/agent/{project}/{name}/feed?since=<n>` | read | `since` optional, a line's `n` | `{lines: [{n, role, text, time, model?}], busy, waiting: {tool} or null, session}` | 400 `agent_refused`, `agent_feed_refused` (since not a whole number, any other parameter); 404 `agent_not_live`, `transcript_unavailable`; 503 `fleet_unavailable` |
| `POST /v1/agent/{project}/{name}/send` | operate | `{text}` | `{ok: true}` | 400 `agent_refused`, `agent_body_refused` (not JSON), `agent_text_refused` (no text, or nothing left after cleaning); 404 `agent_not_live`; 409 `agent_no_room`; 503 `fleet_unavailable` (no baud binary), `agent_send_failed` |
| `POST /v1/agent/{project}/{name}/interrupt` | operate | `{}` | `{ok: true}` | as send, less the text refusals |
| `POST /v1/agent/{project}/{name}/allow` | operate | `{}` | `{ok: true}` | as interrupt |
| `POST /v1/agent/{project}/{name}/deny` | operate | `{}` | `{ok: true}` | as interrupt |
| `POST /v1/agent/{project}/{name}/model` | operate | `{provider?, model?, effort?}`, a model or a provider | `{ok: true, typed: "<line>"}` | 400 `agent_refused`, `agent_body_refused`, `agent_model_refused` (no model or provider, a field not a string, an unknown model or effort, a switch the seat does not take, a dispatched agent); 404 `agent_not_live`; 409 `agent_busy` (working or waiting), `agent_no_room`; 503 `fleet_unavailable`, `agent_send_failed` |
| `GET /v1/agent/{project}/{name}/usage` | read | none | `{provider, context: {used, total, percent} or null, limits: [{label, percent, severity, resets_at}], note}` | 400 `agent_refused`; 404 `agent_not_live`; 503 `fleet_unavailable` |
| `GET /v1/models` | read | none | `{claude: {models}, codex: {models: [{name, label, efforts}]}, opencode: {models, inline, reason}, switch: {from: {to: takes_model}}}` | 401, 403 only |
| `POST /v1/speak` | read | `{text}` | `audio/L16` stream, rate in `X-Sample-Rate` | 400 `agent_body_refused`, `speak_text_refused`; 503 `speech_unavailable` |
| `POST /v1/screenshot` | operate | none | `{path}` of the saved PNG on the host | 503 `screenshot_unavailable` |

Every route is a `def`: the roster execs @baud, the feed reads up to 4 MB of transcript, the catalog
execs `opencode`, the usage read calls Anthropic, speech runs Piper, and the screenshot waits for the picker.

## The feed

**Where the transcript is.** The roster row's `run.session_id`, else its `resume_id`, names the session.
Claude Code: `~/.claude/projects/<path>/<session>.jsonl`, where `<path>` is the agent's absolute path with
every non-alphanumeric character turned to `-`. Codex: `~/.codex/sessions/**/rollout-*-<session>.jsonl`,
found once and remembered. Any other provider (OpenCode) is **404** `transcript_unavailable`: only Claude
and Codex transcripts are read. A Codex rollout not yet written, or a session file not on disk, is the same 404.

**What a line is.** The last 4 MB of the file is read and each row becomes zero or more lines:

- `user`: a typed prompt. Pasted content is unwrapped to what was pasted; a prompt queued while the agent
  worked shows as its own line. Harness rows (a user row starting with `<`, Codex's own context rows) are left out.
- `agent`: the agent's text, cut at 20 000 characters, with `model`, the model's display name.
- `tool`: one line per tool call, the verb and the key argument, a path by its file name only
  (`edited server.py`, `ran: pytest -q`). A Codex exec script gives one line per call in it (`ran:` for
  commands, `edited` for patches), its stdin polls left out.

**What `n` is.** A line's `n` is the byte offset of its row in the transcript file plus the line's index
within that row. It never changes while the file grows, and it rises through the file, so a client that
polls every 2 s with `since=<last n it holds>` gets only the new lines and keeps its reading position.
Without `since` the answer is the last 80 lines; with it, the last 80 of the lines after `n`.
`n` starts again near 0 in a new session's file: `session` names the file read, and a client that sees it
change drops its `since`.

**busy and waiting.** From the AIPass hooks engine log (`<aipass package>/hooks/logs/engine.jsonl`, its last
256 KB, resolved from the installed `aipass` package), the session's last events decide: a
`PermissionRequest`, a `permission_prompt` notification, or an untyped notification right after a
`PreToolUse` is **waiting** on the last tool named; `Stop`, `SessionStart` or `SessionEnd` is **idle**;
anything else is **working**. With no hook rows for the session, a transcript written under 10 s ago is
working, else idle. `busy` is working or waiting; `waiting` is `{tool}` only while waiting.

## Typing into the room

A send goes through @baud's headless door, never raw tmux: `baud-cli --send-room <name> --project <p>
--text <chunk>`, then `--key Enter`. The agent must have a room of its own (`own_room_live` on its roster
row), else **409** `agent_no_room` (a dispatched seat has none).

1. The text is cleaned: control characters become spaces (a CR would press Enter, an ESC would interrupt),
   then it is trimmed and cut at 20 000 characters. Nothing left is **400** `agent_text_refused`.
2. It is framed as one bracketed paste, `ESC[200~ … ESC[201~`, so Claude Code and Codex read it as one
   paste and the Enter submits it.
3. The frame goes in 2000-character `--text` calls (@baud refuses a longer one), then one `--key Enter`.
4. If a call after the first fails, the frame is closed with one more `--text ESC[201~` and **no Enter is
   pressed**: half a line never submits. Any failed call is **503** `agent_send_failed`; @baud's words go to
   the host log under `ref`.

Keys use the same door, one `--key` call: **interrupt** and **deny** press `Escape`, **allow** presses
`Enter`. Interrupt is the chat's stop button.

## The fleet rows

`GET /v1/fleet` (one project) and `GET /v1/roster` (every project's working agents, what the orb's
rings read) add five fields to every branch row and change none of @baud's (a field @baud already
sent is never overwritten). A row that is working (`interactive` or `dispatched`, the rows the roster
carries) gets:

| Field | Value |
|---|---|
| `state` | `working`, `waiting` or `idle`, as for the feed; `null` when neither the hooks log nor a transcript says |
| `busy` | working or waiting |
| `tool` | the tool a waiting agent is held on, else `null` |
| `model` | the model display name on the transcript's last assistant row (Codex: its last turn context) |
| `delegating` | a `Task` or `Agent` tool started and not yet closed by `SubagentStop`, `Stop` or `SessionEnd` |

Any other row is asleep and answers `state: null, busy: false, tool: null, model: null, delegating: false`.
`provider`, `dispatched` (a boolean) and `subagents` (a count) are @baud's own row fields, unchanged.
The poll stays cheap: the hooks log is read once per request, each live seat costs a stat, and the
model is re-read only when its transcript's mtime moves.

## Switching an agent's model

`POST .../model` types the provider's own line into the agent's room, through the same send as a chat line
(one bracketed paste, then Enter), then presses **Enter once more**: the first Enter only takes the slash
menu's suggestion and the command runs on the second. On an empty prompt Enter does nothing.

| Seat | Body | Line typed |
|---|---|---|
| Claude | `{model}`, one of `opus`, `fable`, `sonnet`, `haiku` | `/model <alias>` |
| Codex | `{model}`, a listed slug; `effort` optional, one the slug lists | `/model <slug>` or `/model <slug> --reasoning=<effort>` |
| OpenCode | any | refused: its `/models` only opens a picker |
| any | `{provider}` other than the seat's, `model` where the table's `switch` says it takes one | the seat's own switch command: `/codex`, `/opencode` (Claude), `$claude`, `$opencode` (Codex), `/claude`, `/codex` (OpenCode) |

`provider` absent or equal to the seat's is a model switch on the same provider. The seat's provider is its
roster row's `provider`, Claude when the row names none. Checked in this order, nothing typed on a refusal:
the body; the agent is live (404); it is not dispatched (a dispatched agent keeps the model it was
dispatched with, 400); the line can be built (400, the reason in the message); it is not working or
waiting (409 `agent_busy`, read as the feed reads `busy`); it has a room (409 `agent_no_room`).

## The model catalog

`GET /v1/models` lists what the switch accepts. Claude: the four aliases. Codex: the rows of
`~/.codex/models_cache.json` (read-only) whose `visibility` is `list`, each with its
`supported_reasoning_levels` as `efforts`; no cache, or an unreadable one, answers empty `models` and a
`reason`. OpenCode: the lines of `opencode models` that hold a `/`, each with its `group` (the prefix),
`inline: false` and `reason: "picker only"`; the listing is kept 60 s. A missing `opencode`, a timeout
(20 s) or a failing exit answers empty `models` and the reason, never an error, and is not kept.
`switch` is `{from: {to: takes_model}}` for the handoff commands above.

## Usage

`GET .../usage` reads one live agent's context window and its provider's plan limits.

- **Claude context.** The transcript's last assistant row with `usage`: input plus both cache counts,
  over a fixed window of **350 000** tokens (`CLAUDE_WINDOW`, the deck's one window; a row does not name
  its own). `null` before the first reply, with the note `no reply yet` when nothing else is said.
- **Claude plan limits.** This route reads the Claude Code sign-in token from the user's own
  credentials file, `~/.claude/.credentials.json` (`claudeAiOauth.accessToken`, `expiresAt`), and calls
  Anthropic's usage endpoint with it: `GET https://api.anthropic.com/api/oauth/usage`,
  `Authorization: Bearer <token>`, `anthropic-beta: oauth-2025-04-20`, 5 s timeout. **The token is never
  returned, never logged, and never in an error**; the answer is cached 60 s keyed by the token's sha256.
  A five-hour limit is labelled `5 hour`, `weekly_all` `All models`, `weekly_scoped` `<model> only`;
  severity is the endpoint's, else `warning` from 75% and `critical` from 90%. No file, no token or an
  expired one answers `limits: []` and a `note` saying which. A **429** holds for its `Retry-After`, else
  5 minutes doubling per further 429 up to 30, makes no call while it holds, and shows the last good
  limits with a note naming when they were read. An unreachable endpoint is `limits: []` and a note.
- **Codex.** Both from the rollout's newest `token_count` rows: context from `last_token_usage` over
  `model_context_window`, limits from `rate_limits.primary` and `secondary`. No network.
- **OpenCode.** `context: null, limits: []`, note `OpenCode usage is not wired yet`.

## Speech

`POST /v1/speak` with `{text}` streams Piper's raw 16-bit mono PCM (`audio/L16`) as Piper makes it,
sentence by sentence, so the first sentence plays while the rest is made; the sample rate is in
`X-Sample-Rate`. The text is cleaned as a chat line is; nothing left is **400**. Piper is
`~/.local/share/piper/piper` with the voice `~/.local/share/piper-voices/en_US-amy-medium.onnx`, its rate
read from `<voice>.onnx.json`; either missing is **503** `speech_unavailable` (Linux installs only).
Closing the stream, or the client hanging up, kills Piper: no orphan process.

It takes `read` scope: it types into no agent and changes nothing on the host, it only makes local
audio for the caller.

## Screenshot

`POST /v1/screenshot` opens the desktop's own screenshot picker on the host, the one the keyboard's
Print key opens, through the XDG portal (`gdbus call … org.freedesktop.portal.Screenshot.Screenshot`,
interactive). The portal answers over D-Bus, which the host does not listen to, so the call waits up to
120 s for a new PNG in `~/Pictures/Screenshots` or `~/Pictures` and answers `{path}`: a host path, which
the client puts behind an `[Image #n]` tag as it does an upload's. No `gdbus`, a refused portal, or no
shot within the wait is **503** `screenshot_unavailable` (Linux desktops only).

It takes `operate` scope: it opens a window on the host's desktop and writes a file there.

## Calls from the browser extension

The extension's side panel and service worker call from `chrome-extension://<id>` with `host_permissions`
for the host's address. The host has no CORS middleware and no check on `Origin`, `Host` or `Sec-Fetch-*`
on any route, so such a call (bearer GET, bearer JSON POST, the `POST /v1/pair` redeem, the `/v1/speak`
stream) is answered exactly as one without those headers.

The extension gets its bearer through `drone @api host-api pair extension [--scope read|operate] [--ttl SECONDS]`:
the same one-use mint as the phone's pairing ([host_api.md](host_api.md), Pairing) under the label
`extension`, `operate` by default (the chat types into rooms), with a loopback bind allowed (the
extension runs on this machine). It prints three plain lines, no QR: `Pairing code: <code>`,
`Host: http://<bind>`, and the expiry. The extension posts `{code}` to `<Host>/v1/pair` and keeps the
bearer it gets back; no bearer is ever printed. Each run mints one code; a second extension runs it again.
