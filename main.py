from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Union
import os
import time
import asyncio
import logging

import httpx
from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from pydantic import BaseModel, Field, field_validator, ConfigDict

# ---------------------------------------------------------------------------
# Configuração de logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("ibama-api")

# ---------------------------------------------------------------------------
# Configurações
# ---------------------------------------------------------------------------
API_BEARER_TOKEN = os.getenv("IBAMA_API_TOKEN", "ibama-secret-token")
SPINERGIE_BASE_URL = os.getenv("SPINERGIE_BASE_URL", "https://api.spinergie.com")
SPINERGIE_API_KEY = os.getenv("SPINERGIE_API_KEY", "")
SPINERGIE_TIMEOUT = float(os.getenv("SPINERGIE_TIMEOUT", "10"))

RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "60"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))  # segundos

# ---------------------------------------------------------------------------
# Modelos Pydantic
# ---------------------------------------------------------------------------
class Posicao(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    identificador: str = Field(..., description="Identificador da embarcação (MMSI, nome ou código alfanumérico)")
    mmsi: Optional[str] = Field(None, description="MMSI convertido para string")
    nome: Optional[str] = Field(None, description="Nome da embarcação")
    latitude: Optional[float] = Field(None, description="Latitude em graus decimais")
    longitude: Optional[float] = Field(None, description="Longitude em graus decimais")
    timestamp: str = Field(..., description="Timestamp ISO 8601 com sufixo Z")
    origem: str = Field("local", description="Origem dos dados (local ou spinergie)")

    @field_validator("mmsi", mode="before")
    @classmethod
    def converter_mmsi_para_string(cls, v):
        if v is None:
            return None
        if isinstance(v, int):
            return str(v)
        if isinstance(v, str):
            return v
        return str(v)


class Unidade(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    identificador: str = Field(..., description="Identificador único da unidade")
    mmsi: Optional[str] = Field(None, description="MMSI como string")
    nome: str = Field(..., description="Nome da unidade")
    tipo: str = Field("embarcacao", description="Tipo da unidade")
    status: str = Field("ativo", description="Status operacional")
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    ultima_atualizacao: str = Field(..., description="Timestamp ISO 8601 com Z")

    @field_validator("mmsi", mode="before")
    @classmethod
    def converter_mmsi_para_string(cls, v):
        if v is None:
            return None
        if isinstance(v, int):
            return str(v)
        return str(v)


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    versao: str
    servicos: Dict[str, str]


# ---------------------------------------------------------------------------
# Base de dados hardcoded (plataformas e embarcações IBAMA)
# ---------------------------------------------------------------------------
PLATAFORMAS: List[Dict[str, Any]] = [
    {
        "identificador": "710002450",
        "mmsi": 710002450,
        "nome": "Maersk Ventura",
        "tipo": "plataforma",
        "status": "ativo",
        "latitude": -22.8123,
        "longitude": -41.9876,
    },
    {
        "identificador": "710001720",
        "mmsi": 710001720,
        "nome": "Maersk Vega",
        "tipo": "plataforma",
        "status": "ativo",
        "latitude": -23.0456,
        "longitude": -42.1234,
    },
    {
        "identificador": "P-65",
        "mmsi": None,
        "nome": "Plataforma P-65",
        "tipo": "plataforma",
        "status": "ativo",
        "latitude": -22.4567,
        "longitude": -41.5678,
    },
    {
        "identificador": "P-08",
        "mmsi": None,
        "nome": "Plataforma P-08",
        "tipo": "plataforma",
        "status": "ativo",
        "latitude": -22.7890,
        "longitude": -41.8901,
    },
    {
        "identificador": "PPM-1",
        "mmsi": None,
        "nome": "Plataforma PPM-1",
        "tipo": "plataforma",
        "status": "ativo",
        "latitude": -23.1234,
        "longitude": -42.2345,
    },
    {
        "identificador": "PCE-1",
        "mmsi": None,
        "nome": "Plataforma PCE-1",
        "tipo": "plataforma",
        "status": "ativo",
        "latitude": -23.3456,
        "longitude": -42.4567,
    },
]


def agora_iso_z() -> str:
    """Retorna timestamp atual em ISO 8601 com sufixo Z (UTC)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def buscar_plataforma_local(identificador: str) -> Optional[Dict[str, Any]]:
    """Busca plataforma por MMSI numérico, MMSI alfanumérico ou nome."""
    ident_lower = identificador.strip().lower()
    for p in PLATAFORMAS:
        candidatos = [
            str(p.get("identificador", "")).lower(),
            str(p.get("nome", "")).lower(),
        ]
        if p.get("mmsi") is not None:
            candidatos.append(str(p["mmsi"]).lower())
        if ident_lower in candidatos:
            return p
    return None


# ---------------------------------------------------------------------------
# Integração Spinergie (com try/except e fallback)
# ---------------------------------------------------------------------------
async def buscar_spinergie(identificador: str) -> Optional[Dict[str, Any]]:
    """Consulta a API Spinergie. Retorna None em caso de erro (fallback local)."""
    if not SPINERGIE_API_KEY:
        logger.debug("SPINERGIE_API_KEY não configurada; usando fallback local.")
        return None

    url = f"{SPINERGIE_BASE_URL}/v1/assets/{identificador}/position"
    headers = {
        "Authorization": f"Bearer {SPINERGIE_API_KEY}",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=SPINERGIE_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                logger.warning("Spinergie respondeu %s para %s", resp.status_code, identificador)
                return None
            data = resp.json()
            return {
                "identificador": identificador,
                "mmsi": data.get("mmsi"),
                "nome": data.get("name"),
                "latitude": data.get("latitude"),
                "longitude": data.get("longitude"),
                "timestamp": data.get("timestamp") or agora_iso_z(),
                "origem": "spinergie",
            }
    except httpx.TimeoutException:
        logger.error("Timeout Spinergie para %s", identificador)
    except httpx.HTTPError as exc:
        logger.error("Erro HTTP Spinergie para %s: %s", identificador, exc)
    except Exception as exc:
        logger.error("Erro inesperado Spinergie para %s: %s", identificador, exc)
    return None


# ---------------------------------------------------------------------------
# Autenticação Bearer Token
# ---------------------------------------------------------------------------
security = HTTPBearer(auto_error=False)


async def verificar_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autenticação ausente ou esquema inválido.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if credentials.credentials != API_BEARER_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token Bearer inválido.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


# ---------------------------------------------------------------------------
# Rate Limiting simples (em memória)
# ---------------------------------------------------------------------------
class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window = window_seconds
        self._requests: Dict[str, List[float]] = {}
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> None:
        async with self._lock:
            now = time.monotonic()
            timestamps = self._requests.get(key, [])
            timestamps = [t for t in timestamps if now - t < self.window]
            if len(timestamps) >= self.max_requests:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Limite de requisições excedido. Tente novamente em alguns instantes.",
                    headers={"Retry-After": str(self.window)},
                )
            timestamps.append(now)
            self._requests[key] = timestamps


rate_limiter = RateLimiter(RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW)


async def rate_limit_dependency(request: Request):
    client_key = request.client.host if request.client else "unknown"
    await rate_limiter.check(client_key)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="API IBAMA",
    description="API para consulta de unidades e posições de plataformas IBAMA.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def handler_erro_nao_tratado(request: Request, exc: Exception):
    logger.exception("Erro não tratado: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Erro interno do servidor."},
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse, tags=["monitoramento"])
async def health_check():
    return HealthResponse(
        status="ok",
        timestamp=agora_iso_z(),
        versao="1.0.0",
        servicos={
            "api": "ok",
            "spinergie": "configurado" if SPINERGIE_API_KEY else "nao_configurado",
            "base_local": "ok",
        },
    )


@app.get(
    "/v1/unidades",
    response_model=List[Unidade],
    tags=["unidades"],
    summary="Lista todas as unidades/plataformas cadastradas",
)
async def listar_unidades(
    _: str = Depends(verificar_token),
    __: None = Depends(rate_limit_dependency),
):
    unidades: List[Unidade] = []
    for p in PLATAFORMAS:
        unidades.append(
            Unidade(
                identificador=p["identificador"],
                mmsi=p.get("mmsi"),
                nome=p["nome"],
                tipo=p.get("tipo", "embarcacao"),
                status=p.get("status", "ativo"),
                latitude=p.get("latitude"),
                longitude=p.get("longitude"),
                ultima_atualizacao=agora_iso_z(),
            )
        )
    return unidades


@app.get(
    "/v1/posicao/{identificador}",
    response_model=Posicao,
    tags=["posicao"],
    summary="Consulta posição de uma unidade por MMSI numérico, alfanumérico ou nome",
)
async def consultar_posicao(
    identificador: str,
    _: str = Depends(verificar_token),
    __: None = Depends(rate_limit_dependency),
):
    # 1) Tentar Spinergie
    dados_spinergie = await buscar_spinergie(identificador)
    if dados_spinergie:
        return Posicao(
            identificador=dados_spinergie["identificador"],
            mmsi=dados_spinergie.get("mmsi"),
            nome=dados_spinergie.get("nome"),
            latitude=dados_spinergie.get("latitude"),
            longitude=dados_spinergie.get("longitude"),
            timestamp=dados_spinergie.get("timestamp") or agora_iso_z(),
            origem="spinergie",
        )

    # 2) Fallback local
    plataforma = buscar_plataforma_local(identificador)
    if plataforma is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Identificador '{identificador}' não encontrado.",
        )

    return Posicao(
        identificador=plataforma["identificador"],
        mmsi=plataforma.get("mmsi"),
        nome=plataforma.get("nome"),
        latitude=plataforma.get("latitude"),
        longitude=plataforma.get("longitude"),
        timestamp=agora_iso_z(),
        origem="local",
    )


@app.get("/", tags=["raiz"])
async def raiz():
    return {
        "servico": "API IBAMA",
        "versao": "1.0.0",
        "endpoints": [
            "/health",
            "/v1/unidades",
            "/v1/posicao/{identificador}",
            "/docs",
        ],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=bool(os.getenv("DEBUG", "0") == "1"),
    )