# Contribuir com o AgentsCloud

O repositório de teste é [samvieiracar-debug/AgentsCloud](https://github.com/samvieiracar-debug/AgentsCloud).
Novos agentes podem ser enviados pela CLI; mudanças em agentes existentes e no
código seguem o fluxo Git de revisão da equipe. O projeto usa Python 3.11+, Git e
uv, com Textual para o hub e Questionary para os comandos tradicionais.

## Preparar o ambiente

```console
git clone https://github.com/samvieiracar-debug/AgentsCloud.git
cd AgentsCloud
uv sync --locked
git status --short
uv run agentscloud validate
```

Configure seu nome e e-mail Git caso ainda não estejam definidos. Antes de usar
`upload` ou `update`, o checkout e o índice devem estar limpos, inclusive sem
arquivos não rastreados. Guarde suas alterações em commits próprios ou resolva-as
antes de continuar. O upstream identifica o remoto e a branch de destino.

Para usar o fluxo visual, abra `hub.cmd`, execute `python hub.py` ou, no ambiente
instalado, `agentscloud hub`. A central reúne Update, Upload e Diagnóstico;
Upload apresenta a revisão por etapas e Update permite instalar o catálogo
inteiro ou selecionar agentes por categoria. As confirmações de instalação,
substituição de arquivos e publicação continuam sendo necessárias.

O hub não faz pull nem prepara dependências ao abrir. Quando as dependências
mudarem, feche a central e execute `uv sync --locked` na pasta do atalho.
`python hub.py --repo CAMINHO` opera outro clone de dados com a `.venv` e o código
da pasta do atalho; sem `--repo`, opera essa própria pasta. O diagnóstico
independente em `diagnostico.cmd`/`python diagnostico.py` funciona sem o ambiente
visual e continua disponível para recuperar a instalação.

## Enviar um agente novo

1. Siga o [guia e template do README](README.md#criar-um-agente). Prepare o arquivo
   em `CODEX_HOME/agents/`, ou `~/.codex/agents/` quando a variável não estiver
   definida. Também é possível escolher outro caminho pelo modo manual.
2. Escolha um `name` e um arquivo ainda não utilizados. A identidade vem de
   `name`; diferença de maiúsculas/minúsculas não torna um nome disponível.
3. Execute `uv run agentscloud upload`. Aceite o scan e use ↑/↓ e Enter para
   selecionar, ou recuse o scan e informe o caminho do TOML.
4. Informe a categoria e, se houver atribuição aceita, o responsável pela
   manutenção. Deixar o responsável vazio omite esse campo.
5. Confira os bytes exibidos, destino, categoria, responsável, remoto e branch.
   A confirmação final, com padrão **não**, autoriza cópia, commit e push.
   Ctrl+C cancela a interação.

O upload cria um commit apenas com o novo agente, `catalog.toml` e `README.md`.
Para criar uma contribuição nova, exige HEAD igual ao upstream consultado.
Se houver commits locais adiantados, oferece revisar e publicar todo o conjunto
com confirmação específica, encerrando essa rodada sem scan nem novo commit.
Se houver novidades remotas, execute `uv run agentscloud update` antes de tentar
contribuir novamente. Nome ou arquivo ocupado cancela com **“Esse nome está
indisponível”**; o upload não substitui um agente existente.

O envio direto exige permissão de push. Se a política da equipe exigir pull
request, prepare a contribuição em uma branch e publique-a pelo fluxo Git manual.
A CLI não cria pull requests nem altera as regras da branch.

## Categoria e responsável

O arquivo do agente contém apenas sua configuração nativa. Metadados da equipe
ficam no catálogo:

```toml
[[agents]]
file = "documentador.toml"
category = "Documentação"
maintainer = "A definir"
```

`file` e `category` são obrigatórios; `maintainer` é opcional. Categoria e
responsável informado devem ser strings não vazias, de uma linha, sem espaços
nas bordas. Outras chaves são recusadas. O nome da pessoa/equipe deve corresponder
a uma atribuição aceita; não é inferido do autor Git ou do dono do repositório.

**A definir** indica uma pendência. Os três exemplos usam esse marcador até a
equipe assumir sua manutenção. Em um catálogo com responsáveis, ausência do campo aparece como **Não informado**.
Catálogos inteiramente sem responsável preservam o índice original de quatro
colunas; a coluna Responsável aparece quando houver ao menos uma atribuição ou
marcador. Catálogos antigos permanecem válidos, inclusive com o README legado.

O catálogo é reserializado em ordem determinística, preservando os responsáveis
existentes e os campos suportados. Seus comentários e formatação não são
preservados. Os bytes dos TOMLs nativos são copiados integralmente.

## Alterar agentes existentes ou o código

Use uma branch baseada na versão atual da equipe. No remoto de teste, o ponto de
partida previsto é `main`; confirme a branch antes dos comandos:

```console
git switch main
git pull --ff-only
git switch -c contrib/documentador
```

Edite o agente e seus metadados, quando necessário. Mantenha o escopo da alteração
claro: o problema observado, o comportamento esperado e exemplos que permitam
revisar o resultado. Antes de compartilhar, confira que o conteúdo não inclui
credenciais ou dados restritos.

Depois de editar:

```console
uv run agentscloud index
uv run python -m unittest discover -s tests -v
uv run agentscloud validate
uv run agentscloud index --check
```

Adicione ao índice somente os arquivos da contribuição, revise-os e faça commit.
Este exemplo cobre uma alteração no agente documentador:

```console
git add Agents/documentador.toml catalog.toml README.md
git diff --cached
git commit -m "Melhora as instruções do documentador"
git push -u origin HEAD
```

Abra a revisão no GitHub conforme o processo da equipe. Para alterações no código,
inclua testes que observem o comportamento alterado. Se dependências mudarem,
atualize `pyproject.toml` e `uv.lock` juntos e confira `uv sync --locked`.

## Checks da contribuição

O [workflow de validação](.github/workflows/validate.yml) roda em pushes e pull
requests com Python 3.11 em Windows, Linux e macOS. Ele exige Git, prepara o
ambiente pelo lockfile, executa a suíte e confere catálogo/índice. Falta de Git deve
falhar antes da suíte, evitando que todos os testes Git sejam pulados.

Os testes usam repositórios bare, clones e homes temporários. Não execute
`update` ou `upload` contra o remoto ou perfil pessoal real apenas para testar a
implementação. Um skip por restrição de symlink deve aparecer no resultado,
junto do sistema e da razão; não equivale a um teste aprovado.

Consulte o resultado do commit no [GitHub Actions](https://github.com/samvieiracar-debug/AgentsCloud/actions).
A validação automática não comprova que o Codex carregou e executou os agentes;
esse aceite está separado no [roteiro de compatibilidade](docs/compatibilidade.md).

## Recuperar uma contribuição interrompida

Se a cópia ocorreu e o commit falhou, os arquivos permanecem disponíveis. Confira
`git status` e `git diff --cached`, corrija a causa e valide catálogo/índice antes
de concluir manualmente o commit ou desfazer somente sua contribuição.

Se o push falhou, a CLI preserva o commit e consulta o destino efetivo de escrita.
Se o SHA já estiver contido no remoto, confirma a publicação mesmo que a resposta
do push tenha falhado. Caso contrário, informa pendência ou resultado incerto e
pode oferecer uma única tentativa adicional, sempre com nova confirmação.

Para retomar, execute `upload`. Revise todos os SHA, assuntos, arquivos e destino
apresentados: o aceite publica o conjunto inteiro de commits locais adiantados,
inclusive commits preparados manualmente. O fluxo revalida o estado e envia
exatamente o SHA aprovado. Recusar preserva os commits; essa rodada não faz scan,
cópia nem novo commit. A revisão e as regras da equipe continuam aplicáveis.

Se o histórico divergiu ou o destino mudou durante a confirmação, reconcilie
manualmente antes de repetir. Não há reset, stash, rebase ou force push
automático. `update` aceita HEAD adiantado e oferece instalar seu catálogo local
com aviso e consentimento; isso não publica os commits.

Use `python diagnostico.py` ou `diagnostico.cmd` para conferir ferramentas,
ambiente, dependências, identidade Git, upstream, conectividade e eventos
recentes. O diagnóstico funciona sem Questionary/venv e oferece reparos
opcionais confirmados. Nome/e-mail de commit não autenticam no servidor; leitura
remota pública não comprova acesso de escrita. A causa de uma falha antiga sem
log não pode ser deduzida só do estado atual. Veja [diagnóstico](docs/diagnostico.md)
para limites de tempo, modo offline e relatório sanitizado.

Arquivos pessoais idênticos são preservados na instalação. Substituições aceitas
geram backups `*.toml.bak-IDENTIFICADOR`; para recuperar um deles, revise o
conteúdo e o nome de destino antes de restaurar. Remover um agente do catálogo
não exclui sua instalação pessoal.
