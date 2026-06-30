from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Load environment variables from .env file if available
load_dotenv()

# Environment validation
REQUIRED_ENV_VARS = ["JWT_SECRET_KEY", "SPINERGIE_API_KEY"]
for var in REQUIRED_ENV_VARS:
    if not os.getenv(var):
        raise RuntimeError(f"Environment variable {var} is required but not set.")

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
SPINERGIE_API_KEY = os.getenv("SPINERGIE_API_KEY", "")
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
PORT = int(os.getenv("PORT", "8000"))


# Logging configuration optimized for Render (JSON to stdout)
class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj, ensure_ascii=False)


def setup_logging() -> logging.Logger:
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    # Remove existing handlers to avoid duplicates
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(JSONFormatter())
    logger.addHandler(stream_handler)
    return logger


logger = setup_logging()


# Pydantic models
class Platform(BaseModel):
    id: str
    name: str
    code: str
    type: str
    latitude: float
    longitude: float
    region: str
    operator: str
    status: str


class Vessel(BaseModel):
    mmsi: int
    name: str
    imo: Optional[str] = None
    type: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    speed_knots: Optional[float] = None
    course: Optional[float] = None
    last_update: Optional[datetime] = None
    status: Optional[str] = None


class VesselTrackRequest(BaseModel):
    mmsi: int = Field(
        ..., ge=100000000, le=999999999, description="MMSI number of the vessel"
    )
    name: Optional[str] = Field(None, description="Optional vessel name")


class VesselLocation(BaseModel):
    mmsi: int
    name: str
    latitude: float
    longitude: float
    speed_knots: Optional[float] = None
    course: Optional[float] = None
    last_update: datetime
    source: str


class License(BaseModel):
    id: str
    process_number: str
    company: str
    activity: str
    location: str
    status: str
    issue_date: Optional[str] = None
    expiration_date: Optional[str] = None
    environmental_authorization: str


class HealthCheck(BaseModel):
    status: str
    healthy: bool
    version: str
    environment: str
    timestamp: datetime
    checks: Dict[str, Any]


# Hardcoded data
PLATFORMS: List[Platform] = [
    Platform(
        id="platform-001",
        name="PPM-1",
        code="PPM-1",
        type="FPSO",
        latitude=-22.5123,
        longitude=-40.0123,
        region="Bacia de Campos",
        operator="Petrobras",
        status="Operacional",
    ),
    Platform(
        id="platform-002",
        name="PCE-1",
        code="PCE-1",
        type="Plataforma Fixa",
        latitude=-22.6234,
        longitude=-40.1234,
        region="Bacia de Campos",
        operator="Petrobras",
        status="Operacional",
    ),
    Platform(
        id="platform-003",
        name="P-08",
        code="P-08",
        type="Plataforma Semi-submersível",
        latitude=-22.7345,
        longitude=-40.2345,
        region="Bacia de Campos",
        operator="Petrobras",
        status="Operacional",
    ),
    Platform(
        id="platform-004",
        name="P-65",
        code="P-65",
        type="FPSO",
        latitude=-22.8456,
        longitude=-40.3456,
        region="Bacia de Campos",
        operator="Petrobras",
        status="Operacional",
    ),
]

VESSELS_BASE: List[Dict[str, Any]] = [
    {
        "mmsi": 219017000,
        "name": "Maersk Vega",
        "imo": "9290940",
        "type": "Navio Tanque de Produtos",
        "latitude": -22.9000,
        "longitude": -43.1700,
        "speed_knots": 12.5,
        "course": 90.0,
    },
    {
        "mmsi": 219018000,
        "name": "Maersk Ventura",
        "imo": "9290952",
        "type": "Navio de Carga Geral",
        "latitude": -23.9600,
        "longitude": -46.3300,
        "speed_knots": 0.0,
        "course": 0.0,
    },
]

IBAMA_LICENSES: List[License] = [
    License(
        id="lic-001",
        process_number="02001.008430/2014-10",
        company="Petrobras",
        activity="Exploração e Produção de Petróleo e Gás Natural",
        location="Bacia de Campos - Rio de Janeiro",
        status="Ativa",
        issue_date="2014-05-15",
        expiration_date="2029-05-15",
        environmental_authorization="Licença de Operação",
    ),
    License(
        id="lic-002",
        process_number="02001.008431/2014-11",
        company="Petrobras",
        activity="Descarte de Resíduos em Águas Jurisdicionais Brasileiras",
        location="Bacia de Campos - Rio de Janeiro",
        status="Ativa",
        issue_date="2015-03-10",
        expiration_date="2028-03-10",
        environmental_authorization="Autorização de Dispensa de Licença Ambiental",
    ),
    License(
        id="lic-003",
        process_number="02001.008432/2014-12",
        company="Shell Brasil",
        activity="Atividades de Apoio Marítimo em Plataformas Offshore",
        location="Bacia de Santos - São Paulo",
        status="Ativa",
        issue_date="2016-08-22",
        expiration_date="2027-08-22",
        environmental_authorization="Licença de Instalação",
    ),
    License(
        id="lic-004",
        process_number="02001.008433/2014-13",
        company="Equinor Brasil",
        activity="Pesquisa e Lavra de Hidrocarbonetos em Águas Profundas",
        location="Bacia de Campos - Rio de Janeiro",
        status="Em Análise",
        issue_date=None,
        expiration_date=None,
        environmental_authorization="Licença Prévia",
    ),
]


# AIS service
async def fetch_ais_data(mmsi: int) -> Optional[Dict[str, Any]]:
    """
    Attempts to fetch real-time AIS data for a given MMSI.
    Falls back to None if the external provider is unavailable.
    """
    ais_api_url = os.getenv("AIS_API_URL")
    if not ais_api_url:
        return None

    api_key = os.getenv("AIS_API_KEY") or SPINERGIE_API_KEY
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    timeout = float(os.getenv("AIS_API_TIMEOUT", "10.0"))

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{ais_api_url.rstrip('/')}/vessel/{mmsi}",
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            logger.info(f"Successfully fetched AIS data for MMSI {mmsi}")
            return data
    except httpx.HTTPStatusError as e:
        logger.warning(f"AIS API returned {e.response.status_code} for MMSI {mmsi}")
    except httpx.RequestError as e:
        logger.warning(f"AIS API request failed for MMSI {mmsi}: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error fetching AIS data for MMSI {mmsi}: {e}")
    return None


def enrich_vessel_with_ais(
    base_vessel: Dict[str, Any], ais_data: Optional[Dict[str, Any]]
) -> Vessel:
    if ais_data:
        return Vessel(
            mmsi=base_vessel["mmsi"],
            name=base_vessel["name"],
            imo=base_vessel.get("imo"),
            type=base_vessel["type"],
            latitude=ais_data.get("latitude"),
            longitude=ais_data.get("longitude"),
            speed_knots=ais_data.get("speed"),
            course=ais_data.get("course"),
            last_update=datetime.now(timezone.utc),
            status="Dados AIS em tempo real",
        )
    return Vessel(
        mmsi=base_vessel["mmsi"],
        name=base_vessel["name"],
        imo=base_vessel.get("imo"),
        type=base_vessel["type"],
        latitude=base_vessel.get("latitude"),
        longitude=base_vessel.get("longitude"),
        speed_knots=base_vessel.get("speed_knots"),
        course=base_vessel.get("course"),
        last_update=datetime.now(timezone.utc),
        status="Dados simulados (provedor AIS indisponível)",
    )


def get_vessel_base_by_mmsi(mmsi: int) -> Optional[Dict[str, Any]]:
    for vessel in VESSELS_BASE:
        if vessel["mmsi"] == mmsi:
            return vessel.copy()
    return None


# FastAPI application with default docs at /docs and OpenAPI at /openapi.json
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting application version {APP_VERSION} in {ENVIRONMENT} mode")
    yield
    logger.info("Application shutdown")


app = FastAPI(
    title="Offshore Operations API",
    description="API for managing offshore platforms, vessels with AIS data, and IBAMA licenses.",
    version=APP_VERSION,
    lifespan=lifespan,
)

router = APIRouter(prefix="/v1")


# Exception handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning(f"HTTP {exc.status_code}: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": "HTTP Error",
            "detail": exc.detail,
            "status_code": exc.status_code,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(f"Validation error: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "Validation Error",
            "detail": exc.errors(),
            "status_code": 422,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal Server Error",
            "detail": "An unexpected error occurred. Please try again later.",
            "status_code": 500,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


# Routes
@router.get(
    "/health",
    response_model=HealthCheck,
    tags=["Health"],
    summary="Health and readiness check",
)
async def health_check():
    return HealthCheck(
        status="healthy",
        healthy=True,
        version=APP_VERSION,
        environment=ENVIRONMENT,
        timestamp=datetime.now(timezone.utc),
        checks={
            "jwt_secret_configured": bool(JWT_SECRET_KEY),
            "spinergie_api_key_configured": bool(SPINERGIE_API_KEY),
            "platforms_data_loaded": len(PLATFORMS) > 0,
            "vessels_data_loaded": len(VESSELS_BASE) > 0,
            "licenses_data_loaded": len(IBAMA_LICENSES) > 0,
        },
    )


@router.get(
    "/platforms",
    response_model=List[Platform],
    tags=["Platforms"],
    summary="List offshore platforms with hardcoded coordinates",
)
async def list_platforms():
    return PLATFORMS


@router.get(
    "/vessels",
    response_model=List[Vessel],
    tags=["Vessels"],
    summary="List vessels with real-time AIS data",
)
async def list_vessels():
    tasks = [fetch_ais_data(v["mmsi"]) for v in VESSELS_BASE]
    ais_results = await asyncio.gather(*tasks, return_exceptions=True)

    vessels = []
    for base, ais_result in zip(VESSELS_BASE, ais_results):
        if isinstance(ais_result, Exception):
            logger.warning(f"Failed to fetch AIS for {base['name']}: {ais_result}")
            ais_result = None
        vessels.append(enrich_vessel_with_ais(base, ais_result))
    return vessels


@router.get(
    "/licenses",
    response_model=List[License],
    tags=["Licenses"],
    summary="List IBAMA licenses and authorizations",
)
async def list_licenses():
    return IBAMA_LICENSES


@router.post(
    "/vessels/track",
    response_model=Vessel,
    tags=["Vessels"],
    summary="Track a vessel by MMSI",
)
async def track_vessel(request: VesselTrackRequest):
    base = get_vessel_base_by_mmsi(request.mmsi)
    if not base:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vessel with MMSI {request.mmsi} not found",
        )
    ais_data = await fetch_ais_data(request.mmsi)
    return enrich_vessel_with_ais(base, ais_data)


@router.get(
    "/vessels/{mmsi}/location",
    response_model=VesselLocation,
    tags=["Vessels"],
    summary="Get current location of a vessel",
)
async def get_vessel_location(mmsi: int):
    if mmsi < 100000000 or mmsi > 999999999:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MMSI must be a 9-digit number",
        )
    base = get_vessel_base_by_mmsi(mmsi)
    if not base:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vessel with MMSI {mmsi} not found",
        )
    ais_data = await fetch_ais_data(mmsi)
    vessel = enrich_vessel_with_ais(base, ais_data)
    return VesselLocation(
        mmsi=vessel.mmsi,
        name=vessel.name,
        latitude=vessel.latitude or 0.0,
        longitude=vessel.longitude or 0.0,
        speed_knots=vessel.speed_knots,
        course=vessel.course,
        last_update=vessel.last_update or datetime.now(timezone.utc),
        source="AIS" if ais_data else "Simulated",
    )


app.include_router(router)


# Non-admin friendly startup (uses unprivileged port by default)
if __name__ == "__main__":
    import uvicorn

    logger.info(f"Starting Uvicorn on 0.0.0.0:{PORT}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        log_level="info",
        access_log=False,
        log_config=None,
    )