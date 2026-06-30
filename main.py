import asyncio
import logging
import math
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Configuração de logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("ibama_api")

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
class Settings:
    CLIENT_ID: str = os.getenv("CLIENT_ID", "ibama-client")
    CLIENT_SECRET: str = os.getenv("CLIENT_SECRET", "ibama-secret")
    JWT_SECRET: str = os.getenv("JWT_SECRET", secrets.token_urlsafe(32))
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    RATE_LIMIT: int = int(os.getenv("RATE_LIMIT", "100"))
    RATE_LIMIT_WINDOW_SECONDS: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))

settings = Settings()

# ---------------------------------------------------------------------------
# Modelos Pydantic
# ---------------------------------------------------------------------------
class UnidadeMaritima(BaseModel):
    id: str = Field(..., examples=["P-65"], description="Identificador único da unidade")
    nome: str = Field(..., examples=["P-65"], description="Nome da unidade marítima")
    tipo: str = Field(..., examples=["PLATAFORMA DE PETRÓLEO"], description="Tipo de unidade")
    latitude: float = Field(..., ge=-90.0, le=90.0, examples=[-22.7018])
    longitude: float = Field(..., ge=-180.0, le=180.0, examples=[-40.6772])
    licenca: str = Field(
        default="LO1572/2020",
        examples=["LO1572/2020"],
        description="Licença ambiental emitida pelo IBAMA"
    )
    ativa: bool = Field(default=True, examples=[True])


class PosicaoAIS(BaseModel):
    mmsi: int = Field(..., examples=[710002450], description="Número MMSI da embarcação")
    nome: str = Field(..., examples=["Maersk Ventura"], description="Nome da embarcação")
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    velocidade: float = Field(
        ...,
        ge=0.0,
        le=50.0,
        examples=[12.5],
        description="Velocidade sobre o solo em nós"
    )
    curso: float = Field(
        ...,
        ge=0.0,
        lt=360.0,
        examples=[45.0],
        description="Curso sobre o solo em graus"
    )
    timestamp: str = Field(
        ...,
        examples=["2024-01-15T10:30:00Z"],
        description="Timestamp ISO 8601 UTC"
    )
    status: str = Field(
        ...,
        examples=["UNDER WAY USING ENGINE"],
        description="Status de navegação"
    )


class TokenResponse(BaseModel):
    access_token: str = Field(..., description="Token JWT de acesso")
    token_type: str = Field(default="Bearer", examples=["Bearer"])
    expires_in: int = Field(
        default=3600,
        examples=[3600],
        description="Tempo de expiração do token em segundos"
    )


class ErroResponse(BaseModel):
    error: str = Field(..., examples=["HTTPException"])
    message: str = Field(..., examples=["Recurso não encontrado"])
    request_id: Optional[str] = Field(default=None, examples=["uuid-1234"])
    timestamp: str = Field(..., examples=["2024-01-15T10:30:00Z"])


# ---------------------------------------------------------------------------
# Dados em memória
# ---------------------------------------------------------------------------
PLATAFORMAS: List[UnidadeMaritima] = [
    UnidadeMaritima(
        id="P-65",
        nome="P-65",
        tipo="PLATAFORMA DE PETRÓLEO",
        latitude=-22.7018,
        longitude=-40.6772,
    ),
    UnidadeMaritima(
        id="P-08",
        nome="P-08",
        tipo="PLATAFORMA DE PETRÓLEO",
        latitude=-22.6732,
        longitude=-40.5465,
    ),
    UnidadeMaritima(
        id="PPM-1",
        nome="PPM-1",
        tipo="PLATAFORMA DE PETRÓLEO",
        latitude=-22.798,
        longitude=-40.7625,
    ),
    UnidadeMaritima(
        id="PCE-1",
        nome="PCE-1",
        tipo="PLATAFORMA DE PETRÓLEO",
        latitude=-22.7083,
        longitude=-40.6932,
    ),
]

EMBARCACOES: List[Dict[str, Any]] = [
    {
        "mmsi": 710002450,
        "nome": "Maersk Ventura",
        "plataforma": "P-65",
        "raio": 0.008,
        "velocidade_angular": 0.0005,
        "fase": 0.0,
    },
    {
        "mmsi": 710001720,
        "nome": "Maersk Vega",
        "plataforma": "P-08",
        "raio": 0.007,
        "velocidade_angular": 0.0007,
        "fase": math.pi,
    },
]


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------
def iso_timestamp() -> str:
    """Retorna timestamp ISO 8601 com sufixo Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_access_token(
    data: Dict[str, Any], expires_delta: Optional[timedelta] = None
) -> str:
    """Gera um JWT de acesso OAuth 2.0 Client Credentials."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    expire = now + expires_delta
    to_encode.update({"exp": expire, "iat": now, "type": "access_token"})
    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def calcular_posicao(embarcacao: Dict[str, Any], timestamp: datetime) -> PosicaoAIS:
    """Simula movimento circular da embarcação ao redor da plataforma."""
    plataforma = next(
        (p for p in PLATAFORMAS if p.id == embarcacao["plataforma"]), None
    )
    if plataforma is None:
        raise ValueError(f"Plataforma {embarcacao['plataforma']} não encontrada")

    lat_center = plataforma.latitude
    lon_center = plataforma.longitude

    t = timestamp.timestamp()
    theta = embarcacao["fase"] + embarcacao["velocidade_angular"] * t
    raio = embarcacao["raio"]

    dlat = raio * math.cos(theta)
    dlon = raio * math.sin(theta) / math.cos(math.radians(lat_center))

    lat = lat_center + dlat
    lon = lon_center + dlon

    curso = (math.degrees(theta) + 90.0) % 360.0
    velocidade = 10.0 + 2.0 * math.sin(theta * 2.0)

    return PosicaoAIS(
        mmsi=embarcacao["mmsi"],
        nome=embarcacao["nome"],
        latitude=round(lat, 6),
        longitude=round(lon, 6),
        velocidade=round(abs(velocidade), 2),
        curso=round(curso, 2),
        timestamp=timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        status="UNDER WAY USING ENGINE",
    )


# ---------------------------------------------------------------------------
# Rate Limiting (in-memory)
# ---------------------------------------------------------------------------
class RateLimiter:
    def __init__(self, limit: int, window: int):
        self.limit = limit
        self.window = window
        self._requests: Dict[str, List[float]] = {}
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> Tuple[bool, int]:
        async with self._lock:
            now = time.time()
            timestamps = [
                ts
                for ts in self._requests.get(key, [])
                if now - ts < self.window
            ]
            if len(timestamps) >= self.limit:
                self._requests[key] = timestamps
                return False, 0

            timestamps.append(now)
            self._requests[key] = timestamps
            return True, self.limit - len(timestamps)


rate_limiter = RateLimiter(
    limit=settings.RATE_LIMIT, window=settings.RATE_LIMIT_WINDOW_SECONDS
)


# ---------------------------------------------------------------------------
# Dependências de segurança
# ---------------------------------------------------------------------------

security = HTTPBearer(auto_error=False)

async def get_current_client(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    """Valida o token Bearer e retorna o identificador do cliente."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de acesso não fornecido",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        client_id = payload.get("sub")
        if not client_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token inválido: sem identificação do cliente",
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return client_id


async def rate_limit_guard(
    request: Request, client_id: str = Depends(get_current_client)
) -> str:
    """Aplica rate limiting de 100 requisições/minuto por cliente."""
    allowed, remaining = await rate_limiter.check(client_id)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Limite de requisições excedido. "
                f"Limite: {settings.RATE_LIMIT} requisições por "
                f"{settings.RATE_LIMIT_WINDOW_SECONDS} segundos."
            ),
        )
    request.state.rate_limit_remaining = remaining
    return client_id


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Inicializando API IBAMA...")
    yield
    logger.info("Finalizando API IBAMA...")


# ---------------------------------------------------------------------------
# Inicialização do FastAPI
# ---------------------------------------------------------------------------
app = FastAPI(
    title="API IBAMA - Monitoramento de Unidades Marítimas",
    description=(
        "API REST para consulta de unidades marítimas licenciadas pelo IBAMA "
        "e acompanhamento de posições AIS de embarcações em tempo real."
    ),
    version="1.0.0",
    docs_url="/v1/docs",
    redoc_url="/v1/redoc",
    openapi_url="/v1/openapi.json",
    contact={
        "name": "IBAMA - Instituto Brasileiro do Meio Ambiente",
        "url": "https://www.ibama.gov.br",
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Middlewares
# ---------------------------------------------------------------------------
@app.middleware("http")
async def add_response_headers(request: Request, call_next):
    response = await call_next(request)

    request_id = getattr(request.state, "request_id", None)
    if request_id:
        response.headers["X-Request-ID"] = request_id

    remaining = getattr(request.state, "rate_limit_remaining", None)
    if remaining is not None:
        response.headers["X-RateLimit-Limit"] = str(settings.RATE_LIMIT)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Window"] = str(
            settings.RATE_LIMIT_WINDOW_SECONDS
        )

    return response


# ---------------------------------------------------------------------------
# Tratamento de erros padronizado
# ---------------------------------------------------------------------------
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    content = ErroResponse(
        error="HTTPException",
        message=exc.detail,
        request_id=getattr(request.state, "request_id", None),
        timestamp=iso_timestamp(),
    ).model_dump()
    headers = dict(exc.headers) if exc.headers else {}
    return JSONResponse(status_code=exc.status_code, content=content, headers=headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
):
    content = ErroResponse(
        error="ValidationError",
        message="Erro de validação nos dados de entrada. Verifique os parâmetros e o corpo da requisição.",
        request_id=getattr(request.state, "request_id", None),
        timestamp=iso_timestamp(),
    ).model_dump()
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=content
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.exception("Erro interno não tratado")
    content = ErroResponse(
        error="InternalServerError",
        message="Erro interno do servidor. Entre em contato com o suporte.",
        request_id=getattr(request.state, "request_id", None),
        timestamp=iso_timestamp(),
    ).model_dump()
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=content
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post(
    "/auth/token",
    response_model=TokenResponse,
    tags=["Autenticação"],
    summary="Obter token de acesso OAuth 2.0 Client Credentials",
    response_description="Token JWT para autenticação nos endpoints protegidos",
)
async def auth_token(
    grant_type: str = Form(..., description="Deve ser 'client_credentials'"),
    client_id: str = Form(..., description="Client ID fornecido"),
    client_secret: str = Form(..., description="Client Secret fornecido"),
):
    if grant_type != "client_credentials":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="grant_type deve ser 'client_credentials'",
        )
    if client_id != settings.CLIENT_ID or client_secret != settings.CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais do cliente inválidas",
        )
    access_token = create_access_token(data={"sub": client_id})
    return TokenResponse(
        access_token=access_token,
        token_type="Bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@app.get(
    "/v1/unidades",
    response_model=List[UnidadeMaritima],
    tags=["IBAMA"],
    dependencies=[Depends(rate_limit_guard)],
    summary="Listar unidades marítimas licenciadas",
    response_description="Lista de plataformas e unidades marítimas com licença LO1572/2020",
)
async def listar_unidades():
    return PLATAFORMAS


@app.get(
    "/v1/posicao/{mmsi}",
    response_model=PosicaoAIS,
    tags=["IBAMA"],
    dependencies=[Depends(rate_limit_guard)],
    summary="Consultar posição AIS de embarcação",
    response_description="Posição atual simulada da embarcação identificada pelo MMSI",
)
async def obter_posicao(mmsi: int):
    for embarcacao in EMBARCACOES:
        if embarcacao["mmsi"] == mmsi:
            return calcular_posicao(embarcacao, datetime.now(timezone.utc))
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Embarcação com MMSI {mmsi} não encontrada",
    )


@app.get(
    "/health",
    tags=["Monitoramento"],
    summary="Health check da API",
    response_description="Status operacional e timestamp atual",
)
async def health_check():
    return {
        "status": "ok",
        "timestamp": iso_timestamp(),
        "version": "1.0.0",
        "service": "api-ibama",
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")