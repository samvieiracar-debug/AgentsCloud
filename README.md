# AgentsCloud

Repositório da equipe para compartilhar agentes nativos do Codex em arquivos TOML.
Cada agente descreve uma especialidade; o Git mantém seu histórico e a CLI ajuda a
sincronizar, instalar e contribuir sem copiar arquivos manualmente.

## Arquitetura

A base usa Python 3.11+, Git e uma CLI pequena. `argparse` cuida dos comandos,
`tomllib` valida TOML e Questionary fornece perguntas e seleção com setas.
Não há servidor nem banco de dados. A pasta `Agents/` é plana para simplificar
cópia e identificação de duplicatas; categorias e responsáveis ficam em `catalog.toml`.
Nome e descrição vêm do agente, e o índice do README é gerado desses dados.

```text
AgentsCloud/
├── Agents/                   # Agentes distribuídos, um TOML por arquivo
├── catalog.toml              # Metadados: file, category, maintainer opcional
├── templates/agente.toml     # Ponto de partida para um novo agente
├── src/agentscloud/
│   ├── cli.py                # Fluxos update/upload e comandos auxiliares
│   ├── ui.py                 # Perguntas, seleção e saída de terminal
│   ├── agents.py             # Validação e identidade dos agentes
│   ├── catalog.py            # Catálogo e geração do índice
│   ├── git.py                # Git via subprocess, sem shell
│   ├── install.py            # CODEX_HOME, scan, cópia e backup
│   └── errors.py             # Erros esperados da CLI
├── tests/                    # Testes com repositórios e homes temporários
├── .github/workflows/validate.yml # CI Windows, Linux e macOS
├── CONTRIBUTING.md           # Contribuição e recuperação
├── docs/compatibilidade.md   # Evidências e roteiro de homologação/piloto
├── update.py                 # Atalho para agentscloud update
├── upload.py                 # Atalho para agentscloud upload
├── pyproject.toml
├── uv.lock
└── README.md
```

## Preparar o clone

Instale Python 3.11 ou superior, Git e [uv](https://docs.astral.sh/uv/getting-started/installation/).
Clone o repositório de teste da equipe e entre na pasta:

```console
git clone https://github.com/samvieiracar-debug/AgentsCloud.git AgentsCloud
cd AgentsCloud
uv sync --locked
uv run agentscloud validate
```

`uv sync --locked` prepara `.venv` a partir do lockfile. A dependência runtime
direta é Questionary; as dependências transitivas e versões estão em `uv.lock`.
Como alternativa sem uv, crie e ative uma venv e execute `python -m pip install -e .`;
essa alternativa resolve as versões permitidas em `pyproject.toml`, sem usar o lockfile.

O clone deve ter uma branch com upstream configurado e checkout limpo para usar
os comandos de sincronização e upload. O upload direto exige permissão de push;
uma branch protegida pode recusar a publicação. A CLI não cria repositório remoto
nem publica a base por conta própria.

Consulte [CONTRIBUTING.md](CONTRIBUTING.md) para contribuições novas, alterações
de agentes existentes, revisão e recuperação. O estado da compatibilidade e o
roteiro de piloto estão em [docs/compatibilidade.md](docs/compatibilidade.md).

## Criar um agente

O formato standalone documentado pelo Codex exige as strings `name`, `description`
e `developer_instructions`. `name` identifica o agente e pode diferir do nome do
arquivo. Outras configurações são opcionais; os exemplos aqui não fixam modelo.
Consulte o [contrato oficial de agentes](https://learn.chatgpt.com/docs/agent-configuration/subagents)
para opções aceitas na versão usada pela equipe.

1. Copie `templates/agente.toml` para a sua pasta pessoal de agentes, com um nome
   novo, por exemplo `meu-documentador.toml`. No PowerShell, a partir do clone:

   ```powershell
   $codexRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' }
   $agentsDir = Join-Path $codexRoot 'agents'
   New-Item -ItemType Directory -Path $agentsDir -Force | Out-Null
   $destino = Join-Path $agentsDir 'meu-documentador.toml'
   if (Test-Path -LiteralPath $destino) { throw 'Esse arquivo já existe; escolha outro nome.' }
   Copy-Item -LiteralPath './templates/agente.toml' -Destination $destino
   ```

2. Edite as três chaves obrigatórias. Use este exemplo original de TOML válido:

   ```toml
   name = "meu-documentador"
   description = "Explica módulos Python a partir do código e dos testes existentes."
   developer_instructions = """
   Leia o módulo e os testes relacionados antes de escrever.
   Explique entradas, saídas e exemplos de uso em português.
   Aponte comportamentos não verificados e não invente resultados de execução.
   """
   ```

3. Use UTF-8. Por convenção **do AgentsCloud**, `name` e o nome do arquivo usam
   letras ASCII, números, hífen ou underscore, começando por letra ou número.
   O arquivo termina em `.toml`; nomes reservados do Windows, como `CON.toml`,
   são recusados. Não diferencie agentes apenas por maiúsculas/minúsculas.
4. Execute `uv run agentscloud upload`, aceite o scan, selecione com **↑/↓ e Enter**,
   informe a categoria e, opcionalmente, o responsável. Revise conteúdo, destino,
   responsável e remoto antes de confirmar.
   **Ctrl+C** cancela a interação. Se recusar o scan, informe um caminho manual.
   A seleção usa o componente [select do Questionary](https://questionary.readthedocs.io/en/stable/pages/types.html#select).
5. O upload copia os bytes originais do TOML, atualiza catálogo e índice, cria um
   commit desses três arquivos e executa push para o upstream da branch atual.
   Nome (`name`) ou arquivo já usado, inclusive com outra caixa, cancela com
   **“Esse nome está indisponível”**.

O diretório pessoal padrão é `~/.codex/agents/`. `CODEX_HOME` substitui a raiz
`~/.codex`, portanto os agentes vão para `CODEX_HOME/agents/` quando configurado.
Veja a [documentação de variáveis do Codex](https://learn.chatgpt.com/docs/config-file/environment-variables).
O comando mostra o caminho efetivo antes de instalar.

Se preferir preparar uma contribuição manual, coloque o TOML em `Agents/`, acrescente
a entrada abaixo a `catalog.toml`, gere o índice e siga o processo Git da equipe:

```toml
[[agents]]
file = "meu-documentador.toml"
category = "Documentação"
maintainer = "A definir" # Opcional; atribuição ainda pendente.
```

```console
uv run agentscloud index
uv run agentscloud validate
```

O catálogo é um arquivo gerenciado: a CLI o reescreve em ordem determinística,
preservando `file`, `category` e `maintainer` quando informado. Comentários e estilos de formatação
do catálogo não são preservados; os TOMLs dos agentes são copiados integralmente.

O responsável é metadado do catálogo, nunca uma chave adicionada ao TOML nativo.
O campo pode ser omitido; se presente, deve ser texto não vazio em uma linha.
Use o nome da pessoa ou equipe que aceitou a manutenção. Os exemplos estão
marcados como **A definir**; essa atribuição permanece pendente para o piloto.
No upload, Enter no campo vazio omite o responsável sem apagar os já cadastrados.

## Atualizar e instalar

```console
uv run agentscloud update
```

1. Com o checkout limpo, o comando busca a branch upstream configurada e valida
   agentes, catálogo e índice remotos. Não presume `origin` nem `main`.
2. Lista agentes disponíveis, destacando novos, alterados e removidos do catálogo.
3. Havendo commits remotos, pergunta **y/n**, com padrão **não**, antes de atualizar
   os arquivos locais por `git merge --ff-only`. Recusar encerra sem instalação.
   O fetch já feito atualiza referências Git, mas não o checkout.
4. Após sincronizar, oferece instalar todos os agentes no destino pessoal exibido.
   Essa oferta também ocorre quando o repositório já está atualizado.
5. Cria a pasta de destino depois do aceite. Arquivos idênticos são preservados;
   conflitos por nome ou arquivo exigem nova confirmação e geram backups únicos
   `*.toml.bak-IDENTIFICADOR`. Recusar mantém o agente pessoal. Se um mesmo `name`
   estava em outro arquivo, a substituição guarda backup e retira o arquivo antigo
   para evitar duas definições da mesma identidade.

Remover um agente do repositório **não apaga** sua cópia pessoal. Links simbólicos,
junções e TOMLs pessoais inválidos são recusados durante a instalação; corrija-os
antes de tentar novamente. Os scripts não executam instruções dos TOMLs.

## Comandos e recuperação

| Comando | Efeito |
| --- | --- |
| `uv run agentscloud update` | Consulta, sincroniza e oferece instalação |
| `uv run agentscloud upload` | Scan ou caminho manual, seleção, commit e push |
| `uv run agentscloud validate` | Valida arquivos, catálogo e índice, sem rede |
| `uv run agentscloud index` | Regenera apenas a seção marcada do README |
| `uv run agentscloud index --check` | Confere o índice sem escrever |
| `uv run python update.py` | Atalho para update, usando a raiz do script |
| `uv run python upload.py` | Atalho para upload, usando a raiz do script |

A opção `--repo CAMINHO` permite indicar outro clone. Os comandos Git exigem
commit inicial, branch com upstream e checkout/índice limpos. Upload também exige
HEAD igual ao remoto consultado, para não publicar commits locais anteriores.
Se o remoto avançou, execute update primeiro. Em divergências, resolva o histórico
manualmente. Não há merge de conflitos nem force push automáticos.

No upload, a confirmação final autoriza cópia, commit e push. Se o commit falhar,
a contribuição copiada fica disponível para inspeção com `git status`; verifique
catálogo/índice e conclua ou desfaça manualmente. Se o push falhar, o commit local
é preservado e seu hash é exibido como publicação pendente. Confira autenticação,
permissões e mudanças no remoto antes de reconciliar e publicar manualmente.

## Validação e compatibilidade

```console
uv run python -m unittest discover -s tests -v
uv run agentscloud validate
uv run agentscloud index --check
```

Os testes usam remotos Git e diretórios pessoais temporários; não publicam nem
instalam agentes na conta real. A base tem testes executados no Windows com
Python 3.11 e Git. O uso de APIs portáveis prepara macOS/Linux, mas esses sistemas
ainda precisam de execução de testes e piloto. Validação TOML é estrutural: não
comprova carregamento, seleção ou execução do agente em uma sessão real do Codex.

O workflow [.github/workflows/validate.yml](.github/workflows/validate.yml) exige
Git e executa esses checks com Python 3.11 em Windows, Linux e macOS após push ou
pull request. Consulte os resultados por commit no [GitHub Actions](https://github.com/samvieiracar-debug/AgentsCloud/actions).
A existência do workflow não comprova uma execução aprovada nem a homologação
do runtime Codex; veja [evidências e pendências](docs/compatibilidade.md).

## Índice de Agentes

As frases da coluna Sintaxe são exemplos de pedidos em linguagem natural ao Codex;
não representam comandos de barra. O texto gerado entre os marcadores deve ser
atualizado com `agentscloud index`.

<!-- agentscloud:index:start -->

### Desenvolvimento

| Nome | Sintaxe | Categoria | Descrição | Responsável |
| --- | --- | --- | --- | --- |
| [revisor-codigo](Agents/revisor-codigo.toml) | Use o agente revisor-codigo para … | Desenvolvimento | Revisa uma alteração de código e aponta defeitos reproduzíveis e riscos de regressão. | A definir |

### Documentação

| Nome | Sintaxe | Categoria | Descrição | Responsável |
| --- | --- | --- | --- | --- |
| [documentador](Agents/documentador.toml) | Use o agente documentador para … | Documentação | Escreve documentação técnica a partir do comportamento confirmado no código. | A definir |

### Qualidade

| Nome | Sintaxe | Categoria | Descrição | Responsável |
| --- | --- | --- | --- | --- |
| [planejador-testes](Agents/planejador-testes.toml) | Use o agente planejador-testes para … | Qualidade | Propõe testes a partir de requisitos, casos de borda e riscos de regressão. | A definir |

<!-- agentscloud:index:end -->
