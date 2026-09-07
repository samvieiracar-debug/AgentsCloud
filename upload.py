"""Atalho: python upload.py [--repo CAMINHO]."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from agentscloud.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["upload", *sys.argv[1:]], default_repo=Path(__file__).resolve().parent))
