# Handlers

Implementation details for `DAEMON`.

Handlers do the actual work. They are called by modules, never directly by the CLI. Keep business logic in modules, implementation in handlers.
