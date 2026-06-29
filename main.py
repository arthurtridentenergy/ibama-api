import asyncio
import logging
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import aiohttp
from aiohttp import ClientTimeout
from fastapi import FastAPI, HTTPException, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def _configure_logging() -> None:
    """Configura logging de acordo com a variável LOG_LEVEL."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


_configure_logging()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuração das APIs externas
# ---------------------------------------------------------------------------
TRIDENT_BASE_URL = os.getenv("TRIDENT_BASE_URL", "https://api.trident.example.com").rstrip("/")
TRIDENT_API_KEY = os.getenv("TRIDENT_API_KEY")
TRIDENT_API_PATH = os.getenv("TRIDENT_API_PATH", "/api/v1/position")

SPINERGIE_BASE_URL = os.getenv("SPINERGIE_BASE_URL", "https://api.spinergie.com").rstrip("/")
SPINERGIE_API_KEY = os.getenv("SPINERGIE_API_KEY")

CACHE_TTL = timedelta(minutes=5)
DISCREPANCY_THRESHOLD_KM = 3.0
FLORIANOPOLIS_CENTER = (-27.595, -48.548)
FLORIANOPOLIS_RADIUS_KM = 50.0


# ---------------------------------------------------------------------------
# Coordenadas corretas das plataformas (conversão de graus/minutos para decimal)
# ---------------------------------------------------------------------------
PPM_1_LAT = -(22 + 47.88 / 60)
PPM_1_LON = -(40 + 45.75 / 60)
PCE_1_LAT = -(22 + 42.50 / 60)
PCE_1_LON = -(40 + 41.59 / 60)
P08_LAT = -(22 + 40.39 / 60)
P08_LON = -(40 + 32.79 / 60)
P65_LAT = -(22 + 42.11 / 60)
P65_LON = -(40 + 40.63 / 60)

P08_MMSI = os.getenv("P08_MMSI", "000000008")
P65_MMSI = os.getenv("P65_MMSI", "000000065")

PLATAFORMAS_FIXAS: Dict[str, str] = {
    "PPM-1": "PPM-1",
    "PCE-1": "PCE-1",
    P08_MMSI: "P-08",
    P65_MMSI: "P-65",
}

COORDENADAS_PLATAFORMAS: Dict[str, Dict[str, float]] = {
    "PPM-1": {
        "latitude": float(os.getenv("PPM_1_LATITUDE", str(PPM_1_LAT))),
        "longitude": float(os.getenv("PPM_1_LONGITUDE", str(PPM_1_LON))),
    },
    "PCE-1": {
        "latitude": float(os.getenv("PCE_1_LATITUDE", str(PCE_1_LAT))),
        "longitude": float(os.getenv("PCE_1_LONGITUDE", str(PCE_1_LON))),
    },
    "P-08": {
        "latitude": float(os.getenv("P08_LATITUDE", str(P08_LAT))),
        "longitude": float(os.getenv("P08_LONGITUDE", str(P08_LON))),
    },
    "P-65": {
        "latitude": float(os.getenv("P65_LATITUDE", str(P65_LAT))),
        "longitude": float(os.getenv("P65_LONGITUDE", str(P65_LON))),
    },
}

logger.info(f"Plataformas fixas configuradas: {list(PLATAFORMAS_FIXAS.values())}")


# ---------------------------------------------------------------------------
# Modelos Pydantic
# ---------------------------------------------------------------------------
class UnidadeMaritima(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "mmsi": "P-65",
                "nome": "P-65",
                "tipoUnidade": "PLATAFORMA_FIXA",
                "ativo": True,
            }
        }
    )

    mmsi: str = Field(..., description="MMSI ou identificador da unidade")
    nome: str = Field(..., description="Nome da unidade marítima")
    tipoUnidade: str = Field(default="EMBARCACAO", description="Tipo da unidade")
    ativo: bool = Field(default=True, description="Indica se a unidade está ativa")
    latitudeFixa: Optional[float] = Field(default=None, description="Latitude fixa (plataformas)")
    longitudeFixa: Optional[float] = Field(default=None, description="Longitude fixa (plataformas)")


class PosicaoAIS(BaseModel):
    mmsi: str
    nome: str
    latitude: float
    longitude: float
    timestampAquisicao: str


class VesselPositionResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "mmsi": "P-65",
                "nome": "P-65",
                "latitude": P65_LAT,
                "longitude": P65_LON,
                "timestampAquisicao": "2026-06-25T13:56:11+00:00",
                "fonte": "trident",
            }
        }
    )

    mmsi: str = Field(
        ...,
        description="MMSI da embarcação ou identificador da plataforma",
        example="P-65",
    )
    nome: str = Field(..., description="Nome da embarcação ou plataforma", example="P-65")
    latitude: float = Field(..., description="Latitude da posição", example=P65_LAT)
    longitude: float = Field(..., description="Longitude da posição", example=P65_LON)
    timestampAquisicao: str = Field(
        ...,
        description="Data e hora da aquisição da posição no formato ISO 8601",
        example="2026-06-25T13:56:11+00:00",
    )
    fonte: str = Field(
        default="desconhecida",
        description="Fonte dos dados (trident, spinergie, coordenada_fixa, fallback_local)",
        example="trident",
    )


class ErrorResponse(BaseModel):
    detail: str = Field(..., description="Mensagem descritiva do erro")


# ---------------------------------------------------------------------------
# Registro de unidades marítimas
# ---------------------------------------------------------------------------
UNIDADES_REGISTRY: List[Dict[str, Any]] = [
    {
        "mmsi": "PPM-1",
        "nome": "PPM-1",
        "tipoUnidade": "PLATAFORMA_FIXA",
        "ativo": True,
    },
    {
        "mmsi": "PCE-1",
        "nome": "PCE-1",
        "tipoUnidade": "PLATAFORMA_FIXA",
        "ativo": True,
    },
    {
        "mmsi": P08_MMSI,
        "nome": "P-08",
        "tipoUnidade": "PLATAFORMA_FIXA",
        "ativo": True,
    },
    {
        "mmsi": P65_MMSI,
        "nome": "P-65",
        "tipoUnidade": "PLATAFORMA_FIXA",
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


# ---------------------------------------------------------------------------
# Caches
# ---------------------------------------------------------------------------
_trident_cache: Dict[str, Dict[str, Any]] = {}
_spinergie_cache: Dict[str, Dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
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


def _is_valid_coordinate(lat: Any, lon: Any) -> bool:
    """Valida se as coordenadas são reais e não correspondem a valores padrão/nulos."""
    if lat is None or lon is None:
        return False
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return False

    if not (-90.0 <= lat_f <= 90.0) or not (-180.0 <= lon_f <= 180.0):
        return False

    if abs(lat_f) < 1e-6 and abs(lon_f) < 1e-6:
        logger.debug("Coordenada (0,0) rejeitada como inválida")
        return False

    dist_floripa = _haversine_distance_km(
        lat_f, lon_f, FLORIANOPOLIS_CENTER[0], FLORIANOPOLIS_CENTER[1]
    )
    if dist_floripa < FLORIANOPOLIS_RADIUS_KM:
        logger.debug(
            f"Coordenada ({lat_f}, {lon_f}) rejeitada por estar em Florianópolis "
            f"(distância: {dist_floripa:.2f} km)"
        )
        return False

    return True


def _validar_identificador(identificador: str) -> None:
    """Valida se o identificador é um MMSI de 9 dígitos ou uma plataforma fixa conhecida."""
    if not identificador:
        logger.warning("Identificador não informado")
        raise HTTPException(status_code=400, detail="Identificador é obrigatório.")

    if identificador in PLATAFORMAS_FIXAS:
        return

    if identificador.isdigit() and len(identificador) == 9:
        return

    logger.warning(f"Identificador inválido: '{identificador}'")
    raise HTTPException(
        status_code=400,
        detail=(
            f"Identificador inválido: '{identificador}'. "
            "Informe um MMSI de 9 dígitos ou um identificador de plataforma fixa "
            "(PPM-1, PCE-1, P-08, P-65)."
        ),
    )


def _normalizar_nome(identificador: str, nome_original: Optional[str] = None) -> str:
    """Retorna o nome correto da plataforma ou embarcação."""
    nome_corrigido = PLATAFORMAS_FIXAS.get(identificador)
    if nome_corrigido:
        return nome_corrigido

    if nome_original:
        return nome_original

    for unidade in get_all_vessels():
        if unidade.mmsi == identificador:
            return unidade.nome

    return identificador


def _normalizar_unidade(unidade: UnidadeMaritima) -> UnidadeMaritima:
    """Garante que plataformas fixas apareçam com os nomes oficiais."""
    nome_corrigido = PLATAFORMAS_FIXAS.get(unidade.mmsi)
    if not nome_corrigido or unidade.nome == nome_corrigido:
        return unidade
    return unidade.model_copy(update={"nome": nome_corrigido})


def _get_fixed_position(identificador: str) -> Optional[Dict[str, Any]]:
    """Monta a posição a partir das coordenadas fixas cadastradas."""
    nome = PLATAFORMAS_FIXAS.get(identificador)
    if not nome:
        return None

    coords = COORDENADAS_PLATAFORMAS.get(nome)
    if not coords:
        return None

    return {
        "mmsi": identificador,
        "nome": nome,
        "latitude": coords["latitude"],
        "longitude": coords["longitude"],
        "timestampAquisicao": datetime.now(timezone.utc).isoformat(),
        "fonte": "coordenada_fixa",
    }


def _converter_posicao_mock(
    posicao: PosicaoAIS, mmsi: str, fonte: str = "fallback_local"
) -> VesselPositionResponse:
    """Converte uma posição mock em VesselPositionResponse."""
    return VesselPositionResponse(
        mmsi=posicao.mmsi,
        nome=posicao.nome,
        latitude=posicao.latitude,
        longitude=posicao.longitude,
        timestampAquisicao=posicao.timestampAquisicao,
        fonte=fonte,
    )


def _is_cache_valid(cache: Dict[str, Dict[str, Any]], key: str) -> bool:
    """Verifica se existe cache válido para a chave informada."""
    entry = cache.get(key)
    if not entry:
        return False
    return datetime.now(timezone.utc) - entry["timestamp"] < CACHE_TTL


def _set_cache(cache: Dict[str, Dict[str, Any]], key: str, value: Any) -> None:
    """Armazena um valor no cache."""
    cache[key] = {"data": value, "timestamp": datetime.now(timezone.utc)}


def _normalize_api_response(
    raw: Any,
    identificador: str,
    fonte: str,
) -> Optional[Dict[str, Any]]:
    """Converte a resposta bruta de uma API para o formato interno."""
    if not raw or not isinstance(raw, dict):
        return None

    mmsi = str(raw.get("mmsi") or identificador)
    nome = raw.get("vesselName") or raw.get("name") or raw.get("nome")
    nome = _normalizar_nome(identificador, nome)

    latitude = raw.get("latitude") or raw.get("lat")
    longitude = raw.get("longitude") or raw.get("lon") or raw.get("lng")

    try:
        latitude = float(latitude) if latitude is not None else None
        longitude = float(longitude) if longitude is not None else None
    except (TypeError, ValueError) as exc:
        logger.warning(f"Coordenadas inválidas para {identificador}: {exc}")
        latitude = None
        longitude = None

    if latitude is None or longitude is None:
        return None

    timestamp = (
        raw.get("timestamp")
        or raw.get("timestampAquisicao")
        or raw.get("lastReceived")
        or datetime.now(timezone.utc).isoformat()
    )

    return {
        "mmsi": mmsi,
        "nome": nome,
        "latitude": latitude,
        "longitude": longitude,
        "timestampAquisicao": timestamp,
        "fonte": fonte,
    }


# ---------------------------------------------------------------------------
# Fontes de dados: Trident e Spinergie
# ---------------------------------------------------------------------------
async def _call_trident_api(identificador: str) -> Optional[Any]:
    """Executa a chamada HTTP ao endpoint da Trident."""
    if not TRIDENT_API_KEY:
        logger.error("Variável de ambiente TRIDENT_API_KEY não configurada")
        return None

    url = f"{TRIDENT_BASE_URL}{TRIDENT_API_PATH}"
    headers = {
        "Authorization": f"ApiKey {TRIDENT_API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    params = {"mmsi": identificador}
    timeout = ClientTimeout(total=15)

    logger.info(f"Consultando Trident para {identificador} - URL: {url}")

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=headers, params=params) as response:
            logger.debug(f"Trident respondeu {response.status} para {identificador}")

            if response.status == 200:
                data = await response.json()
                logger.debug(f"Resposta bruta da Trident para {identificador}: {data}")
                if isinstance(data, list):
                    return data[0] if data else None
                if isinstance(data, dict):
                    return data
                return None

            if response.status == 401:
                logger.error("Falha de autenticação na API Trident (401). Verifique TRIDENT_API_KEY")
            elif response.status == 403:
                logger.error("Acesso negado à API Trident (403)")
            elif response.status == 404:
                logger.warning(f"Embarcação não encontrada na Trident (404) para {identificador}")
            elif response.status >= 500:
                logger.error(f"Erro no servidor Trident ({response.status}) para {identificador}")
            else:
                body = await response.text()
                logger.error(
                    f"Resposta inesperada da Trident ({response.status}) para {identificador}: {body}"
                )

            return None


async def fetch_trident_position_async(identificador: str) -> Optional[Dict[str, Any]]:
    """Busca a posição na Trident com cache e normalização."""
    if _is_cache_valid(_trident_cache, identificador):
        logger.debug(f"Retornando posição do cache Trident para {identificador}")
        return _trident_cache[identificador]["data"]

    try:
        raw = await _call_trident_api(identificador)
    except asyncio.TimeoutError:
        logger.error(f"Timeout ao consultar Trident para {identificador}")
        raw = None
    except aiohttp.ClientError as exc:
        logger.error(f"Erro de conexão com Trident para {identificador}: {exc}")
        raw = None
    except Exception as exc:
        logger.exception(f"Erro inesperado ao consultar Trident para {identificador}: {exc}")
        raw = None

    position = _normalize_api_response(raw, identificador, "trident")
    if position:
        _set_cache(_trident_cache, identificador, position)
        logger.info(f"Posição Trident obtida para {identificador}: ({position['latitude']}, {position['longitude']})")
    return position


async def _call_spinergie_api(identificador: str) -> Optional[Any]:
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
    params = {"mmsi": identificador}
    timeout = ClientTimeout(total=15)

    logger.info(f"Consultando Spinergie para {identificador} - URL: {url}")

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=headers, params=params) as response:
            logger.debug(f"Spinergie respondeu {response.status} para {identificador}")

            if response.status == 200:
                data = await response.json()
                logger.debug(f"Resposta bruta da Spinergie para {identificador}: {data}")
                if isinstance(data, list):
                    return data[0] if data else None
                if isinstance(data, dict):
                    return data
                return None

            if response.status == 401:
                logger.error("Falha de autenticação na API Spinergie (401). Verifique SPINERGIE_API_KEY")
            elif response.status == 403:
                logger.error("Acesso negado à API Spinergie (403)")
            elif response.status == 404:
                logger.warning(f"Embarcação não encontrada no Spinergie (404) para {identificador}")
            elif response.status >= 500:
                logger.error(f"Erro no servidor Spinergie ({response.status}) para {identificador}")
            else:
                body = await response.text()
                logger.error(
                    f"Resposta inesperada do Spinergie ({response.status}) para {identificador}: {body}"
                )

            return None


async def fetch_spinergie_position_async(identificador: str) -> Optional[Dict[str, Any]]:
    """Busca a posição no Spinergie com cache e normalização."""
    if _is_cache_valid(_spinergie_cache, identificador):
        logger.debug(f"Retornando posição do cache Spinergie para {identificador}")
        return _spinergie_cache[identificador]["data"]

    try:
        raw = await _call_spinergie_api(identificador)
    except asyncio.TimeoutError:
        logger.error(f"Timeout ao consultar Spinergie para {identificador}")
        raw = None
    except aiohttp.ClientError as exc:
        logger.error(f"Erro de conexão com Spinergie para {identificador}: {exc}")
        raw = None
    except Exception as exc:
        logger.exception(f"Erro inesperado ao consultar Spinergie para {identificador}: {exc}")
        raw = None

    position = _normalize_api_response(raw, identificador, "spinergie")
    if position:
        _set_cache(_spinergie_cache, identificador, position)
        logger.info(f"Posição Spinergie obtida para {identificador}: ({position['latitude']}, {position['longitude']})")
    return position


# ---------------------------------------------------------------------------
# Dados locais (compatibilidade / testes)
# ---------------------------------------------------------------------------
def get_all_vessels() -> List[UnidadeMaritima]:
    """Retorna a lista de unidades marítimas cadastradas."""
    unidades: List[UnidadeMaritima] = []
    for item in UNIDADES_REGISTRY:
        if not item.get("ativo", True):
            continue
        unidades.append(UnidadeMaritima(**item))
    return unidades


def get_vessel_position(mmsi: str) -> Optional[PosicaoAIS]:
    """Retorna posições mock locais quando as APIs externas não têm dados."""
    mock_positions: Dict[str, Dict[str, Any]] = {
        # Pode ser preenchido com dados de teste quando necessário.
    }
    pos = mock_positions.get(mmsi)
    if pos:
        return PosicaoAIS(**pos)
    return None


# ---------------------------------------------------------------------------
# Resolução de posição com fallback inteligente
# ---------------------------------------------------------------------------
async def _resolver_posicao(identificador: str) -> Optional[Dict[str, Any]]:
    """
    Orquestra a busca de posição priorizando Trident, depois Spinergie e,
    por fim, as coordenadas fixas cadastradas. Valida coordenadas e registra
    discrepâncias entre as fontes.
    """
    fixed = _get_fixed_position(identificador)

    # 1) Tenta Trident (fonte primária)
    trident_pos: Optional[Dict[str, Any]] = None
    try:
        trident_pos = await fetch_trident_position_async(identificador)
        if trident_pos and not _is_valid_coordinate(
            trident_pos["latitude"], trident_pos["longitude"]
        ):
            logger.warning(
                f"Trident retornou coordenadas inválidas para {identificador} "
                f"({trident_pos['latitude']}, {trident_pos['longitude']}); descartando"
            )
            trident_pos = None
        elif trident_pos:
            logger.info(f"Trident retornou posição válida para {identificador}")
    except Exception as exc:
        logger.exception(f"Erro ao consultar Trident para {identificador}: {exc}")

    if trident_pos:
        # Compara com Spinergie (quando disponível) para detectar discrepâncias
        spinergie_pos: Optional[Dict[str, Any]] = None
        try:
            spinergie_pos = await fetch_spinergie_position_async(identificador)
            if spinergie_pos and not _is_valid_coordinate(
                spinergie_pos["latitude"], spinergie_pos["longitude"]
            ):
                logger.warning(
                    f"Spinergie retornou coordenadas inválidas para {identificador}; descartando"
                )
                spinergie_pos = None
        except Exception as exc:
            logger.exception(f"Erro ao consultar Spinergie para {identificador}: {exc}")

        if spinergie_pos:
            distancia = _haversine_distance_km(
                trident_pos["latitude"],
                trident_pos["longitude"],
                spinergie_pos["latitude"],
                spinergie_pos["longitude"],
            )
            if distancia > DISCREPANCY_THRESHOLD_KM:
                logger.warning(
                    f"Discrepância Trident x Spinergie para {identificador}: "
                    f"{distancia:.2f} km (threshold: {DISCREPANCY_THRESHOLD_KM} km)"
                )

        if fixed:
            distancia_fixa = _haversine_distance_km(
                trident_pos["latitude"],
                trident_pos["longitude"],
                fixed["latitude"],
                fixed["longitude"],
            )
            if distancia_fixa > DISCREPANCY_THRESHOLD_KM:
                logger.warning(
                    f"Discrepância Trident x coordenada fixa para {identificador}: "
                    f"{distancia_fixa:.2f} km (threshold: {DISCREPANCY_THRESHOLD_KM} km)"
                )

        return trident_pos

    # 2) Fallback Spinergie
    spinergie_pos = None
    try:
        spinergie_pos = await fetch_spinergie_position_async(identificador)
        if spinergie_pos and not _is_valid_coordinate(
            spinergie_pos["latitude"], spinergie_pos["longitude"]
        ):
            logger.warning(
                f"Spinergie retornou coordenadas inválidas para {identificador}; descartando"
            )
            spinergie_pos = None
        elif spinergie_pos:
            logger.info(f"Spinergie retornou posição válida para {identificador} (fallback)")
    except Exception as exc:
        logger.exception(f"Erro ao consultar Spinergie para {identificador}: {exc}")

    if spinergie_pos:
        if fixed:
            distancia_fixa = _haversine_distance_km(
                spinergie_pos["latitude"],
                spinergie_pos["longitude"],
                fixed["latitude"],
                fixed["longitude"],
            )
            if distancia_fixa > DISCREPANCY_THRESHOLD_KM:
                logger.warning(
                    f"Discrepância Spinergie x coordenada fixa para {identificador}: "
                    f"{distancia_fixa:.2f} km (threshold: {DISCREPANCY_THRESHOLD_KM} km)"
                )
        return spinergie_pos

    # 3) Fallback para coordenadas fixas cadastradas
    if fixed:
        logger.info(f"Usando coordenadas fixas de fallback para {identificador}")
        return fixed

    return None


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="IBAMA API - Monitoramento de Embarcações e Plataformas",
    description=(
        "API para rastreamento em tempo real de embarcações móveis e "
        "plataformas fixas integrada às APIs Trident e Spinergie."
    ),
    version="1.1.0",
    docs_url="/v1/docs",
    openapi_url="/v1/openapi.json",
    redoc_url="/v1/redoc",
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get(
    "/v1/unidades",
    response_model=List[UnidadeMaritima],
    responses={
        503: {
            "model": ErrorResponse,
            "description": "Serviço de listagem de unidades indisponível",
        },
    },
    summary="Listagem completa de unidades marítimas",
    description=(
        "Retorna a lista completa de embarcações móveis e plataformas fixas "
        "monitoradas. Plataformas são normalizadas para os nomes oficiais."
    ),
)
async def listar_unidades() -> List[UnidadeMaritima]:
    logger.info("Requisição recebida: GET /v1/unidades")
    try:
        unidades = get_all_vessels()
        unidades_normalizadas = [_normalizar_unidade(u) for u in unidades]
        logger.info(f"Listagem concluída: {len(unidades_normalizadas)} unidade(s) retornada(s)")
        return unidades_normalizadas
    except Exception as exc:
        logger.exception(f"Erro ao listar unidades: {exc}")
        raise HTTPException(
            status_code=503,
            detail=(
                "Serviço de listagem de unidades está indisponível no momento. "
                "Tente novamente mais tarde."
            ),
        )


@app.get(
    "/v1/posicao/{mmsi}",
    response_model=VesselPositionResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Identificador inválido"},
        404: {"model": ErrorResponse, "description": "Embarcação ou plataforma não encontrada"},
        503: {"model": ErrorResponse, "description": "Serviço de posição indisponível"},
    },
    summary="Consulta posição em tempo real",
    description=(
        "Retorna a posição em tempo real de uma embarcação móvel ou de uma "
        "plataforma fixa (PPM-1, PCE-1, P-08, P-65) a partir do seu MMSI ou "
        "identificador. A fonte primária é a Trident; em caso de falha, usa "
        "Spinergie e, por último, as coordenadas fixas cadastradas."
    ),
)
async def consultar_posicao(
    mmsi: str = Path(
        ...,
        title="MMSI ou identificador da plataforma",
        description=(
            "MMSI da embarcação com 9 dígitos ou identificador de plataforma fixa "
            "(PPM-1, PCE-1, P-08, P-65)"
        ),
        pattern=r"^(?:\d{9}|PPM-1|PCE-1|P-08|P-65)$",
        min_length=1,
        max_length=9,
    )
) -> VesselPositionResponse:
    logger.info(f"Requisição recebida: GET /v1/posicao/{mmsi}")
    _validar_identificador(mmsi)

    posicao = await _resolver_posicao(mmsi)
    if posicao:
        logger.info(
            f"Retornando posição para {mmsi}: fonte={posicao['fonte']} "
            f"({posicao['latitude']}, {posicao['longitude']})"
        )
        return VesselPositionResponse(**posicao)

    # Fallback local para testes/compatibilidade
    logger.info(f"APIs sem dados válidos para {mmsi}; tentando fallback local")
    posicao_mock = get_vessel_position(mmsi)
    if posicao_mock:
        logger.info(f"Posição local encontrada para {mmsi}")
        return _converter_posicao_mock(posicao_mock, mmsi)

    logger.warning(f"Embarcação ou plataforma {mmsi} não encontrada ou sem posição disponível")
    raise HTTPException(
        status_code=404,
        detail=f"Embarcação ou plataforma '{mmsi}' não encontrada ou sem posição disponível.",
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(f"Erro inesperado na requisição {request.url}: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Erro interno no servidor. Por favor, tente novamente mais tarde."
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))