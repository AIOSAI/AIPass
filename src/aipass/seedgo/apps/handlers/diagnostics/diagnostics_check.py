# =================== AIPass ====================
# Name: diagnostics_check.py
# Description: Diagnostics Orchestrator
# Version: 2.0.0
# Created: 2026-03-05
# Modified: 2026-03-10
# =============================================

"""
Diagnostics Orchestrator

Shared diagnostics orchestrator that discovers runner configurations from
standards packs (handlers/*_standards/diagnostics.json) and dispatches to
the appropriate runner handlers in handlers/diagnostics/.

Falls back to python/pyright if no runner config is found (backwards compatible).
"""

import sys
import subprocess
import json
import importlib
from pathlib import Path
from typing import Dict, List, Optional

from rich.console import Console

console = Console()

# Import ignore patterns from bypass handler
from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.ignore_handler import get_audit_ignore_patterns
from aipass.seedgo.apps.handlers.json import json_handler

AUDIT_SCOPE = "branch_level"

# Diagnostics handler directory (where this file lives)
DIAGNOSTICS_DIR = Path(__file__).resolve().parent

# Handlers root (parent of diagnostics/)
HANDLERS_DIR = DIAGNOSTICS_DIR.parent


# =============================================
# FILE / DIRECTORY HELPERS (used by runners)
# =============================================

def should_ignore_file(file_path: str, ignore_patterns: List[str]) -> bool:
    """Check if file should be ignored based on audit patterns"""
    for pattern in ignore_patterns:
        if pattern in file_path:
            return True
    return False


def check_file(file_path: str) -> Dict:
    """
    Run pyright on a single file and return diagnostics

    Args:
        file_path: Path to Python file to check

    Returns:
        dict: {
            'file': str,
            'errors': int,
            'warnings': int,
            'diagnostics': [{'line': int, 'severity': str, 'message': str}]
        }
    """
    path = Path(file_path)

    if not path.exists():
        return {
            'file': str(file_path),
            'errors': 0,
            'warnings': 0,
            'diagnostics': [],
            'error': f'File not found: {file_path}'
        }

    if not path.suffix == '.py':
        return {
            'file': str(file_path),
            'errors': 0,
            'warnings': 0,
            'diagnostics': [],
            'skipped': 'Not a Python file'
        }

    try:
        # Run pyright with JSON output
        result = subprocess.run(
            ['python3', '-m', 'pyright', '--outputjson', str(path)],
            capture_output=True,
            text=True,
            timeout=30
        )

        # Parse JSON output
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError:
            logger.info("Failed to parse pyright JSON output for %s", file_path)
            return {
                'file': str(file_path),
                'errors': 0,
                'warnings': 0,
                'diagnostics': [],
                'error': f'Failed to parse pyright output: {result.stderr or result.stdout}'
            }

        diagnostics = []
        errors = 0
        warnings = 0

        for diag in output.get('generalDiagnostics', []):
            severity = diag.get('severity', 'error')
            if severity == 'error':
                errors += 1
            elif severity == 'warning':
                warnings += 1

            diagnostics.append({
                'line': diag.get('range', {}).get('start', {}).get('line', 0) + 1,
                'severity': severity,
                'message': diag.get('message', 'Unknown error'),
                'rule': diag.get('rule', '')
            })

        return {
            'file': str(file_path),
            'errors': errors,
            'warnings': warnings,
            'diagnostics': diagnostics
        }

    except subprocess.TimeoutExpired:
        logger.info("Pyright timed out for %s", file_path)
        return {
            'file': str(file_path),
            'errors': 0,
            'warnings': 0,
            'diagnostics': [],
            'error': 'Pyright timed out'
        }
    except Exception as e:
        logger.info("Pyright check failed for %s: %s", file_path, e)
        return {
            'file': str(file_path),
            'errors': 0,
            'warnings': 0,
            'diagnostics': [],
            'error': str(e)
        }


def check_directory(directory: str, pattern: str = "**/*.py") -> Dict:
    """
    Run pyright on all Python files in a directory

    Args:
        directory: Directory to scan
        pattern: Glob pattern for files (default: all .py files)

    Returns:
        dict: {
            'total_files': int,
            'files_with_errors': int,
            'total_errors': int,
            'total_warnings': int,
            'results': [file_result, ...]
        }
    """
    path = Path(directory)

    if not path.exists():
        return {
            'total_files': 0,
            'files_with_errors': 0,
            'total_errors': 0,
            'total_warnings': 0,
            'results': [],
            'error': f'Directory not found: {directory}'
        }

    # Run pyright on entire directory for efficiency
    try:
        result = subprocess.run(
            ['python3', '-m', 'pyright', '--outputjson', str(path)],
            capture_output=True,
            text=True,
            timeout=300  # 5 minutes for full directory
        )

        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError:
            logger.info("Failed to parse pyright JSON output for directory %s", directory)
            return {
                'total_files': 0,
                'files_with_errors': 0,
                'total_errors': 0,
                'total_warnings': 0,
                'results': [],
                'error': 'Failed to parse pyright output'
            }

        # Get ignore patterns
        ignore_patterns = get_audit_ignore_patterns()

        # Group diagnostics by file (filtering ignored files)
        file_diagnostics = {}

        for diag in output.get('generalDiagnostics', []):
            file_path = diag.get('file', 'unknown')

            # Skip files matching ignore patterns
            if should_ignore_file(file_path, ignore_patterns):
                continue
            if file_path not in file_diagnostics:
                file_diagnostics[file_path] = {
                    'file': file_path,
                    'errors': 0,
                    'warnings': 0,
                    'diagnostics': []
                }

            severity = diag.get('severity', 'error')
            if severity == 'error':
                file_diagnostics[file_path]['errors'] += 1
            elif severity == 'warning':
                file_diagnostics[file_path]['warnings'] += 1

            file_diagnostics[file_path]['diagnostics'].append({
                'line': diag.get('range', {}).get('start', {}).get('line', 0) + 1,
                'severity': severity,
                'message': diag.get('message', 'Unknown error'),
                'rule': diag.get('rule', '')
            })

        results = list(file_diagnostics.values())
        total_errors = sum(r['errors'] for r in results)
        total_warnings = sum(r['warnings'] for r in results)
        files_with_errors = len([r for r in results if r['errors'] > 0])

        return {
            'total_files': output.get('summary', {}).get('filesAnalyzed', 0),
            'files_with_errors': files_with_errors,
            'total_errors': total_errors,
            'total_warnings': total_warnings,
            'results': sorted(results, key=lambda x: x['errors'], reverse=True)
        }

    except subprocess.TimeoutExpired:
        logger.info("Pyright timed out for directory %s", directory)
        return {
            'total_files': 0,
            'files_with_errors': 0,
            'total_errors': 0,
            'total_warnings': 0,
            'results': [],
            'error': 'Pyright timed out (directory too large?)'
        }
    except Exception as e:
        logger.info("Pyright directory check failed for %s: %s", directory, e)
        return {
            'total_files': 0,
            'files_with_errors': 0,
            'total_errors': 0,
            'total_warnings': 0,
            'results': [],
            'error': str(e)
        }


# =============================================
# RUNNER DISCOVERY & DISPATCH
# =============================================

def _discover_pack_configs() -> List[Dict]:
    """
    Find diagnostics.json files in handlers/*_standards/ directories.

    Scans HANDLERS_DIR for subdirectories matching *_standards/ pattern
    and loads any diagnostics.json found within.

    Returns:
        List of dicts: [{'pack_name': str, 'pack_path': Path, 'config': dict}]
    """
    configs = []

    if not HANDLERS_DIR.exists():
        return configs

    for subdir in sorted(HANDLERS_DIR.iterdir()):
        if not subdir.is_dir():
            continue
        if not subdir.name.endswith('_standards'):
            continue

        config_file = subdir / 'diagnostics.json'
        if not config_file.exists():
            continue

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            configs.append({
                'pack_name': subdir.name,
                'pack_path': subdir,
                'config': config
            })
        except (json.JSONDecodeError, IOError):
            logger.info("Skipped malformed diagnostics config: %s", config_file)
            continue

    return configs


def _get_enabled_runners_from_config(config: Dict) -> List[str]:
    """
    Extract enabled runner names from a diagnostics.json config.

    Handles both simple format ({"python": true}) and detailed format
    ({"python": {"enabled": true, ...}}).

    Args:
        config: Parsed diagnostics.json content

    Returns:
        List of enabled runner names (e.g. ["python"])
    """
    enabled = []
    runners = config.get('runners', {})

    for name, value in runners.items():
        if isinstance(value, bool) and value:
            enabled.append(name)
        elif isinstance(value, dict) and value.get('enabled', False):
            enabled.append(name)

    return enabled


def _run_runner(runner_name: str, branch_path: str, bypass_rules: Optional[list] = None) -> Optional[Dict]:
    """
    Dispatch to a runner handler in handlers/diagnostics/.

    Looks for a module named {runner_name}_diagnostics.py (or
    {runner_name}_diognostics.py for backwards compat) with a
    check_branch(branch_path, bypass_rules) function.

    Args:
        runner_name: Runner identifier (e.g. "python", "typescript")
        branch_path: Path to branch root
        bypass_rules: Optional bypass rules for audit compatibility

    Returns:
        Runner result dict, or None if runner not found/empty
    """
    # Try canonical name first, then known typo variant for backwards compat
    candidate_names = [
        f"{runner_name}_diagnostics",
        f"{runner_name}_diognostics",
    ]

    for module_file_stem in candidate_names:
        runner_path = DIAGNOSTICS_DIR / f"{module_file_stem}.py"
        if not runner_path.exists():
            continue

        # Skip empty files
        if runner_path.stat().st_size == 0:
            continue

        # Check if file has actual content (not just whitespace/comments)
        try:
            content = runner_path.read_text(encoding='utf-8').strip()
            if not content:
                continue
        except IOError:
            logger.info("Cannot read runner file: %s", runner_path)
            continue

        # Dynamically import the runner module
        module_name = f"aipass.seedgo.apps.handlers.diagnostics.{module_file_stem}"
        try:
            runner_module = importlib.import_module(module_name)
        except (ImportError, Exception):
            logger.info("Failed to import runner module: %s", module_name)
            continue

        # Call check_branch if it exists
        check_fn = getattr(runner_module, 'check_branch', None)
        if check_fn is None:
            continue

        try:
            return check_fn(branch_path, bypass_rules=bypass_rules)
        except Exception:
            logger.info("Runner %s failed for branch %s", runner_name, branch_path)
            continue

    return None


# =============================================
# BRANCH-LEVEL CHECK (audit pipeline entry)
# =============================================

def check_branch(branch_path: str, bypass_rules: Optional[list] = None) -> Dict:
    """
    Run diagnostics on a branch by discovering pack configs and dispatching runners.

    Flow:
        1. Scan handlers/*_standards/ for diagnostics.json files
        2. For each enabled runner, call the corresponding handler in handlers/diagnostics/
        3. If no runner configs found, fall back to python/pyright (backwards compatible)
        4. Merge results into audit-pipeline-compatible format

    Args:
        branch_path: Path to branch root (e.g., src/aipass/seedgo)
        bypass_rules: Optional bypass rules (audit pipeline compatibility)

    Returns:
        dict: {passed, score, checks, standard: 'DIAGNOSTICS', ...}
    """
    apps_path = Path(branch_path) / "apps"

    if not apps_path.exists():
        return {
            'passed': True,
            'score': 100,
            'total_files': 0,
            'total_errors': 0,
            'checks': [],
            'standard': 'DIAGNOSTICS',
            'error': f'No apps/ directory found in {branch_path}'
        }

    # Step 1: Discover pack configs
    pack_configs = _discover_pack_configs()

    # Step 2: Collect enabled runners across all packs
    all_runners = []
    for pack_info in pack_configs:
        runners = _get_enabled_runners_from_config(pack_info['config'])
        for runner in runners:
            if runner not in all_runners:
                all_runners.append(runner)

    # Step 3: Fall back to python if no runner config found
    if not all_runners:
        all_runners = ["python"]

    # Step 4: Dispatch to each runner and merge results
    merged_checks = []
    total_errors = 0
    total_warnings = 0
    total_files = 0
    all_results = []
    runner_executed = False

    for runner_name in all_runners:
        runner_result = _run_runner(runner_name, branch_path, bypass_rules)

        if runner_result is not None:
            runner_executed = True
            total_errors += runner_result.get('total_errors', 0)
            total_warnings += runner_result.get('total_warnings', 0)
            total_files += runner_result.get('total_files', 0)
            merged_checks.extend(runner_result.get('checks', []))
            all_results.extend(runner_result.get('results', []))
        # If runner doesn't exist or is empty, skip gracefully

    # Step 5: If no runner executed, fall back to direct pyright check
    if not runner_executed:
        result = check_directory(str(apps_path))

        total_errors = result.get('total_errors', 0)
        total_warnings = result.get('total_warnings', 0)
        total_files = result.get('total_files', 0)
        all_results = result.get('results', [])

        # Build checks from file results
        for file_result in all_results:
            if file_result['errors'] > 0:
                merged_checks.append({
                    'name': f"Type errors in {Path(file_result['file']).name}",
                    'passed': False,
                    'message': f"{file_result['errors']} errors"
                })

    # Default passing check if nothing failed
    if not merged_checks:
        merged_checks.append({
            'name': 'Type check',
            'passed': True,
            'message': f"No type errors ({total_files} files analyzed)"
        })

    # Calculate score
    score = 100 if total_errors == 0 else max(0, 100 - (total_errors * 5))

    json_handler.log_operation("diagnostics_run", {"branch": branch_path, "total_errors": total_errors, "runners": len(all_runners)})
    return {
        'passed': total_errors == 0,
        'score': score,
        'total_files': total_files,
        'total_errors': total_errors,
        'total_warnings': total_warnings,
        'files_with_errors': len([r for r in all_results if r.get('errors', 0) > 0]),
        'checks': merged_checks,
        'results': all_results,
        'standard': 'DIAGNOSTICS'
    }


def format_summary(results: Dict) -> str:
    """Format results as a summary string.

    Note: Used by tests/test_diagnostics.py — not called in production audit pipeline.
    """
    if 'error' in results and results['error']:
        return f"Error: {results['error']}"

    lines = []
    lines.append(f"Files analyzed: {results['total_files']}")
    lines.append(f"Files with errors: {results['files_with_errors']}")
    lines.append(f"Total errors: {results['total_errors']}")
    lines.append(f"Total warnings: {results['total_warnings']}")

    return '\n'.join(lines)


if __name__ == '__main__':
    # CLI usage: drone @seedgo diagnostics [file_or_directory]
    if len(sys.argv) < 2:
        console.print("[yellow]Usage:[/yellow] drone @seedgo diagnostics <file_or_directory>")
        sys.exit(1)

    target = sys.argv[1]

    if Path(target).is_file():
        result = check_file(target)
        console.print_json(json.dumps(result, indent=2))
    else:
        result = check_directory(target)

        # Summary header
        console.print()
        console.print("[bold cyan]TYPE ERROR DIAGNOSTICS[/bold cyan]")
        console.print(f"  Files analyzed:     {result['total_files']}")
        console.print(f"  Files with errors:  {result['files_with_errors']}")

        if result['total_errors'] > 0:
            console.print(f"  [red]Total errors:       {result['total_errors']}[/red]")
        else:
            console.print(f"  [green]Total errors:       0[/green]")

        if result['total_warnings'] > 0:
            console.print(f"  [yellow]Total warnings:     {result['total_warnings']}[/yellow]")

        # File details
        for file_result in result.get('results', [])[:20]:  # Top 20
            if file_result['errors'] > 0:
                console.print()
                console.print(f"[red]\u2717[/red] {file_result['file']} [dim]({file_result['errors']} errors)[/dim]")
                for diag in file_result['diagnostics'][:5]:  # Top 5 per file
                    console.print(f"  [dim]Line {diag['line']}:[/dim] {diag['message']}")
