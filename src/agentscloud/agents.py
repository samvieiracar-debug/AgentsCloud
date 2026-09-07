"""Validação compartilhada; arquivos de agentes são copiados sem reserialização."""

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib

from .errors import AgentsCloudError

PORTABLE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
RESERVED_FILES = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])\Z", re.I)


@dataclass(frozen=True)
class Agent:
    file: str
    name: str
    description: str
    content: bytes


def validate_filename(filename: str) -> None:
    path = Path(filename)
    if (path.name != filename or "/" in filename or "\\" in filename
            or path.suffix.lower() != ".toml"
            or not PORTABLE_NAME.fullmatch(path.stem)
            or RESERVED_FILES.fullmatch(path.stem)):
        raise AgentsCloudError(
            f"Nome de arquivo inválido: {filename!r}. Use letras ASCII, números, "
            "hífen ou underscore e extensão .toml; evite nomes reservados do Windows."
        )


def ensure_not_link(path: Path) -> None:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise AgentsCloudError(f"Links simbólicos/junções não são aceitos: {path}")
    if path.exists() and hasattr(path.lstat(), "st_file_attributes"):
        import stat
        if path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise AgentsCloudError(f"Ponto de redirecionamento não aceito: {path}")


def parse_agent(filename: str, content: bytes) -> Agent:
    validate_filename(filename)
    try:
        data = tomllib.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise AgentsCloudError(f"TOML inválido em {filename}: {exc}") from exc
    for field in ("name", "description", "developer_instructions"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise AgentsCloudError(f"{filename}: {field} deve ser uma string não vazia.")
    if not PORTABLE_NAME.fullmatch(data["name"]):
        raise AgentsCloudError(
            f"{filename}: name não segue a convenção portátil do AgentsCloud "
            "(letras ASCII, números, hífen ou underscore, começando por letra/número)."
        )
    return Agent(filename, data["name"], data["description"], content)


def read_agent(path: Path) -> Agent:
    ensure_not_link(path)
    if not path.is_file():
        raise AgentsCloudError(f"Arquivo de agente não encontrado: {path}")
    return parse_agent(path.name, path.read_bytes())


def check_unique(agents: list[Agent]) -> None:
    names: set[str] = set()
    files: set[str] = set()
    for agent in agents:
        if agent.name.casefold() in names or agent.file.casefold() in files:
            raise AgentsCloudError(f"Esse nome está indisponível: {agent.name} ({agent.file}).")
        names.add(agent.name.casefold())
        files.add(agent.file.casefold())


def conflicts(candidate: Agent, agents: list[Agent]) -> list[Agent]:
    return [a for a in agents if a.name.casefold() == candidate.name.casefold()
            or a.file.casefold() == candidate.file.casefold()]
