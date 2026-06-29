import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from data import get_all_vessels, get_vessel_position
from models import PosicaoAIS, UnidadeMaritima
from spinergie_service import fetch_vessel_position_async


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

app = FastAPI(
    title="IBAMA API - Monitoramento de Embarcações e Plataformas",
    description=(
        "API para rastreamento em tempo real de embarcações móveis e "
        "plataformas fixas integrada ao Spinergie."
    ),
    version="1.0.0",
    docs_url="/v1/docs",
    openapi_url="/v1/openapi.json",
    redoc_url="/v1/redoc",
)


class VesselPositionResponse(BaseModel):
    mmsi: str = Field(
        ...,
        description="Maritime Mobile Service Identity (MMSI) da embarcação ou plataforma",
        example="710001720",
    )
    nome: str = Field(
        ...,
        description="Nome da embarcação ou plataforma",
        example="P-65",
    )
    latitude: float = Field(
        ...,
        description="Latitude da posição",
        example=-22.0816707611,
    )
    longitude: float = Field(
        ...,
        description="Longitude da posição",
        example=-40.7330474854,
    )
    timestampAquisicao: str = Field(
        ...,
        description="Data e hora da aquisição da posição no formato ISO 8601",
        example="2026-06-25T13:56:11+00:00",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "mmsi": "710001720",
                "nome": "P-65",
                "latitude": -22.0816707611,
                "longitude": -40.7330474854,
                "timestampAquisicao": "2026-06-25T13:56:11+00:00",
            }
        }


class ErrorResponse(BaseModel):
    detail: str = Field(..., description="Mensagem descritiva do erro")


# ---------------------------------------------------------------------------
# Configuração de plataformas fixas
# ---------------------------------------------------------------------------
P08_MMSI = os.getenv("P08_MMSI", "000000008")
P65_MMSI = os.getenv("P65_MMSI", "000000065")

PLATAFORMAS_FIXAS: Dict[str, str] = {
    P08_MMSI: "P-08",
    P65_MMSI: "P-65",
}

COORDENADAS_PLATAFORMAS: Dict[str, Dict[str, float]] = {
    "P-08": {
        "latitude": float(os.getenv("P08_LATITUDE", "-22.5")),
        "longitude": float(os.getenv("P08_LONGITUDE", "-40.0")),
    },
    "P-65": {
        "latitude": float(os.getenv("P65_LATITUDE", "-23.5")),
        "longitude": float(os.getenv("P65_LONGITUDE", "-41.0")),
    },
}

logger.info(f"Plataformas fixas configuradas: {list(PLATAFORMAS_FIXAS.values())}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _validar_mmsi(mmsi: str) -> None:
    """Valida se o MMSI possui exatamente 9 dígitos numéricos."""
    if not mmsi:
        logger.warning("MMSI não informado")
        raise HTTPException(status_code=400, detail="MMSI é obrigatório.")

    if not mmsi.isdigit():
        logger.warning(f"MMSI inválido (não numérico): '{mmsi}'")
        raise HTTPException(
            status_code=400,
            detail=(
                f"MMSI inválido: '{mmsi}'. "
                "O MMSI deve conter apenas 9 dígitos numéricos."
            ),
        )

    if len(mmsi) != 9:
        logger.warning(f"MMSI inválido (tamanho {len(mmsi)}): '{mmsi}'")
        raise HTTPException(
            status_code=400,
            detail=(
                f"MMSI inválido: '{mmsi}'. "
                "O MMSI deve possuir exatamente 9 dígitos."
            ),
        )


def _is_plataforma_fixa(mmsi: str) -> Optional[str]:
    """Retorna o nome da plataforma fixa caso o MMSI corresponda."""
    return PLATAFORMAS_FIXAS.get(mmsi)


def _normalizar_nome(mmsi: str, nome_original: Optional[str] = None) -> str:
    """Retorna o nome correto da plataforma ou embarcação."""
    nome_corrigido = PLATAFORMAS_FIXAS.get(mmsi)
    if nome_corrigido:
        return nome_corrigido

    if nome_original:
        return nome_original

    for unidade in get_all_vessels():
        if unidade.mmsi == mmsi:
            return unidade.nome

    return "DESCONHECIDO"


def _normalizar_unidade(unidade: UnidadeMaritima) -> UnidadeMaritima:
    """Garante que plataformas fixas apareçam com os nomes oficiais P-08/P-65."""
    nome_corrigido = PLATAFORMAS_FIXAS.get(unidade.mmsi)
    if not nome_corrigido or unidade.nome == nome_corrigido:
        return unidade

    try:
        return unidade.model_copy(update={"nome": nome_corrigido})
    except AttributeError:
        unidade.nome = nome_corrigido
        return unidade


def _converter_posicao_mock(posicao: PosicaoAIS, mmsi: str) -> VesselPositionResponse:
    """Converte uma posição mock em VesselPositionResponse."""
    return VesselPositionResponse(
        mmsi=posicao.mmsi,
        nome=_normalizar_nome(posicao.mmsi),
        latitude=posicao.latitude,
        longitude=posicao.longitude,
        timestampAquisicao=posicao.timestampAquisicao,
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
        "monitoradas. Plataformas são normalizadas para os nomes oficiais P-08 e P-65."
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
        400: {"model": ErrorResponse, "description": "MMSI inválido"},
        404: {"model": ErrorResponse, "description": "Embarcação ou plataforma não encontrada"},
        503: {"model": ErrorResponse, "description": "Serviço Spinergie indisponível"},
    },
    summary="Consulta posição em tempo real",
    description=(
        "Retorna a posição em tempo real de uma embarcação móvel ou de uma "
        "plataforma fixa (P-08, P-65) a partir do seu MMSI."
    ),
)
async def consultar_posicao(
    mmsi: str = Path(
        ...,
        title="MMSI",
        description="MMSI da embarcação ou plataforma com 9 dígitos numéricos",
        min_length=9,
        max_length=9,
        pattern=r"^\d{9}$",
    )
) -> VesselPositionResponse:
    logger.info(f"Requisição recebida: GET /v1/posicao/{mmsi}")
    _validar_mmsi(mmsi)

    # --- Plataforma fixa: retorna coordenadas estáticas ----------------------
    nome_plataforma = _is_plataforma_fixa(mmsi)
    if nome_plataforma:
        logger.info(f"MMSI {mmsi} identificado como plataforma fixa: {nome_plataforma}")
        coords = COORDENADAS_PLATAFORMAS.get(nome_plataforma)
        if not coords:
            logger.error(f"Coordenadas não configuradas para {nome_plataforma}")
            raise HTTPException(
                status_code=503,
                detail=f"Coordenadas não configuradas para a plataforma {nome_plataforma}.",
            )

        return VesselPositionResponse(
            mmsi=mmsi,
            nome=nome_plataforma,
            latitude=coords["latitude"],
            longitude=coords["longitude"],
            timestampAquisicao=datetime.now(timezone.utc).isoformat(),
        )

    # --- Embarcação móvel: consulta Spinergie ------------------------------
    logger.info(f"MMSI {mmsi} é embarcação móvel; consultando Spinergie")
    try:
        vessel_data = await fetch_vessel_position_async(mmsi)
    except Exception as exc:
        logger.exception(f"Erro ao comunicar com o serviço Spinergie para MMSI {mmsi}: {exc}")
        raise HTTPException(
            status_code=503,
            detail=(
                "Serviço Spinergie está indisponível no momento. "
                "Tente novamente mais tarde."
            ),
        )

    if vessel_data:
        nome = _normalizar_nome(
            mmsi,
            vessel_data.get("nome") or vessel_data.get("name"),
        )
        try:
            posicao = VesselPositionResponse(
                mmsi=str(vessel_data.get("mmsi", mmsi)),
                nome=nome,
                latitude=float(vessel_data.get("latitude")),
                longitude=float(vessel_data.get("longitude")),
                timestampAquisicao=(
                    vessel_data.get("timestampAquisicao")
                    or vessel_data.get("timestamp")
                    or vessel_data.get("lastReceived")
                    or datetime.now(timezone.utc).isoformat()
                ),
            )
            logger.info(f"Posição Spinergie retornada para MMSI {mmsi}: {posicao.nome}")
            return posicao
        except (TypeError, ValueError) as exc:
            logger.error(f"Formato inesperado de resposta do Spinergie para MMSI {mmsi}: {exc}")
            raise HTTPException(
                status_code=503,
                detail=(
                    "Resposta inesperada do serviço Spinergie. "
                    "Serviço pode estar indisponível."
                ),
            )

    # --- Fallback para dados locais (testes) ---------------------------------
    logger.info(f"Spinergie não retornou dados para MMSI {mmsi}; tentando fallback local")
    posicao_mock = get_vessel_position(mmsi)
    if posicao_mock:
        logger.info(f"Posição local encontrada para MMSI {mmsi}")
        return _converter_posicao_mock(posicao_mock, mmsi)

    logger.warning(f"Embarcação com MMSI {mmsi} não encontrada ou sem posição disponível")
    raise HTTPException(
        status_code=404,
        detail=f"Embarcação com MMSI '{mmsi}' não encontrada ou sem posição disponível.",
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