"""Entry point for ``python -m sentinel.agent``.

The package previously had no ``__main__`` module, so the documented command
could not run. All logic lives in :mod:`sentinel.agent.runner`; this only
exposes it as an executable module.
"""

from __future__ import annotations

import sys

from .runner import main

if __name__ == "__main__":
    sys.exit(main())
