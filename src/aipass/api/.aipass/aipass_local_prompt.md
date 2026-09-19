# API Branch — Local Context
<!-- Before editing or adding to this file: read .aipass/PROMPT_STYLE.md (repo root) — the prompt format rules. -->

# Identity

API — the external API gateway, and the Stage 0 host API the BAUD phone talks to. Consumers import ready-to-use clients; API owns plumbing, consumers own business logic.

# Where things are

 - Inventory: `drone @api` (self-map), `drone @api --help` (full surface), `drone @api host-api --help` (the host server).
 - Depth: `docs/` — one file per surface, indexed from `README.md`. Read one when something breaks, not at startup.
 - Credentials: `~/.secrets/aipass/` — `.env`, `google_creds.json`, `google_client_secret.json`, `host_api/` (token store + receipts).

# Directory tree

```
api/
├── apps/
│   ├── api.py                      # Entry point — module discovery, routing, exit codes
│   ├── modules/                    # Orchestration + CLI
│   │   ├── api_key.py              # Keys: get-key, get-secret, validate, init, list-providers
│   │   ├── secrets.py              # Cross-branch secrets door (in-process)
│   │   ├── openrouter_client.py    # OpenRouter: test, models, status, call
│   │   ├── google_client.py        # Google services: validate google, reauth google
│   │   ├── usage_tracker.py        # track, stats, session, caller-usage, cleanup
│   │   ├── bridge.py               # Generic contract registry (register/resolve)
│   │   ├── integrations_manager.py # integrations list / call
│   │   ├── registry.py             # Driver auto-discovery (load_drivers)
│   │   ├── host_api.py             # host-api router + the cross-branch door
│   │   ├── host_serve.py           # host-api sub-router — serve/--detach, status, stop, autostart
│   │   └── host_config_cli.py      # host-api sub-router — config, set-config
│   ├── handlers/                   # Implementation
│   │   ├── module_root.py          # module_file() — the one guarded __file__ resolve
│   │   ├── auth/                   # env.py, keys.py, secrets.py
│   │   ├── config/provider.py
│   │   ├── google/                 # auth.py, service_factory.py, retry.py
│   │   ├── openrouter/             # caller.py, client.py, models.py, provision.py
│   │   ├── usage/                  # aggregation.py, cleanup.py, tracking.py
│   │   ├── integrations/           # list.py, call.py
│   │   ├── json/json_handler.py    # The fleet's one json service, bound to prax
│   │   └── host/                   # config.py, tokens.py, server.py, verbs.py, reads.py,
│   │                               # git_reads.py, fleet.py, face.py, feed.py, attach.py,
│   │                               # pump.py, uploads.py, statics.py, settings.py,
│   │                               # lifetime.py, autostart.py, read_cache.py, refusals.py,
│   │                               # machine.py, lock.py, memory_config.py
│   └── integrations/               # Private driver space (gitignored)
└── tests/                          # conformance/settings/ holds the shared goldens
```

# Design rules

 - Not auth, credentials, or a service factory → it does not belong here (DPLAN-0036; the old Telegram anti-pattern).
 - One module per provider, one handler directory per provider. Module orchestrates, handlers implement.
 - No default models or configs — consumers provide their own. API provides the connection.
 - The server owns the pipe, never the meaning: a host route proxies the branch that owns the data (verbs.py D0).
 - Handlers never print. Facts belong in a handler, presentation in a module — seedgo refuses the other way round.

# Gotchas

 - `handle_command()` returning True means "recognised", never "worked". The exit code is resolved from cli's error flag: 1 unrecognised, 2 recognised-and-refused, 0 only when nothing printed an error.
 - Google libraries are optional deps behind `GOOGLE_AUTH_AVAILABLE`; host extras (`fastapi`, `starlette`) resolve locally and vanish in CI unless the module carries the suppression header.
 - Secrets never reach stdout. `get-secret` prints a masked summary; programmatic reads go through `modules/secrets.py`.
 - The phone face is resolved once at `create_app` (restart to change it); the baud binary is resolved per request (no restart).
 - Expensive host reads go through `read_cache.py` — single-flight plus TTL. A refusal must be raised inside the producer, never returned, or the refusal gets cached.
 - `os.access(X_OK)` is always true on Windows; those tests carry a posix skip.
 - No module may need a working directory to import: route module-level path resolves through `module_root.module_file()`.
 - Server file cap is 1500 lines — the next host route splits into a router.

# Habits

 - Before build or edit work: `drone @trigger medic mute @api`.
 - Before reporting complete: `drone @seedgo audit aipass @api`, plus `drone @seedgo checklist <file>` on each changed file.
 - Tests: edit existing files only — a hook gate refuses new test files. Mail @devpulse with the defect a new file would pin.
 - Prove a cure red-first, then green, and mutate the production line the test claims to hold.
