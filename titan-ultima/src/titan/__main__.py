"""Allow running the package directly: ``python -m titan``."""

import sys

from .cli import main

exit_code = main()
sys.exit(exit_code if exit_code is not None else 0)
