import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger("spinergie_locations_proxy")


# ---------------------------------------------------------------------------
# Configuration - read from environment variables
# ---------------------------------------------------------------------------
class AppConfig:
    def __init__(self) -> None:
        self.base_url = (os.getenv("SPINERGIE_BASE_URL") or "https://api.spinergie.com").rstrip("/")
        self.username = os.getenv("SPINERGIE_USERNAME")
        self.password = os.getenv("SPINERGIE_PASSWORD")
        self.api_token = os.getenv("SPINERGIE_API_TOKEN")
        self.timeout = int(os.getenv("SPINERGIE_TIMEOUT", "30"))
        # Comma-separated names, easy to extend without touching the code.
        self.platform_names = self._split(
            os.getenv("SPINERGIE_PLATFORM_NAMES", "PCE-1,PPM-1,P-08,P-65")
        )
        self.vessel_names = self._split(
            os.getenv("SPINERGIE_VESSEL_NAMES", "Maersk Vega,Maersk Ventura")
        )

    @staticmethod
    def _split(value: str) -> List[str]:
        if not value:
            return []
        return [item.strip() for item in value.split(",") if item.strip()]

    def has_credentials(self) -> bool:
        return bool(self.api_token) or (bool(self.username) and bool(self.password))


config = AppConfig()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Spinergie Locations Proxy",
    description="Proxy para localizações de plataformas e embarcações do Spinergie",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Pydantic models / validation
# ---------------------------------------------------------------------------
class LocationItem(BaseModel):
    """Item normalizado de localização. Campos extras do Spinergie são preservados."""

    name: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    class Config:
        extra = "allow"


class AllLocationsData(BaseModel):
    platforms: List[LocationItem]
    vessels: List[LocationItem]


class ApiResponse(BaseModel):
    status: str = "success"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    count: int
    data: Any
    message: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers to normalize Spinergie responses
# ---------------------------------------------------------------------------
LATITUDE_KEYS = ("latitude", "lat", "y", "Latitude", "Lat")
LONGITUDE_KEYS = ("longitude", "lon", "lng", "x", "Longitude", "Long")


def find_coordinate(obj: Any, keys: Tuple[str, ...]) -> Optional[float]:
    """Busca latitude/longitude no dicionário principal ou em subdicionários comuns."""
    if isinstance(obj, dict):
        for key in keys:
            value = obj.get(key)
            if value is not None:
                try:
                    return float(value)
                except (ValueError, TypeError):
                    continue
        for nested in ("location", "position", "coordinates", "geo", "geometry"):
            nested_value = obj.get(nested)
            if isinstance(nested_value, dict):
                found = find_coordinate(nested_value, keys)
                if found is not None:
                    return found
    return None


def find_name(item: Dict[str, Any]) -> Optional[str]:
    for key in ("name", "vesselName", "platformName", "poiName", "Name"):
        value = item.get(key)
        if value:
            return str(value).strip()
    return None


def normalize_and_filter(
    raw_items: List[Dict[str, Any]], allowed_names: List[str]
) -> List[LocationItem]:
    """Filtra pelo nome configurado e valida/normaliza as coordenadas."""
    allowed_set = {name.strip() for name in allowed_names}
    results: List[LocationItem] = []

    for item in raw_items:
        if not isinstance(item, dict):
            logger.warning("Item não-dict ignorado na resposta do Spinergie")
            continue

        name = find_name(item)
        if not name:
            logger.warning("Item sem nome ignorado")
            continue

        if allowed_set and name not in allowed_set:
            continue

        latitude = find_coordinate(item, LATITUDE_KEYS)
        longitude = find_coordinate(item, LONGITUDE_KEYS)

        if latitude is None or longitude is None:
            logger.warning("'%s' ignorado: coordenadas ausentes ou inválidas", name)
            continue

        normalized = {"name": name, "latitude": latitude, "longitude": longitude}
        for key, value in item.items():
            if key not in normalized:
                normalized[key] = value

        try:
            location = LocationItem(**normalized)
            results.append(location)
        except ValidationError as exc:
            logger.warning("Erro de validação para '%s': %s", name, exc)
            continue

    results.sort(key=lambda loc: loc.name)
    return results


# ---------------------------------------------------------------------------
# Spinergie HTTP client
# ---------------------------------------------------------------------------
def get_auth() -> Tuple[Dict[str, str], Optional[httpx.BasicAuth]]:
    headers: Dict[str, str] = {}
    auth: Optional[httpx.BasicAuth] = None
    if config.api_token:
        headers["Authorization"] = f"Bearer {config.api_token}"
    elif config.username and config.password:
        auth = httpx.BasicAuth(config.username, config.password)
    return headers, auth


def parse_list_response(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "items", "results", "locations", "vessels", "platforms"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


async def fetch_spinergie(path: str) -> List[Dict[str, Any]]:
    if not config.has_credentials():
        logger.error("Credenciais do Spinergie não configuradas")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Spinergie credentials not configured",
        )

    headers, auth = get_auth()
    url = f"{config.base_url}{path}"

    async with httpx.AsyncClient(timeout=config.timeout, headers=headers) as client:
        try:
            response = await client.get(url, auth=auth)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("Erro upstream %s em %s: %s", exc.response.status_code, url, exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Upstream Spinergie returned status {exc.response.status_code}",
            )
        except httpx.RequestError as exc:
            logger.error("Erro de requisição para %s: %s", url, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to reach Spinergie API",
            )

    try:
        raw_data = response.json()
    except ValueError as exc:
        logger.error("JSON inválido de %s: %s", url, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid JSON response from Spinergie",
        )

    data = parse_list_response(raw_data)
    if not isinstance(data, list) or (not data and not isinstance(raw_data, list)):
        logger.error("Formato inesperado da resposta de %s: %s", url, type(raw_data))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unexpected response format from Spinergie",
        )

    return data


async def fetch_platforms() -> List[LocationItem]:
    raw = await fetch_spinergie("/sd/api/poi/locations")
    return normalize_and_filter(raw, config.platform_names)


async def fetch_vessels() -> List[LocationItem]:
    raw = await fetch_spinergie("/sd/api/vessel/sfm-latest-locations")
    return normalize_and_filter(raw, config.vessel_names)


def build_response(data: Any, count: Optional[int] = None) -> ApiResponse:
    return ApiResponse(
        status="success",
        count=count if count is not None else (len(data) if hasattr(data, "__len__") else 0),
        data=data,
    )


# ---------------------------------------------------------------------------
# Startup / error handling
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def on_startup() -> None:
    logger.info("Iniciando Spinergie Locations Proxy")
    logger.info("Base URL: %s", config.base_url)
    logger.info("Plataformas configuradas: %s", config.platform_names)
    logger.info("Embarcações configuradas: %s", config.vessel_names)
    if not config.has_credentials():
        logger.warning(
            "Nenhuma credencial do Spinergie configurada. "
            "Defina SPINERGIE_API_TOKEN ou SPINERGIE_USERNAME + SPINERGIE_PASSWORD"
        )


@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception) -> JSONResponse:
    logger.exception("Erro não tratado")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ApiResponse(
            status="error",
            timestamp=datetime.now(timezone.utc).isoformat(),
            count=0,
            data=None,
            message="Internal server error",
        ).dict(),
    )


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------
@app.get("/api/locations/all", response_model=ApiResponse)
async def get_all_locations():
    """Retorna plataformas e embarcações em uma única resposta."""
    platforms_task = asyncio.create_task(fetch_platforms())
    vessels_task = asyncio.create_task(fetch_vessels())
    results = await asyncio.gather(platforms_task, vessels_task, return_exceptions=True)

    errors: List[str] = []
    for result in results:
        if isinstance(result, Exception):
            if isinstance(result, HTTPException):
                errors.append(str(result.detail))
            else:
                errors.append(str(result))

    if errors:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Erro ao buscar dados do Spinergie: {'; '.join(errors)}",
        )

    platforms, vessels = results
    data = AllLocationsData(platforms=platforms, vessels=vessels)
    return build_response(data, count=len(platforms) + len(vessels))


@app.get("/api/platforms/locations", response_model=ApiResponse)
async def get_platform_locations():
    """Retorna apenas as plataformas configuradas."""
    platforms = await fetch_platforms()
    return build_response(platforms)


@app.get("/api/vessels/locations", response_model=ApiResponse)
async def get_vessel_locations():
    """Retorna apenas as embarcações configuradas."""
    vessels = await fetch_vessels()
    return build_response(vessels)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)