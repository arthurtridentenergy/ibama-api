from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, HTTPBearer, HTTPAuthorizationCredentials
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional, List
import jwt
import os
from dotenv import load_dotenv
import logging

# Carregar variáveis de ambiente
load_dotenv()

# ============================================
# CONFIGURAÇÃO DE LOGGING
# ============================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/api.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================
# VARIÁVEIS DE AMBIENTE
# ============================================
CLIENT_ID = os.getenv("CLIENT_ID", "ibama_client")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "sua_secret_key_aqui")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "sua_jwt_secret_aqui")

# ============================================
# CONFIGURAÇÃO DA API FastAPI
# ============================================
app = FastAPI(
    title="API Unidades Marítimas IBAMA",
    description="API para localização de unidades marítimas integrada com Spinergie",
    version="1.0.0"
)

# ============================================
# SCHEMAS (Modelos de Dados)
# ============================================

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

# ============================================
# SEGURANÇA E AUTENTICAÇÃO
# ============================================

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/auth/token",
    auto_error=False
)

http_bearer = HTTPBearer(auto_error=False)

def criar_token_jwt(client_id: str, expires_in: int = 3600) -> str:
    payload = {
        "sub": client_id,
        "exp": datetime.utcnow() + timedelta(seconds=expires_in),
        "iat": datetime.utcnow()
    }
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm="HS256")
    logger.info(f"Token criado para cliente: {client_id}")
    return token

def verificar_token_jwt(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"])
        logger.info(f"Token válido para: {payload.get('sub')}")
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Token expirado")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expirado"
        )
    except jwt.InvalidTokenError:
        logger.warning("Token inválido")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido"
        )

async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer)
) -> str:
    if credentials:
        token = credentials.credentials
    
    if not token:
        logger.warning("Token não fornecido")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token não fornecido"
        )
    
    payload = verificar_token_jwt(token)
    return payload.get("sub")

# ============================================
# ENDPOINTS
# ============================================

@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    logger.info("Health check realizado")
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "version": "1.0.0"
    }

@app.post("/auth/token", response_model=TokenResponse, tags=["Autenticação"])
async def obter_token(request: TokenRequest):
    if request.client_id != CLIENT_ID or request.client_secret != CLIENT_SECRET:
        logger.warning(f"Tentativa de autenticação falha com client_id: {request.client_id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais inválidas"
        )
    
    expires_in = 3600
    token = criar_token_jwt(request.client_id, expires_in)
    
    logger.info(f"Token gerado com sucesso para: {request.client_id}")
    
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": expires_in
    }

@app.get("/v1/unidades", response_model=List[UnidadeMaritima], tags=["Unidades Marítimas"])
async def listar_unidades(current_user: str = Depends(get_current_user)):
    logger.info(f"Listando unidades marítimas para usuário: {current_user}")
    
    unidades = [
        {
            "nome": "Plataforma P-01",
            "imo": "1234567",
            "mmsi": "123456789",
            "tipoUnidade": "Plataforma de Produção",
            "licencasAutorizadas": ["ANP-2024-001", "IBAMA-2024-002"],
            "disponibilidadeInicio": "2024-01-01T00:00:00Z",
            "disponibilidadeFim": "2026-12-31T23:59:59Z"
        },
        {
            "nome": "Navio de Suporte N-02",
            "imo": "9876543",
            "mmsi": "987654321",
            "tipoUnidade": "Navio de Apoio",
            "licencasAutorizadas": ["ANP-2024-003"],
            "disponibilidadeInicio": "2024-06-01T00:00:00Z",
            "disponibilidadeFim": "2026-12-31T23:59:59Z"
        }
    ]
    
    logger.info(f"Retornando {len(unidades)} unidades marítimas")
    return unidades

@app.get("/v1/posicao/{mmsi}", response_model=PosicaoAIS, tags=["Posição AIS"])
async def obter_posicao(mmsi: str, current_user: str = Depends(get_current_user)):
    logger.info(f"Buscando posição para MMSI: {mmsi} (usuário: {current_user})")
    
    posicoes = {
        "123456789": {
            "mmsi": "123456789",
            "latitude": -22.9068,
            "longitude": -42.0281,
            "timestampAquisicao": datetime.utcnow().isoformat() + "Z"
        },
        "987654321": {
            "mmsi": "987654321",
            "latitude": -23.5505,
            "longitude": -46.6333,
            "timestampAquisicao": datetime.utcnow().isoformat() + "Z"
        }
    }
    
    if mmsi not in posicoes:
        logger.warning(f"MMSI não encontrado: {mmsi}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unidade com MMSI {mmsi} não encontrada"
        )
    
    logger.info(f"Posição encontrada para MMSI: {mmsi}")
    return posicoes[mmsi]

@app.get("/v1/posicao", response_model=List[PosicaoAIS], tags=["Posição AIS"])
async def obter_posicoes_todas(current_user: str = Depends(get_current_user)):
    logger.info(f"Buscando todas as posições (usuário: {current_user})")
    
    posicoes = [
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
    
    logger.info(f"Retornando posições de {len(posicoes)} unidades")
    return posicoes

# ============================================
# DOCUMENTAÇÃO AUTOMÁTICA (OpenAPI)
# ============================================

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title="API Unidades Marítimas IBAMA",
        version="1.0.0",
        description="API para localização e monitoramento de unidades marítimas integrada com Spinergie",
        routes=app.routes,
    )
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# ============================================
# EXECUÇÃO
# ============================================

if __name__ == "__main__":
    import uvicorn
    
    os.makedirs("logs", exist_ok=True)
    
    logger.info("Iniciando API IBAMA...")
    logger.info(f"CLIENT_ID: {CLIENT_ID}")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )