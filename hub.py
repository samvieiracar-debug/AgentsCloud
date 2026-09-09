"""Abre a central com a .venv local, sem sincronização ou preparação automática."""

import os
from pathlib import Path
import runpy
import subprocess
import sys

sys.dont_write_bytecode = True
from _launcher import _owns_python_console, _wait_for_close


def _preparation_message(root):
    return (f"Prepare o ambiente na pasta {root} com: uv sync --locked. "
            "Para verificar problemas sem as dependências do hub, execute diagnostico.cmd "
            "ou python diagnostico.py nessa pasta.")


def _run(root, arguments):
    if sys.version_info < (3, 11):
        print("Python 3.11 ou superior é necessário para abrir o hub.", file=sys.stderr)
        return 1
    # Ajuda e argumentos inválidos terminam aqui, sem importar pacote ou dependências.
    parser = runpy.run_path(str(root / "src/agentscloud/arguments.py"))["build_parser"]
    args = parser(root).parse_args(["hub", *arguments])
    data_root = args.repo.expanduser().resolve()
    environment_root = root / ".venv"
    interpreter = environment_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if environment_root.resolve() != environment_root or not interpreter.is_file():
        print("A .venv local do hub está ausente ou aponta para outra pasta. "
              + _preparation_message(root), file=sys.stderr)
        return 1
    runtime = root / "_hub_runtime.py"
    if not runtime.is_file():
        print("Clone incompleto: falta _hub_runtime.py. Restaure o arquivo do projeto.", file=sys.stderr)
        return 1
    environment = dict(os.environ)
    environment["VIRTUAL_ENV"] = str(environment_root)
    environment["AGENTSCLOUD_WRAPPER_CHILD"] = "1"
    result = subprocess.run(
        [str(interpreter), "-I", "-B", str(runtime), str(data_root)],
        env=environment, check=False,
    )
    return result.returncode if result.returncode >= 0 else 130


def launch(arguments=None):
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    root = Path(__file__).resolve().parent
    own_console = _owns_python_console()
    try:
        try:
            return _run(root, list(sys.argv[1:] if arguments is None else arguments))
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        except (KeyboardInterrupt, EOFError):
            return 130
        except OSError as exc:
            print(f"Não foi possível abrir o hub: {exc}. {_preparation_message(root)}", file=sys.stderr)
            return 1
    finally:
        if own_console:
            _wait_for_close()


if __name__ == "__main__":
    raise SystemExit(launch())
