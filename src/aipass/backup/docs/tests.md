# Running the tests

[<- Back to BACKUP](../README.md)

```bash
python -m pytest src/aipass/backup/tests -q
```

Run it from the **repo root**. From the branch directory the local `aipass/`
tree shadows the installed package, and the suite then tests something other
than what ships.

The count belongs to the run, not to this page: whatever pytest prints is the
truth of the moment. The same goes for how the cases divide across files —
`test_drive_pipeline.py` and `test_dead_cwd_imports.py` are heavily
parametrised, so case counts run well ahead of function counts there.

## What the suite is careful about

- **Live files.** The audit trail honours `AIPASS_TEST_LOG_DIR`, so a test run
  writes its operation trail into a sandbox rather than the branch's own
  `logs/operations.jsonl`. One live file is still rewritten by a full run, for a
  reason that is a defect rather than a choice — see
  [known issues](known_issues.md).
- **Real credentials.** A help-gate test once patched only one lane, so `all`
  fell through to live OAuth and rewrote the machine's real Google credentials
  file. The pins that closed it stay in `tests/test_cli_routing.py`.
- **Fabricated filenames.** Tests that compile code under made-up paths keep
  those paths under `tmp_path`; a fabricated name that looks like a real tree
  file breaks the coverage report with no test failure at all. See
  [the handlers fence](module_fence.md).
- **New test files.** They need permission by fleet policy. Editing an existing
  test file is normal work; adding one is a conversation with @devpulse first.

---

[<- Back to BACKUP](../README.md)
