# Testing Standards
**Status:** Draft v1 - Current manual process documented
**Date:** 2025-11-12

---

## Current State: Manual Testing (Effective for Rapid Iteration)

**Reality:** AIPass is a custom framework in active evolution. System changes weekly. Building extensive test infrastructure now = updating tests constantly instead of building features.

**Current approach:** Manual testing with JSON/log verification works effectively for rapid iteration phase.

**Future:** pytest framework expansion once branches stabilize (pytest is already configured and operational in some branches).

---

## The 90% Build Process

**How we build and test:**

### 1. Planning Phase (Upfront Investment)
- Issue plan through Flow (master plan or default plan depending on scope)
- Spend time getting structure right before coding
- Define what we're building and how it fits together

### 2. Build to 90% (AI-Led, Internal Verification)
- AI builds structure and implementation
- **Internal verification tests as we go:**
  - Does the module turn on?
  - Do commands work?
  - Basic functionality confirmed?
- Human mostly observes, provides input if things go astray
- Focus on getting structure and pieces in place

**Linux advantage:** Same environment (AI and human both on Linux) = outputs match = internal tests are reliable. Windows had issues with this, Linux doesn't.

### 3. 90% Threshold (Human Review Phase)
- Human gets actively involved
- Reviews structure and implementation
- Asks questions about concerns
- Performs feature tests (what module is supposed to do)
- Identifies bugs and missing error handling

### 4. Debug Cycle (Error Handling First, Then Fixes)

**Critical pattern: Fix error handling BEFORE fixing bugs**

**Example scenario:**
```
Bug: API call not working, but console says "Success"
No error output, but logs show API never executed
Output is lying

Process:
1. Fix error handling FIRST - make errors tell the truth
2. THEN fix the actual bug (why API isn't executing)
3. See clean pass with honest outputs
4. Move to next feature
```

**Why this order:**
- Can't debug effectively if errors lie
- Truth in outputs = faster debugging
- Honest error messages = system teaches itself what's wrong

### 5. Iterate Until Acceptable
- Test different features
- Continue debug cycle (handle errors → fix bugs → verify)
- Reach acceptable standard (basic or advanced depending on module)
- Move on

---

## Why Manual Testing Works Right Now

**Advantages:**
- **Fast iteration** - No test maintenance overhead
- **Flexible** - System can change tomorrow without breaking test suite
- **JSON/log infrastructure** - Acts as verification layer
  - Check config.json → see settings
  - Check data.json → see state
  - Check log.json → see operations history
  - Check Prax logs → detailed debugging
- **Linux environment match** - AI tests = human tests (same outputs)
- **Effective debugging** - Error-first approach catches issues early

**Tradeoffs:**
- Manual effort required at 90% stage
- No automated regression testing (yet)
- Relies on human review for final verification

**Acceptable because:** System is evolving rapidly. Better to build fast and test manually than build slow and maintain brittle tests.

---

## Future: pytest Framework

**Infrastructure in place:**
- `pytest.ini` at repo root - Configuration for test discovery and markers
- `tests/` - Root test directory with conftest.py
- Branch-specific test directories at `src/aipass/{branch}/tests/` (API, Prax, CLI, etc.)

**Already operational in some branches:**
- API branch: 4 test files (test_api_system.py, test_openrouter_key.py, etc.)
- Prax branch: test_log_rotation.py validates rotation behavior
- Seedgo branch: test_cli_errors.py demonstrates error handling patterns

**When to expand testing:**
- Once modules and branches stabilize
- When system changes slow down (monthly, not weekly)
- When maintenance cost < value of automation

**Why pytest:**
- Standard Python testing framework
- Already configured with pytest.ini
- Infrastructure exists, ready for expansion
- Some branches already have working tests

**Current selective approach:**
- Test critical/stable components (API, Prax log rotation)
- Skip testing rapidly changing features
- Manual testing for experimental work
- Automated tests where they add value without maintenance burden

---

## Error Handling Philosophy

**Errors must tell the truth** - foundational to testing effectiveness

**Good error handling:**
```python
try:
    result = api_call()
    if not result:
        logger.error("API call failed - no response")
        return {"success": False, "error": "API returned no data"}
except Exception as e:
    logger.error(f"API call exception: {e}", exc_info=True)
    return {"success": False, "error": str(e)}
```

**Bad error handling:**
```python
try:
    result = api_call()
    return {"success": True}  # LIES - didn't check if result valid
except:
    pass  # Silent failure - no truth
```

**Testing relies on honest errors:**
- If errors lie, testing is impossible
- Fix error handling first = testing becomes possible
- Then fix bugs with confident verification

---

## JSON/Log Infrastructure as Testing Layer

**Three-JSON pattern supports testing:**

### Config Verification
```bash
# Check if settings are correct
cat module_name_config.json
# See API keys, limits, feature toggles
```

### State Verification
```bash
# Check current state
cat module_name_data.json
# See metrics, counts, current status
```

### Operations Verification
```bash
# Check what actually happened
cat module_name_log.json
# See recent operations and results
```

### Detailed Debugging
```bash
# Prax provides file-based logging, not real-time watching
# Check system logs directory for detailed output
ls -la system_logs/
# Read specific module logs (Prax manages this directory location)
cat system_logs/module_name.log
```

**This infrastructure = verification layer without formal tests**

---

## Testing Workflow Example

**Building a new branch creation module:**

1. **Plan** - Define structure, features, workflow (Flow plan)

2. **Build to 90%** - AI implements:
   - Module structure
   - Handler functions
   - Config/data/log JSONs
   - Internal verification: "Does `create_branch test_branch` work?"

3. **Review at 90%** - Human tests:
   - Create branch with various names
   - Check if files copied correctly
   - Verify registry updated
   - Try edge cases (existing branch, invalid name)

4. **Find bug** - Branch created but registry not updated
   - **First:** Check error handling - is error logged? Is return value honest?
   - Add error handling if missing
   - **Then:** Fix bug - why isn't registry updating?
   - Verify with clean pass

5. **Iterate** - Test more features:
   - Template copying
   - Placeholder replacement
   - Memory file handling
   - Backup on conflicts

6. **Acceptable** - All major features work, errors are honest, ready to use

---

## Current Testing Checklist

**For any new module/feature:**

- [ ] Does it turn on without errors?
- [ ] Do basic commands work?
- [ ] Are errors handled and logged?
- [ ] Do outputs tell the truth?
- [ ] Check config.json - settings correct?
- [ ] Check data.json - state tracking working?
- [ ] Check log.json - operations recorded?
- [ ] Test edge cases (invalid input, missing files, etc.)
- [ ] Check Prax logs in system_logs/ for detailed debugging info
- [ ] Manual feature tests at 90% stage

---

## When to Test What

**During development (AI internal verification):**
- Module starts without errors
- Basic commands execute
- Expected output appears

**At 90% stage (human testing):**
- Feature functionality (does it do what it's supposed to?)
- Edge cases (what breaks it?)
- Error handling (are errors honest?)
- Integration (does it work with other modules?)

**Before considering "done":**
- Clean passes on major features
- Errors tell the truth (no silent failures)
- JSON logs show operations correctly
- Acceptable standard reached (basic or advanced)

---

## Summary

**Current approach:** Manual testing with JSON/log infrastructure

**Why it works:**
- Fast iteration without test maintenance
- Linux environment = reliable verification
- Error-first debugging = effective bug fixing
- JSON/log system = verification layer

**Build process:** Plan → Build to 90% → Review/test → Debug (errors first, then bugs) → Iterate → Acceptable

**Future:** pytest framework when system stabilizes

**Philosophy:** Build fast, verify as you go, handle errors honestly, iterate rapidly. Test infrastructure comes after stability.

---

## Pytest Test Structure

**Current implementation:**
```
pytest.ini                          # Test configuration (repo root)
tests/                              # Root test directory
  conftest.py                       # Shared fixtures
src/aipass/
  api/tests/                        # API tests (4 files operational)
    test_api_system.py
    test_openrouter_key.py
    test_free_models_quick.py
    test_paid_model.py
  prax/tests/                       # Prax tests
    test_log_rotation.py
  cli/tests/                        # CLI tests (infrastructure ready)
  seedgo/
    tests/conftest.py
    apps/modules/test_cli_errors.py  # Demo module
```

**Running tests:**
```bash
# Run all tests
pytest

# Run specific branch tests
pytest src/aipass/api/tests/

# Run with markers
pytest -m unit
pytest -m integration
pytest -m slow
```

**Test demonstration module:**
- `src/aipass/seedgo/apps/modules/test_cli_errors.py` - Shows error handling patterns
- Not a pytest test, but demonstrates testing concepts
- Run directly: `python3 src/aipass/seedgo/apps/modules/test_cli_errors.py`

---

## Comments

#@comments:2025-11-13:claude: Pytest infrastructure exists and operational in API/Prax branches. Selective testing approach: automate stable components, manual testing for rapid development.

#@comments:2025-11-13:claude: Prax doesn't have real-time "watcher" command for logs - uses file-based logging in system_logs/ (Prax manages the location). Updated documentation to reflect actual capabilities.

#@comments:2025-11-13:claude: Error-first debugging approach is critical - maybe this should be emphasized in error_handling.md when we fill that section?

#@comments:2025-11-13:claude: "90% threshold" is interesting pattern - not 100% perfection, but "acceptable standard" (basic or advanced). Reflects pragmatic development philosophy.
