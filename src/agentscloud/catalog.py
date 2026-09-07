"""Catálogo gerenciado e índice Markdown derivado dos TOMLs."""

from dataclasses import dataclass, field
import json
from pathlib import Path
import tomllib

from .agents import Agent, check_unique, ensure_not_link, parse_agent, validate_filename
from .errors import AgentsCloudError

START = "<!-- agentscloud:index:start -->"
END = "<!-- agentscloud:index:end -->"


@dataclass(frozen=True)
class Catalog:
    categories: dict[str, str]
    maintainers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Bundle:
    agents: list[Agent]
    categories: dict[str, str]
    maintainers: dict[str, str] = field(default_factory=dict)


def valid_label(value: object, label: str) -> str:
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value.splitlines()) != 1
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise AgentsCloudError(f"{label} deve ser texto não vazio, em uma linha, sem espaços nas bordas.")
    return value


def valid_category(value: object) -> str:
    return valid_label(value, "Categoria")


def valid_maintainer(value: object) -> str:
    return valid_label(value, "Responsável (maintainer)")


def parse_catalog(content: bytes) -> Catalog:
    try:
        data = tomllib.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise AgentsCloudError(f"catalog.toml inválido: {exc}") from exc
    if set(data) != {"agents"} or not isinstance(data["agents"], list):
        raise AgentsCloudError("catalog.toml deve conter somente a lista [[agents]] (file, category e maintainer opcional).")
    categories: dict[str, str] = {}
    maintainers: dict[str, str] = {}
    folded: set[str] = set()
    for row in data["agents"]:
        if (not isinstance(row, dict) or not {"file", "category"}.issubset(row)
                or set(row) - {"file", "category", "maintainer"}):
            raise AgentsCloudError("Cada entrada [[agents]] exige file e category; somente maintainer é opcional.")
        filename = row["file"]
        if not isinstance(filename, str):
            raise AgentsCloudError("file no catálogo deve ser uma string.")
        validate_filename(filename)
        if filename.casefold() in folded:
            raise AgentsCloudError(f"Arquivo duplicado no catálogo: {filename}")
        folded.add(filename.casefold())
        categories[filename] = valid_category(row["category"])
        if "maintainer" in row:
            maintainers[filename] = valid_maintainer(row["maintainer"])
    return Catalog(categories, maintainers)


def make_bundle(files: dict[str, bytes], catalog_content: bytes) -> Bundle:
    catalog = parse_catalog(catalog_content)
    categories = catalog.categories
    if set(files) != set(categories):
        missing = sorted(set(categories) - set(files))
        extra = sorted(set(files) - set(categories))
        raise AgentsCloudError(f"Catálogo inconsistente. Arquivos ausentes: {missing}; sem categoria: {extra}.")
    agents = [parse_agent(name, content) for name, content in sorted(files.items())]
    check_unique(agents)
    return Bundle(agents, categories, catalog.maintainers)


def load_bundle(root: Path) -> Bundle:
    folder = root / "Agents"
    catalog = root / "catalog.toml"
    ensure_not_link(folder)
    ensure_not_link(catalog)
    if not catalog.is_file():
        raise AgentsCloudError(f"catalog.toml ausente em {root}.")
    if folder.exists() and not folder.is_dir():
        raise AgentsCloudError(f"Agents/ deve ser um diretório: {folder}")
    # Git não mantém diretórios vazios; um catálogo vazio pode não ter Agents/.
    files = {}
    for path in sorted(folder.iterdir()) if folder.exists() else []:
        if path.suffix.lower() == ".toml":
            ensure_not_link(path)
            if not path.is_file():
                raise AgentsCloudError(f"Esperado arquivo TOML regular: {path}")
            files[path.name] = path.read_bytes()
        elif path.is_dir():
            raise AgentsCloudError(f"Agents/ deve ser plano; subpasta encontrada: {path.name}")
    return make_bundle(files, catalog.read_bytes())


def serialize_catalog(categories: dict[str, str], maintainers: dict[str, str] | None = None) -> bytes:
    maintainers = {} if maintainers is None else maintainers
    if set(maintainers) - set(categories):
        raise AgentsCloudError("Responsável informado para arquivo ausente do catálogo.")
    if not categories:
        return b"agents = []\n"
    rows = []
    for filename in sorted(categories, key=str.casefold):
        validate_filename(filename)
        category = valid_category(categories[filename])
        row = (f"[[agents]]\nfile = {json.dumps(filename, ensure_ascii=False)}\n"
               f"category = {json.dumps(category, ensure_ascii=False)}\n")
        if filename in maintainers:
            maintainer = valid_maintainer(maintainers[filename])
            row += f"maintainer = {json.dumps(maintainer, ensure_ascii=False)}\n"
        rows.append(row)
    return ("\n".join(rows)).encode("utf-8")


def markdown(value: str) -> str:
    return (value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\\", "&#92;").replace("|", "&#124;").replace(chr(96), "&#96;")
            .replace("[", "&#91;").replace("]", "&#93;").replace("*", "&#42;")
            .replace("_", "&#95;").replace("\r", " ").replace("\n", " "))


def render_index(bundle: Bundle) -> str:
    sections = []
    show_maintainer = bool(bundle.maintainers)
    for category in sorted(set(bundle.categories.values()), key=str.casefold):
        header = "| Nome | Sintaxe | Categoria | Descrição |"
        separator = "| --- | --- | --- | --- |"
        if show_maintainer:
            header += " Responsável |"
            separator += " --- |"
        lines = [f"### {markdown(category)}", "", header, separator]
        members = [a for a in bundle.agents if bundle.categories[a.file] == category]
        for agent in sorted(members, key=lambda item: item.name.casefold()):
            row = (f"| [{markdown(agent.name)}](Agents/{agent.file}) | "
                   f"Use o agente {markdown(agent.name)} para … | {markdown(category)} | "
                   f"{markdown(agent.description)} |")
            if show_maintainer:
                maintainer = bundle.maintainers.get(agent.file, "Não informado")
                row += f" {markdown(maintainer)} |"
            lines.append(row)
        sections.append("\n".join(lines))
    return "\n\n".join(sections) if sections else "Nenhum agente cadastrado."


def updated_readme(content: bytes, bundle: Bundle) -> bytes:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AgentsCloudError("README.md deve ser UTF-8.") from exc
    if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
        raise AgentsCloudError("README.md deve conter um único par de marcadores agentscloud:index.")
    before, tail = text.split(START)
    _, after = tail.split(END)
    newline = "\r\n" if "\r\n" in text else "\n"
    generated = render_index(bundle).replace("\n", newline)
    return f"{before}{START}{newline}{newline}{generated}{newline}{newline}{END}{after}".encode("utf-8")


def read_readme(root: Path) -> bytes:
    path = root / "README.md"
    ensure_not_link(path)
    if not path.is_file():
        raise AgentsCloudError(f"README.md ausente: {root}")
    return path.read_bytes()
