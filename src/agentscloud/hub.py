"""Hub Textual; operações síncronas trabalham fora da thread de renderização."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from collections import deque
from pathlib import Path
import sys
import threading
import time
from typing import Any

from rich.text import Text
from rich.segment import Segment
from rich.style import Style
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.screen import ModalScreen
from textual.strip import Strip
from textual.worker import get_current_worker
from textual.widgets import (
    Button, Footer, Input, LoadingIndicator, OptionList, RichLog, Select,
    SelectionList, Static,
)
from textual.widgets.option_list import OptionDoesNotExist

from .agents import Agent
from .errors import AgentsCloudError, Cancelled
from .help_text import HUB_HELP
from .processes import process_output, sanitize
from .theme import COMPACT_HEIGHT, COMPACT_WIDTH, CSS, HUB_THEME, MIN_HEIGHT, MIN_WIDTH
from .ui import TerminalUI


TOO_SMALL = "Amplie o terminal para pelo menos 80 colunas × 24 linhas.\nCtrl+Q para sair; Esc cancela uma pergunta pendente."
PAGES = {
    "update": (
        "Update", "Instale os agentes da equipe",
        "Consulte as novidades e instale o catálogo inteiro ou uma seleção por categoria.",
        "01 Consultar   /   02 Escolher   /   03 Instalar", "Consultar catálogo",
    ),
    "upload": (
        "Upload", "Compartilhe uma especialidade",
        "Escolha um agente pessoal, revise os dados e o conteúdo, depois confirme a publicação.",
        "01 Escolher   /   02 Revisar   /   03 Publicar", "Escolher agente",
    ),
    "diagnostico": (
        "Diagnóstico", "Entenda o ambiente",
        "Confira as ferramentas, o ambiente Python e o Git. Reparos são oferecidos individualmente.",
        "01 Verificar   /   02 Examinar   /   03 Reparar", "Iniciar diagnóstico",
    ),
}
WELCOME = {
    "update": "Pronto para consultar o catálogo.\n\nAo iniciar, confira as novidades e escolha quais agentes instalar.\nArquivos pessoais diferentes terão confirmação e backup antes de substituir.",
    "upload": "Pronto para preparar uma contribuição.\n\nEscolha o agente, informe a categoria e revise o envio por etapas.\nVocê verá o destino da publicação antes de autorizar commit e push.",
    "diagnostico": "Pronto para verificar este clone.\n\nO diagnóstico mostra as condições do ambiente e os próximos passos.\nCada reparo exige sua confirmação com a ação exata visível.",
}


class ResponsiveLog(RichLog):
    """RichLog renderiza uma vez; reapresentamos o texto quando a largura muda."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.entries: deque[str] = deque(maxlen=2000)
        self.rendered_width = 0

    def record(self, message: str) -> None:
        self.entries.append(message)
        width = max(1, self.scrollable_content_region.width - 1) if self.size.width else None
        self.write(Text(message, overflow="fold", no_wrap=False), width=width)

    def reset(self) -> None:
        self.entries.clear()
        self.clear()

    def on_resize(self, event: Resize) -> None:
        super().on_resize(event)
        if event.size.width != self.rendered_width:
            self.rendered_width = event.size.width
            self.call_after_refresh(self.reflow)

    def reflow(self) -> None:
        previous_y = self.scroll_y
        at_end = self.scroll_y >= self.max_scroll_y
        width = max(1, self.scrollable_content_region.width - 1)
        self.clear()
        for message in self.entries:
            self.write(Text(message, overflow="fold", no_wrap=False), width=width, scroll_end=False)
        if self.auto_scroll and at_end:
            self.scroll_end(animate=False)
        else:
            self.scroll_to(y=previous_y, animate=False)


class AgentSelectionList(SelectionList[str]):
    """Marcadores ASCII distinguem estados também com NO_COLOR."""

    def render_line(self, y: int) -> Strip:
        line = super().render_line(y)
        index = self.scroll_offset.y + y
        try:
            option = self.get_option_at_index(index)
        except OptionDoesNotExist:
            return line
        style = self.get_component_rich_style(
            "option-list--option-highlighted" if self.highlighted == index else "option-list--option"
        ) + Style(meta={"option": index})
        marker = "[x] " if option.value in self.selected else "[ ] "
        return Strip.join([Strip([Segment(marker, style)], 4), line.crop(4)])


class Dialog(ModalScreen[Any]):
    """Cada diálogo devolve uma resposta; Esc nunca concede confirmação."""

    BINDINGS = [Binding("escape", "cancel", "Cancelar", priority=True)]

    def __init__(self) -> None:
        super().__init__(classes="dialog-screen")

    def on_resize(self, event: Resize) -> None:
        self.set_class(event.size.width < COMPACT_WIDTH or event.size.height < COMPACT_HEIGHT, "compact")
        self.set_class(event.size.width < MIN_WIDTH or event.size.height < MIN_HEIGHT, "too-small")

    def action_cancel(self) -> None:
        self.dismiss(None)


class Prompt(Dialog):
    def __init__(self, kind: str, message: str, *, choices: Sequence[tuple[str, str]] = (), content: str = "") -> None:
        super().__init__()
        self.kind = kind
        self.message = message
        self.choices = list(choices)
        self.content = content

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(Text(self.message if self.kind == "review" else {
                "confirm": "Confirmação", "text": "Dados da operação", "select": "Escolha o próximo passo",
            }[self.kind]), id="dialog-title")
            yield Static("Tab alterna o foco · Enter confirma a opção · Esc cancela", id="dialog-hint")
            if self.kind == "review":
                yield ResponsiveLog(id="review-content", wrap=True, markup=False, highlight=False, auto_scroll=False, min_width=1)
            elif self.kind == "select":
                yield Static(Text(self.message), id="prompt-message")
                yield OptionList(*(Text(label) for label, _ in self.choices), id="choices")
            else:
                with VerticalScroll(id="prompt-scroll"):
                    yield Static(Text(self.message), id="prompt-message")
                    if self.kind == "text":
                        yield Input(id="answer")
            with Horizontal(id="dialog-actions"):
                yield Button("Não" if self.kind == "confirm" else "Cancelar", id="reject")
                if self.kind != "select":
                    yield Button("Sim, confirmar" if self.kind == "confirm" else "Continuar", id="accept", variant="primary")
        yield Static(TOO_SMALL, id="dialog-size")

    def on_mount(self) -> None:
        if self.kind == "review":
            log = self.query_one("#review-content", ResponsiveLog)
            # Text evita interpretar o conteúdo TOML como markup ou sequências ANSI.
            log.record(self.content)
            log.focus()
        elif self.kind == "select":
            self.query_one("#choices", OptionList).focus()
        elif self.kind == "text":
            self.query_one("#answer", Input).focus()
        else:
            self.query_one("#reject", Button).focus()

    @on(Button.Pressed, "#reject")
    def reject(self) -> None:
        self.dismiss(False if self.kind in ("confirm", "review") else None)

    @on(Button.Pressed, "#accept")
    def accept(self) -> None:
        self.dismiss(self.query_one("#answer", Input).value.strip() if self.kind == "text" else True)

    @on(Input.Submitted, "#answer")
    def submit_text(self) -> None:
        self.accept()

    @on(OptionList.OptionSelected, "#choices")
    def select_option(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self.choices[event.option_index][1])


class AgentPicker(Dialog):
    """As escolhas são do catálogo completo; o filtro só muda a lista visível."""

    def __init__(self, agents: Sequence[Agent], categories: dict[str, str]) -> None:
        super().__init__()
        self.agents = list(agents)
        self.categories = categories
        self.chosen: set[str] = set()
        self.visible_agents: list[Agent] = list(agents)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("Monte sua seleção", id="dialog-title")
            yield Static("Espaço marca agentes · Tab muda o foco · As escolhas permanecem ao trocar a categoria", id="dialog-hint")
            yield Select(
                [("Todas as categorias", ""), *((category, category) for category in sorted(set(self.categories.values()), key=str.casefold))],
                value="", allow_blank=False, id="category",
            )
            yield AgentSelectionList(id="agent-list")
            yield Static("", id="agent-details", markup=False)
            yield Static("0 agentes selecionados", id="selection-summary")
            with Horizontal(id="selection-tools"):
                yield Button("Marcar visíveis", id="mark-visible")
                yield Button("Limpar seleção", id="clear-selection")
            with Horizontal(id="dialog-actions"):
                yield Button("Cancelar", id="reject")
                yield Button("Usar seleção", id="use-selection", variant="primary", disabled=True)
        yield Static(TOO_SMALL, id="dialog-size")

    def on_mount(self) -> None:
        self.populate("")
        self.query_one("#agent-list", SelectionList).focus()

    def remember(self) -> None:
        selected = self.query_one("#agent-list", SelectionList).selected
        self.chosen.difference_update(agent.file for agent in self.visible_agents)
        self.chosen.update(selected)

    def populate(self, category: str) -> None:
        self.visible_agents = [a for a in self.agents if not category or self.categories[a.file] == category]
        listing = self.query_one("#agent-list", SelectionList)
        with listing.prevent(SelectionList.SelectedChanged):
            listing.clear_options()
            listing.add_options([(Text(f"{a.name}  /  {a.file}", no_wrap=True, overflow="ellipsis"), a.file, a.file in self.chosen) for a in self.visible_agents])
            listing.highlighted = 0 if self.visible_agents else None
        self.refresh_summary()
        self.query_one("#agent-details", Static).update(
            "Escolha um agente para ler sua descrição." if self.visible_agents else "Nenhum agente nesta categoria."
        )

    def refresh_summary(self) -> None:
        hidden = len(self.chosen - {a.file for a in self.visible_agents})
        summary = f"{len(self.chosen)} selecionado(s) · {len(self.visible_agents)} visível(is)"
        if hidden:
            summary += f" · {hidden} em outras categorias"
        self.query_one("#selection-summary", Static).update(summary)
        self.query_one("#use-selection", Button).disabled = not self.chosen

    @on(Select.Changed, "#category")
    def change_category(self, event: Select.Changed) -> None:
        if not self.is_mounted or not isinstance(event.value, str):
            return
        self.remember()
        self.populate(event.value)

    @on(SelectionList.SelectedChanged, "#agent-list")
    def changed_selection(self) -> None:
        self.remember()
        self.refresh_summary()

    @on(SelectionList.SelectionHighlighted, "#agent-list")
    def highlight_agent(self, event: SelectionList.SelectionHighlighted) -> None:
        agent = next((a for a in self.agents if a.file == event.selection.value), None)
        if agent:
            self.query_one("#agent-details", Static).update(Text(f"{self.categories[agent.file]} · {agent.description}"))

    @on(Button.Pressed, "#mark-visible")
    def mark_visible(self) -> None:
        self.query_one("#agent-list", SelectionList).select_all()

    @on(Button.Pressed, "#clear-selection")
    def clear_agent_selection(self) -> None:
        self.chosen.clear()
        self.query_one("#agent-list", SelectionList).deselect_all()
        self.refresh_summary()

    @on(Button.Pressed, "#reject")
    def reject(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#use-selection")
    def use_selection(self) -> None:
        self.remember()
        if self.chosen:
            self.dismiss([a.file for a in self.agents if a.file in self.chosen])


class HubUI(TerminalUI):
    """Ponte síncrona para os fluxos existentes, chamada somente pelo worker."""

    def __init__(self, app: HubApp) -> None:
        self.app = app

    def checkpoint(self) -> None:
        if self.app.cancel_requested.is_set() or get_current_worker().is_cancelled:
            raise Cancelled("Cancelamento solicitado no hub.")

    def emit(self, message: str) -> None:
        self.checkpoint()
        self.app.call_from_thread(self.app.append_output, message)

    def ask(self, dialog: Dialog) -> Any:
        self.checkpoint()
        finished = threading.Event()
        result: list[Any] = []

        def answer(value: Any) -> None:
            result.append(value)
            finished.set()

        self.app.call_from_thread(self.app.show_question, dialog, answer)
        while not finished.wait(0.1):
            self.checkpoint()
        self.checkpoint()
        if result[0] is None:
            raise Cancelled("Operação cancelada no hub.")
        return result[0]

    def confirm(self, message: str) -> bool:
        return bool(self.ask(Prompt("confirm", message)))

    def text(self, message: str) -> str:
        return str(self.ask(Prompt("text", message)))

    def select(self, message: str, choices: Sequence[tuple[str, str]]) -> str:
        if not choices:
            raise Cancelled("Nenhuma opção disponível.")
        return str(self.ask(Prompt("select", message, choices=choices)))

    def choose_installation(self, agents: list[Agent], categories: dict[str, str]) -> list[str]:
        if not agents:
            self.emit("O catálogo está vazio. Nenhum agente para instalar.")
            return []
        mode = self.select("Como deseja instalar os agentes?", [
            (f"Catálogo inteiro — {len(agents)} agente(s)", "all"),
            ("Selecionar agentes e filtrar por categoria", "choose"),
        ])
        if mode == "all":
            return [agent.file for agent in agents]
        return self.ask(AgentPicker(agents, categories))

    def review_step(self, title: str, content: str) -> bool:
        approved = bool(self.ask(Prompt("review", title, content=content)))
        self.emit(f"{title}: {'revisado' if approved else 'revisão recusada'}.")
        return approved


OperationRunner = Callable[[str, Path, HubUI], int]


def run_operation(action: str, root: Path, ui: HubUI) -> int:
    """Integração real; não passa pelos lançadores que fazem pull/sync."""
    if action != "diagnostico":
        from .cli import main

        return main([action, "--repo", str(root)], ui=ui)
    from .diagnostics import Diagnostics

    doctor = Diagnostics(root, progress=ui.emit, confirm_fn=ui.confirm)
    doctor.collect()
    doctor.render(emit=ui.emit)
    if ui.confirm("Deseja examinar os reparos disponíveis? Cada alteração terá sua própria confirmação."):
        if doctor.repairs(input_fn=ui.text, emit=ui.emit):
            doctor.collect()
            doctor.render(emit=ui.emit)
    return doctor.exit_code()


class HubApp(App[int]):
    TITLE = "AgentsCloud"
    CSS = CSS
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("f2", "page('update')", "Update"),
        Binding("f3", "page('upload')", "Upload"),
        Binding("f4", "page('diagnostico')", "Diagnóstico"),
        Binding("f1", "help", "Ajuda"),
        Binding("escape", "cancel", "Cancelar"),
        Binding("ctrl+q,ctrl+c", "quit", "Sair", priority=True),
    ]

    def __init__(self, root: Path, *, initial_action: str | None = None, runner: OperationRunner | None = None) -> None:
        super().__init__()
        self.root = root
        self.current_action = initial_action if initial_action in PAGES else "update"
        self.runner = runner or run_operation
        self.busy = False
        self.cancel_requested = threading.Event()
        self.pending_dialog: Dialog | None = None
        self.started_at = 0.0
        self.last_code = 0
        self.has_run = False
        self.register_theme(HUB_THEME)
        self.theme = HUB_THEME.name

    def compose(self) -> ComposeResult:
        with Horizontal(id="shell"):
            with Vertical(id="sidebar"):
                yield Static("AGENTSCLOUD", id="brand")
                yield Static("Especialidades\ncompartilhadas", id="brand-caption")
                yield Static("FLUXOS", id="nav-label")
                yield Button("Update", id="nav-update", classes="nav-button")
                yield Button("Upload", id="nav-upload", classes="nav-button")
                yield Button("Diagnóstico", id="nav-diagnostico", classes="nav-button")
                yield Static("", id="sidebar-spacer")
                yield Static("Catálogo local", id="catalog-summary")
                yield Static("CLONE ATIVO", id="repo-label")
                yield Static(Text(self.root.name, overflow="ellipsis", no_wrap=True), id="repo-name")
                yield Static(Text(str(self.root), overflow="ellipsis", no_wrap=True), id="repo-path")
            with Vertical(id="workspace"):
                yield Static("HUB / UPDATE", id="eyebrow")
                yield Static("", id="page-title")
                yield Static("", id="page-description")
                yield Static("", id="steps")
                with Horizontal(id="action-row"):
                    yield Button("Iniciar", id="start", variant="primary")
                    yield LoadingIndicator(id="activity")
                    yield Static("PRONTO", id="status")
                yield ResponsiveLog(id="session-log", wrap=True, markup=False, highlight=False, max_lines=2000, min_width=1)
                yield Static("Escolha uma ação no menu para começar.", id="context-hint")
        yield Static(TOO_SMALL, id="too-small")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#activity", LoadingIndicator).display = False
        self.query_one("#session-log", RichLog).border_title = "Atividade da sessão"
        self.query_one("#repo-path", Static).tooltip = str(self.root)
        self.action_page(self.current_action)
        self.refresh_catalog()
        self.set_interval(1, self.update_elapsed)
        self.query_one("#start", Button).focus()

    def refresh_catalog(self) -> None:
        from .catalog import load_bundle

        try:
            bundle = load_bundle(self.root)
            label = f"CATÁLOGO LOCAL\n{len(bundle.agents)} agentes\n{len(set(bundle.categories.values()))} categorias"
        except (AgentsCloudError, OSError, UnicodeError, ValueError):
            label = "CATÁLOGO LOCAL\nIndisponível\nConsulte o diagnóstico"
        self.query_one("#catalog-summary", Static).update(label)

    def on_resize(self, event: Resize) -> None:
        for screen in self.screen_stack:
            screen.set_class(event.size.width < COMPACT_WIDTH or event.size.height < COMPACT_HEIGHT, "compact")
            screen.set_class(event.size.width < MIN_WIDTH or event.size.height < MIN_HEIGHT, "too-small")

    def action_page(self, action: str) -> None:
        if self.busy or len(self.screen_stack) > 1:
            return
        self.current_action = action
        label, title, description, steps, button = PAGES[action]
        self.query_one("#eyebrow", Static).update("HUB / " + label.upper())
        self.query_one("#page-title", Static).update(title)
        self.query_one("#page-description", Static).update(description)
        self.query_one("#steps", Static).update(steps)
        self.query_one("#start", Button).label = button
        for item in PAGES:
            self.query_one("#nav-" + item, Button).set_class(item == action, "selected")
        if not self.has_run:
            log = self.query_one("#session-log", ResponsiveLog)
            log.border_title = "Antes de começar"
            log.reset()
            log.record(WELCOME[action])

    @on(Button.Pressed, ".nav-button")
    def navigate(self, event: Button.Pressed) -> None:
        self.action_page(event.button.id.removeprefix("nav-"))

    @on(Button.Pressed, "#start")
    def start_operation(self) -> None:
        if self.busy or self.size.width < MIN_WIDTH or self.size.height < MIN_HEIGHT:
            return
        self.busy = True
        self.has_run = True
        self.cancel_requested.clear()
        self.started_at = time.monotonic()
        self.query_one("#start", Button).disabled = True
        for button in self.query(".nav-button"):
            button.disabled = True
        self.query_one("#activity", LoadingIndicator).display = True
        self.query_one("#session-log", ResponsiveLog).reset()
        self.query_one("#session-log", RichLog).border_title = "Atividade da sessão"
        self.append_output(f"{PAGES[self.current_action][0]} iniciado.\nClone: {self.root}")
        self.query_one("#context-hint", Static).update("Esc solicita parada após a etapa atual.")
        self.update_elapsed()
        self.execute_operation(self.current_action)

    @work(thread=True, exclusive=True, exit_on_error=False)
    def execute_operation(self, action: str) -> None:
        ui = HubUI(self)
        code = 1
        try:
            with process_output(lambda text: self.call_from_thread(self.append_output, text)):
                code = self.runner(action, self.root, ui)
        except (Cancelled, KeyboardInterrupt, EOFError):
            code = 130
            self.call_from_thread(self.append_output, "Operação cancelada. Etapas já concluídas, se houver, foram preservadas.")
        except Exception as exc:
            self.call_from_thread(self.append_output, "Erro: " + sanitize(exc))
        finally:
            self.call_from_thread(self.finish_operation, code)

    def append_output(self, message: str) -> None:
        self.query_one("#session-log", ResponsiveLog).record(str(message).rstrip("\r\n"))

    def show_question(self, dialog: Dialog, answer: Callable[[Any], None]) -> None:
        if self.cancel_requested.is_set():
            answer(None)
            return
        self.pending_dialog = dialog
        self.query_one("#status", Static).update("AGUARDANDO VOCÊ")

        def complete(value: Any) -> None:
            self.pending_dialog = None
            answer(value)
            self.update_elapsed()

        self.push_screen(dialog, complete)

    def update_elapsed(self) -> None:
        if not self.busy or self.pending_dialog is not None:
            return
        seconds = int(time.monotonic() - self.started_at)
        label = "PARADA SOLICITADA" if self.cancel_requested.is_set() else "EM ANDAMENTO"
        self.query_one("#status", Static).update(f"{label}  {seconds // 60:02d}:{seconds % 60:02d}")

    def finish_operation(self, code: int) -> None:
        self.busy = False
        self.last_code = code
        self.query_one("#activity", LoadingIndicator).display = False
        self.query_one("#status", Static).update({0: "CONCLUÍDO", 130: "CANCELADO"}.get(code, "REQUER ATENÇÃO"))
        self.query_one("#context-hint", Static).update("Resultado acima. Escolha outra ação ou Ctrl+Q para sair.")
        self.query_one("#start", Button).disabled = False
        for button in self.query(".nav-button"):
            button.disabled = False
        self.refresh_catalog()
        self.query_one("#session-log", RichLog).focus()

    def action_cancel(self) -> None:
        if self.pending_dialog:
            self.pending_dialog.dismiss(None)
        elif self.busy:
            self.cancel_requested.set()
            self.query_one("#context-hint", Static).update("Etapa atual terminará; alterações concluídas permanecem.")
            self.update_elapsed()

    def action_quit(self) -> None:
        if self.busy:
            self.action_cancel()
            self.notify("Aguarde o término da operação e use Ctrl+Q novamente para sair.")
            return
        self.exit(self.last_code)

    def action_help(self) -> None:
        if self.busy or len(self.screen_stack) > 1:
            return
        self.push_screen(Prompt("review", "Ajuda e comandos do projeto", content=f"Clone ativo: {self.root}\n\n{HUB_HELP}"))


def run_hub(root: Path, *, initial_action: str | None = None) -> int:
    """Só inicia tela inteira em um terminal real, sem animações em pipelines."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("O hub exige terminal interativo. Use agentscloud update, upload ou diagnostico.cmd.", file=sys.stderr)
        return 2
    app = HubApp(root, initial_action=initial_action)
    result = app.run()
    return result if result is not None else 0
