# =================== AIPass ====================
# Name: bash_writes.py
# Version: 2.5.0
# Description: Write targets a shell command can be seen to name (edit_gate's scripted lane)
# Branch: hooks
# Layer: apps/modules
# Created: 2026-08-30
# Modified: 2026-10-25
# =============================================

"""Reads a Bash command and reports which paths it can be seen to WRITE.

Edit/Write hooks never see a shell write. The bar is the obvious write verbs; every gap is in :data:`NOT_CAUGHT`.
Directed verbs (redirection, tee, sed -i, cp, mv, dd of=) report their target; interpreters, every path held.
"""

import os
import re
import shlex
from pathlib import Path, PureWindowsPath

from aipass.cli.apps.modules import err_console
from aipass.hooks.apps.modules.shell_programs import named_operands, sed_actions, sed_scripts
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console

_SEPARATORS = frozenset({"&&", "||", ";", "|", "&", "\n"})

# The newline is an operator on purpose: shlex counts it as blank, gluing every later line onto line one.
_PUNCTUATION = "();<>|&\n"

# A subshell's cd ends with the subshell; the parentheses scope it.
_SUBSHELL_OPEN, _SUBSHELL_CLOSE = "(", ")"

# The lexer glues an operator run into one token (");", "&&\n"); these split it. Redirections stay whole.
_OPERATOR_SPLIT = re.compile(r"(\n|&&|\|\||;|\(|\))")

_ALL_OPERANDS = frozenset({"tee", "touch", "mkdir", "truncate"})

_LAST_OPERAND = frozenset({"cp", "mv", "ln", "install", "rsync"})

# Only with the in-place flag: without it sed is a filter, and reading a foreign file is legal.
_INPLACE_FLAGS = frozenset({"-i", "--in-place"})

_INTERPRETERS = frozenset(
    {"python", "python3", "node", "nodejs", "perl", "ruby", "php", "bash", "sh", "zsh", "awk", "gawk"}
)
_SHELLS = frozenset({"bash", "sh", "zsh"})

# Windows runs git.exe, RM.EXE, git.cmd as the bare name; only executable extensions strip (git.py is not git).
_EXEC_EXTENSIONS = frozenset({".exe", ".com", ".bat", ".cmd", ".ps1"})

# Apart from _SHELL_WRITE_SHAPES (`>` compares in python); only the narrow "is a file created" caller reads them.
_SOURCE_WRITE_SHAPES = (
    re.compile(r"""open\s*\([^)]*['"][rbt+]*[wax][rbt+]*['"]"""),
    re.compile(r"\.\s*(write|write_text|write_bytes|writelines|truncate|touch|mkdir|rename|replace|unlink)\s*\("),
    re.compile(
        r"\b(makedirs|mkstemp|mkdtemp|copyfile|copytree|copy2|copy|move|rename|replace|remove|dump|savefig|to_csv|to_json)\s*\("
    ),
    re.compile(
        r"\b(writeFile|writeFileSync|appendFile|appendFileSync|createWriteStream|mkdirSync|renameSync"
        r"|copyFileSync|file_put_contents|fwrite|fputs|fopen)\s*\("
    ),
    # Shelling out: the verb sits in a string, so the call is the evidence. A word before a call bracket is
    # a call; one in a quoted module name handed to a loader is a module (with createRequire, every whole
    # word counts); one joined by / - or \ to a path character is a path (xdist's popen-gw0). Disguise
    # (`a-system`, `const r=require`) passes, '/spawn' and 'system.md' are refused; edit_gate stays broad.
    re.compile(
        r"\b(system|popen|spawn|exec|execSync|check_call|check_output|subprocess"
        r"|execl|execle|execlp|execlpe|execv|execve|execvp|execvpe"
        r"|spawnl|spawnle|spawnlp|spawnlpe|spawnv|spawnve|spawnvp|spawnvpe"
        r"|posix_spawn|posix_spawnp|startfile|create_subprocess_exec|create_subprocess_shell|Popen|popen2|popen3"
        r"|execFile|execFileSync|spawnSync|shell_exec|passthru|proc_open|capture2|capture3)\b(?=[\s\\]*\()"
        r"""|(?:require(?:\s*\.\s*resolve)?|import)\s*\(\s*(?:'[^']*|"[^"]*|`[^`]*)\b"""
        r"(system|popen|spawn|exec|execSync|check_call|check_output|subprocess)\b"
        r"""|\b(?:from|import)\s*['"][^'"]*\b(system|popen|spawn|exec|execSync|check_call|check_output|subprocess)\b"""
        r"|\bcreateRequire\b[\s\S]*?\b(system|popen|spawn|exec|execSync|check_call|check_output|subprocess)\b"
        r"|\b(system|popen|spawn|exec|execSync|check_call|check_output|subprocess)\b"
        r"(?=[\s\S]*?\bcreateRequire\b)"
        r"|(?<![\w.][/\\-])(?<![\w.]\\\\)(?<!\w)"
        r"(system|popen|spawn|exec|execSync|check_call|check_output|subprocess)\b(?!(?:[/-]|\\{1,2})[\w.])"
    ),
)

# Flags that put the program inside the command. Without one it is a file nobody read and the broad
# reading stands (test_a_real_creation_is_still_refused); awk's bare-operand program stays on that side.
_INLINE_SOURCE_FLAGS = frozenset({"-c", "-e", "-E", "--eval", "--exec"})

_SHELL_WRITE_SHAPES = (
    re.compile(r">"),
    re.compile(r"(^|[\s;&|])(tee|touch|cp|mv|ln|install|rsync|dd|mkdir|truncate|sed)\b"),
)

#: rm_gate's interpreter lane. remove counts only on the os module; shell programs are shell_reader's.
_SOURCE_DELETE_SHAPES = (
    re.compile(r"\bos\s*\.\s*(remove|unlink|rmdir|removedirs)\b"),
    re.compile(r"\b(rmtree|removedirs)\b"),
    re.compile(r"\.\s*(unlink|rmdir)\s*\("),
    re.compile(r"\b(unlink|rmdir)\b"),
    re.compile(r"\.\s*(rm|rmSync|unlinkSync|rmdirSync)\s*\("),
    re.compile(r"\b(File\s*\.\s*delete|FileUtils\s*\.\s*(rm|rm_r|rm_rf|rm_f|remove_dir|remove_entry))\b"),
    # A delete verb counts only after a shell-out call; without the call it is data: print('rm x').
    re.compile(
        r"""\b(system|popen|Popen|subprocess|spawn\w*|exec\w*|check_call|check_output|call|run|shell_exec)\b"""
        r"""[\s\S]*?['"`](rm|rmdir|unlink|shred)\b"""
    ),
)

# drone, aipass, git, gh need no skip-list: no verb read here is theirs; a redirection they carry is caught.

# Redirections that write their word; `>&` only when the word is no descriptor (`2>&1`, `>&-`).
_REDIRECT_OPS = frozenset({">", ">>", ">|", "&>", "&>>", "<>"})
_DUP_OP = ">&"

# Both separators: a run that knew only "/" was blind to Windows paths in interpreter source.
_PATH_RUN = re.compile(r"[~\w.@+\-]*[/\\][~\w./\\@+\-]*")

_HEREDOC_OPEN = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_]\w*)\1")

_TRAILING_JUNK = ",;:)]}'\"`"

# Git Bash spells C:\Users\me as /c/Users/me, and agents copy it from its pwd.
_GIT_BASH_DRIVE = re.compile(r"/([A-Za-z])(?=/|$)")

#: How an interpreter's held path is labelled. write_ownership reads it: a held path
#: cannot be told from a read, so the branch fence never convicts on one.
HELD_BY_INTERPRETER = "(interpreter — may write any path it holds)"

#: Narrow callers ("is a NEW file created") stand down on this, broad ones ignore it. Spelled once, here.
NO_WRITE_VERB = " — no write verb in its own text"

# The residual, as data so the reply, the README and the tests quote one list.
NOT_CAUGHT: tuple[str, ...] = (
    "paths built from shell or program variables ($DIR/x, os.environ-derived) — nothing to resolve",
    "paths reached through a symlink that points into another project",
    "find -exec / xargs WRITES, which name the write verb but not the operand (their DELETES and "
    "git/gh launches are read by shell_reader since DPLAN-0356 phase 3)",
    "background or detached writes (nohup, disown, at, cron, systemd-run)",
    "metadata-only changes: chmod, chown, touch -t on an existing file",
    "git, gh, drone and aipass — they name no write verb this parser reads; their own fences apply",
    "writes made by a process the command merely starts (a server, a test runner)",
    "paths an interpreter receives from ANOTHER command — through a pipe, a file or an argument "
    "list built elsewhere. Only the paths in its own command and its own heredoc are read as held.",
    "a path spelled for the OTHER operating system's filesystem — 'C:\\Proj\\x' read on Linux "
    "names no drive that exists here, so it resolves relative and reads as local. Separators are "
    "understood on every OS; ROOTS are only walkable on the OS that has them.",
    "a file name with no separator inside interpreter source — a bare 'local.json' after a cd. A "
    "bare word cannot be told from json.load, so it is not read as a path; './local.json' is",
    "a path joined in program text — Path('.trinity') / 'local.json' is two strings, neither a path",
    "write verbs this parser has no grammar for: sponge, ed / ex, an interactive editor",
    "the w and W files of a sed -f script file: shell_reader reads its e commands, not its writes",
    "a WRITE an interpreter makes through a shape _SOURCE_WRITE_SHAPES has no pattern for — the "
    "path is still reported, but without the write-verb evidence a narrow caller (testwrite_gate) "
    "stands down on it. The broad callers, edit_gate's fences, are unaffected",
    "which held path a write shape belongs to — the evidence is read per interpreter, not per "
    "path, so a program that writes one file and merely names another claims both",
    "what a SCRIPT FILE does — its text is on disk, never in the command, so an interpreter "
    "handed a path instead of inline source keeps the broad reading and no write-verb evidence "
    "is claimed about it",
    "a delete an interpreter makes through a name its delete shapes do not list — an alias "
    "(from os import remove as r), getattr(os, 'remove'), a delete built from strings",
    "a script file that changes after the check — shell_reader reads it at decision time (R4); "
    "whatever is on disk when the shell opens it is what runs. Time of check is not time of use",
    "a script a command creates and runs in one breath through a verb the reader cannot parse "
    "(tar, unzip, curl -o, a compiler's output) — the file is not on disk to read at decision time",
    "a module run by an interpreter's -m flag, or a program found on PATH — their code is "
    "installed, not handed in, and shell_reader reads only a script path the command names",
    "a launcher shell_reader has no table for (npx <pkg>, a package manager's run-script, a shell "
    "function or alias) — the wrapped program is read as the launcher's argument, not as a program",
    "the working directory of a subshell, a pipeline stage or a backgrounded job is approximated "
    "by the last literal cd; after a cd to an expansion the cwd is unknown and relative paths read from the old one",
    "an interpreter's delete reached through aliasing or data flow (a name bound at runtime, a "
    "function chosen from a table) — text gates teach; the sandbox enforces",
    "GitHub writes to hosts other than api.github.com (uploads, raw git over https) — egress is the sandbox's",
    "a write verb the default-deny lane cannot see as an operand: a path built at runtime, read from a "
    "file or a pipe, or joined inside program text (phase 4 inverts the tables for named operands only)",
    "a shell or alias table the session already holds (an alias set in an earlier Bash call, a sourced "
    "rc file) — each Bash call is read alone",
    "GitHub writes without gh are a TEXT gate's reach only (R6): a token pasted into a file, a client "
    "the gate has no grammar for, a program that reads the keyring by another name. The kernel "
    "sandbox (sandbox.py: the gh credential deny-read off the admin seat) is the real boundary",
    "an operand that neither expands nor reads as a literal path under the working directory "
    "— dropped and logged, so no fence judges it",
)


def print_introspection() -> None:
    """Print module structure for drone routing."""
    CONSOLE.print("[bold cyan]bash_writes[/bold cyan] — write targets a shell command can be seen to name")
    CONSOLE.print("[dim]Consumed by handlers/security/edit_gate.py for the scripted cross-project lane.[/dim]")
    CONSOLE.print()
    CONSOLE.print("[yellow]NOT CAUGHT — the residual, stated rather than discovered:[/yellow]")
    for gap in NOT_CAUGHT:
        CONSOLE.print(f"  - {gap}")


def verb_name(token: str) -> str:
    """The program a command token names, spelled one way on every host.

    Every host reads alike: over-reading TEE on Linux is the safe side; misreading RM.EXE misses a delete.
    """
    # Path(".").name is "": the dot builtin (`. script.sh`) keeps its own name.
    name = Path(token.replace("\\", "/")).name.lower() or token
    stem, dot, ext = name.rpartition(".")
    return stem if dot and f".{ext}" in _EXEC_EXTENSIONS else name


def _program_writes(verb: str, segment: list[str], raw: str) -> bool:
    """True when an interpreter can be SEEN to create a file, or was never read.

    A script path's text was never read, so it counts as writing rather than claim "no write verb" unseen.
    """
    inline = "<<" in segment or any(token in _INLINE_SOURCE_FLAGS for token in segment)
    if not inline:
        return True
    shapes = _SHELL_WRITE_SHAPES if verb in _SHELLS else _SOURCE_WRITE_SHAPES
    return any(shape.search(raw) for shape in shapes)


def _strip_heredoc_bodies(command: str) -> str:
    """Blank out heredoc bodies before the command is read as shell syntax.

    A heredoc body is data: read as syntax, a reply quoting a command blocked itself. Lines are blanked,
    not deleted, so nothing shifts; _interpreter_targets still reads the original text.
    """
    return _split_heredocs(command)[0]


def _split_heredocs(command: str) -> tuple[str, list[str]]:
    """The command with heredoc bodies blanked, and the bodies, in opener order."""
    if "<<" not in command:
        return command, []
    lines = command.split("\n")
    out: list[str] = []
    pending: list[str] = []
    bodies: list[str] = []
    current: list[str] = []
    for line in lines:
        if pending:
            out.append("")
            if line.strip() == pending[0]:
                pending.pop(0)
                bodies.append("\n".join(current))
                current = []
            else:
                current.append(line)
            continue
        out.append(line)
        pending.extend(match.group(2) for match in _HEREDOC_OPEN.finditer(line))
    # An unterminated body is dropped: its opener goes unpaired and the whole-command read holds it.
    return "\n".join(out), bodies


def _strip_comments(command: str) -> str:
    """Drop shell comments, keeping the newline that ends each one.

    shlex reads ``#`` anywhere in a word; the shell opens a comment only at a word start, never in quotes.
    """
    if "#" not in command:
        return command
    out: list[str] = []
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        if char == "\\" and quote != "'" and index + 1 < len(command):
            out.append(command[index : index + 2])
            index += 2
            continue
        if quote:
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif char == "#" and (index == 0 or command[index - 1] in " \t\n;&|()"):
            end = command.find("\n", index)
            index = len(command) if end < 0 else end
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _tokenize(command: str) -> list[str]:
    """Split a command into tokens, keeping shell operators as their own tokens.

    An unbalanced quote falls back to whitespace splitting, logged: no tokens would read as no writes.
    """
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=_PUNCTUATION)
        lexer.whitespace_split = True
        lexer.whitespace = " \t\r"
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError as exc:
        logger.info("[HOOKS] bash_writes: lexer fell back to whitespace split (%s)", exc)
        return [token for line in command.split("\n") for token in (*line.split(), "\n")]
    out: list[str] = []
    for token in tokens:
        if len(token) > 1 and all(char in _PUNCTUATION for char in token):
            out.extend(piece for piece in _OPERATOR_SPLIT.split(token) if piece)
        else:
            out.append(token)
    return out


def _readings(command: str) -> list[list[str]]:
    """Every token stream this command could honestly be. Usually one.

    POSIX escapes eat Windows separators (``C:\\Users\\x`` reads as one local name), so both readings
    are unioned: ``\\`` as a separator only adds components, never making a foreign write local.
    """
    # A backslash-newline is a continuation: join the lines before a newline means "next command".
    shell = _strip_comments(_strip_heredoc_bodies(command).replace("\\\n", ""))
    readings = [_tokenize(shell)]
    if "\\" in shell:
        protected = _tokenize(shell.replace("\\", "\\\\"))
        if protected != readings[0]:
            readings.append(protected)
    return readings


def _segments(tokens: list[str]) -> list[list[str]]:
    """Group tokens into individual commands, split on shell separators."""
    out: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in (_SUBSHELL_OPEN, _SUBSHELL_CLOSE):
            if current:
                out.append(current)
            out.append([token])
            current = []
            continue
        if token in _SEPARATORS:
            if current:
                out.append(current)
            current = []
            continue
        current.append(token)
    if current:
        out.append(current)
    return out


def _looks_like_path(token: str) -> bool:
    """True for operands that could name a file on disk.

    An unexpanded variable is excluded: half a path on the wrong root names a project nobody addressed.
    """
    if not token or token.startswith("-"):
        return False
    if "$" in token or "*" in token or "?" in token:
        return False
    return "/" in token or "\\" in token or "." in token or token.isidentifier()


def _resolve(word: str, cwd: Path) -> Path | None:
    """Resolve one operand against the segment's working directory.

    None means an empty word, which names no file; every caller drops it. A word pathlib cannot
    read even literally raises, and the gate calling this refuses the command.
    """
    word = word.strip().strip(_TRAILING_JUNK)
    if not word:
        return None
    # Git Bash drives, on a Windows cwd only (on POSIX /c is a directory): WindowsPath("/c/x") joins the
    # seat's drive as C:\c\x and lets a foreign write through.
    if isinstance(cwd, PureWindowsPath) and (drive := _GIT_BASH_DRIVE.match(word)):
        word = f"{drive.group(1).upper()}:/{word[drive.end() :].lstrip('/')}"
    # Separators normalise on every OS; a drive ROOT still names nothing on Linux (NOT_CAUGHT).
    word = word.replace("\\", "/")
    # os.path keeps an unknown user's word (~nosuchuser) literal, as bash does; pathlib raises on it.
    candidate = Path(os.path.expanduser(word))
    return candidate if candidate.is_absolute() else (cwd / candidate)


def _redirect_targets(segment: list[str], cwd: Path) -> list[tuple[Path, str]]:
    """Collect `> file` / `>> file` destinations."""
    hits: list[tuple[Path, str]] = []
    for index, token in enumerate(segment):
        if index + 1 >= len(segment):
            continue
        word = segment[index + 1]
        if token not in _REDIRECT_OPS and not (token == _DUP_OP and not (word.isdigit() or word == "-")):
            continue
        target = _resolve(segment[index + 1], cwd)
        if target is not None:
            hits.append((target, f"redirection ({token})"))
    return hits


def _operands(segment: list[str]) -> list[str]:
    """Non-flag, non-operator tokens of a command, excluding the command name."""
    out: list[str] = []
    for token in segment[1:]:
        if token in _REDIRECT_OPS or token.startswith(("-", ">", "<", "&")):
            continue
        out.append(token)
    return out


def _sed_short_letters(flag: str) -> str:
    """A short cluster's option letters: an i ends them, the rest is its backup suffix (-ni.bak reads ni)."""
    letters = flag[1:]
    return letters[: letters.index("i") + 1] if "i" in letters else letters


def _sed_in_place_targets(segment: list[str], cwd: Path) -> list[tuple[Path, str]]:
    """Every file `sed -i` edits, never its script (pad row 87, devpulse 953c8a70)."""
    flags = [token for token in segment[1:] if token.startswith("-") and token != "-"]
    longs = {flag.split("=", 1)[0] for flag in flags if flag.startswith("--")}
    shorts = "".join(_sed_short_letters(flag) for flag in flags if not flag.startswith("--"))
    if not (longs & _INPLACE_FLAGS or "i" in shorts):
        return []
    inputs = sed_scripts(segment[1:])[2]
    return [(t, "sed -i") for t in (_resolve(o, cwd) for o in inputs if _looks_like_path(o)) if t is not None]


def _verb_targets(segment: list[str], cwd: Path) -> list[tuple[Path, str]]:
    """Collect write targets named by a known verb's own grammar."""
    verb = verb_name(segment[0])
    operands = [t for t in _operands(segment) if _looks_like_path(t)]
    hits: list[tuple[Path, str]] = []

    if verb == "dd":
        for token in segment[1:]:
            if token.startswith("of="):
                target = _resolve(token[3:], cwd)
                if target is not None:
                    hits.append((target, "dd of="))
        return hits

    if verb == "sed":
        written = [path for script in sed_scripts(segment[1:])[0] for path in sed_actions(script)[1]]
        hits = [(t, "sed w") for t in (_resolve(path, cwd) for path in written) if t is not None]
        return _sed_in_place_targets(segment, cwd) + hits

    if verb in _ALL_OPERANDS:
        return [(t, verb) for t in (_resolve(o, cwd) for o in operands) if t is not None]

    if verb in _LAST_OPERAND:
        return [(t, f"{verb} destination") for t in _landings(segment, operands, cwd)]
    return hits


def _landings(segment: list[str], operands: list[str], cwd: Path) -> list[Path]:
    """Where cp/mv/ln land: dest, or each source's name in a directory dest (shell_reader._landing; it imports us)."""
    words = segment[1:]
    target_dir = next((w.split("=", 1)[1] for w in words if w.startswith("--target-directory=")), None)
    if "-t" in words[:-1]:
        target_dir = words[words.index("-t") + 1]
    if target_dir is not None:
        sources, dest = [o for o in operands if o != target_dir], target_dir
    elif len(operands) >= 2:
        sources, dest = operands[:-1], operands[-1]
    else:
        return []
    target = _resolve(dest, cwd)
    if target is None:
        return []
    into_dir = target_dir is not None or dest.endswith(("/", "\\")) or os.path.isdir(target)
    if into_dir and "-T" not in words and "--no-target-directory" not in words:
        return [target / Path(source.replace("\\", "/")).name for source in sources] or [target]
    return [target]


def _interpreter_targets(segment: list[str], raw: str, cwd: Path) -> list[tuple[Path, str]]:
    """Collect every path an interpreter invocation is handed.

    *raw* is its OWN text (its command and its heredoc), scanned as text so a path the lexer glued into
    source comes out whole. Never the whole command: a later segment's path resolves from the wrong cwd.
    """
    verb = verb_name(segment[0])
    if verb not in _INTERPRETERS:
        return []
    writes = _program_writes(verb, segment, raw)
    why = f"{verb} {HELD_BY_INTERPRETER}" if writes else f"{verb} {HELD_BY_INTERPRETER}{NO_WRITE_VERB}"
    seen: set[str] = set()
    hits: list[tuple[Path, str]] = []
    for match in _PATH_RUN.findall(raw):
        token = match.strip(_TRAILING_JUNK)
        if not token or token in seen or "$" in token:
            continue
        # Separators alone are not a path: an escaped quote (\\") would put filesystem root in a refusal.
        if not any(char.isalnum() for char in token):
            continue
        seen.add(token)
        target = _resolve(token, cwd)
        if target is not None:
            hits.append((target, why))
    return hits


def write_targets_by_segment(command: str, cwd: str) -> list[tuple[list[str], list[tuple[Path, str]]]]:
    """Same reading as :func:`write_targets`, but grouped by the segment that earned it.

    For narrower callers (testwrite_gate drops interpreter targets from runner segments only); a segment
    naming no target comes with an empty list.
    Raises OSError when no cwd is given and the process has none: [] would read as "writes nothing".
    """
    if not command or not command.strip():
        return []
    try:
        base = Path(cwd) if cwd else Path.cwd()
    except OSError as exc:
        logger.warning("[HOOKS] bash_writes: no usable cwd, the command cannot be read: %s", exc)
        raise

    # Heredoc bodies are stripped for the syntax read and kept for the interpreter read.
    grouped: list[tuple[list[str], list[tuple[Path, str]]]] = []
    seen: set[tuple[Path, str]] = set()
    bodies = _split_heredocs(command)[1]
    for tokens in _readings(command):
        current = base
        subshells: list[Path] = []
        segments = _segments(tokens)
        owned = _heredocs_by_segment(segments, bodies)
        for index, segment in enumerate(segments):
            if not segment:
                continue
            if segment == [_SUBSHELL_OPEN]:
                subshells.append(current)
                continue
            if segment == [_SUBSHELL_CLOSE]:
                current = subshells.pop() if subshells else current
                continue
            verb = verb_name(segment[0])

            # cd moves the ground: untracked, `cd ../Other && sed -i s/a/b/ f.json` reads as a local write.
            if verb == "cd" and len(segment) > 1:
                moved = _resolve(segment[1], current)
                if moved is not None:
                    current = moved
                continue

            hits: list[tuple[Path, str]] = []
            for hit in (
                *_redirect_targets(segment, current),
                *_verb_targets(segment, current),
                *_interpreter_targets(segment, owned.get(index, command), current),
            ):
                # The two readings overlap; one write must not be named twice.
                if hit in seen:
                    continue
                seen.add(hit)
                hits.append(hit)
            grouped.append((segment, hits))

    return grouped


def _heredocs_by_segment(segments: list[list[str]], bodies: list[str]) -> dict[int, str]:
    """Each segment's own text: its tokens plus the heredoc bodies it opened.

    Paired in order; on a mismatch nothing is returned and every interpreter keeps the whole command.
    """
    openers = [sum(1 for token in segment if token == "<<") for segment in segments]
    if sum(openers) != len(bodies):
        if bodies:
            logger.info(
                "[HOOKS] bash_writes: %d heredoc bodies, %d openers - whole-command read", len(bodies), sum(openers)
            )
        return {}
    owned: dict[int, str] = {}
    taken = 0
    for index, segment in enumerate(segments):
        own = bodies[taken : taken + openers[index]]
        taken += openers[index]
        owned[index] = "\n".join([" ".join(segment), *own])
    return owned


def write_targets(command: str, cwd: str) -> list[tuple[Path, str]]:
    """Return every (path, why) this command can be seen to write."""
    return [hit for _segment, hits in write_targets_by_segment(command, cwd) for hit in hits]


def changed_paths(command: str, cwd: str) -> list[str]:
    """Every path *command* can be seen to change: shell_reader.mutated_paths plus each operand of a program
    that does not only read (``crudini --set <file>``, ``ed <file>``). Imported late: shell_reader imports this module."""
    from aipass.hooks.apps.modules import shell_reader

    paths = [str(path) for path, _role, _how in shell_reader.mutated_paths(command, cwd)]
    invocations = shell_reader.invocations(command, cwd)
    paths.extend(str(path) for _program, path in named_operands(invocations))
    return paths
