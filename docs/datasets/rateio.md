---
dataset:
  id: rateio
  fonte: loterias
  titulo: Rateio de prêmios por concurso
  resumo: Faixas de premiação de um concurso, com o número de ganhadores e o valor do prêmio de cada faixa.
  orgao: Caixa Econômica Federal
  pagina_oficial: https://loterias.caixa.gov.br
  licenca: "Não informada pela fonte: a página inicial do portal de loterias da Caixa não traz licença nem termo de uso dos dados (conferido em 2026-11-09)."
  periodicidade: "um concurso por sorteio; o JSON do último concurso muda a cada sorteio (a Caixa não informa a frequência)"
  cobertura: {inicio: 2026-10, fim: em-curso}
  unidade: uma faixa de premiação de um concurso de uma modalidade
  granularidade: {espacial: nacional, temporal: dia}
  formato_bruto: JSON da API do portal de loterias, um arquivo por coleta (último concurso) ou por concurso (comando backfill), UTF-8
  lake: {estado: convertido, particoes: [modalidade], chave: [modalidade, concurso, faixa], colunas: 6}
  unidades_de_medida:
    concurso: número do concurso
    faixa: ordem da faixa de premiação
    ganhadores: ganhadores, como informado pela fonte
    valor_premio: R$
  dados_pessoais: nenhum
  eras: []
  revisado_em: 2026-11-09
  versao_fetcher: 0.2.2
---

# Rateio de prêmios por concurso

## Resumo

Para cada concurso, as faixas de premiação (por exemplo, "6 acertos", "5 acertos") com o número de ganhadores e o valor pago a cada um. Serve para estudar a distribuição dos prêmios e a frequência de ganhadores em cada faixa.

## Ficha técnica

<!-- gerado:ficha -->

| Campo | Valor |
|---|---|
| Dataset | `loterias/rateio` |
| Órgão | Caixa Econômica Federal |
| Página oficial | https://loterias.caixa.gov.br |
| Licença | Não informada pela fonte: a página inicial do portal de loterias da Caixa não traz licença nem termo de uso dos dados (conferido em 2026-11-09). |
| Periodicidade | um concurso por sorteio; o JSON do último concurso muda a cada sorteio (a Caixa não informa a frequência) |
| Cobertura | 2026-10 a em-curso |
| Unidade (uma linha) | uma faixa de premiação de um concurso de uma modalidade |
| Granularidade | espacial: nacional; temporal: dia |
| Formato bruto | JSON da API do portal de loterias, um arquivo por coleta (último concurso) ou por concurso (comando backfill), UTF-8 |
| Estado no lake | convertido |
| Partições | `modalidade` |
| Chave | `modalidade`, `concurso`, `faixa` |
| Colunas | 6 |
| Unidades de medida | `concurso`: número do concurso; `faixa`: ordem da faixa de premiação; `ganhadores`: ganhadores, como informado pela fonte; `valor_premio`: R$ |
| Dados pessoais | nenhum |
| Eras | nenhuma |
| Revisado em | 2026-11-09 |
| Versão do fetcher | 0.2.2 |

## Origem e coleta

- O fetcher baixa o JSON do concurso pelo endereço `/api/<modalidade>` (último concurso) ou `/api/<modalidade>/<número>` (concurso específico, usado pelo comando `backfill`) da API do portal de loterias.
- No bruto, o arquivo se chama `detalhe/<modalidade>@AAAAMMDD.json` (último concurso, data da coleta) ou `detalhe/<modalidade>_<concurso>@AAAAMMDD.json` (backfill).
- Conferido em 2026-11-09 pela listagem do bruto: há 41 JSONs, todos do tipo "último concurso", coletados entre 2026-11-02 e 2026-11-09, de dois a seis por modalidade; nenhum arquivo de backfill. O JSON de um dia traz só o concurso mais recente naquele dia, então concursos entre duas coletas não aparecem (por exemplo, a Quina tem JSON dos concursos 7157, 7159, 7160, 7161 e 7162, sem o 7158).

## Conteúdo

- Uma linha por faixa de um concurso. O número de faixas varia com a modalidade (conferido nos JSONs mais recentes): Loteca 2, Mega-Sena 3, Quina 4, Dia de Sorte, Lotofácil, Loteria Federal e Super Sete 5, Timemania 6, Lotomania 7, Dupla Sena 8 e +Milionária 10.
- Cobertura no lake: **um concurso por modalidade**, o do JSON mais recente. Na amostra de 2026-11-09, 11 modalidades e 60 linhas.
- O `descricao_faixa` é o texto da fonte: "6 acertos", "5 acertos + 1 ou nenhum trevo" (+Milionária), "1º (14 acertos)" (Loteca). Na Loteria Federal a fonte rotula as cinco faixas como "1 acertos" a "5 acertos", embora sejam os cinco prêmios da extração.

## Variáveis

| Coluna no lake | Na fonte | Tipo | Descrição | Unidade / códigos | Período |
|---|---|---|---|---|---|
| `concurso` | `numero` (ou `concurso`) | inteiro | Número do concurso | — | todo |
| `faixa` | `faixa` (ou `ordem`) | inteiro | Ordem da faixa de premiação, a partir de 1 | — | todo |
| `descricao_faixa` | `descricaoFaixa` | texto | Descrição da faixa, como a fonte publica | — | todo |
| `ganhadores` | `numeroDeGanhadores` | inteiro | Número de ganhadores da faixa; zero quando a faixa não teve ganhador ou a fonte não informou | ganhadores | todo |
| `valor_premio` | `valorPremio` | decimal | Valor do prêmio de cada ganhador da faixa; zero quando a faixa não teve ganhador ou a fonte não informou | R$ | todo |
| `_origem` | — (gerada) | texto | Chave do arquivo bruto de onde a linha veio (na amostra, o nome da modalidade) | — | todo |
| `modalidade` | — (nome do arquivo) | texto | Modalidade em minúsculas | ver [concursos](concursos.md) | todo |

## No lake

- Dataset `loterias/rateio`, particionado por `modalidade`; um Parquet por modalidade, com as linhas de cada arquivo bruto de origem (`_origem`).
- O conversor lê a lista `listaRateioPremio` do JSON. Todo o resto do JSON fica de fora: data, dezenas, valores acumulados, arrecadação, local do sorteio e próximo concurso.
- Valores ausentes viram zero (`faixa`, `ganhadores`, `valor_premio`) ou texto vazio (`descricao_faixa`).
- Um JSON ilegível ou sem número de concurso é contado como erro e não gera linhas.
- Para cada modalidade, o conversor usa só a versão mais recente entre os arquivos de mesmo nome base; por isso os JSONs diários mais antigos não entram no lake.

## Cuidados de uso

- **Cobertura mínima.** O lake tem só o último concurso de cada modalidade na data da coleta. Para a série histórica de rateio, é preciso rodar o `backfill`; sem ele, não use este dataset para tendências.
- **Zero não é ausência.** Uma faixa sem ganhadores tem `ganhadores` e `valor_premio` iguais a zero; o conversor também grava zero quando o campo falta no JSON.
- **O valor é por ganhador**, não o total da faixa. O total é `ganhadores * valor_premio`.
- **Federal:** as "faixas" são os cinco prêmios da extração, rotulados "N acertos" pela fonte.
- **Valores brutos de imposto.** A fonte não informa se os valores são antes ou depois do imposto de renda sobre prêmios; a planilha de Super Sete avisa que os valores do link "Locais da Sorte" são brutos, sem desconto.

## Exemplos

Valor total pago por faixa no último concurso de cada modalidade:

```python
import polars as pl

r = pl.scan_parquet("lake/loterias/rateio/**/*.parquet", hive_partitioning=True)
total_por_faixa = (
    r.with_columns((pl.col("ganhadores") * pl.col("valor_premio")).alias("total"))
    .select("modalidade", "concurso", "faixa", "descricao_faixa", "ganhadores", "total")
    .sort("modalidade", "faixa")
    .collect()
)
```

## Referências

- Portal de loterias da Caixa: https://loterias.caixa.gov.br
