from fastapi import FastAPI, HTTPException, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
import logging
from spinergie_service import fetch_vessel_position_async

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="API de Posição de Embarcações",
    description="API para consulta de posição em tempo real de embarcações via integração Spinergie.",
    version="1.0.0",
)


class VesselPositionResponse(BaseModel):
    mmsi: str = Field(..., description="Maritime Mobile Service Identity (MMSI) da embarcação", example="710001720")
    nome: str = Field(..., description="Nome da embarcação", example="MAERSK VEGA")
    latitude: float = Field(..., description="Latitude da posição da embarcação", example=-22.0816707611)
    longitude: float = Field(..., description="Longitude da posição da embarcação", example=-40.7330474854)
    timestampAquisicao: str = Field(
        ...,
        description="Data e hora da aquisição da posição no formato ISO 8601",
        example="2026-06-25T13:56:11+00:00Z",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "mmsi": "710001720",
                "nome": "MAERSK VEGA",
                "latitude": -22.0816707611,
                "longitude": -40.7330474854,
                "timestampAquisicao": "2026-06-25T13:56:11+00:00Z",
            }
        }


class ErrorResponse(BaseModel):
    detail: str = Field(..., description="Mensagem descritiva do erro")


def validate_mmsi(mmsi: str) -> None:
    if not mmsi:
        raise HTTPException(status_code=400, detail="MMSI é obrigatório.")

    if not mmsi.isdigit():
        raise HTTPException(
            status_code=400,
            detail=f"MMSI inválido: '{mmsi}'. O MMSI deve conter apenas dígitos numéricos.",
        )

    if len(mmsi) != 9:
        raise HTTPException(
            status_code=400,
            detail=f"MMSI inválido: '{mmsi}'. O MMSI deve possuir exatamente 9 dígitos.",
        )


@app.get(
    "/v1/posicao/{mmsi}",
    response_model=VesselPositionResponse,
    responses={
        400: {"model": ErrorResponse, "description": "MMSI inválido"},
        404: {"model": ErrorResponse, "description": "Embarcação não encontrada"},
        503: {"model": ErrorResponse, "description": "Serviço Spinergie indisponível"},
    },
    summary="Consulta posição em tempo real de uma embarcação",
    description="Retorna a posição em tempo real de uma embarcação a partir do seu MMSI, utilizando a integração Spinergie.",
)
async def get_vessel_position(
    mmsi: str = Path(
        ...,
        title="MMSI",
        description="Maritime Mobile Service Identity (MMSI) da embarcação com 9 dígitos numéricos",
        min_length=9,
        max_length=9,
        pattern="^\\d{9}$",
    )
):
    validate_mmsi(mmsi)

    try:
        vessel_data = await fetch_vessel_position_async(mmsi)
    except HTTPException as http_exc:
        raise http_exc
    except Exception as exc:
        logger.error(f"Erro ao comunicar com o serviço Spinergie para MMSI {mmsi}: {exc}")
        raise HTTPException(
            status_code=503,
            detail="Serviço Spinergie está indisponível no momento. Tente novamente mais tarde.",
        )

    if not vessel_data:
        raise HTTPException(
            status_code=404,
            detail=f"Embarcação com MMSI '{mmsi}' não encontrada ou sem posição disponível.",
        )

    try:
        position = VesselPositionResponse(
            mmsi=str(vessel_data.get("mmsi", mmsi)),
            nome=vessel_data.get("nome") or vessel_data.get("name") or "N/A",
            latitude=float(vessel_data.get("latitude")),
            longitude=float(vessel_data.get("longitude")),
            timestampAquisicao=vessel_data.get("timestampAquisicao")
            or vessel_data.get("timestamp")
            or vessel_data.get("lastUpdate"),
        )
    except (TypeError, ValueError) as exc:
        logger.error(f"Formato inesperado de resposta do Spinergie para MMSI {mmsi}: {exc}")
        raise HTTPException(
            status_code=503,
            detail="Resposta inesperada do serviço Spinergie. Serviço pode estar indisponível.",
        )

    return position


@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    logger.error(f"Erro inesperado na requisição {request.url}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Erro interno no servidor. Por favor, tente novamente mais tarde."},
    )