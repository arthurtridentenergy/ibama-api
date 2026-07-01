import os
import time
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from collections import defaultdict, deque

from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

try:
    from spinergie_service import SpinergieService
except Exception:
    SpinergieService = None


# ---------------------------------------------------------------------------
# Configuração de logging estruturado
# ---------------------------------------------------------------------------
class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_payload, ensure_ascii=False)


logging.basicConfig(level=logging.INFO)
root_logger = logging.getLogger()
for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(StructuredFormatter())
root_logger.addHandler(stream_handler)

logger = logging.getLogger("ibama.api")


# ---------------------------------------------------------------------------
# Configurações
# ---------------------------------------------------------------------------
API_TITLE = "API IBAMA"
API_VERSION = "1.0.0"
API_DESCRIPTION = "API IBAMA com autenticação OAuth 2.0 Client Credentials e integração com Spinergie."

CLIENT_ID = os.getenv("IBAMA_CLIENT_ID", "ibama_client")
CLIENT_SECRET = os.getenv("IBAMA_CLIENT_SECRET", "super_secret_change_me")
TOKEN_TTL_SECONDS = int(os.getenv("IBAMA_TOKEN_TTL", "3600"))
RATE_LIMIT_PER_MINUTE = int(os.getenv("IBAMA_RATE_LIMIT", "100"))

ALLOWED_ORIGINS = os.getenv("IBAMA_CORS_ORIGINS", "*").split(",")

security_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------
class TokenRequest(BaseModel):
    grant_type: str = Field(..., description="Tipo de concessão OAuth 2.0")
    client_id: str = Field(..., description="Identificador do cliente")
    client_secret: str = Field(..., description="Segredo do cliente")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int


class Unidade(BaseModel):
    identificador: str
    nome: str
    tipo: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    status: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


class Posicao(BaseModel):
    identificador: str
    latitude: float
    longitude: float
    timestamp: Optional[str] = None
    velocidade: Optional[float] = None
    rumo: Optional[float] = None
    status: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: str
    spinergie: str


# ---------------------------------------------------------------------------
# Armazenamento em memória de tokens e rate limiting
# ---------------------------------------------------------------------------
_active_tokens: Dict[str, Dict[str, Any]] = {}
_rate_limit_buckets: Dict[str, deque] = defaultdict(deque)


def _prune_tokens() -> None:
    now = time.time()
    expired = [t for t, meta in _active_tokens.items() if meta["expires_at"] <= now]
    for token in expired:
        _active_tokens.pop(token, None)


def _create_token() -> str:
    token = secrets.token_urlsafe(48)
    _active_tokens[token] = {
        "client_id": CLIENT_ID,
        "issued_at": time.time(),
        "expires_at": time.time() + TOKEN_TTL_SECONDS,
    }
    return token


def _verify_token(token: str) -> bool:
    _prune_tokens()
    meta = _active_tokens.get(token)
    if not meta:
        return False
    return meta["expires_at"] > time.time()


def _rate_limit_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(key: str) -> None:
    now = time.time()
    window_start = now - 60
    bucket = _rate_limit_buckets[key]
    while bucket and bucket[0] < window_start:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT_PER_MINUTE:
        logger.warning("Rate limit excedido", extra={"client": key, "limit": RATE_LIMIT_PER_MINUTE})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Limite de requisicoes por minuto excedido.",
            headers={"Retry-After": "60"},
        )
    bucket.append(now)


# ---------------------------------------------------------------------------
# Dependências
# ---------------------------------------------------------------------------
async def rate_limiter(request: Request) -> None:
    key = _rate_limit_key(request)
    _check_rate_limit(key)


async def authenticate(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
) -> str:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais de autenticacao ausentes ou invalidas.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    if not _verify_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido ou expirado.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


def get_spinergie_service() -> Optional[Any]:
    if SpinergieService is None:
        logger.warning("SpinergieService nao disponivel")
        return None
    try:
        return SpinergieService()
    except Exception as exc:
        logger.error("Falha ao instanciar SpinergieService", exc_info=exc)
        return None


# ---------------------------------------------------------------------------
# Aplicação FastAPI
# ---------------------------------------------------------------------------
app = FastAPI(
    title=API_TITLE,
    description=API_DESCRIPTION,
    version=API_VERSION,
    docs_url="/v1/docs",
    redoc_url="/v1/redoc",
    openapi_url="/v1/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in ALLOWED_ORIGINS],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration_ms = round((time.time() - start) * 1000, 2)
    logger.info(
        "Requisicao processada",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post("/auth/token", response_model=TokenResponse, tags=["Autenticacao"])
async def gerar_token(
    payload: TokenRequest,
    _: None = Depends(rate_limiter),
):
    if payload.grant_type != "client_credentials":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="grant_type deve ser 'client_credentials'.",
        )
    if payload.client_id != CLIENT_ID or payload.client_secret != CLIENT_SECRET:
        logger.warning("Tentativa de autenticacao invalida", extra={"client_id": payload.client_id})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="client_id ou client_secret invalidos.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = _create_token()
    logger.info("Token emitido", extra={"client_id": payload.client_id})
    return TokenResponse(access_token=token, token_type="Bearer", expires_in=TOKEN_TTL_SECONDS)


@app.get("/v1/unidades", response_model=List[Unidade], tags=["Unidades"])
async def listar_unidades(
    token: str = Depends(authenticate),
    _: None = Depends(rate_limiter),
    service: Optional[Any] = Depends(get_spinergie_service),
):
    if service is None:
        raise HTTPException(
            status_code=status.HTTP::503_SERVICE_UNAVAILABLE,
            detail="Servico de dados em tempo real indisponivel.",
        )
    try:
        dados = service.listar_unidades()
        logger.info("Unidades listadas", extra={"quantidade": len(dados) if dados else 0})
        return dados
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Erro ao listar unidades", exc_info=exc)
        raise HTTPException(
            status_code=status.HTTP::500_INTERNAL_SERVER_ERROR,
            detail="Erro interno ao obter unidades.",
        )


@app.get("/v1/posicao/{identificador}", response_model=Posicao, tags=["Posicao"])
async def obter_posicao(
    identificador: str,
    token: str = Depends(authenticate),
    _: None = Depends(rate_limiter),
    service: Optional[Any] = Depends(get_spinergie_service),
):
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servico de dados em tempo real indisponivel.",
        )
    try:
        dados = service.obter_posicao(identificador)
        if not dados:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Posicao nao encontrada para o identificador informado.",
            )
        logger.info("Posicao obtida", extra={"identificador": identificador})
        return dados
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Erro ao obter posicao", exc_info=exc, extra={"identificador": identificador})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno ao obter posicao.",
        )


@app.get("/health", response_model=HealthResponse, tags=["Saude"])
async def health_check(_: None = Depends(rate_limiter)):
    spinergie_status = "disponivel" if SpinergieService is not None else "indisponivel"
    return HealthResponse(
        status="ok",
        version=API_VERSION,
        timestamp=datetime.now(timezone.utc).isoformat(),
        spinergie=spinergie_status,
    )


@app.get("/", tags=["Raiz"])
async def raiz():
    return JSONResponse(
        {
            "nome": API_TITLE,
            "versao": API_VERSION,
            "docs": "/v1/docs",
            "endpoints": [
                "/auth/token",
                "/v1/unidades",
                "/v1/posicao/{identificador}",
                "/health",
            ],
        }
    )


# ---------------------------------------------------------------------------
# Custom OpenAPI com esquema Bearer
# ---------------------------------------------------------------------------
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=API_TITLE,
        version=API_VERSION,
        description=API_DESCRIPTION,
        routes=app.routes,
    )
    schema["components"]["securitySchemes"] = {
        "HTTPBearer": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Informe o access_token obtido em /auth/token.",
        }
    }
    schema["security"] = [{"HTTPBearer": []}]
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("IBAMA_HOST", "0.0.0.0"),
        port=int(os.getenv("IBAMA_PORT", "8000")),
        log_level=os.getenv("IBAMA_LOG_LEVEL", "info"),
    )