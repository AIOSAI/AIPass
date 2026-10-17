[<- Back to the README](../README.md)

# todos v2 shape contract

What @memory's code enforces and renders for the todo pad: the canonical todo, the todos tab, how
`next #N` is derived, where the numbers come from, the backlog file and the template.
Paths are relative to `src/aipass/memory/` unless stated otherwise.

## 1. The canonical todo

The shape lives in config, `entry_limits.entry_types.todos.fields` in `memory.config.json` (seeded
from `config_loader.DEFAULT_CONFIG`):

```python
"fields": {
    "number": {"type": "int", "required": True},
    "date": {"type": "str", "required": True, "max_chars": 10},
    "task": {"type": "str", "required": True, "max_chars": 100},
    "priority": {"type": "str", "required": False, "max_chars": 10},
},
```

`trinity_push.entry_rules()` derives the required/optional split from it. What is on the pad IS the
status; done = deleted, so there is no `status` field. The shape is closed. A key outside
`number, date, task, priority` makes a todo non-canonical. `task` is also held to the configured
`max_chars` (section 4).

`trinity_push.todo_defect` gives each todo one reason: the first match in `DEFECT_ORDER`. That order
is the order `todo_defect` checks in, and the push report prints it verbatim.

1. `not an object`: the entry is not a dict.
2. `status present`: the key `status` exists, whatever its value.
3. `task over cap`: the report prints this as `task over <max_chars>`.
4. `missing field`: `number`, `date` or `task` is absent.
5. `unknown field`: a key outside the shape.
6. `wrong type`: any other `entry_problems` finding, for example a `number` that is not an int.
7. `overflow`: applies only to canonical todos past the pad count.

Todos that fail 1-6 move to the backlog with reason `non-canonical`, in file order. Next, if the canonical todos left are more than the count, the oldest move with reason `overflow`. Oldest means sorted by `(number, file index)`. A moved todo is stored as it was. It is not reshaped, not shortened and never sent to vectors. The pad is written only after every append reads back json-equal. If the read-back fails, the push refuses that branch and leaves its `local.json` alone.

## 2. The todos tab

From `apps/handlers/tracking/tab_renderer.py`:

```python
def _todos_tab(rollover_cfg: dict, branch_name: str, max_chars: Any, draft: Any, todo_ctx: dict | None) -> str:
    """The todos tab: pad size from rollover config, the backlog file, the caps, the next number."""
    context = todo_ctx if isinstance(todo_ctx, dict) else {}
    branch_dir = context.get("branch_dir") or UNKNOWN_BRANCH_DIR
    number = context.get("next_number")
    next_label = number if isinstance(number, int) and not isinstance(number, bool) else UNKNOWN_NEXT
    tail = f"task ≤{max_chars} chars · draft to {draft} · next #{next_label}"
    count = config_loader.get_todos_count(branch_name, rollover_cfg)
    if count is None:
        return f"⟦ no pad size configured — nothing rolls · {tail} ⟧"
    backlog = f"{todo_roll.BACKUP_DIR}/{todo_roll.TODO_DIR}/{branch_dir}/{todo_roll.BACKLOG_FILE}"
    return f"⟦ pad of {count} · oldest roll to {backlog} · {tail} ⟧"
```

The fallbacks are `UNKNOWN_BRANCH_DIR = "<branch>"` and `UNKNOWN_NEXT = "?"`. `todo_roll.BACKUP_DIR`, `TODO_DIR` and `BACKLOG_FILE` are `.backup`, `todo` and `backlog.json`. The full `todos_meta` value is the tab, one space, then the template prose (`compose_meta`).

Here is an example rendered from the live config (count 10, max_chars 100). The branch directory is `memory`, the pad holds numbers 12 and 3, and the backlog holds #40:

```
⟦ pad of 10 · oldest roll to .backup/todo/memory/backlog.json · task ≤100 chars · draft to 80 · next #41 ⟧ One line of what to do: 'Check on seedgo's errors in logs', 'fix drone help'. No status, no log — the story lives in plans and sessions. Delete it when done.
```

The tab in the other cases:

| Case | Tab |
| --- | --- |
| No branch context: `render_all_meta_tabs()` with no argument | `⟦ pad of 10 · oldest roll to .backup/todo/<branch>/backlog.json · task ≤100 chars · draft to 80 · next #? ⟧` |
| Branch known, empty pad, no backlog | `⟦ pad of 10 · oldest roll to .backup/todo/memory/backlog.json · task ≤100 chars · draft to 80 · next #1 ⟧` |
| No usable count configured | `⟦ no pad size configured — nothing rolls · task ≤100 chars · draft to 80 · next #1 ⟧` |

Where each renderer gets its branch context:

- **Trinity push and normalizer.** `trinity_push._plan_file` and `build_frame` use the push's branch name, which is the directory name. The pad is the `todos` list as read before the push, and the file's current `todos_meta` is passed as the tab floor (section 3). Every todo the push moves is appended to the backlog, so N matches what the pad and backlog would give after the push.
- **`refresh_all_tabs`, called by `rollover run`.** `_refresh_local` uses the name of the directory that holds `.trinity/`, the `todos` list as read from `local.json`, and that file's current `todos_meta` as the tab floor.
- **`render_all_meta_tabs(branch_dir=None)`.** It uses an empty pad plus that branch's backlog, and no tab floor: it is the birth path, and a branch being born has no tab yet. @spawn's birth passes the newborn's directory name (`spawn/apps/modules/core.py`, `render_all_meta_tabs(branch_dir)`). With no argument it renders `<branch>` and `#?`.

## 3. How `next #N` is derived

From `apps/handlers/rollover/todo_roll.py` (`_as_number`, `high_water_of`, `floor_from_tab`, `_highest`, `next_number`, `_stamp_high_water`; the tab pattern `_TAB_NEXT_RE`):

```python
_TAB_NEXT_RE = re.compile(r"⟦ [^⟧]* · next #([1-9][0-9]*) ⟧")

def high_water_of(document: Any) -> int | None:
    metadata = document.get("document_metadata") if isinstance(document, dict) else None
    return _as_number(metadata.get(HIGH_WATER_KEY)) if isinstance(metadata, dict) else None

def floor_from_tab(todos_meta: Any) -> int | None:
    match = _TAB_NEXT_RE.match(todos_meta) if isinstance(todos_meta, str) else None
    return int(match.group(1)) - 1 if match else None

def next_number(pad, backlog_entries, *, high_water=None, tab_floor=None) -> int:
    highest = _highest(pad, backlog_entries, high_water, tab_floor)
    return highest + 1 if highest is not None else 1
```

**NUMBERS ARE NEVER RE-ISSUED ON PURPOSE.** N is one past the highest of four things, or 1 when none holds a number:

1. every number on the pad;
2. every original number in the backlog (`record["entry"]["number"]`);
3. the backlog's `document_metadata.high_water` (section 5);
4. the tab floor: N − 1 from the `next #N` in the branch's current `todos_meta`.

- Only an `int` that is not a `bool` counts, everywhere. Strings like `"31"`, floats, `None` and `true` are ignored, as are pad items that are not objects. A `high_water` of `true` or `"7"` is no floor.
- **`high_water`** is raised, never lowered, on every memory backlog write: a roll (`roll_todos` passes the whole pad as found, so a kept todo's number reaches it), a push move (`trinity_push.move_todos` passes the pad as found), and a restore (the fresh number and the pad as written). Each write reads `document_metadata` back and refuses on a mismatch, like every record. A backlog without the key has no floor, never an error; its first memory write stamps it.
- **The tab floor** is read only from memory's own tab shape — `⟦ … · next #N ⟧` at the start of the line, N a positive integer. `#?`, `#0`, a retired tab, free text or a non-string is no floor. It is how a number survives a hand deletion between renders: the tab that offered #13 still says #13 after #12 is deleted, so the next render says #13 again rather than walking back to #12. Callers: `tab_renderer.todo_context(..., todos_meta=)` from `_refresh_local`, `trinity_push.build_frame` and `_plan_file`; `todo_roll.restore_todo` reads the pad's own `todos_meta`. `render_all_meta_tabs` passes none (birth, no tab yet).
- The tab shows `#?` in three cases. The pad is not a list. The backlog is unusable (`read_backlog` returned an error: the file cannot be read, has no `document_metadata` object, or has no `entries` list). There is no branch.
- A missing backlog is not unusable. It just adds no numbers and no `high_water`.
- **A restore lands on top.** Its fresh number is `next_number` with both floors, so it is the highest on the pad and goes to index 0: lists are newest-first (seedgo refuses "number N is not below the entry above it").
- **N only changes when the tab is rendered.** The renderers are: push, `rollover run` (only for branches whose sessions, key_learnings or observations rolled), the normalizer, `templates bump --confirm`, `todo restore` (its pad write carries a fresh `todos_meta`), a `config` limit write that moves the branch's enforced count (`tab_renderer.refresh_moved_limits`), and spawn birth. Adding or deleting a todo does not re-render. So after an agent adds a todo, a checker that recomputes N from the live pad will disagree with a correctly rendered file until the next render.
- **Residual (stated, not cured):** a todo added by hand and deleted by hand with no memory write or tab render in between leaves no trace, so its number can be issued again once.

**A checker needs nothing for the floors.** @seedgo's `trinity_groups.py` never derives N: `_meta_item` sends the todos line to `_todos_meta_matches`, which byte-matches the whole line except the `next #N` slot. A higher N from either floor is still a match, and seedgo need not read `high_water`.

## 4. Where count, max_chars and draft come from

All three come from `memory_json/custom_config/memory.config.json`. None is a literal in the push or the tab.

| Value | Resolver | Config key | Live value |
| --- | --- | --- | --- |
| count | `config_loader.get_todos_count(branch, rollover_cfg)`, through `_resolve_limits` | `rollover.per_branch.<branch>.local.todos.count`, else `rollover.defaults.local.todos.count` | 10 |
| max_chars | `entry_limits.resolve_entry_types(entry_limits_cfg, branch)["todos"]["max_chars"]`, read by `render_tab` | `entry_limits.per_branch.<branch>.todos`, deep-merged over `entry_limits.entry_types.todos.max_chars` | 100 |
| draft | `entry_limits.draft_target(max_chars)` | `max_chars * DRAFT_PERCENT // 100`, where `DRAFT_PERCENT = 80` | 80 |

How the count resolves:

- The branch name is matched lowercased.
- Lookup goes per file key: if `per_branch.<branch>.local` exists, `defaults.local` is not read. Todos are the exception. A per-branch `local` block that has no todos count falls back to the default todos count (`config_loader.COUNT_ONLY_ENTRY_TYPES`).
- The count is `None` unless it is an int of at least 1 and not a bool. `None` renders `no pad size configured — nothing rolls`. The push then rolls no overflow, but non-canonical todos still move.
- `render_tab` falls back to `max_chars` 300 only when config has no todos `max_chars` at all.

## 5. The backlog

- **Path:** `<repo_root>/.backup/todo/<branch_dir>/backlog.json`, from `todo_roll.backlog_path_for`. `.backup/` is gitignored.
- **`<branch_dir>`** is the branch directory name, not the registry name. Registry names are mixed case, for example `BACKUP`.
- **Schema** (`todo_roll.py` module docstring):

```
{"document_metadata": {"managed_by": "memory", "branch": "<dir>", "high_water": <int>},
 "entries": [{"rolled": "<iso>", "reason": "overflow|non-canonical|migration",
              "entry": {<the todo, json-equal to the pad's copy>}}]}
```

- **`document_metadata.high_water`** (optional int, memory-owned): the highest todo number memory has seen for the branch — on the pad, in the entries, or issued by a restore. Raised, never lowered, on every memory backlog write (roll, push move, restore) and verified on read-back. Absent means no floor, never an error. It is a floor for `next #N` (section 3) and nothing else; seedgo need not read it. Residual: a todo added by hand and deleted by hand with no memory write or tab render in between leaves no trace, so its number can be issued again once.

- **Reasons:** `overflow`, `non-canonical` and `migration` (`todo_roll.REASONS`). The push writes `non-canonical` first, then `overflow`, with one verified append per reason.
- **Appending** (`append_to_backlog`): read the file, add the records, replace it atomically, then read it back. Every record must match what was written, and every appended `entry` must be json-equal to the pad's copy. Equality is `json.dumps(sort_keys=True, ensure_ascii=False, separators=(",", ":"))`. The file is only ever appended to, never overwritten.
- **Directory-name collision.** Two in-scope branches whose directory names match case-insensitively are refused (`_collision`) with: `REFUSED: directory name '<name>' is shared by N branches (...) - their todo backlogs would merge in .backup/todo/<name>/backlog.json`. The push records `<name>: todos not movable — <error>` and refuses that branch.
- **Owner mismatch.** If an existing backlog's `document_metadata.branch` names a different directory, the append is refused.
- **Unusable file.** The read returns an error, and the file is never written over.
- **Absent file.** `read_backlog` returns `exists: False` with a message and no error. This means "no backlog", which is a normal state, not a failure. The push report says `does not exist yet, created by the push`.

## 6. LOCAL.template.json

In `templates/LOCAL.template.json`, `version` is 2.0.0 and `schema_version` is 3.0.0.

`document_metadata._usage`:

```
Your working draft — the context that keeps you YOU across sessions; updated freely, often several times a session. sessions = what happened (the chronicle) · key_learnings = what you'd want to know again (transferable technical lessons) · todos = a sticky-note pad, one line of what to do, no status, no log — delete one when done; the oldest roll to your backlog. Newest on top; rollover archives oldest sessions/key_learnings to @memory. Caps and pad size: @memory memory.config.json, rendered into each *_meta line.
```

`todos_meta`:

```
{{TODOS_META}} One line of what to do: 'Check on seedgo's errors in logs', 'fix drone help'. No status, no log — the story lives in plans and sessions. Delete it when done.
```

`"todos": []`. @seedgo's `_usage` byte-match reads this template from `memory/templates`, so this text is what every branch's `_usage` is compared against.
