"""Coletor e conversor Lake Hive de dados das Loterias da Caixa Econômica Federal."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("loterias-fetcher")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = ["__version__"]
