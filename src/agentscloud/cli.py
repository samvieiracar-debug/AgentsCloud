"""Comandos de catálogo, sincronização e contribuição."""

import argparse
from pathlib import Path
import sys

from .agents import conflicts, read_agent
from .catalog import Bundle, load_bundle, read_readme, serialize_catalog, updated_readme, valid_category, valid_maintainer
from .errors import AgentsCloudError, Cancelled
from .git import Repository
from .install import codex_home, install_agents, personal_folder, scan_personal, write_atomic
from .ui import TerminalUI


def assert_index(root: Path, bundle: Bundle) -> None:
    current = read_readme(root)
    if updated_readme(current, bundle) != current:
        raise AgentsCloudError("Índice README desatualizado. Execute agentscloud index e registre a alteração no Git.")


def update(root: Path, ui: TerminalUI) -> None:
    repo = Repository(root)
    initial_head = repo.head()
    upstream = repo.fetch_upstream()
    local = load_bundle(root)
    remote = repo.remote_bundle(upstream)
    assert_index(root, local)
    ui.emit(f"Remoto consultado: {upstream.remote}, {upstream.branch_ref} ({upstream.commit[:12]}).")
    ui.emit("Agentes disponíveis no remoto:")
    local_by_file = {item.file: item for item in local.agents}
    for agent in remote.agents:
        old = local_by_file.get(agent.file)
        state = "novo" if old is None else ("alterado" if old.content != agent.content else "já disponível")
        ui.emit(f"  {agent.name} | {agent.file} | {remote.categories[agent.file]} | {state}")
    for filename in sorted(set(local_by_file) - set(remote.categories)):
        ui.emit(f"  Removido do catálogo remoto: {filename} (a instalação pessoal será preservada).")
    if initial_head != upstream.commit:
        if not repo.is_ancestor(initial_head, upstream.commit):
            raise AgentsCloudError("Há commits locais ou divergência com o upstream. Resolva o histórico manualmente; nenhum merge foi feito.")
        if not ui.confirm("Deseja atualizar o repositório local por fast-forward?"):
            ui.emit("Atualização recusada. Checkout e agentes pessoais preservados.")
            return
        repo.fast_forward(upstream, initial_head)
        local = load_bundle(root)
        assert_index(root, local)
        ui.emit(f"Repositório atualizado para {repo.head()[:12]}.")
    else:
        ui.emit("Repositório já está atualizado.")
    destination = codex_home()
    folder = personal_folder(destination)
    if not ui.confirm(f"Deseja instalar {len(local.agents)} agente(s) em {folder}?"):
        ui.emit("Instalação recusada.")
        return
    stats = install_agents(local.agents, destination, ui.confirm, ui.emit)
    ui.emit(f"Instalação concluída: {stats['installed']} instalado(s), "
            f"{stats['unchanged']} idêntico(s), {stats['skipped']} preservado(s) por escolha.")


def upload(root: Path, ui: TerminalUI) -> None:
    repo = Repository(root)
    initial_head = repo.head()
    upstream = repo.fetch_upstream()
    local = load_bundle(root)
    remote = repo.remote_bundle(upstream)
    assert_index(root, local)
    if initial_head != upstream.commit:
        raise AgentsCloudError("Upload exige HEAD igual ao upstream, sem commits locais anteriores. Execute update se o remoto avançou; resolva divergências manualmente.")
    source_root = codex_home()
    if ui.confirm("Deseja fazer um scan automático dos agentes pessoais?"):
        scan = scan_personal(source_root, local.agents + remote.agents)
        for message in scan.skipped:
            ui.emit(message)
        if not scan.candidates:
            ui.emit("Nenhum agente novo disponível para upload.")
            return
        filename = ui.select("Escolha um agente para enviar:", [
            (f"{a.name} ({a.file}) — {a.description}", a.file) for a in scan.candidates
        ])
        source = personal_folder(source_root) / filename
    else:
        entered = ui.text("Caminho do arquivo .toml (vazio cancela):")
        if not entered:
            raise Cancelled("Upload cancelado.")
        source = Path(entered).expanduser().absolute()
    agent = read_agent(source)
    if conflicts(agent, local.agents + remote.agents):
        raise AgentsCloudError(f"Esse nome está indisponível: {agent.name} ({agent.file}). Upload cancelado.")
    category = valid_category(ui.text("Categoria do agente:"))
    entered_maintainer = ui.text("Responsável pelo agente (vazio = não informado):")
    maintainer = valid_maintainer(entered_maintainer) if entered_maintainer else None
    categories = {**local.categories, agent.file: category}
    maintainers = dict(local.maintainers)
    if maintainer is not None:
        maintainers[agent.file] = maintainer
    contribution = Bundle([*local.agents, agent], categories, maintainers)
    new_catalog = serialize_catalog(categories, maintainers)
    new_readme = updated_readme(read_readme(root), contribution)
    destination = root / "Agents" / agent.file
    ui.emit(f"Origem: {source}\nDestino: {destination}\nNome: {agent.name}\nCategoria: {category}")
    ui.emit(f"Responsável: {maintainer or 'Não informado'}")
    ui.emit("Conteúdo a publicar:\n" + agent.content.decode("utf-8"))
    ui.emit(f"Publicação: {upstream.remote}, {upstream.branch_ref}. "
            "O commit incluirá somente o agente, catalog.toml e o índice README.md.")
    if not ui.confirm("Deseja copiar, criar o commit e executar git push desta contribuição?"):
        ui.emit("Upload recusado. Nenhum arquivo foi copiado ou publicado.")
        return
    repo.require_clean()
    if repo.head() != initial_head:
        raise AgentsCloudError("HEAD mudou durante a confirmação. Execute upload novamente.")
    # Reconsulta o upstream para detectar publicações ocorridas durante a interação.
    fresh = repo.fetch_upstream()
    if (fresh.remote, fresh.branch_ref) != (upstream.remote, upstream.branch_ref):
        raise AgentsCloudError("Upstream mudou durante a confirmação. Execute upload novamente.")
    latest = repo.remote_bundle(fresh)
    if conflicts(agent, latest.agents):
        raise AgentsCloudError(f"Esse nome está indisponível: {agent.name} ({agent.file}).")
    if fresh.commit != initial_head:
        raise AgentsCloudError("O remoto avançou durante a confirmação. Execute update antes do upload.")
    # Revalida metadados e conteúdo; o usuário aprovou precisamente os bytes exibidos.
    current = load_bundle(root)
    if conflicts(agent, current.agents):
        raise AgentsCloudError(f"Esse nome está indisponível: {agent.name} ({agent.file}).")
    if read_agent(source).content != agent.content:
        raise AgentsCloudError("O agente de origem mudou durante a confirmação. Execute upload novamente.")
    destination.parent.mkdir(exist_ok=True)
    with destination.open("xb") as handle:
        handle.write(agent.content)
    try:
        write_atomic(root / "catalog.toml", new_catalog)
        write_atomic(root / "README.md", new_readme)
        repo.commit_agent([f"Agents/{agent.file}", "catalog.toml", "README.md"], agent.name)
    except (AgentsCloudError, OSError) as exc:
        raise AgentsCloudError(
            f"Contribuição copiada, mas commit não concluído: {exc}\n"
            "Arquivos locais foram preservados. Confira git status, valide catálogo/índice e conclua ou desfaça manualmente. Nenhum push foi executado."
        ) from exc
    commit = repo.head()
    try:
        repo.push(upstream)
    except AgentsCloudError as exc:
        raise AgentsCloudError(
            f"Push não concluído; commit local {commit} preservado. Publicação pendente.\n"
            f"{exc}\nInspecione o remoto e o histórico antes de reconciliar e publicar manualmente; não use force push."
        ) from exc
    ui.emit(f"Agente {agent.name} publicado. Commit: {commit}")


def build_parser(default_repo: Path | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compartilhe agentes TOML do Codex por Git.")
    parser.add_argument("--repo", type=Path, default=default_repo or Path.cwd(), help="Raiz do clone (padrão: diretório atual).")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("update", "Consulta o upstream, atualiza e oferece instalação."),
                            ("upload", "Seleciona um agente pessoal e publica uma contribuição."),
                            ("validate", "Valida agentes, catálogo e índice sem acessar a rede."),
                            ("index", "Gera o índice de agentes do README.")):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("--repo", type=Path, default=argparse.SUPPRESS, help="Raiz do clone.")
        if name == "index":
            sub.add_argument("--check", action="store_true", help="Verifica o índice sem escrever.")
    return parser


def main(argv: list[str] | None = None, *, default_repo: Path | None = None,
         ui: TerminalUI | None = None) -> int:
    args = build_parser(default_repo).parse_args(argv)
    terminal = ui or TerminalUI()
    root = args.repo.expanduser().resolve()
    try:
        if args.command == "update":
            update(root, terminal)
        elif args.command == "upload":
            upload(root, terminal)
        else:
            bundle = load_bundle(root)
            if args.command == "validate" or args.check:
                assert_index(root, bundle)
                terminal.emit(f"Validação concluída: {len(bundle.agents)} agente(s), catálogo e índice consistentes.")
            else:
                path = root / "README.md"
                write_atomic(path, updated_readme(read_readme(root), bundle))
                terminal.emit("Índice de agentes atualizado no README.md.")
        return 0
    except (KeyboardInterrupt, EOFError, Cancelled):
        terminal.emit("Operação cancelada. Etapas já concluídas, se houver, foram preservadas.")
        return 130
    except (AgentsCloudError, OSError, UnicodeError) as exc:
        terminal.emit(f"Erro: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
