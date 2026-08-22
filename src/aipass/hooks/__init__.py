"""Hooks - package marker so pytest's module names stay unique (per devpulse, 2026-08-20).

THIS FILE EXISTS TO KEEP PYTEST'S MODULE NAMES UNIQUE, and that is worth
stating because an empty-looking package marker is exactly the kind of file a
later cleanup deletes.

pytest names a conftest by walking UP from it while `__init__.py` files exist,
and the first directory without one becomes the package root. Without this
file that walk stops at `src/aipass/hooks`, so this branch's conftest is
imported as the bare name `tests.conftest`. With it, the walk continues to
`src/` and the name becomes `aipass.hooks.tests.conftest` - which is what
every other branch already gets.

Two branches resolving to the same bare `tests.conftest` is a hard collection
error (`ImportPathMismatchError`), and it takes the WHOLE suite down, not just
the two: pytest aborts collection at the first clash. @hooks was the only
branch missing this marker for months and got away with it by being the only
offender - @canary's birth (2026-08-20) made it two and red the board. That
collision is already fixed on canary's side (src/aipass/canary/__init__.py,
commit b966b77d). This file closes the other half so the next branch born
without a marker doesn't collide with @hooks instead.
"""
