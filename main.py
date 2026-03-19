# main.py — API IBAMA com FastAPI — VERSÃO FINAL

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
from models import UnidadeMaritima, PosicaoAIS, TipoUnidade
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

# ✅ ATIVOS AUTORIZADOS — 2 Vessels + Seastar Virtus + 4 Plataformas
ATIVOS_AUTORIZADOS = {
    # ===== VESSELS (2 — SEM MAERSK MAKER) =====
    "710001720": {
        "nome": "MAERSK VEGA",
        "imo": "9294082",
        "mmsi": "710001720",
        "tipoUnidade": TipoUnidade.EMBARCACAO_EMERGENCIA_APOIO,
        "licencasAutorizadas": ["Ofício nº 163/2024/COPROD/CGMAC/DILIC (SEI 18951971)"]
    },
    "710002450": {
        "nome": "Maersk Ventura",
        "imo": "9294094",
        "mmsi": "710002450",
        "tipoUnidade": TipoUnidade.EMBARCACAO_APOIO,
        "licencasAutorizadas": ["Anuência - Licenciamento Ambiental nº 23341605/2025-Coprod/CGMac/Dilic (SEI 23341605)"]
    },

    # ===== SEASTAR VIRTUS =====
    "SEASTAR_VIRTUS": {
        "nome": "Seastar Virtus",
        "imo": None,
        "mmsi": None,
        "tipoUnidade": TipoUnidade.EMBARCACAO_APOIO,
        "licencasAutorizadas": ["Ofício nº 95/2026/Coprod/CGMac/Dilic | Válido até: 06/abril/2026"]
    },
    
    # ===== PLATAFORMAS (4) =====
    "PPM1": {
        "nome": "PPM-1",
        "imo": None,
        "mmsi": None,
        "tipoUnidade": TipoUnidade.UNIDADE_PRODUCAO,
        "licencasAutorizadas": ["LO Nº 1572/2020 - 1ª Retificação | Válido até: 11/Julho/2024 | Renovação solicitada dentro do prazo legal. Aguardando manifestação do IBAMA"]
    },
    "PCE1": {
        "nome": "PCE-1",
        "imo": None,
        "mmsi": None,
        "tipoUnidade": TipoUnidade.UNIDADE_PRODUCAO,
        "licencasAutorizadas": ["LO Nº 1572/2020 - 1ª Retificação | Válido até: 11/Julho/2024 | Renovação solicitada dentro do prazo legal. Aguardando manifestação do IBAMA"]
    },
    "P65": {
        "nome": "P65",
        "imo": None,
        "mmsi": None,
        "tipoUnidade": TipoUnidade.UNIDADE_PRODUCAO,
        "licencasAutorizadas": ["LO Nº 1572/2020 - 1ª Retificação | Válido até: 11/Julho/2024 | Renovação solicitada dentro do prazo legal. Aguardando manifestação do IBAMA"]
    },
    "P08": {
        "nome": "P08",
        "imo": None,
        "mmsi": None,
        "tipoUnidade": TipoUnidade.UNIDADE_PRODUCAO,
        "licencasAutorizadas": ["LO Nº 1572/2020 - 1ª Retificação | Válido até: 11/Julho/2024 | Renovação solicitada dentro do prazo legal. Aguardando manifestação do IBAMA"]
    }
}

logger.info(f"[CONFIG] Environment: {ENVIRONMENT}")
logger.info(f"[CONFIG] JWT_SECRET_KEY: {'✅ Carregado' if JWT_SECRET_KEY else '❌ Não carregado'}")
logger.info(f"[CONFIG] SPINERGIE_API_KEY: {'✅ Carregado' if SPINERGIE_API_KEY else '❌ Não carregado'}")
logger.info(f"[CONFIG] Ativos autorizados: {len(ATIVOS_AUTORIZADOS)} (2 vessels + 1 Seastar + 4 plataformas)\n")

# Inicialização FastAPI
app = FastAPI(
    title="IBAMA Location API",
    description="API de localização de embarcações e plataformas para o IBAMA/CGMAC",
    version="2.1.0",
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
    """Normaliza MMSI removendo casas decimais"""
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
            raise HTTPException(status_code=401, detail={"error": "invalid_token"})

        logger.info(f"[API] Token validado para: {client_id}")
        return client_id

    except jwt.ExpiredSignatureError:
        logger.warning("[API] Token expirado")
        raise HTTPException(status_code=401, detail={"error": "token_expired"})
    except jwt.InvalidTokenError as e:
        logger.error(f"[API] Token inválido: {str(e)}")
        raise HTTPException(status_code=401, detail={"error": "invalid_token"})
    except Exception as e:
        logger.error(f"[API] Erro ao validar token: {str(e)}")
        raise HTTPException(status_code=500, detail={"error": "internal_error"})


# ====== ENDPOINTS ======

@app.get("/")
async def root():
    """Endpoint raiz da API"""
    return {
        "message": "IBAMA Location API",
        "version": "2.1.0",
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
    Lista as unidades marítimas e plataformas autorizadas da Trident Energy.
    
    Retorna:
    - 2 Vessels: MAERSK VEGA, Maersk Ventura
    - 1 Vessel: Seastar Virtus
    - 4 Plataformas: PPM-1, PCE-1, P65, P08
    
    Total: 7 unidades
    """
    logger.info(f"[API] GET /v1/unidades - Client: {client_id}")

    try:
        headers = {
            "Apikey": SPINERGIE_API_KEY,
            "Accept": "application/json"
        }

        url = f"{SPINERGIE_BASE_URL}/sd/api/vessel/sfm-latest-locations"

        logger.debug(f"[DEBUG] Chamando Spinergie: GET {url}")

        response = requests.get(
            url, headers=headers, timeout=60, verify=False
        )

        logger.debug(f"[DEBUG] Status: {response.status_code}")

        unidades = []

        # ===== Processar VESSELS do Spinergie =====
        if response.status_code == 200:
            vessels_data = response.json()

            if not isinstance(vessels_data, list):
                vessels_data = vessels_data.get("data", [])

            logger.debug(f"[DEBUG] Total vessels Spinergie: {len(vessels_data)}")

            for vessel in vessels_data:
                mmsi = normalizar_mmsi(vessel.get("mmsi", ""))

                # Verificar se é um dos vessels autorizados (apenas os 2, não Seastar)
                if mmsi in ["710001720", "710002450"]:
                    if mmsi in ATIVOS_AUTORIZADOS:
                        dados = ATIVOS_AUTORIZADOS[mmsi]

                        logger.info(
                            f"[API] Incluindo vessel: {dados['nome']} (MMSI: {mmsi})"
                        )

                        unidades.append(UnidadeMaritima(
                            nome=dados["nome"],
                            imo=dados.get("imo"),
                            mmsi=mmsi,
                            tipoUnidade=dados["tipoUnidade"],
                            licencasAutorizadas=dados.get("licencasAutorizadas", []),
                            disponibilidadeInicio=datetime.now(timezone.utc).isoformat() + "Z",
                            disponibilidadeFim=None
                        ))

        # ===== Adicionar Seastar Virtus (não está no Spinergie) =====
        if "SEASTAR_VIRTUS" in ATIVOS_AUTORIZADOS:
            dados = ATIVOS_AUTORIZADOS["SEASTAR_VIRTUS"]
            logger.info(f"[API] Incluindo vessel estático: {dados['nome']}")

            unidades.append(UnidadeMaritima(
                nome=dados["nome"],
                imo=dados.get("imo"),
                mmsi=dados.get("mmsi"),
                tipoUnidade=dados["tipoUnidade"],
                licencasAutorizadas=dados.get("licencasAutorizadas", []),
                disponibilidadeInicio=datetime.now(timezone.utc).isoformat() + "Z",
                disponibilidadeFim=None
            ))

        # ===== Adicionar Plataformas (não estão no Spinergie) =====
        for plataforma_id in ["PPM1", "PCE1", "P65", "P08"]:
            if plataforma_id in ATIVOS_AUTORIZADOS:
                dados = ATIVOS_AUTORIZADOS[plataforma_id]
                logger.info(f"[API] Incluindo plataforma: {dados['nome']}")

                unidades.append(UnidadeMaritima(
                    nome=dados["nome"],
                    imo=dados.get("imo"),
                    mmsi=dados.get("mmsi"),
                    tipoUnidade=dados["tipoUnidade"],
                    licencasAutorizadas=dados.get("licencasAutorizadas", []),
                    disponibilidadeInicio=datetime.now(timezone.utc).isoformat() + "Z",
                    disponibilidadeFim=None
                ))

        if unidades:
            logger.info(f"[API] Retornando {len(unidades)} unidades autorizadas")
            return unidades

        logger.warning("[WARNING] Nenhum ativo autorizado encontrado")
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
    """Retorna dados estáticos como fallback"""
    unidades = []
    
    for ativo_id, dados in ATIVOS_AUTORIZADOS.items():
        unidades.append(UnidadeMaritima(
            nome=dados["nome"],
            imo=dados.get("imo"),
            mmsi=dados.get("mmsi"),
            tipoUnidade=dados["tipoUnidade"],
            licencasAutorizadas=dados.get("licencasAutorizadas", []),
            disponibilidadeInicio=datetime.now(timezone.utc).isoformat() + "Z",
            disponibilidadeFim=None
        ))
    
    return unidades


@app.get("/v1/posicao/{mmsi}", response_model=PosicaoAIS, tags=["Vessels"])
async def get_posicao(
    mmsi: str,
    client_id: str = Depends(get_current_client_id)
):
    """
    Obtém a posição de uma embarcação pelo MMSI.
    
    Apenas MMSIs autorizados Trident são aceitos:
    - 710001720 (MAERSK VEGA)
    - 710002450 (Maersk Ventura)
    
    NOTA: Seastar Virtus e plataformas não possuem MMSI (retornarão 404)
    """
    logger.info(f"[API] GET /v1/posicao/{mmsi} - Client: {client_id}")

    mmsi = normalizar_mmsi(mmsi)

    # Validar se é um MMSI autorizado (apenas os 2 vessels com MMSI)
    if mmsi not in ["710001720", "710002450"]:
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
        headers = {
            "Apikey": SPINERGIE_API_KEY,
            "Accept": "application/json"
        }

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

            logger.debug(f"[DEBUG] Total vessels: {len(vessels_data)}")

            for vessel in vessels_data:
                vessel_mmsi = normalizar_mmsi(vessel.get("mmsi", ""))

                logger.debug(f"[DEBUG] Comparando: {vessel_mmsi} == {mmsi} ?")

                if vessel_mmsi == mmsi:
                    latitude = vessel.get("latitude")
                    longitude = vessel.get("longitude")
                    datetime_ms = vessel.get("datetime", int(time.time() * 1000))

                    datetime_obj = datetime.fromtimestamp(
                        datetime_ms / 1000, tz=timezone.utc
                    )

                    logger.info(
                        f"[SUCCESS] Posição encontrada MMSI {mmsi}: "
                        f"lat={latitude}, lon={longitude}"
                    )

                    return PosicaoAIS(
                        mmsi=mmsi,
                        latitude=float(latitude) if latitude else 0.0,
                        longitude=float(longitude) if longitude else 0.0,
                        timestampAquisicao=datetime_obj.isoformat() + "Z"
                    )

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
        raise HTTPException(status_code=504, detail={"error": "timeout"})
    except requests.ConnectionError as e:
        logger.error(f"[ERROR] Connection Error: {str(e)}")
        raise HTTPException(status_code=503, detail={"error": "connection_error"})
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
    logger.info("\n[INFO] ========== INICIANDO API IBAMA 2.1 ==========\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)