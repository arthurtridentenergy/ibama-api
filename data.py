import math
import time
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any, Union

try:
    from spinergie_service import SpinergieService
except ImportError:
    SpinergieService = None

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuração do serviço Spinergie
# ---------------------------------------------------------------------------

_spinergie_service: Optional["SpinergieService"] = None


def _get_spinergie_service() -> Optional["SpinergieService"]:
    """Retorna instância singleton do SpinergieService, se disponível."""
    global _spinergie_service
    if SpinergieService is None:
        logger.warning("SpinergieService não disponível — usando simulação local.")
        return None
    if _spinergie_service is None:
        try:
            _spinergie_service = SpinergieService()
        except Exception as exc:
            logger.error("Falha ao inicializar SpinergieService: %s", exc)
            _spinergie_service = None
    return _spinergie_service


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _iso_timestamp() -> str:
    """Retorna timestamp atual em ISO 8601 com sufixo Z (UTC)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_identifier(identifier: str) -> str:
    """Normaliza MMSI ou nome para comparação (sem espaços, maiúsculas)."""
    return str(identifier).strip().upper().replace(" ", "")


def _simulate_circular_position(
    center_lat: float,
    center_lon: float,
    radius_nm: float = 2.0,
    period_seconds: float = 3600.0,
    timestamp: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Simula movimento circular ao redor de um ponto central.

    Args:
        center_lat: Latitude do centro em graus decimais.
        center_lon: Longitude do centro em graus decimais.
        radius_nm: Raio da órbita em milhas náuticas.
        period_seconds: Período de uma volta completa em segundos.
        timestamp: Timestamp Unix opcional (usa time.time() se None).

    Returns:
        Dicionário com latitude, longitude e timestamp ISO 8601.
    """
    if timestamp is None:
        timestamp = time.time()

    angle = (2.0 * math.pi * (timestamp % period_seconds)) / period_seconds

    # Converter milhas náuticas para graus (1 NM ≈ 1/60 grau)
    radius_deg = radius_nm / 60.0

    delta_lat = radius_deg * math.cos(angle)
    delta_lon = radius_deg * math.sin(angle) / max(math.cos(math.radians(center_lat)), 0.01)

    return {
        "latitude": round(center_lat + delta_lat, 6),
        "longitude": round(center_lon + delta_lon, 6),
        "timestamp": _iso_timestamp(),
        "source": "simulation",
    }


# ---------------------------------------------------------------------------
# Plataformas (hardcoded)
# ---------------------------------------------------------------------------

PLATFORMS: List[Dict[str, Any]] = [
    {
        "name": "P-65",
        "mmsi": "P65-IBAMA-001",
        "type": "platform",
        "latitude": -22.7833,
        "longitude": -41.8667,
        "ibama_license": "IBAMA-2018-P65-OP-001",
        "operator": "Petrobras",
        "field": "Bacia de Campos",
        "status": "active",
    },
    {
        "name": "P-08",
        "mmsi": "P08-IBAMA-002",
        "type": "platform",
        "latitude": -23.4500,
        "longitude": -42.0167,
        "ibama_license": "IBAMA-2019-P08-OP-002",
        "operator": "Petrobras",
        "field": "Bacia de Campos",
        "status": "active",
    },
    {
        "name": "PPM-1",
        "mmsi": "PPM1-IBAMA-003",
        "type": "platform",
        "latitude": -24.1167,
        "longitude": -42.2333,
        "ibama_license": "IBAMA-2020-PPM1-OP-003",
        "operator": "Petrobras",
        "field": "Bacia de Campos",
        "status": "active",
    },
    {
        "name": "PCE-1",
        "mmsi": "PCE1-IBAMA-004",
        "type": "platform",
        "latitude": -25.2833,
        "longitude": -42.5333,
        "ibama_license": "IBAMA-2021-PCE1-OP-004",
        "operator": "Petrobras",
        "field": "Bacia de Santos",
        "status": "active",
    },
]

# ---------------------------------------------------------------------------
# Embarcações (buscam dados em tempo real da API Spinergie)
# ---------------------------------------------------------------------------

VESSELS: List[Dict[str, Any]] = [
    {
        "name": "Maersk Ventura",
        "mmsi": "710002450",
        "type": "vessel",
        "imo": "9776018",
        "operator": "Maersk Supply Service",
        "base_latitude": -22.5000,
        "base_longitude": -41.5000,
        "sim_radius_nm": 3.0,
        "sim_period_seconds": 1800.0,
        "status": "active",
    },
    {
        "name": "Maersk Vega",
        "mmsi": "710001720",
        "type": "vessel",
        "imo": "9776020",
        "operator": "Maersk Supply Service",
        "base_latitude": -23.2000,
        "base_longitude": -42.1000,
        "sim_radius_nm": 2.5,
        "sim_period_seconds": 2400.0,
        "status": "active",
    },
]


# ---------------------------------------------------------------------------
# Cache interno de posições em tempo real
# ---------------------------------------------------------------------------

_position_cache: Dict[str, Dict[str, Any]] = {}


def _fetch_vessel_position_from_api(vessel: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Busca posição em tempo real da API Spinergie para uma embarcação.

    Returns:
        Dicionário com latitude, longitude, speed, course, timestamp e source,
        ou None se a API falhar.
    """
    service = _get_spinergie_service()
    if service is None:
        return None

    mmsi = vessel.get("mmsi", "")
    try:
        position = service.get_vessel_position(mmsi)
        if position and isinstance(position, dict):
            lat = position.get("latitude") or position.get("lat")
            lon = position.get("longitude") or position.get("lon") or position.get("lng")
            if lat is not None and lon is not None:
                return {
                    "latitude": float(lat),
                    "longitude": float(lon),
                    "speed": position.get("speed"),
                    "course": position.get("course"),
                    "heading": position.get("heading"),
                    "timestamp": position.get("timestamp", _iso_timestamp()),
                    "source": "spinergie_api",
                }
        logger.warning("SpinergieService retornou dados incompletos para MMSI %s", mmsi)
        return None
    except Exception as exc:
        logger.error("Erro ao buscar posição via Spinergie para MMSI %s: %s", mmsi, exc)
        return None


def _get_vessel_simulated_position(vessel: Dict[str, Any]) -> Dict[str, Any]:
    """Gera posição simulada (movimento circular) para uma embarcação."""
    return _simulate_circular_position(
        center_lat=vessel.get("base_latitude", -22.5),
        center_lon=vessel.get("base_longitude", -41.5),
        radius_nm=vessel.get("sim_radius_nm", 2.0),
        period_seconds=vessel.get("sim_period_seconds", 3600.0),
    )


def _resolve_vessel_position(vessel: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolve a posição de uma embarcação: tenta API Spinergie primeiro,
    e usa simulação circular como fallback.
    """
    mmsi = vessel.get("mmsi", "")

    # Tentar cache primeiro
    cached = _position_cache.get(mmsi)
    if cached and (time.time() - cached.get("_cache_time", 0)) < 30:
        return cached

    # Tentar API em tempo real
    position = _fetch_vessel_position_from_api(vessel)

    if position is None:
        # Fallback: simulação de movimento circular
        position = _get_vessel_simulated_position(vessel)

    # Enriquecer com dados da embarcação
    position["_cache_time"] = time.time()
    _position_cache[mmsi] = position
    return position


def _build_vessel_record(vessel: Dict[str, Any], include_position: bool = True) -> Dict[str, Any]:
    """Constrói registro completo de embarcação com posição resolvida."""
    record = {
        "name": vessel.get("name"),
        "mmsi": vessel.get("mmsi"),
        "type": vessel.get("type"),
        "operator": vessel.get("operator"),
        "status": vessel.get("status"),
    }

    if vessel.get("imo"):
        record["imo"] = vessel.get("imo")

    if include_position:
        position = _resolve_vessel_position(vessel)
        record["latitude"] = position.get("latitude")
        record["longitude"] = position.get("longitude")
        record["timestamp"] = position.get("timestamp", _iso_timestamp())
        record["source"] = position.get("source", "unknown")
        if position.get("speed") is not None:
            record["speed"] = position.get("speed")
        if position.get("course") is not None:
            record["course"] = position.get("course")
        if position.get("heading") is not None:
            record["heading"] = position.get("heading")

    return record


def _build_platform_record(platform: Dict[str, Any]) -> Dict[str, Any]:
    """Constrói registro completo de plataforma (posição fixa)."""
    return {
        "name": platform.get("name"),
        "mmsi": platform.get("mmsi"),
        "type": platform.get("type"),
        "latitude": platform.get("latitude"),
        "longitude": platform.get("longitude"),
        "ibama_license": platform.get("ibama_license"),
        "operator": platform.get("operator"),
        "field": platform.get("field"),
        "status": platform.get("status"),
        "timestamp": _iso_timestamp(),
        "source": "static",
    }


# ---------------------------------------------------------------------------
# Funções públicas da API
# ---------------------------------------------------------------------------

def get_all_vessels() -> List[Dict[str, Any]]:
    """
    Retorna todas as plataformas e embarcações com suas posições.

    Returns:
        Lista de dicionários contendo dados de cada unidade (plataforma ou embarcação).
    """
    results: List[Dict[str, Any]] = []

    for platform in PLATFORMS:
        results.append(_build_platform_record(platform))

    for vessel in VESSELS:
        results.append(_build_vessel_record(vessel, include_position=True))

    return results


def get_vessel_by_mmsi(mmsi: Union[str, int]) -> Optional[Dict[str, Any]]:
    """
    Busca uma unidade (plataforma ou embarcação) pelo MMSI.

    Suporta MMSI numérico (ex: 710002450) e alfanumérico (ex: P65-IBAMA-001).

    Args:
        mmsi: MMSI numérico ou alfanumérico.

    Returns:
        Dicionário com dados da unidade ou None se não encontrada.
    """
    normalized = _normalize_identifier(str(mmsi))

    # Buscar em plataformas (MMSI alfanumérico)
    for platform in PLATFORMS:
        if _normalize_identifier(platform.get("mmsi", "")) == normalized:
            return _build_platform_record(platform)

    # Buscar em embarcações (MMSI numérico)
    for vessel in VESSELS:
        if _normalize_identifier(vessel.get("mmsi", "")) == normalized:
            return _build_vessel_record(vessel, include_position=True)

    return None


def get_vessel_by_name(name: str) -> Optional[Dict[str, Any]]:
    """
    Busca uma unidade (plataforma ou embarcação) pelo nome.

    A busca é case-insensitive e ignora espaços extras.

    Args:
        name: Nome da plataforma ou embarcação.

    Returns:
        Dicionário com dados da unidade ou None se não encontrada.
    """
    normalized = _normalize_identifier(name)

    for platform in PLATFORMS:
        if _normalize_identifier(platform.get("name", "")) == normalized:
            return _build_platform_record(platform)

    for vessel in VESSELS:
        if _normalize_identifier(vessel.get("name", "")) == normalized:
            return _build_vessel_record(vessel, include_position=True)

    return None


def get_vessel_position(identifier: Union[str, int]) -> Optional[Dict[str, Any]]:
    """
    Retorna a posição de uma unidade (plataforma ou embarcação).

    Aceita MMSI (numérico ou alfanumérico) ou nome como identificador.
    Para embarcações, tenta a API Spinergie em tempo real; se falhar,
    usa simulação de movimento circular.

    Args:
        identifier: MMSI ou nome da unidade.

    Returns:
        Dicionário com name, mmsi, latitude, longitude, timestamp e source,
        ou None se a unidade não for encontrada.
    """
    record = get_vessel_by_mmsi(identifier)
    if record is None:
        record = get_vessel_by_name(identifier)

    if record is None:
        return None

    return {
        "name": record.get("name"),
        "mmsi": record.get("mmsi"),
        "type": record.get("type"),
        "latitude": record.get("latitude"),
        "longitude": record.get("longitude"),
        "timestamp": record.get("timestamp", _iso_timestamp()),
        "source": record.get("source", "unknown"),
    }


# ---------------------------------------------------------------------------
# Inicialização
# ---------------------------------------------------------------------------

def refresh_all_positions() -> None:
    """Limpa cache de posições, forçando nova busca na API na próxima chamada."""
    global _position_cache
    _position_cache = {}
    logger.info("Cache de posições limpo.")