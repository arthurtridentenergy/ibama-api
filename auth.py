import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

load_dotenv()

logger = logging.getLogger(__name__)

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
CLIENT_ID = os.getenv("CLIENT_ID", "ibama_client")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

logger.info("[AUTH] Módulo de autenticação carregado")
logger.info("[AUTH] JWT_SECRET_KEY configurada: %s", bool(JWT_SECRET_KEY))
logger.info("[AUTH] CLIENT_SECRET configurada: %s", bool(CLIENT_SECRET))
logger.info("[AUTH] CLIENT_ID: %s", CLIENT_ID)
logger.info("[AUTH] ALGORITHM: %s", ALGORITHM)
logger.info("[AUTH] ACCESS_TOKEN_EXPIRE_MINUTES: %s", ACCESS_TOKEN_EXPIRE_MINUTES)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


def _is_configured() -> bool:
    """Verifica se as variáveis obrigatórias para autenticação estão configuradas."""
    return bool(JWT_SECRET_KEY) and bool(CLIENT_ID) and bool(CLIENT_SECRET)


def authenticate_client(client_id: str, client_secret: str) -> bool:
    """
    Valida as credenciais do cliente OAuth 2.0 (client_id e client_secret).

    Args:
        client_id: Identificador do cliente.
        client_secret: Segredo do cliente.

    Returns:
        True se as credenciais forem válidas, False caso contrário.
    """
    logger.debug("[AUTH] Tentativa de autenticação para client_id: %s", client_id)

    if not _is_configured():
        logger.error(
            "[AUTH ERROR] CLIENT_ID, CLIENT_SECRET ou JWT_SECRET_KEY não configurados"
        )
        return False

    id_match = client_id == CLIENT_ID
    secret_match = client_secret == CLIENT_SECRET

    logger.debug("[AUTH] client_id coincide: %s", id_match)
    logger.debug("[AUTH] client_secret coincide: %s", secret_match)

    if id_match and secret_match:
        logger.info("[AUTH] Autenticação bem-sucedida para client_id: %s", client_id)
        return True

    logger.warning("[AUTH] Falha na autenticação para client_id: %s", client_id)
    return False


def create_access_token(
    data: Dict[str, Any], expires_delta: Optional[timedelta] = None
) -> str:
    """
    Cria um access token JWT OAuth 2.0 com expiração.

    Args:
        data: Payload base a ser codificado no token.
        expires_delta: Tempo adicional até a expiração. Padrão é 60 minutos.

    Returns:
        Token JWT codificado.
    """
    if not JWT_SECRET_KEY:
        logger.error("[AUTH ERROR] JWT_SECRET_KEY não configurada; não é possível criar token")
        raise RuntimeError("JWT_SECRET_KEY não configurada")

    to_encode = data.copy()

    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update(
        {
            "exp": expire,
            "iat": now,
            "type": "access_token",
        }
    )

    subject = to_encode.get("sub")
    logger.info(
        "[AUTH] Criando access token JWT para subject: %s | expiração: %s",
        subject,
        expire.isoformat(),
    )
    logger.debug("[AUTH] ALGORITHM: %s", ALGORITHM)

    try:
        encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=ALGORITHM)
        logger.info("[AUTH] Access token JWT criado com sucesso")
        return encoded_jwt
    except Exception as exc:
        logger.exception("[AUTH ERROR] Erro ao criar access token JWT: %s", exc)
        raise


def verify_token(token: str) -> Dict[str, Any]:
    """
    Verifica e decodifica um access token JWT OAuth 2.0.

    Args:
        token: Token JWT a ser verificado.

    Returns:
        Payload decodificado do token.

    Raises:
        HTTPException: 401 para token expirado ou inválido; 500 para erros inesperados.
    """
    if not JWT_SECRET_KEY:
        logger.error("[AUTH ERROR] JWT_SECRET_KEY não configurada; não é possível verificar token")
        raise RuntimeError("JWT_SECRET_KEY não configurada")

    logger.debug("[AUTH] Verificando token JWT")

    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
        logger.info(
            "[AUTH] Token JWT verificado com sucesso para subject: %s",
            payload.get("sub"),
        )
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("[AUTH WARNING] Token JWT expirado")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as exc:
        logger.warning("[AUTH WARNING] Token JWT inválido: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as exc:
        logger.exception("[AUTH ERROR] Erro inesperado ao verificar token JWT: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao verificar token",
        )


def get_current_token_payload(token: str = Depends(oauth2_scheme)) -> Dict[str, Any]:
    """
    Retorna o payload de um token Bearer presente no header Authorization.

    Pode ser usada como dependência FastAPI para proteger rotas OAuth 2.0.
    """
    if not token:
        logger.warning("[AUTH WARNING] Requisição sem token Bearer")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify_token(token)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    client_id = os.getenv("CLIENT_ID", "ibama_client")
    client_secret = os.getenv("CLIENT_SECRET", "secret_exemplo")

    if authenticate_client(client_id, client_secret):
        token = create_access_token({"sub": client_id})
        print(f"Token gerado: {token}")
        payload = verify_token(token)
        print(f"Payload decodificado: {payload}")
    else:
        print("Falha na autenticação do cliente")