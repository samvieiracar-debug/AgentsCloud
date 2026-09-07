# Simular contribuição, sincronização e instalação

O roteiro usa a CLI do produto e Git real em um laboratório local novo. Apenas
as perguntas e a seleção de agentes são respondidas por uma interface
roteirizada. Ele não envia teclas ao terminal, não executa o Codex e não publica
no GitHub.

Prepare o ambiente e escolha um diretório que ainda não exista:

```console
uv sync --locked
uv run python scripts/simular_fluxo.py --destino ../AgentsCloud-lab-001
```

O caminho pode ser absoluto. Se já existir, mesmo vazio, será recusado. Cada
execução usa um nome novo; o script não apaga nem reutiliza laboratórios.

## O que acontece

1. Cria um remoto bare e dois clones, contribuidor e consumidor, dentro do
   destino. O seed contém os três agentes reais de `Agents/`, incluindo
   `documentador`, e seus metadados de catálogo.
2. Copia as fixtures `qa-resumo.toml` e `qa-revisor.toml` de
   `tests/fixtures/agents/` para o perfil isolado do contribuidor. Elas não fazem
   parte do catálogo distribuído do projeto.
3. Envia `qa-resumo` por scan e seleção simulados e `qa-revisor` pelo caminho
   manual. Cada upload cria um commit apenas com o agente, catálogo e índice,
   seguido de push para o remoto local.
4. O consumidor recusa uma atualização, preservando checkout e perfil; depois
   aceita a atualização e a instalação dos cinco agentes.
5. Repete a atualização/instalação e confere bytes e data de modificação dos
   agentes, demonstrando idempotência.
6. Tenta enviar um nome já usado e confere que o cancelamento não altera arquivos,
   commits ou remoto.
7. Acrescenta um comentário pessoal à cópia instalada de `qa-revisor`, recusa a
   substituição desse conflito e verifica sua preservação. O
   `documentador.toml` permanece idêntico ao agente distribuído.

Todas as operações de escrita Git e os perfis `CODEX_HOME` ficam dentro do
laboratório. Configurações Git pessoais são isoladas durante a execução, e
protocolos de transporte externos são bloqueados; somente transporte local de
arquivos é permitido. A configuração anterior do ambiente é restaurada ao final.

## Evidências deixadas no destino

```text
AgentsCloud-lab-001/
├── remote.git/               # Remoto bare exclusivamente local
├── contribuidor/             # Seed e dois commits de upload
├── consumidor/               # Clone sincronizado
├── profiles/
│   ├── contribuidor/agents/  # Duas fixtures de origem
│   └── consumidor/agents/   # Cinco agentes instalados
├── resultado.json            # Checks, comandos, escolhas, caminhos e hashes
└── resultado.md              # Resumo legível
```

O terminal informa o resultado e o caminho do perfil consumidor. Os relatórios
contêm os SHAs dos commits, a lista de arquivos de cada contribuição, hashes
SHA256 e tamanhos dos agentes, transcrições das respostas simuladas e o estado
dos arquivos instalados.

Um resultado `passed` significa que todos os checks daquele laboratório
passaram. O código 1 da CLI no cenário de duplicidade é uma recusa esperada; o
relatório explica isso. Se uma verificação inesperada falhar, o script retorna
código 1, preserva o laboratório e registra o erro para inspeção.

Ao final, `qa-revisor.toml` difere propositalmente do catálogo porque seu ajuste
pessoal foi preservado. Os demais agentes, incluindo `documentador.toml`,
continuam iguais aos arquivos sincronizados. Uma nova execução deverá usar
outro diretório.

O teste de aceitação da suíte também executa o roteiro em diretório temporário
e confere os objetos Git, os bytes instalados e a preservação de um perfil
externo ao laboratório:

```console
uv run python -m unittest discover -s tests -v
```

Essa demonstração comprova os fluxos observados da CLI. Ela não comprova
carregamento ou execução de agente no Codex. Para essa etapa separada, use o
[roteiro de compatibilidade](compatibilidade.md) e registre a versão do runtime,
o agente selecionado e o resultado realmente produzido.
