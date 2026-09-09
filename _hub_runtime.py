"""Entrada isolada do hub: usa o código e a .venv da pasta deste arquivo."""

from pathlib import Path
import sys


def run(arguments=None):
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    root = Path(__file__).resolve().parent
    if Path(sys.prefix).resolve() != (root / ".venv").resolve():
        print("O hub precisa da .venv da própria pasta. Execute hub.cmd ou python hub.py.", file=sys.stderr)
        return 1
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if len(arguments) != 1:
        print("Entrada interna do hub inválida. Execute hub.cmd ou python hub.py.", file=sys.stderr)
        return 2
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root / "src"))
    try:
        from agentscloud.hub import run_hub
    except ImportError as exc:
        print(f"Dependências do hub ausentes ou incompatíveis: {exc}. "
              f"Na pasta {root}, execute uv sync --locked. "
              "O diagnóstico independente continua disponível em diagnostico.cmd "
              "ou python diagnostico.py.", file=sys.stderr)
        return 1
    return run_hub(Path(arguments[0]).expanduser().resolve())


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except (KeyboardInterrupt, EOFError):
        raise SystemExit(130)
