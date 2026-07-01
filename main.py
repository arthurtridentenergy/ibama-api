import asyncio
import logging
import math
import os
import secrets
import time
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


# ---------------------------------------------------------------------------
# Configuração de logging estruturado
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("ibama_api")


# ---------------------------------------------------------------------------
# Configurações
# ---------------------------------------------------------------------------
JWT_SECRET: str = os.getenv("JWT_SECRET", secrets.token_urlsafe(32))
JWT_ALGORITHM: str = "HS256"
CLIENT_ID: str = os.getenv("CLIENT_ID", "ibama-client")
CLIENT_SECRET: str = os.getenv("CLIENT_SECRET", "ibama-secret")
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
RATE_LIMIT: int = int(os.getenv("RATE_LIMIT", "100"))
RATE_LIMIT_WINDOW_SECONDS: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class TipoUnidade(str, Enum if False else object):
    pass


from enum import Enum


class TipoUnidade(str, Enum):
    EMBARCACAO_EMERGENCIA = "EMBARCACAO_EMERGENCIA"
    EMBARCACAO_APOIO = "EMBARCACAO_APOIO"
    EMBARCACAO_MONITORAMENTO = "EMBARCACAO_MONITORAMENTO"
    UNIDADE_PRODUCAO = "UNIDADE_PRODUCAO"
    PLATAFORMA_FIXA = "PLATAFORMA_FIXA"
    PLATAFORMA_MOVEL = "PLATAFORMA_MOVEL"


class StatusUnidade(str, Enum):
    ATIVA = "ATIVA"
    INATIVA = "INATIVA"
    EM_MANUTENCAO = "EM_MANUTENCAO"
    EM_DESATIVACAO = "EM_DESATIVACAO"


# ---------------------------------------------------------------------------
# Modelos Pydantic
# ---------------------------------------------------------------------------
class UnidadeMaritima(BaseModel):
    mmsi: str = Field(
        ...,
        description="Identificador MMSI da unidade (numérico para embarcações, alfanumérico para plataformas fixas)",
        examples=["710002450", "P-65", "PPM-1"],
    )
    nome: str = Field(
        ...,
        min_length=1,
        description="Nome da unidade marítima",
        examples=["MAERSK VENTURA", "P-65"],
    )
    imo: Optional[str] = Field(
        default=None,
        description="Número IMO de 7 dígitos, quando aplicável",
        examples=["1234567"],
    )
    tipoUnidade: TipoUnidade = Field(
        ...,
        description="Tipo da unidade marítima",
        examples=["PLATAFORMA_FIXA"],
    )
    status: StatusUnidade = Field(
        default=StatusUnidade.ATIVA,
        description="Status operacional da unidade",
        examples=["ATIVA"],
    )
    licencasAutorizadas: List[str] = Field(
        default_factory=list,
        description="Licenças e autorizações vigentes",
        examples=[["LO1572/2020"]],
    )
    disponibilidadeInicio: Optional[str] = Field(
        default=None,
        description="Início do período de disponibilidade (ISO 8601 UTC)",
        examples=["2024-01-01T00:00:00Z"],
    )
    disponibilidadeFim: Optional[str] = Field(
        default=None,
        description="Fim do período de disponibilidade (ISO 8601 UTC)",
        examples=["2028-03-15T00:00:00Z"],
    )
    latitude: Optional[float] = Field(
        default=None,
        ge=-90,
        le=90,
        description="Latitude em graus decimais (para plataformas fixas)",
        examples=[-22.701833],
    )
    longitude: Optional[float] = Field(
        default=None,
        ge=-180,
        le=180,
        description="Longitude em graus decimais (para plataformas fixas)",
        examples=[-40.677167],
    )
    licenca_ibama: Optional[str] = Field(
        default=None,
        description="Número da licença IBAMA",
        examples=["LO1572/2020"],
    )
    validade_licenca: Optional[str] = Field(
        default=None,
        description="Data de validade da licença (YYYY-MM-DD)",
        examples=["2024-07-11"],
    )
    status_licenca: Optional[str] = Field(
        default=None,
        description="Status da licença junto ao IBAMA",
        examples=["Renovação solicitada"],
    )
    observacao_licenca: Optional[str] = Field(
        default=None,
        description="Observações sobre o licenciamento",
        examples=["Aguardando manifestação do IBAMA"],
    )


class PosicaoAIS(BaseModel):
    mmsi: str = Field(
        ...,
        description="Identificador MMSI da unidade",
        examples=["710002450"],
    )
    nome: str = Field(
        ...,
        description="Nome da unidade marítima",
        examples=["MAERSK VENTURA"],
    )
    latitude: float = Field(
        ...,
        ge=-90,
        le=90,
        description="Latitude em graus decimais",
        examples=[-22.7018],
    )
    longitude: float = Field(
        ...,
        ge=-180,
        le=180,
        description="Longitude em graus decimais",
        examples=[-40.6772],
    )
    velocidade: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Velocidade sobre o solo em nós",
        examples=[12.5],
    )
    curso: Optional[float] = Field(
        default=None,
        ge=0.0,
        lt=360.0,
        description="Curso sobre o solo em graus",
        examples=[45.0],
    )
    timestampAquisicao: str = Field(
        ...,
        description="Data e hora da aquisição da posição (ISO 8601 UTC com sufixo Z)",
        examples=["2025-01-15T10:30:00Z"],
    )
    status: Optional[str] = Field(
        default=None,
        description="Status de navegação AIS",
        examples=["UNDER WAY USING ENGINE"],
    )


class TokenResponse(BaseModel):
    access_token: str = Field(
        ...,
        description="Token JWT de acesso",
        examples=["eyJhbGciOiJIUzI1NiIs..."],
    )
    token_type: str = Field(
        default="Bearer",
        description="Tipo do token",
        examples=["Bearer"],
    )
    expires_in: int = Field(
        ...,
        description="Tempo de expiração do token em segundos",
        examples=[3600],
    )


class ErrorResponse(BaseModel):
    error: str = Field(
        ...,
        description="Tipo do erro",
        examples=["HTTPException"],
    )
    message: str = Field(
        ...,
        description="Mensagem descritiva do erro",
        examples=["Recurso não encontrado"],
    )
    timestamp: str = Field(
        ...,
        description="Timestamp ISO 8601 UTC do erro",
        examples=["2025-01-15T10:30:00Z"],
    )


# ---------------------------------------------------------------------------
# Dados em memória — Registro de unidades marítimas
# ---------------------------------------------------------------------------
# Plataformas fixas: posições hardcoded (Bacia de Santos)
# Embarcações: movimento simulado em tempo real (circular ao redor de plataforma)

UNIDADES_REGISTRY: List[Dict[str, Any]] = [
    {
        "mmsi": "538003593",
        "nome": "P-65",
        "imo": None,
        "tipoUnidade": TipoUnidade.PLATAFORMA_FIXA,
        "status": StatusUnidade.ATIVA,
        "licencasAutorizadas": ["LO1572/2020"],
        "disponibilidadeInicio": "2020-09-01T00:00:00Z",
        "disponibilidadeFim": "2029-09-01T00:00:00Z",
        "latitude": -22.701833,
        "longitude": -40.677167,
        "licenca_ibama": "LO1572/2020",
        "validade_licenca": "2024-07-11",
        "status_licenca": "Renovação solicitada",
        "observacao_licenca": "Aguardando manifestação do IBAMA",
    },
    {
        "mmsi": "538001903",
        "nome": "P-08",
        "imo": None,
        "tipoUnidade": TipoUnidade.PLATAFORMA_FIXA,
        "status": StatusUnidade.ATIVA,
        "licencasAutorizadas": ["LO1572/2020"],
        "disponibilidadeInicio": "2021-03-15T00:00:00Z",
        "disponibilidadeFim": "2028-03-15T00:00:00Z",
        "latitude": -22.673167,
        "longitude": -40.546500,
        "licenca_ibama": "LO1572/2020",
        "validade_licenca": "2024-07-11",
        "status_licenca": "Renovação solicitada",
        "observacao_licenca": "Aguardando manifestação do IBAMA",
    },
    {
        "mmsi": "PPM-1",
        "nome": "PPM-1",
        "imo": None,
        "tipoUnidade": TipoUnidade.PLATAFORMA_FIXA,
        "status": StatusUnidade.ATIVA,
        "licencasAutorizadas": ["LO1572/2020"],
        "disponibilidadeInicio": "2023-01-01T00:00:00Z",
        "disponibilidadeFim": "2027-12-31T00:00:00Z",
        "latitude": -22.798,
        "longitude": -40.7625,
        "licenca_ibama": "LO1572/2020",
        "validade_licenca": "2024-07-11",
        "status_licenca": "Renovação solicitada",
        "observacao_licenca": "Aguardando manifestação do IBAMA",
    },
    {
        "mmsi": "PCE-1",
        "nome": "PCE-1",
        "imo": None,
        "tipoUnidade": TipoUnidade.PLATAFORMA_FIXA,
        "status": StatusUnidade.ATIVA,
        "licencasAutorizadas": ["LO1572/2020"],
        "disponibilidadeInicio": "2022-06-01T00:00:00Z",
        "disponibilidadeFim": "2027-06-01T00:00:00Z",
        "latitude": -22.708333,
        "longitude": -40.693167,
        "licenca_ibama": "LO1572/2020",
        "validade_licenca": "2024-07-11",
        "status_licenca": "Renovação solicitada",
        "observacao_licenca": "Aguardando manifestação do IBAMA",
    },
    {
        "mmsi": "710002450",
        "nome": "MAERSK VENTURA",
        "imo": None,
        "tipoUnidade": TipoUnidade.EMBARCACAO_APOIO,
        "status": StatusUnidade.ATIVA,
        "licencasAutorizadas": ["LO1572/2020"],
        "disponibilidadeInicio": "2024-01-01T00:00:00Z",
        "disponibilidadeFim": None,
        "latitude": None,
        "longitude": None,
        "licenca_ibama": "LO1572/2020",
        "validade_licenca": None,
        "status_licenca": "Anuência",
        "observacao_licenca": "Licenciamento Ambiental nº 23341605/2025-Coprod/CGMac/Dilic (SEI 23341605)",
        # Parâmetros de simulação de movimento
        "sim_orbita_plataforma": "P-65",
        "sim_raio": 0.008,
        "sim_velocidade_angular": 0.0005,
        "sim_fase": 0.0,
    },
    {
        "mmsi": "710001720",
        "nome": "MAERSK VEGA",
        "imo": None,
        "tipoUnidade": TipoUnidade.EMBARCACAO_APOIO,
        "status": StatusUnidade.ATIVA,
        "licencasAutorizadas": ["LO1572/2020"],
        "disponibilidadeInicio": "2024-01-01T00:00:00Z",
        "disponibilidadeFim": None,
        "latitude": None,
        "longitude": None,
        "licenca_ibama": "LO1572/2020",
        "validade_licenca": None,
        "status_licenca": "Ofício",
        "observacao_licenca": "Ofício nº 163/2024/COPROD/CGMAC/DILIC (SEI 18951971)",
        "sim_orbita_plataforma": "P-08",
        "sim_raio": 0.007,
        "sim_velocidade_angular": 0.0007,
        "sim_fase": math.pi,
    },
    {
        "mmsi": "123456789",
        "nome": "Navio Emergência Alpha",
        "imo": "1234567",
        "tipoUnidade": TipoUnidade.EMBARCACAO_EMERGENCIA,
        "status": StatusUnidade.ATIVA,
        "licencasAutorizadas": ["LO1234/2025", "LPS123/2025"],
        "disponibilidadeInicio": "2024-01-01T00:00:00Z",
        "disponibilidadeFim": "2026-12-31T00:00:00Z",
        "latitude": None,
        "longitude": None,
        "licenca_ibama": "LO1234/2025",
        "validade_licenca": None,
        "status_licenca": "Vigente",
        "observacao_licenca": None,
        "sim_orbita_plataforma": "PPM-1",
        "sim_raio": 0.010,
        "sim_velocidade_angular": 0.0003,
        "sim_fase": math.pi / 2,
    },
    {
        "mmsi": "987654321",
        "nome": "Navio Apoio Beta",
        "imo": "7654321",
        "tipoUnidade": TipoUnidade.EMBARCACAO_APOIO,
        "status": StatusUnidade.ATIVA,
        "licencasAutorizadas": ["LO5678/2025"],
        "disponibilidadeInicio": "2024-02-01T00:00:00Z",
        "disponibilidadeFim": None,
        "latitude": None,
        "longitude": None,
        "licenca_ibama": "LO5678/2025",
        "validade_licenca": None,
        "status_licenca": "Vigente",
        "observacao_licenca": None,
        "sim_orbita_plataforma": "PCE-1",
        "sim_raio": 0.009,
        "sim_velocidade_angular": 0.0004,
        "sim_fase": math.pi / 4,
    },
]


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------
def iso_timestamp() -> str:
    """Retorna timestamp ISO 8601 com sufixo Z (UTC)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_access_token(
    data: Dict[str, Any], expires_delta: Optional[timedelta] = None
) -> str:
    """
    Gera um token JWT de acesso (OAuth 2.0 Client Credentials).

    Args:
        data: Dados a serem codificados no payload (deve conter 'sub').
        expires_delta: Tempo de expiração personalizado. Se None, usa o padrão.

    Returns:
        Token JWT codificado.
    """
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta is None:
        expires_delta = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    expire = now + expires_delta
    to_encode.update({"exp": expire, "iat": now, "type": "access_token"})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    logger.info(f"Token de acesso gerado para cliente: {data.get('sub')}")
    return encoded_jwt


def _resolver_unidade(identificador: str) -> Optional[Dict[str, Any]]:
    """
    Resolve um identificador (MMSI numérico, string ou nome) para uma unidade
    cadastrada no registro.

    Aceita: MMSI numérico (710002450), MMSI alfanumérico (PPM-1),
    ou nome da unidade (P-65, MAERSK VENTURA).
    """
    if not identificador:
        return None

    ident_normalizado = identificador.strip()
    ident_upper = ident_normalizado.upper()

    for unidade in UNIDADES_REGISTRY:
        mmsi = str(unidade.get("mmsi", "")).strip()
        nome = str(unidade.get("nome", "")).strip()

        if mmsi == ident_normalizado:
            return unidade
        if mmsi.upper() == ident_upper:
            return unidade
        if nome.upper() == ident_upper:
            return unidade

    return None


def _calcular_posicao_simulada(
    unidade: Dict[str, Any], timestamp: datetime
) -> Tuple[float, float, float, float]:
    """
    Simula movimento circular de uma embarcação ao redor de uma plataforma.

    Returns:
        Tupla (latitude, longitude, curso, velocidade).
    """
    plataforma_nome = unidade.get("sim_orbita_plataforma")
    plataforma = _resolver_unidade(plataforma_nome) if plataforma_nome else None

    if plataforma is None or plataforma.get("latitude") is None:
        # Fallback: posição estática aproximada da Bacia de Santos
        lat_center = -22.9068
        lon_center = -43.1729
    else:
        lat_center = plataforma["latitude"]
        lon_center = plataforma["longitude"]

    t = timestamp.timestamp()
    theta = unidade.get("sim_fase", 0.0) + unidade.get("sim_velocidade_angular", 0.0005) * t
    raio = unidade.get("sim_raio", 0.008)

    dlat = raio * math.cos(theta)
    dlon = raio * math.sin(theta) / math.cos(math.radians(lat_center))

    lat = lat_center + dlat
    lon = lon_center + dlon

    curso = (math.degrees(theta) + 90.0) % 360.0
    velocidade = 10.0 + 2.0 * math.sin(theta * 2.0)

    return round(lat, 6), round(lon, 6), round(curso, 2), round(abs(velocidade), 2)


def _unidade_to_model(unidade: Dict[str, Any]) -> UnidadeMaritima:
    """Converte um registro interno para o modelo Pydantic UnidadeMaritima."""
    return UnidadeMaritima(
        mmsi=unidade["mmsi"],
        nome=unidade["nome"],
        imo=unidade.get("imo"),
        tipoUnidade=unidade["tipoUnidade"],
        status=unidade.get("status", StatusUnidade.ATIVA),
        licencasAutorizadas=unidade.get("licencasAutorizadas", []),
        disponibilidadeInicio=unidade.get("disponibilidadeInicio"),
        disponibilidadeFim=unidade.get("disponibilidadeFim"),
        latitude=unidade.get("latitude"),
        longitude=unidade.get("longitude"),
        licenca_ibama=unidade.get("licenca_ibama"),
        validade_licenca=unidade.get("validade_licenca"),
        status_licenca=unidade.get("status_licenca"),
        observacao_licenca=unidade.get("observacao_licenca"),
    )


def _obter_posicao_unidade(unidade: Dict[str, Any]) -> PosicaoAIS:
    """
    Obtém a posição de uma unidade.

    - Plataformas fixas: retorna coordenadas hardcoded.
    - Embarcações móveis: calcula posição simulada em tempo real.
    """
    now = datetime.now(timezone.utc)
    timestamp_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    tipo = unidade.get("tipoUnidade")

    if tipo in (TipoUnidade.PLATAFORMA_FIXA, TipoUnidade.UNIDADE_PRODUCAO):
        return PosicaoAIS(
            mmsi=unidade["mmsi"],
            nome=unidade["nome"],
            latitude=unidade["latitude"],
            longitude=unidade["longitude"],
            velocidade=0.0,
            curso=0.0,
            timestampAquisicao=timestamp_str,
            status="MOORED",
        )

    # Embarcação móvel — movimento simulado
    lat, lon, curso, velocidade = _calcular_posicao_simulada(unidade, now)
    return PosicaoAIS(
        mmsi=unidade["mmsi"],
        nome=unidade["nome"],
        latitude=lat,
        longitude=lon,
        velocidade=velocidade,
        curso=curso,
        timestampAquisicao=timestamp_str,
        status="UNDER WAY USING ENGINE",
    )


# ---------------------------------------------------------------------------
# Rate Limiting (in-memory, assíncrono)
# ---------------------------------------------------------------------------
class RateLimiter:
    """
    Rate limiter em memória baseado em janela deslizante.

    Controla o número de requisições por cliente dentro de uma janela de tempo.
    """

    def __init__(self, limit: int, window: int):
        self.limit = limit
        self.window = window
        self._requests: Dict[str, List[float]] = {}
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> Tuple[bool, int]:
    """
    Verifica se o cliente identificado por 'key' pode fazer uma requisição.

    Returns:
        Tupla (permitido, requisicoes_restantes).
    """
    async with self._lock:
        now = time.time()
        timestamps = [
            ts
            for ts in self._requests.get(key, [])
            if now - ts < self.window
        ]

        if len(timestamps) >= self.limit:
            self._requests[key] = timestamps
            logger.warning(
                f"Rate limit excedido para cliente {key}: "
                f"{len(timestamps)}/{self.limit} requisições em {self.window}s"
            )
            return False, 0

        timestamps.append(now)
        self._requests[key] = timestamps
        remaining = self.limit - len(timestamps)
        return True, remaining


rate_limiter = RateLimiter(
    limit=RATE_LIMIT, window=RATE_LIMIT_WINDOW_SECONDS
)


# ---------------------------------------------------------------------------
# Segurança — HTTPBearer e validação de token
# ---------------------------------------------------------------------------
security = HTTPBearer(auto_error=False)


async def get_current_client(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    """
    Dependência de segurança que valida o token Bearer JWT.

    Retorna o identificador do cliente (sub) contido no token.

    Raises:
        HTTPException 401: Token não fornecido.
        HTTPException 403: Token inválido, expirado ou sem identificação.
    """
    if not credentials:
        logger.warning("Requisição sem token de acesso")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de acesso não fornecido. Envie o cabeçalho Authorization: Bearer <token>.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        logger.warning(f"Falha ao decodificar token JWT: {exc}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token inválido ou expirado.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    client_id = payload.get("sub")
    if not client_id:
        logger.warning("Token JWT sem claim 'sub'")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token inválido: sem identificação do cliente.",
        )

    logger.debug(f"Cliente autenticado: {client_id}")
    return client_id


async def rate_limit_guard(
    request: Request, client_id: str = Depends(get_current_client)
) -> str:
    """
    Dependência que aplica rate limiting por cliente autenticado.

    Define atributos no estado da requisição para inclusão nos headers de resposta.
    """
    allowed, remaining = await rate_limiter.check(client_id)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Limite de requisições excedido. "
                f"Limite: {RATE_LIMIT} requisições por {RATE_LIMIT_WINDOW_SECONDS} segundos."
            ),
            headers={
                "Retry-After": str(RATE_LIMIT_WINDOW_SECONDS),
            },
        )
    request.state.rate_limit_remaining = remaining
    return client_id


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("Inicializando API IBAMA - Monitoramento de Unidades Marítimas")
    logger.info(f"Rate Limit: {RATE_LIMIT} req / {RATE_LIMIT_WINDOW_SECONDS}s")
    logger.info(f"Token expira em: {ACCESS_TOKEN_EXPIRE_MINUTES} minutos")
    logger.info(f"Unidades cadastradas: {len(UNIDADES_REGISTRY)}")
    logger.info("=" * 60)
    yield
    logger.info("Finalizando API IBAMA...")


# ---------------------------------------------------------------------------
# Inicialização do FastAPI
# ---------------------------------------------------------------------------
app = FastAPI(
    title="API IBAMA - Monitoramento de Unidades Marítimas",
    description=(
        "## Visão Geral\n\n"
        "API REST para consulta de unidades marítimas licenciadas pelo IBAMA "
        "e acompanhamento de posições AIS de embarcações em tempo real.\n\n"
        "## Autenticação\n\n"
        "Esta API utiliza o fluxo **OAuth 2.0 Client Credentials**.\n\n"
        "1. Obtenha um token em `POST /auth/token` enviando `client_id` e `client_secret`.\n"
        "2. Envie o token no cabeçalho `Authorization: Bearer <token>` em todas as requisições protegidas.\n\n"
        "## Rate Limiting\n\n"
        fCada cliente autenticado pode realizar até **{RATE_LIMIT} requisições** "
        fpor **{RATE_LIMIT_WINDOW_SECONDS} segundos**. "
        "Os headers `X-RateLimit-Limit` e `X-RateLimit-Remaining` indicam o limite e o saldo atual.\n\n"
        "## Unidades Disponíveis\n\n"
        "- **Plataformas fixas**: P-65, P-08, PPM-1, PCE-1 (posições hardcoded)\n"
        "- **Embarcações de apoio**: MAERSK VENTURA (710002450), MAERSK VEGA (710001720) (movimento simulado)\n"
        "- **Embarcações de emergência**: Navio Emergência Alpha (123456789)\n"
    ),
    version="1.0.0",
    docs_url="/v1/docs",
    redoc_url="/v1/redoc",
    openapi_url="/v1/openapi.json",
    contact={
        "name": "IBAMA - Instituto Brasileiro do Meio Ambiente",
        "url": "https://www.ibama.gov.br",
        "email": "contato@ibama.gov.br",
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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Middleware — Headers de resposta
# ---------------------------------------------------------------------------
@app.middleware("http")
async def add_response_headers(request: Request, call_next):
    """Adiciona headers de rate limiting e timestamp em todas as respostas."""
    response = await call_next(request)

    remaining = getattr(request.state, "rate_limit_remaining", None)
    if remaining is not None:
        response.headers["X-RateLimit-Limit"] = str(RATE_LIMIT)
        response.headers["X-RateLimit-Remaining"] = str(remaining)

    response.headers["X-Timestamp"] = iso_timestamp()

    return response


# ---------------------------------------------------------------------------
# Tratamento de erros padronizado
# ---------------------------------------------------------------------------
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handler padronizado para HTTPException, retornando ErrorResponse."""
    logger.warning(
        f"HTTPException {exc.status_code}: {exc.detail} - "
        f"path={request.url.path} method={request.method}"
    )
    content = ErrorResponse(
        error="HTTPException",
        message=str(exc.detail),
        timestamp=iso_timestamp(),
    ).model_dump()
    headers = dict(exc.headers) if exc.headers else {}
    return JSONResponse(status_code=exc.status_code, content=content, headers=headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
):
    """Handler para erros de validação de entrada (422)."""
    logger.warning(
        f"ValidationError: {exc.errors()} - path={request.url.path}"
    )
    content = ErrorResponse(
        error="ValidationError",
        message="Erro de validação nos dados de entrada. Verifique os parâmetros enviados.",
        timestamp=iso_timestamp(),
    ).model_dump()
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=content
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handler para erros internos não tratados (500)."""
    logger.exception(
        f"Erro interno não tratado: {exc} - path={request.url.path}"
    )
    content = ErrorResponse(
        error="InternalServerError",
        message="Erro interno do servidor. Entre em contato com o suporte.",
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
    summary="Obter token de acesso (OAuth 2.0 Client Credentials)",
    description=(
        "Endpoint para obtenção de token de acesso utilizando o fluxo "
        "OAuth 2.0 Client Credentials.\n\n"
        "Envie os parâmetros `grant_type`, `client_id` e `client_secret` "
        "no corpo da requisição como `application/x-www-form-urlencoded`.\n\n"
        "O token retornado deve ser enviado no cabeçalho `Authorization: Bearer <token>` "
        "em todas as requisições aos endpoints protegidos."
    ),
    response_description="Token JWT de acesso com tipo e tempo de expiração",
    responses={
        200: {"description": "Token gerado com sucesso", "model": TokenResponse},
        400: {"description": "grant_type inválido", "model": ErrorResponse},
        401: {"description": "Credenciais inválidas", "model": ErrorResponse},
    },
)
async def auth_token(
    grant_type: str = Form(
        ...,
        description="Tipo de concessão OAuth 2.0. Deve ser 'client_credentials'.",
        examples=["client_credentials"],
    ),
    client_id: str = Form(
        ...,
        description="Client ID fornecido pelo IBAMA",
        examples=["ibama-client"],
    ),
    client_secret: str = Form(
        ...,
        description="Client Secret fornecido pelo IBAMA",
        examples=["ibama-secret"],
    ),
):
    """
    Gera um token JWT de acesso via OAuth 2.0 Client Credentials.

    - **grant_type**: deve ser `client_credentials`
    - **client_id**: identificador do cliente
    - **client_secret**: segredo do cliente
    """
    if grant_type != "client_credentials":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="grant_type deve ser 'client_credentials'.",
        )

    if client_id != CLIENT_ID or client_secret != CLIENT_SECRET:
        logger.warning(f"Tentativa de autenticação com credenciais inválidas: client_id={client_id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais do cliente inválidas.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": client_id})
    logger.info(f"Token emitido para cliente: {client_id}")

    return TokenResponse(
        access_token=access_token,
        token_type="Bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@app.get(
    "/v1/unidades",
    response_model=List[UnidadeMaritima],
    tags=["Unidades Marítimas"],
    dependencies=[Depends(rate_limit_guard)],
    summary="Listar unidades marítimas licenciadas",
    description=(
        "Retorna a lista completa de unidades marítimas licenciadas pelo IBAMA, "
        "incluindo plataformas fixas e embarcações de apoio/emergência.\n\n"
        "Cada unidade contém dados de licenciamento, disponibilidade e, "
        "para plataformas fixas, coordenadas geográficas estáticas."
    ),
    response_description="Lista de unidades marítimas cadastradas",
    responses={
        200: {"description": "Lista de unidades retornada com sucesso"},
        401: {"description": "Token não fornecido", "model": ErrorResponse},
        403: {"description": "Token inválido", "model": ErrorResponse},
        429: {"description": "Rate limit excedido", "model": ErrorResponse},
    },
)
async def listar_unidades():
    """
    Lista todas as unidades marítimas licenciadas pelo IBAMA.

    Inclui plataformas fixas (P-65, P-08, PPM-1, PCE-1) e embarcações
    de apoio e emergência.
    """
    logger.info("Listagem de unidades solicitada")
    unidades = [_unidade_to_model(u) for u in UNIDADES_REGISTRY]
    logger.info(f"{len(unidades)} unidades retornadas")
    return unidades


@app.get(
    "/v1/posicao/{identificador}",
    response_model=PosicaoAIS,
    tags=["Posição AIS"],
    dependencies=[Depends(rate_limit_guard)],
    summary="Consultar posição AIS de unidade marítima",
    description=(
        "Retorna a posição atual de uma unidade marítima identificada por:\n\n"
        "- **MMSI numérico**: ex. `710002450`, `710001720`, `538001903`\n"
        "- **MMSI alfanumérico**: ex. `PPM-1`, `PCE-1`\n"
        "- **Nome da unidade**: ex. `P-65`, `P-08`, `MAERSK VENTURA`\n\n"
        "Para **plataformas fixas**, retorna coordenadas hardcoded.\n"
        "Para **embarcações móveis**, retorna posição simulada em tempo real "
        "(movimento circular ao redor da plataforma de referência)."
    ),
    response_description="Posição AIS atual da unidade solicitada",
    responses={
        200: {"description": "Posição retornada com sucesso", "model": PosicaoAIS},
        401: {"description": "Token não fornecido", "model": ErrorResponse},
        403: {"description": "Token inválido", "model": ErrorResponse},
        404: {"description": "Unidade não encontrada", "model": ErrorResponse},
        429: {"description": "Rate limit excedido", "model": ErrorResponse},
    },
)
async def obter_posicao(identificador: str):
    """
    Consulta a posição AIS de uma unidade marítima.

    O parâmetro `identificador` aceita:
    - MMSI numérico: 710002450, 710001720, 538001903, 538003593
    - MMSI alfanumérico: PPM-1, PCE-1
    - Nome: P-65, P-08, MAERSK VENTURA, MAERSK VEGA
    """
    unidade = _resolver_unidade(identificador)

    if unidade is None:
        logger.warning(f"Unidade não encontrada para identificador: {identificador}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unidade marítima '{identificador}' não encontrada. "
                   f"Identificadores válidos: MMSI numérico, MMSI alfanumérico ou nome da unidade.",
        )

    posicao = _obter_posicao_unidade(unidade)
    logger.info(
        f"Posição retornada para {unidade['nome']} ({unidade['mmsi']}): "
        f"lat={posicao.latitude}, lon={posicao.longitude}"
    )
    return posicao


@app.get(
    "/health",
    tags=["Monitoramento"],
    summary="Health check da API",
    description=(
        "Endpoint de verificação de saúde da API. Não requer autenticação.\n\n"
        "Retorna status operacional, versão e timestamp atual."
    ),
    response_description="Status operacional da API",
)
async def health_check():
    """
    Verifica a saúde da API.

    Retorna status operacional, versão e timestamp UTC atual.
    """
    return {
        "status": "ok",
        "timestamp": iso_timestamp(),
        "version": "1.0.0",
        "service": "api-ibama",
        "unidades_cadastradas": len(UNIDADES_REGISTRY),
    }


# ---------------------------------------------------------------------------
# Endpoint raiz — redirecionamento para documentação
# ---------------------------------------------------------------------------
@app.get(
    "/",
    tags=["Geral"],
    summary="Endpoint raiz",
    description="Redireciona para a documentação Swagger em /v1/docs",
    include_in_schema=False,
)
async def root():
    return {
        "service": "API IBAMA - Monitoramento de Unidades Marítimas",
        "version": "1.0.0",
        "docs": "/v1/docs",
        "health": "/health",
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    logger.info(f"Iniciando servidor uvicorn em {host}:{port}")
    uvicorn.run("main:app", host=host, port=port, log_level="info")