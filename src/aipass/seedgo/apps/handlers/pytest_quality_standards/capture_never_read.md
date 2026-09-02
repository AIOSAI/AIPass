# capture_never_read — did the test look at what it captured?

> A unit that arranges to SEE something and then never looks proves nothing
> about what was printed. Requesting the fixture costs a line of source, so it
> is a declaration of intent — and an unread capture is that intent abandoned.

**Scope:** `branch_level` · **Severity:** advisory · **Ported from:** TAXONOMY section 5 rule 8

---

## Why this rule exists

`no_oracle` asks whether a unit verifies anything. `assertion_shape` asks whether
its assertions can fail. This rule asks a narrower and more embarrassing
question: the test asked for the output, and then never read it.

It is the most precise tell in the pack, and precise for a structural reason.
`capsys` does nothing whatsoever unless `readouterr()` is called — it is not a
setting, it is a buffer with a read method. A signature that names it and a body
that never reads it is either a leftover from an assertion somebody deleted, or a
test that was never finished. One live example was found requesting `capsys`,
never reading it, and surviving a probe that changed what the program prints.

## CAPTURE-NEVER-READ

```python
def test_help_flag_prints_usage(capsys):
    main(["--help"])                    # flagged: capsys is never read
```

The fix is to read what you captured:

```python
def test_help_flag_prints_usage(capsys):
    main(["--help"])
    assert "usage:" in capsys.readouterr().out
```

If the output genuinely does not matter, drop the fixture from the signature. It
is costing every future reader a question that has no answer in the body.

## RECEIPT-ONLY

```python
def test_summary(rows):
    assert print_summary(rows) is True      # flagged: a receipt, not evidence
```

`print_summary`'s whole job is what it emits. `True` means the call returned —
it says nothing about what came out. The function could print an empty string
forever and this test would stay green.

```python
def test_summary(rows, capsys):
    print_summary(rows)
    assert "3 rows" in capsys.readouterr().out
```

## Sole is the species

This is the direction in which being wrong would do real damage, so the rule is
narrow on purpose. A receipt standing **beside** anything else is never flagged:

```python
def test_key_is_fetched_once(mock_keys):
    result = show_key(mock_keys)
    assert result is True                            # not flagged — it has company
    mock_keys.get_api_key.assert_called_once_with("prod")
```

And a predicate under test is never flagged, because there the boolean **is** the
behaviour:

```python
def test_ssl_errors_are_recognised():
    assert is_ssl_error(SSLError("bad handshake")) is True
```

Nine assertions of the first shape and five of the second were found in one
fleet's suite, and every one of them is correct. A rule that convicted them would
be switched off within a day, and would deserve to be.

## What this rule does not claim

- **It does not follow calls.** A unit that hands `capsys` to a helper which
  reads it is flagged, and that flag is wrong. Following the call means resolving
  a helper across modules — an interpreter, not a reader.
- **It does not cover `caplog`,** despite what the rule's name suggests. `capsys`
  has a read *method*: a call site a reader can find. `caplog` is read by
  touching `.records` or `.text`, which is ordinary attribute access and looks
  exactly like every other attribute access in the body. Naming a fixture the
  mechanism cannot judge would turn a precise tell into a guess.
- **The output-prefix list is a measured under-count.** A hand audit recorded 24
  receipt-only units in one branch and this rule finds none of them: that
  branch's receipts sit on `handle_command`, a router. Widening the prefixes to
  catch routers would also catch every predicate under test. The gap is published
  rather than closed by guessing.
- **The receipt constants are wider than their name.** The set is `(True, 0)` and
  Python decides membership by equality, so `is False` and `== 1` read as
  receipts too. All four are receipts by the same argument — a bare boolean or
  exit code from a function whose work is what it prints — so the behaviour is
  kept and this line is the correction.

## Scoring

Units that read what they asked for, over total units. **Per unit, not per
finding**: a unit already flagged for an unread capture is not judged a second
time for a receipt, and the scorer deduplicates regardless, because a flagged
total that can exceed the unit total reports a negative score.

**Advisory**: it reports a number and never fails a board.

A project with no test files reports `not_applicable` rather than zero. A project
whose only test file is unparseable says so explicitly, and is never reported as
a project without tests.

*Ported from `tests_pytest_standards/capture_never_read_check.py` · Design: DPLAN-0323 / FPLAN-0469*
