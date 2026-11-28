# Changelog

Todas as alterações notáveis neste projeto serão documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e este projeto adere ao [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Corrigido

- **Conversor do lake não grava mais dado errado sem erro.** Antes, planilha sem a coluna `Concurso` usava a primeira coluna no lugar; sem colunas de bolas gravava `dezenas` vazio; linha com número de concurso ilegível sumia sem registro; e prêmio ou número de ganhadores ausentes no JSON viravam zero. Agora: planilha sem a coluna do concurso (`Concurso` ou, na Loteria Federal, `Extração`) ou, fora da Federal e da Loteca, sem colunas de bolas é erro do arquivo (a mensagem lista as colunas encontradas, nada é gravado e a conversão sai com erro); linhas com número ilegível são contadas num aviso e, acima de 1% das linhas, o arquivo inteiro é erro; campo ausente no JSON de detalhe (`faixa`, `descricaoFaixa`, `numeroDeGanhadores`, `valorPremio`, `municipio`, `uf`, `ganhadores`) vira nulo, e zero só quando a fonte informa zero. O esquema do Parquet não muda (as colunas já aceitavam nulo).
- **Conversor com entrada ausente é erro.** Diretório de entrada inexistente, ou `concursos`/`detalhe` ausente quando o dataset foi pedido por nome (ou quando faltam os dois), devolvia resultado vazio sem erro; agora entra em `errors`. Arquivo de modalidade desconhecida é ignorado com aviso.
- **Manifestos laterais do acervo (`*.json.manifest.json`) são ignorados na descoberta do detalhe**, sem aviso de modalidade desconhecida.
- **`sync` usa o host que a Caixa publica.** O catálogo gravava o host fixo em todas as URLs e só o `backfill` tentava resolvê-lo, e mesmo ali a leitura do `params.txt` nunca funcionava (passava `timeout` ao `get`, que não o aceita, e caía sempre no host fixo). Agora a leitura funciona, o `sync` (e o `--from-plan`) resolve o host uma vez por execução e o fixo fica como reserva, com aviso quando a leitura falha ou a resposta não traz o endereço. Um host novo entra na política de tráfego.
- **`--summary-json` do `sync` traz os contadores.** O download próprio do plugin não preenchia `last_download_stats`; agora `downloaded`, `skipped`, `bytes_downloaded` e `failed` saem com valores.
- **`backfill`:** o JSON baixado é validado (uma página HTML com `200` não vira mais um `.json`); as funções `download_contest` e `download_xlsx` passam `source_id`, `dataset_id` e `producer` ao core (antes a chamada real terminava em `TypeError`); um único cliente por execução (o `params.txt` é lido uma vez, não por concurso); e a modalidade cujo último concurso não veio deixa de ser ignorada com aviso: vira a unidade `<modalidade>:ultimo`, que falha, entra no checkpoint e faz o comando sair com erro.

## [0.3.2] - 2026-11-24

### Corrigido

- **Detalhe do concurso sem linhas num dataset grava o membro vazio.** O detalhe de cada modalidade é um arquivo só (o concurso mais recente) e a versão nova substitui a anterior. Quando o concurso não teve ganhador por município (`listaMunicipioUFGanhadores` vazia), o conversor não gravava o membro de `ganhadores_municipio` e o grupo ficava com o da versão anterior, cuja origem já não era a vigente (`origem_superada` na auditoria, em `duplasena`, `megasena` e `supersete`). O membro agora vai vazio, com o esquema, e tira do grupo as linhas da versão anterior. Vale também para `rateio`. Como consequência, toda modalidade passa a ter o Parquet agrupado dos dois datasets, mesmo sem linhas.

### Alterado
- CI e infraestrutura alinhados ao template (fetcher-template v0.2.1).
- Sem `DATA_DIR`, o diretório de dados deixa de ser `~/data` e passa a ser `$XDG_DATA_HOME/quantilica` (ou `~/.local/share/quantilica`). Quem define `DATA_DIR` não muda de caminho.

## [0.3.1] - 2026-11-15
### Adicionado
- Testes: identidade do registro conferida.
- Testes com servidor falso que recusa com `429` (com e sem `Retry-After`): as 22 entradas do catálogo terminam, as requisições simultâneas e o espaçamento respeitam a política e o `429` pausa o host inteiro.

### Alterado
- Requer `quantilica-core>=0.23.0` (política por host com token bucket e pausa no `429`).
- Política de tráfego da API da Caixa (`host_policy`): uma requisição a cada 2 s por host, sem rajada, no máximo 2 simultâneas e, num `429`, pausa do host inteiro pelo `Retry-After` do servidor ou, sem ele, por 10 s dobrando a cada `429` seguido.

### Corrigido
- A coleta (`sync`/`pipeline`) deixa de falhar com `HTTP 429` em algumas modalidades: o download da CLI usava um cliente por thread, sem a política por host, e a API recebia as requisições em paralelo. Agora todas as threads compartilham um único cliente com a política, e o número de threads respeita o `max_concurrency` do host.
- CI: o pyproject declara o PyPI antes do índice Quantilica (`[[tool.uv.index]]`), e o workflow perde `--index` e `--index-strategy`. Com a estratégia padrão `first-index`, o `uv sync` só consulta o índice para o que não está no PyPI (`quantilica-analytics`) e deixa de receber o 503 intermitente que o GitHub Pages devolve a caminhos inexistentes.

## [0.3.0] - 2026-11-14

### Adicionado
- O fetcher declara os fatos da fonte (`FetcherInfo`: id canônico, apelidos, órgão, licença, página e cadência) para o registro de fetchers da Quantilica.

### Alterado
- Requer `quantilica-core>=0.19.0` (e `quantilica-cli>=0.17.0` como host).
- `FetcherInfo.licenca` passa a declarar a licença da fonte: Sem licença declarada; dados públicos pela Lei 12.527/2011 (LAI) e Decreto 8.777/2016.

## [0.2.3] - 2026-11-09

### Adicionado
- Documentação dos dados em `docs/`, conforme a norma de documentação dos dados: página, dicionário de todas as variáveis e esquema de referência para cada um dos três datasets. Um teste a verifica.

### Corrigido
- A Lotomania saía sem nenhuma linha na conversão para o lake. A planilha da Caixa não traz o atributo `r` (referência da célula) e, ao reler o arquivo como texto, todas as células iam para a primeira coluna. Agora, sem `r`, a coluna é a posição da célula na linha. Exige reconversão da Lotomania para recuperar os concursos. As demais modalidades não mudam.

## [0.2.2] - 2026-11-06

### Corrigido
- O `backfill` e a leitura do endereço da API deixam de engolir erros: modalidade que falha ao obter o último concurso e falha ao ler o `params.txt` (que cai no host padrão) agora são registradas em `warning`.

### Alterado
- A chave do arquivo bruto no lake passa a ser montada com `composite_file_key` do `quantilica-core` (nome do arquivo e, quando houver, o membro do ZIP), sem mudar as partições.

## [0.2.1] - 2026-11-04

### Corrigido
- `lake`: XLSX que o leitor padrão (calamine) rejeita, por exemplo com célula numérica malformada (`Parse float error: invalid float literal`), é relido como texto, sem descartar linhas; valores em formato brasileiro (`1.234,56`) seguem a regra de conversão existente e células vazias viram nulo.

## [0.2.0] - 2026-11-04

### Corrigido
- Lake: `rateio` e `ganhadores_municipio` gravam cada concurso como membro do arquivo
  agrupado `<modalidade>.parquet` (`LakeWriter.write_member`). Antes, a modalidade
  inteira era escrita com o primeiro JSON como origem: reconverter após um concurso novo
  era pulado por sha256 e as linhas dos demais concursos se perdiam.
- Lake: `converted` não conta mais escritas puladas (`skipped` separado). JSON ilegível
  ou sem número de concurso vira erro contado, não arquivo vazio.
- Sem o extra `analysis`, o comando `convert` termina com código 1 e a instrução de instalação (`quantilica install loterias --extra analysis`), sem traceback.

### Alterado
- O nome-base dos arquivos brutos vem de `file_key` do `quantilica-core`, com resultado idêntico no lake.

## [0.1.0] - 2026-11-01

### Adicionado
- Versão inicial do pacote `loterias-fetcher` (`quantilica loterias`).
- Suporte a `list`, `check`, `sync` e verificação de frescor via SDK `FetcherApp`.

- Conversor Universal Hive Parquet Lake com `DatasetSpec` em `lake.py`.

