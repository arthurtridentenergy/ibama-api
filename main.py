import os
import math
import logging
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import httpx
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

VERSION = "1.0.0"
APP_NAME = "IBAMA Vessels & Platforms API"


class VesselType(str, Enum):
    PLATFORM = "PLATFORM"
    TANKER = "TANKER"
    FPSO = "FPSO"
    SUPPORT = "SUPPORT"
    CARGO = "CARGO"


class LicenseType(str, Enum):
    OPERATING = "OPERATING"
    EXPLORATION = "EXPLORATION"
    PRODUCTION = "PRODUCTION"
    TRANSPORT = "TRANSPORT"
    NAVIGATION = "NAVIGATION"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PENDING = "PENDING"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"


class VesselStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    UNDER_WAY = "UNDER_WAY"
    AT_ANCHOR = "AT_ANCHOR"
    MOORED = "MOORED"
    UNKNOWN = "UNKNOWN"


class Coordinates(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="Latitude em graus decimais")
    lon: float = Field(..., ge=-180, le=180, description="Longitude em graus decimais")


class License(BaseModel):
    id: str
    name: str
    holder: str
    license_type: LicenseType
    status: LicenseStatus
    start_date: str
    end_date: str
    area_block: Optional[str] = None
    related_asset: str


class Vessel(BaseModel):
    id: str
    name: str
    mmsi: Optional[str] = None
    vessel_type: VesselType
    flag: str
    coordinates: Coordinates
    status: VesselStatus
    speed: float = Field(..., ge=0, description="Velocidade em nós")
    course: float = Field(..., ge=0, lt=360, description="Curso em graus")
    destination: Optional[str] = None
    last_update: str
    license_id: str


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Any
    timestamp: str
    version: str = VERSION


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str
    uptime_seconds: int


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _convert_dm_to_decimal(degrees: int, minutes: float, hemisphere: str) -> float:
    decimal = abs(degrees) + minutes / 60.0
    if hemisphere.upper() in ("S", "W"):
        decimal = -decimal
    return round(decimal, 6)


LICENSES: List[License] = [
    License(
        id="IBAMA-OP-P65-2018",
        name="Licença de Operação - Plataforma P-65",
        holder="Petrobras",
        license_type=LicenseType.OPERATING,
        status=LicenseStatus.ACTIVE,
        start_date="2018-01-15",
        end_date="2028-01-14",
        area_block="BM-C-33",
        related_asset="P-65",
    ),
    License(
        id="IBAMA-OP-P08-2015",
        name="Licença de Operação - Plataforma P-08",
        holder="Petrobras",
        license_type=LicenseType.OPERATING,
        status=LicenseStatus.ACTIVE,
        start_date="2015-08-10",
        end_date="2025-08-09",
        area_block="BM-C-33",
        related_asset="P-08",
    ),
    License(
        id="IBAMA-EXPL-PPM1-2020",
        name="Licença de Exploração - PPM-1",
        holder="Petrobras",
        license_type=LicenseType.EXPLORATION,
        status=LicenseStatus.ACTIVE,
        start_date="2020-03-22",
        end_date="2025-03-21",
        area_block="BM-C-33",
        related_asset="PPM-1",
    ),
    License(
        id="IBAMA-PROD-PCE1-2019",
        name="Licença de Produção - PCE-1",
        holder="Petrobras",
        license_type=LicenseType.PRODUCTION,
        status=LicenseStatus.ACTIVE,
        start_date="2019-06-01",
        end_date="2029-05-31",
        area_block="BM-C-33",
        related_asset="PCE-1",
    ),
    License(
        id="IBAMA-NAV-VENTURA-2023",
        name="Licença de Navegação - Maersk Ventura",
        holder="Maersk",
        license_type=LicenseType.TRANSPORT,
        status=LicenseStatus.ACTIVE,
        start_date="2023-01-01",
        end_date="2025-12-31",
        related_asset="Maersk Ventura",
    ),
    License(
        id="IBAMA-NAV-VEGA-2022",
        name="Licença de Navegação - Maersk Vega",
        holder="Maersk",
        license_type=LicenseType.TRANSPORT,
        status=LicenseStatus.ACTIVE,
        start_date="2022-06-01",
        end_date="2024-12-31",
        related_asset="Maersk Vega",
    ),
]

PLATFORMS: List[Vessel] = [
    Vessel(
        id="P-65",
        name="Plataforma P-65",
        mmsi=None,
        vessel_type=VesselType.PLATFORM,
        flag="BR",
        coordinates=Coordinates(
            lat=_convert_dm_to_decimal(22, 42.11, "S"),
            lon=_convert_dm_to_decimal(40, 40.63, "W"),
        ),
        status=VesselStatus.OPERATIONAL,
        speed=0.0,
        course=0.0,
        destination="P-65",
        last_update=_now_iso(),
        license_id="IBAMA-OP-P65-2018",
    ),
    Vessel(
        id="P-08",
        name="Plataforma P-08",
        mmsi=None,
        vessel_type=VesselType.PLATFORM,
        flag="BR",
        coordinates=Coordinates(
            lat=_convert_dm_to_decimal(22, 40.39, "S"),
            lon=_convert_dm_to_decimal(40, 32.79, "W"),
        ),
        status=VesselStatus.OPERATIONAL,
        speed=0.0,
        course=0.0,
        destination="P-08",
        last_update=_now_iso(),
        license_id="IBAMA-OP-P08-2015",
    ),
    Vessel(
        id="PPM-1",
        name="Plataforma PPM-1",
        mmsi=None,
        vessel_type=VesselType.PLATFORM,
        flag="BR",
        coordinates=Coordinates(
            lat=_convert_dm_to_decimal(22, 47.88, "S"),
            lon=_convert_dm_to_decimal(40, 45.75, "W"),
        ),
        status=VesselStatus.OPERATIONAL,
        speed=0.0,
        course=0.0,
        destination="PPM-1",
        last_update=_now_iso(),
        license_id="IBAMA-EXPL-PPM1-2020",
    ),
    Vessel(
        id="PCE-1",
        name="Plataforma PCE-1",
        mmsi=None,
        vessel_type=VesselType.PLATFORM,
        flag="BR",
        coordinates=Coordinates(
            lat=_convert_dm_to_decimal(22, 42.50, "S"),
            lon=_convert_dm_to_decimal(40, 41.59, "W"),
        ),
        status=VesselStatus.OPERATIONAL,
        speed=0.0,
        course=0.0,
        destination="PCE-1",
        last_update=_now_iso(),
        license_id="IBAMA-PROD-PCE1-2019",
    ),
]

VESSEL_CONFIG: List[Dict[str, Any]] = [
    {
        "id": "maersk-ventura",
        "name": "Maersk Ventura",
        "mmsi": "710002450",
        "type": VesselType.TANKER,
        "flag": "BR",
        "license_id": "IBAMA-NAV-VENTURA-2023",
        "base": Coordinates(
            lat=_convert_dm_to_decimal(22, 42.11, "S"),
            lon=_convert_dm_to_decimal(40, 40.63, "W"),
        ),
        "phase": 0.0,
        "radius": 0.025,
    },
    {
        "id": "maersk-vega",
        "name": "Maersk Vega",
        "mmsi": "710001720",
        "type": VesselType.TANKER,
        "flag": "BR",
        "license_id": "IBAMA-NAV-VEGA-2022",
        "base": Coordinates(
            lat=_convert_dm_to_decimal(22, 40.39, "S"),
            lon=_convert_dm_to_decimal(40, 32.79, "W"),
        ),
        "phase": 2.0,
        "radius": 0.030,
    },
]


class VesselDataProvider:
    def __init__(self, cache_ttl_seconds: int = 60):
        self.cache_ttl = cache_ttl_seconds
        self._cache: Dict[str, Vessel] = {}
        self._last_fetch: Optional[datetime] = None
        self._lock = None

    async def initialize(self):
        self._lock = asyncio.Lock()

    async def get_all_vessels(self) -> List[Vessel]:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._is_cache_stale():
                await self._refresh()
            return list(self._cache.values())

    async def get_by_mmsi(self, mmsi: str) -> Optional[Vessel]:
        vessels = await self.get_all_vessels()
        for vessel in vessels:
            if vessel.mmsi == mmsi or vessel.id == mmsi:
                return vessel
        return None

    async def get_platforms(self) -> List[Vessel]:
        vessels = await self.get_all_vessels()
        return [v for v in vessels if v.vessel_type == VesselType.PLATFORM]

    def _is_cache_stale(self) -> bool:
        if not self._cache or self._last_fetch is None:
            return True
        return datetime.now(timezone.utc) - self._last_fetch > timedelta(seconds=self.cache_ttl)

    async def _refresh(self):
        try:
            fetched = await self._fetch_real_time_from_external()
        except Exception as exc:
            logger.warning("Falha ao buscar dados externos: %s. Usando simulador.", exc)
            fetched = []

        if fetched:
            merged = {v.mmsi or v.id: v for v in PLATFORMS}
            for v in fetched:
                merged[v.mmsi or v.id] = v
            self._cache = merged
        else:
            self._cache = self._simulate_real_time_data()

        self._last_fetch = datetime.now(timezone.utc)

    async def _fetch_real_time_from_external(self) -> List[Vessel]:
        api_url = os.getenv("AIS_API_URL")
        api_key = os.getenv("AIS_API_KEY")
        if not api_url:
            return []

        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        mmsi_list = [cfg["mmsi"] for cfg in VESSEL_CONFIG]
        vessels: List[Vessel] = []

        async with httpx.AsyncClient(timeout=15.0) as client:
            for mmsi in mmsi_list:
                url = api_url.format(mmsi=mmsi)
                try:
                    response = await client.get(url, headers=headers)
                    response.raise_for_status()
                    payload = response.json()
                    vessel = self._parse_ais_payload(mmsi, payload)
                    if vessel:
                        vessels.append(vessel)
                except Exception as exc:
                    logger.warning("Erro ao buscar MMSI %s: %s", mmsi, exc)

        return vessels

    def _parse_ais_payload(self, mmsi: str, payload: Dict[str, Any]) -> Optional[Vessel]:
        cfg = next((c for c in VESSEL_CONFIG if c["mmsi"] == mmsi), None)
        if cfg is None:
            return None
        try:
            return Vessel(
                id=cfg["id"],
                name=payload.get("name") or cfg["name"],
                mmsi=mmsi,
                vessel_type=cfg["type"],
                flag=payload.get("flag") or cfg["flag"],
                coordinates=Coordinates(
                    lat=float(payload["latitude"]),
                    lon=float(payload["longitude"]),
                ),
                status=VesselStatus(payload.get("status", "UNDER_WAY")),
                speed=float(payload.get("speed", 0.0)),
                course=float(payload.get("course", 0.0)),
                destination=payload.get("destination"),
                last_update=_now_iso(),
                license_id=cfg["license_id"],
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("Payload inválido para MMSI %s: %s", mmsi, exc)
            return None

    def _simulate_real_time_data(self) -> Dict[str, Vessel]:
        data: Dict[str, Vessel] = {v.id: v for v in PLATFORMS}
        now = datetime.now(timezone.utc)
        t = now.timestamp() / 60.0

        for cfg in VESSEL_CONFIG:
            phase = cfg["phase"]
            radius = cfg["radius"]
            base = cfg["base"]

            lat = base.lat + radius * math.cos((t + phase) / 10.0)
            lon = base.lon + radius * math.sin((t + phase) / 10.0)
            speed = 4.0 + 3.0 * math.sin((t + phase) / 5.0)
            course = ((t * 5.0 + phase * 30.0) % 360.0)

            status = VesselStatus.UNDER_WAY if speed > 1.0 else VesselStatus.AT_ANCHOR
            data[cfg["id"]] = Vessel(
                id=cfg["id"],
                name=cfg["name"],
                mmsi=cfg["mmsi"],
                vessel_type=cfg["type"],
                flag=cfg["flag"],
                coordinates=Coordinates(lat=round(lat, 6), lon=round(lon, 6)),
                status=status,
                speed=round(abs(speed), 2),
                course=round(course, 2),
                destination="BC-33 Terminal",
                last_update=now.isoformat(),
                license_id=cfg["license_id"],
            )

        return data


provider = VesselDataProvider(cache_ttl_seconds=60)
startup_time = datetime.now(timezone.utc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await provider.initialize()
    await provider.get_all_vessels()
    logger.info("Aplicação %s iniciada (v%s)", APP_NAME, VERSION)
    yield
    logger.info("Aplicação %s finalizada", APP_NAME)


app = FastAPI(
    title=APP_NAME,
    description="API para integração de dados de embarcações e plataformas offshore supervisionadas pelo IBAMA.",
    version=VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content=ApiResponse(
            success=False,
            message=exc.detail,
            data=None,
            timestamp=_now_iso(),
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.exception("Erro inesperado: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ApiResponse(
            success=False,
            message="Erro interno no servidor. A equipe de suporte foi notificada.",
            data=None,
            timestamp=_now_iso(),
        ).model_dump(),
    )


@app.get("/health", response_model=ApiResponse, tags=["Health"])
async def health_check():
    uptime = int((datetime.now(timezone.utc) - startup_time).total_seconds())
    return ApiResponse(
        success=True,
        message="Serviço operacional",
        data=HealthResponse(
            status="ok",
            timestamp=_now_iso(),
            version=VERSION,
            uptime_seconds=uptime,
        ).model_dump(),
        timestamp=_now_iso(),
    )


@app.get("/api/v1/vessels", response_model=ApiResponse, tags=["Vessels"])
async def list_vessels():
    try:
        vessels = await provider.get_all_vessels()
        return ApiResponse(
            success=True,
            message=f"{len(vessels)} embarcações/plataformas encontradas",
            data=[v.model_dump() for v in vessels],
            timestamp=_now_iso(),
        )
    except Exception as exc:
        logger.error("Erro ao listar embarcações: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível recuperar a lista de embarcações.",
        )


@app.get("/api/v1/vessels/{mmsi}", response_model=ApiResponse, tags=["Vessels"])
async def get_vessel(mmsi: str):
    try:
        vessel = await provider.get_by_mmsi(mmsi)
        if not vessel:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Embarcação ou plataforma com identificador '{mmsi}' não encontrada.",
            )
        return ApiResponse(
            success=True,
            message="Dados da embarcação/plataforma recuperados com sucesso",
            data=vessel.model_dump(),
            timestamp=_now_iso(),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Erro ao buscar embarcação %s: %s", mmsi, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível recuperar os dados da embarcação.",
        )


@app.get("/api/v1/platforms", response_model=ApiResponse, tags=["Platforms"])
async def list_platforms():
    try:
        platforms = await provider.get_platforms()
        return ApiResponse(
            success=True,
            message=f"{len(platforms)} plataformas encontradas",
            data=[p.model_dump() for p in platforms],
            timestamp=_now_iso(),
        )
    except Exception as exc:
        logger.error("Erro ao listar plataformas: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível recuperar a lista de plataformas.",
        )


@app.get("/api/v1/licenses", response_model=ApiResponse, tags=["Licenses"])
async def list_licenses():
    try:
        return ApiResponse(
            success=True,
            message=f"{len(LICENSES)} licenças encontradas",
            data=[lic.model_dump() for lic in LICENSES],
            timestamp=_now_iso(),
        )
    except Exception as exc:
        logger.error("Erro ao listar licenças: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível recuperar a lista de licenças.",
        )


if __name__ == "__main__":
    import asyncio

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=os.getenv("ENVIRONMENT", "production").lower() == "development",
    )