"""Referência dos comandos públicos apresentada na ajuda do hub."""

HUB_HELP = r"""COMO USAR ESTA REFERÊNCIA

Execute os comandos em um terminal, a partir da pasta do projeto. Esta ajuda apenas apresenta a referência; ela não executa comandos.
Substitua CAMINHO e ARQUIVO pelos valores desejados. Use aspas em caminhos com espaços. Itens entre [colchetes] são opcionais; não digite os colchetes.
PageUp/PageDown ou a roda do mouse percorrem este conteúdo. Esc volta ao hub.

NAVEGAÇÃO NO HUB

F1                 Abre esta ajuda.
F2                 Seleciona Update.
F3                 Seleciona Upload.
F4                 Seleciona Diagnóstico.
Tab / Shift+Tab    Move o foco entre os controles.
Setas              Navegam pelas opções e listas.
Espaço             Marca ou desmarca um agente.
Enter              Ativa a opção ou o botão em foco.
PageUp / PageDown  Percorre conteúdo, revisão e atividade.
Esc                Cancela a pergunta ou solicita parar a operação.
Ctrl+Q / Ctrl+C    Sai quando não há operação em andamento.

O filtro de categorias preserva os agentes já marcados. Durante uma operação, o cancelamento aguarda a etapa atual; alterações já concluídas permanecem. Para sair, aguarde o término e use Ctrl+Q novamente.

PREPARAR O AMBIENTE

uv sync --locked
  Prepara ou atualiza a .venv conforme o uv.lock. Pode baixar e instalar dependências; não sincroniza o repositório Git.

Os exemplos usam uv run para executar no ambiente do projeto. Esse prefixo pode preparar o ambiente antes do comando. Se o ambiente já estiver ativo e o pacote instalado, também pode usar agentscloud COMANDO ou python -m agentscloud COMANDO.

ABRIR O HUB

uv run agentscloud hub [--repo CAMINHO]
  Abre a central de Update, Upload e Diagnóstico. Exige terminal interativo e só inicia uma operação quando você a escolhe.

python hub.py [--repo CAMINHO]
.\hub.cmd [--repo CAMINHO]
  Abrem a mesma central com a .venv já preparada da pasta do atalho. Não fazem pull nem preparam dependências automaticamente. A versão .cmd é para Windows e também aceita duplo clique.

ATUALIZAR E INSTALAR AGENTES

uv run agentscloud update [--repo CAMINHO]
  Consulta o upstream, mostra as alterações e pede confirmação antes de atualizar o clone por fast-forward. Depois permite instalar o catálogo inteiro ou selecionar agentes com filtro por categoria. Conflitos pessoais exigem confirmação e geram backup quando substituídos.

python update.py [--repo CAMINHO]
.\update.cmd [--repo CAMINHO]
  Fazem git pull automaticamente, preparam a .venv com uv sync --locked e iniciam Update. As confirmações de instalação e substituição continuam presentes.

ENVIAR AGENTES E RETOMAR PUBLICAÇÕES

uv run agentscloud upload [--repo CAMINHO]
  Oferece scan dos agentes pessoais ou entrada manual do arquivo. Solicita categoria e responsável opcional, apresenta dados e conteúdo por etapas e pede confirmação antes de copiar, criar commit e executar push.
  Havendo commits locais pendentes, oferece revisar e publicar esse conjunto em uma rodada própria, sem preparar outra contribuição.

python upload.py [--repo CAMINHO]
.\upload.cmd [--repo CAMINHO]
  Fazem git pull automaticamente, preparam a .venv com uv sync --locked e iniciam Upload. A publicação continua dependendo de confirmação.

Update e Upload exigem branch com upstream e repositório sem alterações pendentes. A instalação pessoal usa CODEX_HOME/agents quando configurado; caso contrário, ~/.codex/agents.

VALIDAR O CATÁLOGO E O ÍNDICE

uv run agentscloud validate [--repo CAMINHO]
  Valida os TOMLs, o catálogo e o índice do README. A validação da CLI não consulta a rede nem regrava esses arquivos.

uv run agentscloud index [--repo CAMINHO]
  Regenera a seção marcada do índice de agentes no README, preservando o restante do documento. Este comando escreve no README.

uv run agentscloud index --check [--repo CAMINHO]
  Confere agentes, catálogo e consistência do índice sem regravar o README.

DIAGNÓSTICO E REPAROS

python diagnostico.py [--repo CAMINHO] [--offline] [--non-interactive] [--repair] [--output ARQUIVO.json]
  Verifica ferramentas, dependências, Git e eventos recentes. Funciona sem a .venv, Textual ou Questionary. Em terminal interativo, oferece reparos com confirmação individual.

.\diagnostico.cmd
  Abre o diagnóstico no Windows. Aceita as mesmas opções de diagnostico.py e também pode ser aberto por duplo clique.

Opções do diagnóstico:
  --repo CAMINHO       Escolhe o clone a verificar.
  --offline           Pula consultas remotas; eventual reparo uv também usa modo offline.
  --non-interactive   Somente relata: não pergunta nem executa reparos.
  --repair            Solicita a oferta de reparos, já padrão em terminal interativo. Não autoriza alterações automaticamente.
  --output ARQUIVO.json
                      Exporta o relatório sanitizado para um arquivo novo; recusa sobrescrever um arquivo existente.
  -h / --help         Mostra a ajuda e encerra.

Exemplos:
  python diagnostico.py --offline --non-interactive
    Faz somente verificações locais, sem perguntas ou reparos.
  python diagnostico.py --non-interactive --output diagnostico.json
    Gera um relatório novo sem reparar; pode consultar o remoto.
  .\diagnostico.cmd --repo "C:/Projetos/AgentsCloud" --offline
    Verifica esse clone sem consulta remota e oferece reparos confirmados se o terminal for interativo.

As opções de diagnóstico não pertencem aos comandos hub, update ou upload. Não existe o subcomando agentscloud diagnostico; use diagnostico.py, diagnostico.cmd ou a página Diagnóstico do hub.

ESCOLHER OUTRO REPOSITÓRIO

uv run agentscloud --repo CAMINHO COMANDO
uv run agentscloud COMANDO --repo CAMINHO
  As duas posições de --repo são aceitas. COMANDO pode ser hub, update, upload, validate ou index. Na CLI instalada, --repo troca os dados; o código e o ambiente continuam os instalados.

python hub.py --repo CAMINHO
  Troca somente o clone de dados. O código e a .venv continuam na pasta de hub.py.

python update.py --repo CAMINHO
python upload.py --repo CAMINHO
  Escolhem o clone completo que receberá o pull, a preparação da .venv e a execução do código desse clone. Os atalhos .cmd correspondentes seguem a mesma regra.

Nos atalhos, o padrão é a pasta do script; na CLI instalada, é o diretório atual. Caminhos relativos são resolvidos a partir do terminal que iniciou o comando.

CONSULTAR A SINTAXE NO TERMINAL

uv run agentscloud --help
  Lista os subcomandos e as opções gerais.

uv run agentscloud COMANDO --help
  Mostra as opções do subcomando escolhido.

python hub.py --help
python update.py --help
python upload.py --help
python diagnostico.py --help
  Mostram a ajuda dos atalhos sem preparar o ambiente nem executar suas operações. Os quatro arquivos .cmd também aceitam -h e --help.

VERIFICAÇÕES E DESENVOLVIMENTO

uv run python -m unittest discover -s tests -v
  Executa a suíte de testes com detalhes, usando repositórios Git e perfis temporários. A suíte inclui o laboratório de simulação.

uv run python scripts/simular_fluxo.py --destino CAMINHO_NOVO
  Executa o roteiro de laboratório local com respostas simuladas. O destino deve ser uma pasta inexistente. Esse roteiro depende das fixtures de simulação; há uma fixture ausente no estado atual. Consulte docs/simulacao.md.

uv run python scripts/simular_fluxo.py --help
  Mostra a sintaxe do roteiro sem criar o laboratório.

Instalação alternativa, sem uv:
  python -m venv .venv
    Cria um ambiente virtual. A ativação depende do seu terminal.
  python -m pip install -e .
    Execute dentro da venv criada e ativada. Instala o projeto em modo editável com as versões permitidas pelo pyproject.toml; essa alternativa não usa o uv.lock.

AUTENTICAÇÃO E AMBIENTE

O hub utiliza credenciais Git já disponíveis. Se for necessário login interativo, use update.cmd ou upload.cmd fora do hub e volte à central.
Reparos que precisem recriar a .venv devem ser feitos com o hub fechado, pelo diagnostico.cmd ou por python diagnostico.py usando um Python externo à .venv.
"""
