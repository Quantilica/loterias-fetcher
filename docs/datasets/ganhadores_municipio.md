---
dataset:
  id: ganhadores_municipio
  fonte: loterias
  titulo: Municípios dos ganhadores por concurso
  resumo: Município e UF dos ganhadores de um concurso, com o número de ganhadores em cada local.
  orgao: Caixa Econômica Federal
  pagina_oficial: https://loterias.caixa.gov.br
  licenca: "Não informada pela fonte: a página inicial do portal de loterias da Caixa não traz licença nem termo de uso dos dados (conferido em 2026-11-09)."
  periodicidade: "um concurso por sorteio; o JSON do último concurso muda a cada sorteio (a Caixa não informa a frequência)"
  cobertura: {inicio: 2026-10, fim: em-curso}
  unidade: um município (ou canal eletrônico) com ganhadores em um concurso de uma modalidade
  granularidade: {espacial: município, temporal: dia}
  formato_bruto: JSON da API do portal de loterias, um arquivo por coleta (último concurso) ou por concurso (comando backfill), UTF-8
  lake: {estado: convertido, particoes: [modalidade], chave: [modalidade, concurso, posicao], colunas: 6}
  unidades_de_medida:
    concurso: número do concurso
    posicao: ordem do município na lista da fonte
    ganhadores: ganhadores, como informado pela fonte
  dados_pessoais: nenhum
  eras: []
  revisado_em: 2026-11-09
  versao_fetcher: 0.2.2
---

# Municípios dos ganhadores por concurso

## Resumo

Lista dos municípios onde foram feitas as apostas ganhadoras de um concurso, com o número de ganhadores em cada um. Apostas feitas pela internet ou pelo aplicativo aparecem como "CANAL ELETRONICO". Serve para ver onde os prêmios principais saem.

## Ficha técnica

<!-- gerado:ficha -->

| Campo | Valor |
|---|---|
| Dataset | `loterias/ganhadores_municipio` |
| Órgão | Caixa Econômica Federal |
| Página oficial | https://loterias.caixa.gov.br |
| Licença | Não informada pela fonte: a página inicial do portal de loterias da Caixa não traz licença nem termo de uso dos dados (conferido em 2026-11-09). |
| Periodicidade | um concurso por sorteio; o JSON do último concurso muda a cada sorteio (a Caixa não informa a frequência) |
| Cobertura | 2026-10 a em-curso |
| Unidade (uma linha) | um município (ou canal eletrônico) com ganhadores em um concurso de uma modalidade |
| Granularidade | espacial: município; temporal: dia |
| Formato bruto | JSON da API do portal de loterias, um arquivo por coleta (último concurso) ou por concurso (comando backfill), UTF-8 |
| Estado no lake | convertido |
| Partições | `modalidade` |
| Chave | `modalidade`, `concurso`, `posicao` |
| Colunas | 6 |
| Unidades de medida | `concurso`: número do concurso; `posicao`: ordem do município na lista da fonte; `ganhadores`: ganhadores, como informado pela fonte |
| Dados pessoais | nenhum |
| Eras | nenhuma |
| Revisado em | 2026-11-09 |
| Versão do fetcher | 0.2.2 |

## Origem e coleta

- Vem do mesmo JSON do dataset [`rateio`](rateio.md) (lista `listaMunicipioUFGanhadores`): `/api/<modalidade>` para o último concurso e `/api/<modalidade>/<número>` para um concurso específico (comando `backfill`).
- No bruto, o arquivo se chama `detalhe/<modalidade>@AAAAMMDD.json` ou `detalhe/<modalidade>_<concurso>@AAAAMMDD.json`.
- Conferido em 2026-11-09 pela listagem do bruto: 41 JSONs de "último concurso", coletados entre 2026-11-02 e 2026-11-09, sem arquivos de backfill.

## Conteúdo

- Uma linha por município com ganhadores no concurso. Concursos sem ganhadores na lista não geram linhas, então o dataset não tem todas as modalidades: na amostra de 2026-11-09 (JSON mais recente de cada modalidade) só cinco das onze tinham a lista preenchida (Dupla Sena, Loteria Federal, Loteca, Lotofácil e Mega-Sena), com 10 linhas.
- Cobertura no lake: **um concurso por modalidade**, o do JSON mais recente.
- Na Loteria Federal a lista traz cinco locais por extração, com `ganhadores` igual a zero na amostra.

## Variáveis

| Coluna no lake | Na fonte | Tipo | Descrição | Unidade / códigos | Período |
|---|---|---|---|---|---|
| `concurso` | `numero` (ou `concurso`) | inteiro | Número do concurso | — | todo |
| `posicao` | `posicao` | inteiro | Posição do município na lista da fonte | — | todo |
| `municipio` | `municipio` | texto | Nome do município em maiúsculas e sem acento, ou `CANAL ELETRONICO` | — | todo |
| `uf` | `uf` | texto | Sigla da UF em maiúsculas; `--` para o canal eletrônico | sigla | todo |
| `ganhadores` | `ganhadores` (ou `numeroDeGanhadores`) | inteiro | Número de ganhadores no município; zero quando a fonte não informa | ganhadores | todo |
| `_origem` | — (gerada) | texto | Chave do arquivo bruto de onde a linha veio (na amostra, o nome da modalidade) | — | todo |
| `modalidade` | — (nome do arquivo) | texto | Modalidade em minúsculas | ver [concursos](concursos.md) | todo |

## No lake

- Dataset `loterias/ganhadores_municipio`, particionado por `modalidade`; um Parquet por modalidade.
- O conversor lê `listaMunicipioUFGanhadores`; textos perdem espaços nas pontas e a UF vai para maiúsculas. Município ausente vira texto vazio.
- Um concurso sem lista de ganhadores não gera arquivo.
- Como em `rateio`, só o JSON mais recente de cada modalidade é convertido.

## Cuidados de uso

- **Cobertura mínima**: só o último concurso por modalidade; para a série histórica é preciso rodar o `backfill`.
- **Ausência não é zero ganhadores.** Modalidade sem linhas no dataset significa que a lista veio vazia no JSON consultado.
- **`CANAL ELETRONICO` não é município**; filtre-o antes de agregar por UF (a UF vem como `--`).
- **Nomes de município sem acento** e em maiúsculas, como a fonte publica; não há código IBGE, então o cruzamento com outras bases exige tratar nomes.
- **A posição não identifica a faixa.** A fonte não informa a faixa de premiação de cada local nesta lista.

## Exemplos

Ganhadores por UF no último concurso de cada modalidade, sem o canal eletrônico:

```python
import polars as pl

g = pl.scan_parquet("lake/loterias/ganhadores_municipio/**/*.parquet", hive_partitioning=True)
por_uf = (
    g.filter(pl.col("uf") != "--")
    .group_by("modalidade", "uf")
    .agg(pl.col("ganhadores").sum())
    .sort("modalidade", "uf")
    .collect()
)
```

## Referências

- Portal de loterias da Caixa: https://loterias.caixa.gov.br
