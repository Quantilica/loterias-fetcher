"""HTTP client for Caixa Loterias API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from quantilica.core.http import HostPolicy, HttpClient
from quantilica.core.logging import get_logger

from .constants import DEFAULT_API_HOST, MODALIDADES, PARAMS_URL

logger = get_logger(__name__)


class LoteriasClient:
    """Client for Caixa Loterias services."""

    def __init__(self, client: HttpClient | None = None) -> None:
        host_policies = {
            "servicebus3.caixa.gov.br": HostPolicy(min_interval=1.0),
            "servicebus2.caixa.gov.br": HostPolicy(min_interval=1.0),
            "loterias.caixa.gov.br": HostPolicy(min_interval=1.0),
        }
        self.client = client or HttpClient(host_policies=host_policies)
        self._api_host: str | None = None

    def resolve_api_host(self) -> str:
        """Resolve current API host from params.txt or fallback."""
        if self._api_host is not None:
            return self._api_host

        try:
            resp = self.client.get(PARAMS_URL, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and "urlapiloterias" in data:
                    host = data["urlapiloterias"].rstrip("/")
                    if host:
                        self._api_host = host
                        return host
        except Exception as exc:  # noqa: BLE001 - cai no host padrão, mas avisa
            logger.warning(
                "Falha ao ler %s (%s); usando o host padrão %s",
                PARAMS_URL,
                exc,
                DEFAULT_API_HOST,
            )

        self._api_host = DEFAULT_API_HOST
        return self._api_host

    def download_url_for_modalidade(self, modalidade_slug: str) -> str:
        """Build the historical XLSX download URL for a modalidade."""
        mod = MODALIDADES.get(modalidade_slug)
        if mod is None:
            raise ValueError(f"Modalidade desconhecida: {modalidade_slug!r}")
        api_host = self.resolve_api_host()
        return f"{api_host}/api/resultados/download?modalidade={mod.download_name}"

    def contest_url(
        self, modalidade_slug: str, contest_number: int | None = None
    ) -> str:
        """Build contest JSON endpoint URL."""
        if modalidade_slug not in MODALIDADES:
            raise ValueError(f"Modalidade desconhecida: {modalidade_slug!r}")
        api_host = self.resolve_api_host()
        if contest_number is not None:
            return f"{api_host}/api/{modalidade_slug}/{contest_number}"
        return f"{api_host}/api/{modalidade_slug}"

    def get_contest(
        self, modalidade_slug: str, contest_number: int | None = None
    ) -> dict[str, Any]:
        """Fetch contest JSON payload."""
        url = self.contest_url(modalidade_slug, contest_number)
        resp = self.client.get(url)
        resp.raise_for_status()
        return resp.json()

    def download_xlsx(self, modalidade_slug: str, destination: Path) -> Path:
        """Download XLSX with manifest sidecar."""
        url = self.download_url_for_modalidade(modalidade_slug)
        return self.client.download_with_manifest(url, destination)

    def download_contest(
        self, modalidade_slug: str, contest_number: int | None, destination: Path
    ) -> Path:
        """Download contest JSON with manifest sidecar."""
        url = self.contest_url(modalidade_slug, contest_number)
        return self.client.download_with_manifest(url, destination)
