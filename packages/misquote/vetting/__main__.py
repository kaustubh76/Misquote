"""`python -m misquote.vetting` — badge the pools this marketplace lists."""

from __future__ import annotations

import sys

from misquote.vetting.read import main

if __name__ == "__main__":
    sys.exit(main())
