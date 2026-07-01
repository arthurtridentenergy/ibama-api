from typing import List, Dict, Optional, Any
from services.spinergie_service import SpinergieService


# Instância do serviço Spinergie para busca de dados em tempo real
spinergie_service = SpinergieService()


# Embarcações monitoradas (MMSI numérico e identificador alfanumérico)
VESSELS: List[Dict[str, Any]] = [
    {
        "name": "Maersk Ventura",
        "mmsi": "710002450",
        "mmsi_numeric": 710002450,
        "mmsi_alphanumeric": "MAERSK-VENTURA-710002450",
        "imo": None,
        "callsign": None,
        "type": "OSV / PSV",
    },
    {
        "name": "Maersk Vega",
        "mmsi": "710001720",
        "mmsi_numeric": 710001720,
        "mmsi_alphanumeric": "MAERSK-VEGA-710001720",
        "imo": None,
        "callsign": None,
        "type": "OSV / PSV",
    },
]


# Plataformas hardcoded retornadas pelo sistema
PLATFORMS: List[Dict[str, Any]] = [
    {
        "id": "P-65",
        "name": "P-65",
        "type": "Plataforma semissubmersível",
        "operator": "Petrobras",
        "basin": "Bacia de Campos",
    },
    {
        "id": "P-08",
        "name": "P-08",
        "type": "Plataforma fixa",
        "operator": "Petrobras",
        "basin": "Bacia de Campos",
    },
    {
        "id": "PPM-1",
        "name": "PPM-1",
        "type": "Plataforma de produção",
        "operator": "Petrobras",
        "basin": "Bacia de Campos",
    },
    {
        "id": "PCE-1",
        "name": "PCE-1",
        "type": "Plataforma de produção",
        "operator": "Petrobras",
        "basin": "Bacia de Campos",
    },
]


def _normalize_mmsi(mmsi: Any) -> str:
    """Normaliza o MMSI recebido para string, removendo espaços e hífens."""
    if mmsi is None:
        return ""
    return str(mmsi).strip().replace("-", "").replace(" ", "")


def _match_vessel(vessel: Dict[str, Any], identifier: str) -> bool:
    """Verifica se a embarcação corresponde ao identificador (MMSI numérico,
    alfanumérico ou nome)."""
    identifier = identifier.strip()
    if not identifier:
        return False

    normalized = _normalize_mmsi(identifier)
    lower = identifier.lower()

    candidates = [
        str(vessel.get("mmsi", "")),
        str(vessel.get("mmsi_numeric", "")),
        str(vessel.get("mmsi_alphanumeric", "")),
        _normalize_mmsi(vessel.get("mmsi_alphanumeric", "")),
        str(vessel.get("name", "")).lower(),
    ]

    for candidate in candidates:
        candidate_str = str(candidate).strip()
        if not candidate_str:
            continue
        if candidate_str == identifier or candidate_str == normalized or candidate_str.lower() == lower:
            return True
    return False


def _enrich_vessel(vessel: Dict[str, Any], realtime_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Combina os dados base da embarcação com os dados em tempo real do Spinergie."""
    enriched = dict(vessel)
    if realtime_data:
        enriched["realtime"] = realtime_data
        enriched["latitude"] = realtime_data.get("latitude")
        enriched["longitude"] = realtime_data.get("longitude")
        enriched["speed"] = realtime_data.get("speed")
        enriched["heading"] = realtime_data.get("heading")
        enriched["course"] = realtime_data.get("course")
        enriched["status"] = realtime_data.get("status")
        enriched["last_update"] = realtime_data.get("timestamp") or realtime_data.get("last_update")
        if realtime_data.get("imo"):
            enriched["imo"] = realtime_data.get("imo")
        if realtime_data.get("callsign"):
            enriched["callsign"] = realtime_data.get("callsign")
    else:
        enriched["realtime"] = None
    return enriched


def get_all_vessels() -> List[Dict[str, Any]]:
    """Retorna todas as embarcações monitoradas com dados em tempo real do Spinergie."""
    result: List[Dict[str, Any]] = []
    for vessel in VESSELS:
        try:
            realtime_data = spinergie_service.get_vessel_data(vessel["mmsi"])
        except Exception as exc:
            print(f"[data] Erro ao buscar dados em tempo real para {vessel['name']}: {exc}")
            realtime_data = None
        result.append(_enrich_vessel(vessel, realtime_data))
    return result


def get_vessel_by_mmsi(mmsi: Any) -> Optional[Dict[str, Any]]:
    """Busca uma embarcação pelo MMSI (numérico, alfanumérico ou string).
    Retorna None caso não seja encontrada."""
    identifier = str(mmsi).strip() if mmsi is not None else ""
    if not identifier:
        return None

    for vessel in VESSELS:
        if _match_vessel(vessel, identifier):
            try:
                realtime_data = spinergie_service.get_vessel_data(vessel["mmsi"])
            except Exception as exc:
                print(f"[data] Erro ao buscar dados em tempo real para {vessel['name']}: {exc}")
                realtime_data = None
            return _enrich_vessel(vessel, realtime_data)
    return None


def get_vessel_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Busca uma embarcação pelo nome (case-insensitive).
    Retorna None caso não seja encontrada."""
    if not name:
        return None

    target = name.strip().lower()
    for vessel in VESSELS:
        if str(vessel.get("name", "")).strip().lower() == target:
            try:
                realtime_data = spinergie_service.get_vessel_data(vessel["mmsi"])
            except Exception as exc:
                print(f"[data] Erro ao buscar dados em tempo real para {vessel['name']}: {exc}")
                realtime_data = None
            return _enrich_vessel(vessel, realtime_data)
    return None


def get_vessel_position(mmsi: Any) -> Optional[Dict[str, Any]]:
    """Retorna a posição em tempo real de uma embarcação pelo MMSI.
    Suporta MMSI numérico, alfanumérico e nome como fallback."""
    vessel = get_vessel_by_mmsi(mmsi)
    if vessel is None and isinstance(mmsi, str):
        vessel = get_vessel_by_name(mmsi)

    if vessel is None:
        return None

    realtime = vessel.get("realtime")
    if not realtime:
        return None

    return {
        "mmsi": vessel.get("mmsi"),
        "name": vessel.get("name"),
        "latitude": realtime.get("latitude"),
        "longitude": realtime.get("longitude"),
        "speed": realtime.get("speed"),
        "heading": realtime.get("heading"),
        "course": realtime.get("course"),
        "status": realtime.get("status"),
        "timestamp": realtime.get("timestamp") or realtime.get("last_update"),
    }


def get_all_platforms() -> List[Dict[str, Any]]:
    """Retorna a lista de plataformas hardcoded."""
    return [dict(platform) for platform in PLATFORMS]


def get_platform_by_id(platform_id: str) -> Optional[Dict[str, Any]]:
    """Retorna uma plataforma pelo seu identificador."""
    if not platform_id:
        return None
    target = platform_id.strip().lower()
    for platform in PLATFORMS:
        if str(platform.get("id", "")).strip().lower() == target:
            return dict(platform)
    return None