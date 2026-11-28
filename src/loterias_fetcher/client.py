"""HTTP client for Caixa Loterias API."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from quantilica.core.http import HostPolicy, HttpClient
from quantilica.core.logging import get_logger

from .constants import DEFAULT_API_HOST, MODALIDADES, PARAMS_URL, SOURCE_ID

logger = get_logger(__name__)

API_HOSTS: tuple[str, ...] = (
    "servicebus3.caixa.gov.br",
    "servicebus2.caixa.gov.br",
    "loterias.caixa.gov.br",
)
"""Hosts da Caixa que respondem pelos dados das loterias."""


def host_policy(
    *,
    min_interval: float = 2.0,
    max_concurrency: int = 2,
    backoff_base: float = 10.0,
) -> HostPolicy:
    """Política de tráfego por host para a API da Caixa.

    A API recusa com ``429`` quem pede depressa demais. A política espaça as
    requisições (uma a cada ``min_interval`` segundos, sem rajada), limita as
    simultâneas e, ao primeiro ``429``, pausa o host inteiro: todas as threads
    esperam o ``Retry-After`` do servidor ou, sem ele, ``backoff_base``
    segundos dobrando a cada ``429`` seguido.

    Args:
        min_interval: Segundos entre requisições ao mesmo host.
        max_concurrency: Requisições simultâneas ao mesmo host.
        backoff_base: Primeira pausa do host (s) num ``429`` sem ``Retry-After``.

    Returns:
        HostPolicy: A política, para ``HttpClient(host_policies=...)``.
    """
    return HostPolicy(
        min_interval=min_interval,
        max_concurrency=max_concurrency,
        burst=1,
        backoff_base=backoff_base,
    )


def host_policies(
    hosts: tuple[str, ...] = API_HOSTS, policy: HostPolicy | None = None
) -> dict[str, HostPolicy]:
    """Mapa host -> política, a mesma para todos os ``hosts``.

    Args:
        hosts: Hosts a proteger (padrão: os da API da Caixa).
        policy: Política a aplicar (padrão: :func:`host_policy`).

    Returns:
        dict[str, HostPolicy]: Política por host.
    """
    chosen = policy or host_policy()
    return dict.fromkeys(hosts, chosen)


_DEFAULT_BASE = urlsplit(DEFAULT_API_HOST)
_ALLOWED_DOMAIN = ".caixa.gov.br"


def validate_api_host(value: Any) -> str | None:
    """Valida o endereço lido do ``params.txt``; ``None`` se não servir.

    Só vale ``https`` em host de ``.caixa.gov.br`` (sem usuário, sem porta,
    sem consulta) e com o mesmo caminho base do host fixo: as URLs são formadas
    como ``<host>/api/...``. Nunca levanta exceção.
    """
    try:
        parsed = urlsplit(str(value).strip())
        hostname = parsed.hostname or ""
        ok = (
            parsed.scheme == "https"
            and hostname.endswith(_ALLOWED_DOMAIN)
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
            and not parsed.query
            and not parsed.fragment
            and parsed.path.rstrip("/") == _DEFAULT_BASE.path.rstrip("/")
        )
    except Exception:  # noqa: BLE001 - ``https://[::1`` e afins: valor inválido
        return None
    return f"https://{hostname}{_DEFAULT_BASE.path.rstrip('/')}" if ok else None


class LoteriasClient:
    """Client for Caixa Loterias services."""

    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient(host_policies=host_policies())
        self._api_host: str | None = None

    def resolve_api_host(self) -> str:
        """Resolve current API host from params.txt or fallback."""
        if self._api_host is not None:
            return self._api_host

        reason = ""
        try:
            resp = self.client.get(PARAMS_URL)
            if resp.status_code == 200:
                data = resp.json()
                raw = data.get("urlapiloterias") if isinstance(data, dict) else None
                if not raw:
                    reason = "resposta sem 'urlapiloterias'"
                elif (host := validate_api_host(raw)) is not None:
                    self._api_host = host
                    return host
                else:
                    reason = f"endereço rejeitado: {str(raw)[:80]!r}"
            else:
                reason = f"HTTP {resp.status_code}"
        except Exception as exc:  # noqa: BLE001 - cai no host padrão, mas avisa
            reason = str(exc)

        logger.warning(
            "Falha ao ler %s (%s); usando o host padrão %s",
            PARAMS_URL,
            reason,
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
        return self.client.download_with_manifest(
            url,
            destination,
            source_id=SOURCE_ID,
            dataset_id="concursos",
            producer=SOURCE_ID,
            expected_format="xlsx",
        )

    def download_contest(
        self, modalidade_slug: str, contest_number: int | None, destination: Path
    ) -> Path:
        """Download contest JSON with manifest sidecar.

        O payload é validado como JSON antes de gravar: uma página HTML com
        ``200`` (manutenção, bloqueio) não vira um ``.json``.
        """
        url = self.contest_url(modalidade_slug, contest_number)
        return self.client.download_with_manifest(
            url,
            destination,
            source_id=SOURCE_ID,
            dataset_id="detalhe",
            producer=SOURCE_ID,
            expected_format="json",
        )
