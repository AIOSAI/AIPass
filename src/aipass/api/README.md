[← Back to AIPass](../../../README.md)

# API

**Purpose:** The gateway every branch reaches an outside service through — authenticated clients (OpenRouter, Google), key and secret storage, OAuth flows, usage accounting — and the Stage 0 host API the BAUD phone talks to over the tailnet.
**Module:** `aipass.api`
**Version:** 2.0.0
**Created:** 2026-03-07

---

## Quick Start

```bash
drone @api validate                                     # Is the OpenRouter key good
drone @api models                                       # What this account may call
drone @api call "Summarise this" --model anthropic/claude-3.5-sonnet
drone @api host-api status                              # Is the phone's server up, and who holds it
```

---

## What It Does

- **Hands out authenticated clients.** A consumer imports a ready service — OpenRouter chat, Google Drive, Google Calendar — and never writes an auth flow of its own. Plumbing, never product: what you do with the service is yours.
- **Owns the credentials.** Keys, OAuth tokens and per-provider secrets live under `~/.secrets/aipass/`, owner-only on disk, and are read through this branch. A raw value is never printed to a terminal.
- **Accounts for usage.** Every generation can be tracked by caller, aggregated, and cleaned up on a retention window.
- **Serves the phone.** The host API binds one address this machine holds and answers the BAUD face: reads of the fleet, the git surface, files, settings, a photo upload, a terminal socket into a real tmux room, and a backup door that starts and stops @backup's lanes and reads their status and progress.
- **Pairs a phone by its camera.** `drone @api host-api pair phone --scope operate` prints a
  QR. The phone's camera opens it and the face signs itself in: no token is typed, copied,
  mailed or shown.
  - **What a code is:** a one-use secret in the URL's fragment, which a browser never sends
    to a server. The phone posts it to `POST /v1/pair` and gets a bearer token for the code's
    label and scope. Only the code's sha256 is stored, beside the token store.
  - **Five minutes, one use:** `--ttl` sets 30 to 900 seconds. An unknown, expired or used
    code gets one and the same refusal, and each address is limited to ten tries a minute.
  - **No receipt:** a paired token's only copy is on the phone. `list-tokens` lists it and
    `revoke-token` revokes it like any other.
  - **A reachable address:** a loopback or wildcard bind is refused, with the command that
    fixes it.

  The installer calls the same door, `mint_pairing` and `render_qr`; depth is in
  [docs/host_api.md](docs/host_api.md).
- **Refuses in the open.** A refusal exits non-zero and names the reason. A command that printed a red cross and exited 0 was the defect that started that rule.

Not business logic, not workflows, and never a default model or config — consumers bring their own.

---

## Live Inventory

The modules, verbs and flags are **generated from the code that runs them**, so they are not
written down here and cannot go stale:

- `drone @api` — the self-map: every discovered module, with the version.
- `drone @api --help` — the full command surface: every verb, its arguments and its flags.

---

## How To Reach Me

- Mail: `drone @ai_mail email @api "Subject" "Body"` — a client you need, a credential that
  will not validate, a route on the host API that answers the wrong thing.
- A refusal that exits 0, a value that reaches stdout, or a route that returns 200 on a failed
  read is a bug here, not a fault in your branch. Say which command and what you saw.
- Cross-branch callers import the in-process door rather than shelling out — see
  [docs/clients.md](docs/clients.md).

---

## Commands

There is no command table on this page, deliberately: a hand-typed copy of this branch's own
help output rots the next time a verb is added or a flag changes. The generated surface above
under **Live Inventory** is the current one, and `drone @api host-api --help` covers the host
server's own subcommands.

---

## Architecture

Three tiers. `apps/api.py` is the entry point: it discovers every module under
`apps/modules/`, offers each one the command, and turns a refusal into an exit code. The
modules orchestrate and print — `api_key`, `secrets`, `openrouter_client`, `google_client`,
`usage_tracker`, `bridge`, `integrations_manager`, `registry`, and `host_api` with its three
sub-routers `host_serve` (serve, status, stop, autostart), `host_config_cli` (config,
set-config) and `host_pair_cli` (pair). The handlers under `apps/handlers/` hold the implementation, one directory per
concern: `auth/`, `config/`, `google/`, `openrouter/`, `usage/`, `integrations/`, the shared
`json/` shim bound to prax, and `host/` for the server, its routes and its readers.

A module claims a command by returning `True` from `handle_command()`, which means "I
recognised this", never "it worked" — the exit code carries that, resolved from whether
anything printed an error.

The directory tree lives in this branch's own prompt (`.aipass/aipass_local_prompt.md`) —
one place, so it cannot disagree with itself.

---

## Documentation

Depth lives in [docs/](docs/README.md), one file per surface or handler group:

| Doc | What it covers |
|---|---|
| [docs/clients.md](docs/clients.md) | The in-process Python API other branches import, and the contract registry |
| [docs/host_api.md](docs/host_api.md) | The Stage 0 host API: bind rule, tokens, scopes, routes, the read cache |
| [docs/host_surfaces.md](docs/host_surfaces.md) | Scopes and verbs, the phone face, the fleet snapshot, the terminal socket, uploads, the backup door |
| [docs/host_autostart.md](docs/host_autostart.md) | The systemd user unit, what it installs, and what it deliberately does not |
| [docs/git_surface.md](docs/git_surface.md) | The git reads the phone asks for: patch, changes, log, commit |
| [docs/git_remote.md](docs/git_remote.md) | The remote lane, its two fields, and why credentials never travel |
| [docs/internals.md](docs/internals.md) | Import safety without a working directory, and the settings conformance corpus |
| [docs/decisions.md](docs/decisions.md) | Why this branch is shaped the way it is — the incident record behind the code |
| [docs/SECURITY.md](docs/SECURITY.md) | The security posture of the host API and the credential store |

---

## Integration Points

**Depends On**
- `aipass.cli` — Rich console output, and the error channel the exit code is resolved from
- `aipass.prax` — structured logging, and the json service the local shim binds
- `aipass.drone` — branch and project resolution on the host API's read lanes
- Optional extras: `fastapi`, `starlette`, `uvicorn` (host), `google-auth` and friends (Google)

**Provides To**
- Every branch — authenticated clients, secret reads, usage tracking, in-process
- `@baud` — the Stage 0 host API the phone face is served from and talks to
- `@aipass` — the installer door for the phone face directory and the baud binary

**Credentials** (`~/.secrets/aipass/`): `.env` for API keys, `google_creds.json` and
`google_client_secret.json` for OAuth, `host_api/` for the token store, its receipts and
the pairing store.
Values are never printed; read them through the Python door.

---

**Last Updated:** 2026-10-13

---
[← Back to AIPass](../../../README.md)
