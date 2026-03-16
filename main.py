from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from typing import Optional, List, Dict
import jwt
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
from slowapi import Limiter
from slowapi.util import get_remote_address
import logging

# Carregar variáveis de ambiente
load_dotenv()

# Configuração de Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Variáveis de Ambiente
CLIENT_ID = os.getenv("CLIENT_ID", "ibama_client")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "seu_secret_aqui")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "seu_jwt_secret_aqui")

# Configuração da API FastAPI
app = FastAPI(
    title="API de Localização de Unidades Marítimas",
    description="Integração com plataforma IBAMA/CGMAC conforme Anexo Técnico",
    version="1.0.0",
    docs_url="/v1/docs",
    redoc_url="/v1/redoc",
    openapi_url="/v1/openapi.json"
)

# Rate Limiting (100 requisições por minuto)
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

# ============================================================================
# MODELOS PYDANTIC (Schemas JSON)
# ============================================================================

class TokenRequest(BaseModel):
    """Requisição de Token OAuth 2.0 Client Credentials"""
    grant_type: str = "client_credentials"
    client_id: str
    client_secret: str

class TokenResponse(BaseModel):
    """Resposta de Token JWT"""
    access_token: str
    token_type: str
    expires_in: int

class UnidadeMaritima(BaseModel):
    """Modelo de Unidade Marítima conforme IBAMA"""
    nome: str
    imo: Optional[str] = None
    mmsi: str
    tipoUnidade: str
    licencasAutorizadas: List[str]
    disponibilidadeInicio: str
    disponibilidadeFim: Optional[str] = None

class PosicaoAIS(BaseModel):
    """Modelo de Posição AIS conforme IBAMA"""
    mmsi: str
    latitude: float
    longitude: float
    timestampAquisicao: str

class ErrorResponse(BaseModel):
    """Modelo de Erro Padronizado IBAMA"""
    error: str
    error_description: str

# ============================================================================
# AUTENTICAÇÃO E SEGURANÇA
# ============================================================================

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/auth/token",
    auto_error=False
)

def criar_token_jwt(client_id: str, expires_in: int = 3600) -> str:
    """Cria um token JWT válido"""
    payload = {
        "sub": client_id,
        "exp": datetime.utcnow() + timedelta(seconds=expires_in),
        "iat": datetime.utcnow()
    }
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm="HS256")
    logger.info(f"Token JWT criado para: {client_id}")
    return token

def verificar_token_jwt(token: str) -> Dict:
    """Verifica e valida um token JWT"""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"])
        logger.info(f"Token validado para: {payload.get('sub')}")
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

def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> str:
    """Obtém o usuário atual baseado no token Bearer"""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token não fornecido",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    payload = verificar_token_jwt(token)
    return payload.get("sub")

# ============================================================================
# ENDPOINTS OBRIGATÓRIOS (Conforme IBAMA)
# ============================================================================

@app.post("/auth/token", response_model=TokenResponse, tags=["Autenticação"])
async def obter_token(
    grant_type: str = "client_credentials",
    client_id: str = None,
    client_secret: str = None
):
    """
    POST /auth/token
    
    Obtém um token JWT para autenticação via OAuth 2.0 Client Credentials Flow.
    
    **Parâmetros:**
    - grant_type: Sempre "client_credentials"
    - client_id: ID da credencial (ibama_client)
    - client_secret: Senha da credencial
    
    **Retorna:**
    - access_token: Token JWT temporário (válido por 3600 segundos)
    - token_type: Sempre "Bearer"
    - expires_in: Tempo de expiração em segundos
    
    **Códigos de Resposta:**
    - 200: Token gerado com sucesso
    - 401: Credenciais inválidas
    - 400: Parâmetros obrigatórios ausentes
    """
    
    # Validação de parâmetros obrigatórios
    if not grant_type or not client_id or not client_secret:
        logger.warning("Requisição com parâmetros obrigatórios faltando")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parâmetros obrigatórios: grant_type, client_id, client_secret"
        )
    
    # Validação de credenciais
    if client_id != CLIENT_ID or client_secret != CLIENT_SECRET:
        logger.warning(f"Tentativa de autenticação falha: client_id={client_id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_token"
        )
    
    # Criação do token
    expires_in = 3600
    access_token = criar_token_jwt(client_id, expires_in)
    
    logger.info(f"Autenticação bem-sucedida para: {client_id}")
    
    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": expires_in
    }

@app.get("/v1/unidades", response_model=List[UnidadeMaritima], tags=["Unidades Marítimas"])
@limiter.limit("100/minute")
async def listar_unidades(
    request,
    current_user: str = Depends(get_current_user)
):
    """
    GET /v1/unidades
    
    Retorna a lista completa de unidades marítimas gerenciadas.
    
    **Autenticação:** Requer Bearer Token JWT válido
    
    **Rate Limit:** 100 requisições/minuto
    
    **Retorna:**
    - Lista de objetos UnidadeMaritima com dados cadastrais e de disponibilidade
    
    **Códigos de Resposta:**
    - 200: Lista de unidades retornada com sucesso
    - 401: Token ausente ou inválido
    - 429: Limite de requisições excedido
    - 500: Erro interno do servidor
    """
    
    logger.info(f"GET /v1/unidades - Usuário: {current_user}")
    
    # Dados de exemplo (em produção, integrar com Spinergie)
    unidades = [
        {
            "nome": "MAERSK MAKER",
            "imo": "9413535",
            "mmsi": "710005854",
            "tipoUnidade": "EMBARCACAO_APOIO",
            "licencasAutorizadas": ["LO1234/2025", "LPS123/2025"],
            "disponibilidadeInicio": "2024-01-01T00:00:00Z",
            "disponibilidadeFim": None
        },
        {
            "nome": "PLATAFORMA MARLIN",
            "imo": "7654321",
            "mmsi": "123456789",
            "tipoUnidade": "UNIDADE_PRODUCAO",
            "licencasAutorizadas": ["ANP-2024-001"],
            "disponibilidadeInicio": "2023-06-15T00:00:00Z",
            "disponibilidadeFim": "2026-12-31T23:59:59Z"
        }
    ]
    
    logger.info(f"Retornando {len(unidades)} unidades marítimas")
    return unidades

@app.get("/v1/posicao/{mmsi}", response_model=PosicaoAIS, tags=["Posição AIS"])
@limiter.limit("100/minute")
async def obter_posicao(
    request,
    mmsi: str,
    current_user: str = Depends(get_current_user)
):
    """
    GET /v1/posicao/{mmsi}
    
    Retorna a geolocalização AIS mais recente de uma unidade específica.
    
    **Parâmetros:**
    - mmsi: Número MMSI da embarcação (9 dígitos, ex: 710005854)
    
    **Autenticação:** Requer Bearer Token JWT válido
    
    **Rate Limit:** 100 requisições/minuto
    
    **Retorna:**
    - Objeto PosicaoAIS com coordenadas geográficas em tempo real
    
    **Códigos de Resposta:**
    - 200: Posição retornada com sucesso
    - 401: Token ausente ou inválido
    - 404: MMSI não encontrado
    - 429: Limite de requisições excedido
    - 500: Erro interno do servidor
    """
    
    logger.info(f"GET /v1/posicao/{mmsi} - Usuário: {current_user}")
    
    # Dados de exemplo (em produção, integrar com Spinergie)
    posicoes = {
        "710005854": {
            "mmsi": "710005854",
            "latitude": -22.9068,
            "longitude": -42.0281,
            "timestampAquisicao": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        },
        "123456789": {
            "mmsi": "123456789",
            "latitude": -23.5505,
            "longitude": -46.6333,
            "timestampAquisicao": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        }
    }
    
    if mmsi not in posicoes:
        logger.warning(f"MMSI não encontrado: {mmsi}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"not_found: A unidade marítima com MMSI '{mmsi}' não foi encontrada."
        )
    
    logger.info(f"Posição encontrada para MMSI: {mmsi}")
    return posicoes[mmsi]

# ============================================================================
# TRATAMENTO DE ERROS GLOBAL
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Handler customizado para HTTPException retornando JSON IBAMA"""
    if exc.status_code == 401:
        return {
            "error": "invalid_token",
            "error_description": "Token de autenticação inválido ou expirado."
        }
    elif exc.status_code == 404:
        return {
            "error": "not_found",
            "error_description": exc.detail
        }
    elif exc.status_code == 429:
        return {
            "error": "rate_limit_exceeded",
            "error_description": "Limite de requisições excedido. Tente novamente mais tarde."
        }
    else:
        return {
            "error": "internal_server_error",
            "error_description": "Ocorreu uma falha inesperada no servidor."
        }

# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.get("/health", tags=["Health Check"])
async def health_check():
    """
    GET /health
    
    Verifica se a API está operacional.
    
    **Retorna:**
    - status: "ok" se tudo está funcionando
    - timestamp: data/hora atual em ISO 8601 UTC
    - version: versão da API
    """
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "version": "1.0.0"
    }

# ============================================================================
# EXECUÇÃO
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    logger.info("========================================")
    logger.info("Iniciando API IBAMA - Unidades Marítimas")
    logger.info("========================================")
    logger.info(f"Cliente ID: {CLIENT_ID}")
    logger.info(f"Base URL: https://ibama.onrender.com")
    logger.info(f"Docs: https://ibama.onrender.com/v1/docs")
    logger.info(f"ReDoc: https://ibama.onrender.com/v1/redoc")
    logger.info("========================================")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        log_level="info"
    )