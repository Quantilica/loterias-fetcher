# Loterias da Caixa (`loterias`)

O `loterias-fetcher` coleta os resultados das loterias federais da Caixa Econômica Federal e os converte para o lake em Parquet particionado por modalidade. São onze modalidades: Mega-Sena, Lotofácil, Quina, Lotomania, Timemania, Dupla Sena, Dia de Sorte, Super Sete, +Milionária, Loteria Federal e Loteca.

| Dataset | O que é | Origem | Período | Página |
|---|---|---|---|---|
| `concursos` | Um registro por concurso: data, dezenas sorteadas, arrecadação e estimativa de prêmio | Planilha XLSX de resultados históricos, uma por modalidade | 1962-09 em diante (Loteria Federal); as demais modalidades começam entre 1994 e 2022 | [concursos](datasets/concursos.md) |
| `rateio` | Faixas de premiação de um concurso: ganhadores e valor do prêmio por faixa | JSON do detalhe do concurso | Só o último concurso de cada modalidade | [rateio](datasets/rateio.md) |
| `ganhadores_municipio` | Município e UF dos ganhadores de um concurso | JSON do detalhe do concurso | Só o último concurso de cada modalidade | [ganhadores_municipio](datasets/ganhadores_municipio.md) |

## Como a Caixa publica

- **Resultados históricos** saem como uma planilha XLSX por modalidade, que traz todos os concursos desde o primeiro. O fetcher baixa a planilha inteira a cada coleta e guarda uma versão nova só quando o conteúdo muda.
- **Detalhe do concurso** sai como JSON, por um endereço da API do portal de loterias. Sem número de concurso, o endereço devolve o último concurso; com número, devolve aquele concurso. O fetcher guarda o JSON do último concurso a cada coleta, e o comando `backfill` baixa os concursos anteriores um a um.
- A Caixa não declara, nas páginas consultadas, uma licença de uso nem a periodicidade de atualização dos dados (conferido em 2026-11-09).

O fetcher guarda cada versão baixada com a data de coleta no nome (`<arquivo>@AAAAMMDD`). O lake converte a versão mais recente de cada arquivo.

## Como os conjuntos se relacionam

- `concursos` traz o resumo de cada concurso; `rateio` e `ganhadores_municipio` detalham a premiação e a localização dos ganhadores, e se ligam a ele por `modalidade` e `concurso`.
- A planilha de resultados tem colunas de premiação por faixa e de cidade dos ganhadores que o lake de `concursos` não guarda; essas informações só chegam ao lake pelos JSONs de detalhe.

## Quebras que valem para mais de um conjunto

| Desde | Mudança | Afeta |
|---|---|---|
| varia por modalidade | O nome e a quantidade de colunas da planilha mudam de uma modalidade para outra (por exemplo, `Data Sorteio` na Lotofácil, `Data do Sorteio` na Mega-Sena e `Data de apuração` na Loteca) | `concursos` |
| 2018-05 | Dia de Sorte começa (primeiro concurso em 2018-05-19) | todos |
| 2020-10 | Super Sete começa (primeiro concurso em 2020-10-02) | todos |
| 2022-05 | +Milionária começa (primeiro concurso em 2022-05-28) | todos |
