"""One-command installer. Python 3.11+ and internet access are required."""

import sys

if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11 or newer is required.")

from jev_router.installer import main

if __name__ == "__main__":
    raise SystemExit(main())
