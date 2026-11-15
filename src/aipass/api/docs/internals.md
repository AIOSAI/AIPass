[<- Back to the README](../README.md)

# Internals — the handlers fence and the conformance corpus

**Branch** api · **Code** `apps/handlers/__init__.py`, `apps/handlers/host/settings.py`

---

## The handlers fence walks frames without a working directory

`apps/handlers/__init__.py` walks frames with `sys._getframe`, skips pseudo-files and importlib
frames *before* any resolve, and guards each frame's resolve with a raw-spelling fallback
(`_frame_path`): an outer frame's filename can be relative (an `exec`'d source, a relative zip, a
sourceless `.pyc`), and resolving a relative path reads the cwd, which a process may have lost.

## The settings conformance corpus

The settings lane is a faithful mirror of @baud's `settings.rs`, and a mirror
drifts: a divergence is a place where the two faces would write the operator's
own config differently while each believes it is correct, and it is found by
*running* both implementations, not by reading each other's source.

Prose cannot hold a mirror straight; shared **data** can. `tests/conformance/settings/`
holds 39 cases in plain JSON — starting file state, the operation, the expected
outcome — that each runtime proves it satisfies in its own suite. The python
runner is `tests/test_settings_conformance.py`; a rust `#[test]` walks the same
files with `serde` and no translation, which is the whole design constraint.

Cases carry a per-runtime verdict, so a divergence one side has not closed yet
is **skipped and reported**, never quietly passed. Two differences are recorded
rather than forced: the desktop still accepts a zero compaction window and still
drops unknown patch keys (both freeze-gated on their side), and file mode
genuinely differs — python stages through `mkstemp` and lands `0600` whatever
the umask is, rust inherits it.

A settings file that is missing or empty reads as `{}` — a fresh branch, not a fault.
Anything that exists but is not a JSON object is an error, never blank.

**A runtime difference and a platform difference are two axes.** A wall that python
and rust both hit on the same OS cannot be described by a per-runtime verdict, so
cases carry an optional `platform` block, and every capability in it is **measured
on the machine**, never read off `sys.platform`:

- `unreadable_files` — write a file, `chmod 000`, try to read it. Absent for
  root and on Windows, where the mode only sets a read-only attribute. A case
  that needs it is **skipped with the capability named**, because its starting
  state could not be built and running it would measure the harness.
- `posix_mode_bits` — create with `0600`, read the mode back. Absent on Windows,
  so the mode expectation drops there and the rest of the case still counts.
- `parent_is_a_file_is_distinguishable` — put a **file** where a directory
  belongs and look at what opening through it raises. Where an OS reports it as
  `FileNotFoundError`, the missing-file-reads-blank rule genuinely cannot tell a
  broken tree from a fresh branch, and the read answers blank. That is a **real
  per-platform semantic divergence**, recorded as the expectation for that
  world rather than papered over.

**Digests normalize line endings before hashing, and the manifest says so in a
`digest` field.** git rewrites text files to CRLF on a Windows checkout under
`core.autocrlf`, so a raw byte digest measures which OS ran the checkout rather
than whether a case changed. A scoped `.gitattributes` pins `eol=lf` as well, but
the normalization is the contract, because a vendored copy in another repository
carries its own checkout rules.

The corpus guards itself, because the failure that matters reports as success: a
manifest pins every case by digest and by count, so an empty corpus and a stale
one are both loud. Two further guards cover the platform axis — a capability probe
that stops finding things would turn cases into *skips*, which read as green, so a
POSIX machine that fails to measure all three is an error; and the skip path itself
is exercised by taking the capabilities away by hand, because on a box that has them
the whole block is otherwise unreachable. See its own README for the format.

---

[← api README](../README.md)
