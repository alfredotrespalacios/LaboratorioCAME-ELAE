"""Cliente HTTP resiliente y contrato mínimo de conectores."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def resilient_session(retries: int = 3, backoff: float = 0.6) -> requests.Session:
    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": "Laboratorio-CAME/1.0 (uso académico; ELAE)",
            "Accept": "application/json, text/plain, */*",
        }
    )
    return session


class DataProvider(ABC):
    source_name: str

    def __init__(self, *, timeout: int = 45, session: requests.Session | None = None) -> None:
        self.timeout = timeout
        self.session = session or resilient_session()

    @abstractmethod
    def healthcheck(self) -> dict[str, Any]:
        """Comprueba un punto pequeño sin descargar una historia extensa."""
