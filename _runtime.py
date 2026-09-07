"""Entrada interna de uma única execução; nunca volta ao bootstrap público."""

import json
from pathlib import Path
import sys
import tempfile


def run():
    root = Path(sys.argv[1]).resolve()
    if Path(sys.prefix).resolve() != (root / ".venv").resolve():
        print("Erro: o runtime não reconheceu a .venv do alvo. Execute o atalho novamente.", file=sys.stderr)
        return 1
    # Evita bytecode de uma versão anterior, inclusive mesmo tamanho/mtime.
    with tempfile.TemporaryDirectory(prefix="agentscloud-bytecode-") as cache:
        sys.pycache_prefix = cache
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(root / "src"))
        try:
            from agentscloud.errors import AgentsCloudError
            from agentscloud.git import Repository
            from agentscloud.prepared import PreparedCheckout

            prepared = PreparedCheckout(**json.loads(sys.argv[2]))
            prepared.check_local(Repository(root))
            from agentscloud.cli import main
            return main(sys.argv[3:], default_repo=root, prepared=prepared)
        except (ImportError, OSError) as exc:
            print(f"Erro no runtime preparado de {root}: {exc}. Execute o atalho novamente.", file=sys.stderr)
            return 1
        except AgentsCloudError as exc:
            print(f"Erro: {exc}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except (KeyboardInterrupt, EOFError):
        raise SystemExit(130)
