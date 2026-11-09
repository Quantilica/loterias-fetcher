# loterias-fetcher

[![CI](https://github.com/Quantilica/loterias-fetcher/actions/workflows/test.yml/badge.svg)](https://github.com/Quantilica/loterias-fetcher/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

Coletor e conversor Lake Hive para dados abertos de **Loterias da Caixa Econômica Federal** (`loterias`), parte do ecossistema [Quantilica](https://quantilica.com).

## Instalação

### Via CLI Quantilica (recomendado)

```bash
quantilica install loterias
```

Para instalar com suporte à conversão Parquet Lake:

```bash
quantilica install loterias --extra analysis
```

### Como biblioteca Python

```bash
uv add loterias-fetcher --index https://index.quantilica.com/simple/
```

Com o extra de análise analítica:

```bash
uv add 'loterias-fetcher[analysis]' --index https://index.quantilica.com/simple/
```

## Uso via CLI

```bash
# Listar conjuntos disponíveis
quantilica loterias list

# Verificar novos arquivos e frescor
quantilica loterias check

# Sincronizar arquivos para o diretório local bruto
quantilica loterias sync -o /data/loterias

# Converter acervo bruto para o Universal Hive Parquet Lake
quantilica loterias convert /data/loterias /data/lake
```

## Documentação dos dados

O que cada dataset contém, de onde vem, como chega ao lake e os cuidados de uso: [docs/README.md](docs/README.md).

## Licença

Distribuído sob licença MIT. Consulte [LICENSE](LICENSE) para mais detalhes.
