"""Repository-local alternative to the installed `ut61e` console command."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ut61e_toolkit.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
