"""
Template Scanner - Automatically scan template to discover structure

Scans Spawn template directory and generates baseline structure.
Respects .registry_ignore.json patterns.
"""

# =================== AIPass ====================
# Name: template_scanner.py
# Description: Template Scanner - Automatically scan template to discover structure
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================


import sys
import json
from pathlib import Path
from typing import Dict, List, Set
from rich.console import Console

PACK_ROOT = Path(__file__).resolve().parent.parent.parent  # standards/ -> handlers/ -> aipass/
console = Console()

def load_ignore_patterns(template_path: Path) -> Dict:
    """Load ignore patterns from .registry_ignore.json"""
    ignore_file = template_path / ".registry_ignore.json"

    if not ignore_file.exists():
        return {"ignore_files": [], "ignore_patterns": []}

    with open(ignore_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        return {
            "ignore_files": data.get("ignore_files", []),
            "ignore_patterns": data.get("ignore_patterns", [])
        }


def should_ignore(path: Path, template_path: Path, ignore_config: Dict) -> bool:
    """Check if path should be ignored based on ignore patterns"""
    relative_path = path.relative_to(template_path)
    path_str = str(relative_path)
    name = path.name

    # Check exact filename matches
    if name in ignore_config["ignore_files"]:
        return True

    # Check patterns
    for pattern in ignore_config["ignore_patterns"]:
        # Simple pattern matching
        if pattern.startswith('*'):
            # *.pyc -> check extension
            suffix = pattern[1:]
            if name.endswith(suffix):
                return True
        elif '*' in pattern:
            # More complex patterns - skip for now
            continue
        else:
            # Exact match or directory name
            if name == pattern:
                return True
            # Check if any parent directory matches
            if pattern in path.parts:
                return True

    return False


def scan_template(template_path: Path) -> Dict:
    """Scan template directory and return structure"""
    ignore_config = load_ignore_patterns(template_path)

    structure = {
        "directories": [],
        "files": [],
        "root_files": []
    }

    for item in template_path.rglob('*'):
        # Skip ignored items
        if should_ignore(item, template_path, ignore_config):
            continue

        relative = item.relative_to(template_path)

        if item.is_dir():
            structure["directories"].append(str(relative))
        elif item.is_file():
            if item.parent == template_path:
                # Root level file
                structure["root_files"].append(item.name)
            else:
                # Nested file
                structure["files"].append(str(relative))

    return structure


def compare_to_branch(template_structure: Dict, branch_path: Path, branch_name: str) -> Dict:
    """Compare template structure to actual branch"""

    missing = {
        "directories": [],
        "files": [],
        "root_files": []
    }

    # Substitute {{BRANCH}} and {{branch}} in template items
    for template_dir in template_structure["directories"]:
        actual_dir = template_dir.replace("{{BRANCH}}", branch_name.upper())
        actual_dir = actual_dir.replace("{{branch}}", branch_name.lower())

        dir_path = branch_path / actual_dir
        if not dir_path.exists():
            missing["directories"].append(actual_dir)

    for template_file in template_structure["files"]:
        actual_file = template_file.replace("{{BRANCH}}", branch_name.upper())
        actual_file = actual_file.replace("{{branch}}", branch_name.lower())

        file_path = branch_path / actual_file
        if not file_path.exists():
            missing["files"].append(actual_file)

    for template_file in template_structure["root_files"]:
        actual_file = template_file.replace("{{BRANCH}}", branch_name.upper())
        actual_file = actual_file.replace("{{branch}}", branch_name.lower())

        file_path = branch_path / actual_file
        if not file_path.exists():
            missing["root_files"].append(actual_file)

    return missing


if __name__ == "__main__":
    import sys

    # Test on pack root
    template_path = PACK_ROOT

    console.print("Scanning template...")
    structure = scan_template(template_path)

    console.print("Template structure:")
    console.print(f"  Directories: {len(structure['directories'])}")
    console.print(f"  Files: {len(structure['files'])}")
    console.print(f"  Root files: {len(structure['root_files'])}")

    console.print("\nRoot files found in template:")
    for f in sorted(structure['root_files']):
        console.print(f"  - {f}")

    # Compare to branch
    if len(sys.argv) > 1:
        branch_path = Path(sys.argv[1])
        branch_name = branch_path.name

        console.print(f"\n\nComparing to branch: {branch_name}")
        missing = compare_to_branch(structure, branch_path, branch_name)

        if missing["root_files"]:
            console.print(f"\nMissing root files ({len(missing['root_files'])}):")
            for f in sorted(missing['root_files']):
                console.print(f"  ✗ {f}")

        if missing["directories"]:
            console.print(f"\nMissing directories ({len(missing['directories'])}):")
            for d in sorted(missing['directories'])[:10]:
                console.print(f"  ✗ {d}")

        if missing["files"]:
            console.print(f"\nMissing files ({len(missing['files'])}):")
            for f in sorted(missing['files'])[:10]:
                console.print(f"  ✗ {f}")
