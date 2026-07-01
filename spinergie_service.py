"""
spinergie_service.py

Serviço de integração com a API Spinergie para buscar dados em tempo real
de embarcações, com tratamento de erros, retry exponencial, cache com TTL,
logging estruturado e fallback para dados hardcoded.

Embarcações monitoradas:
  - Maersk Ventura (IMO 710002450)
  - Maersk Vega    (IMO 710001720)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import httpx

# ---------------------------------------------------------------------------
# Configuração de logging estruturado
# ---------------------------------------------------------------------------

logger = logging.getLogger("spinergie_service")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter(
            json.dumps(
                {
                    "ts": "%(asctime)s",
                    "level": "%(levelname)s",
                    "logger": "%(name)s",
                    "msg": "%(message)s",
                }
            )
        )
    )
    logger.addHandler(_handler)
    logger.setLevel(os.getenv("SPINERGIE_LOG_LEVEL", "INFO").upper())
    logger.propagate = False


def _log(level: int, message: str, **fields: Any) -> None:
    """Log estruturado com campos extras em JSON."""
    payload = {"message": message, **fields}
    logger.log(level, json.dumps(payload, default=str, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Constantes e configuração
# ---------------------------------------------------------------------------

SPINERGIE_BASE_URL = os.getenv(
    "SPINERGIE_BASE_URL", "https://api.spinergie.com"
)
SPINERGIE_API_TOKEN = os.getenv("SPINERGIE_API_TOKEN", "")
SPINERGIE_API_VERSION = os.getenv("SPINERGIE_API_VERSION", "v1")

DEFAULT_TIMEOUT = float(os.getenv("SPINERGIE_TIMEOUT", "30"))
DEFAULT_CACHE_TTL = int(os.getenv("SPINERGIE_CACHE_TTL", "300"))  # 5 minutos
MAX_RETRIES = int(os.getenv("SPINERGIE_MAX_RETRIES", "3"))
RETRY_BACKOFF_BASE = float(os.getenv("SPINERGIE_RETRY_BACKOFF", "0.8"))

VESSEL_IMO_VENTURA = "710002450"
VESSEL_IMO_VEGA = "710001720"

MONITORED_VESSELS: List[str] = [VESSEL_IMO_VENTURA, VESSEL_IMO_VEGA]


class VesselStatus(str, Enum):
    UNDERWAY = "underway"
    AT_ANCHOR = "at_anchor"
    IN_PORT = "in_port"
    NOT_UNDER_COMMAND = "not_under_command"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Modelos de dados
# ---------------------------------------------------------------------------


@dataclass
class VesselPosition:
    imo: str
    name: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    heading: Optional[float] = None
    speed: Optional[float] = None  # nós
    course: Optional[float] = None
    nav_status: VesselStatus = VesselStatus.UNKNOWN
    timestamp: Optional[str] = None
    destination: Optional[str] = None
    eta: Optional[str] = None
    draught: Optional[float] = None
    source: str = "spinergie"

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["nav_status"] = self.nav_status.value
        return data


@dataclass
class VesselConsumption:
    imo: str
    name: str
    fuel_consumption_mt: Optional[float] = None
    co2_emissions_t: Optional[float] = None
    distance_nm: Optional[float] = None
    reporting_period: Optional[str] = None
    source: str = "spinergie"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VesselData:
    imo: str
    name: str
    position: Optional[VesselPosition] = None
    consumption: Optional[VesselConsumption] = None
    fetched_at: float = field(default_factory=time.time)
    source: str = "spinergie"
    cached: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "imo": self.imo,
            "name": self.name,
            "position": self.position.to_dict() if self.position else None,
            "consumption": self.consumption.to_dict() if self.consumption else None,
            "fetched_at": self.fetched_at,
            "source": self.source,
            "cached": self.cached,
        }


# ---------------------------------------------------------------------------
# Cache simples em memória com TTL
# ---------------------------------------------------------------------------


class TTLCache:
    """Cache assíncrono simples com expiração por chave."""

    def __init__(self, ttl: int = DEFAULT_CACHE_TTL) -> None:
        self.ttl = ttl
        self._store: Dict[str, Tuple[float, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            expires_at, value = entry
            if time.time() > expires_at:
                self._store.pop(key, None)
                _log(logging.DEBUG, "Cache expirado", key=key)
                return None
            _log(logging.DEBUG, "Cache hit", key=key)
            return value

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        async with self._lock:
            expires_at = time.time() + (ttl if ttl is not None else self.ttl)
            self._store[key] = (expires_at, value)

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()

    async def remove(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)


# ---------------------------------------------------------------------------
# Dados hardcoded de fallback
# ---------------------------------------------------------------------------

FALLBACK_DATA: Dict[str, Dict[str, Any]] = {
    VESSEL_IMO_VENTURA: {
        "name": "Maersk Ventura",
        "position": {
            "latitude": 1.2906,
            "longitude": 103.8547,
            "heading": 95.0,
            "speed": 18.2,
            "course": 92.0,
            "nav_status": VesselStatus.UNDERWAY.value,
            "timestamp": None,
            "destination": "Rotterdam",
            "eta": None,
            "draught": 14.5,
        },
        "consumption": {
            "fuel_consumption_mt": 165.0,
            "co2_emissions_t": 520.0,
            "distance_nm": 8500.0,
            "reporting_period": "last_24h",
        },
    },
    VESSEL_IMO_VEGA: {
        "name": "Maersk Vega",
        "position": {
            "latitude": 25.276987,
            "longitude": 55.296249,
            "heading": 270.0,
            "speed": 16.8,
            "course": 268.0,
            "nav_status": VesselStatus.UNDERWAY.value,
            "timestamp": None,
            "destination": "Jebel Ali",
            "eta": None,
            "draught": 13.8,
        },
        "consumption": {
            "fuel_consumption_mt": 152.0,
            "co2_emissions_t": 480.0,
            "distance_nm": 7800.0,
            "reporting_period": "last_24h",
        },
    },
}


def _build_fallback(imo: str) -> VesselData:
    """Constrói um VesselData a partir dos dados hardcoded de fallback."""
    fb = FALLBACK_DATA.get(imo)
    if not fb:
        _log(logging.WARNING, "Sem fallback disponível para IMO", imo=imo)
        return VesselData(imo=imo, name=f"Vessel-{imo}", source="fallback")

    pos = fb.get("position", {})
    cons = fb.get("consumption", {})

    position = VesselPosition(
        imo=imo,
        name=fb["name"],
        latitude=pos.get("latitude"),
        longitude=pos.get("longitude"),
        heading=pos.get("heading"),
        speed=pos.get("speed"),
        course=pos.get("course"),
        nav_status=VesselStatus(pos.get("nav_status", VesselStatus.UNKNOWN.value)),
        timestamp=pos.get("timestamp"),
        destination=pos.get("destination"),
        eta=pos.get("eta"),
        draught=pos.get("draught"),
        source="fallback",
    )

    consumption = VesselConsumption(
        imo=imo,
        name=fb["name"],
        fuel_consumption_mt=cons.get("fuel_consumption_mt"),
        co2_emissions_t=cons.get("co2_emissions_t"),
        distance_nm=cons.get("distance_nm"),
        reporting_period=cons.get("reporting_period"),
        source="fallback",
    )

    return VesselData(
        imo=imo,
        name=fb["name"],
        position=position,
        consumption=consumption,
        source="fallback",
    )


# ---------------------------------------------------------------------------
# Exceções
# ---------------------------------------------------------------------------


class SpinergieError(Exception):
    """Erro base do serviço Spinergie."""


class SpinergieAuthError(SpinergieError):
    """Falha de autenticação com a API Spinergie."""


class SpinergieNotFoundError(SpinergieError):
    """Embarcação não encontrada na API Spinergie."""


class SpinergieRateLimitError(SpinergieError):
    """Limite de requisições excedido."""


class SpinergieTimeoutError(SpinergieError):
    """Timeout ao chamar a API Spinergie."""


# ---------------------------------------------------------------------------
# Cliente do serviço Spinergie
# ---------------------------------------------------------------------------


class SpinergieService:
    """
    Cliente assíncrono para a API Spinergie.

    Features:
      - httpx assíncrono com keep-alive
      - Retry exponencial para erros transitórios
      - Cache em memória com TTL
      - Logging estruturado
      - Fallback para dados hardcoded
    """

    def __init__(
        self,
        api_token: Optional[str] = None,
        base_url: str = SPINERGIE_BASE_URL,
        api_version: str = SPINERGIE_API_VERSION,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
        cache_ttl: int = DEFAULT_CACHE_TTL,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.api_token = api_token or SPINERGIE_API_TOKEN
        self.base_url = base_url.rstrip("/")
        self.api_version = api_version
        self.timeout = timeout
        self.max_retries = max_retries
        self.cache = TTLCache(ttl=cache_ttl)
        self._client = client
        self._owns_client = client is None

    # ------------------------------------------------------------------
    # Gerenciamento do cliente HTTP
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {
                "Accept": "application/json",
                "User-Agent": "spinergie-service/1.0",
            }
            if self.api_token:
                headers["Authorization"] = f"Bearer {self.api_token}"
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=httpx.Timeout(self.timeout),
            )
        return self._client

    async def close(self) -> None:
        if self._client and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "SpinergieService":
        await self._get_client()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Retry com backoff exponencial
    # ------------------------------------------------------------------

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        return status_code in {408, 429, 500, 502, 503, 504}

    async def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> httpx.Response:
        client = await self._get_client()
        url = f"/{self.api_version}{endpoint}"
        last_exc: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                _log(
                    logging.INFO,
                    "Requisição Spinergie",
                    method=method,
                    url=url,
                    attempt=attempt,
                    params=params,
                )
                response = await client.request(
                    method, url, params=params, json=json_body
                )

                if response.status_code == 401:
                    raise SpinergieAuthError(
                        f"Autenticação falhou (401) em {url}"
                    )
                if response.status_code == 404:
                    raise SpinergieNotFoundError(
                        f"Recurso não encontrado (404) em {url}"
                    )
                if response.status_code == 429:
                    raise SpinergieRateLimitError(
                        f"Rate limit excedido (429) em {url}"
                    )

                if self._is_retryable_status(response.status_code):
                    last_exc = SpinergieError(
                        f"Status transitório {response.status_code} em {url}"
                    )
                    _log(
                        logging.WARNING,
                        "Status HTTP transitório",
                        status=response.status_code,
                        url=url,
                        attempt=attempt,
                    )
                else:
                    response.raise_for_status()
                    return response

            except httpx.TimeoutException as exc:
                last_exc = SpinergieTimeoutError(str(exc))
                _log(
                    logging.WARNING,
                    "Timeout na requisição",
                    url=url,
                    attempt=attempt,
                    error=str(exc),
                )
            except httpx.TransportError as exc:
                last_exc = SpinergieError(str(exc))
                _log(
                    logging.WARNING,
                    "Erro de transporte",
                    url=url,
                    attempt=attempt,
                    error=str(exc),
                )
            except (SpinergieAuthError, SpinergieNotFoundError):
                # Erros não transitórios: não retentar
                raise
            except SpinergieRateLimitError as exc:
                last_exc = exc
                _log(
                    logging.WARNING,
                    "Rate limit atingido",
                    url=url,
                    attempt=attempt,
                )
            except SpinergieError as exc:
                last_exc = exc
                _log(
                    logging.WARNING,
                    "Erro transitório da API",
                    url=url,
                    attempt=attempt,
                    error=str(exc),
                )

            if attempt < self.max_retries:
                delay = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                _log(logging.INFO, "Aguardando retry", delay=delay, attempt=attempt)
                await asyncio.sleep(delay)

        raise SpinergieError(
            f"Falha após {self.max_retries} tentativas em {url}: {last_exc}"
        )

    # ------------------------------------------------------------------
    # Mapeamento de respostas
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_nav_status(value: Any) -> VesselStatus:
        if not value:
            return VesselStatus.UNKNOWN
        if isinstance(value, int):
            mapping = {
                0: VesselStatus.UNDERWAY,
                1: VesselStatus.AT_ANCHOR,
                2: VesselStatus.NOT_UNDER_COMMAND,
                5: VesselStatus.IN_PORT,
            }
            return mapping.get(value, VesselStatus.UNKNOWN)
        try:
            return VesselStatus(str(value).lower())
        except ValueError:
            return VesselStatus.UNKNOWN

    def _map_position(self, imo: str, payload: Dict[str, Any]) -> VesselPosition:
        name = payload.get("vessel_name") or payload.get("name") or f"Vessel-{imo}"
        return VesselPosition(
            imo=imo,
            name=name,
            latitude=payload.get("latitude") or payload.get("lat"),
            longitude=payload.get("longitude") or payload.get("lon"),
            heading=payload.get("heading"),
            speed=payload.get("speed") or payload.get("sog"),
            course=payload.get("course") or payload.get("cog"),
            nav_status=self._parse_nav_status(
                payload.get("nav_status") or payload.get("navigation_status")
            ),
            timestamp=payload.get("timestamp") or payload.get("position_timestamp"),
            destination=payload.get("destination"),
            eta=payload.get("eta"),
            draught=payload.get("draught") or payload.get("draft"),
            source="spinergie",
        )

    def _map_consumption(
        self, imo: str, payload: Dict[str, Any]
    ) -> VesselConsumption:
        name = payload.get("vessel_name") or payload.get("name") or f"Vessel-{imo}"
        return VesselConsumption(
            imo=imo,
            name=name,
            fuel_consumption_mt=payload.get("fuel_consumption_mt")
            or payload.get("fuel_consumption"),
            co2_emissions_t=payload.get("co2_emissions_t")
            or payload.get("co2_emissions"),
            distance_nm=payload.get("distance_nm") or payload.get("distance"),
            reporting_period=payload.get("reporting_period") or payload.get("period"),
            source="spinergie",
        )

    def _map_vessel_data(self, imo: str, payload: Dict[str, Any]) -> VesselData:
        name = payload.get("vessel_name") or payload.get("name") or f"Vessel-{imo}"
        position = None
        consumption = None

        pos_payload = payload.get("position") or payload.get("latest_position")
        if pos_payload and isinstance(pos_payload, dict):
            position = self._map_position(imo, {**pos_payload, "name": name})
        elif any(k in payload for k in ("latitude", "lat", "longitude", "lon")):
            position = self._map_position(imo, payload)

        cons_payload = payload.get("consumption") or payload.get("fuel")
        if cons_payload and isinstance(cons_payload, dict):
            consumption = self._map_consumption(imo, {**cons_payload, "name": name})
        elif any(k in payload for k in ("fuel_consumption_mt", "fuel_consumption")):
            consumption = self._map_consumption(imo, payload)

        return VesselData(
            imo=imo,
            name=name,
            position=position,
            consumption=consumption,
            source="spinergie",
        )

    # ------------------------------------------------------------------
    # Chamadas de API
    # ------------------------------------------------------------------

    async def fetch_vessel_raw(self, imo: str) -> Dict[str, Any]:
        """Busca o payload bruto da embarcação na API Spinergie."""
        response = await self._request_with_retry(
            "GET", f"/vessels/{imo}", params={"include": "position,consumption"}
        )
        return response.json()

    async def get_vessel(self, imo: str, use_cache: bool = True) -> VesselData:
        """
        Retorna dados consolidados de uma embarcação.

        Ordem de preferência:
          1. Cache (se válido)
          2. API Spinergie
          3. Fallback hardcoded
        """
        cache_key = f"vessel:{imo}"

        if use_cache:
            cached = await self.cache.get(cache_key)
            if cached is not None:
                cached.cached = True
                _log(logging.INFO, "Retornando dados em cache", imo=imo)
                return cached

        try:
            payload = await self.fetch_vessel_raw(imo)
            data = self._map_vessel_data(imo, payload)
            await self.cache.set(cache_key, data)
            _log(
                logging.INFO,
                "Dados obtidos da API Spinergie",
                imo=imo,
                name=data.name,
            )
            return data

        except SpinergieNotFoundError:
            _log(
                logging.WARNING,
                "Embarcação não encontrada na API, usando fallback",
                imo=imo,
            )
            fallback = _build_fallback(imo)
            await self.cache.set(cache_key, fallback, ttl=60)
            return fallback

        except SpinergieAuthError as exc:
            _log(
                logging.ERROR,
                "Erro de autenticação, usando fallback",
                imo=imo,
                error=str(exc),
            )
            fallback = _build_fallback(imo)
            await self.cache.set(cache_key, fallback, ttl=60)
            return fallback

        except SpinergieError as exc:
            _log(
                logging.ERROR,
                "Erro na API Spinergie, usando fallback",
                imo=imo,
                error=str(exc),
            )
            fallback = _build_fallback(imo)
            await self.cache.set(cache_key, fallback, ttl=60)
            return fallback

        except Exception as exc:  # noqa: BLE001
            _log(
                logging.ERROR,
                "Erro inesperado, usando fallback",
                imo=imo,
                error=str(exc),
            )
            fallback = _build_fallback(imo)
            await self.cache.set(cache_key, fallback, ttl=60)
            return fallback

    async def get_all_vessels(
        self, imos: Optional[List[str]] = None, use_cache: bool = True
    ) -> List[VesselData]:
        """Busca dados de múltiplas embarcações em paralelo."""
        imos = imos or MONITORED_VESSELS
        tasks = [self.get_vessel(imo, use_cache=use_cache) for imo in imos]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        vessels: List[VesselData] = []
        for imo, result in zip(imos, results):
            if isinstance(result, Exception):
                _log(
                    logging.ERROR,
                    "Falha ao obter embarcação, usando fallback",
                    imo=imo,
                    error=str(result),
                )
                vessels.append(_build_fallback(imo))
            else:
                vessels.append(result)
        return vessels

    async def get_vessel_position(self, imo: str) -> Optional[VesselPosition]:
        """Conveniência: retorna apenas a posição da embarcação."""
        data = await self.get_vessel(imo)
        return data.position

    async def get_vessel_consumption(self, imo: str) -> Optional[VesselConsumption]:
        """Conveniência: retorna apenas o consumo da embarcação."""
        data = await self.get_vessel(imo)
        return data.consumption

    async def refresh_vessel(self, imo: str) -> VesselData:
        """Força atualização ignorando o cache."""
        await self.cache.remove(f"vessel:{imo}")
        return await self.get_vessel(imo, use_cache=False)

    async def clear_cache(self) -> None:
        """Limpa todo o cache."""
        await self.cache.clear()
        _log(logging.INFO, "Cache limpo")


# ---------------------------------------------------------------------------
# Instância singleton de conveniência
# ---------------------------------------------------------------------------

_service_instance: Optional[SpinergieService] = None
_service_lock = asyncio.Lock()


async def get_service() -> SpinergieService:
    """Retorna uma instância singleton do SpinergieService."""
    global _service_instance
    async with _service_lock:
        if _service_instance is None:
            _service_instance = SpinergieService()
        return _service_instance


async def close_service() -> None:
    """Encerra a instância singleton."""
    global _service_instance
    async with _service_lock:
        if _service_instance is not None:
            await _service_instance.close()
            _service_instance = None


# ---------------------------------------------------------------------------
# Exemplo de uso
# ---------------------------------------------------------------------------


async def main() -> None:
    """Demonstração de uso do serviço."""
    async with SpinergieService() as service:
        vessels = await service.get_all_vessels()
        for v in vessels:
            print(json.dumps(v.to_dict(), indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())