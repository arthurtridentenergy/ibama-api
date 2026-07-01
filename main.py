import asyncio
import json
import logging
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel, Field

from data import get_all_vessels, get_vessel_position
from models import UnidadeMaritima, PosicaoAIS


# ---------------------------------------------------------------------------
# Configuração de logging estruturado (JSON)
# ---------------------------------------------------------------------------
class StructuredFormatter(logging.Formatter):
    """Formatter que produz logs em JSON estruturado."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            log_entry["request_id"] = request_id
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


_handler = logging.StreamHandler()
_handler.setFormatter(StructuredFormatter())

logging.basicConfig(level=logging.INFO, handlers=[_handler])
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
    CORS_ORIGINS: List[str] = os.getenv("CORS_ORIGINS", "*").split(",")


settings = Settings()


# ---------------------------------------------------------------------------
# Modelos de resposta
# ---------------------------------------------------------------------------
class UnidadeResponse(BaseModel):
    nome: str = Field(..., description="Nome da unidade marítima", examples=["P-65"])
    mmsi: str = Field(..., description="MMSI ou identificador da unidade", examples=["538003593"])
    imo: Optional[str] = Field(default=None, description="Número IMO", examples=["1234567"])
    tipoUnidade: str = Field(..., description="Tipo da unidade", examples=["PLATAFORMA_FIXA"])
    licencasAutorizadas: List[str] = Field(
        default_factory=list, description="Licenças/autorizações vigentes"
    )
    disponibilidadeInicio: Optional[str] = Field(
        default=None, description="Início de disponibilidade (ISO 8601 UTC)"
    )
    disponibilidadeFim: Optional[str] = Field(
        default=None, description="Fim de disponibilidade (ISO 8601 UTC)"
    )
    latitude: Optional[float] = Field(
        default=None, ge=-90, le=90, description="Latitude em graus decimais"
    )
    longitude: Optional[float] = Field(
        default=None, ge=-180, le=180, description="Longitude em graus decimais"
    )
    licenca_ibama: Optional[str] = Field(default=None, description="Número da licença IBAMA")
    validade_licenca: Optional[str] = Field(default=None, description="Validade da licença")
    status_licenca: Optional[str] = Field(default=None, description="Status da licença")
    observacao_licenca: Optional[str] = Field(default=None, description="Observações da licença")


class PosicaoResponse(BaseModel):
    identificador: str = Field(
        ..., description="Identificador consultado (MMSI ou nome)", examples=["538003593"]
    )
    mmsi: str = Field(..., description="MMSI da unidade", examples=["538003593"])
    nome: Optional[str] = Field(default=None, description="Nome da unidade", examples=["P-65"])
    latitude: float = Field(..., ge=-90, le=90, description="Latitude em graus decimais")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude em graus decimais")
    timestampAquisicao: str = Field(
        ..., description="Timestamp ISO 8601 UTC", examples=["2024-01-15T10:30:00Z"]
    )
    tipoUnidade: Optional[str] = Field(default=None, description="Tipo da unidade")
    fonte: str = Field(
        default="data_local", description="Fonte dos dados de posição"
    )


class TokenResponse(BaseModel):
    access_token: str = Field(..., description="Token JWT de acesso")
    token_type: str = Field(default="Bearer", examples=["Bearer"])
    expires_in: int = Field(
        default=3600, examples=[3600], description="Expiração do token em segundos"
    )


class ErroResponse(BaseModel):
    error: str = Field(..., examples=["HTTPException"])
    message: str = Field(..., examples=["Recurso não encontrado"])
    request_id: Optional[str] = Field(default=None, examples=["uuid-1234"])
    timestamp: str = Field(..., examples=["2024-01-15T10:30:00Z"])


class HealthResponse(BaseModel):
    status: str = Field(..., examples=["ok"])
    timestamp: str = Field(..., examples=["2024-01-15T10:30:00Z"])
    version: str = Field(..., examples=["1.0.0"])
    service: str = Field(..., examples=["api-ibama"])


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------
def iso_timestamp() -> str:
    """Retorna timestamp ISO 8601 UTC com sufixo Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_datetime(value: Any) -> Optional[str]:
    """Normaliza datetime ou string para ISO 8601 UTC com sufixo Z."""
    if value is None:
        return None
    if isinstance(value, str):
        if value.endswith("+00:00Z"):
            return value.replace("+00:00Z", "Z")
        if value.endswith("+00:00"):
            return value.replace("+00:00", "Z")
        if not value.endswith("Z"):
            return value + "Z"
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


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
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def _tipo_unidade_str(u: UnidadeMaritima) -> str:
    """Extrai o valor string do tipoUnidade (Enum ou string)."""
    if hasattr(u.tipoUnidade, "value"):
        return u.tipoUnidade.value
    return str(u.tipoUnidade)


def to_unidade_response(u: UnidadeMaritima) -> UnidadeResponse:
    """Converte UnidadeMaritima do models.py para UnidadeResponse."""
    return UnidadeResponse(
        nome=u.nome,
        mmsi=u.mmsi,
        imo=u.imo,
        tipoUnidade=_tipo_unidade_str(u),
        licencasAutorizadas=u.licencasAutorizadas,
        disponibilidadeInicio=normalize_datetime(u.disponibilidadeInicio),
        disponibilidadeFim=normalize_datetime(u.disponibilidadeFim),
        latitude=u.latitude,
        longitude=u.longitude,
        licenca_ibama=u.licenca_ibama,
        validade_licenca=u.validade_licenca,
        status_licenca=u.status_licenca,
        observacao_licenca=u.observacao_licenca,
    )


def buscar_vessel_por_nome(nome: str) -> Optional[UnidadeMaritima]:
    """Busca uma unidade pelo nome (case-insensitive)."""
    nome_upper = nome.strip().upper()
    for vessel in get_all_vessels():
        if vessel.nome.strip().upper() == nome_upper:
            return vessel
    return None


def buscar_vessel_por_mmsi(mmsi: str) -> Optional[UnidadeMaritima]:
    """Busca uma unidade pelo MMSI ou identificador alfanumérico."""
    mmsi_clean = mmsi.strip()
    for vessel in get_all_vessels():
        if vessel.mmsi == mmsi_clean:
            return vessel
    return None


# ---------------------------------------------------------------------------
# Rate Limiting (in-memory, 100 req/min por cliente)
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
                ts for ts in self._requests.get(key, []) if now - ts < self.window
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
# Dependências de segurança (HTTPBearer)
# ---------------------------------------------------------------------------
security = HTTPBearer(auto_error=False)


async def get_current_client(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    """Valida o token Bearer JWT e retorna o identificador do cliente."""
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
    """Aplica rate limiting de 100 requisições/minuto por cliente autenticado."""
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
    logger.info("Inicializando API IBAMA")
    yield
    logger.info("Finalizando API IBAMA")


# ---------------------------------------------------------------------------
# Inicialização do FastAPI
# ---------------------------------------------------------------------------
app = FastAPI(
    title="API IBAMA - Monitoramento de Unidades Marítimas",
    description=(
        "API REST para consulta de unidades marítimas licenciadas pelo IBAMA "
        "e acompanhamento de posições de embarcações e plataformas.\n\n"
        "**Autenticação:** OAuth 2.0 Client Credentials via `POST /auth/token`. "
        "Inclua o token no header `Authorization: Bearer <token>`."
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
# CORS
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Middleware: request ID, headers de rate limit e logging
# ---------------------------------------------------------------------------
@app.middleware("http")
async def request_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    logger.info(
        f"Requisição iniciada: {request.method} {request.url.path}",
        extra={"request_id": request_id},
    )

    response = await call_next(request)

    response.headers["X-Request-ID"] = request_id

    remaining = getattr(request.state, "rate_limit_remaining", None)
    if remaining is not None:
        response.headers["X-RateLimit-Limit"] = str(settings.RATE_LIMIT)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Window"] = str(settings.RATE_LIMIT_WINDOW_SECONDS)

    logger.info(
        f"Requisição finalizada: {request.method} {request.url.path} - {response.status_code}",
        extra={"request_id": request_id},
    )

    return response


# ---------------------------------------------------------------------------
# Tratamento de erros padronizado
# ---------------------------------------------------------------------------
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    content = ErroResponse(
        error="HTTPException",
        message=str(exc.detail),
        request_id=getattr(request.state, "request_id", None),
        timestamp=iso_timestamp(),
    ).model_dump()
    headers = dict(exc.headers) if exc.headers else {}
    return JSONResponse(
        status_code=exc.status_code, content=content, headers=headers
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
):
    content = ErroResponse(
        error="ValidationError",
        message="Erro de validação nos dados de entrada. Verifique os parâmetros da requisição.",
        request_id=getattr(request.state, "request_id", None),
        timestamp=iso_timestamp(),
    ).model_dump()
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=content
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.exception(
        "Erro interno não tratado",
        extra={"request_id": getattr(request.state, "request_id", None)},
    )
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
    client_id: str = Form(..., description="Client ID fornecido pelo IBAMA"),
    client_secret: str = Form(..., description="Client Secret fornecido pelo IBAMA"),
):
    """
    Endpoint de autenticação OAuth 2.0 Client Credentials.

    - **grant_type**: deve ser `client_credentials`
    - **client_id**: identificador do cliente
    - **client_secret**: segredo do cliente

    Retorna um JWT Bearer para uso nos endpoints protegidos.
    """
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
    logger.info(f"Token emitido para cliente: {client_id}")
    return TokenResponse(
        access_token=access_token,
        token_type="Bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@app.get(
    "/v1/unidades",
    response_model=List[UnidadeResponse],
    tags=["Unidades"],
    dependencies=[Depends(rate_limit_guard)],
    summary="Listar todas as unidades marítimas licenciadas",
    response_description="Lista de unidades marítimas com licenças IBAMA",
)
async def listar_unidades():
    """
    Retorna todas as unidades marítimas cadastradas, incluindo plataformas fixas
    e embarcações de apoio/emergência, com suas respectivas licenças e coordenadas.
    """
    vessels = get_all_vessels()
    logger.info(f"Listagem de unidades retornou {len(vessels)} registros")
    return [to_unidade_response(v) for v in vessels]


@app.get(
    "/v1/posicao/{identificador}",
    response_model=PosicaoResponse,
    tags=["Posição"],
    dependencies=[Depends(rate_limit_guard)],
    summary="Consultar posição de unidade por MMSI ou nome",
    response_description="Posição atual da unidade identificada",
)
async def obter_posicao(identificador: str):
    """
    Consulta a posição de uma unidade marítima aceitando:

    - **MMSI numérico** (ex: `538003593`)
    - **MMSI alfanumérico** (ex: `PPM-1`)
    - **Nome da unidade** (ex: `P-65`)

    A busca é feita em ordem:
    1. Posição direta pelo identificador informado (MMSI numérico ou alfanumérico)
    2. Busca por nome da unidade e posterior busca de posição pelo MMSI encontrado
    3. Coordenadas fixas cadastradas (para plataformas sem posição AIS dinâmica)
    """
    ident = identificador.strip()

    # 1. Tentar buscar posição diretamente pelo identificador (MMSI numérico ou alfanumérico)
    pos = get_vessel_position(ident)
    vessel = buscar_vessel_por_mmsi(ident)

    # 2. Se não encontrou posição, tentar buscar por nome da unidade
    if pos is None:
        vessel_by_name = buscar_vessel_por_nome(ident)
        if vessel_by_name:
            vessel = vessel_by_name
            pos = get_vessel_position(vessel.mmsi)

    # 3. Se encontrou a unidade mas não a posição dinâmica, usar coordenadas fixas
    if pos is None and vessel and vessel.latitude is not None and vessel.longitude is not None:
        logger.info(
            f"Posição construída a partir de coordenadas fixas para: {ident}"
        )
        return PosicaoResponse(
            identificador=ident,
            mmsi=vessel.mmsi,
            nome=vessel.nome,
            latitude=vessel.latitude,
            longitude=vessel.longitude,
            timestampAquisicao=iso_timestamp(),
            tipoUnidade=_tipo_unidade_str(vessel),
            fonte="coordenada_fixa",
        )

    # 4. Se encontrou posição (direta ou via nome)
    if pos is not None:
        tipo = None
        nome = None
        if vessel:
            tipo = _tipo_unidade_str(vessel)
            nome = vessel.nome
        else:
            v = buscar_vessel_por_mmsi(pos.mmsi)
            if v:
                tipo = _tipo_unidade_str(v)
                nome = v.nome

        ts = normalize_datetime(pos.timestampAquisicao) or iso_timestamp()
        logger.info(f"Posição encontrada para identificador: {ident} (MMSI: {pos.mmsi})")
        return PosicaoResponse(
            identificador=ident,
            mmsi=pos.mmsi,
            nome=nome,
            latitude=pos.latitude,
            longitude=pos.longitude,
            timestampAquisicao=ts,
            tipoUnidade=tipo,
            fonte="data_local",
        )

    # 5. Nenhuma unidade ou posição encontrada
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Unidade não encontrada para o identificador: {ident}",
    )


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Monitoramento"],
    summary="Health check da API",
    response_description="Status operacional e timestamp atual",
)
async def health_check():
    """Verifica a saúde operacional da API."""
    return HealthResponse(
        status="ok",
        timestamp=iso_timestamp(),
        version="1.0.0",
        service="api-ibama",
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")