# Modules package - Branch-specific functionality modules
#
# UnknownArgument is re-exported here on purpose: the router (apps/daemon.py)
# talks to the modules layer, never to a handler directly. The gate that raises
# it lives in apps/handlers/cli/arg_gate.py, where every module imports it from.
from aipass.daemon.apps.handlers.cli.arg_gate import UnknownArgument

__all__ = ["UnknownArgument"]
