# Lowercase Name Standard
**Status:** v1
**Date:** 2026-11-22
**Standard:** `lowercase_name` (branch_level, pass or fail)

---

## What This Standard Is

The system speaks lowercase. An agent's name is stored in lowercase: in a registry, in a
branch's data files, and in anything code writes. The owner's ruling, 2026-11-22. A document
is not the runtime, so markdown may spell a name in capitals, and this standard never opens a
`.md` file.

---

## Why It Matters

- **One name, one spelling.** A name stored as `FLOW` in one file and `flow` in another is
  two keys to every exact comparison, and the second lookup misses.
- **Code is the part that writes it.** Fixing the stored files once does nothing while a
  writer still capitalises: the next write brings the capital back.

---

## What the Checker Checks

One finding fails the standard. There is no partial score.

| Leg | Where | Fails when |
|---|---|---|
| Registry row | this branch's row in the `*_REGISTRY.json` at or above it | the `name` is not lowercase, or the `path` is absolute |
| Data files | `.trinity/passport.json` `branch_info.branch_name`, `artifacts/birth_certificate.json` `owner`, `DASHBOARD.local.json` `branch` | the value is not lowercase |
| Code | production Python under `apps/` and `shared/` | an agent name reaches storage in capitals (below) |
| Templates | every non-markdown file under `templates/`, `.archive/` excluded | it holds `{{BRANCHNAME}}` in its name or text |

The registry finding names the row and the cure, `drone @spawn sync-registry <registry> --lowercase`.
The project's own name (the registry file's stem and `metadata.name`) is not an agent name and
is never checked. A dashboard written before the rule fails until it is refreshed, and its
finding names the refresh. No verb rewrites a birth certificate, so that finding says to mail
@spawn.

spawn fills `{{BRANCHNAME}}` with the capital name and `{{BRANCH}}` with the lowercase one, so
a template file that is code or data uses `{{BRANCH}}`.

### The code leg

An agent name is an expression one of whose identifiers or string keys carries `branch`,
`agent`, `citizen`, `sender`, `recipient` or `owner`. It is capitalised when it goes through
`.upper()`, `.title()` or `.capitalize()`, directly or through a local assigned from one in
the same function (followed through re-assignment, f-strings and string methods such as
`replace` or `join`; a local of one function never marks another's). A finding is that value
stored:

- as a dict literal's key or value,
- as the key or value of a subscript assignment,
- as a path: either side of `/`, or the first argument of `open`, `Path`, `joinpath`,
  `with_name` or `write_text`.

A string literal that is an agent name in capitals fails the same way: as a dict key, as a
dict value under a key naming a name field (`name`, `branch`, `from`, `to`, `by`, ...), as a
stored subscript, or as a path whose part before the first dot is the name
(`"AI_MAIL.central.json"`). An agent name is the branch's own folder name or a row in its
registry, so a clean checkout knows only the branch's own name.

### What it leaves out

- **Screens and logs.** Nothing inside a `print`, console, logger, `log_operation` or
  `add_row` call is read. The owner has not ruled on screens.
- **Storage it cannot see.** A capital value that leaves the function before it is stored (a
  return value, an argument to a writer) is not followed, and neither is what a call returns
  when a capital name is its argument (a lookup key is not a stored name).
- **What it cannot tell apart.** A dict or a subscript store is read as storage. An in-memory
  map keyed by a capital label, a status dict returned to a screen, or a colour palette keyed
  by capital names fails the same way; each such site is waived by a row that says why.
- **Names it cannot prove.** A variable called `name` with no agent word, or a literal that
  is not the branch's own name or a registry row.

---

## Bypass

A row with `lines` waives one code site, and says why: a dict built only for a screen is
the case the code leg cannot tell from storage. The registry, data and template legs take no
bypass; their cure is the rewrite the finding names.
