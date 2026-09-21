"""Use the installed private runtime; JEV_ROUTER_FROM_SOURCE=1 uses this checkout."""

import os
import subprocess
import sys
from pathlib import Path

from jev_router.settings import codex_home

if __name__ == "__main__":
    root = codex_home() / "jev-router"
    if "--config" in sys.argv:
        position = sys.argv.index("--config")
        if position + 1 < len(sys.argv):
            root = Path(sys.argv[position + 1]).expanduser().resolve().parent
    python = root / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    entry = root / "app" / "entry.py"
    use_installed = (
        os.environ.get("JEV_ROUTER_FROM_SOURCE") != "1"
        and python.is_file()
        and entry.is_file()
        and (root / "manifest.json").is_file()
        and len(sys.argv) > 1
        and sys.argv[1] not in {"install", "uninstall"}
    )
    if use_installed:
        raise SystemExit(subprocess.call([str(python), "-I", str(entry), *sys.argv[1:]]))
    from jev_router.cli import main

    raise SystemExit(main())
