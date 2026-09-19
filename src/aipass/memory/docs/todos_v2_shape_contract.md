[<- Back to the README](../README.md)

# todos v2 shape contract (DPLAN-0345, FPLAN-0590 rows 3-4)

This is the relay for @seedgo (FPLAN-0590 row 6). It records what @memory's code enforces and renders, and which seedgo lines still hold the old truth. Everything below was read from disk on 2026-09-15, and the line numbers are from that read. Paths are relative to `src/aipass/memory/` unless stated otherwise.

## 1. The canonical todo

In `apps/handlers/templates/trinity_push.py:188-192`, inside `ENTRY_RULES`:

```python
    # DPLAN-0345: no `status`. What is on the pad IS the status; done = deleted.
    "todos": {
        "required": {"number": _TYPE_INT, "date": _TYPE_STR, "task": _TYPE_STR},
        "optional": {"priority": _TYPE_STR},
    },
```

The shape is closed. A key outside `number, date, task, priority` makes a todo non-canonical. `task` is also held to the configured `max_chars` (section 4).

`todo_defect` (`trinity_push.py:306-330`) gives each todo one reason: the first match in `DEFECT_ORDER` (`trinity_push.py:295-303`). That order is the order `todo_defect` checks in, and the push report prints it verbatim.

1. `not an object`: the entry is not a dict.
2. `status present`: the key `status` exists, whatever its value.
3. `task over cap`: the report prints this as `task over <max_chars>`.
4. `missing field`: `number`, `date` or `task` is absent.
5. `unknown field`: a key outside the shape.
6. `wrong type`: any other `entry_problems` finding, for example a `number` that is not an int.
7. `overflow`: applies only to canonical todos past the pad count.

Todos that fail 1-6 move to the backlog with reason `non-canonical`, in file order. Next, if the canonical todos left are more than the count, the oldest move with reason `overflow`. Oldest means sorted by `(number, file index)`. A moved todo is stored as it was. It is not reshaped, not shortened and never sent to vectors. The pad is written only after every append reads back json-equal. If the read-back fails, the push refuses that branch and leaves its `local.json` alone.

## 2. The todos tab

From `apps/handlers/tracking/tab_renderer.py:167-178`:

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

The fallbacks are `UNKNOWN_BRANCH_DIR = "<branch>"` and `UNKNOWN_NEXT = "?"` (`tab_renderer.py:138-139`). `todo_roll.BACKUP_DIR`, `TODO_DIR` and `BACKLOG_FILE` are `.backup`, `todo` and `backlog.json`. The full `todos_meta` value is the tab, one space, then the template prose (`compose_meta`, `tab_renderer.py:115-129`).

Here is an example rendered from the live config (count 10, max_chars 100). The branch directory is `memory`, the pad holds numbers 12 and 3, and the backlog holds #40:

```
⟦ pad of 10 · oldest roll to .backup/todo/memory/backlog.json · task ≤100 chars · draft to 80 · next #41 ⟧ One line of what to do: 'Check on seedgo's errors in logs', 'fix drone help'. No status, no log — the story lives in plans and sessions. Delete it when done.
```

The tab in the other cases:

| Case | Tab |
| --- | --- |
| No branch context. This is `render_all_meta_tabs()` with no argument, which spawn birth uses today. | `⟦ pad of 10 · oldest roll to .backup/todo/<branch>/backlog.json · task ≤100 chars · draft to 80 · next #? ⟧` |
| Branch known, empty pad, no backlog | `⟦ pad of 10 · oldest roll to .backup/todo/memory/backlog.json · task ≤100 chars · draft to 80 · next #1 ⟧` |
| No usable count configured | `⟦ no pad size configured — nothing rolls · task ≤100 chars · draft to 80 · next #1 ⟧` |

Where each renderer gets its branch context:

- **Trinity push and normalizer.** `trinity_push._plan_file` and `build_frame` use the push's branch name, which is the directory name. The pad is the `todos` list as read before the push, and the file's current `todos_meta` is passed as the tab floor (section 3). Every todo the push moves is appended to the backlog, so N matches what the pad and backlog would give after the push.
- **`refresh_all_tabs`, called by `rollover run`.** `_refresh_local` uses the name of the directory that holds `.trinity/`, the `todos` list as read from `local.json`, and that file's current `todos_meta` as the tab floor.
- **`render_all_meta_tabs(branch_dir=None)`.** It uses an empty pad plus that branch's backlog, and no tab floor: it is the birth path, and a branch being born has no tab yet. With no argument it renders `<branch>` and `#?`.

## 3. How `next #N` is derived

From `apps/handlers/rollover/todo_roll.py` (`_as_number` :119, `high_water_of` :141, `floor_from_tab` :151, `_highest` :157, `next_number` :169, `_stamp_high_water` :192; the tab pattern `_TAB_NEXT_RE` :92):

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
- **`high_water`** is raised, never lowered, on every memory backlog write: a roll (`roll_todos` passes the whole pad as found, so a kept todo's number reaches it), a push move (`trinity_push.move_todos` passes the pad as found), and a restore (the fresh number and the pad as written). Each write reads `document_metadata` back and refuses on a mismatch, like every record. A backlog without the key (every one written before it existed) has no floor, never an error; its first memory write stamps it.
- **The tab floor** is read only from memory's own tab shape — `⟦ … · next #N ⟧` at the start of the line, N a positive integer. `#?`, `#0`, a retired tab, free text or a non-string is no floor. It is how a number survives a hand deletion between renders: the tab that offered #13 still says #13 after #12 is deleted, so the next render says #13 again rather than walking back to #12. Callers: `tab_renderer.todo_context(..., todos_meta=)` (`tab_renderer.py:143`) from `_refresh_local` (`:321`), `trinity_push.build_frame` (`:600`) and `_plan_file` (`:706`); `todo_roll.restore_todo` reads the pad's own `todos_meta`. `render_all_meta_tabs` passes none (birth, no tab yet).
- The tab shows `#?` in three cases. The pad is not a list. The backlog is unusable (`read_backlog` returned an error: the file cannot be read, has no `document_metadata` object, or has no `entries` list). There is no branch.
- A missing backlog is not unusable. It just adds no numbers and no `high_water`.
- **A restore lands on top.** Its fresh number is `next_number` with both floors, so it is the highest on the pad and goes to index 0: lists are newest-first (seedgo refuses "number N is not below the entry above it").
- **N only changes when the tab is rendered.** The renderers are: push, `rollover run` (only for branches whose sessions, key_learnings or observations rolled), the normalizer, `templates bump --confirm`, and spawn birth. Adding or deleting a todo does not re-render. So after an agent adds a todo, a checker that recomputes N from the live pad will disagree with a correctly rendered file until the next render.
- **Residual (stated, not cured):** a todo added by hand and deleted by hand with no memory write or tab render in between leaves no trace, so its number can be issued again once.

**seedgo needs nothing for the floors.** `trinity_groups.py` never derives N. `_meta_item` (`:1053`) sends the todos line to `_todos_meta_matches` (`:1029-1050`), which byte-matches the whole line except the `next #N` slot: it renders the expected line with `next_number: None`, accepts that `#?` line whole, and otherwise requires the text before `next #` and after ` ⟧` to match while the slot holds any rendered int (`_RENDERED_INT_RE`, `:205`). A higher N from either floor is still a match. seedgo need not read `high_water`.

## 4. Where count, max_chars and draft come from

All three come from `memory_json/custom_config/memory.config.json`. None is a literal in the push or the tab.

| Value | Resolver | Config key | Live value |
| --- | --- | --- | --- |
| count | `config_loader.get_todos_count(branch, rollover_cfg)` (`config_loader.py:526-541`), through `_resolve_limits` (`:416`) | `rollover.per_branch.<branch>.local.todos.count`, else `rollover.defaults.local.todos.count` | 10 |
| max_chars | `entry_limits.resolve_entry_types(entry_limits_cfg, branch)["todos"]["max_chars"]` (`entry_limits.py:195`, read at `tab_renderer.py:251-253`) | `entry_limits.per_branch.<branch>.todos`, deep-merged over `entry_limits.entry_types.todos.max_chars` | 100 |
| draft | `entry_limits.draft_target(max_chars)` (`entry_limits.py:156-165`) | `max_chars * DRAFT_PERCENT // 100`, where `DRAFT_PERCENT = 80` (`entry_limits.py:153`) | 80 |

How the count resolves:

- The branch name is matched lowercased.
- Lookup goes per file key: if `per_branch.<branch>.local` exists, `defaults.local` is not read. Todos are the exception. A per-branch `local` block that has no todos count falls back to the default todos count (`COUNT_ONLY_ENTRY_TYPES`, `config_loader.py:163` and `:456-462`).
- The count is `None` unless it is an int of at least 1 and not a bool. `None` renders `no pad size configured — nothing rolls`. The push then rolls no overflow, but non-canonical todos still move.
- `render_tab` falls back to `max_chars` 300 only when config has no todos `max_chars` at all (`tab_renderer.py:253`, existing code).

## 5. The backlog

- **Path:** `<repo_root>/.backup/todo/<branch_dir>/backlog.json`, from `todo_roll.backlog_path_for` (`todo_roll.py:158-169`). `.backup/` is gitignored.
- **`<branch_dir>`** is the branch directory name, not the registry name. Registry names are mixed case, for example `BACKUP`.
- **Schema** (`todo_roll.py:42-46`):

```
{"document_metadata": {"managed_by": "memory", "branch": "<dir>", "high_water": <int>},
 "entries": [{"rolled": "<iso>", "reason": "overflow|non-canonical|migration",
              "entry": {<the todo, json-equal to the pad's copy>}}]}
```

- **`document_metadata.high_water`** (optional int, memory-owned): the highest todo number memory has seen for the branch — on the pad, in the entries, or issued by a restore. Raised, never lowered, on every memory backlog write (roll, push move, restore) and verified on read-back. Absent (every backlog written before 2026-09-15) means no floor, never an error. It is a floor for `next #N` (section 3) and nothing else; seedgo need not read it. Residual: a todo added by hand and deleted by hand with no memory write or tab render in between leaves no trace, so its number can be issued again once.

- **Reasons:** `overflow`, `non-canonical` and `migration` (`todo_roll.py:72-75`). The push writes `non-canonical` first, then `overflow`, with one verified append per reason.
- **Appending** (`append_to_backlog`, `todo_roll.py:485-544`): read the file, add the records, replace it atomically, then read it back. Every record must match what was written, and every appended `entry` must be json-equal to the pad's copy. Equality is `json.dumps(sort_keys=True, ensure_ascii=False, separators=(",", ":"))`. The file is only ever appended to, never overwritten.
- **Directory-name collision.** Two in-scope branches whose directory names match case-insensitively are refused (`_collision`, `todo_roll.py:218-227`) with: `REFUSED: directory name '<name>' is shared by N branches (...) - their todo backlogs would merge in .backup/todo/<name>/backlog.json`. The push records `<name>: todos not movable — <error>` and refuses that branch.
- **Owner mismatch.** If an existing backlog's `document_metadata.branch` names a different directory, the append is refused (`todo_roll.py:522-525`).
- **Unusable file.** The read returns an error, and the file is never written over (`todo_roll.py:453-459`).
- **Absent file.** `read_backlog` returns `exists: False` with a message and no error (`todo_roll.py:446-451`). This means "no backlog", which is a normal state, not a failure. The push report says `does not exist yet, created by the push`.

## 6. LOCAL.template.json

In `templates/LOCAL.template.json`, `version` 2.0.0 and `schema_version` 3.0.0 are unchanged.

`document_metadata._usage`:

```
Your working draft — the context that keeps you YOU across sessions; updated freely, often several times a session. sessions = what happened (the chronicle) · key_learnings = what you'd want to know again (transferable technical lessons) · todos = a sticky-note pad, one line of what to do, no status, no log — delete one when done; the oldest roll to your backlog. Newest on top; rollover archives oldest sessions/key_learnings to @memory. Caps and pad size: @memory memory.config.json, rendered into each *_meta line.
```

`todos_meta`:

```
{{TODOS_META}} One line of what to do: 'Check on seedgo's errors in logs', 'fix drone help'. No status, no log — the story lives in plans and sessions. Delete it when done.
```

`"todos": []` is unchanged. seedgo's `_usage` byte-match (`trinity_groups.py:997-1008`) reads this template from `memory/templates` (`trinity_check.py:215`), so this text is now what every branch's `_usage` is compared against.

## 7. seedgo lines holding the old truth

All paths below are under `src/aipass/seedgo/apps/handlers/aipass_standards/`.

### trinity_groups.py:144-151: `_ENTRY_RULES` todos

The dict opens at `:125`, and `:152` is `"optional": {},`. The lines now read:

```python
    "todos": {
        "required": {
            "number": _TYPE_INT,
            "date": _TYPE_STR,
            "task": _TYPE_STR,
            "priority": _TYPE_STR,
            "status": _TYPE_STR,
        },
```

Memory's side is section 1: `number`, `date` and `task` required; `priority` optional; no `status`.

### trinity_groups.py:416-420: the todos tab in `expected_meta_line`

The function is defined at `:390`, and `:421` is the return. The lines now read:

```python
    if section == "todos":
        tab = (
            f"⟦ rollover OFF — operational, never trimmed · cap ~10 entries · task ≤{max_chars} chars"
            f" · draft to {draft} ⟧"
        )
        return f"{tab} {template_prose}"
```

Memory's side is section 2. A mirror of the new tab needs the count (section 4), the branch directory name, and N (section 3).

### trinity_groups.py:1137-1157: Group 8, Todos hygiene

It is registered at `:1239`, weighted `"Todos hygiene": 5` at `trinity_check.py:148`, and described at `trinity_check.py:85`. The lines now read:

```python
def _todo_problem(entry: object) -> str | None:
    """Return why a todo breaks hygiene, or None."""
    if not isinstance(entry, dict):
        return f"entry must be an object, found {type(entry).__name__} -- status unmeasurable"
    status = entry.get("status")
    if not isinstance(status, str):
        return f"'status' unmeasurable: must be str, found {_found(entry, 'status')}"
    if status.strip().lower() == "done":
        return "todo kept with status done -- delete it, do not keep it"
    return None


def _todo_probe(section: str, entries: list) -> tuple[int, list]:
    """Check every todo for the done-trophy pattern."""
    return _run_probe(section, entries, _todo_problem)


def _group_todos_hygiene(ctx: dict) -> dict:
    """Group 8: no todo survives as status done."""
    ok, total, records = _entry_scan(ctx, ("todos",), _todo_probe)
    return _records_check("Todos hygiene", ok, total, records, f"All {total} todos are open -- none kept as done")
```

Against v2 todos, `_todo_problem` requires `status` to be a str. A canonical todo has no `status`, so every one of them returns a problem. After a push, no pad holds a todo with `status` at all.

### trinity.md:61

Now reads:

```
| todos | `{number, date, task, priority, status}` | task ≤150 | **NEVER rolled** — delete by hand when done |
```

Other lines with the same truth: `:76` (todos prose, "never leave `status: done`"), `:132` (Group 8 description), `:149` (example todo with `"status": "done"`), `:182` (`| Todos hygiene | 5 |`).

### trinity_content.py:83

Now reads (`:83-84`):

```python
        "  [dim]todos[/dim]          {number:int, date:str, task:str,",
        "                  priority:str, status:str}",
```

Same truth at `:68-69`: `8. Todos hygiene (5) — status:done is a violation;` / `delete, do not keep.`

### Also pinned

`src/aipass/seedgo/tests/test_trinity_check.py:71` and `:1910` hold the old tab string.

### Outside seedgo, same old truth (for the relay only)

- `CLAUDE.md:25` (repo root): "Todos[] don't auto-roll — rollover never trims them … never leave it as `status: done`".
- `.claude/commands/prep.md:36`: "Rollover never trims todos … done items left as `status: done` pile up".

## 8. Landing order

seedgo's half lands in the same commit as memory rows 3-4. Either half alone leaves the fleet red:

- Memory's template `_usage` has already changed on disk, and seedgo byte-matches every branch's `_usage` against it. Until a branch is re-rendered, it fails "Meta lines & _usage".
- Every render after rows 3-4 writes the new todos tab, which seedgo's old mirror at `trinity_groups.py:416-420` rejects.
- After the first push, no todo carries `status`. seedgo's `_ENTRY_RULES` (`:150`) and Group 8 (`:1141-1143`) then flag every todo left on the pad.
- In memory, `tests/test_trinity_push.py::TestThePushedFileIsCanonical::test_a_pushed_branch_satisfies_the_trinity_checker` xfails under three conditions together: seedgo's mirror still renders the retired todos tab, "Meta lines & _usage" is the only failing group, and every message is about `todos_meta`. Once seedgo lands, the test asserts strictly with no memory edit.
- There is no migration code. The first real `drone @memory push --confirm` moves every non-canonical todo to its branch's backlog and empties those pads.
- Spawn birth: `src/aipass/spawn/apps/modules/core.py:361` calls `render_all_meta_tabs()` with no branch. A newborn's tab reads `<branch>` / `#?` until its first push or render. `folder_name` is in scope at `:311`.
