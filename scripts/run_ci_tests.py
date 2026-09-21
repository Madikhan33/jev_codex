"""Run the offline suite and expose failed test names in GitHub annotations."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    suite = unittest.defaultTestLoader.discover("tests")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    for test, traceback in [*result.failures, *result.errors]:
        name = str(test).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        detail = traceback.strip().splitlines()[-1]
        detail = detail.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::error title={name}::{detail}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
