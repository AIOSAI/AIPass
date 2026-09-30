# Unused Conftest Fixture Standards
**Status:** v1
**Date:** 2026-09-22

---

## What It Is

Crack class **G** from the 2026-09-22 eyes-on review of @backup's tests. A fixture defined in
a branch's `conftest.py`, not `autouse`, that no test and no other fixture in the branch ever
requests.

It is apparatus nothing uses — dead weight that reads as shared infrastructure, so the next
author extends it instead of deleting it.

@backup's `tests/conftest.py` carries three: `temp_dir`, `sample_data` and `mock_logger`.
Cited by name: line numbers written here drift with every edit of that conftest.

---

## Three ways to request a fixture, and all three count

```python
def test_it(temp_dir): ...                      # by parameter name
@pytest.mark.usefixtures("temp_dir")            # by string
request.getfixturevalue("temp_dir")             # by string
```

Both string forms are why **every string literal** in the branch's tests is read as a possible
request. A rule that reads only parameter names convicts every fixture used through
`usefixtures` or `getfixturevalue` — that is most of the gap between the review's first cut
of 17 / 51 and this rule's 13 / 22.

`autouse=True` is never convicted. Nothing requests it by design; that is what autouse means.

---

## Built alone, not inside `conftest_fixtures`

The dispatch left this to me, so here is the reasoning.

`conftest_fixtures` is `all_files` and judges one `conftest.py` **in isolation** — its two
rules are about what that file itself contains. This question cannot be answered from that
file at all: whether a fixture is requested is a fact about the **whole branch's `tests/`
tree**. So the rule is `branch_level` and its entry point is `check_branch`.

Folding it into a file-level checker would have meant a file-level rule secretly reading its
siblings, which is exactly the coupling the two scopes exist to keep apart.

---

## Fleet standing on arrival

Measured 2026-09-22. **13 conftest files, 22 fixtures, 5.1s.**

| branch | fixtures |
|---|---|
| backup | 3 |
| drone | 3 |
| commons · daemon · memory · skills · spawn | 2 each |
| ai_mail · aipass · api · cli · devpulse · flow | 1 each |

@backup's three are the same fixtures the review named. The review cited the `@pytest.fixture`
decorator line and this rule cites the `def`, so the two line numbers differ by one — the
finding carries the live line.

@seedgo scores 100.

---

## Why it cannot be satisfied by accident

If no parameter, no `usefixtures` string and no `getfixturevalue` string in the entire branch
names the fixture, pytest can never construct it. Deleting it cannot turn the suite red.
**There is no threshold and nothing to tune.**

---

## Known limits

**Reading every string literal over-acquits.** A fixture whose name happens to appear as an
unrelated string anywhere in the branch's tests is acquitted. For a scored rule that is the
right direction, and it is why this number is smaller than the review's.

**Only `conftest.py` is judged.** A fixture in a test file is local to it, and its neighbours
either see it or do not.

**A fixture requested only from another branch** — there is no such thing today, and if there
were, this rule would convict it wrongly.

---

## Provenance

Crack class G of the owner's 2026-09-22 ruling, built on @devpulse's dispatch f66ac9d0
(DPLAN-0354). The brief is `dropbox/test_review_cracks_brief_2026-09-22.md`.
