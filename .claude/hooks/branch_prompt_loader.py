#!/usr/bin/env python3
"""
Branch Prompt Loader — AIPass Public Repo

Injects branch-specific prompts based on CWD. When working in a branch
directory, loads .aipass/aipass_local_prompt.md and outputs it so the
AI sees branch-specific context.

Version: 1.0.0
"""
from pathlib import Path


def find_branch_root() -> Path | None:
    """
    Find the branch root directory.
    Looks for .trinity/ or .aipass/ as branch indicators.
    Stops at the repo root (has pyproject.toml or .git).
    """
    cwd = Path.cwd()
    search_path = cwd

    while search_path.parent != search_path:
        # Branch indicators: has .trinity/ (memory files) or apps/ (code)
        has_trinity = (search_path / ".trinity").is_dir()
        has_apps = (search_path / "apps").is_dir()

        if has_trinity or has_apps:
            return search_path

        # Stop at repo root
        if (search_path / "pyproject.toml").exists() or (search_path / ".git").is_dir():
            return None

        search_path = search_path.parent

    return None


def main():
    branch_root = find_branch_root()

    if branch_root:
        prompt_file = branch_root / ".aipass" / "aipass_local_prompt.md"
        if prompt_file.exists():
            content = prompt_file.read_text().strip()
            branch_name = branch_root.name.upper()
            print(f"\n# Branch Context: {branch_name}\n<!-- Source: {prompt_file} -->\n{content}")


if __name__ == "__main__":
    main()
