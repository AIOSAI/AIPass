# Settings conformance corpus

Shared goldens for the two settings implementations — the python lane in
`aipass/api` and `settings.rs` in BAUD. **One set of cases, two runtimes, no
translation.**

## Why

The settings lane is a faithful mirror of `settings.rs`, and a mirror drifts.
@baud measured six real divergences in a single night — by *running* both, not
by reading each other's source — and every one was a place where two faces would
have written the operator's own config differently while each believed it was
correct.

Prose cannot hold a mirror straight. Shared **data** can. From here on, a
disagreement turns a case red on one side and names itself, instead of an
operator finding it.

## Layout

```
conformance/settings/
├── README.md         # this file — the format, next to the data it describes
├── manifest.json     # every case file, its sha256, and the total count
├── agent/*.json      # one case per file — .claude/settings.local.json
└── baud/*.json       # one case per file — .aipass/baud.settings.json
```

One case per file, on purpose: a failure names itself in the test output, a diff
touches only the case that changed, and a runner is a `read_dir` away from
working. The manifest exists so that "found nothing" and "found everything" can
never look the same.

## Case format

Pure JSON. No language's literals, no comments, nothing a `serde` derive cannot
walk.

```json
{
  "id": "agent-read-negative-window-is-null",
  "document": "agent",
  "description": "One sentence saying what rule this pins and why it matters.",
  "given":     { "path": ".claude/settings.local.json", "state": "present",
                 "content": { "autoCompactWindow": -5 } },
  "operation": { "kind": "read" },
  "expect":    { "outcome": "ok", "view": { "model": null,
                 "auto_compact_enabled": null, "auto_compact_window": null } },
  "runtimes":  { "python": "supported", "rust": "supported" },
  "notes":     "Optional. Provenance — which divergence, who was strict."
}
```

### `document`

Which door the case exercises. `agent` is the three-key surgical patch over
claude's own file; `baud` is BAUD's opaque document with shallow-merge
semantics. `manifest.json` maps each to its relative path.

### `given.state`

The starting state of the filesystem. Every one is a state a real branch can
genuinely be in — this is the half a prose spec always leaves vague.

| state | meaning |
| --- | --- |
| `missing` | parent directory exists, file does not |
| `absent_parent` | nothing on the way to the file exists either |
| `parent_is_a_file` | a **file** stands where the parent directory belongs |
| `empty` | the file exists and is zero bytes |
| `present` | the file holds `given.content`, serialised as JSON |
| `raw` | the file holds `given.raw` verbatim — for content that is not valid JSON, or is valid JSON of the wrong shape |
| `unreadable` | the file holds `given.content` and is then made unreadable (mode `000`) |

A runner that cannot produce a state **skips that case and says so**. It never
passes it — see `platform` below, which is how a case declares that.

### `operation`

`{"kind": "read"}` or `{"kind": "patch", "patch": <payload>}`. The payload is
handed to the door exactly as it appears — including when it is deliberately not
an object, which is itself a case.

### `expect`

`outcome` is one of three, and the split is the same one the HTTP surface makes:

| outcome | meaning |
| --- | --- |
| `ok` | the door answered |
| `refused` | the **caller's** fault — a 400, `SettingsRefused` in python |
| `unavailable` | **our** fault — a 503, `SettingsUnavailable` in python |

Alongside it, any of:

- `view` — the agent document's three-key API shape that was returned
- `document` — the baud document that was returned
- `file` — the **whole** document on disk afterwards, which is what pins that
  keys the door does not own survived
- `mode` — the file's permission bits, octal, as a string
- `file_unchanged` — `true` asserts the file's bytes are identical to before.
  A refusal that already wrote something is not a refusal.

### `runtimes`

| verdict | a runner must |
| --- | --- |
| `supported` | run the case and pass it |
| `pending` | **skip** it, reporting `notes` — a known divergence the other side has not closed |
| `divergent` | a difference ruled deliberate; see `expect_by_runtime` |

`pending` is not a way to park an inconvenience. It means the rule is agreed and
one implementation has not caught up, and the case documents the gap out loud
rather than pretending it is closed.

### `expect_by_runtime` (optional)

Per-runtime overrides folded over `expect`. Used only where the two runtimes
differ **on purpose** — today that is file mode, where python stages through
`mkstemp` and lands `0600` regardless of umask while rust inherits the umask
(measured at 664 under 0002, 644 under 0022 — not a constant, so it cannot be
written as one).

### `platform` (optional)

A runtime difference is about the implementation. A **platform** difference is
about the machine, and the two are not the same axis — python on Windows and
rust on Windows hit the identical wall. This block is that second axis.

```json
"platform": {
  "requires": ["unreadable_files"],
  "expect_without": {
    "posix_mode_bits": { "drop": ["mode"] },
    "parent_is_a_file_is_distinguishable": { "outcome": "ok", "document": {} }
  }
}
```

- **`requires`** — capabilities the case needs in order to be BUILDABLE. If any
  is absent, the runner **skips the case and names the capability**. The state
  could not be constructed, so running it would measure the harness.
- **`expect_without`** — for a capability the case survives without, the
  expectation override to fold in when it is absent. `drop` removes keys from
  the expectation; every other key replaces one.

**Every capability is MEASURED, never read off a platform string.** A runner
probes its own machine once, in a temporary directory:

| capability | the probe | absent when |
| --- | --- | --- |
| `unreadable_files` | write a file, `chmod 000`, try to read it | running as root, or on Windows, where the mode only sets a read-only attribute |
| `posix_mode_bits` | create with mode `0600`, read the mode back | Windows, which has no such semantics |
| `parent_is_a_file_is_distinguishable` | put a **file** where a directory belongs, open a path through it, look at what was raised | any OS that reports it as `FileNotFoundError` — there, a missing-file-reads-blank rule cannot tell a broken tree from a fresh branch |

That last one is a real, recorded semantic divergence rather than a
convenience: on a platform that cannot distinguish, the read genuinely answers
blank, and the corpus says so out loud instead of pretending both worlds refuse.

Expectations fold in a fixed order, and a second runner must reproduce it:
`expect`, then `expect_by_runtime[<runtime>]`, then every
`expect_without[<capability>]` this machine lacks — platform last, because it
describes the machine rather than the implementation.

## Writing a runner

Three jobs, and nothing else:

1. **Build** `given` under a temporary root. Hermetic — read nothing the machine
   happens to be carrying.
2. **Call** the door named by `document` and `operation`.
3. **Compare** against `expect`, with `expect_by_runtime[<your runtime>]` folded
   over it.

Two guards are not optional, because their absence reports as success:

- Fail if the corpus loads **zero** cases.
- Verify every file against `manifest.json`'s digests, and fail on a mismatch.

### The digest rule

`sha256` of each file's bytes **with `\r\n` normalized to `\n` first**, recorded
in the manifest's own `digest` field so a runner cannot get it wrong by
guessing. This is not tidiness. git rewrites text files to CRLF on a Windows
checkout under `core.autocrlf`, so a raw byte digest measures which OS ran the
checkout rather than whether a case changed — it went red on the Windows lane
on 2026-08-18 with nothing wrong. Line endings are not content of a JSON case.

A scoped `.gitattributes` in this directory pins `eol=lf` as well, so the
working tree stays byte-identical on all three platforms and a diff here is
always a case that really changed. The normalization is the **contract**
though, because a vendored copy in another repository carries its own checkout
rules and cannot inherit ours.

The python runner is `tests/test_settings_conformance.py` — about 200 lines,
most of it the state builder.

## Consuming this from another repository

BAUD lives in its own repository, so its runner cannot reach these files by a
relative path without assuming both trees are checked out side by side — an
assumption that fails in CI and, worse, fails *quietly*: no corpus found, no
cases run, green.

**Vendor a copy, and pin it by hash.** Copy this directory into the BAUD tree
and let the rust runner check `manifest.json` exactly as the python one does. A
stale copy then announces itself the moment a case changes here, instead of two
suites agreeing about different data.

The manifest is the whole mechanism: it carries the digests *and* the count, so
"my copy is old" and "my copy is empty" are both loud.

## Regenerating the manifest

After adding or editing a case, `test_the_manifest_matches_what_is_on_disk` goes
red until the manifest is updated — and it prints the corrected `manifest.json`
in the failure, ready to paste. A pin that only tells you that you are wrong
makes regenerating the tedious option and deleting the pin the easy one.
