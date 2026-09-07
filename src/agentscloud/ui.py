"""Interface interativa isolada da lógica para testes e outras interfaces futuras."""

from typing import Sequence
import questionary

from .errors import Cancelled


class TerminalUI:
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
