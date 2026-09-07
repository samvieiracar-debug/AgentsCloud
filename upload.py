"""Atalho: python upload.py [--repo CAMINHO]."""

from pathlib import Path
from _launcher import launch

if __name__ == "__main__":
    raise SystemExit(launch("upload", Path(__file__)))
