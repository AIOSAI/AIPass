# Rollover limit config verbs

**Branch** memory · **Code** `apps/modules/rollover.py` (the config verbs), `apps/handlers/json/config_loader.py`, `apps/handlers/json/budget.py`, `apps/handlers/cli/json_flag.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

`drone @memory config` is the verb surface over the rollover entry-count limits in
`memory.config.json`, so nothing hand-edits that file (DPLAN-0302). @api execs these verbs to serve
the BAUD settings panels, which makes **the CLI output and the refusal sentences the API contract** —
change them and something downstream breaks.

---

## The verbs

Bare `drone @memory config` introspects — it names the three verbs; `config --help` prints the full
usage, including a BOUNDS block that reads the live ceilings.

| Verb | What it answers |
|---|---|
| `config get` | Defaults + every branch that deviates |
| `config get @devpulse` | One branch's EFFECTIVE limits, each marked |
| `config set @devpulse sessions 25` | Override one branch |
| `config set-default sessions 25` | Change the global default |

Each of those takes `--json`, and so does `rollover push` — the machine surface below.

**Settable types — exactly three:** `sessions`, `key_learnings`, `observations`. `auto_compact_cap`
is displayed read-only and preserved across writes, but is not settable in v1. The todos count is the
same: `config get` shows it (`read_only: true` under `--json`), and `set` / `set-default` refuse it —
`'todos' is display-only in v1: config get shows its count, config set cannot change it`.

**Bounds:** `1 <= count <= 100`. Zero would roll over every entry immediately; past 100 rollover
stops being rollover. Unknown branches are refused against the registry — registry is truth. That
flat bound is no longer the whole story: a count also has to fit its FILE, which is the ceiling
below and is always the lower of the two.

**Effective limits resolve per FILE KEY, not per leaf key** — `config get` mirrors
`monitor/detector.py` `_should_rollover` exactly. If `per_branch[branch]["local"]` exists at all,
`defaults["local"]` is never consulted for that branch, so a per-branch entry carrying only
`sessions` leaves `key_learnings` with *no* limit rather than the default one. A deep merge here
would report a limit the engine does not enforce; `test_matches_the_detector_on_a_real_file` pins
the two together with the engine as the oracle.

**`[OVERRIDE]` is decided by VALUE**, not by provenance. `rollover push` materializes a
`per_branch` entry for every active branch in the registry, so once it has run, provenance marks
every branch an override — pure noise. A value is an override when it differs from the
corresponding default.

*Live state, measured 2026-08-25:* `per_branch` is **empty** in both `rollover` and `entry_limits`,
so every branch resolves from `defaults` and `config get @branch` reports
`source: "defaults"`. The registry carries **18** active branches, which is the number
`rollover push` materializes and reports.

**`set-default` does not touch `per_branch`.** It changes `defaults` only — which means already
materialized branches keep their old numbers and start reporting as `[OVERRIDE]`. `rollover push`
remains the one explicit fleet-wide reset that brings every branch back to the defaults; its
semantics are unchanged. Writes go through `config_loader._write_config_file` (atomic tmp +
`os.replace`) and inherit the no-clobber contract: a config that exists but cannot be read is
refused, never rewritten.

**Apply timing:** limits take effect on the next rollover run (daemon tick) — there is no
immediate-kick verb in v1. The `*_meta` tab strings in `.trinity/` files are likewise re-rendered by
the next `rollover run` that touches the branch (scoped to what it rolled) or by the next
`drone @memory push`, so a freshly changed limit is live in the engine before it is visible in the tab
text. `rollover report-lines` does not re-render them — it writes nothing.

---

## The keep-count ceiling — a count has to fit its file

Landed 2026-09-15 (FPLAN-0593 Phase 1). The caps in `entry_limits` bound a single ENTRY. The budgets
in `entry_limits.file_budgets` bound a whole FILE. Nothing in between bounded the NUMBER of entries,
so a keep-count was free to multiply a legal entry until the file it sits in was illegal — every
entry inside its cap, the document over budget, and no surface able to say which number was wrong.

The missing arithmetic lives in `handlers/json/budget.py`. It is per file, because that is the unit a
budget names, and it needs co-tenants, because a `.trinity` file is shared:

```
local.json        sessions + key_learnings + todos   →  25,000 chars
observations.json observations                       →  15,000 chars
```

"The sessions ceiling" is therefore **not a property of sessions**. It is what is LEFT of
`local.json`'s 25,000 once key_learnings and todos have taken their configured share and the
document's own structure has taken its allowance. Raise key_learnings and the sessions ceiling drops
— which is why `count_ceiling()` takes the whole count map and not just the type being asked about.

Two properties worth knowing about that module:

- **It is pure on purpose and imports nothing from `config_loader` or `entry_limits`.**
  `config_loader` clamps on load and must call it mid-resolution; an import edge back the other way
  would be a cycle that only shows up in whichever import order CI happens to take. Every map it
  works on is HANDED to it — field shapes, entry types, budgets, counts — and it reads no config and
  touches no disk.
- **The worst case is measured, not hand-summed.** It is built as a real entry and serialized exactly
  the way memory files are written (`indent=2, ensure_ascii=False`), then measured. Hand-summing the
  punctuation of a JSON object — braces, quotes, colons, commas, the indentation each line carries —
  is how a ceiling ends up wrong by a few percent in the direction nobody checks.

**Refused at the verb.** `_validate_count` applies three bounds, widening in what each one knows: the
count is a whole number, it is inside 1..100, and the file it grows still fits its budget. The third
one calls `config_loader.ceiling_refusal(entry_type, count, branch)` — the sentence lives in
`config_loader` for the same reason `set_branch_limit`'s refusals do, because config_loader owns
config reads and a refusal quoting numbers the verb fetched itself would be a second opinion. The
refusal names the ceiling, the file's worst case at the count that was asked for, the budget it
would bust, and the co-tenant counts it was measured against; the suggestion points at
`entry_limits.file_budgets` and says the ceiling moves only when that number or the entry caps do.

**Clamped on load.** A hand-edit of `memory.config.json` never passes the verb, so `_resolve_limits`
also runs `_clamp_to_budget`: any resolved count over its ceiling is **lowered to the ceiling** —
lowered, not dropped, because a branch with no limit rolls nothing and grows without end. The raw
value stays on the row as `requested_count`, so the display can show what the operator wrote next to
what the engine will do, and a warning names the count, the ceiling, the worst case, the budget and
the co-tenants. The count snapshot is taken **before any clamp**, so every ceiling is measured
against the same co-tenants and clamping one type cannot silently buy room for the next one in
iteration order. `_clamp_to_budget` also re-decides `is_override` against the clamped value.
A caller holding only the rollover section gets the pre-1.5.0 behaviour, unclamped, which is why the
accessors all pass `entry_limits` through.

**The ceilings as they stand.** Measured 2026-09-15 against the shipped defaults (sessions 15,
key_learnings 15, todos 10, observations 15):

| Type | Ceiling | File | Budget | Co-tenants it was measured against |
|---|---|---|---|---|
| `sessions` | 16 | `local.json` | 25,000 | key_learnings 15, todos 10 |
| `key_learnings` | 17 | `local.json` | 25,000 | sessions 15, todos 10 |
| `todos` | 14 | `local.json` | 25,000 | key_learnings 15, sessions 15 |
| `observations` | 19 | `observations.json` | 15,000 | none — its file's only tenant |

No shipped default is clamped: every default sits under its own ceiling, with little room above it.
The table is not a constant — `config_loader.get_count_ceilings(branch)` computes it in one config
read, and the BOUNDS block of `config --help` prints the live numbers rather than a copy.

---

## `--json` — the machine surface

`config get`, `config get @branch`, `config set`, `config set-default` and `rollover push` all take
`--json`. It exists because @api serves BAUD's memory-settings screens from these verbs and was
**reading the rendered human output** — every wording change was a silent breakage waiting to happen.

**`ok` is the machine success signal.** Refusals exit 0 branch-wide (that ruling is not this arc's to
change), so an exit code tells a caller nothing and the old alternative was inferring failure from
output *shape*. Every payload carries `ok` and `verb`; a refusal is `ok: false` plus `error` and
`suggestion` — **the exact sentences the human path prints**, because those are the published
contract. `suggestion` is always present, `null` where the refusal genuinely has no remedy line
(the unreadable-config refusal is the one such case).

**The flag rides in any slot** and is stripped before positional parsing, so
`config set @memory sessions 25 --json` parses identically to the same line without it.
**`--help` still outranks `--json`**: `config set @memory sessions 25 --help --json` prints help and
writes neither the config nor a payload — same rule that stopped `rollover push --help` from
performing the fleet-wide reset it was being asked to describe.

**Exactly one JSON document reaches stdout** — no panels, no banners, nothing else, and stderr stays
silent. The payload never travels through Rich: the shared console is width-80 with
`is_terminal=False`, so it hard-wraps a long document and a wrap landing inside a string value
inserts a newline *into* the value; it also parses markup, so a `[...]` token inside a string is
eaten as a style name. Both corruptions are invisible to a test that asserts on the string handed to
the printer, so `rollover._emit()` writes through `sys.stdout` and the tests assert on what reached
the pipe.

```jsonc
// config get --json
{"ok": true, "verb": "config get",
 "defaults": {"sessions": {"count": 15, "auto_compact_cap": 3},
              "key_learnings": {"count": 15}, "observations": {"count": 15}},
 "overrides": {"devpulse": {"sessions": {"count": 25, "default_count": 15,
                                         "is_override": true, "source": "per_branch"}}}}

// config get @memory --json
{"ok": true, "verb": "config get", "branch": "memory",
 "limits": {"sessions": {"count": 15, "default_count": 15, "is_override": false,
                         "source": "per_branch", "auto_compact_cap": 3},
            "key_learnings": {...}, "observations": {...}}}

// config set @memory sessions 25 --json
{"ok": true, "verb": "config set", "branch": "memory",
 "entry_type": "sessions", "count": 25, "pushed": false}

// config set-default sessions 25 --json
{"ok": true, "verb": "config set-default", "entry_type": "sessions", "count": 25, "pushed": false}

// rollover push --json
{"ok": true, "verb": "rollover push", "branches": 18}   // = active branches in AIPASS_REGISTRY.json

// any refusal
{"ok": false, "verb": "config set", "error": "Unknown branch: @wizard",
 "suggestion": "Registry is truth — run 'drone systems' to list branches"}
```

`overrides` holds only the branches that deviate — `{}` when none do — and inside a branch only the
entry types that actually deviate, the same rule the rendered OVERRIDES block applies. `count` is
`null` when no limit is configured: the resolution is per FILE KEY, so a per-branch entry carrying
only `sessions` leaves `key_learnings` with *no* limit, and reporting `15` there would claim
enforcement that does not happen. `auto_compact_cap` appears only where one is set (`sessions`).

`pushed` is always `false` on both write verbs and states the delivery semantics in data:
`set-default` reaches **no** branch — `rollover push` is what delivers it. It is reported by
`config_loader`, not synthesized in the module, so the payload cannot drift from what the writer did.

*Note: the `count: 25` payloads above are the shipped examples and predate the ceiling. A real
`config set @memory sessions 25` is refused today — 25 is over the sessions ceiling of 16 — and
answers with the `ok: false` shape.*

---

## Related

- [rollover_pipeline.md](rollover_pipeline.md) — the engine these limits steer
- [trinity_standard.md](trinity_standard.md) — the entry caps the file budgets sit over
- [todos_and_backlog.md](todos_and_backlog.md) — why the todos count is display-only in v1
- [cli_surface.md](cli_surface.md) — the flag rules `--json` inherits
