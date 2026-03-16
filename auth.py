# auth.py — Autenticação OAuth 2.0 — VERSÃO CORRIGIDA

import os
from datetime import datetime, timedelta, timezone
import jwt
from dotenv import load_dotenv

load_dotenv()

# Carrega JWT_SECRET com valor padrão se não existir
JWT_SECRET = os.getenv("JWT_SECRET") or "default-jwt-secret-change-in-production"
ALGORITHM = "HS256"

# Credenciais do cliente
CLIENT_ID = os.getenv("CLIENT_ID") or "ibama_client_id"
CLIENT_SECRET = os.getenv("CLIENT_SECRET") or "ibama_client_secret"

print(f"[AUTH] JWT_SECRET: {'✅ Carregado' if os.getenv('JWT_SECRET') else '⚠️ Usando padrão'}")
print(f"[AUTH] CLIENT_ID: {CLIENT_ID}")
print(f"[AUTH] CLIENT_SECRET: {'✅ Carregado' if os.getenv('CLIENT_SECRET') else '⚠️ Usando padrão'}\n")


def authenticate_client(client_id: str, client_secret: str) -> bool:
    """Valida credenciais de autenticação."""
    id_match = client_id == CLIENT_ID
    secret_match = client_secret == CLIENT_SECRET
    
    print(f"[AUTH] client_id match: {id_match}")
    print(f"[AUTH] client_secret match: {secret_match}")
    
    return id_match and secret_match


def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    """Cria um token JWT com expiração."""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(hours=1)

    to_encode.update({"exp": expire.timestamp()})
    
    print(f"[AUTH] Token criado para: {to_encode.get('sub')}")
    
    encoded_jwt = jwt.encode(
        to_encode,
        JWT_SECRET,
        algorithm=ALGORITHM
    )

    return encoded_jwt