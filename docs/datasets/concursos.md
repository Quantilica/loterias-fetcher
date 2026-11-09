---
dataset:
  id: concursos
  fonte: loterias
  titulo: Concursos das loterias da Caixa
  resumo: Um registro por concurso de cada modalidade, com data, dezenas sorteadas, arrecadação e estimativa de prêmio.
  orgao: Caixa Econômica Federal
  pagina_oficial: https://loterias.caixa.gov.br
  licenca: "Não informada pela fonte: a página inicial do portal de loterias da Caixa não traz licença nem termo de uso dos dados (conferido em 2026-11-09)."
  periodicidade: "um concurso por sorteio; a planilha é refeita a cada atualização do portal (a Caixa não informa a frequência)"
  cobertura: {inicio: 1962-09, fim: em-curso}
  unidade: um concurso de uma modalidade
  granularidade: {espacial: nacional, temporal: dia}
  formato_bruto: XLSX, uma planilha por modalidade, cabeçalho na primeira linha, valores em reais como texto ("R$1.234,56") e datas como texto (dd/mm/aaaa)
  lake: {estado: convertido, particoes: [modalidade], chave: [modalidade, concurso], colunas: 7}
  unidades_de_medida:
    concurso: número do concurso (Loteria Federal e Extração, mesmo número)
    arrecadacao_total: R$
    valor_acumulado: R$
    estimativa_premio: R$
  dados_pessoais: nenhum
  eras: []
  revisado_em: 2026-11-09
  versao_fetcher: 0.2.2
---

# Concursos das loterias da Caixa

## Resumo

Resultado de cada concurso das loterias federais da Caixa: a data do sorteio, as dezenas sorteadas, a arrecadação do concurso e a estimativa de prêmio do concurso seguinte. Serve para estudar a série histórica dos sorteios e da arrecadação de cada modalidade.

## Ficha técnica

<!-- gerado:ficha -->

| Campo | Valor |
|---|---|
| Dataset | `loterias/concursos` |
| Órgão | Caixa Econômica Federal |
| Página oficial | https://loterias.caixa.gov.br |
| Licença | Não informada pela fonte: a página inicial do portal de loterias da Caixa não traz licença nem termo de uso dos dados (conferido em 2026-11-09). |
| Periodicidade | um concurso por sorteio; a planilha é refeita a cada atualização do portal (a Caixa não informa a frequência) |
| Cobertura | 1962-09 a em-curso |
| Unidade (uma linha) | um concurso de uma modalidade |
| Granularidade | espacial: nacional; temporal: dia |
| Formato bruto | XLSX, uma planilha por modalidade, cabeçalho na primeira linha, valores em reais como texto ("R$1.234,56") e datas como texto (dd/mm/aaaa) |
| Estado no lake | convertido |
| Partições | `modalidade` |
| Chave | `modalidade`, `concurso` |
| Colunas | 7 |
| Unidades de medida | `concurso`: número do concurso (Loteria Federal e Extração, mesmo número); `arrecadacao_total`: R$; `valor_acumulado`: R$; `estimativa_premio`: R$ |
| Dados pessoais | nenhum |
| Eras | nenhuma |
| Revisado em | 2026-11-09 |
| Versão do fetcher | 0.2.2 |

## Origem e coleta

- O fetcher baixa a planilha de resultados históricos de cada modalidade pelo endereço `/api/resultados/download?modalidade=<nome>` da API do portal de loterias. O endereço da API é lido de um arquivo de parâmetros do portal; se ele falhar, o fetcher usa o endereço padrão.
- No bruto, o arquivo se chama `concursos/<modalidade>@AAAAMMDD.xlsx`, em que o sufixo é a data da coleta. A planilha traz todos os concursos desde o primeiro; cada versão nova substitui a anterior no lake.
- A Caixa chama a Super Sete de "Super 7" no parâmetro de download (o nome "Super Sete" devolve erro 404).
- Conferido em 2026-11-09 pela listagem do bruto: há versões diárias de 2026-11-02 a 2026-11-09, para as onze modalidades.

## Conteúdo

- Uma linha por concurso. Na Loteria Federal, a linha é uma extração (o número fica na coluna `Extração` da planilha, e o lake o grava em `concurso`).
- Cobertura real, conferida na planilha de 2026-11-07: Mega-Sena 1 a 3082 (1996-03-11 a 2026-11-06), Quina 1 a 7161 (1994-03-13 a 2026-11-06), Lotofácil 1 a 3823 (2003-09-29 a 2026-11-06), Dupla Sena 1 a 3029, Dia de Sorte 1 a 1341 (2018-05-19 em diante), Timemania 1 a 2464 (2008-03-01 em diante), Super Sete 1 a 919 (2020-10-02 em diante), +Milionária 1 a 405 (2022-05-28 em diante), Loteca 1 a 1280 (2002-02-18 em diante), Loteria Federal 6097 extrações entre 1 e 6115 (1962-09-15 a 2026-11-04) e Lotomania 1 a 2996 (1999-10-02 a 2026-11-06) na planilha, mas **zero linhas no lake** (veja os cuidados de uso).
- A planilha tem linhas além dos concursos, com texto livre da Caixa no lugar do número do concurso (avisos e estimativas); o conversor as descarta.
- Dezenas por modalidade, como o lake as grava: Mega-Sena 6; Quina 5; Lotofácil 15; Lotomania 20; Timemania 7; Dia de Sorte 7; +Milionária 6 (os dois trevos não entram); Super Sete 7 (um dígito por coluna do volante); Dupla Sena 12 (os dois sorteios na mesma lista); Loteria Federal e Loteca sem dezenas (veja os cuidados de uso).

## Variáveis

| Coluna no lake | Na fonte | Tipo | Descrição | Unidade / códigos | Período |
|---|---|---|---|---|---|
| `concurso` | `Concurso` (Loteria Federal: `Extração`) | inteiro | Número do concurso | — | todo |
| `data_sorteio` | `Data Sorteio`, `Data do Sorteio` (Mega-Sena) ou `Data de apuração` (Loteca) | texto | Data do sorteio, como a fonte publica | dd/mm/aaaa | todo |
| `dezenas` | colunas `Bola1`, `Bola2`... (Super Sete: `Coluna 1`...) | texto | Dezenas sorteadas, na ordem das colunas da planilha, com dois dígitos e separadas por vírgula e espaço (`04, 05, 30, 33, 41, 52`); vazio quando a modalidade não tem colunas de bolas reconhecidas | — | todo |
| `arrecadacao_total` | `Arrecadação Total` | decimal | Arrecadação do concurso; nulo na Loteria Federal, que não tem a coluna | R$ | todo |
| `acumulado` | `Acumulado <faixa principal>` | booleano | Verdadeiro quando a coluna da fonte vale `Sim`, `true`, `1` ou `S`. Só tem sentido nas modalidades em que a fonte publica `Sim`/`Não` (Dia de Sorte, Dupla Sena, Loteca e +Milionária); nas demais é sempre falso | — | todo |
| `valor_acumulado` | — | decimal | Reservada para o valor acumulado; está nula em todas as linhas | R$ | nunca preenchida |
| `estimativa_premio` | `Estimativa Prêmio` | decimal | Estimativa de prêmio informada pela fonte; nulo na Loteria Federal | R$ | todo |
| `modalidade` | — (nome do arquivo) | texto | Modalidade em minúsculas: `megasena`, `lotofacil`, `quina`, `lotomania`, `timemania`, `duplasena`, `diadesorte`, `supersete`, `maismilionaria`, `federal`, `loteca` | ver descrição | todo |

## No lake

- Dataset `loterias/concursos`, particionado por `modalidade`; um Parquet por modalidade.
- O conversor localiza as colunas pelo nome normalizado (sem acento, minúsculas), porque os nomes variam entre as modalidades. Colunas que ele não reconhece não vão para o lake: ganhadores e rateio por faixa, cidade e UF dos ganhadores, Mês da Sorte, Time do Coração, trevos, jogos da Loteca, prêmios da Loteria Federal, acumulados de sorteios especiais e a observação.
- Valores em reais: remove `R$` e pontos de milhar e troca a vírgula decimal por ponto; `-` e vazio viram nulo.
- Concurso: texto convertido para inteiro; linha sem número de concurso é descartada.
- Se a leitura padrão da planilha falhar, o conversor tenta uma leitura alternativa (registrada em aviso).

## Cuidados de uso

- **Lotomania vem vazia.** A planilha da Lotomania tem 2996 concursos, mas o lake fica com zero linhas: a leitura padrão rejeita a planilha (`Parse float error: invalid float literal`) e a leitura alternativa não lê as células sem referência de coluna (conferido em 2026-11-09, versão 0.2.2, planilha de 2026-11-07).
- **`acumulado` só vale em quatro modalidades.** Em Mega-Sena, Quina, Lotofácil, Super Sete e Timemania a coluna da fonte traz o valor acumulado em reais, e `acumulado` sai sempre falso (0 verdadeiros em 3082, 7161, 3823, 919 e 2464 concursos). Em Dia de Sorte, Dupla Sena, Loteca e +Milionária vale `Sim`/`Não` (951 de 1341, 2752 de 3029, 581 de 1280 e 403 de 405 concursos verdadeiros, conferido na amostra de 2026-11-07). Não use a coluna como indicador geral de acúmulo.
- **`valor_acumulado` é sempre nula**, mesmo onde a fonte publica o valor acumulado.
- **Zeros antigos.** Nos primeiros concursos de várias modalidades a fonte traz `R$0,00` em arrecadação e estimativa (Mega-Sena: 1069 concursos com arrecadação zero; Quina: 2055). Provavelmente é informação ausente, não zero real, mas a fonte não explica; trate com cuidado em somas e médias.
- **Dupla Sena** tem dois sorteios por concurso; `dezenas` junta os 12 números, sem marcar onde termina o primeiro sorteio. A ordem segue as colunas da planilha: as seis primeiras dezenas são do sorteio 1 e as seis seguintes, do sorteio 2.
- **Loteria Federal e Loteca** ficam sem `dezenas`: a Federal publica números de bilhete de seis dígitos nas colunas de prêmio, e a Loteca publica o resultado de 14 jogos (`Coluna 1`, `Coluna 2`, `Coluna do meio`).
- **Datas são texto** no formato dd/mm/aaaa; converta antes de ordenar por data.
- **Federal tem lacunas:** 6097 extrações para os números de 1 a 6115 (18 números ausentes na planilha, conferido em 2026-11-07).
- **Versão do dia.** A planilha é refeita a cada coleta; um concurso pode ser revisto pela Caixa e o lake guarda só a versão mais recente.

## Exemplos

Arrecadação anual da Mega-Sena, em R$ milhões, ignorando os concursos antigos com arrecadação zero:

```python
import polars as pl

c = pl.scan_parquet("lake/loterias/concursos/**/*.parquet", hive_partitioning=True)
por_ano = (
    c.filter((pl.col("modalidade") == "megasena") & (pl.col("arrecadacao_total") > 0))
    .with_columns(pl.col("data_sorteio").str.to_date("%d/%m/%Y").dt.year().alias("ano"))
    .group_by("ano")
    .agg((pl.col("arrecadacao_total").sum() / 1e6).alias("arrecadacao_mi"), pl.len().alias("concursos"))
    .sort("ano")
    .collect()
)
```

## Referências

- Portal de loterias da Caixa: https://loterias.caixa.gov.br
