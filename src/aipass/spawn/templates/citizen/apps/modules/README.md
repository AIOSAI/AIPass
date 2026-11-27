# Modules

Business logic for `{{BRANCHNAME}}`. One module per command.

Modules orchestrate work by calling handlers. They are the public API of the branch — drone routes commands here.

Each module defines three functions, and sentry's cli_ux check reads all three:

- `handle_command(command, args)`: no args prints the introspection; `--help` prints the help.
- `print_introspection()`: what the module is and which handlers it calls. Its last line points at the help, for example `Run drone @{{BRANCH}} <command> --help for usage`.
- `print_help()`: a `Usage:` line, the flags, then an `Examples:` heading with real commands. Pass `highlight=False` on a plain line that holds numbers, so Rich does not colour them.
