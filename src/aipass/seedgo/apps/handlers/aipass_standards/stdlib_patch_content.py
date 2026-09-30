# =================== AIPass ====================
# Name: stdlib_patch_content.py
# Description: Stdlib Patch Standards Content Handler
# Version: 1.1.0
# Created: 2026-09-22
# Modified: 2026-09-23
# =============================================

"""
Stdlib Patch Standards Content Handler

Provides formatted Stdlib Patch standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_stdlib_patch_standards() -> str:
    """Return formatted stdlib_patch standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (crack class Q, review of @backup 2026-09-22):[/bold cyan]",
        "  A patch whose target is a STDLIB function the product calls to do its own",
        "  work. Replacing it is process-wide, and the oracle becomes",
        "  spelling-specific — the test passes only while the product keeps reaching",
        "  that exact name.",
        "",
        "[bold cyan]THE EVIDENCE LINE, test_ceiling_guard.py:103:[/bold cyan]",
        "  [red]with patch.object(ceiling.os.path, 'getsize', side_effect=AssertionError):[/red]",
        "",
        "  ceiling.os IS the real os. That line replaces posixpath.getsize for every",
        "  module in the process. Rewrite check_ceiling to use Path.stat() — the same",
        "  measurement, a different spelling — and the guard [red]silently stops being",
        "  tested[/red].",
        "",
        "[bold cyan]THE JUDGEMENT: which non-aipass targets are sanctioned, and why.[/bold cyan]",
        "  The line is not 'stdlib versus product'. It is:",
        "",
        "  [green]SANCTIONED[/green] — an EDGE the test must seal. A process, the network, the",
        "  environment, the interpreter's own I/O and module table. Sealing an edge is",
        "  what a test is supposed to do, and no product-local seam would be better:",
        "    subprocess · socket · urllib · http · smtplib · ssl · ftplib · asyncio",
        "    sys.argv · sys.stdout · sys.stderr · sys.stdin · sys.path · sys.modules",
        "    os.environ",
        "  [green]819 hits acquitted, 662 of them subprocess.[/green] Running a real subprocess in a",
        "  unit test is the defect; patching it is the cure.",
        "",
        "  [red]SCORED[/red] — the product's OWN work, done through the stdlib. The filesystem,",
        "  the clock, serialisation, imports, open. The product could have been given",
        "  a seam and was not, so the test reaches around it into a shared namespace:",
        "    importlib 218 · sys (not the six above) 211 · os 126 · builtins 97 ·",
        "    pathlib 94 · shutil 93 · time 54 · tempfile 9 · inspect 5 · signal 3",
        "",
        "[bold cyan]FOUR CUTS, 6,926 → 916:[/bold cyan]",
        "    raw dotted root                              363 files, 6,926 hits",
        "    the root resolved through the file's imports  208 files, 1,993 hits",
        "    aipass name-collisions checked ON DISK        175 files, 1,584 hits",
        "    edges sanctioned                             155 files,   916 hits",
        "",
        "  [red]aipass/ai_mail/apps/handlers/contacts/email.py[/red] is a product module whose",
        "  name collides with stdlib email, and [red]291 hits were that one collision[/red]. A",
        "  segment is only stdlib when the aipass path up to it does NOT exist as a",
        "  file on disk. Guessing from the name alone convicts a third of @ai_mail.",
        "",
        "[bold cyan]THE FIFTH CUT — A STDLIB CLASS THROUGH A PRODUCT BINDING:[/bold cyan]",
        "  patch('pathlib.Path.resolve') scored while monkeypatch.setattr(upload.Path,",
        "  'resolve') acquitted — the same process-wide replacement, two spellings, so",
        "  [red]a branch could turn the row green one character at a time[/red]. The target is now",
        "  judged by what it IS: a name that is not a module is looked up in the PRODUCT",
        "  MODULE'S OWN imports, so upload.Path is pathlib.Path, while a class the module",
        "  defines (agent.TranscriptScanner) has no import and stays acquitted. A relative",
        "  import keeps its leading dots — from ..json import json_handler is a sibling",
        "  package, never stdlib json. [yellow]152 files / 905 hits → 159 / 1,002: 97 acquittals",
        "  were this shape, every one of them pathlib.Path.[/yellow]",
        "",
        "[bold cyan]WHAT IT REFUSES TO JUDGE:[/bold cyan]",
        "  Targets bound to a local name by assignment — mod = importlib.import_module",
        "  (...) then patch.object(mod.os, ...). The AST cannot say what mod is, so the",
        "  rule says nothing and counts them in the passing message. [yellow]That set is larger",
        "  than everything it convicts.[/yellow]",
        "",
        "[bold cyan]WHY IT CANNOT BE SATISFIED BY ACCIDENT:[/bold cyan]",
        "  A patched stdlib name is replaced for the whole process, so the test pins",
        "  the product's SPELLING rather than its behaviour. Change the spelling",
        "  without changing the behaviour and the test stops testing anything.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per file. Every hit names the line, the target and the stdlib module",
        "  it lands in, on ONE check.",
        "",
        "[bold cyan]THE CURE:[/bold cyan]",
        "  [green]give the product a seam and patch that, or assert the effect on disk.[/green]",
    ]

    json_handler.log_operation("content_served", {"standard": "stdlib_patch"})
    return "\n".join(lines)
