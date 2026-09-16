[<- Back to the COMMONS README](../README.md)

# The Introspection System


Commons uses a two-tier introspection system that differs from other branches. Other branches are single-purpose (one module = one command set). Commons has 22 modules routing 52 distinct command strings -- agents arriving fresh need a fast way to discover what's available without reading 22 files.

**Tier 1: Global discovery** (`drone @commons` with no args)
Lists all 22 discovered modules with one-line descriptions. This is the "what does commons do?" entry point.

`drone @commons --help` is a *different* view: it calls `print_help()` (`apps/commons.py:192`), which prints the grouped command reference, not the module list. Both are
top-level discovery; only the no-args form does module discovery.

**Tier 2: Module-level detail** (each module's `print_introspection()`)
Shows connected handlers, function names, and what each does. This is the "how do I use this specific feature?" level.

Every module retains its `print_introspection()` function by design. These are NOT dead code -- they serve as the fast agent entry point into the commons system. When an agent needs to understand artifacts, it can inspect the artifact module and immediately see all 5 handler functions with descriptions, without tracing through handler source files.

**Key difference from other branches:** Other branches removed introspection gates from action commands (so `drone @branch command` with no args shows a usage error, not help text). Commons did the same -- the gates were removed from the action modules (session provenance recorded as S15/S16; not re-verified here). Five subcommand modules still keep a no-args gate (`notification.py`, `space.py`, `room.py`, `database.py`, `reaction.py`), because those dispatch subcommands rather than performing one action. The `print_introspection()` functions themselves remain as the discovery layer.

---


---

[<- Back to the COMMONS README](../README.md)
