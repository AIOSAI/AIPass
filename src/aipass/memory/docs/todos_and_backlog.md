[<- Back to the README](../README.md)

# Todos — the pad and the backlog

**Branch** memory · **Code** `apps/modules/todo.py`, `apps/handlers/rollover/todo_roll.py`, `apps/handlers/rollover/todo_report.py`

A todo is a sticky note: one line of what to
do — "Check on seedgo's errors in logs", "fix drone help". The pad holds a few; the ones that roll
off wait in a plain file.

The field-by-field contract — every key, its type, who may write it, and what each surface must do
with it — lives in [todos_v2_shape_contract.md](todos_v2_shape_contract.md). This document is the
lane: where a todo goes, when, and what refuses.

---

## The shape, in one table

| | |
|---|---|
| **Shape** | `{number, date, task, priority?}` — no `status`. What is on the pad is the status; done = deleted. |
| **Pad count** | `rollover.defaults.local.todos.count` — **10** — resolved per branch by `config_loader.get_todos_count` (a `per_branch.<b>.local` block without a todos count falls back to the default). `config get` shows it; `config set` refuses `todos` in v1. No verb reads it as a literal. |
| **Task cap** | `entry_limits.entry_types.todos.max_chars` — **100**, draft to 80. |
| **Backlog** | `<repo_root>/.backup/todo/<branch_dir>/backlog.json`, keyed by the branch DIRECTORY name. Two in-scope branches sharing a directory name are refused by name. |
| **Vectors** | Never. File only — no embedding, no ChromaDB, no subprocess. |

---

## When the oldest roll

- **`drone @memory rollover run`**, for ONE branch: `--branch @name`, or the branch the caller's working
  directory sits in. From the repo root nothing rolls, and one line says so. Past the count, the oldest
  by `number` move with reason `overflow`: append to the backlog, replace atomically, read back and
  compare every record json-equal, and only then write the pruned pad. A mismatch refuses and leaves
  the pad untouched — a todo may end up in both places, never in neither. `rollover check` counts the
  same pad and prints `ready for rollover` when it is over.
- **`drone @memory push`**, the trinity push: every non-canonical todo, then any canonical overflow,
  moves to the same file, nothing reshaped (see
  [trinity_push.md](trinity_push.md#todos-go-to-the-backlog-never-to-vectors)).
- Nowhere else. The fleet walk (`detector.check_all_branches`, which `rollover run` and `check` also
  run) never counts todos. Its file list is fleet-wide whatever `--branch` names, and `check` labels
  it so: `Found N files ready for rollover (fleet-wide):`, then one line saying `--branch` scopes only
  the todo pad line.

---

## The verbs, and what they print

`drone @memory todo` run from `src/aipass/memory` answers with the pad and backlog counts:

```
memory: pad N of 10 · backlog M (.backup/todo/memory/backlog.json)
memory: pad N of 10 · backlog 0 (no backlog yet: .backup/todo/memory/backlog.json)
```

The same verb from the repo root resolves no branch, and says which argument fixes it:

```
Todos: no branch resolved (…/AIPass is not inside a registered branch directory) - no todo pad counted; pass --branch @name
```

`drone @memory todo backlog` on a branch that has never rolled says so as a state, not an error:

```
memory: no backlog - .backup/todo/memory/backlog.json does not exist. Nothing has rolled off this pad on this machine (.backup/ is gitignored, so a fresh clone starts without one)
```

A backlog with records prints a header, then one line per record — original number · date · priority
(when set) · rolled · reason · task:

```
memory backlog: N record(s), oldest roll first (.backup/todo/memory/backlog.json)
  #<number> · <date> · priority <p> · rolled <iso> · <reason> · <task>
```

`status` is never printed: a record moved for being non-canonical keeps any `status` it carried,
verbatim, and that text can be long.

---

## The backlog file

- **`.backup/` is gitignored**, so a fresh clone has no backlog. "No backlog" is a state (exit 0), not
  an error. An unreadable or misshapen backlog is refused (exit 2) and never written over.
- **`todo restore <number>`** puts one backlog todo back on the CALLER's own pad. It writes
  `.trinity/local.json`, so a `--branch` naming another branch is refused, and so is a caller standing
  in no branch. It is refused when the pad already holds its count (read from config), when no record
  carries the number, and when several do (the candidates are named by rolled time and task). The todo
  returns **on top of the pad** (lists are newest-first) under the next number (below) with task, date
  and priority identical. The same pad write re-renders `todos_meta` through the tab renderer, so the
  tab's `next #N` is the restored number + 1 the moment the verb returns (a tab that cannot be rendered
  refuses the restore, nothing written). The pad is written and read back first; only then is the record removed from
  the backlog. It re-numbers because an emptied pad restarts at 1 while the backlog already holds 1..N,
  and a restored todo keeping its low number would be the first to roll again.
- **A NON-CANONICAL todo cannot be restored**: the pad write is refused by the write gate. `memory_files.write_memory_file`
  judges a write by what it AUTHORS, and a restored record is authored by that write, so a legacy
  `status` key, a task over its cap, an unknown key or a wrong type is measured by
  `entry_limits.check_fields` and refused. `restore_todo` surfaces the writer's sentence under
  `NOTHING RESTORED`, and **both files are left exactly as found** — the pad is not written, the
  backlog record is not removed. That is the intended end state: the machine will not reshape
  someone's open work to make it fit. `drone @memory todo backlog` is the way to read the text,
  and re-adding it by hand in the canonical shape is the way back onto the pad.
- **Numbers are never re-issued on purpose.** The next number is one past the highest of: the pad, the
  backlog's original numbers, the backlog's `document_metadata.high_water`, and N − 1 from the `next #N`
  the branch's own tab last rendered. `high_water` is raised (never lowered) on every memory backlog
  write — roll, push move, restore — and read back; a backlog without it has no floor, never an error.
  The tab floor is why a re-render after deleting the top todo still says the same `next #N`. `#?` or an
  unrecognised tab is no floor; a bool is not a number. seedgo's check masks the `next #N` slot, so it
  needs nothing. **Residual:** a todo added by hand and deleted by hand with no memory write or tab
  render in between leaves no trace, so its number can be issued again once.
- **Every refusal exits non-zero** (2: routed, refused); a refused argument also names the valid forms.
  There is no `--json` on these verbs — nothing reads them by machine — and the flag is refused like
  any other unknown argument rather than silently ignored.

---

## Related

- [todos_v2_shape_contract.md](todos_v2_shape_contract.md) — the field-by-field contract
- [trinity_push.md](trinity_push.md) — the other lane that moves todos off a pad
- [rollover_pipeline.md](rollover_pipeline.md) — `rollover run` / `check` and the fleet walk
- [config_verbs.md](config_verbs.md) — where the pad count is read from and why `set` refuses it
