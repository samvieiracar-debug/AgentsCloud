"""Comandos de catálogo, sincronização e contribuição."""

from pathlib import Path
import sys

from .arguments import build_parser
from .prepared import PreparedCheckout
from .agents import Agent, conflicts, read_agent
from .catalog import Bundle, load_bundle, read_readme, serialize_catalog, updated_readme, valid_category, valid_maintainer
from .errors import AgentsCloudError, Cancelled
from .git import Repository
from .install import codex_home, install_agents, personal_folder, scan_personal, write_atomic
from .ui import TerminalUI
from .recovery import handle_pending, publish_exact
from .processes import sanitize


def assert_index(root: Path, bundle: Bundle) -> None:
    current = read_readme(root)
    if updated_readme(current, bundle) != current:
        raise AgentsCloudError("Índice README desatualizado. Execute agentscloud index e registre a alteração no Git.")


def installation_selection(bundle: Bundle, ui: TerminalUI) -> list[Agent]:
    """Seleciona somente arquivos do catálogo validado, mantendo a ordem original."""
    choose = getattr(ui, "choose_installation", None)
    if not callable(choose):
        return list(bundle.agents)
    filenames = choose(list(bundle.agents), dict(bundle.categories))
    available = {agent.file for agent in bundle.agents}
    if (not isinstance(filenames, list)
            or any(not isinstance(filename, str) for filename in filenames)
            or len(set(filenames)) != len(filenames)
            or not set(filenames).issubset(available)):
        raise AgentsCloudError("Seleção inválida: escolha somente agentes disponíveis no catálogo.")
    selected = set(filenames)
    return [agent for agent in bundle.agents if agent.file in selected]


def review_step(ui: TerminalUI, title: str, content: str) -> bool:
    """Interfaces com etapas podem pausar; consumidores antigos mantêm a saída."""
    review = getattr(ui, "review_step", None)
    if callable(review):
        return review(title, content)
    ui.emit(content)
    return True


def update(root: Path, ui: TerminalUI, prepared: PreparedCheckout | None = None) -> None:
    repo = Repository(root)
    if prepared:
        prepared.check_local(repo)
    initial_head = repo.head()
    upstream = repo.fetch_upstream()
    if prepared:
        prepared.check_upstream(repo, upstream)
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
        if repo.is_ancestor(upstream.commit, initial_head):
            ui.emit("O checkout contém commits locais ainda não publicados; a instalação usará esse catálogo local.")
        elif repo.is_ancestor(initial_head, upstream.commit):
            if not ui.confirm("Deseja atualizar o repositório local por fast-forward?"):
                ui.emit("Atualização recusada. Checkout e agentes pessoais preservados.")
                return
            repo.fast_forward(upstream, initial_head)
            local = load_bundle(root)
            assert_index(root, local)
            ui.emit(f"Repositório atualizado para {repo.head()[:12]}.")
        else:
            raise AgentsCloudError("Há divergência com o upstream. Resolva o histórico manualmente; nenhum merge foi feito.")
    else:
        ui.emit("Repositório já está atualizado.")
    agents = installation_selection(local, ui)
    if not agents and callable(getattr(ui, "choose_installation", None)):
        ui.emit("Nenhum agente selecionado. Nenhuma instalação foi realizada.")
        return
    destination = codex_home()
    folder = personal_folder(destination)
    if not ui.confirm(f"Deseja instalar {len(agents)} agente(s) em {folder}?"):
        ui.emit("Instalação recusada.")
        return
    if prepared:
        prepared.check_upstream(repo, repo.fetch_upstream())
    stats = install_agents(agents, destination, ui.confirm, ui.emit)
    ui.emit(f"Instalação concluída: {stats['installed']} instalado(s), "
            f"{stats['unchanged']} idêntico(s), {stats['skipped']} preservado(s) por escolha.")


def upload(root: Path, ui: TerminalUI, prepared: PreparedCheckout | None = None) -> None:
    repo = Repository(root)
    if prepared:
        prepared.check_local(repo)
    initial_head = repo.head()
    upstream = repo.fetch_upstream()
    if prepared:
        prepared.check_upstream(repo, upstream)
    target = repo.push_target(upstream)
    target_tip = repo.fetch_target(target)
    local = load_bundle(root)
    remote = repo.remote_bundle(upstream)
    assert_index(root, local)
    if handle_pending(repo, ui, upstream, target, initial_head, target_tip):
        return
    if initial_head != upstream.commit:
        raise AgentsCloudError("O upstream difere do HEAD. Execute update ou reconcilie o histórico antes de uma nova contribuição.")
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
    details = (f"Origem: {source}\nDestino: {destination}\nNome: {agent.name}\nCategoria: {category}\n"
               f"Responsável: {maintainer or 'Não informado'}")
    if not review_step(ui, "1/3 · Dados do envio", details):
        ui.emit("Upload recusado. Nenhum arquivo foi copiado ou publicado.")
        return
    if not review_step(ui, "2/3 · Conteúdo TOML", "Conteúdo a publicar:\n" + agent.content.decode("utf-8")):
        ui.emit("Upload recusado. Nenhum arquivo foi copiado ou publicado.")
        return
    publication = (f"Publicação: {target.display}. "
                   "O commit incluirá somente o agente, catalog.toml e o índice README.md.")
    ui.emit(publication)
    confirmation = "Deseja copiar, criar o commit e executar git push desta contribuição?"
    if callable(getattr(ui, "review_step", None)):
        confirmation = f"3/3 · Confirmar publicação\n{publication}\n\n{confirmation}"
    if not ui.confirm(confirmation):
        ui.emit("Upload recusado. Nenhum arquivo foi copiado ou publicado.")
        return
    repo.require_clean()
    if repo.head() != initial_head:
        raise AgentsCloudError("HEAD mudou durante a confirmação. Execute upload novamente.")
    # Reconsulta o upstream para detectar publicações ocorridas durante a interação.
    fresh = repo.fetch_upstream()
    if prepared:
        prepared.check_upstream(repo, fresh)
    if (fresh.remote, fresh.branch_ref) != (upstream.remote, upstream.branch_ref):
        raise AgentsCloudError("Upstream mudou durante a confirmação. Execute upload novamente.")
    if repo.push_target(fresh) != target:
        raise AgentsCloudError("Destino de push mudou durante a confirmação. Execute upload novamente.")
    latest = repo.remote_bundle(fresh)
    if conflicts(agent, latest.agents):
        raise AgentsCloudError(f"Esse nome está indisponível: {agent.name} ({agent.file}).")
    if repo.fetch_target(target) != target_tip:
        raise AgentsCloudError("O destino de push avançou durante a confirmação. Execute upload novamente.")
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
        approved = {f"Agents/{agent.file}": agent.content, "catalog.toml": new_catalog, "README.md": new_readme}
        commit = repo.commit_agent(list(approved), agent.name)
        repo.verify_contribution(commit, initial_head, approved)
    except (AgentsCloudError, OSError) as exc:
        raise AgentsCloudError(
            f"Contribuição copiada, mas commit não concluído ou não confirmado: {exc}\n"
            "Arquivos locais foram preservados. Confira git status, valide catálogo/índice e conclua ou desfaça manualmente. Nenhum push foi executado."
        ) from exc
    publish_exact(repo, ui, upstream, target, commit, initial_head, repo.branch())
    ui.emit(f"Agente {agent.name} publicado. Commit: {commit}")


def main(argv: list[str] | None = None, *, default_repo: Path | None = None,
         ui: TerminalUI | None = None, prepared: PreparedCheckout | None = None) -> int:
    args = build_parser(default_repo).parse_args(argv)
    terminal = ui or TerminalUI()
    root = args.repo.expanduser().resolve()
    try:
        if args.command == "hub":
            try:
                from .hub import run_hub
            except ImportError as exc:
                raise AgentsCloudError("O hub precisa das dependências visuais. Execute uv sync --locked no clone.") from exc
            return run_hub(root)
        elif args.command == "update":
            update(root, terminal, prepared)
        elif args.command == "upload":
            upload(root, terminal, prepared)
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
        terminal.emit(sanitize(f"Erro: {exc}"))
        return 1


if __name__ == "__main__":
    sys.exit(main())
