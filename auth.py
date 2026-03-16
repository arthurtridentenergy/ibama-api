# auth.py — Autenticação OAuth 2.0 — VERSÃO COM LOGGING MELHORADO

import os
from datetime import datetime, timedelta, timezone
import jwt
from dotenv import load_dotenv
import logging

load_dotenv()

# Configuração de logging
logger = logging.getLogger(__name__)

# Carrega JWT_SECRET_KEY
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
ALGORITHM = "HS256"

# Credenciais do cliente
CLIENT_ID = os.getenv("CLIENT_ID", "ibama_client_id")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

logger.info(f"[AUTH] JWT_SECRET_KEY carregado: {'✅' if JWT_SECRET_KEY else '❌'}")
logger.info(f"[AUTH] CLIENT_ID: {CLIENT_ID}")
logger.info(f"[AUTH] CLIENT_SECRET: {'✅' if CLIENT_SECRET else '❌'}\n")


def authenticate_client(client_id: str, client_secret: str) -> bool:
    """Valida credenciais de autenticação"""
    
    if not CLIENT_ID or not CLIENT_SECRET:
        logger.error("[AUTH ERROR] CLIENT_ID ou CLIENT_SECRET não configurados!")
        return False
    
    id_match = client_id == CLIENT_ID
    secret_match = client_secret == CLIENT_SECRET
    
    logger.debug(f"[AUTH] Validando client_id: {client_id} == {CLIENT_ID} → {id_match}")
    logger.debug(f"[AUTH] Validando client_secret: ******* (length={len(client_secret)}) → {secret_match}")
    
    return id_match and secret_match


def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    """Cria um token JWT com expiração"""
    
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(hours=1)

    to_encode.update({"exp": expire.timestamp()})
    
    logger.info(f"[AUTH] Criando token para: {to_encode.get('sub')}")
    logger.debug(f"[AUTH] JWT_SECRET_KEY (primeiros 20 chars): {JWT_SECRET_KEY[:20] if JWT_SECRET_KEY else 'NONE'}...")
    logger.debug(f"[AUTH] Expiração (timestamp): {expire.timestamp()}")
    
    try:
        encoded_jwt = jwt.encode(
            to_encode,
            JWT_SECRET_KEY,
            algorithm=ALGORITHM
        )
        logger.info(f"[AUTH] Token criado com sucesso")
        return encoded_jwt
    except Exception as e:
        logger.error(f"[AUTH ERROR] Erro ao criar token: {str(e)}")
        raise


def verify_token(token: str) -> dict:
    """Verifica e decodifica um token JWT"""
    
    logger.debug(f"[AUTH] Verificando token (primeiros 50 chars): {token[:50]}...")
    logger.debug(f"[AUTH] JWT_SECRET_KEY (primeiros 20 chars): {JWT_SECRET_KEY[:20] if JWT_SECRET_KEY else 'NONE'}...")
    
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[ALGORITHM]
        )
        logger.info(f"[AUTH] Token validado com sucesso para: {payload.get('sub')}")
        return payload
    
    except jwt.ExpiredSignatureError:
        logger.warning("[AUTH WARNING] Token expirado")
        raise
    
    except jwt.InvalidTokenError as e:
        logger.error(f"[AUTH ERROR] Token inválido: {str(e)}")
        raise
    
    except Exception as e:
        logger.error(f"[AUTH ERROR] Erro ao verificar token: {str(e)}")
        raise