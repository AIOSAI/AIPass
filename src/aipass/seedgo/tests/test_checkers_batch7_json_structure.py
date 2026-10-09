# =================== AIPass ====================
# Name: test_checkers_batch7_json_structure.py
# Description: json_structure_check: declaration-only and bootstrap modules (split from test_checkers_batch7.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/aipass_standards/json_structure_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that each checker in handlers/aipass_standards/ parses and imports

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import json_structure_check

pytestmark = pytest.mark.usefixtures("_pin_bypass_log")


class TestJsonStructureExemptsDeclarationOnlyModules:
    """ "Every module must log operations" is a rule about modules that PERFORM them.

    Raised by @drone 2026-08-31 on drone/apps/handlers/exceptions.py — 86 lines,
    ten exception classes, zero functions. It USED to pass, by carrying
    `log_operation("exceptions_loaded")` at module level. That turned out to be a
    real defect: running at import, it fired during pytest COLLECTION, before any
    fixture existed, so no seam could intercept it. Removing it took the file
    from passing to 0.

    So the check was REWARDING the defect, and both routes to green were worse
    than the violation: put the import-time write back, or add a function to a
    file of pure class definitions purely so there is somewhere to call
    log_operation from — dead code written to satisfy a grep, which
    unused_function would then flag.

    A module that defines no callable code performs no operations, so it has
    nothing to log. The exemption is keyed on that structural fact and nothing
    else: ONE method anywhere, and the module is back in scope.
    """

    def _score(self, source, tmp_path):
        # MUST land under apps/handlers or the checker returns not-applicable
        # on the PATH and every assertion below passes for the wrong reason —
        # which is exactly what the first cut of this class did.
        target = tmp_path / "apps" / "handlers" / "routing" / "mod.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
        return json_structure_check.check_module(str(target))

    DECLARATIONS_ONLY = '"""Doc."""\n\n\nclass RoutingError(Exception):\n    """Boom."""\n\n\nclass BranchNotFound(RoutingError):\n    pass\n'

    def test_a_module_of_pure_exception_classes_is_not_applicable(self, tmp_path):
        result = self._score(self.DECLARATIONS_ONLY, tmp_path)
        assert result["score"] == 100, result["checks"]

    def test_the_exemption_is_published_not_a_silent_pass(self, tmp_path):
        """A skip nobody can read is indistinguishable from a check that ran."""
        result = self._score(self.DECLARATIONS_ONLY, tmp_path)
        text = " ".join(c["message"] for c in result["checks"]).lower()
        # The message names the fact the exemption is keyed on AND why it follows.
        assert "declarations only" in text, result["checks"]
        assert "performs no operations to log" in text, result["checks"]

    def test_one_method_puts_the_module_back_in_scope(self, tmp_path):
        source = '"""Doc."""\n\n\nclass Thing:\n    def do(self):\n        return 1\n'
        assert self._score(source, tmp_path)["score"] < 100

    def test_a_module_level_function_is_still_in_scope(self, tmp_path):
        source = '"""Doc."""\n\n\ndef work():\n    return 1\n'
        assert self._score(source, tmp_path)["score"] < 100

    def test_a_dataclass_with_no_methods_is_exempt(self, tmp_path):
        source = '"""Doc."""\nfrom dataclasses import dataclass\n\n\n@dataclass\nclass Point:\n    x: int\n'
        assert self._score(source, tmp_path)["score"] == 100

    def test_constants_alone_do_not_earn_the_exemption_back(self, tmp_path):
        """Declarations plus data is still declarations."""
        source = '"""Doc."""\n\nLIMIT = 10\n\n\nclass E(Exception):\n    pass\n'
        assert self._score(source, tmp_path)["score"] == 100

    def test_an_unparseable_file_does_not_earn_the_exemption(self, tmp_path):
        """A syntax error is not evidence of purity. Answering "no callable
        code" for a file we could not read hands out the exemption on
        ignorance — and the first cut of these pins let that mutant live."""
        assert self._score('"""Doc."""\n\nclass Broken(\n', tmp_path)["score"] < 100

    def test_the_real_drone_file_is_exempt(self, tmp_path):
        from pathlib import Path

        target = Path(__file__).resolve().parents[2] / "drone" / "apps" / "handlers" / "exceptions.py"
        if not target.exists():
            import pytest

            pytest.skip("drone exceptions.py not on disk")
        assert json_structure_check.check_module(str(target))["score"] == 100


class TestJsonStructureExemptsPreLoggingBootstrapModules:
    """The pre-logging bootstrap class @prax reported (2026-08-31).

    A module the logging substrate itself imports cannot import json_handler
    back: log_operation() WRITES, so wiring it there puts a file write on the
    import path of every branch — the ungateable write that fires during pytest
    COLLECTION. Two clauses decide it, both MEASURED here: no aipass import of
    any kind, AND the logging chain's own imports reach the module. Either
    clause alone hands out the exemption far too widely.
    """

    def _universe(self, tmp_path):
        """A miniature src/aipass with a logger that imports one bootstrap module."""
        root = tmp_path / "src" / "aipass"
        prax = root / "prax" / "apps"
        (prax / "modules").mkdir(parents=True)
        (prax / "handlers").mkdir(parents=True)
        (prax / "modules" / "logger.py").write_text(
            "from aipass.prax.apps.handlers.boot import find_root\ndef get_system_logger():\n    return find_root()\n",
            encoding="utf-8",
        )
        return root

    def _check(self, path):
        """check_module grants the bootstrap exemption. Mutant: exemption bypassed in json_structure_check.py — killed."""
        message = json_structure_check.check_module(str(path))["checks"][0]["message"]
        return message.startswith("Pre-logging bootstrap module")

    def test_a_stdlib_only_module_the_logger_imports_is_exempt(self, tmp_path):
        root = self._universe(tmp_path)
        boot = root / "prax" / "apps" / "handlers" / "boot.py"
        boot.write_text(
            "import logging\nfrom pathlib import Path\n\ndef find_root():\n    return Path(__file__).parent\n",
            encoding="utf-8",
        )
        assert self._check(boot) is True

    def test_the_same_module_loses_the_exemption_the_moment_it_imports_aipass(self, tmp_path):
        root = self._universe(tmp_path)
        boot = root / "prax" / "apps" / "handlers" / "boot.py"
        boot.write_text(
            "from pathlib import Path\n"
            "from aipass.prax.apps.handlers.json import json_handler\n\n"
            "def find_root():\n    return Path(__file__).parent\n",
            encoding="utf-8",
        )
        assert self._check(boot) is False

    def test_an_aipass_import_inside_a_function_still_disqualifies(self, tmp_path):
        """The dependency is taken wherever it is written. A module that can reach
        aipass from inside a function can reach json_handler the same way."""
        root = self._universe(tmp_path)
        boot = root / "prax" / "apps" / "handlers" / "boot.py"
        boot.write_text(
            "from pathlib import Path\n\n"
            "def find_root():\n"
            "    from aipass.prax.apps.handlers.json import json_handler\n"
            "    return Path(__file__).parent\n",
            encoding="utf-8",
        )
        assert self._check(boot) is False

    def test_a_stdlib_only_module_the_chain_never_reaches_is_not_exempt(self, tmp_path):
        """Clause 2 is what keeps the exemption from being free — 79 fleet modules
        import nothing from aipass, and only 9 are in the chain."""
        root = self._universe(tmp_path)
        lonely = root / "prax" / "apps" / "handlers" / "lonely.py"
        lonely.write_text(
            "import re\n\ndef parse(text):\n    return re.findall(r'x', text)\n",
            encoding="utf-8",
        )
        assert self._check(lonely) is False

    def test_an_unparseable_file_is_not_exempt(self, tmp_path):
        """_aipass_imports answers [] for a file it could not read, which would
        otherwise read as 'holds no aipass import'. No exemption on ignorance."""
        root = self._universe(tmp_path)
        boot = root / "prax" / "apps" / "handlers" / "boot.py"
        boot.write_text("def find_root(:\n    pass\n", encoding="utf-8")
        assert self._check(boot) is False

    def test_a_file_outside_any_aipass_source_root_is_not_exempt(self, tmp_path):
        """Under apps/handlers/, so check_module asks the question and only the missing root answers it.
        Mutant: a file with no aipass source root is exempt in apps/handlers/aipass_standards/json_structure_check.py — killed."""
        loose = tmp_path / "apps" / "handlers" / "loose.py"
        loose.parent.mkdir(parents=True)
        loose.write_text("import re\n\ndef parse(t):\n    return t\n", encoding="utf-8")
        assert self._check(loose) is False

    def test_the_real_prax_repo_root_scores_100(self):
        """The live case that prompted the rule — pinned against the real tree so a
        regression shows up as prax going red again, not as a green unit test."""
        from pathlib import Path

        import pytest

        target = Path(__file__).resolve().parents[2] / "prax" / "apps" / "handlers" / "repo_root.py"
        if not target.exists():
            pytest.skip("prax/apps/handlers/repo_root.py not on disk")
        result = json_structure_check.check_module(str(target))
        assert result["score"] == 100
        assert "bootstrap" in result["checks"][0]["message"]

    def test_the_real_memory_repo_root_is_not_exempt(self):
        """Same filename, same purpose, different position: memory's copy imports
        json_handler and the prax logger, so it is a consumer and stays in scope."""
        from pathlib import Path

        import pytest

        target = Path(__file__).resolve().parents[2] / "memory" / "apps" / "handlers" / "repo_root.py"
        if not target.exists():
            pytest.skip("memory/apps/handlers/repo_root.py not on disk")
        assert self._check(target) is False


class TestTheBootstrapChainSeesRelativeImports:
    """@canary's json_structure finding, and it was a hole in an exemption I
    ratified the night before.

    Clause 2 of the pre-logging bootstrap exemption asks whether the logging
    substrate's own imports REACH a module. The walk only followed absolute
    ``aipass.*`` imports, and @canary's json_handler reaches its stdlib-only
    helper with ``from ..paths import module_file`` — so a module that IS
    beneath the logging system was invisible to the walk and got told to import
    it. A relative import is a STATIC fact, unlike the importlib hops the walk
    deliberately cannot see, so resolving it moves the set toward correct in the
    direction the walk's own docstring already asks for.
    """

    def _resolve(self, module, level, package):
        # The resolver is the unit, pure name arithmetic, public since 10-08;
        # check_module reaches it only through a whole src/aipass tree, which the
        # end-to-end test below already walks.
        return json_structure_check.resolve_relative(module, level, package)

    def test_a_sibling_import_resolves(self):
        assert self._resolve("paths", 2, "aipass.canary.apps.handlers.json") == "aipass.canary.apps.handlers.paths"

    def test_a_same_package_import_resolves(self):
        assert self._resolve("utils", 1, "aipass.canary.apps.handlers") == "aipass.canary.apps.handlers.utils"

    def test_a_bare_from_dot_import_resolves_to_the_package(self):
        assert self._resolve(None, 1, "aipass.canary.apps.handlers") == "aipass.canary.apps.handlers"

    def test_no_package_means_no_resolution(self):
        """Negative control: guessing an absolute name for a file we cannot
        place would put fabricated members into the chain, and the chain hands
        out exemptions. Coming up SHORT is the safe direction."""
        assert self._resolve("paths", 2, None) is None

    def test_climbing_past_the_root_answers_none(self):
        assert self._resolve("x", 9, "aipass.canary") is None

    def test_an_absolute_import_is_untouched_by_the_resolver(self):
        assert self._resolve("aipass.prax", 0, "aipass.canary.apps") is None

    def test_the_walk_reaches_a_relatively_imported_bootstrap_module(self, tmp_path):
        """End to end on the real tree: @canary's helper is in the chain now."""
        from pathlib import Path

        # parents[2] is src/aipass — parents[3] is src, and the wrong one made
        # this skip instead of run. A skip reports its own defeat as a pass,
        # which is the whole reason the branch is asserted rather than guessed.
        aipass_root = Path(__file__).resolve().parents[2]
        assert aipass_root.name == "aipass", aipass_root
        target = aipass_root / "canary" / "apps" / "handlers" / "paths.py"
        if not target.exists():
            import pytest

            pytest.skip(f"canary's paths.py is not on this machine ({target})")
        message = json_structure_check.check_module(str(target))["checks"][0]["message"]
        assert message.startswith("Pre-logging bootstrap module"), message
