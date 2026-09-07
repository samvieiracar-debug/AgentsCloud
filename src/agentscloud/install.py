"""Destino pessoal, scan e instalação com consentimento e backups."""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Callable, Mapping
from uuid import uuid4

from .agents import Agent, check_unique, conflicts, ensure_not_link, read_agent
from .errors import AgentsCloudError


def codex_home(environ: Mapping[str, str] | None = None, home: Path | None = None) -> Path:
    env = os.environ if environ is None else environ
    value = env.get("CODEX_HOME")
    if value is not None:
        if not value.strip():
            raise AgentsCloudError("CODEX_HOME está vazio. Defina um diretório ou remova a variável.")
        return Path(value).expanduser().absolute()
    return (Path.home() if home is None else home) / ".codex"


def personal_folder(root: Path) -> Path:
    ensure_not_link(root)
    folder = root / "agents"
    ensure_not_link(folder)
    if folder.exists() and not folder.is_dir():
        raise AgentsCloudError(f"O destino não é um diretório: {folder}")
    return folder


@dataclass(frozen=True)
class Scan:
    candidates: list[Agent]
    skipped: list[str]


def scan_personal(root: Path, occupied: list[Agent]) -> Scan:
    folder = personal_folder(root)
    if not folder.exists():
        return Scan([], [f"Pasta não encontrada: {folder}"])
    candidates: list[Agent] = []
    skipped: list[str] = []
    found: list[Agent] = []
    for path in sorted(folder.iterdir(), key=lambda p: p.name.casefold()):
        if path.suffix.lower() != ".toml":
            continue
        try:
            found.append(read_agent(path))
        except (AgentsCloudError, OSError) as exc:
            skipped.append(f"Ignorado {path.name}: {exc}")
    for candidate in found:
        if conflicts(candidate, occupied):
            skipped.append(f"Esse nome está indisponível: {candidate.name} ({candidate.file}).")
        elif len(conflicts(candidate, found)) > 1:
            skipped.append(f"Nome duplicado entre agentes pessoais: {candidate.name} ({candidate.file}).")
        else:
            candidates.append(candidate)
    return Scan(candidates, skipped)


def write_atomic(path: Path, content: bytes) -> None:
    ensure_not_link(path)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def install_agents(agents: list[Agent], root: Path, confirm: Callable[[str], bool],
                   emit: Callable[[str], None]) -> dict[str, int]:
    """Chamada somente depois da confirmação geral do destino pelo comando."""
    folder = personal_folder(root)
    existing = []
    if folder.exists():
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() == ".toml":
                existing.append(read_agent(path))
    check_unique(existing)
    check_unique(agents)
    folder.mkdir(parents=True, exist_ok=True)
    stats = {"installed": 0, "unchanged": 0, "skipped": 0}
    for agent in agents:
        collisions = conflicts(agent, existing)
        if (len(collisions) == 1 and collisions[0].file == agent.file
                and collisions[0].content == agent.content):
            emit(f"Já instalado, preservado: {agent.file}")
            stats["unchanged"] += 1
            continue
        if collisions:
            names = ", ".join(item.file for item in collisions)
            if not confirm(f"Conflito com {names}. Substituir por {agent.file}, criando backup?"):
                emit(f"Preservado por escolha do usuário: {names}")
                stats["skipped"] += 1
                continue
            # Reconfere os bytes antes de qualquer substituição.
            for old in collisions:
                current = read_agent(folder / old.file)
                if current.content != old.content:
                    raise AgentsCloudError(f"{old.file} mudou durante a confirmação. Instalação interrompida.")
            for old in collisions:
                backup = folder / f"{old.file}.bak-{uuid4().hex}"
                with backup.open("xb") as handle:
                    handle.write(old.content)
                emit(f"Backup: {backup}")
            target = folder / agent.file
            write_atomic(target, agent.content)
            for old in collisions:
                old_path = folder / old.file
                # No Windows, grafias diferentes podem apontar ao mesmo arquivo.
                if old_path != target and old_path.exists() and not old_path.samefile(target):
                    old_path.unlink()
            existing = [item for item in existing if item not in collisions]
        else:
            with (folder / agent.file).open("xb") as handle:
                handle.write(agent.content)
        existing.append(agent)
        emit(f"Instalado: {agent.file}")
        stats["installed"] += 1
    return stats
