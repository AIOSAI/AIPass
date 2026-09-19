# Docs Page Standard
**Status:** Active v1.0
**Date:** 2026-09-19

---

## What This Covers

Every `<branch>/docs/*.md` page (one level). A page is a guide a seat reads on arriving at the branch, or a stranger reads from GitHub. After one page the reader can find the verb, understand the reason behind the design, and knows what is not verified. The README is the face; `docs/` is the depth, one page per module or handler group (DPLAN-0347). Every page has one shape, so page-to-page sameness makes a random sample honest (DPLAN-0351).

---

## The Shape

```
[<- Back to the README](../README.md)
# <Title>
<one purpose paragraph, present tense>
## <topic>            free topic sections, current tense, depth <= 3
### <detail>
## Why it is this way      optional, fixed name when present
## What is not verified    optional, fixed name when present
## Related                 optional, fixed name when present
```

- Commands by reference: `drone @<branch> --help` is the source of truth.
- No history: the CHANGELOG carries what changed and when.
- No cured entries, no defect paragraphs: an open defect lives on the owner's pad.
- `docs/README.md` is the index shape: back-link, title, one line, then one line per page.

---

## Scored Checks

| # | Check | Passes when |
|---|-------|-------------|
| 1 | One H1, first | Exactly one `# ` heading outside code fences; only blank lines, HTML comments and a README back-link above it |
| 2 | Purpose paragraph | The first line under the H1 (back-link lines skipped) is prose: not a heading, list, table, quote, fence, rule or lone link |
| 3 | Heading depth | No heading deeper than `###` |
| 4 | Links resolve | Every relative link and image target exists, resolved from the page's own directory |
| 5 | Size | At most the context pack's `caps["docs/*.md"].max_chars`, read at call time; at the cap passes; an unreadable cap fails and names the key |

Five checks, 20 points each; pass threshold 75%. The CI job holds every branch at 100. A branch with no `docs/*.md` skips all five.

---

## Advisory Lines

Rendered by `check_branch_info()` at any score; never a score, a pass or a violation.

- **back-link** — no README back-link above the purpose paragraph. The DPLAN-0347 move stamp's link, below the purpose, is not the slot. Advisory until one mechanical wave, then scored.
- **story** — `used to`, `previously`, and fixed/cured/corrected/retired beside a date. These arms hand-sampled at 7/8 or better; the ~50% arms (`no longer`, `was <verb>`, `as of <date>`) are not built. A dated reason stays; a dated change is history.
- **defect prose** — an open defect told as a paragraph (`known gap`, `still open`, `tracked in APLAN-…`). Link text is not read, and a line linking to the register is a pointer, not a defect.

---

## Exempt

- Pages whose name contains `known_issues` or `tech_debt` — defect registers pending the owner's ruling. No rule, scored or advisory, reads them until he rules.
- `docs/**/` below one level, and `docs.local/` — not the corpus. Research and dated one-offs belong in `docs.local/`.

---

## Bypass

Per page, by path, in the branch's `.seedgo/bypass.json`:

```json
{"file": "docs/<page>.md", "standard": "docs_page", "reason": "..."}
```

A rule on the entry point bypasses the whole standard.

---

## Related

- `readme.md` — the README standard and its docs index lane (every page reachable from the README)
- `context_standards/pack.json` — the size cap key
- DPLAN-0351 — the survey and the owner's rulings behind this shape
