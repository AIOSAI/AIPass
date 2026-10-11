# Minimal __init__.py - handler independence pattern
# No exports - handlers import directly when needed

# Python 3.10 mock.patch compatibility — submodules must be importable as
# attributes for mock._dot_lookup to resolve dotted paths.
from . import detector
