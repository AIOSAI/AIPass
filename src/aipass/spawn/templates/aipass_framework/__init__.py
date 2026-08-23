"""{{BRANCHNAME}} - package marker so pytest's module names stay unique.

THIS FILE EXISTS TO KEEP PYTEST'S MODULE NAMES UNIQUE, and that is worth
stating because an empty-looking package marker is exactly the kind of file a
later cleanup deletes.

pytest names a conftest by walking UP from it while `__init__.py` files
exist, and the first directory without one becomes the package root. Without
this file that walk stops at `src/aipass/{{BRANCH}}`, so this branch's
conftest would be imported as the bare name `tests.conftest`. With it, the
walk continues to `src/` and the name becomes `aipass.{{BRANCH}}.tests.conftest`
- which is what every branch needs.

Two branches resolving to the same bare `tests.conftest` is a hard collection
error (`ImportPathMismatchError`), and it takes the WHOLE suite down, not
just the two: pytest aborts collection at the first clash. It stays
invisible until a SECOND branch is missing this marker - @canary and @hooks
collided this way on 2026-08-20 before this file existed to mint it at birth
(see commits b966b77d and 069974d4). Do not delete this file.
"""
