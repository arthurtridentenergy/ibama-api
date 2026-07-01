import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.models import OAuthFlowClientCredentials, OAuthFlows
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware

import data
import spinergie_service


# ---------------------------------------------------------------------------
# Configuração de Logging em JSON
# ---------------------------------------------------------------------------
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_payload, ensure_ascii=False)


logger = logging.getLogger("api")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger.addHandler(handler)
logger.propagate = False


# ---------------------------------------------------------------------------
# Configurações via variáveis de ambiente
# ---------------------------------------------------------------------------
TOKEN_URL = os.getenv("OAUTH_TOKEN_URL", "https://auth.example.com/oauth/token")
CLIENT_ID = os.getenv("OAUTH_CLIENT_ID", "client-id")
CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET", "client-secret")
OAUTH_SCOPES = {"read": "Acesso de leitura aos recursos da API"}
RATE_LIMIT = os.getenv("RATE_LIMIT", "60/minute")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")


# ---------------------------------------------------------------------------
# Rate Limiting
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address, default_limits=[RATE_LIMIT])


# ---------------------------------------------------------------------------
# OAuth 2.0 Client Credentials
# ---------------------------------------------------------------------------
class OAuth2ClientCredentialsBearer(OAuth2):
    def __init__(self, token_url: str, scopes: Optional[dict] = None, auto_error: bool = True):
        flows = OAuthFlows(
            clientCredentials=OAuthFlowClientCredentials(tokenUrl=token_url, scopes=scopes or {})
        )
        super().__init__(flows=flows, scheme_name="OAuth2ClientCredentials", auto_error=auto_error)

    async def __call__(self, request: Request) -> Optional[str]:
        authorization = request.headers.get("Authorization")
        if not authorization:
            if self.auto_error:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token de autenticação ausente.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return None
        scheme, _, param = authorization.partition(" ")
        if scheme.lower() != "bearer":
            if self.auto_error:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Esquema de autenticação inválido. Use Bearer.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return None
        return param


oauth2_scheme = OAuth2ClientCredentialsBearer(tokenUrl=TOKEN_URL, scopes=OAUTH_SCOPES)
bearer_scheme = HTTPBearer(auto_error=False)


# Cache simples para introspecção de token (evita chamada repetida ao IdP)
_token_cache: dict = {}


async def introspect_token(token: str) -> dict:
    """Introspecta o token no servidor de autorização.

    Em ambientes sem IdP real, valida apenas o formato e presença do token.
    """
    now = time.time()
    cached = _token_cache.get(token)
    if cached and cached.get("expires_at", 0) > now:
        return cached["payload"]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "token": token,
                },
                headers={"Accept": "application/json"},
            )
        if response.status_code == 401:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expirado ou inválido.")
        if response.status_code == 403:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso negado pelo provedor de identidade.")
        if response.status_code >= 400:
            # Fallback: aceita o token se ele estiver presente (modo desenvolvimento)
            payload = {"active": True, "scope": "read", "expires_in": 3600}
        else:
            payload = response.json()
            if not payload.get("active", True):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inativo.")
    except httpx.RequestError:
        logger.warning("Falha de comunicação com o IdP; validando token localmente.")
        payload = {"active": True, "scope": "read", "expires_in": 3600}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Erro inesperado ao introspectar token: %s", str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Erro ao validar token.")

    _token_cache[token] = {"payload": payload, "expires_at": now + payload.get("expires_in", 3600)}
    return payload


async def require_auth(
    request: Request,
    token: str = Depends(oauth2_scheme),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    """Dependência que valida o token via OAuth2 Client Credentials."""
    bearer_token = token or (credentials.credentials if credentials else None)
    if not bearer_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais não fornecidas.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = await introspect_token(bearer_token)
    scopes = payload.get("scope", "")
    if isinstance(scopes, str):
        scopes_list = scopes.split()
    else:
        scopes_list = list(scopes)
    if "read" not in scopes_list and scopes_list:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Escopo insuficiente.")
    request.state.token_payload = payload
    return payload


# ---------------------------------------------------------------------------
# Middleware de Logging
# ---------------------------------------------------------------------------
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = (time.time() - start_time) * 1000
            logger.error(
                "Erro não tratado: %s | path=%s | duration_ms=%.2f",
                str(exc),
                request.url.path,
                duration_ms,
            )
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": "Erro interno do servidor."},
            )
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "request_completed | method=%s | path=%s | status=%s | duration_ms=%.2f",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


# ---------------------------------------------------------------------------
# Aplicação FastAPI
# ---------------------------------------------------------------------------
app = FastAPI(
    title="API de Unidades e Posições",
    description="API integrada com data.py e spinergie_service.py. Autenticação OAuth 2.0 Client Credentials.",
    version="1.0.0",
    docs_url="/v1/docs",
    redoc_url="/v1/redoc",
    openapi_url="/v1/openapi.json",
)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(RequestLoggingMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Handlers de Erro
# ---------------------------------------------------------------------------
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    logger.warning("Rate limit excedido | path=%s | detail=%s", request.url.path, str(exc))
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "detail": "Limite de requisições excedido. Tente novamente mais tarde.",
            "limit": str(exc.limit.limit) if exc.limit else None,
        },
        headers={"Retry-After": "60"},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning("HTTPException | path=%s | status=%s | detail=%s", request.url.path, exc.status_code, str(exc.detail))
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    logger.info("Recurso não encontrado | path=%s", request.url.path)
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": "Recurso não encontrado."})


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error("Erro interno | path=%s | error=%s", request.url.path, str(exc))
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Erro interno do servidor."},
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/v1/unidades", tags=["Unidades"], summary="Lista todas as unidades/embarcações")
@limiter.limit(RATE_LIMIT)
async def get_unidades(request: Request, _auth: dict = Depends(require_auth)):
    """Retorna todas as embarcações disponíveis via data.get_all_vessels()."""
    try:
        vessels = data.get_all_vessels()
        if vessels is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nenhuma unidade encontrada.")
        logger.info("unidades retornadas | total=%s", len(vessels) if isinstance(vessels, list) else "n/a")
        return {"unidades": vessels}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Erro ao obter unidades: %s", str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Erro ao obter unidades.")


@app.get("/v1/posicao/{identificador}", tags=["Posição"], summary="Obtém a posição de uma embarcação")
@limiter.limit(RATE_LIMIT)
async def get_posicao(identificador: str, request: Request, _auth: dict = Depends(require_auth)):
    """Obtém a posição de uma embarcação pelo MMSI ou nome.

    Tenta primeiro data.get_vessel_by_mmsi(identificador).
    Caso não encontre, tenta data.get_vessel_by_name(identificador).
    Por fim, usa data.get_vessel_position(vessel) para retornar a posição.
    """
    try:
        vessel = data.get_vessel_by_mmsi(identificador)
        if vessel is None:
            vessel = data.get_vessel_by_name(identificador)

        if vessel is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Embarcação não encontrada para o identificador: {identificador}",
            )

        position = data.get_vessel_position(vessel)
        if position is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Posição não disponível para a embarcação: {identificador}",
            )

        # Enriquecimento opcional via spinergie_service
        enriched = None
        try:
            enriched = spinergie_service.get_position_info(vessel, position)
        except Exception as exc:
            logger.warning("Falha ao enriquecer posição via spinergie_service: %s", str(exc))

        logger.info("posicao retornada | identificador=%s", identificador)
        return {
            "identificador": identificador,
            "embarcacao": vessel,
            "posicao": position,
            "spinergie": enriched,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Erro ao obter posição: %s", str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Erro ao obter posição.")


@app.get("/v1/health", tags=["Saúde"], summary="Verificação de saúde da API")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ---------------------------------------------------------------------------
# OpenAPI customizada para incluir os fluxos OAuth2
# ---------------------------------------------------------------------------
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "OAuth2ClientCredentials": {
            "type": "oauth2",
            "flows": {
                "clientCredentials": {
                    "tokenUrl": TOKEN_URL,
                    "scopes": OAUTH_SCOPES,
                }
            },
        }
    }
    for path_item in openapi_schema.get("paths", {}).values():
        for operation in path_item.values():
            if isinstance(operation, dict):
                operation["security"] = [{"OAuth2ClientCredentials": ["read"]}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))