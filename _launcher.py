"""Inicialização dos atalhos sem importar dependências externas antes da .venv."""

import ctypes
from ctypes import wintypes
import os
import json
import runpy
import shutil
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


_PROCESS = None
_LOG = None


class PreparationError(Exception):
    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code if code > 0 else 130


def _git(root, *arguments):
    interactive = arguments[0] in ("pull", "fetch")
    timeout = _PROCESS["INTERACTIVE_NETWORK_TIMEOUT"] if interactive else _PROCESS["LOCAL_TIMEOUT"]
    result = _PROCESS["run_command"](
        [shutil.which("git") or "git", "-C", str(root), *arguments], cwd=root,
        timeout=timeout, interactive=interactive,
        operation="bootstrap-git-" + arguments[0], log=_LOG,
    )
    if result.returncode:
        raise PreparationError(f"git {arguments[0]} falhou [{result.category}]: {result.message}", result.returncode)
    return result.stdout.decode("utf-8", errors="replace").strip()


def _clean(root):
    if _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise PreparationError("Checkout/índice não está limpo (incluindo arquivos não rastreados). "
                               "Salve ou resolva suas alterações antes de tentar novamente.")


def _identity(root):
    try:
        head = _git(root, "rev-parse", "--verify", "HEAD^{commit}")
    except PreparationError as exc:
        raise PreparationError("O repositório não tem commit inicial.", exc.code) from exc
    try:
        branch = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
        remote = _git(root, "config", "--get", f"branch.{branch}.remote")
        branch_ref = _git(root, "config", "--get", f"branch.{branch}.merge")
    except PreparationError as exc:
        raise PreparationError("Branch sem upstream configurado ou HEAD destacado. "
                               "Configure o rastreamento da branch da equipe.", exc.code) from exc
    if not remote or remote == "." or not branch_ref.startswith("refs/heads/"):
        raise PreparationError("Upstream deve apontar para uma branch em um remoto Git configurado.")
    _git(root, "remote", "get-url", "--", remote)
    return dict(head=head, branch=branch, remote=remote, branch_ref=branch_ref)


def _structure(root, *, after_pull=False):
    required = ("pyproject.toml", "uv.lock", "src/agentscloud/cli.py", "catalog.toml", "README.md")
    if after_pull:
        required += ("_runtime.py", "src/agentscloud/arguments.py", "src/agentscloud/prepared.py", "src/agentscloud/processes.py")
    for filename in required:
        if not (root / filename).is_file():
            raise PreparationError(f"Alvo incompleto: falta {filename}. --repo exige um clone completo do AgentsCloud.")
    # O ambiente contratado deve estar fisicamente dentro deste clone.
    venv = root / ".venv"
    if venv.resolve() != venv:
        raise PreparationError("A .venv do alvo é um link/junção. Use um ambiente local ao clone.")


def _run(command, wrapper, arguments):
    global _PROCESS, _LOG
    default_root = wrapper.resolve().parent
    if sys.version_info < (3, 11):
        print(f"Erro ao iniciar AgentsCloud em {default_root}: Python 3.11 ou superior é necessário.", file=sys.stderr)
        return 1
    # Executa apenas o arquivo do parser, sem importar pacote, CLI ou Questionary.
    parser = runpy.run_path(str(default_root / "src/agentscloud/arguments.py"))["build_parser"]
    args = parser(default_root).parse_args([command, *arguments])
    root = args.repo.expanduser().resolve()  # relativo ao cwd original do chamador
    _PROCESS = runpy.run_path(str(default_root / "src/agentscloud/processes.py"))
    _LOG = None
    phase, prepared = "pré-requisitos", None
    print(f"Preparando AgentsCloud em: {root}", flush=True)
    try:
        for tool in ("git", "uv"):
            if not shutil.which(tool):
                raise PreparationError(f"{tool} não encontrado. Instale {tool} e disponibilize-o no PATH; consulte README.md.")
        if Path(_git(root, "rev-parse", "--show-toplevel")).resolve() != root:
            raise PreparationError("--repo deve indicar a raiz Git do clone completo, não uma subpasta.")
        _structure(root)
        log_path = Path(_git(root, "rev-parse", "--git-path", "agentscloud/logs"))
        _LOG = _PROCESS["EventLog"](log_path if log_path.is_absolute() else root / log_path)
        _clean(root)
        initial = _identity(root)
        phase = "git pull"
        print("Atualizando clone: git pull --ff-only --no-rebase --no-autostash", flush=True)
        _git(root, "pull", "--ff-only", "--no-rebase", "--no-autostash",
             "--", initial["remote"], initial["branch_ref"])
        _clean(root)
        prepared = _identity(root)
        if any(prepared[key] != initial[key] for key in ("branch", "remote", "branch_ref")):
            raise PreparationError("Branch/upstream mudou durante o pull. Execute o atalho novamente.")
        remote_head = _git(root, "rev-parse", "--verify", "FETCH_HEAD^{commit}")
        if prepared["head"] != remote_head:
            try:
                _git(root, "merge-base", "--is-ancestor", remote_head, prepared["head"])
            except PreparationError as exc:
                raise PreparationError("Histórico divergente do upstream. Resolva manualmente; nenhum sync foi iniciado.", exc.code) from exc
            print("HEAD contém commits locais ainda não publicados. Upload oferecerá revisão das pendências.", flush=True)
        prepared["upstream_commit"] = remote_head
        _structure(root, after_pull=True)  # o pull pode mudar os arquivos do projeto
        phase = "uv sync --locked"
        print("Preparando dependências: uv sync --locked", flush=True)
        environment = _PROCESS["project_environment"](root)
        result = _PROCESS["run_command"](
            [shutil.which("uv"), "sync", "--locked", "--project", str(root), "--directory", str(root)],
            cwd=root, env=environment, timeout=_PROCESS["SYNC_TIMEOUT"], interactive=True,
            operation="bootstrap-sync", log=_LOG,
        )
        if result.returncode:
            raise PreparationError("uv sync --locked falhou; o fluxo não será iniciado.", result.returncode)
        _clean(root)
        if _identity(root) != {key: value for key, value in prepared.items() if key != "upstream_commit"}:
            raise PreparationError("HEAD/branch/upstream mudou durante o sync. Execute o atalho novamente.")
        interpreter = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not interpreter.is_file():
            raise PreparationError("uv não disponibilizou o Python da .venv do alvo.")
        phase = "runtime"
        environment["AGENTSCLOUD_WRAPPER_CHILD"] = "1"
        # A entrada interna não relança os wrappers e carrega o código novo do alvo.
        result = subprocess.run(
            [str(interpreter), "-I", "-B", str(root / "_runtime.py"), str(root),
             json.dumps(prepared), command, "--repo", str(root)],
            env=environment, check=False,  # preserva cwd para caminhos pessoais relativos
        )
        return result.returncode if result.returncode >= 0 else 130
    except (PreparationError, OSError) as exc:
        print(_PROCESS["sanitize"](f"Erro na fase {phase} em {root}: {exc}"), file=sys.stderr)
        if prepared is not None:
            print(f"O pull terminou; checkout preservado em {prepared['head']}. "
                  "O fluxo não foi concluído; execute o atalho novamente após corrigir a falha.", file=sys.stderr)
        if phase == "uv sync --locked":
            print("O ambiente não foi preparado. Se o Python desta .venv estiver em uso no Windows, "
                  "feche esses processos e repita pelo .cmd ou por um Python externo. "
                  "Não é necessário instalar Questionary globalmente.", file=sys.stderr)
        return exc.code if isinstance(exc, PreparationError) else 1


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
