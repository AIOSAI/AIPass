"""
Type Error Diagnostics Checker

Uses pyright to detect type errors, undefined variables, and other
static analysis issues that would show as Pylance errors in VS Code.
"""

# =================== AIPass ====================
# Name: diagnostics_check.py
# Description: Type Error Diagnostics Checker
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================


import sys
import subprocess
import json
from pathlib import Path
from typing import Dict, List

from rich.console import Console

console = Console()

# Import ignore patterns from config handler (same branch)
from aipass.seedgo.apps.standards.aipass.handlers.config.ignore_handler import get_audit_ignore_patterns


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
            # Pyright may output text on error
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
        return {
            'file': str(file_path),
            'errors': 0,
            'warnings': 0,
            'diagnostics': [],
            'error': 'Pyright timed out'
        }
    except Exception as e:
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
            return {
                'total_files': 0,
                'files_with_errors': 0,
                'total_errors': 0,
                'total_warnings': 0,
                'results': [],
                'error': f'Failed to parse pyright output'
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
        return {
            'total_files': 0,
            'files_with_errors': 0,
            'total_errors': 0,
            'total_warnings': 0,
            'results': [],
            'error': 'Pyright timed out (directory too large?)'
        }
    except Exception as e:
        return {
            'total_files': 0,
            'files_with_errors': 0,
            'total_errors': 0,
            'total_warnings': 0,
            'results': [],
            'error': str(e)
        }


def check_branch(branch_path: str) -> Dict:
    """
    Run diagnostics on a branch's apps/ directory

    Args:
        branch_path: Path to branch root (e.g., src/aipass/seedgo)

    Returns:
        Same format as check_directory
    """
    apps_path = Path(branch_path) / "apps"

    if not apps_path.exists():
        return {
            'total_files': 0,
            'files_with_errors': 0,
            'total_errors': 0,
            'total_warnings': 0,
            'results': [],
            'error': f'No apps/ directory found in {branch_path}'
        }

    return check_directory(str(apps_path))


def format_summary(results: Dict) -> str:
    """Format results as a summary string"""
    if 'error' in results and results['error']:
        return f"Error: {results['error']}"

    lines = []
    lines.append(f"Files analyzed: {results['total_files']}")
    lines.append(f"Files with errors: {results['files_with_errors']}")
    lines.append(f"Total errors: {results['total_errors']}")
    lines.append(f"Total warnings: {results['total_warnings']}")

    return '\n'.join(lines)


if __name__ == '__main__':
    # CLI usage: python diagnostics_check.py [file_or_directory]
    if len(sys.argv) < 2:
        console.print("[yellow]Usage:[/yellow] python diagnostics_check.py <file_or_directory>")
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
                console.print(f"[red]✗[/red] {file_result['file']} [dim]({file_result['errors']} errors)[/dim]")
                for diag in file_result['diagnostics'][:5]:  # Top 5 per file
                    console.print(f"  [dim]Line {diag['line']}:[/dim] {diag['message']}")
