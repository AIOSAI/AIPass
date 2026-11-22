# Lowercase Name Standard
**Status:** v2
**Date:** 2026-11-22
**Standard:** `lowercase_name` (branch_level, pass or fail)

---

## What This Standard Is

The system speaks lowercase. An agent's name is lowercase wherever it runs: in a registry, in a
branch's data files, and in what code prints, logs or labels, including banners, `[tag]` log
tags and help text. The owner's ruling, 2026-11-22. A document is not the runtime, so this
standard never opens a `.md` file.

---

## Why It Matters

- **One name, one spelling.** A name stored as `FLOW` in one file and `flow` in another is
  two keys to every exact comparison, and the second lookup misses.
- **A screen teaches the spelling.** An agent that reads `[SENTRY]` in a log or `SENTRY AUDIT`
  on a banner writes the name that way next.
- **Code is the part that writes it.** Fixing the stored files once does nothing while a
  writer still capitalises: the next write brings the capital back.

---

## What the Checker Checks

One finding fails the standard. There is no partial score, and no site needs a waiver.

| Leg | Where | Fails when |
|---|---|---|
| Registry row | this branch's row in the `*_REGISTRY.json` at or above it | the `name` is not lowercase, or the `path` is absolute |
| Data files | `.trinity/passport.json` `branch_info.branch_name`, `artifacts/birth_certificate.json` `owner`, `DASHBOARD.local.json` `branch` | the value is not lowercase, or the file is unreadable or not JSON |
| Code | production Python under `apps/` and `shared/` | an agent name is forced to capitals, or written in capitals (below) |

The registry, passport and certificate findings name the cure
`drone @spawn sync-registry <registry> --lowercase`; the dashboard finding names
`drone @prax dashboard refresh @<branch>`. The project's own name (the registry file's stem and
`metadata.name`) is not checked as a row.

### The code leg

An **agent name** is the branch's own folder name or a row in its registry, read at check time,
so the rule works for any project's registry. Two shapes fail:

- **Forced to capitals.** `.upper()`, `.title()` or `.capitalize()` called on an expression one
  of whose identifiers or string keys carries `branch`, `agent`, `citizen`, `sender`,
  `recipient`, `owner` or `caller` (`caller.upper()`, `branch["name"].title()`). An operand of
  a comparison is exempt: `a.upper() == b.upper()` is a case-fold, not output. So is a value
  assigned to a local the function reads only in comparisons (`wanted = branch.upper()`).
- **Written in capitals.** A string literal holding a whole word, made of letters, digits and
  `_`, that is all capitals and whose lowercase is an agent name: `"[SENTRY] failed"`,
  `"SENTRY AUDIT"`, `f"{x} sent to DRONE"`. Literals inside a call, an f-string or a
  concatenation all count; the finding names the source line the word sits on.

Words that are not agent names stay legal: `FPLAN`, `README`, `JSON`, `UNKNOWN`, column headers.
A word joined to more by `_` is one token, so identifiers and file names such as
`AI_MAIL_REGISTRY.json` or `AGENT_AIPASS` are not a name.

**Names that are also common words.** `cli`, `api`, `flow`, `hooks`, `memory`, `trigger` and
`aipass` (the project's own name) are English or product words in capitals as often as they
are agents ("PUBLIC CLI", "CREATE TRIGGER", "IN MEMORY"). In capitals they count only in a
name position:

- a tag, `[HOOKS]` or `[HOOKS:sub]`, or a `:HOOKS]` suffix,
- an address `@HOOKS` or a value `=HOOKS`,
- the whole literal, alone or wrapped in markup (`"[bold]FLOW[/bold]"`),
- the head of a banner: the name followed by a dash or a version (`"CLI v1.0.0"`).

### What it leaves out

- **Comments and docstrings.** They are prose for the reader, not runtime output; the parser
  never sees a comment, and a docstring is skipped.
- **Title Case.** `Sentry` is also a sentence's first word or a product name; the leg reads
  only all capitals.
- **A common-word name outside a name position.** `"HOOKS BROKEN:"` or `"FLOW STATUS"` pass.
- **Capitals made another way.** `str.upper(branch)`, or `.upper()` on a variable whose name
  carries no agent word (`name.upper()`).
- **A clean checkout.** With no registry beside it (CI), the roster is the branch's own name
  only.

---

## Bypass

A row with `lines` waives one code site and says why. The rule is drawn so that none is needed.
The registry and data legs take no bypass; their cure is the command the finding names.
