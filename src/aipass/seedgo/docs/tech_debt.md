# Known issues and tech debt

**Branch** seedgo · **Standing record** APLAN-0005 — that plan is the live status; this page is
the reasoning behind each entry.
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract): a dated status block in
the face of the branch is a snapshot that is true once and unfalsifiable afterwards.

Every entry below was re-checked on 2026-09-07 unless marked **UNVERIFIED**. Where an entry
quotes a number, treat the number as the date's, and re-run the command beside it.

---

## Where the live status actually is

| The old README section | Its live equivalent |
|---|---|
| `## Status (2026-09-07)` — self-audit, tests, type errors, proof, coverage, bypass count | **replaced by** `drone @seedgo audit aipass @seedgo` (score + diagnostics + coverage line), `drone @seedgo proof aipass` (certification), `drone @seedgo test_map @seedgo` (coverage), `.seedgo/bypass.json` (the rules themselves), and the pytest command in [proof_and_coverage.md](proof_and_coverage.md) |
| `## Latest Audit (2026-09-12)` — one run's scores | **replaced by** `drone @seedgo audit aipass @seedgo`, whose untruncated result is written to `.seedgo/last_audit_seedgo.json` every run |
| The startup-cost row | **replaced by** `drone @seedgo audit context @seedgo` |

Nothing in those two blocks was a fact about the branch that code could not regenerate. That
is the whole test for whether a section belongs in the README.

---

## Proof: NOT CERTIFIED

`drone @seedgo proof aipass` does not certify this branch's own pack. On 2026-09-07,
`content_naming`, `interface` and `plugin_integrity` passed; two did not.

### `readme_currency` FAILED — three causes, one of them a detector bug

Verbatim: *"README is stale: count mismatch, 1 stale reference(s), 44 undocumented
standard(s). (15 issues)"*.

1. It recognises standard names only in a `pack checks:` prose format this branch's README has
   never used, so an accurate standards table still reads as "undocumented".
2. It scrapes any number near a pack reference as the claimed check count, so a sentence about
   how many checkers ship no `.md` is read as a claim about pack size.
3. It harvests the bullet *describing* the bug into `stale_refs` — writing the detector's own
   defect down makes the detector fail harder. A checker cannot tell a document from a
   document *about* the document; `rich_markup` on `# BAD` examples is the same species.

The README diet of 2026-09-15 removes the count claims this detector was scraping; the
detector's three causes are unchanged.

### `triplet` FAILED

Live 2026-09-07: **37 complete | 1 check-only | 1 missing-check | 7 other-incomplete |
4 orphaned | 46 total (9 issues)**.

- **8 checkers ship no `.md`** — the 7 "other-incomplete" (`cli_ux`, `gateway_boundary`,
  `hardcoded_path`, `json_structure`, `readme_quality`, `rich_markup`, `subcommand_help`) plus
  `ruff`, the "check-only" entry, which is missing content *and* md. `gateway_boundary` shipped
  without one on 2026-08-18 and still has none.
- The `ruff` / `ruff_check` name split is what produces the check-only + missing-check pair —
  see [aipass_standards.md](aipass_standards.md).
- The **4 orphans** are `trinity_groups.py`, `applicability.py`, `skip_dirs.py` and
  `exception_handling.py`: shared infrastructure living in the pack directory without being
  standards, which the triplet proof has no category for.

---

## Open

- **`standard ruff` returns "Unknown standard"** while the audit displays the standard as
  `Ruff`. The naming split, in [aipass_standards.md](aipass_standards.md). APLAN-0005.
- **`--help` advertises `drone @seedgo diagnostics @flow`**, but the module rejects a branch
  argument — standalone diagnostics is disabled and runs through the audit pipeline. Re-checked
  2026-09-07: the answer is *"Unknown argument: '@flow'"*.
- **This README has no auto-update markers**, so `drone @seedgo readme check @seedgo` skips
  every section — re-run 2026-09-07, five sections, all *"Skipped — no marker found"*. The
  branch that ships README generation does not consume it.
- **No bypass-rot detection, and the obvious detector is wrong.** Nothing tells a branch that a
  bypass rule has stopped suppressing anything. The tempting measurement — re-run the audit with
  `bypass_rules=[]` and match each rule against the resulting violation records — was run on
  2026-08-13 against 28 rules and called 6 of them dead. Five were live: four suppress real
  failures in the **checklist** lane (the audit walks `apps/`, the PostToolUse hook checks
  `tests/`), and one guards `dead_code`, a branch-level standard that reports through
  `checks[].message` prose rather than a `*_violations` list — removing it drops that standard
  100 → 95. A rot detector must read both lanes and canary branch-level standards through
  `check_branch()`. **UNVERIFIED at today's rule set:** the sweep has not been re-run since
  2026-08-13. APLAN-0005.
- **`documentation_check.py` multi-line signature lookahead is 30 lines**, not the 5 an older
  edition of this note claimed — `min(line_num + 30, len(lines) + 1)`. Still a bounded window,
  still a limitation, six times wider than documented.
- **`dead_code_check.py` recognises `glob("*.py")` as a discovery pattern but not
  `iterdir()`** — no `iterdir` appears anywhere in the file. Re-verified 2026-09-05, unchanged
  2026-09-07.
- **`standards_audit.print_help` has no test calling it.** Removing
  `test_handle_command_output_capture` (a DELETE verdict from the 2026-09-05 contested band,
  whose own comment said the `capsys` fixture was there "to satisfy the pattern requirement")
  left the function reached only through `handle_command`'s no-args path. The removed row
  asserted nothing about the output it captured, so this is a gap that was already there, now
  visible. Noted, not papered over.
- **`apps/seedgo.py` carries header version 2.0.2 while its `VERSION` constant reads 2.0.1**,
  so `drone @seedgo --version` and the file header disagree. Observed 2026-09-15 during the
  README diet; not touched in that pass, and no session in this branch's memory records which
  change left them apart.

---

## Closed, kept for the species

- ~~`test_quality_check.py` says 11 categories and holds 7~~ — **moot 2026-09-07: the file is
  archived.** The 09-05 pass found its header and docstring claiming *"11 categories"* against a
  `STANDARD_CATEGORIES` of 7. It was never corrected because the standard retired first
  (FPLAN-0491). Recorded rather than deleted: a docstring outliving the table it describes is
  the species, not the instance.
- ~~`--help` names 13 commands and the branch answers 19~~ — fixed 2026-09-06. `audit-tests`,
  `test-inventory`, `shadow-cycle`, `permissions`, `inbox_audit` and the `audit pytest_quality`
  pack are all in the help text and its `Commands:` line.
- ~~`permissions.py` introspection leak~~ — **fixed 2026-08-13 (S80).** The gate keyed on the
  arguments, never the command name, so the trust list printed above every bare subcommand while
  `drone @seedgo permissions` answered "Unknown command" *and then* printed the block. It now
  claims its own command and is silent for every other.
- ~~`audit_display.py` carries 16 hardcoded per-standard display blocks~~ — **the DPLAN-0047
  dynamic refactor landed.** The file derives every standard from its `<name>_violations` key
  and renders it generically, with exactly one special case left (`architecture`, which routes
  to its own renderer because it reports through `results['checks']`). Re-verified 2026-09-05,
  unchanged 2026-09-07. Not attributed: this branch's memory does not record who made it.
- ~~Cross-branch file write detection recommended but not in standards (S73)~~ — **shipped as
  `gateway_boundary`, 2026-08-18.**
- ~~The module path `python3 -m aipass.seedgo`~~ — never worked and is no longer advertised.
  There is no `__main__.py`; the entry point is the full path
  `python3 -m aipass.seedgo.apps.seedgo`. The README advertised the short form until
  2026-08-25.

---

## Related

- [aipass_standards.md](aipass_standards.md) · [audit_engine.md](audit_engine.md) ·
  [proof_and_coverage.md](proof_and_coverage.md)
