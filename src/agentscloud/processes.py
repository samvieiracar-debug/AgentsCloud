"""Runner stdlib: timeout da árvore própria, diagnóstico sanitizado e logs limitados."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import codecs
import sys
import threading
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4


LOCAL_TIMEOUT = 10
NETWORK_TIMEOUT = 30
INTERACTIVE_NETWORK_TIMEOUT = 180
SYNC_TIMEOUT = 300
PUSH_TIMEOUT = 180


def sanitize(value, limit=4000):
    text = str(value)
    # Não preservar userinfo/query/fragmento de URLs.
    def url(match):
        raw = match.group(0)
        try:
            parts = urlsplit(raw)
            host = parts.hostname or ""
            if parts.port:
                host += ":" + str(parts.port)
            return urlunsplit((parts.scheme, host, parts.path, "", ""))
        except ValueError:
            return "[URL omitida]"
    text = re.sub(r"(?:https?|ssh)://[^\s<>\"']+", url, text, flags=re.I)
    text = re.sub(r"(?im)(authorization|proxy-authorization|cookie|set-cookie|extraheader)\s*[:=][^\r\n]*",
                  r"\1: [omitido]", text)
    text = re.sub(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9+/_.=-]+", "[credencial omitida]", text)
    text = re.sub(r"(?i)\b(password|passwd|token|secret|access_token|api[_-]?key)\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
                  r"\1=[omitido]", text)
    text = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)\b", "[token omitido]", text)
    # Elimina controle de terminal, preservando quebras/abas.
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]|[\x00-\x08\x0b-\x1f\x7f]", "", text)
    return text[:limit] + (" … [limitado]" if len(text) > limit else "")


def classify(returncode, message="", *, timed_out=False, missing=False):
    if missing:
        return "ferramenta_ausente"
    if timed_out:
        return "timeout"
    if returncode == 0:
        return "ok"
    text = message.casefold()
    if any(t in text for t in ("authentication failed", "could not read username", "terminal prompts disabled",
                               "invalid username or password", "permission denied (publickey)")):
        return "autenticacao"
    if any(t in text for t in ("non-fast-forward", "fetch first", "not possible to fast-forward")):
        return "divergencia"
    if any(t in text for t in ("hook declined", "protected branch", "pre-receive hook", "403", "permission denied")):
        return "permissao_ou_politica"
    if any(t in text for t in ("could not resolve", "unable to access", "connection refused",
                               "connection timed out", "ssl certificate", "host key verification")):
        return "conexao"
    return "indeterminado"


class EventLog:
    """JSONL com campos permitidos; nenhuma URL, argv, ambiente ou saída de processo."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.run_id = uuid4().hex
        self.warned = False

    @property
    def path(self):
        return self.directory / "events.jsonl"

    def write(self, operation, *, returncode=None, category=None, duration=None, commit=None, ref=None, outcome=None):
        event = {"time": datetime.now(timezone.utc).isoformat(), "run": self.run_id,
                 "operation": sanitize(operation, 80)}
        for key, value in (("returncode", returncode), ("category", category), ("duration", duration),
                           ("commit", commit), ("ref", ref), ("outcome", outcome)):
            if value is not None:
                if key == "commit" and not re.fullmatch(r"[a-fA-F0-9]{40,64}", str(value)):
                    continue
                event[key] = sanitize(value, 200) if isinstance(value, str) else value
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size >= 128 * 1024:
                previous = self.directory / "events.previous.jsonl"
                self.path.replace(previous)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            return True
        except OSError:
            if not self.warned:
                print("Aviso: não foi possível gravar o log local. A operação e os commits serão preservados.", file=sys.stderr)
                self.warned = True
            return False

    def recent(self, count=20):
        try:
            # Não ler um arquivo arbitrariamente grande alterado externamente.
            with self.path.open("rb") as stream:
                stream.seek(max(0, self.path.stat().st_size - 64 * 1024))
                lines = stream.read().splitlines()
            result = []
            for line in lines[-min(count, 50):]:
                try:
                    event = json.loads(line)
                    allowed = {"time", "run", "operation", "returncode", "category", "duration", "commit", "ref", "outcome"}
                    result.append({key: sanitize(value, 200) for key, value in event.items() if key in allowed})
                except (ValueError, AttributeError):
                    continue
            return result
        except OSError:
            return []


@dataclass
class CommandResult:
    returncode: int
    stdout: bytes = b""
    stderr: bytes = b""
    category: str = "ok"
    duration: float = 0
    timed_out: bool = False

    @property
    def message(self):
        return sanitize((self.stderr or self.stdout).decode("utf-8", errors="replace"))


def git_environment(environment=None):
    """--repo fixa o alvo; o ambiente herdado não pode trocar gitdir/índice/refs."""
    env = dict(os.environ if environment is None else environment)
    redirects = {
        "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_NAMESPACE", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
        "GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM",
    }
    for key in list(env):
        normalized = key.upper()
        if normalized in redirects or normalized.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
            env.pop(key)
    return env


def noninteractive_env(environment=None):
    env = git_environment(environment)
    env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never", GIT_OPTIONAL_LOCKS="0")
    # Terminal desabilitado sozinho ainda permite GIT_ASKPASS/core.askPass.
    env.update(GIT_ASKPASS="", SSH_ASKPASS="", SSH_ASKPASS_REQUIRE="never",
               GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.askPass", GIT_CONFIG_VALUE_0="")
    # Sondagens não abrem login ou aceitam novas chaves de host automaticamente.
    env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10"
    return env


def project_environment(root, environment=None):
    env = git_environment(environment)
    for name in ("VIRTUAL_ENV", "UV_PROJECT", "UV_WORKING_DIR", "UV_WORKING_DIRECTORY"):
        env.pop(name, None)
    env["UV_PROJECT_ENVIRONMENT"] = str(Path(root).resolve() / ".venv")
    return env


class _WindowsJob:
    """Job privado: fechar o handle encerra somente os processos associados."""
    def __init__(self, process):
        self.handle = None
        if os.name != "nt":
            return
        import ctypes
        from ctypes import wintypes
        class BASIC(ctypes.Structure):
            _fields_ = [("ProcessTime", ctypes.c_int64), ("JobTime", ctypes.c_int64),
                        ("Flags", wintypes.DWORD), ("MinWorkingSet", ctypes.c_size_t),
                        ("MaxWorkingSet", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("Priority", wintypes.DWORD), ("Scheduling", wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOps", "WriteOps", "OtherOps", "Read", "Write", "Other")]
        class LIMITS(ctypes.Structure):
            _fields_ = [("Basic", BASIC), ("Io", IO), ("ProcessMemory", ctypes.c_size_t),
                        ("JobMemory", ctypes.c_size_t), ("PeakProcess", ctypes.c_size_t), ("PeakJob", ctypes.c_size_t)]
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = self.kernel.CreateJobObjectW(None, None)
        limits = LIMITS()
        limits.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if handle and self.kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            if self.kernel.AssignProcessToJobObject(handle, wintypes.HANDLE(int(process._handle))):
                self.handle = handle
                return
        if handle:
            self.kernel.CloseHandle(handle)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def _stop_tree(process, job):
    if os.name == "nt":
        if job.handle:
            job.close()
        else:
            taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/taskkill.exe"
            try:
                subprocess.run([str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass



def _interactive_output(process, job, timeout):
    """Exibe linhas e prompts completos durante a execução; não persiste sua saída."""
    chunks = [[], []]
    lock = threading.Lock()

    def consume(pipe, channel, index):
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        pending = ""
        def emit(text):
            with lock:
                channel.write(sanitize(text, 65536))
                channel.flush()
        while True:
            data = pipe.read1(4096)
            if not data:
                pending += decoder.decode(b"", final=True)
                if pending:
                    emit(pending)
                return
            chunks[index].append(data)
            pending += decoder.decode(data)
            while "\n" in pending:
                line, pending = pending.split("\n", 1)
                emit(line + "\n")
            # Git username/password prompts terminate with ': ' without a newline.
            # Do not stream arbitrary split tokens/URLs before their boundary.
            if pending.endswith((": ", "? ", "] ")) and re.search(r"(?i)\b(username|password|passphrase|enter|press|digite|senha)\b", pending):
                emit(pending)
                pending = ""
            elif len(pending) > 65536:
                emit("[saída sem quebra de linha omitida]\n")
                pending = ""

    readers = [threading.Thread(target=consume, args=(process.stdout, sys.stdout, 0), daemon=True),
               threading.Thread(target=consume, args=(process.stderr, sys.stderr, 1), daemon=True)]
    for reader in readers:
        reader.start()
    timed_out = False
    try:
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _stop_tree(process, job)
            process.wait(timeout=5)
        except KeyboardInterrupt:
            _stop_tree(process, job)
            process.wait(timeout=5)
            raise
    finally:
        job.close()
        for reader in readers:
            reader.join(timeout=5)
    return b"".join(chunks[0]), b"".join(chunks[1]), timed_out


def run_command(argv, *, cwd=None, timeout=LOCAL_TIMEOUT, env=None, interactive=False, operation="command", log=None, expected_codes=(0,), input_bytes=None):
    """Captura bytes para consumidores internos; só message/sanitize podem ir ao console."""
    started = time.monotonic()
    if interactive and input_bytes is not None:
        raise ValueError("Entrada explícita requer comando sem interação.")
    environment = git_environment(env)
    if not interactive:
        environment = noninteractive_env(environment)
    process = None
    job = None
    input_stream = None
    try:
        if input_bytes is not None:
            # Um pipe escrito sincronamente por communicate no Windows pode
            # bloquear antes de aplicar timeout se o filho não consumir stdin.
            input_stream = tempfile.TemporaryFile()
            input_stream.write(input_bytes)
            input_stream.seek(0)
        process = subprocess.Popen(
            [str(part) for part in argv], cwd=cwd, env=environment,
            stdin=input_stream if input_stream is not None else (None if interactive else subprocess.DEVNULL),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        job = _WindowsJob(process)
        timed_out = False
        if interactive:
            stdout, stderr, timed_out = _interactive_output(process, job, timeout)
        else:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                _stop_tree(process, job)
                stdout, stderr = process.communicate(timeout=5)
        code = 124 if timed_out else process.returncode
        result = CommandResult(code, stdout, stderr,
                               classify(code, stderr.decode("utf-8", errors="replace"), timed_out=timed_out),
                               round(time.monotonic() - started, 3), timed_out)
    except FileNotFoundError as exc:
        result = CommandResult(127, stderr=str(exc).encode("utf-8"), category="ferramenta_ausente")
    except KeyboardInterrupt:
        if process is not None and process.poll() is None:
            _stop_tree(process, job)
            process.wait(timeout=5)
        if log:
            log.write(operation, returncode=130, category="cancelado", duration=round(time.monotonic()-started, 3))
        raise
    except (OSError, subprocess.TimeoutExpired) as exc:
        if process is not None and process.poll() is None:
            _stop_tree(process, job)
        result = CommandResult(1, stderr=str(exc).encode("utf-8"), category="indeterminado")
    finally:
        if input_stream is not None:
            input_stream.close()
        if job is not None:
            job.close()
        if process is not None:
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe is not None and not pipe.closed:
                    pipe.close()
    if result.returncode in expected_codes and result.returncode != 0:
        result.category = "esperado"
    if log:
        log.write(operation, returncode=result.returncode, category=result.category, duration=result.duration)
    return result
