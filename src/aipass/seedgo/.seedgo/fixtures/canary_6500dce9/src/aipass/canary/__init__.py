"""Canary - the permanent test citizen (DPLAN-0312).

THIS FILE EXISTS TO KEEP PYTEST'S MODULE NAMES UNIQUE, and that is worth
stating because an empty-looking package marker is exactly the kind of file a
later cleanup deletes.

pytest names a conftest by walking UP from it while `__init__.py` files exist,
and the first directory without one becomes the package root. Without this
file that walk stops at `src/aipass/canary`, so this branch's conftest is
imported as the bare name `tests.conftest`. With it, the walk continues to
`src/` and the name becomes `aipass.canary.tests.conftest` - which is what the
other branches already get.

Two branches resolving to the same bare `tests.conftest` is a hard collection
error (`ImportPathMismatchError`), and it takes the WHOLE suite down, not just
the two: pytest aborts collection at the first clash. It is invisible until a
second offender is born - CI collects every branch in ONE process, so the
branch that has been missing its marker for months is fine right up to the
moment another one joins it. That is how this landed: @canary's birth commit
turned @hooks' long-standing omission into a red board.
"""
