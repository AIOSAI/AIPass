# Gateway Boundary
**Status:** v1.1 (the secrets-store arm)
**Date:** 2026-10-22

---

## What It Is

A branch writes its own private storage. Another branch's storage goes through
that branch's door. The secrets store at `~/.secrets/aipass` is @api's alone:
outside `src/aipass/api/`, a file never imports it, builds a path into it or
calls into it. Agents get actions, never values.

Scope: production files (`APPLIES_TO = "production"`), one file at a time
(`AUDIT_SCOPE = "all_files"`), the per-file audit corpus (`apps/`, `shared/`).

## What the Checker Scans For

### Owned filenames and private storage roots (writes)

A write whose target path resolves to a filename another branch declares
(`aipass-hooks-muted` is @hooks', `settings.local.json` is @aipass') or into a
private root (`.seedgo/`, `.daemon/`, `.spawn/`, `.flow/`, `.ai_mail.local/`)
the file's branch does not own, with no sign of a door (`drone`,
`route_command`, `subprocess`). Names are tainted from the foreign literal and
followed through helpers that return one; a read or a mention is never a row.

### @api's secrets store (imports, paths, calls)

Outside @api, any of:

- an import of `aipass.api.apps.modules.secrets`,
  `aipass.api.apps.handlers.auth.secrets`, `...auth.keys` or `...auth.env`, in
  any form: `import`, `from ... import`, `from aipass.api.apps.modules import
  secrets`, or the module name handed to `importlib.import_module()` /
  `__import__()`;
- a `/` whose one side is the literal `.secrets` (or `.secrets/...`):
  `Path.home() / ".secrets" / "aipass"`;
- a literal containing `/.secrets` handed to `Path`, `PurePath`, `PosixPath`,
  `open`, `expanduser`, `expandvars`, `join` or `joinpath`:
  `os.path.expanduser("~/.secrets/aipass/.env")`;
- a call to `get_secret`, `set_secret`, `list_secrets` or `get_api_key` bound
  from those modules, by name or as an attribute of the imported module.

One row per file, at the first reach, the line quoted. The cure: ask @api for
the action through a drone door.

**Not a row:** a `.secrets/` string that is a pattern, not a path, such as
backup's `drive/floor.py` never-leaves tuple; the store named in prose, a
docstring or a printed message (`aipass doctor`'s "protect ~/.secrets/");
a module name held as data in a table. A literal is judged only as an argument
to an importer or a path maker.

**Not read:** a path to the store assembled at run time from parts that are not
literals, and a reach through a sibling module (`telegram/notifier.py` reads
its token through `config.load_bot_config`; `config.py` is the row).

**Fleet, 2026-10-22 (1,670 production files outside @api):** 5 rows, all the
retired Telegram relay: `prax/apps/modules/monitor.py:196`, and in
`skills/lib/telegram/` `apps/handlers/config.py:36`, `bot_factory.py:53`,
`botfather_client.py:64`, `telethon_auth.py:22`. The four under `lib/` sit
outside the per-file audit corpus; the checklist names them.

## Scoring

100 with no row; each row costs 25.

## Bypass

`.seedgo/bypass.json`, key `gateway_boundary`, file and line, with the reason.
