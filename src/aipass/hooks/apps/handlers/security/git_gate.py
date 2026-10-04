# =================== AIPass ====================
# Name: git_gate.py
# Version: 5.0.0
# Description: Raw git and gh, GitHub API writes and credentials for every seat; protected file changes (PreToolUse)
# Branch: hooks
# Layer: apps/handlers/security
# Created: 2026-05-21
# Modified: 2026-10-04
# =============================================

"""Blocks raw git and gh, GitHub writes without gh, the gh credential, and changes to the protected files.

Failure mode: a crash refuses the call it was checking (Bash and edit tools);
the engine refuses on import error and timeout.

Since 5.0.0 (DPLAN-0356 follow-up, the owner 2026-10-04: "if drone cannot do
it, it cannot be done"): raw git, read or write, raw gh (``gh api`` GET
included) and the R5/R6 lanes below are refused for EVERY seat, the verified
admin seat included. A git refusal names the drone @git twin of the verb; a
verb with no twin cannot be done, and the refusal says to mail @devpulse to ask
@drone for one. Only the protected-file lane still answers to WHO: those files
are the admin seat's to write (modules/admin_seat's 5-leg grant, never a
directory name). Agent Bash only: service code that runs git as a subprocess
never passes through a hook.

Since 3.0.0 (DPLAN-0356 phase 2): the protected files (modules/protected_paths)
are the admin seat's to write; WHO is the grant alone; no refusal tells an agent
how to switch a gate off.

Since 4.0.0 (DPLAN-0356 phase 3, the red team's root causes):
  - R3: the program is read through modules/shell_reader, the branch's one
    shell-word reader, the way the shell will run it. ``'g'it push``,
    ``$'\\x67it' push``, ``{git,x} push``, ``eval 'git push'`` and ``uv run git
    push`` are git. This gate keeps no split or regex of its own.
  - R5: an interpreter whose readable program launches git or gh (a
    subprocess call, backticks, GitPython, octokit) is refused.
  - R6: reading the gh credential (``gh auth token``, the
    keyring, gh's hosts file) and an HTTP client writing to the GitHub API
    (curl/wget/httpie with a method other than GET or a body; the same in an
    interpreter's program) are refused. A text gate cannot close this fully:
    bash_writes.NOT_CAUGHT says so, and the kernel sandbox is the real boundary.
  - R1/R2: the protected lane asks shell_reader.mutated_paths, so a delete, a
    move away, a move over, a recursive copy over and a hard link whose source
    is a protected file are refused off the admin seat on this lane's own
    reading; protected_paths matches by file identity as well as by name.
"""

import importlib
import json
import os

from aipass.prax.apps.modules.logger import system_logger as logger


# The owner, 2026-10-04: any git command is blocked; if drone cannot do it, it cannot be done.
# The refusal names the drone @git twin of the verb; a verb missing here has none.
_GIT_TWINS = {
    "status": "drone @git status [--all]",
    "diff": "drone @git diff [--staged] [--all]",
    "log": "drone @git log [count] [path ...] [-- gone-path ...]",
    "show": "drone @git show <ref> [path]",
    "blame": "drone @git blame <file> [-L START,END]",
    "remote": "drone @git remote",
    "branch": "drone @git branches",
    "tag": "drone @git tag --list",
    "commit": "drone @git commit <msg> [--all | files]",
    "checkout": "drone @git checkout <main|dev>",
    "switch": "drone @git checkout <main|dev>",
    "push": "drone @git pr <desc>",
    "pull": "drone @git sync",
    "fetch": "drone @git smart-sync",
    "rebase": "drone @git smart-sync",
    "merge": "drone @git merge-main (dev) or drone @git merge <PR#>",
}

_GIT_OPTS_WITH_ARG = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--exec-path", "--namespace"})

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

# R6: HTTP clients, and the flags that make a request more than a read.
_HTTP_CLIENTS = frozenset({"curl", "wget", "http", "https", "xh", "xhs", "httpie"})
_CURL_METHOD = ("-X", "--request")
_CURL_BODY = ("-d", "--data", "--data-raw", "--data-binary", "--data-urlencode", "--data-ascii", "--json")
_CURL_UPLOAD = ("-F", "--form", "--form-string", "-T", "--upload-file")
_WGET_BODY = ("--post-data", "--post-file", "--body-data", "--body-file")
_HTTPIE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_HTTPIE_BODY_FLAGS = ("-f", "--form", "--multipart", "--raw")

# R6: programs that read a stored secret, and the subcommands of `security` (macOS) that do.
_SECRET_PROGRAMS = frozenset({"secret-tool", "kwallet-query"})
_SECURITY_READS = frozenset({"find-generic-password", "find-internet-password", "dump-keychain"})
_CREDENTIAL_FILES = ("gh/hosts.yml", ".git-credentials")

RAW_GIT_REFUSED = (
    "Raw git is refused for every seat, the admin seat included (the owner's ruling, 2026-10-04: "
    "if drone cannot do it, it cannot be done). Caller: {caller}.\n"
    "\n"
    "{twin}\n"
    "\n"
    "The full list: `drone @git --help`, section RAW GIT READS AND THEIR TWINS."
)

TWIN_LINE = "Its drone twin:  git {verb}  ->  {twin}"

NO_TWIN_LINE = (
    "git {verb} has no drone twin, so it cannot be done. Need it? Mail @devpulse to ask @drone for one:\n"
    '  drone @ai_mail email @devpulse "Drone twin: git {verb}" "<why>"'
)

GH_REDIRECT = (
    "Raw gh is refused for every seat, the admin seat included, gh api GET too (the owner's ruling, "
    "2026-10-04). Drone owns gh.\n"
    "\n"
    "Read and act through the drone @git twins:\n"
    "  gh issue list|view|status     ->  drone @git issue list|view|status\n"
    "  gh run list|view|watch        ->  drone @git run list|view|watch   (view <id> --log-failed)\n"
    "  gh workflow list|view         ->  drone @git workflow list|view\n"
    "  gh pr create                  ->  drone @git pr <desc>\n"
    "\n"
    "Run `drone @git --help` for the full command list. No twin means it cannot be done: "
    "mail @devpulse to ask @drone for one."
)

INTERPRETER_GIT_REFUSED = (
    "A program launching git or gh from inside an interpreter is refused for every seat, the admin seat "
    "included (the owner's ruling, 2026-10-04), the same as raw git and gh. Caller: {caller}.\n"
    "Seen: {what}.\n"
    "\n"
    "Use the drone @git twins from the shell instead: drone @git status | diff | log | show | run list | "
    "issue list.\n"
    "If drone cannot do it, it cannot be done: mail @devpulse to ask @drone for a twin."
)

CREDENTIAL_REFUSED = (
    "Reading the GitHub credential is refused for every seat, the admin seat included (the owner's ruling, "
    "2026-10-04). Caller: {caller}.\n"
    "Seen: {what}.\n"
    "\n"
    "Nothing a seat does needs the token: drone @git holds it."
)

GITHUB_HTTP_REFUSED = (
    "A write to the GitHub API is refused for every seat, the admin seat included (the owner's ruling, "
    "2026-10-04), with gh or without it. Caller: {caller}.\n"
    "Seen: {what}.\n"
    "\n"
    "A GET with no body runs. A write GitHub must see goes through drone @git; no twin means it cannot be done."
)

UNNAMED_CALLER = "could not be named (no readable passport above {cwd})"

PROTECTED_REFUSED = (
    "{path} is protected: it is {what}, which decides whether the gates run.\n"
    "Only the admin seat (@devpulse) writes it ({lane}). Caller: {caller}.\n"
    "If a real change is needed, mail @devpulse:\n"
    '  drone @ai_mail email @devpulse "Config change" "<path>: <what and why>"'
)

GATE_CRASHED = (
    "git_gate could not check this call ({error}), so it is refused: a gate that cannot read a command "
    "does not let it through.\n"
    'Mail @hooks and @devpulse: drone @ai_mail email @hooks "Gate broken: git_gate" "<what you ran, and this text>"'
)

_BLOCK_ALLOW = {"stdout": "", "exit_code": 0}

# Roles under which a protected file inside a directory is reached: removing or replacing the directory.
_CONTAINER_ROLES = frozenset({"delete", "move-away", "overlay"})


def _reader():
    """The branch's one shell-word reader (modules/shell_reader), imported at call time (crash isolation)."""
    return importlib.import_module("aipass.hooks.apps.modules.shell_reader")


def _shell_programs():
    """The default-deny tables (modules/shell_programs), imported at call time (crash isolation)."""
    return importlib.import_module("aipass.hooks.apps.modules.shell_programs")


def _protected_paths():
    """modules/protected_paths, reached at call time: a handler never imports a module at import time."""
    return importlib.import_module("aipass.hooks.apps.modules.protected_paths")


def _block(reason: str) -> dict:
    return {"stdout": json.dumps({"decision": "block", "reason": reason}), "exit_code": 2, "sound": "git gate"}


class _Seat:
    """The caller, asked of modules/admin_seat once per call and only when a refusal needs it. Fail-closed."""

    def __init__(self, cwd: str) -> None:
        self.cwd = cwd
        self._answer: tuple[str | None, bool] | None = None

    def _ask(self) -> tuple[str | None, bool]:
        if self._answer is not None:
            return self._answer
        answer: tuple[str | None, bool] = (None, False)
        try:
            answer = importlib.import_module("aipass.hooks.apps.modules.admin_seat").seat_of(self.cwd)
        except Exception as exc:  # an unreachable seat module refuses rather than opens
            logger.warning("[HOOKS] git_gate: admin lane dark — admin_seat unavailable, refusing as unnamed: %s", exc)
        self._answer = answer
        return answer

    @property
    def admin(self) -> bool:
        """True on the verified admin seat."""
        return self._ask()[1]

    @property
    def named(self) -> str:
        """The caller as a refusal names it."""
        caller = self._ask()[0]
        return f"@{caller}" if caller else UNNAMED_CALLER.format(cwd=self.cwd or "(no cwd)")


def _extract_git_verb(tokens: list[str] | tuple[str, ...]) -> str | None:
    """Extract the git subcommand verb, skipping global options."""
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if not tok.startswith("-"):
            # Lowercased for the membership test that follows it: the verb is
            # read on every host the same way the program name is.
            return tok.lower()
        if tok in _GIT_OPTS_WITH_ARG:
            i += 2
            continue
        i += 1
    return None


def _git_refusal(invocations: list, seat: _Seat) -> dict | None:
    """Raw git, read or write, refused for every seat, the admin seat included; the refusal names the twin.

    A bare ``git`` with no argument prints usage and touches nothing; a path-spelled
    one with no verb is not a usage print anyone types, and is refused.
    """
    calls = [
        inv.argv[1:]
        for inv in invocations
        if inv.program == "git" and (len(inv.argv) > 1 or "/" in inv.argv[0] or "\\" in inv.argv[0])
    ]
    if not calls:
        return None
    verb = _extract_git_verb(calls[0]) or "(no verb)"
    twin = _GIT_TWINS.get(verb)
    line = TWIN_LINE.format(verb=verb, twin=twin) if twin else NO_TWIN_LINE.format(verb=verb)
    return _block(RAW_GIT_REFUSED.format(caller=seat.named, twin=line))


def _next(args, index: int) -> str:
    return args[index + 1] if index + 1 < len(args) else ""


def _gh_refusal(invocations: list, seat: _Seat) -> dict | None:
    """Raw gh, every subcommand, ``gh api`` GET included, refused for every seat, the admin seat included."""
    del seat  # WHO does not matter here: drone owns gh
    if not any(inv.program == "gh" for inv in invocations):
        return None
    return _block(GH_REDIRECT)


def _credential_read(inv, reader) -> str:
    """What reads the gh credential in this program (R6), "" when nothing does."""
    args = inv.argv[1:]
    if inv.program == "gh" and args[:1] == ("auth",):
        if args[1:2] == ("token",) or (args[1:2] == ("status",) and any(a in ("-t", "--show-token") for a in args)):
            return "gh " + " ".join(args[:2])
    if inv.program in _SECRET_PROGRAMS:
        return inv.program
    if inv.program == "keyring" or (inv.language == "python" and "keyring" in args and "-m" in args):
        return "the keyring command"
    if inv.program == "security" and args[:1] and args[0] in _SECURITY_READS:
        return f"security {args[0]}"
    for arg in args:
        if any(name in arg.replace("\\", "/") for name in _CREDENTIAL_FILES):
            return f"a credential file ({arg})"
    return reader.program_credential(inv)


def _flag_value(args, index: int, names: tuple[str, ...]) -> str | None:
    """The value of a flag in *names* at args[index] (next word, ``--x=v`` or ``-Xv``), None when it is not one."""
    arg = args[index]
    for name in names:
        if arg == name:
            return _next(args, index)
        if name.startswith("--") and arg.startswith(name + "="):
            return arg[len(name) + 1 :]
        if not name.startswith("--") and arg.startswith(name) and len(arg) > len(name):
            return arg[len(name) :]
    return None


def _http_write(inv) -> str:
    """The write an HTTP client makes to the GitHub API (R6): a method other than GET/HEAD, or a body."""
    args = inv.argv[1:]
    if inv.program not in _HTTP_CLIENTS or not any(_reader().GITHUB_API_HOST.search(a) for a in args):
        return ""
    if inv.program == "curl":
        return _curl_write(args)
    if inv.program == "wget":
        method = next((v for i in range(len(args)) if (v := _flag_value(args, i, ("--method",))) is not None), None)
        if method is not None and method.upper() not in ("GET", "HEAD"):
            return f"wget --method {method}"
        return next((f"wget {a.split('=')[0]}" for a in args if a.split("=")[0] in _WGET_BODY), "")
    return _httpie_write(inv.program, args)


def _curl_write(args) -> str:
    get = "-G" in args or "--get" in args
    for index, arg in enumerate(args):
        method = _flag_value(args, index, _CURL_METHOD)
        if method is not None and method.upper() not in ("GET", "HEAD"):
            return f"curl method {method}"
        if _flag_value(args, index, _CURL_UPLOAD) is not None:
            return f"curl upload ({arg})"
        if not get and _flag_value(args, index, _CURL_BODY) is not None:
            return f"curl request body ({arg})"
    return ""


def _httpie_write(program: str, args) -> str:
    positional = [a for a in args if not a.startswith("-")]
    if positional and positional[0].upper() in _HTTPIE_METHODS:
        return f"{program} {positional[0]}"
    if any(a in _HTTPIE_BODY_FLAGS for a in args):
        return f"{program} form or raw body"
    items = positional[1:]
    if any(":=" in a or "=@" in a or ("=" in a and "==" not in a) for a in items):
        return f"{program} request body items"
    return ""


def _program_refusal(invocations: list, reader, seat: _Seat) -> dict | None:
    """R5 and R6, for every seat: git/gh from an interpreter, the gh credential, GitHub API writes."""
    launches, credentials, writes = [], [], []
    for inv in invocations:
        launches.append(reader.program_launch(inv))
        credentials.append(_credential_read(inv, reader))
        writes.extend((_http_write(inv), reader.program_github_write(inv)))
    launches, credentials, writes = ([x for x in found if x] for found in (launches, credentials, writes))
    if not (launches or credentials or writes):
        return None
    if credentials:
        logger.warning("[HOOKS] git_gate: credential read refused: %s", credentials[0])
        return _block(CREDENTIAL_REFUSED.format(caller=seat.named, what=credentials[0]))
    if writes:
        return _block(GITHUB_HTTP_REFUSED.format(caller=seat.named, what=writes[0]))
    return _block(INTERPRETER_GIT_REFUSED.format(caller=seat.named, what=launches[0]))


def _protected_refusal(path: str, what: str, lane: str, seat: _Seat) -> dict | None:
    """The refusal for a change to a gate-switching file; None on the verified admin seat."""
    if seat.admin:
        logger.info("[HOOKS] git_gate: protected change ALLOWED for the admin seat: %s (%s)", path, lane)
        return None
    logger.warning("[HOOKS] git_gate: protected change refused: %s (%s) caller=%s", path, lane, seat.named)
    return _block(PROTECTED_REFUSED.format(path=path, what=what, lane=lane, caller=seat.named))


def _check_bash_protected(cmd: str, cwd: str, invocations: list, seat: _Seat) -> dict | None:
    """Any change to a gate-switching file the command can be seen to make, on this lane's own reading (R1, R2).

    A write, a delete, a move away or over, a recursive copy over and the source
    of a hard link all count; a directory counts when a protected file is inside
    it and the command removes, moves or overlays the directory. Since 4.1.0 the
    lane is default-deny (phase 4, P2): a protected path named as an operand of a
    program that does not only read is refused, whatever the program is.
    """
    pp = _protected_paths()
    named = _shell_programs().named_paths(invocations, pp.protected)
    if named:
        program, path, what = named
        return _protected_refusal(path, what, f"Bash: {program} (not a read-only program)", seat)
    for path, role, how in _reader().mutated_paths(cmd, cwd):
        what = pp.protected(path, cwd)
        if what is None and role in _CONTAINER_ROLES:
            what = pp.protected_within(path)
        if what:
            return _protected_refusal(str(path), what, f"Bash: {how}", seat)
    return None


def _check_bash(tool_input: dict, cwd: str = "") -> dict:
    """Refuse raw git and gh, git/gh from programs, GitHub writes and credentials, and protected changes."""
    cmd = tool_input.get("command", "")
    if not cmd:
        return _BLOCK_ALLOW
    reader = _reader()
    invocations = reader.invocations(cmd, cwd)
    seat = _Seat(cwd)
    for check in (
        lambda: _git_refusal(invocations, seat),
        lambda: _program_refusal(invocations, reader, seat),
        lambda: _gh_refusal(invocations, seat),
        lambda: _check_bash_protected(cmd, cwd, invocations, seat),
    ):
        refused = check()
        if refused is not None:
            return refused
    return _BLOCK_ALLOW


def _check_edit(tool_input: dict, cwd: str) -> dict:
    """Refuse an edit-tool write to a gate-switching file off the verified admin seat."""
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not file_path:
        return _BLOCK_ALLOW
    what = _protected_paths().protected(file_path, cwd)
    if not what:
        return _BLOCK_ALLOW
    return _protected_refusal(file_path, what, "edit tool", _Seat(cwd)) or _BLOCK_ALLOW


def handle(hook_data: dict) -> dict:
    """Block raw git/gh commands, GitHub writes and credential reads, and protected file changes.

    Args:
        hook_data: Parsed hook event dict from engine.

    Returns:
        Result dict with stdout (block JSON or empty) and exit_code.
    """
    tool_name = hook_data.get("tool_name", "") if isinstance(hook_data, dict) else ""
    try:
        tool_input = hook_data.get("tool_input", {})
        cwd = hook_data.get("cwd", "") or os.getcwd()
        if tool_name == "Bash":
            # The payload's session directory only: the seat is never read off this process's cwd.
            return _check_bash(tool_input, hook_data.get("cwd", ""))
        if tool_name in EDIT_TOOLS:
            return _check_edit(tool_input, cwd)
        return _BLOCK_ALLOW
    except Exception as exc:  # fail closed on what this gate guards (DPLAN-0356 item 2)
        logger.error("[HOOKS] git_gate: crashed on %s, refusing it: %s", tool_name or "(no tool)", exc)
        if tool_name == "Bash" or tool_name in EDIT_TOOLS:
            return _block(GATE_CRASHED.format(error=f"{type(exc).__name__}: {exc}"))
        return _BLOCK_ALLOW
