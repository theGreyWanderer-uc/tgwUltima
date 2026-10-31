"""Allow running the package directly: ``python -m titan``."""

import sys

from .cli import main

# Guarded so spawn-mode worker processes, which re-import this module as
# ``__mp_main__``, do not re-run the CLI.
if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code if exit_code is not None else 0)
