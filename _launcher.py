"""Inicialização dos atalhos sem importar dependências externas antes da .venv."""

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re
import subprocess
import sys
import traceback


def _console_process_names():
    """Retorna somente os executáveis ligados ao console atual, quando disponível."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetConsoleProcessList.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
    kernel.GetConsoleProcessList.restype = wintypes.DWORD
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    capacity = 16
    while True:
        ids = (wintypes.DWORD * capacity)()
        count = kernel.GetConsoleProcessList(ids, capacity)
        if not count:
            return []
        if count <= capacity:
            break
        capacity = count
    names = []
    for pid in ids[:count]:
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return []
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return []
            names.append(Path(buffer.value).name.casefold())
        finally:
            kernel.CloseHandle(handle)
    return names


def _owns_python_console():
    if os.name != "nt" or os.environ.get("AGENTSCLOUD_NO_PAUSE") == "1":
        return False
    if os.environ.get("AGENTSCLOUD_CMD_WRAPPER") == "1" or os.environ.get("AGENTSCLOUD_WRAPPER_CHILD") == "1":
        return False
    if not sys.stdin or not sys.stdout or not sys.stdin.isatty() or not sys.stdout.isatty():
        return False
    try:
        names = _console_process_names()
        # py.exe e o redirecionador de .venv também permanecem ligados ao console.
        return bool(names) and all(re.fullmatch(r"(?:py|python(?:\d+(?:\.\d+)*)?)\.exe", name) for name in names)
    except (OSError, AttributeError):
        return False


def _wait_for_close():
    try:
        input("\nPressione Enter para fechar esta janela...")
    except (EOFError, KeyboardInterrupt):
        pass


def _preparation_error(root, message):
    print(f"Erro ao iniciar AgentsCloud: {message}", file=sys.stderr)
    print(f"Pasta do projeto: {root}", file=sys.stderr)
    print("Abra um terminal nessa pasta e execute: uv sync --locked", file=sys.stderr)
    print("Depois tente novamente. Nao e necessario instalar Questionary no Python global.", file=sys.stderr)


def _run(command, wrapper, arguments):
    root = wrapper.resolve().parent
    venv = root / ".venv"
    interpreter = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if interpreter.is_file() and Path(sys.prefix).resolve() != venv.resolve():
        if os.environ.get("AGENTSCLOUD_WRAPPER_CHILD") == "1":
            _preparation_error(root, "o Python iniciado nao reconheceu a .venv; repare o ambiente local.")
            return 1
        environment = dict(os.environ)
        environment["AGENTSCLOUD_WRAPPER_CHILD"] = "1"
        try:
            return subprocess.run([str(interpreter), str(wrapper.resolve()), *arguments],
                                  env=environment, check=False).returncode
        except OSError as exc:
            _preparation_error(root, f"o Python da .venv nao pode ser executado: {exc}")
            return 1
    if sys.version_info < (3, 11):
        _preparation_error(root, "Python 3.11 ou superior e necessario.")
        return 1
    sys.path.insert(0, str(root / "src"))
    try:
        from agentscloud.cli import main
    except (ModuleNotFoundError, ImportError) as exc:
        _preparation_error(root, f"dependencia indisponivel neste interpretador: {exc}")
        return 1
    return main([command, *arguments], default_repo=root)


def launch(command, wrapper, arguments=None):
    """Preserva argumentos/código da CLI; pausa apenas no console próprio dos .py."""
    own_console = _owns_python_console()
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    try:
        try:
            return _run(command, Path(wrapper), arguments)
        except SystemExit as exc:
            if exc.code is None:
                return 0
            if isinstance(exc.code, int):
                return exc.code
            print(exc.code, file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            return 130
        except Exception:
            traceback.print_exc()
            return 1
    finally:
        if own_console:
            _wait_for_close()
