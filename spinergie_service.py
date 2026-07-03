import asyncio
import logging
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import aiohttp
from aiohttp import ClientTimeout

logger = logging.getLogger(__name__)

SPINERGIE_BASE_URL = os.getenv("SPINERGIE_BASE_URL", "https://api.spinergie.com").rstrip("/")
# Aceita tanto SPINERGIE_API_KEY (nome usado no render.yaml) quanto
# SPINERGIE_API_TOKEN (nome usado no .env local) para evitar quebra por
# divergência de nomenclatura entre ambientes.
SPINERGIE_API_KEY = os.getenv("SPINERGIE_API_KEY") or os.getenv("SPINERGIE_API_TOKEN")
SPINERGIE_TIMEOUT_SECONDS = int(os.getenv("SPINERGIE_TIMEOUT", "15"))

CACHE_TTL = timedelta(minutes=5)
DISCREPANCY_THRESHOLD_KM = 3.0

_position_cache: Dict[str, Dict[str, Any]] = {}


# Mapeamento de nomes internos para nomes canônicos utilizados pela API Spinergie.
# Exemplo: a plataforma cadastrada internamente como "P08" deve ser referenciada
# como "P-08" perante a Spinergie.
_PLATFORM_NAME_MAP = {
    "P08": "P-08",
    "P65": "P-65",
}

# Registro de unidades marítimas. Em produção esse registro pode ser carregado
# de um banco de dados, arquivo de configuração ou variáveis de ambiente.
UNIDADES_REGISTRY: List[Dict[str, Any]] = [
    {
        "mmsi": "710000001",
        "nome": "P08",
        "tipoUnidade": "PLATAFORMA_FIXA",
        "latitudeFixa": -22.123456,
        "longitudeFixa": -40.123456,
        "ativo": True,
    },
    {
        "mmsi": "710000002",
        "nome": "P65",
        "tipoUnidade": "PLATAFORMA_FIXA",
        "latitudeFixa": -23.654321,
        "longitudeFixa": -41.654321,
        "ativo": True,
    },
    {
        "mmsi": "710001720",
        "nome": "MAERSK VEGA",
        "tipoUnidade": "EMBARCACAO",
        "ativo": True,
    },
    {
        "mmsi": "123456789",
        "nome": "Navio Emergência Alpha",
        "tipoUnidade": "EMBARCACAO_EMERGENCIA",
        "ativo": True,
    },
]


def normalize_platform_name(name: Optional[str]) -> str:
    """Normaliza o nome da plataforma para o formato canônico da Spinergie."""
    if not name:
        return "DESCONHECIDO"
    normalized = str(name).strip().upper()
    return _PLATFORM_NAME_MAP.get(normalized, normalized)


def get_unit_by_mmsi(mmsi: str) -> Optional[Dict[str, Any]]:
    """Retorna a unidade cadastrada a partir do MMSI."""
    mmsi_clean = (mmsi or "").strip()
    for unidade in UNIDADES_REGISTRY:
        if unidade.get("mmsi") == mmsi_clean:
            return unidade
    return None


def get_unit_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Retorna a unidade cadastrada a partir do nome (curto ou canônico)."""
    name_clean = (name or "").strip().upper()
    for unidade in UNIDADES_REGISTRY:
        if unidade.get("nome", "").upper() == name_clean:
            return unidade
        canonical = normalize_platform_name(unidade.get("nome"))
        if canonical.upper() == name_clean:
            return unidade
    return None


def _haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcula a distância em quilômetros entre dois pontos geográficos."""
    earth_radius_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return earth_radius_km * c


def _is_cache_valid(mmsi: str) -> bool:
    """Verifica se existe cache válido para o MMSI informado."""
    entry = _position_cache.get(mmsi)
    if not entry:
        return False
    return datetime.now(timezone.utc) - entry["timestamp"] < CACHE_TTL


def _check_coordinate_discrepancy(
    mmsi: str,
    api_latitude: float,
    api_longitude: float,
    unit: Dict[str, Any],
) -> None:
    """
    Compara a coordenada recebida da API com a coordenada fixa cadastrada.
    Caso a distância ultrapasse o threshold de 3 km, registra log detalhado.
    """
    if unit.get("tipoUnidade") != "PLATAFORMA_FIXA":
        return

    fixed_lat = unit.get("latitudeFixa")
    fixed_lon = unit.get("longitudeFixa")
    if fixed_lat is None or fixed_lon is None:
        return

    try:
        fixed_lat = float(fixed_lat)
        fixed_lon = float(fixed_lon)
    except (TypeError, ValueError):
        logger.warning(
            f"Coordenadas fixas inválidas para {unit.get('nome')} (MMSI {mmsi})"
        )
        return

    distance_km = _haversine_distance_km(fixed_lat, fixed_lon, api_latitude, api_longitude)
    if distance_km > DISCREPANCY_THRESHOLD_KM:
        logger.warning(
            f"Discrepância de coordenadas detectada para {unit.get('nome')} (MMSI {mmsi}): "
            f"coordenada API ({api_latitude:.6f}, {api_longitude:.6f}) dista "
            f"{distance_km:.2f} km da coordenada fixa ({fixed_lat:.6f}, {fixed_lon:.6f}). "
            f"Threshold: {DISCREPANCY_THRESHOLD_KM} km."
        )


def _build_fallback_position(
    unit: Dict[str, Any], mmsi: str
) -> Optional[Dict[str, Any]]:
    """Monta uma posição a partir das coordenadas fixas cadastradas."""
    fixed_lat = unit.get("latitudeFixa")
    fixed_lon = unit.get("longitudeFixa")
    if fixed_lat is None or fixed_lon is None:
        return None

    try:
        fixed_lat = float(fixed_lat)
        fixed_lon = float(fixed_lon)
    except (TypeError, ValueError):
        return None

    nome = normalize_platform_name(unit.get("nome")) or unit.get("nome") or "DESCONHECIDO"
    return {
        "mmsi": mmsi,
        "nome": nome,
        "latitude": fixed_lat,
        "longitude": fixed_lon,
        "timestampAquisicao": datetime.now(timezone.utc).isoformat(),
        "fonte": "fallback_fixo",
        "tipoUnidade": unit.get("tipoUnidade"),
    }


def _normalize_position(
    raw: Any,
    fallback_mmsi: str,
    unit: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Converte a resposta da Spinergie para o formato esperado pela API."""
    if not raw or not isinstance(raw, dict):
        logger.warning(f"Resposta inválida ou vazia da Spinergie para MMSI {fallback_mmsi}")
        return None

    mmsi = str(raw.get("mmsi") or fallback_mmsi)

    vessel_name = raw.get("vesselName") or raw.get("nome") or raw.get("name")
    if vessel_name:
        nome = normalize_platform_name(vessel_name)
    elif unit:
        nome = normalize_platform_name(unit.get("nome")) or unit.get("nome") or "DESCONHECIDO"
    else:
        nome = "DESCONHECIDO"

    latitude = raw.get("latitude")
    longitude = raw.get("longitude")

    try:
        latitude = float(latitude) if latitude is not None else None
        longitude = float(longitude) if longitude is not None else None
    except (TypeError, ValueError) as exc:
        logger.warning(f"Coordenadas inválidas para MMSI {mmsi}: {exc}")
        latitude = None
        longitude = None

    if latitude is None or longitude is None:
        logger.warning(f"Coordenadas ausentes para MMSI {mmsi}")
        return None

    timestamp = raw.get("timestamp") or raw.get("timestampAquisicao") or raw.get("lastReceived")
    if not timestamp:
        timestamp = datetime.now(timezone.utc).isoformat()

    if unit:
        _check_coordinate_discrepancy(mmsi, latitude, longitude, unit)

    position = {
        "mmsi": mmsi,
        "nome": nome,
        "latitude": latitude,
        "longitude": longitude,
        "timestampAquisicao": timestamp,
        "fonte": "spinergie",
        "tipoUnidade": unit.get("tipoUnidade") if unit else None,
    }

    logger.debug(f"Posição normalizada para MMSI {mmsi}: {position}")
    return position


async def _call_spinergie_api(mmsi: str) -> Optional[Any]:
    """Executa a chamada HTTP ao endpoint da Spinergie."""
    if not SPINERGIE_API_KEY:
        logger.error("Variável de ambiente SPINERGIE_API_KEY não configurada")
        return None

    url = f"{SPINERGIE_BASE_URL}/sd/api/vessel/sfm-latest-locations"
    headers = {
        "Authorization": f"ApiKey {SPINERGIE_API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    params = {"mmsi": mmsi}
    timeout = ClientTimeout(total=SPINERGIE_TIMEOUT_SECONDS)

    logger.info(f"Consultando Spinergie para MMSI {mmsi} - URL: {url}")

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=headers, params=params) as response:
            logger.debug(f"Spinergie respondeu {response.status} para MMSI {mmsi}")

            if response.status == 200:
                data = await response.json()
                logger.debug(f"Resposta bruta da Spinergie para MMSI {mmsi}: {data}")
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    return [data]
                return None

            if response.status == 401:
                logger.error(
                    "Falha de autenticação na API Spinergie (401). Verifique SPINERGIE_API_KEY"
                )
            elif response.status == 403:
                logger.error("Acesso negado à API Spinergie (403)")
            elif response.status == 404:
                logger.warning(f"Embarcação não encontrada no Spinergie (404) para MMSI {mmsi}")
            elif response.status >= 500:
                logger.error(f"Erro no servidor Spinergie ({response.status}) para MMSI {mmsi}")
            else:
                body = await response.text()
                logger.error(
                    f"Resposta inesperada do Spinergie ({response.status}) para MMSI {mmsi}: {body}"
                )

            return None


async def fetch_vessel_position_async(mmsi: str) -> Optional[Dict[str, Any]]:
    """
    Busca a posição em tempo real de uma embarcação ou plataforma no Spinergie.

    Para plataformas fixas, mantém cache local de 5 minutos e utiliza coordenadas
    cadastradas como fallback quando a API estiver indisponível. Também detecta e
    loga discrepâncias superiores a 3 km entre a posição da API e a coordenada fixa.
    """
    if not SPINERGIE_API_KEY:
        logger.error("Variável de ambiente SPINERGIE_API_KEY não configurada")
        return None

    if not mmsi or not mmsi.strip():
        logger.error("MMSI não informado")
        return None

    mmsi = mmsi.strip()
    unit = get_unit_by_mmsi(mmsi)

    if _is_cache_valid(mmsi):
        logger.debug(f"Retornando posição do cache para MMSI {mmsi}")
        return _position_cache[mmsi]["data"]

    try:
        raw_data = await _call_spinergie_api(mmsi)
    except asyncio.TimeoutError:
        logger.error(f"Timeout ao consultar Spinergie para MMSI {mmsi}")
        raw_data = None
    except aiohttp.ClientConnectionError as exc:
        logger.error(f"Erro de conexão com Spinergie para MMSI {mmsi}: {exc}")
        raw_data = None
    except aiohttp.ClientResponseError as exc:
        logger.error(
            f"Erro na resposta do Spinergie para MMSI {mmsi}: {exc.status} - {exc.message}"
        )
        raw_data = None
    except aiohttp.ClientError as exc:
        logger.error(f"Erro do cliente HTTP ao consultar Spinergie para MMSI {mmsi}: {exc}")
        raw_data = None
    except Exception as exc:
        logger.exception(f"Erro inesperado ao consultar Spinergie para MMSI {mmsi}: {exc}")
        raw_data = None

    position = None
    if raw_data and isinstance(raw_data, list) and raw_data:
        position = _normalize_position(raw_data[0], mmsi, unit)

    if position:
        _position_cache[mmsi] = {
            "data": position,
            "timestamp": datetime.now(timezone.utc),
        }
        logger.info(f"Posição obtida e cacheada para MMSI {mmsi}")
        return position

    # Fallback para plataformas fixas quando a API está offline ou sem dados.
    if unit and unit.get("tipoUnidade") == "PLATAFORMA_FIXA":
        fallback = _build_fallback_position(unit, mmsi)
        if fallback:
            _position_cache[mmsi] = {
                "data": fallback,
                "timestamp": datetime.now(timezone.utc),
            }
            logger.warning(
                f"API Spinergie indisponível ou sem dados para MMSI {mmsi}. "
                f"Retornando coordenadas fixas de fallback para {fallback['nome']}."
            )
            return fallback

    return None


def listar_unidades() -> List[Dict[str, Any]]:
    """
    Retorna a lista de unidades marítimas cadastradas.

    Suporta plataformas fixas e embarcações/sondas móveis, permitindo que novas
    unidades sejam adicionadas ao registro sem alterações estruturais.
    """
    unidades = []
    for unidade in UNIDADES_REGISTRY:
        if not unidade.get("ativo", True):
            continue

        item: Dict[str, Any] = {
            "mmsi": unidade.get("mmsi"),
            "nome": normalize_platform_name(unidade.get("nome")),
            "nomeOriginal": unidade.get("nome"),
            "tipoUnidade": unidade.get("tipoUnidade"),
            "ativo": unidade.get("ativo", True),
        }

        if unidade.get("tipoUnidade") == "PLATAFORMA_FIXA":
            item["latitudeFixa"] = unidade.get("latitudeFixa")
            item["longitudeFixa"] = unidade.get("longitudeFixa")

        unidades.append(item)

    return unidades


def get_posicao(mmsi: str) -> Optional[Dict[str, Any]]:
    """
    Função mantida para compatibilidade. Retorna a posição atual da embarcação
    ou plataforma, realizando a consulta ao Spinergie de forma transparente.
    """
    logger.info(f"get_posicao chamado para MMSI {mmsi}")
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            logger.debug("Loop de eventos em execução; agendando coroutine")
            future = asyncio.run_coroutine_threadsafe(fetch_vessel_position_async(mmsi), loop)
            return future.result(timeout=20)
        return loop.run_until_complete(fetch_vessel_position_async(mmsi))
    except Exception as exc:
        logger.exception(f"Erro ao executar get_posicao para MMSI {mmsi}: {exc}")
        return None


async def get_posicao_async(mmsi: str) -> Optional[Dict[str, Any]]:
    """Versão assíncrona de get_posicao para uso em contextos async."""
    return await fetch_vessel_position_async(mmsi)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    exemplo_mmsi = "710001720"
    resultado = get_posicao(exemplo_mmsi)
    print(resultado)