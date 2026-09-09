"""Interface interativa isolada da lógica para testes e outras interfaces futuras."""

from typing import Sequence
import questionary

from .errors import Cancelled
from .agents import Agent


class TerminalUI:
    def choose_installation(self, agents: list[Agent], categories: dict[str, str]) -> list[str]:
        """Mesmo contrato de seleção do hub, preservando o terminal em etapas."""
        if not agents:
            self.emit("O catálogo está vazio. Nenhum agente para instalar.")
            return []
        mode = self.select("Como deseja instalar os agentes?", [
            (f"Catálogo inteiro ({len(agents)} agentes)", "all"),
            ("Selecionar agentes por categoria", "choose"),
        ])
        if mode == "all":
            return [agent.file for agent in agents]
        selected: set[str] = set()
        while True:
            category = self.select("Filtrar categoria:", [
                ("Todas as categorias", ""),
                *((item, item) for item in sorted(set(categories.values()), key=str.casefold)),
            ])
            visible = [a for a in agents if not category or categories[a.file] == category]
            answer = questionary.checkbox(
                "Marque os agentes desejados:",
                choices=[questionary.Choice(title=f"{a.name} ({a.file}) — {a.description}",
                                            value=a.file, checked=a.file in selected) for a in visible],
                instruction="(Espaço marca, setas navegam, Enter continua, Ctrl+C cancela)",
            ).unsafe_ask()
            if answer is None:
                raise Cancelled("Seleção cancelada.")
            selected.difference_update(a.file for a in visible)
            selected.update(answer)
            action = self.select(f"{len(selected)} agente(s) selecionado(s) no total:", [
                ("Continuar com esta seleção", "continue"),
                ("Escolher outra categoria", "filter"),
                ("Cancelar instalação", "cancel"),
            ])
            if action == "continue":
                return [a.file for a in agents if a.file in selected]
            if action == "cancel":
                return []

    def review_step(self, title: str, content: str) -> bool:
        self.emit(f"{title}\n{content}")
        return self.confirm("Avançar para a próxima etapa da revisão?")

    def emit(self, message: str) -> None:
        print(message)

    def confirm(self, message: str) -> bool:
        answer = questionary.confirm(f"{message} (y/n)", default=False).unsafe_ask()
        if answer is None:
            raise Cancelled("Operação cancelada; nenhuma confirmação foi concedida.")
        return answer

    def text(self, message: str) -> str:
        answer = questionary.text(message).unsafe_ask()
        if answer is None:
            raise Cancelled("Operação cancelada.")
        return answer.strip()

    def select(self, message: str, choices: Sequence[tuple[str, str]]) -> str:
        answer = questionary.select(
            message,
            choices=[questionary.Choice(title=label, value=value) for label, value in choices],
            instruction="(↑/↓ para escolher, Enter para confirmar, Ctrl+C para cancelar)",
        ).unsafe_ask()
        if answer is None:
            raise Cancelled("Seleção cancelada.")
        return answer
