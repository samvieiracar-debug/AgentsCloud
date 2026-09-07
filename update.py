"""Atalho: python update.py [--repo CAMINHO]."""

from pathlib import Path
from _launcher import launch

if __name__ == "__main__":
    raise SystemExit(launch("update", Path(__file__)))
