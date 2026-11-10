"""O plugin declara o FetcherInfo do registro de fetchers."""

from loterias_fetcher.plugin import fetcher


def test_info_declarado():
    app = fetcher
    assert app.info_declared is True
    assert app.info.id == "loterias"
    assert app.info.orgao
