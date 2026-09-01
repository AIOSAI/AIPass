"""Fleet-level pytest conftest: keeps handler-embedded test fixtures out of collection.

Template test files shipped inside apps/handlers/ are fixture material for the
branches' own checkers, not tests of this repo — collecting them would run them
against whichever branch pytest happens to root in.
"""

import os

collect_ignore_glob = [
    os.path.join("*", "apps", "handlers", "*", "test_*.py"),
    os.path.join("*", "apps", "handlers", "*", "*", "test_*.py"),
]
