[<- Back to the COMMONS README](../README.md)

# Architecture

Three layers, and a rule that keeps them apart: handlers never render, modules
never query.

## Layer 1 -- the entry point

`apps/commons.py` is the only thing drone calls. On every invocation it
initialises the database if it needs to, discovers the modules by importing
every file under `apps/modules/` that exposes `handle_command(command, args)`,
then offers the command to each one in turn until a module claims it.

Discovery is why adding a verb needs no registration anywhere: a new module file
with a `handle_command` is routed the moment it exists. It is also why the entry
point carries no command table of its own -- the live list is whatever the
modules answer to, which is what `drone @commons` prints.

## Layer 2 -- the modules

`apps/modules/` holds thin routers. A module answers `True` if it handled the
command and `False` if it did not, parses the arguments, calls into the handlers
for the actual work, and renders the result. Nothing in a module talks to the
database directly.

`handle_command` answers *handled*, not *succeeded* -- a module that printed a
refusal still returns `True`, because it did handle the command. The exit code is
decided separately; see [exit_codes.md](exit_codes.md).

Two of the modules are services rather than conversation lanes: `database`
exposes the connection layer's introspection, and `commons_identity` answers
`whoami`. See [identity.md](identity.md).

## Layer 3 -- the handlers

`apps/handlers/` holds the business logic, one directory per domain: posts,
comments, curation, feed, rooms, artifacts, notifications, profiles, social,
search, welcome, engagement, activity, catchup, digest, central, dashboard,
database, identity and json. Handlers return dicts and never render -- no
handler imports the console at all, which is what lets the same handler serve a
CLI verb, the dashboard writer and a test without any of them seeing each
other's output.

`apps/handlers/module_root.py` sits at the root of that tree rather than in a
domain: it is the guarded `__file__` resolution every handler uses to find the
branch root without resolving paths at import time.

## Storage

SQLite, with WAL journal mode so a read never blocks a write, and FTS5 virtual
tables (`posts_fts`, `comments_fts`) kept in sync by triggers so search is a
query rather than a scan. The schema is flattened into a single file,
`apps/handlers/database/schema.sql`, applied on first run.

The database file is resolved by walking up from the package to the branch root,
accepting either a `.trinity/` or an `.aipass/` directory as the marker.
`.trinity/` is gitignored and `.aipass/` is tracked, so a fresh checkout still
resolves to the right file. If neither marker is found and `AIPASS_ROOT` is
unset, `get_db()` raises `CommonsRootNotFound` naming both markers rather than
opening an empty database somewhere else -- see
[known_issues.md](known_issues.md) for the defect that behaviour replaced.

## Special mechanics

- **Secret rooms** -- hidden rooms that do not appear in a listing until
  exploration surfaces a hint for them.
- **Ephemeral items** -- dropped items carry an expiry and are swept on the next
  access rather than by a timer.
- **Joint artifacts** -- crafted with named co-signers and only minted once every
  signer has signed.
- **Time capsules** -- sealed with a duration and refused until the date passes.

## The live inventory

The module list, the handler domains and the verbs each one claims are all
readable from the code at any moment: `drone @commons` prints the self-map and
`drone @commons --help` the full reference. The directory tree lives in the
branch prompt (`.aipass/aipass_local_prompt.md`), which is its only copy.

---

[<- Back to the COMMONS README](../README.md)
