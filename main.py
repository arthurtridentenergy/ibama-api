### config.py ###
import os
from typing import Optional

# Configurações carregadas de variáveis de ambiente
SPINERGIE_BASE_URL: str = os.getenv("SPINERGIE_BASE_URL", "https://api.spinergie.com").rstrip("/")
SPINERGIE_API_KEY: Optional[str] = os.getenv("SPINERGIE_API_KEY")
JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "secret")
ALGORITHM: str = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
CLIENT_ID: str = os.getenv("CLIENT_ID", "client")
CLIENT_SECRET: str = os.getenv("CLIENT_SECRET", "secret")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

# Coordenadas hardcoded das plataformas (convertidas para decimal)
# Origem: graus minutos -> decimal
PPM_1_LAT: float = -22.798   # 22°47.88'S
PPM_1_LON: float = -40.7625  # 40°45.75'W
PCE_1_LAT: float = -22.708333  # 22°42.50'S
PCE_1_LON: float = -40.693167  # 40°41.59'W
P08_LAT: float = -22.673167  # 22°40.39'S
P08_LON: float = -40.5465    # 40°32.79'W
P65_LAT: float = -22.701833  # 22°42.11'S
P65_LON: float = -40.67716   # 40°40.63'W

# Mapeamento de nomes de plataformas
PLATAFORMAS_FIXAS = {
    "PPM-1": {"nome": "PPM-1", "latitude": PPM_1_LAT, "longitude": PPM_1_LON},
    "PCE-1": {"nome": "PCE-1", "latitude": PCE_1_LAT, "longitude": PCE_1_LON},
    "P-08": {"nome": "P-08", "latitude": P08_LAT, "longitude": P08_LON},
    "P-65": {"nome": "P-65", "latitude": P65_LAT, "longitude": P65_LON},
}

# MMSIs das plataformas (necessários para consulta externa, se existir)
PLATAFORMAS_MMSI = {
    "P-08": os.getenv("P08_MMSI", "538001903"),
    "P-65": os.getenv("P65_MMSI", "538003593"),
}

# Embarcações móveis monitoradas via Spinergie
VESSEL_NAMES = ["MAERSK VEGA", "MAERSK VENTURA"]
VESSEL_MMSI = {
    "MAERSK VEGA": os.getenv("MAERSK_VEGA_MMSI", "710001720"),
    "MAERSK VENTURA": os.getenv("MAERSK_VENTURA_MMSI", "710002450"),
}

### models.py ###
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class Conformidade(BaseModel):
    """Informações de conformidade IBAMA para uma plataforma ou embarcação."""
    plataforma_embarcacao: str = Field(..., description="Nome da plataforma ou embarcação")
    mmsi: Optional[str] = Field(None, description="MMSI (para embarcações)")
    licenca: str = Field(..., description="Número da licença ambiental")
    validade: Optional[str] = Field(None, description="Data de validade da licença (formato DD/MM/AAAA)")
    observacao: Optional[str] = Field(None, description="Observações adicionais")

    class Config:
        json_schema_extra = {
            "example": {
                "plataforma_embarcacao": "PPM-1",
                "mmsi": None,
                "licenca": "LO1572/2020",
                "validade": "11/7/2024",
                "observacao": ""
            }
        }


class PosicaoResponse(BaseModel):
    """Resposta de posição geográfica."""
    identificador: str = Field(..., description="MMSI, nome da plataforma ou nome da embarcação")
    nome: str = Field(..., description="Nome da unidade")
    latitude: float
    longitude: float
    timestamp_aquisicao: str = Field(..., description="ISO 8601 UTC")
    fonte: str = Field(..., description="Fonte dos dados (coordenada_fixa, spinergie)")

    class Config:
        json_schema_extra = {
            "example": {
                "identificador": "P-65",
                "nome": "P-65",
                "latitude": -22.701833,
                "longitude": -40.67716,
                "timestamp_aquisicao": "2024-07-11T12:00:00+00:00",
                "fonte": "coordenada_fixa"
            }
        }


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ErrorResponse(BaseModel):
    detail: str


### services.py ###
import math
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import httpx

from config import (
    SPINERGIE_BASE_URL, SPINERGIE_API_KEY,
    PLATAFORMAS_FIXAS, PLATAFORMAS_MMSI,
    VESSEL_MMSI, VESSEL_NAMES,
    DISCREPANCY_THRESHOLD_KM
)

logger = logging.getLogger(__name__)

# Cache simples em memória (TTL de 5 minutos)
_cache: Dict[str, Dict[str, Any]] = {}
CACHE_TTL = timedelta(minutes=5)

# Limiar para alerta de discrepância (km)
DISCREPANCY_THRESHOLD_KM = 3.0

# Dados da tabela IBAMA (hardcoded conforme especificação)
TABELA_IBAMA: List[Conformidade] = [
    Conformidade(plataforma_embarcacao="PPM-1", mmsi=None, licenca="LO1572/2020", validade="11/7/2024", observacao=""),
    Conformidade(plataforma_embarcacao="PCE-1", mmsi=None, licenca="LO1572/2020", validade="11/7/2024", observacao=""),
    Conformidade(plataforma_embarcacao="P-08", mmsi="538001903", licenca="LO1572/2020", validade="11/7/2024", observacao=""),
    Conformidade(plataforma_embarcacao="P-65", mmsi="538003593", licenca="LO1572/2020", validade="11/7/2024", observacao=""),
    Conformidade(plataforma_embarcacao="MAERSK VENTURA", mmsi="710002450", licenca="LO1572/2020", validade=None, observacao=""),
    Conformidade(plataforma_embarcacao="MAERSK VEGA", mmsi="710001720", licenca="LO1572/2020", validade=None, observacao=""),
]


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcula a distância em km usando a fórmula de Haversine."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c


def _is_cache_valid(key: str) -> bool:
    """Verifica se há entrada de cache válida para a chave."""
    if key in _cache:
        entry = _cache[key]
        return datetime.now(timezone.utc) - entry["timestamp"] < CACHE_TTL
    return False


def _set_cache(key: str, data: Any) -> None:
    """Armazena no cache com timestamp."""
    _cache[key] = {"data": data, "timestamp": datetime.now(timezone.utc)}


async def _call_spinergie_api(mmsi: str) -> Optional[Dict[str, Any]]:
    """Realiza a chamada à API Spinergie para obter a posição mais recente da embarcação."""
    if not SPINERGIE_API_KEY:
        logger.error("SPINERGIE_API_KEY não configurada. Não será possível consultar Spinergie.")
        return None

    url = f"{SPINERGIE_BASE_URL}/sd/api/vessel/sfm-latest-locations"
    headers = {
        "Authorization": f"ApiKey {SPINERGIE_API_KEY}",
        "Accept": "application/json",
    }
    params = {"mmsi": mmsi}

    logger.info(f"Consultando Spinergie para MMSI {mmsi}")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=headers, params=params)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    return data[0] if data else None
                elif isinstance(data, dict):
                    return data
                else:
                    logger.warning(f"Resposta inesperada do Spinergie para {mmsi}: {data}")
                    return None
            else:
                logger.error(f"Spinergie retornou {response.status_code} para {mmsi}")
                return None
    except httpx.HTTPError as e:
        logger.exception(f"Erro de rede ao consultar Spinergie para {mmsi}: {e}")
        return None
    except Exception as e:
        logger.exception(f"Erro inesperado na chamada Spinergie para {mmsi}: {e}")
        return None


async def _get_vessel_position(mmsi: str, nome: str) -> Optional[Dict[str, Any]]:
    """Obtém a posição de uma embarcação via Spinergie, com cache."""
    cache_key = f"vessel_{mmsi}"
    if _is_cache_valid(cache_key):
        logger.debug(f"Retornando posição do cache para {mmsi}")
        return _cache[cache_key]["data"]

    raw = await _call_spinergie_api(mmsi)
    if raw:
        # Normalizar campos
        latitude = raw.get("latitude") or raw.get("lat")
        longitude = raw.get("longitude") or raw.get("lon") or raw.get("lng")
        timestamp = raw.get("timestamp") or raw.get("lastReceived") or datetime.now(timezone.utc).isoformat()

        if latitude is None or longitude is None:
            logger.warning(f"Coordenadas ausentes na resposta para {mmsi}")
            return None

        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (TypeError, ValueError):
            logger.warning(f"Coordenadas inválidas para {mmsi}")
            return None

        pos = {
            "identificador": mmsi,
            "nome": nome,
            "latitude": latitude,
            "longitude": longitude,
            "timestamp_aquisicao": timestamp,
            "fonte": "spinergie"
        }
        _set_cache(cache_key, pos)
        logger.info(f"Posição obtida para {mmsi} ({nome}): ({latitude}, {longitude})")
        return pos
    return None


def _get_platform_position(nome: str) -> Optional[Dict[str, Any]]:
    """Retorna a posição fixa de uma plataforma, se cadastrada."""
    if nome in PLATAFORMAS_FIXAS:
        plat = PLATAFORMAS_FIXAS[nome]
        return {
            "identificador": nome,
            "nome": nome,
            "latitude": plat["latitude"],
            "longitude": plat["longitude"],
            "timestamp_aquisicao": datetime.now(timezone.utc).isoformat(),
            "fonte": "coordenada_fixa"
        }
    return None


async def get_position(identificador: str) -> Optional[Dict[str, Any]]:
    """Obtém a posição para qualquer identificador (plataforma, MMSI ou nome de embarcação).
    
    Primeiro tenta como plataforma fixa, depois como embarcação via nome ou MMSI.
    """
    # Verificar se é uma plataforma (por nome exato)
    ident_upper = identificador.upper()
    if ident_upper in PLATAFORMAS_FIXAS:
        return _get_platform_position(ident_upper)
    
    # Verificar se é uma plataforma pelo MMSI (caso informado como MMSI)
    for plat_nome, plat_mmsi in PLATAFORMAS_MMSI.items():
        if identificador == plat_mmsi:
            return _get_platform_position(plat_nome)
    
    # Verificar se é um nome de embarcação conhecido
    nome_vessel = None
    for nome in VESSEL_NAMES:
        if nome.upper() == ident_upper:
            nome_vessel = nome
            break
    if nome_vessel:
        mmsi = VESSEL_MMSI.get(nome_vessel)
        if mmsi:
            return await _get_vessel_position(mmsi, nome_vessel)
        else:
            logger.error(f"MMSI não configurado para {nome_vessel}")
            return None
    
    # Se for um MMSI numérico, verificar se pertence a alguma embarcação
    if identificador.isdigit() and len(identificador) == 9:
        for nome, mmsi in VESSEL_MMSI.items():
            if mmsi == identificador:
                return await _get_vessel_position(mmsi, nome)
    
    # Nenhum reconhecido
    logger.warning(f"Identificador não reconhecido: {identificador}")
    return None


def get_conformidade_table() -> List[Conformidade]:
    """Retorna a tabela de conformidade IBAMA completa."""
    return TABELA_IBAMA


def get_plataformas() -> List[Conformidade]:
    """Retorna apenas as plataformas da tabela IBAMA."""
    return [item for item in TABELA_IBAMA if item.plataforma_embarcacao in PLATAFORMAS_FIXAS]


def get_embarcacoes() -> List[Conformidade]:
    """Retorna apenas as embarcações da tabela IBAMA."""
    return [item for item in TABELA_IBAMA if item.plataforma_embarcacao not in PLATAFORMAS_FIXAS]


### main.py ###
import logging
import os
from typing import Optional
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Depends, Path, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from jose import jwt, JWTError

from config import (
    JWT_SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES,
    CLIENT_ID, CLIENT_SECRET, LOG_LEVEL
)
from models import Conformidade, PosicaoResponse, TokenResponse, ErrorResponse
from services import get_position, get_conformidade_table, get_plataformas, get_embarcacoes

# Configuração de logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="IBAMA API - Monitoramento de Embarcações e Plataformas",
    description="API para consulta de conformidade ambiental e posições de plataformas e embarcações.",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Segurança
security = HTTPBearer(auto_error=False)

def authenticate_client(client_id: str, client_secret: str) -> bool:
    """Verifica as credenciais do cliente."""
    return client_id == CLIENT_ID and client_secret == CLIENT_SECRET

def create_access_token(data: dict) -> str:
    """Cria um token JWT."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=ALGORITHM)

def get_current_client_id(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> str:
    """Valida o token JWT e retorna o client_id."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Token de autorização ausente")
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
        client_id: str = payload.get("sub")
        if client_id is None:
            raise HTTPException(status_code=401, detail="Token inválido")
        return client_id
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado")


@app.get("/health")
def health():
    """Endpoint público de verificação de saúde."""
    return {"status": "ok"}


@app.post("/auth/token", response_model=TokenResponse, responses={400: {"model": ErrorResponse}})
async def login_for_access_token(
    grant_type: str = Form(...),
    client_id: str = Form(...),
    client_secret: str = Form(...),
):
    """Autenticação OAuth2 Client Credentials."""
    if grant_type != "client_credentials":
        raise HTTPException(status_code=400, detail="Tipo de concessão inválido")
    if not authenticate_client(client_id, client_secret):
        raise HTTPException(status_code=401, detail="Credenciais de cliente inválidas")
    access_token = create_access_token(data={"sub": client_id})
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/v1/conformidade", response_model=list[Conformidade], response_model_exclude_none=True)
async def listar_conformidade(current_client: str = Depends(get_current_client_id)):
    """Retorna a tabela completa de conformidade IBAMA."""
    logger.info("Requisição: GET /v1/conformidade")
    return get_conformidade_table()


@app.get("/v1/plataformas", response_model=list[Conformidade], response_model_exclude_none=True)
async def listar_plataformas(current_client: str = Depends(get_current_client_id)):
    """Retorna apenas as plataformas da tabela IBAMA."""
    logger.info("Requisição: GET /v1/plataformas")
    return get_plataformas()


@app.get("/v1/embarcacoes", response_model=list[Conformidade], response_model_exclude_none=True)
async def listar_embarcacoes(current_client: str = Depends(get_current_client_id)):
    """Retorna apenas as embarcações da tabela IBAMA."""
    logger.info("Requisição: GET /v1/embarcacoes")
    return get_embarcacoes()


@app.get("/v1/posicao/{identificador}", response_model=PosicaoResponse, responses={
    400: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
})
async def consultar_posicao(
    identificador: str = Path(..., min_length=1, description="Nome da plataforma, MMSI ou nome da embarcação"),
    current_client: str = Depends(get_current_client_id),
):
    """Consulta a posição em tempo real de uma unidade.
    
    Para plataformas, retorna as coordenadas fixas cadastradas.
    Para embarcações, consulta a API Spinergie (c/ fallback para cache).
    """
    logger.info(f"Requisição: GET /v1/posicao/{identificador}")
    try:
        posicao = await get_position(identificador)
        if posicao:
            return PosicaoResponse(**posicao)
        else:
            raise HTTPException(status_code=404, detail=f"Unidade '{identificador}' não encontrada ou sem posição disponível.")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Erro ao consultar posição para {identificador}: {e}")
        raise HTTPException(status_code=503, detail="Erro interno ao obter posição. Tente novamente mais tarde.")


@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    logger.error(f"Erro inesperado: {exc}")
    return JSONResponse(status_code=500, content={"detail": "Erro interno do servidor"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))

### .env.example ###
# Configurações do servidor
PORT=8000
LOG_LEVEL=INFO

# Credenciais da API Spinergie (obrigatório para dados de embarcações)
SPINERGIE_API_KEY=your_spinergie_api_key_here

# Segurança JWT e cliente
JWT_SECRET_KEY=replace_with_a_secure_random_secret
CLIENT_ID=ibama_client
CLIENT_SECRET=strong_secret_here
ACCESS_TOKEN_EXPIRE_MINUTES=30

# MMSIs das embarcações (opcional, pode ser sobrescrito se necessário)
# MAERSK_VEGA_MMSI=710001720
# MAERSK_VENTURA_MMSI=710002450
# MMSIs das plataformas (apenas se houver consulta externa)
# P08_MMSI=538001903
# P65_MMSI=538003593

### requirements.txt ###
fastapi>=0.95.0
uvicorn>=0.17.0
python-jose[cryptography]>=3.3.0
pydantic>=2.0.0
pydantic-settings>=2.0.0
httpx>=0.23.0
python-dotenv>=1.0.0