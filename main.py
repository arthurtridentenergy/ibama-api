from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional, List
import jwt
import os
from dotenv import load_dotenv
import logging
import json

# Carregar variáveis de ambiente
load_dotenv()

# ==================== LOGGING ====================

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/api.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== VARIÁVEIS DE AMBIENTE ====================

CLIENT_ID = os.getenv("CLIENT_ID", "ibama_client")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "seu_client_secret")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "seu_jwt_secret")
SPINERGIE_BASE_URL = os.getenv("SPINERGIE_BASE_URL", "https://trident-energy-br.spinergie.com/")
SPINERGIE_API_KEY = os.getenv("SPINERGIE_API_KEY", "default_api_key")

# ==================== CRIAR APP ====================

app = FastAPI(
    title="API Unidades Marítimas IBAMA",
    description="API para localização de unidades marítimas - Integração Spinergie",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# ==================== MODELOS PYDANTIC ====================

class TokenRequest(BaseModel):
    grant_type: str = "client_credentials"
    client_id: str
    client_secret: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int

class UnidadeMaritima(BaseModel):
    nome: str
    imo: str
    mmsi: str
    tipoUnidade: str
    licencasAutorizadas: List[str]
    disponibilidadeInicio: str
    disponibilidadeFim: str

class PosicaoAIS(BaseModel):
    mmsi: str
    latitude: float
    longitude: float
    timestampAquisicao: str

class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str

class ErrorResponse(BaseModel):
    error: str
    detail: str

# ==================== AUTENTICAÇÃO ====================

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)
http_bearer = HTTPBearer(auto_error=False)

def criar_token(client_id: str, expires_in: int = 3600) -> str:
    """Cria token JWT"""
    payload = {
        "sub": client_id,
        "exp": datetime.utcnow() + timedelta(seconds=expires_in),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm="HS256")

def verificar_token(token: str) -> dict:
    """Verifica token JWT"""
    try:
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        logger.warning("Token expirado")
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        logger.warning("Token inválido")
        raise HTTPException(status_code=401, detail="Token inválido")

async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer)
) -> str:
    """Obtém usuário autenticado"""
    if credentials:
        token = credentials.credentials
    
    if not token:
        raise HTTPException(status_code=401, detail="Token não fornecido")
    
    payload = verificar_token(token)
    return payload.get("sub")

# ==================== ENDPOINTS ====================

@app.get("/", tags=["Root"])
async def root():
    """Root endpoint"""
    return {
        "message": "API Unidades Marítimas IBAMA",
        "version": "1.0.0",
        "docs": "/docs"
    }

@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health():
    """Health check"""
    logger.info("Health check")
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "version": "1.0.0"
    }

@app.post("/auth/token", response_model=TokenResponse, tags=["Auth"])
async def get_token(request: TokenRequest):
    """Gera token JWT"""
    if request.client_id != CLIENT_ID or request.client_secret != CLIENT_SECRET:
        logger.warning(f"Auth falhou: {request.client_id}")
        raise HTTPException(status_code=401, detail="Credenciais inválidas")
    
    token = criar_token(request.client_id)
    logger.info(f"Token gerado para: {request.client_id}")
    
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": 3600
    }

@app.get("/v1/unidades", response_model=List[UnidadeMaritima], tags=["Unidades"])
async def listar_unidades(current_user: str = Depends(get_current_user)):
    """Lista todas as unidades marítimas"""
    logger.info(f"Listando unidades para: {current_user}")
    
    return [
        {
            "nome": "Plataforma P-01",
            "imo": "1234567",
            "mmsi": "123456789",
            "tipoUnidade": "Plataforma",
            "licencasAutorizadas": ["ANP-2024-001"],
            "disponibilidadeInicio": "2024-01-01T00:00:00Z",
            "disponibilidadeFim": "2026-12-31T23:59:59Z"
        },
        {
            "nome": "Navio N-02",
            "imo": "9876543",
            "mmsi": "987654321",
            "tipoUnidade": "Navio",
            "licencasAutorizadas": ["ANP-2024-002"],
            "disponibilidadeInicio": "2024-01-01T00:00:00Z",
            "disponibilidadeFim": "2026-12-31T23:59:59Z"
        }
    ]

@app.get("/v1/posicao/{mmsi}", response_model=PosicaoAIS, tags=["Posição"])
async def obter_posicao(mmsi: str, current_user: str = Depends(get_current_user)):
    """Obtém posição de uma unidade"""
    logger.info(f"Posição solicitada para MMSI: {mmsi}")
    
    posicoes = {
        "123456789": {"mmsi": "123456789", "latitude": -22.9068, "longitude": -42.0281},
        "987654321": {"mmsi": "987654321", "latitude": -23.5505, "longitude": -46.6333}
    }
    
    if mmsi not in posicoes:
        logger.warning(f"MMSI não encontrado: {mmsi}")
        raise HTTPException(status_code=404, detail=f"MMSI {mmsi} não encontrado")
    
    pos = posicoes[mmsi]
    return {
        "mmsi": pos["mmsi"],
        "latitude": pos["latitude"],
        "longitude": pos["longitude"],
        "timestampAquisicao": datetime.utcnow().isoformat() + "Z"
    }

@app.get("/v1/posicao", response_model=List[PosicaoAIS], tags=["Posição"])
async def listar_posicoes(current_user: str = Depends(get_current_user)):
    """Lista posições de todas as unidades"""
    logger.info(f"Todas as posições solicitadas por: {current_user}")
    
    return [
        {
            "mmsi": "123456789",
            "latitude": -22.9068,
            "longitude": -42.0281,
            "timestampAquisicao": datetime.utcnow().isoformat() + "Z"
        },
        {
            "mmsi": "987654321",
            "latitude": -23.5505,
            "longitude": -46.6333,
            "timestampAquisicao": datetime.utcnow().isoformat() + "Z"
        }
    ]

# ==================== EXECUTAR ====================

if __name__ == "__main__":
    import uvicorn
    logger.info("Iniciando API IBAMA")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )