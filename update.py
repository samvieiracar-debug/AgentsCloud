"""Atalho: prepara clone e .venv antes de update [--repo CAMINHO]."""

from pathlib import Path
import sys

# Ajuda/parser não devem criar bytecode no clone.
sys.dont_write_bytecode = True
from _launcher import launch

if __name__ == "__main__":
    raise SystemExit(launch("update", Path(__file__)))
