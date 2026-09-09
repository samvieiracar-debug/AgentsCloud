"""Parser compartilhado: somente biblioteca padrão, sem Git, UI ou preparação."""

import argparse
from pathlib import Path


def build_parser(default_repo: Path | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compartilhe agentes TOML do Codex por Git.")
    parser.add_argument("--repo", type=Path, default=default_repo or Path.cwd(), help="Raiz do clone (padrão: diretório atual).")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("hub", "Abre a central de Update, Upload e Diagnóstico."),
                            ("update", "Consulta o upstream, atualiza e oferece instalação."),
                            ("upload", "Seleciona um agente pessoal e publica uma contribuição."),
                            ("validate", "Valida agentes, catálogo e índice sem acessar a rede."),
                            ("index", "Gera o índice de agentes do README.")):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("--repo", type=Path, default=argparse.SUPPRESS, help="Raiz do clone.")
        if name == "index":
            sub.add_argument("--check", action="store_true", help="Verifica o índice sem escrever.")
    return parser


