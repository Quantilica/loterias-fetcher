# Changelog

Todas as alterações notáveis neste projeto serão documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e este projeto adere ao [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado
- Documentação dos dados em `docs/`, conforme a norma de documentação dos dados: página, dicionário de todas as variáveis e esquema de referência para cada um dos três datasets. Um teste a verifica.

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

