# main.py — API IBAMA com FastAPI — VERSÃO FINAL CORRIGIDA

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

from fastapi import FastAPI, HTTPException, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import timedelta, datetime, timezone
from typing import List
import os
import jwt
import json
import logging
import time

from auth import authenticate_client, create_access_token
from models import UnidadeMaritima, PosicaoAIS
from data import get_all_vessels, get_vessel_position
from dotenv import load_dotenv

load_dotenv()

# Configuração de logging
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# Configurações
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
ALGORITHM = "HS256"
CLIENT_ID = os.getenv("CLIENT_ID", "ibama_client_id")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
SPINERGIE_BASE_URL = os.getenv(
    "SPINERGIE_BASE_URL",
    "https://trident-energy-br.spinergie.com"
)
SPINERGIE_API_KEY = os.getenv("SPINERGIE_API_KEY", "")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# ✅ MMSIs AUTORIZADOS — Apenas embarcações Trident
MMSI_AUTORIZADOS = {
    "710001720": {
        "nome": "MAERSK VEGA",
        "imo": "9294082",
        "tipoUnidade": "EMBARCACAO_EMERGENCIA_APOIO"
    },
    "710005854": {
        "nome": "MAERSK MAKER",
        "imo": "9765483",
        "tipoUnidade": "EMBARCACAO_APOIO"
    },
    "710002450": {
        "nome": "Maersk Ventura",
        "imo": "9294094",
        "tipoUnidade": "EMBARCACAO_APOIO"
    }
}

logger.info(f"[CONFIG] Environment: {ENVIRONMENT}")
logger.info(f"[CONFIG] JWT_SECRET_KEY: {'✅ Carregado' if JWT_SECRET_KEY else '❌ Não carregado'}")
logger.info(f"[CONFIG] SPINERGIE_API_KEY: {'✅ Carregado' if SPINERGIE_API_KEY else '❌ Não carregado'}")
logger.info(f"[CONFIG] MMSIs autorizados: {list(MMSI_AUTORIZADOS.keys())}\n")

# Inicialização FastAPI
app = FastAPI(
    title="IBAMA Location API",
    description="API de localização de embarcações para o IBAMA/CGMAC",
    version="1.0.0",
    docs_url="/v1/docs",
    openapi_url="/v1/openapi.json"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Segurança
security = HTTPBearer()


def normalizar_mmsi(mmsi_raw) -> str:
    """
    Normaliza o MMSI removendo casas decimais desnecessárias.
    Spinergie retorna float: 710005854.0 → deve ser '710005854'
    """
    try:
        return str(int(float(str(mmsi_raw))))
    except Exception:
        return str(mmsi_raw).strip()


def get_current_client_id(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:
    """Valida JWT token do header Authorization"""
    token = credentials.credentials

    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
        client_id: str = payload.get("sub")

        if client_id is None:
            raise HTTPException(
                status_code=401,
                detail={"error": "invalid_token"}
            )

        logger.info(f"[API] Token validado para: {client_id}")
        return client_id

    except jwt.ExpiredSignatureError:
        logger.warning("[API] Token expirado")
        raise HTTPException(
            status_code=401,
            detail={"error": "token_expired"}
        )
    except jwt.InvalidTokenError as e:
        logger.error(f"[API] Token inválido: {str(e)}")
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_token"}
        )
    except Exception as e:
        logger.error(f"[API] Erro ao validar token: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error"}
        )


# ──────────────────────────────────────────────
# ENDPOINTS
# ──────────────────────────────────────────────

@app.get("/")
async def root():
    """Endpoint raiz da API"""
    return {
        "message": "IBAMA Location API",
        "version": "1.0.0",
        "docs": "/v1/docs",
        "environment": ENVIRONMENT
    }


@app.get("/health")
async def health_check():
    """Health check da API"""
    return {
        "status": "ok",
        "environment": ENVIRONMENT,
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
    }


@app.post("/auth/token")
async def get_token(
    grant_type: str = Form(...),
    client_id: str = Form(...),
    client_secret: str = Form(...)
):
    """Endpoint de autenticação OAuth 2.0 Client Credentials"""
    if grant_type != "client_credentials":
        raise HTTPException(
            status_code=400,
            detail={"error": "unsupported_grant_type"}
        )

    if not authenticate_client(client_id, client_secret):
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_client"}
        )

    access_token = create_access_token(
        data={"sub": client_id},
        expires_delta=timedelta(hours=1)
    )

    logger.info(f"[AUTH] Token gerado para: {client_id}")

    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": 3600
    }


@app.get("/v1/unidades", response_model=List[UnidadeMaritima], tags=["Vessels"])
async def get_unidades(client_id: str = Depends(get_current_client_id)):
    """
    Lista as unidades marítimas autorizadas da Trident Energy.

    Retorna APENAS as 3 embarcações cadastradas:
    - MAERSK VEGA (710001720)
    - MAERSK MAKER (710005854)
    - Maersk Ventura (710002450)
    """
    logger.info(f"[API] GET /v1/unidades - Client: {client_id}")

    try:
        # ✅ Headers corretos do Spinergie (case-sensitive)
        headers = {
            "Apikey": SPINERGIE_API_KEY,
            "Accept": "application/json"
        }

        # ✅ Endpoint correto para posições mais recentes
        url = f"{SPINERGIE_BASE_URL}/sd/api/vessel/sfm-latest-locations"

        logger.debug(f"[DEBUG] Chamando Spinergie: GET {url}")

        response = requests.get(
            url, headers=headers, timeout=60, verify=False
        )

        logger.debug(f"[DEBUG] Status: {response.status_code}")

        if response.status_code == 200:
            vessels_data = response.json()

            if not isinstance(vessels_data, list):
                vessels_data = vessels_data.get("data", [])

            logger.debug(
                f"[DEBUG] Total vessels Spinergie: {len(vessels_data)}"
            )

            unidades = []

            for vessel in vessels_data:
                # ✅ Normaliza MMSI (remove .0 do float)
                mmsi = normalizar_mmsi(vessel.get("mmsi", ""))

                # ✅ Filtra APENAS os MMSIs autorizados Trident
                if mmsi not in MMSI_AUTORIZADOS:
                    logger.debug(
                        f"[DEBUG] MMSI {mmsi} ignorado (não autorizado)"
                    )
                    continue

                dados_fixos = MMSI_AUTORIZADOS[mmsi]

                logger.info(
                    f"[API] Incluindo vessel autorizado: "
                    f"{dados_fixos['nome']} (MMSI: {mmsi})"
                )

                unidades.append(UnidadeMaritima(
                    nome=dados_fixos["nome"],
                    imo=dados_fixos["imo"],
                    mmsi=mmsi,
                    tipoUnidade=dados_fixos["tipoUnidade"],
                    licencasAutorizadas=[],
                    disponibilidadeInicio=datetime.now(
                        timezone.utc
                    ).isoformat() + "Z",
                    disponibilidadeFim=None
                ))

            if unidades:
                logger.info(
                    f"[API] Retornando {len(unidades)} unidades autorizadas"
                )
                return unidades

            # Fallback: Spinergie não retornou os MMSIs esperados
            logger.warning(
                "[WARNING] Nenhum MMSI autorizado encontrado no Spinergie. "
                "Usando dados estáticos."
            )
            return _get_unidades_estaticas()

        else:
            logger.error(
                f"[ERROR] Spinergie Status {response.status_code}: "
                f"{response.text[:200]}"
            )
            return _get_unidades_estaticas()

    except requests.Timeout:
        logger.error("[ERROR] Timeout ao chamar Spinergie")
        return _get_unidades_estaticas()

    except requests.ConnectionError as e:
        logger.error(f"[ERROR] Connection Error: {e}")
        return _get_unidades_estaticas()

    except Exception as e:
        logger.error(f"[ERROR] Exception: {str(e)}")
        return _get_unidades_estaticas()


def _get_unidades_estaticas() -> List[UnidadeMaritima]:
    """
    Retorna os dados estáticos das embarcações autorizadas.
    Usado como fallback quando Spinergie não responde.
    """
    return [
        UnidadeMaritima(
            nome=dados["nome"],
            imo=dados["imo"],
            mmsi=mmsi,
            tipoUnidade=dados["tipoUnidade"],
            licencasAutorizadas=[],
            disponibilidadeInicio=datetime.now(timezone.utc).isoformat() + "Z",
            disponibilidadeFim=None
        )
        for mmsi, dados in MMSI_AUTORIZADOS.items()
    ]


@app.get("/v1/posicao/{mmsi}", response_model=PosicaoAIS, tags=["Vessels"])
async def get_posicao(
    mmsi: str,
    client_id: str = Depends(get_current_client_id)
):
    """
    Obtém a posição de uma embarcação pelo MMSI.

    Apenas MMSIs autorizados Trident são aceitos:
    - 710001720 (MAERSK VEGA)
    - 710005854 (MAERSK MAKER)
    - 710002450 (Maersk Ventura)
    """
    logger.info(f"[API] GET /v1/posicao/{mmsi} - Client: {client_id}")

    # ✅ Normaliza o MMSI recebido
    mmsi = normalizar_mmsi(mmsi)

    # ✅ Valida se é um MMSI autorizado
    if mmsi not in MMSI_AUTORIZADOS:
        logger.warning(f"[WARNING] MMSI {mmsi} não autorizado")
        raise HTTPException(
            status_code=404,
            detail={
                "error": "not_found",
                "mmsi": mmsi,
                "message": "MMSI não encontrado ou não autorizado"
            }
        )

    try:
        # ✅ Headers corretos do Spinergie
        headers = {
            "Apikey": SPINERGIE_API_KEY,
            "Accept": "application/json"
        }

        # ✅ Endpoint correto para últimas posições
        url = f"{SPINERGIE_BASE_URL}/sd/api/vessel/sfm-latest-locations"

        logger.debug(f"[DEBUG] Buscando MMSI {mmsi} em: {url}")

        response = requests.get(
            url, headers=headers, timeout=60, verify=False
        )

        logger.debug(f"[DEBUG] Status Spinergie: {response.status_code}")

        if response.status_code == 200:
            vessels_data = response.json()

            if not isinstance(vessels_data, list):
                vessels_data = vessels_data.get("data", [])

            logger.debug(
                f"[DEBUG] Total vessels recebidos: {len(vessels_data)}"
            )

            for vessel in vessels_data:
                # ✅ Normaliza MMSI do Spinergie (remove .0)
                vessel_mmsi = normalizar_mmsi(vessel.get("mmsi", ""))

                logger.debug(
                    f"[DEBUG] Comparando: {vessel_mmsi} == {mmsi} ?"
                )

                if vessel_mmsi == mmsi:
                    latitude = vessel.get("latitude")
                    longitude = vessel.get("longitude")
                    datetime_ms = vessel.get(
                        "datetime", int(time.time() * 1000)
                    )

                    # ✅ Converte timestamp de ms para ISO 8601
                    datetime_obj = datetime.fromtimestamp(
                        datetime_ms / 1000,
                        tz=timezone.utc
                    )

                    logger.info(
                        f"[SUCCESS] Posição encontrada para MMSI {mmsi}: "
                        f"lat={latitude}, lon={longitude}"
                    )

                    return PosicaoAIS(
                        mmsi=mmsi,
                        latitude=float(latitude) if latitude else 0.0,
                        longitude=float(longitude) if longitude else 0.0,
                        timestampAquisicao=datetime_obj.isoformat() + "Z"
                    )

            # MMSI autorizado mas não encontrado no Spinergie
            logger.warning(
                f"[WARNING] MMSI {mmsi} autorizado mas não retornado "
                f"pelo Spinergie"
            )
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "not_found",
                    "mmsi": mmsi,
                    "message": "Embarcação autorizada mas sem posição disponível"
                }
            )

        elif response.status_code == 401:
            logger.error("[ERROR] Spinergie 401 - Apikey inválida")
            raise HTTPException(
                status_code=502,
                detail={"error": "spinergie_auth_error"}
            )

        else:
            logger.error(
                f"[ERROR] Spinergie Status {response.status_code}: "
                f"{response.text[:200]}"
            )
            raise HTTPException(
                status_code=502,
                detail={"error": "spinergie_error"}
            )

    except requests.Timeout:
        logger.error("[ERROR] Timeout ao chamar Spinergie")
        raise HTTPException(
            status_code=504,
            detail={"error": "timeout"}
        )

    except requests.ConnectionError as e:
        logger.error(f"[ERROR] Connection Error: {str(e)}")
        raise HTTPException(
            status_code=503,
            detail={"error": "connection_error"}
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"[ERROR] Exception inesperada: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error"}
        )


if __name__ == "__main__":
    import uvicorn
    logger.info("\n[INFO] ========== INICIANDO API IBAMA ==========\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)