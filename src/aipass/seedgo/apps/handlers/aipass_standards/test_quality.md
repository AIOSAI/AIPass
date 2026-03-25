# Test Quality Standards
**Status:** v3.0 — 10 standard categories (48 items)
**Date:** 2026-03-24

---

## What It Is

The test quality standard evaluates whether a branch's test files cover 10 standard test categories (48 total items). It scans ALL `test_*.py` files and `conftest.py` in a branch's `tests/` directory. This is a static analysis check; it does not run pytest, only inspects test file contents for detection patterns.

---

## Why It Matters

Standard test categories ensure every branch tests its shared infrastructure (json_handler, CLI routing), error handling, contracts, and fixtures consistently. Coverage breadth across categories means reliable, predictable behavior across the ecosystem.

---

## The 10 Categories

### 1. JSON Handler (8 items)
| Item | Detection Patterns |
|------|-------------------|
| default_factory | `_create_default`, `_get_default_template`, `_get_default`, `_default_template`, `load_template`, `_default_config` |
| validate | `validate_json_structure` |
| get_path | `get_json_path` |
| ensure_exists | `ensure_json_exists` |
| load | `load_json` |
| save | `save_json` |
| log_operation | `log_operation` |
| ensure_module | `ensure_module_jsons` |

### 2. CLI Routing (9 items)
| Item | Detection Patterns |
|------|-------------------|
| help_flag | `--help` |
| short_help | `"-h"`, `'-h'` |
| help_word | `"help"`, `'help'` |
| no_args | `test_no_args`, `test_introspection`, `no_args` |
| unknown_command | `unknown_command`, `invalid_command`, `unrecognized` |
| return_bool | `is True`, `is False` |
| print_help | `print_help` |
| print_introspection | `print_introspection` |
| output_capture | `capsys`, `capfd`, `StringIO` |

### 3. Conftest Fixtures (6 items)
| Item | Detection Patterns |
|------|-------------------|
| temp_dir | `tmp_path`, `temp_test_dir`, `temp_dir` |
| sample_data | `sample_test_data`, `sample_data` |
| mock_infrastructure | `mock_infrastructure`, `autouse` |
| mock_logger | `mock_logger`, `mock_log` |
| mock_json_handler | `mock_json_handler`, `mock_json` |
| cleanup | `rmtree`, `yield`, `teardown` |

### 4. Error Resilience (4 items)
| Item | Detection Patterns |
|------|-------------------|
| missing_file | `FileNotFoundError`, `missing_file`, `file_not_found` |
| corrupt_json | `JSONDecodeError`, `corrupt`, `malformed` |
| empty_file | `empty_file`, `empty_content` |
| nonexistent_dir | `nonexistent`, `missing_dir`, `not_a_dir` |

### 5. Return Type Contracts (4 items)
| Item | Detection Patterns |
|------|-------------------|
| command_returns_bool | `isinstance(result, bool)`, `returns_bool`, `return_type` |
| paths_return_path | `isinstance(result, Path)`, `pathlib.Path` |
| ensure_returns_bool | `ensure_json_exists`, `is True` |
| load_correct_type | `isinstance(result, dict)`, `isinstance(data, dict)` |

### 6. Exception Contracts (3 items)
| Item | Detection Patterns |
|------|-------------------|
| create_default_raises | `pytest.raises(ValueError)`, `ValueError`, `_create_default` |
| save_invalid_raises | `pytest.raises`, `save_json` |
| invalid_mode_raises | `pytest.raises(ValueError)`, `invalid_mode`, `invalid_type` |

### 7. Data Structure Contracts (3 items)
| Item | Detection Patterns |
|------|-------------------|
| config_keys | `module_name`, `config_keys` |
| data_keys | `last_updated`, `data_keys` |
| log_entry_field | `log_entry`, `operation` |

### 8. Success/Failure Paths (4 items)
| Item | Detection Patterns |
|------|-------------------|
| known_routes_true | `assert result is True`, `== True` |
| unknown_returns_false | `assert result is False`, `== False` |
| help_preempts | `--help` |
| no_args_triggers | `print_introspection` |

### 9. Init/Provisioning (4 items)
| Item | Detection Patterns |
|------|-------------------|
| creates_files | `.exists()`, `ensure_json_exists` |
| auto_creates_dir | `mkdir`, `makedirs` |
| no_overwrite | `overwrite`, `no_clobber`, `already_exists` |
| returns_dict | `isinstance(result, dict)`, `json_type` |

### 10. Infrastructure Mocking (3 items)
| Item | Detection Patterns |
|------|-------------------|
| autouse_fixtures | `autouse=True`, `autouse` |
| sys_modules_mock | `sys.modules` |
| reimport_after_mock | `importlib.reload`, `reload(` |

---

## Scoring

Score = (items_covered / 48) x 100

- **Overall pass threshold:** 75% (36+ of 48 items)
- **No test files:** 0%
- **All 48 items covered:** 100%

---

## Reference Templates

| Template | Categories Covered |
|----------|-------------------|
| `seedgo/templates/test_json_handler_template.py` | JSON Handler |
| `seedgo/templates/test_cli_routing_template.py` | CLI Routing, Success/Failure Paths |
| `seedgo/templates/test_conftest_template.py` | Conftest Fixtures, Infrastructure Mocking |
| `seedgo/templates/test_error_resilience_template.py` | Error Resilience |
| `seedgo/templates/test_contracts_template.py` | Return Type, Exception, Data Structure Contracts |
| `seedgo/templates/test_init_provisioning_template.py` | Init/Provisioning |

---

## Bypass

Bypass rules are configured in `.seedgo/bypass.json`. Supports:

- **Standard-level bypass:** Skip the entire `test_quality` standard for a branch
- **File-level bypass:** Match by file path substring

---

## Reference

- **Checker:** `test_quality_check.py`
- **Scope:** `branch_level`
- **Entry point:** `check_branch(branch_path, bypass_rules)`
- **Standard label:** `TEST_QUALITY`
