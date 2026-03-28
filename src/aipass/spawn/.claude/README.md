#!/usr/bin/env python3
"""Verify spawn branch integrity.

Simple verification script that checks spawn branch structure and reports status.
"""

from pathlib import Path


def verify():
    """Run basic spawn branch verification checks."""
    branch_dir = Path(__file__).parents[1]
    checks = {
        "apps/branch.py": (branch_dir / "apps" / "branch.py").exists(),
        "apps/modules/": (branch_dir / "apps" / "modules").is_dir(),
        "apps/handlers/": (branch_dir / "apps" / "handlers").is_dir(),
        ".trinity/passport.json": (branch_dir / ".trinity" / "passport.json").exists(),
        "tests/": (branch_dir / "tests").is_dir(),
    }

    all_ok = all(checks.values())
    for name, ok in checks.items():
        status = "OK" if ok else "MISSING"
        print(f"  [{status}] {name}")

    print()
    print(f"spawn branch verification: {'PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(verify())
