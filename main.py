import asyncio
import os
import math
import logging
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional, List, Dict, Any, Union
from contextlib import asynccontextmanager
from collections import defaultdict

from fastapi import FastAPI, HTTPException, status, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

VERSION = "1.0.0"
APP_NAME = "IBAMA Maritime Units API"


class TipoUnidade(str, Enum):
    UNIDADE_PRODUCAO = "UNIDADE_PRODUCAO"
    UNIDADE_PERFURACAO = "UNIDADE_PERFURACAO"
    EMBARCACAO_APOIO = "EMBARCACAO_APOIO"
    EMBARCACAO_TRANSPORTE = "EMBARCACAO_TRANSPORTE"


class UnidadeMaritima(BaseModel):
    id: str
    nome: str
    tipo: TipoUnidade
    mmsi: Optional[str] = None
    licenca: str
    latitude_base: float
    longitude_base: float


class PosicaoAIS(BaseModel):
    mmsi: str
    latitude: float
    longitude: float
    velocidade_nos: float
    curso_graus: float
    destino: Optional[str] = None
    timestamp: str
    status: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int


class ErrorResponse(BaseModel):
    success: bool = False
    message: str
    data: None = None
    timestamp: str


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Any
    timestamp: str
    version: str = VERSION


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# =============================================
# Internal data structures for simulação
# =============================================

class Coordinates(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


# Unidades fixas (plataformas)
PLATFORMS_DATA = [
    {
        "id": "P-65",
        "nome": "P-65",
        "tipo": TipoUnidade.UNIDADE_PRODUCAO,
        "mmsi": "538003593",
        "latitude_base": -22.7018,
        "longitude_base": -40.6772,
        "licenca": "LO1572/2020",
    },
    {
        "id": "P-08",
        "nome": "P-08",
        "tipo": TipoUnidade.UNIDADE_PRODUCAO,
        "mmsi": "538001903",
        "latitude_base": -22.6732,
        "longitude_base": -40.5465,
        "licenca": "LO1572/2020",
    },
    {
        "id": "PPM-1",
        "nome": "PPM-1",
        "tipo": TipoUnidade.UNIDADE_PERFURACAO,
        "mmsi": "PPM-1",
        "latitude_base": -22.7980,
        "longitude_base": -40.7625,
        "licenca": "LO1572/2020",
    },
    {
        "id": "PCE-1",
        "nome": "PCE-1",
        "tipo": TipoUnidade.UNIDADE_PERFURACAO,
        "mmsi": "PCE-1",
        "latitude_base": -22.7083,
        "longitude_base": -40.6932,
        "licenca": "LO1572/2020",
    },
]

# Embarcações móveis (configuração para simulação)
VESSEL_CONFIG = [
    {
        "id": "maersk-ventura",
        "nome": "Maersk Ventura",
        "mmsi": "710002450",
        "tipo": TipoUnidade.EMBARCACAO_TRANSPORTE,
        "base_lat": -22.7018,
        "base_lon": -40.6772,
        "phase": 0.0,
        "radius": 0.025,
        "licenca": "LO1572/2020",
    },
    {
        "id": "maersk-vega",
        "nome": "Maersk Vega",
        "mmsi": "710001720",
        "tipo": TipoUnidade.EMBARCACAO_TRANSPORTE,
        "base_lat": -22.6732,
        "base_lon": -40.5465,
        "phase": 2.0,
        "radius": 0.030,
        "licenca": "LO1572/2020",
    },
]


class VesselDataProvider:
    """Gerencia dados de posição com cache e simulador."""

    def __init__(self, cache_ttl_seconds: int = 60):
        self.cache_ttl = cache_ttl_seconds
        self._cache: Dict[str, PosicaoAIS] = {}
        self._last_fetch: Optional[datetime] = None
        self._lock = asyncio.Lock()

    async def initialize(self):
        # Preenche o cache na inicialização
        await self._refresh()

    async def get_all_positions(self) -> List[PosicaoAIS]:
        async with self._lock:
            if self._is_cache_stale():
                await self._refresh()
            return list(self._cache.values())

    async def get_position_by_mmsi(self, mmsi: str) -> Optional[PosicaoAIS]:
        async with self._lock:
            if self._is_cache_stale():
                await self._refresh()
            return self._cache.get(mmsi)

    def _is_cache_stale(self) -> bool:
        if not self._cache or self._last_fetch is None:
            return True
        return datetime.now(timezone.utc) - self._last_fetch > timedelta(seconds=self.cache_ttl)

    async def _refresh(self):
        try:
            fetched = await self._fetch_real_time()
            if fetched:
                # Mescla com dados fixos das plataformas (sempre disponíveis)
                merged = {}
                for plat in PLATFORMS_DATA:
                    if plat["mmsi"]:
                        merged[plat["mmsi"]] = PosicaoAIS(
                            mmsi=plat["mmsi"],
                            latitude=plat["latitude_base"],
                            longitude=plat["longitude_base"],
                            velocidade_nos=0.0,
                            curso_graus=0.0,
                            timestamp=_now_iso(),
                            status="FIXA",
                        )
                for pos in fetched:
                    merged[pos.mmsi] = pos
                self._cache = merged
            else:
                self._cache = self._simulate_positions()
        except Exception as exc:
            logger.warning("Falha na atualização dos dados, usando simulação: %s", exc)
            self._cache = self._simulate_positions()
        self._last_fetch = datetime.now(timezone.utc)

    async def _fetch_real_time(self) -> List[PosicaoAIS]:
        api_url = os.getenv("AIS_API_URL")
        api_key = os.getenv("AIS_API_KEY")
        if not api_url:
            return []
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        mmsi_list = [v["mmsi"] for v in VESSEL_CONFIG]
        positions = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            for mmsi in mmsi_list:
                url = api_url.format(mmsi=mmsi)
                try:
                    resp = await client.get(url, headers=headers)
                    resp.raise_for_status()
                    payload = resp.json()
                    positions.append(PosicaoAIS(
                        mmsi=mmsi,
                        latitude=float(payload["latitude"]),
                        longitude=float(payload["longitude"]),
                        velocidade_nos=float(payload.get("speed", 0.0)),
                        curso_graus=float(payload.get("course", 0.0)),
                        destino=payload.get("destination"),
                        timestamp=_now_iso(),
                        status=payload.get("status", "UNDER_WAY"),
                    ))
                except Exception as exc:
                    logger.warning("Erro ao buscar MMSI %s: %s", mmsi, exc)
        return positions

    ### def _simulate_positions(self) -> Dict[str, PosicaoAIS]:
        data: Dict[str, PosicaoAIS] = {}
        now = datetime.now(timezone.utc)
        t = now.timestamp() / 60.0

        # Plataformas fixas
        for plat in PLATFORMS_DATA:
            if plat["mmsi"]:  # Algumas plataformas podem ter MMSI, usamos id como chave se não tiver
                key = plat["mmsi"]
            else:
                key = plat["id"]  # Chave interna para plataformas sem MMSI
            data[key] = PosicaoAIS(
                mmsi=key,
                latitude=plat["latitude_base"],
                longitude=plat["longitude_base"],
                velocidade_nos=0.0,
                curso_graus=0.0,
                timestamp=_now_iso(),
                status="FIXA",
            )

        # Embarcações simuladas
        for cfg in VESSEL_CONFIG:
            phase = cfg["phase"]
            radius = cfg["radius"]
            base_lat = cfg["base_lat"]
            base_lon = cfg["base_lon"]
            mmsi = cfg["mmsi"]

            lat = base_lat + radius * math.cos((t + phase) / 10.0)
            lon = base_lon + radius * math.sin((t + phase) / 10.0)
            speed = 4.0 + 3.0 * math.sin((t + phase) / 5.0)
            course = ((t * 5.0 + phase * 30.0) % 360.0)
            status = "EM_MOVIMENTO" if speed > 1.0 else "PARADO"

            data[mmsi] = PosicaoAIS(
                mmsi=mmsi,
                latitude=round(lat, 6),
                longitude=round(lon, 6),
                velocidade_nos=round(abs(speed), 2),
                curso_graus=round(course, 2),
                destino="Terminal BC-33",
                timestamp=_now_iso(),
                status=status,
            )
        return data ###

def _simulate_positions(self):
    data = {}
    for key in self.positions:
        data[key] = PosicaoAIS(
            mmsi=str(key),  # ← CORRETO: converter para string
            latitude=self.positions[key]["latitude"],
            longitude=self.positions[key]["longitude"],
            timestampAquisicao=datetime.now(timezone.utc).isoformat() + "Z",
            status="FIXA",
        )
    return data

# Instância global do provider
provider = VesselDataProvider(cache_ttl_seconds=60)
startup_time = datetime.now(timezone.utc)


# =============================================
# Rate Limiter simples por IP
# =============================================

class RateLimiter:
    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self.requests: Dict[str, List[datetime]] = defaultdict(list)

    async def __call__(self, request: Request):
        client_ip = request.client.host
        now = datetime.now(timezone.utc)
        # Remove entradas antigas
        self.requests[client_ip] = [
            t for t in self.requests[client_ip]
            if now - t < timedelta(seconds=self.window)
        ]
        if len(self.requests[client_ip]) >= self.max_requests:
            raise HTTPException(
                status_code=429,
                detail="Muitas requisições. Aguarde e tente novamente.",
            )
        self.requests[client_ip].append(now)


rate_limiter = RateLimiter()


# =============================================
# FastAPI App e Middlewares
# =============================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    await provider.initialize()
    logger.info("Aplicação %s iniciada (v%s)", APP_NAME, VERSION)
    yield
    logger.info("Aplicação %s finalizada", APP_NAME)


app = FastAPI(
    title=APP_NAME,
    description="API IBAMA para consulta de unidades marítimas e posições AIS.",
    version=VERSION,
    docs_url="/v1/docs",
    redoc_url="/v1/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================
# Tratamento de erros
# =============================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            success=False,
            message=exc.detail,
            timestamp=_now_iso(),
        ).model_dump(),
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.exception("Erro inesperado: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            success=False,
            message="Erro interno do servidor.",
            timestamp=_now_iso(),
        ).model_dump(),
    )


# =============================================
# Endpoints OAuth2
# =============================================

# Simula um banco de clientes
VALID_CLIENTS = {
    "ibama": "secret",
}

@app.post("/v1/auth/token", response_model=TokenResponse, tags=["Autenticação"], dependencies=[Depends(rate_limiter)])
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """Autenticação OAuth 2.0 Client Credentials."""
    client_id = form_data.username
    client_secret = form_data.password
    if client_id not in VALID_CLIENTS or VALID_CLIENTS[client_id] != client_secret:
        raise HTTPException(
            status_code=401,
            detail="Credenciais inválidas.",
        )
    # Em produção geraria um JWT; aqui retornamos um token fixo para demonstração
    return TokenResponse(
        access_token="fake-jwt-token-ibama",
        token_type="bearer",
        expires_in=3600,
    )


# =============================================
# Endpoints IBAMA
# =============================================

@app.get("/v1/unidades", response_model=ApiResponse, tags=["Unidades"], dependencies=[Depends(rate_limiter)])
async def list_unidades():
    """Lista todas as unidades marítimas cadastradas."""
    unidades = []
    # Plataformas
    for p in PLATFORMS_DATA:
        unidades.append(UnidadeMaritima(
            id=p["id"],
            nome=p["nome"],
            tipo=p["tipo"],
            mmsi=p["mmsi"],
            licenca=p["licenca"],
            latitude_base=p["latitude_base"],
            longitude_base=p["longitude_base"],
        ))
    # Embarcações
    for v in VESSEL_CONFIG:
        unidades.append(UnidadeMaritima(
            id=v["id"],
            nome=v["nome"],
            tipo=v["tipo"],
            mmsi=v["mmsi"],
            licenca=v["licenca"],
            latitude_base=v["base_lat"],
            longitude_base=v["base_lon"],
        ))
    return ApiResponse(
        success=True,
        message=f"{len(unidades)} unidades encontradas.",
        data=[u.model_dump() for u in unidades],
        timestamp=_now_iso(),
    )


@app.get("/v1/posicao/{mmsi}", response_model=ApiResponse, tags=["Posições"], dependencies=[Depends(rate_limiter)])
async def get_posicao_by_mmsi(mmsi: str):
    """Obtém a última posição AIS de uma unidade pelo MMSI."""
    # Permite buscar por id de plataforma (caso não tenha MMSI) ou MMSI real
    pos = await provider.get_position_by_mmsi(mmsi)
    if not pos:
        raise HTTPException(status_code=404, detail=f"Unidade com MMSI/ID {mmsi} não encontrada.")
    return ApiResponse(
        success=True,
        message="Posição obtida com sucesso.",
        data=pos.model_dump(),
        timestamp=_now_iso(),
    )


@app.get("/health", response_model=ApiResponse, tags=["Saúde"])
async def health_check():
    """Verifica a saúde da aplicação."""
    uptime = int((datetime.now(timezone.utc) - startup_time).total_seconds())
    return ApiResponse(
        success=True,
        message="Serviço operacional.",
        data={
            "status": "ok",
            "timestamp": _now_iso(),
            "version": VERSION,
            "uptime_seconds": uptime,
        },
        timestamp=_now_iso(),
    )


# =============================================
# Ponto de entrada
# =============================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=os.getenv("ENVIRONMENT", "production").lower() == "development",
    )