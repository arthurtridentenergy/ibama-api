import os
import time
import logging
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

import httpx
from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format=json.dumps({
        "time": "%(asctime)s",
        "level": "%(levelname)s",
        "name": "%(name)s",
        "message": "%(message)s",
    }),
)
logger = logging.getLogger("spinergie.main")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SPINERGIE_BASE_URL = os.getenv("SPINERGIE_BASE_URL", "https://api.spinergie.com")
SPINERGIE_CLIENT_ID = os.getenv("SPINERGIE_CLIENT_ID", "client_id")
SPINERGIE_CLIENT_SECRET = os.getenv("SPINERGIE_CLIENT_SECRET", "client_secret")
SPINERGIE_AUTH_URL = os.getenv("SPINERGIE_AUTH_URL", f"{SPINERGIE_BASE_URL}/auth/token")
SPINERGIE_SCOPE = os.getenv("SPINERGIE_SCOPE", "read")

API_PREFIX = os.getenv("API_PREFIX", "/v1")
RATE_LIMIT = os.getenv("RATE_LIMIT", "100/minute")

# ---------------------------------------------------------------------------
# Hardcoded platforms (static data)
# ---------------------------------------------------------------------------
HARDCODED_PLATFORMS: List[Dict[str, Any]] = [
    {
        "identificador": "P-65",
        "nome": "Plataforma P-65",
        "tipo": "plataforma",
        "mmsi": None,
        "imo": None,
        "latitude": -22.7833,
        "longitude": -41.8500,
        "velocidade": 0.0,
        "rumo": 0,
        "status": " ancorada",
        "ultima_atualizacao": datetime.now(timezone.utc).isoformat(),
        "fonte": "hardcoded",
    },
    {
        "identificador": "P-08",
        "nome": "Plataforma P-08",
        "tipo": "plataforma",
        "mmsi": None,
        "imo": None,
        "latitude": -22.6500,
        "longitude": -41.7200,
        "velocidade": 0.0,
        "rumo": 0,
        "status": "ancorada",
        "ultima_atualizacao": datetime.now(timezone.utc).isoformat(),
        "fonte": "hardcoded",
    },
    {
        "identificador": "PPM-1",
        "nome": "Plataforma PPM-1",
        "tipo": "plataforma",
        "mmsi": None,
        "imo": None,
        "latitude": -22.4500,
        "longitude": -41.6000,
        "velocidade": 0.0,
        "rumo": 0,
        "status": "ancorada",
        "ultima_atualizacao": datetime.now(timezone.utc).isoformat(),
        "fonte": "hardcoded",
    },
    {
        "identificador": "PCE-1",
        "nome": "Plataforma PCE-1",
        "tipo": "plataforma",
        "mmsi": None,
        "imo": None,
        "latitude": -22.3000,
        "longitude": -41.5000,
        "velocidade": 0.0,
        "rumo": 0,
        "status": "ancorada",
        "ultima_atualizacao": datetime.now(timezone.utc).isoformat(),
        "fonte": "hardcoded",
    },
]

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class PosicaoEmbarcacao(BaseModel):
    identificador: str = Field(..., description="Identificador (MMSI, nome ou código)")
    nome: Optional[str] = Field(None, description="Nome da embarcação")
    tipo: Optional[str] = Field(None, description="Tipo (embarcacao, plataforma)")
    mmsi: Optional[str] = Field(None, description="MMSI")
    imo: Optional[str] = Field(None, description="IMO")
    latitude: Optional[float] = Field(None, description="Latitude")
    longitude: Optional[float] = Field(None, description="Longitude")
    velocidade: Optional[float] = Field(None, description="Velocidade em nós")
    rumo: Optional[int] = Field(None, description="Rumo em graus")
    status: Optional[str] = Field(None, description="Status operacional")
    ultima_atualizacao: Optional[str] = Field(None, description="ISO 8601 timestamp")
    fonte: Optional[str] = Field("spinergie", description="Origem dos dados")


class HealthResponse(BaseModel):
    status: str = Field(..., description="Status do serviço")
    timestamp: str = Field(..., description="Timestamp ISO 8601")
    spinergie: Dict[str, Any] = Field(..., description="Status do serviço Spinergie")
    versao: str = Field("1.0.0", description="Versão da API")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    scope: Optional[str] = None


# ---------------------------------------------------------------------------
# Spinergie Service
# ---------------------------------------------------------------------------
class SpinergieService:
    """Serviço de integração com a API Spinergie."""

    def __init__(
        self,
        base_url: str = SPINERGIE_BASE_URL,
        client_id: str = SPINERGIE_CLIENT_ID,
        client_secret: str = SPINERGIE_CLIENT_SECRET,
        auth_url: str = SPINERGIE_AUTH_URL,
        scope: str = SPINERGIE_SCOPE,
    ):
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.auth_url = auth_url
        self.scope = scope
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        logger.info("SpinergieService inicializado", extra={"base_url": self.base_url})

    async def close(self) -> None:
        await self._client.aclose()

    async def _autenticar(self) -> str:
        """Autentica via OAuth 2.0 (POST /auth/token) e retorna o access token."""
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        logger.info("Autenticando na API Spinergie", extra={"auth_url": self.auth_url})
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": self.scope,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        try:
            response = await self._client.post(self.auth_url, data=payload, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("Erro de status na autenticação Spinergie", extra={
                "status_code": exc.response.status_code,
                "detail": exc.response.text,
            })
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Falha na autenticação Spinergie: {exc.response.status_code}",
            )
        except httpx.RequestError as exc:
            logger.error("Erro de conexão na autenticação Spinergie", extra={"error": str(exc)})
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Serviço Spinergie indisponível",
            )

        data = response.json()
        self._token = data.get("access_token")
        expires_in = int(data.get("expires_in", 3600))
        self._token_expires_at = time.time() + expires_in
        logger.info("Autenticação Spinergie concluída", extra={"expires_in": expires_in})
        return self._token

    async def _headers(self) -> Dict[str, str]:
        token = await self._autenticar()
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    async def listar_unidades(self) -> List[Dict[str, Any]]:
        """GET /v1/unidades - lista todas as unidades (embarcações + plataformas)."""
        url = f"{self.base_url}/v1/unidades"
        logger.info("Listando unidades", extra={"url": url})
        try:
            response = await self._client.get(url, headers=await self._headers())
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("Erro ao listar unidades", extra={
                "status_code": exc.response.status_code,
                "detail": exc.response.text,
            })
            raise HTTPException(
                status_code=exc.response.status_code,
                detail=f"Erro ao listar unidades: {exc.response.text}",
            )
        except httpx.RequestError as exc:
            logger.error("Erro de conexão ao listar unidades", extra={"error": str(exc)})
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Serviço Spinergie indisponível",
            )

        unidades = response.json()
        if isinstance(unidades, dict) and "data" in unidades:
            unidades = unidades["data"]
        if not isinstance(unidades, list):
            unidades = [unidades]

        # Adiciona plataformas hardcoded
        unidades.extend(HARDCODED_PLATFORMS)
        logger.info("Unidades listadas", extra={"total": len(unidades)})
        return unidades

    async def buscar_posicao(self, identificador: str) -> Dict[str, Any]:
        """GET /v1/posicao/{identificador} - busca posição por MMSI numérico/alfanumérico/nome."""
        # Verifica plataformas hardcoded primeiro
        for plataforma in HARDCODED_PLATFORMS:
            if identificador.lower() in [
                plataforma["identificador"].lower(),
                plataforma["nome"].lower(),
            ]:
                logger.info("Plataforma encontrada em dados hardcoded", extra={
                    "identificador": identificador,
                })
                return plataforma

        url = f"{self.base_url}/v1/posicao/{identificador}"
        logger.info("Buscando posição", extra={"url": url, "identificador": identificador})
        try:
            response = await self._client.get(url, headers=await self._headers())
            if response.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Embarcação '{identificador}' não encontrada",
                )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("Erro ao buscar posição", extra={
                "status_code": exc.response.status_code,
                "detail": exc.response.text,
                "identificador": identificador,
            })
            raise HTTPException(
                status_code=exc.response.status_code,
                detail=f"Erro ao buscar posição: {exc.response.text}",
            )
        except httpx.RequestError as exc:
            logger.error("Erro de conexão ao buscar posição", extra={
                "error": str(exc),
                "identificador": identificador,
            })
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Serviço Spinergie indisponível",
            )

        data = response.json()
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        data.setdefault("fonte", "spinergie")
        logger.info("Posição encontrada", extra={"identificador": identificador})
        return data

    async def health_check(self) -> Dict[str, Any]:
        """GET /health - verifica a saúde do serviço Spinergie."""
        url = f"{self.base_url}/health"
        logger.info("Verificando saúde do Spinergie", extra={"url": url})
        try:
            response = await self._client.get(url, timeout=httpx.Timeout(5.0))
            return {
                "status": "online" if response.status_code < 500 else "degraded",
                "status_code": response.status_code,
                "url": url,
            }
        except httpx.RequestError as exc:
            logger.warning("Spinergie indisponível no health check", extra={"error": str(exc)})
            return {
                "status": "offline",
                "status_code": None,
                "url": url,
                "error": str(exc),
            }


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
security = HTTPBearer(auto_error=False)

limiter = Limiter(key_func=get_remote_address, default_limits=[RATE_LIMIT])

app = FastAPI(
    title="API Embarcações - Spinergie",
    description="API para busca de dados em tempo real de embarcações e plataformas via Spinergie.",
    version="1.0.0",
    docs_url=f"{API_PREFIX}/docs",
    redoc_url=f"{API_PREFIX}/redoc",
    openapi_url=f"{API_PREFIX}/openapi.json",
)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

spinergie_service = SpinergieService()


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
async def verificar_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """Verifica o token Bearer fornecido pelo cliente da API."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autenticação não fornecido",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Validação simples: aceita qualquer token não vazio.
    # Em produção, validar JWT ou introspecção OAuth.
    return credentials.credentials


# ---------------------------------------------------------------------------
# Exception handler for rate limiting
# ---------------------------------------------------------------------------
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    logger.warning("Rate limit excedido", extra={
        "client": get_remote_address(request),
        "detail": str(exc.detail),
    })
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "error": "rate_limit_exceeded",
            "message": f"Limite de requisições excedido: {exc.detail}",
            "limit": RATE_LIMIT,
        },
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse, tags=["Saúde"])
@limiter.limit(RATE_LIMIT)
async def health(request: Request):
    """Verifica a saúde do serviço e da integração com Spinergie."""
    spinergie_status = await spinergie_service.health_check()
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(timezone.utc).isoformat(),
        spinergie=spinergie_status,
        versao="1.0.0",
    )


@app.get(
    f"{API_PREFIX}/unidades",
    response_model=List[PosicaoEmbarcacao],
    tags=["Unidades"],
    summary="Lista todas as unidades",
    description="Retorna todas as embarcações em tempo real e plataformas hardcoded.",
)
@limiter.limit(RATE_LIMIT)
async def listar_unidades(
    request: Request,
    token: str = Depends(verificar_token),
):
    """Lista todas as unidades (embarcações + plataformas)."""
    logger.info("Requisição listar_unidades", extra={"token_presente": bool(token)})
    unidades = await spinergie_service.listar_unidades()
    return unidades


@app.get(
    f"{API_PREFIX}/posicao/{{identificador}}",
    response_model=PosicaoEmbarcacao,
    tags=["Posição"],
    summary="Busca posição por identificador",
    description=(
        "Busca a posição em tempo real de uma embarcação por MMSI numérico, "
        "MMSI alfanumérico ou nome. Plataformas (P-65, P-08, PPM-1, PCE-1) "
        "são retornadas de dados hardcoded."
    ),
)
@limiter.limit(RATE_LIMIT)
async def buscar_posicao(
    request: Request,
    identificador: str,
    token: str = Depends(verificar_token),
):
    """Busca a posição de uma embarcação ou plataforma por identificador."""
    logger.info("Requisição buscar_posicao", extra={
        "identificador": identificador,
        "token_presente": bool(token),
    })
    posicao = await spinergie_service.buscar_posicao(identificador)
    return posicao


# ---------------------------------------------------------------------------
# Custom OpenAPI with HTTPBearer security
# ---------------------------------------------------------------------------
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "HTTPBearer": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Informe o token Bearer para autenticação.",
        }
    }
    openapi_schema["security"] = [{"HTTPBearer": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


# ---------------------------------------------------------------------------
# Startup / Shutdown
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    logger.info("API iniciada", extra={
        "prefix": API_PREFIX,
        "rate_limit": RATE_LIMIT,
        "spinergie_url": SPINERGIE_BASE_URL,
    })


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Encerrando API e fechando conexões")
    await spinergie_service.close()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("RELOAD", "false").lower() == "true",
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )