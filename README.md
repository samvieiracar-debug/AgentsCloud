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
│   ├── git.py                # Git via processos limitados, sem shell
│   ├── recovery.py           # Revisão de pendências e confirmação de publicação
│   ├── diagnostics.py        # Verificações e reparos opcionais sem Questionary
│   ├── processes.py          # Timeouts, saída sanitizada e logs limitados
│   ├── install.py            # CODEX_HOME, scan, cópia e backup
│   └── errors.py             # Erros esperados da CLI
├── tests/                    # Testes com repositórios e homes temporários
├── .github/workflows/validate.yml # CI Windows, Linux e macOS
├── CONTRIBUTING.md           # Contribuição e recuperação
├── docs/compatibilidade.md   # Evidências e roteiro de homologação/piloto
├── diagnostico.py / diagnostico.cmd # Diagnóstico independente da .venv
├── update.cmd / upload.cmd   # Duplo clique no Windows
├── update.py / upload.py     # Preparação automática e execução do fluxo
├── _launcher.py              # Parser, pull e sync sem dependências externas
├── _runtime.py               # Processo novo com a versão preparada do clone
├── scripts/_launcher_console.ps1 # Detecção do console dos lançadores Windows
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

## Abrir com duplo clique no Windows

Abra **`update.cmd`** para sincronizar/instalar, **`upload.cmd`** para
contribuir ou **`diagnostico.cmd`** para verificar problemas e oferecer reparos.
O diagnóstico usa apenas a biblioteca padrão do Python; funciona sem .venv/Questionary. No Explorador, habilite a exibição das extensões para identificar os
arquivos `.cmd`. Python 3.11+, Git e uv devem estar instalados e disponíveis no PATH.
Os lançadores encontram um Python base por `py` ou `python`, preparam automaticamente
a `.venv` do clone e iniciam o fluxo com esse ambiente, inclusive no primeiro uso.
A janela criada pelo clique aguarda uma tecla no sucesso ou erro.

Os atalhos portáteis `python update.py` e `python upload.py` seguem a mesma
preparação e aguardam Enter quando identificam seu próprio console. Para abrir
um `.py` por clique é necessária uma associação Python funcional; no Windows,
prefira os `.cmd`. A detecção do console dos `.cmd` usa Windows PowerShell.

Se você iniciar o `.py` pelo Python da própria `.venv`, esse processo permanece
vivo durante o sync. No Windows, ele pode impedir que uv recrie o ambiente.
Nesse caso, a operação encerra com erro: feche os processos que usam a `.venv` e
repita pelo `.cmd` ou por um Python externo. O atalho não remove um ambiente em uso.

Em um terminal já aberto ou com entrada/saída redirecionada, os atalhos encerram
com o código da CLI, sem acrescentar pausa. Para consultar a ajuda sem
consultar o remoto nem instalar agentes, execute na pasta do clone:

```powershell
.\update.cmd --help
.\upload.cmd --help
uv run agentscloud validate
```

Se aparecer **checkout sujo**, examine `git status` e resolva suas alterações
antes de sincronizar ou contribuir. A proteção continua valendo nos atalhos.
Se uma política do computador bloquear o script PowerShell ou impedir a
identificação do console, use um terminal já aberto para ler o resultado.
Automações que hospedem os scripts em seu próprio processo Python podem definir
`AGENTSCLOUD_NO_PAUSE=1` para desabilitar explicitamente a pausa.

## Criar um agente

Para o funcionamento correto da indentificação de agentes o usuario deve criar uma pasta chamada 
"agents" dentro da pasta "~/.codex" e instruir ao gpt a criar todos os agentes em .TOML dentro do agents.
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
   Se houver commits locais pendentes, revise e resolva essa rodada primeiro;
   ela termina sem scan nem novo commit. **Ctrl+C** cancela a interação.
   Se recusar o scan de uma contribuição nova, informe um caminho manual.
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
   Essa oferta também ocorre quando o repositório já está atualizado. Se HEAD
   estiver adiantado, informa que há commits não publicados e oferece instalar
   o catálogo local mediante confirmação. Históricos divergentes são recusados.
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
| `uv run agentscloud upload` | Revisa pendências ou prepara e publica uma contribuição nova |
| `uv run agentscloud validate` | Valida arquivos, catálogo e índice, sem rede |
| `uv run agentscloud index` | Regenera apenas a seção marcada do README |
| `uv run agentscloud index --check` | Confere o índice sem escrever |
| `python update.py` / `update.cmd` | Pull automático, sync e fluxo update |
| `python upload.py` / `upload.cmd` | Pull automático, sync e fluxo upload |
| `python diagnostico.py` / `diagnostico.cmd` | Verifica ferramentas, Git, dependências e logs; oferece reparos confirmados |
| `python diagnostico.py --offline --non-interactive` | Diagnóstico local, sem consulta remota nem reparos |

Nos quatro atalhos, `--repo CAMINHO` escolhe o **clone completo** que receberá
todas as fases: Git, ambiente `.venv` e código executado. Sem a opção, usam a pasta
do script; caminhos relativos são resolvidos no diretório original do terminal.
Um atalho no clone A com `--repo B` prepara e executa B. O alvo precisa ser a raiz
Git e conter o produto, incluindo `pyproject.toml` e `uv.lock`. O fluxo mantém
o diretório original do terminal para `CODEX_HOME` relativo e caminhos manuais
de upload.

Após validar os argumentos, os atalhos exigem commit inicial, branch com upstream
e checkout/índice limpos, incluindo arquivos não rastreados. Em seguida executam
`git pull --ff-only --no-rebase --no-autostash` no upstream configurado e
`uv sync --locked` com o lockfile recém-atualizado. O ambiente é sempre a
`.venv` do alvo, mesmo com outra venv ativa ou `UV_PROJECT_ENVIRONMENT` definido.
Um processo novo carrega o código desse clone; não há repetição do bootstrap.

A atualização inicial dos atalhos é automática. As confirmações de instalação
pessoal, substituição de agentes e publicação continuam. Ajuda e argumentos
inválidos encerram antes de Git/uv, sem criar ambiente. Prefira `python update.py`
e `python upload.py` ao usar terminal: `uv run python update.py` pode sincronizar
o ambiente **antes** de iniciar o atalho, fora dessa ordem interna.

Qualquer falha no pull ou sync interrompe o fluxo. Se o pull terminou e o sync
falhou, o checkout atualizado fica preservado; corrija o problema e repita o
atalho. Não há fallback para dependências antigas, reset, stash, rebase ou
resolução automática de divergências. HEAD estritamente adiantado é aceito:
uv prepara as dependências do commit local, e o upload oferece revisar as
pendências. Se HEAD ou upstream mudar após a preparação, execute novamente
para preparar código e dependências juntos.

A entrada instalada `agentscloud` mantém seu comportamento: seu `--repo` indica
o repositório de dados, que pode conter apenas catálogo/agentes, e usa o ambiente
já instalado. O `agentscloud update` valida o catálogo remoto e pede confirmação
antes do fast-forward; os atalhos fazem o pull antes de validar os dados.
Dados inválidos continuam impedindo a instalação/upload. Para criar uma nova
contribuição, o upload exige HEAD igual ao remoto consultado. Havendo commits
estritamente adiantados, abre uma rodada específica de revisão e publicação.

No upload de agente novo, a confirmação final autoriza cópia, commit e push.
Antes do envio, a ferramenta confere o pai, os arquivos, os modos e o conteúdo
do commit contra a contribuição aprovada. Um commit adicional ou alteração por
hook/escritor concorrente interrompe a publicação e fica preservado para revisão.
Se o commit falhar, a contribuição copiada fica disponível para inspeção com
`git status`; verifique catálogo/índice e conclua ou desfaça manualmente.

Se o push falhar ou seu resultado ficar incerto, o commit local é preservado.
O comando consulta a URL efetiva de push para confirmar se o SHA já está no
destino, inclusive se o remoto avançou depois. Quando ainda estiver pendente,
pode oferecer **uma nova tentativa**, com revisão e confirmação próprias;
são no máximo dois pushes por execução, sempre do mesmo SHA.

Execute `upload` novamente para retomar pendências. A prévia lista todos os
commits locais, com SHA, assunto, arquivos e destino. Confirmar autoriza esse
conjunto inteiro; a ferramenta não atribui sua autoria nem presume sua origem.
Recusar mantém os commits. Aceitar revalida checkout, histórico e destino antes
de enviar, sem repetir scan ou criar outra contribuição nessa rodada.
Um destino múltiplo/incoerente ou histórico divergente exige correção manual.

Operações Git com interação permitem o login usual pelo Git/GCM e exibem sua
saída sanitizada durante a execução. Fetch/pull e push têm limite de 180 segundos;
sondagens remotas sem interação usam 30 segundos, comandos locais 10 segundos,
e `uv sync` 300 segundos. Timeout/cancelamento encerra a árvore de processos
iniciada pelo comando. O diagnóstico explica categorias de erro e eventos
recentes; nome/e-mail Git não são login, e leitura pública não comprova permissão
de escrita. Consulte [o guia de diagnóstico](docs/diagnostico.md) para reparos,
logs limitados e exportação do relatório.

## Validação e compatibilidade

```console
uv run python -m unittest discover -s tests -v
uv run agentscloud validate
uv run agentscloud index --check
```

Os testes usam remotos Git e diretórios pessoais temporários; não publicam nem
instalam agentes na conta real. A primeira [execução da CI](https://github.com/samvieiracar-debug/AgentsCloud/actions/runs/34084897708)
aprovou os 43 testes, sem skips, em Windows, Linux e macOS com Python 3.11.
Validação TOML é estrutural: não comprova carregamento, seleção ou execução do
agente em uma sessão real do Codex. O teste local posterior do `documentador`
com registro explícito do TOML está documentado em
[compatibilidade](docs/compatibilidade.md#simulação-e-uso-real-do-documentador-dev-003).
A descoberta automática e o piloto humano ainda precisam de homologação.

O workflow [.github/workflows/validate.yml](.github/workflows/validate.yml) exige
Git e executa esses checks com Python 3.11 em Windows, Linux e macOS após push ou
pull request. Consulte os resultados por commit no [GitHub Actions](https://github.com/samvieiracar-debug/AgentsCloud/actions).
A existência do workflow não comprova uma execução aprovada nem a homologação
do runtime Codex; veja [evidências e pendências](docs/compatibilidade.md).

Para uma demonstração reproduzível com respostas simuladas, Git real e perfis
isolados, consulte [o laboratório de sincronização](docs/simulacao.md).

## Índice de Agentes

As frases da coluna Sintaxe são exemplos de pedidos em linguagem natural ao Codex;
não representam comandos de barra. O texto gerado entre os marcadores deve ser
atualizado com `agentscloud index`.

<!-- agentscloud:index:start -->

### designer

| Nome | Sintaxe | Categoria | Descrição | Responsável |
| --- | --- | --- | --- | --- |
| [designer-cli](Agents/designer-cli.toml) | Use o agente designer-cli para … | designer | Cria interfaces visuais de terminal (CLI/TUI) extremamente personalizadas. Primeiro entende o projeto por alto; depois faz perguntas adaptadas ao usuário e ao script sobre linguagem, tamanho, cores, navegação e funcionalidades, e implementa a interface conforme as respostas. | Samuel Vieira |

### diagnostico

| Nome | Sintaxe | Categoria | Descrição | Responsável |
| --- | --- | --- | --- | --- |
| [diagnosta-agentscloud](Agents/diagnosta-agentscloud.toml) | Use o agente diagnosta-agentscloud para … | diagnostico | Diagnostica o AgentsCloud e explica a arquitetura e os fluxos da main com evidências, coordenando especialistas de leitura quando disponíveis. | Samuel Vieira |

### Documentação

| Nome | Sintaxe | Categoria | Descrição | Responsável |
| --- | --- | --- | --- | --- |
| [documentador](Agents/documentador.toml) | Use o agente documentador para … | Documentação | Escreve documentação técnica a partir do comportamento confirmado no código. | Samuel Vieira |
| [teste-local](Agents/teste-local.toml) | Use o agente teste-local para … | Documentação | Agente simples para verificar o uso de um TOML local no Codex. | Samuel Vieira |

### revisor

| Nome | Sintaxe | Categoria | Descrição | Responsável |
| --- | --- | --- | --- | --- |
| [revisor-codigo](Agents/revisor-codigo.toml) | Use o agente revisor-codigo para … | revisor | Revisa uma alteração de código e aponta defeitos reproduzíveis e riscos de regressão. | Samuel Vieira |

### teste

| Nome | Sintaxe | Categoria | Descrição | Responsável |
| --- | --- | --- | --- | --- |
| [controle-volume](Agents/controle-volume.toml) | Use o agente controle-volume para … | teste | Controla o volume principal de saída do Windows quando o usuário pede para aumentar, diminuir, silenciar, reativar ou definir o volume. | Samuel Vieira |

<!-- agentscloud:index:end -->
