"""Diagnóstico independente; não faz pull nem prepara dependências automaticamente."""

from pathlib import Path
import sys

sys.dont_write_bytecode = True
from _launcher import _owns_python_console, _wait_for_close


def launch(arguments=None):
    own_console = _owns_python_console()
    try:
        if sys.version_info < (3, 11):
            print("Python 3.11 ou superior é necessário. Execute diagnostico.cmd ou instale um Python atualizado.", file=sys.stderr)
            return 1
        root = Path(__file__).resolve().parent
        sys.path.insert(0, str(root / "src"))
        from agentscloud.diagnostics import main
        try:
            return main(arguments, default_repo=root)
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        except KeyboardInterrupt:
            return 130
    finally:
        if own_console:
            _wait_for_close()


if __name__ == "__main__":
    raise SystemExit(launch())
