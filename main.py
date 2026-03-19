# main.py — API IBAMA com FastAPI — VERSÃO FINAL 2.7.0 (Swagger Fixed, No Logo, Trident Layout)

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

from fastapi import FastAPI, HTTPException, Form, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.openapi.docs import get_swagger_ui_html
from datetime import timedelta, datetime, timezone
from typing import List, Optional
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

# MMSIs de plataformas (para pular Spinergie)
MMSI_PLATAFORMAS = ["538001903", "538003593"]  # P08 e P65

# ATIVOS_AUTORIZADOS
ATIVOS_AUTORIZADOS = {
    "710001720": {
        "nome": "MAERSK VEGA",
        "imo": "9294082",
        "mmsi": "710001720",
        "tipoUnidade": TipoUnidade.EMBARCACAO_EMERGENCIA_APOIO,
        "licencasAutorizadas": ["Ofício nº 163/2024/COPROD/CGMAC/DILIC (SEI 18951971)"],
        "validade": "N/A",
        "observacao": None,
        "latitude": -23.5505,
        "longitude": -46.6333
    },
    "710002450": {
        "nome": "Maersk Ventura",
        "imo": "9294094",
        "mmsi": "710002450",
        "tipoUnidade": TipoUnidade.EMBARCACAO_APOIO,
        "licencasAutorizadas": ["Anuência - Licenciamento Ambiental nº 23341605/2025-Coprod/CGMac/Dilic (SEI 23341605)"],
        "validade": "N/A",
        "observacao": None,
        "latitude": -22.9068,
        "longitude": -43.1729
    },
    "SEASTAR_VIRTUS": {
        "nome": "Seastar Virtus",
        "imo": None,
        "mmsi": None,
        "tipoUnidade": TipoUnidade.EMBARCACAO_APOIO,
        "licencasAutorizadas": ["Ofício nº 95/2026/Coprod/CGMac/Dilic"],
        "validade": "06/04/2026",
        "observacao": None,
        "latitude": -23.2237,
        "longitude": -44.2683
    },
    "PPM1": {
        "nome": "PPM-1",
        "imo": None,
        "mmsi": None,
        "tipoUnidade": TipoUnidade.UNIDADE_PRODUCAO,
        "licencasAutorizadas": ["LO Nº 1572/2020 - 1ª Retificação"],
        "validade": "11/07/2024",
        "observacao": "Renovação solicitada dentro do prazo legal. Aguardando manifestação do IBAMA",
        "latitude": -27.8683,
        "longitude": -48.3563
    },
    "PCE1": {
        "nome": "PCE-1",
        "imo": None,
        "mmsi": None,
        "tipoUnidade": TipoUnidade.UNIDADE_PRODUCAO,
        "licencasAutorizadas": ["LO Nº 1572/2020 - 1ª Retificação"],
        "validade": "11/07/2024",
        "observacao": "Renovação solicitada dentro do prazo legal. Aguardando manifestação do IBAMA",
        "latitude": -27.7211,
        "longitude": -48.3215
    },
    "P65": {
        "nome": "P65",
        "imo": None,
        "mmsi": "538003593",
        "tipoUnidade": TipoUnidade.UNIDADE_PRODUCAO,
        "licencasAutorizadas": ["LO Nº 1572/2020 - 1ª Retificação"],
        "validade": "11/07/2024",
        "observacao": "Renovação solicitada dentro do prazo legal. Aguardando manifestação do IBAMA",
        "latitude": -27.5689,
        "longitude": -48.2954
    },
    "P08": {
        "nome": "P08",
        "imo": None,
        "mmsi": "538001903",
        "tipoUnidade": TipoUnidade.UNIDADE_PRODUCAO,
        "licencasAutorizadas": ["LO Nº 1572/2020 - 1ª Retificação"],
        "validade": "11/07/2024",
        "observacao": "Renovação solicitada dentro do prazo legal. Aguardando manifestação do IBAMA",
        "latitude": -27.6542,
        "longitude": -48.3789
    }
}

logger.info(f"[CONFIG] Environment: {ENVIRONMENT}")
logger.info(f"[CONFIG] JWT_SECRET_KEY: {'✅ Carregado' if JWT_SECRET_KEY else '❌ Não carregado'}")
logger.info(f"[CONFIG] SPINERGIE_API_KEY: {'✅ Carregado' if SPINERGIE_API_KEY else '❌ Não carregado'}")
logger.info(f"[CONFIG] MMSI plataformas: {MMSI_PLATAFORMAS}")
logger.info(f"[CONFIG] Ativos autorizados: {len(ATIVOS_AUTORIZADOS)} (2 vessels + 1 Seastar + 4 plataformas)\n")

# CSS Customizado Trident (encurtado, sem logo)
SWAGGER_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
:root { --te-green: #32AA46; --header-blue: #283C50; --header-border: #1f3041; }
body { font-family: 'Inter', sans-serif !important; background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%) !important; color: #1e293b !important; }
.swagger-ui .topbar { background: var(--header-blue) !important; border-bottom: 1px solid var(--header-border) !important; height: 60px !important; }
.swagger-ui .topbar-wrapper { background: var(--header-blue) !important; padding: 0 20px !important; }
.swagger-ui .topbar .link { color: white !important; font-weight: 500 !important; font-family: 'Inter', sans-serif !important; }
.swagger-ui .info { margin: 50px 0 60px 0 !important; background: white !important; border: 1px solid #e2e8f0 !important; border-radius: 12px !important; padding: 40px !important; font-family: 'Inter', sans-serif !important; box-shadow: 0 1px 3px rgba(0,0,0,0.1) !important; }
.swagger-ui .info hgroup h4 { color: var(--header-blue) !important; font-weight: 700 !important; font-size: 28px !important; }
.swagger-ui .opblock-tag-section .opblock-tag { background: var(--te-green) !important; color: white !important; font-weight: 600 !important; border-radius: 8px !important; padding: 8px 16px !important; font-size: 14px !important; }
.swagger-ui .opblock .opblock-summary .opblock-summary-method { background: var(--te-green) !important; color: white !important; border-radius: 6px !important; }
.swagger-ui .opblock .opblock-summary .opblock-summary-path { color: var(--header-blue) !important; font-weight: 600 !important; }
.swagger-ui .parameter__name { font-weight: 600 !important; color: var(--header-blue) !important; }
.swagger-ui .parameter__type { color: var(--te-green) !important; font-weight: 500 !important; }
.swagger-ui .btn { background: var(--te-green) !important; border: none !important; color: white !important; border-radius: 8px !important; font-weight: 500 !important; transition: all 0.2s !important; }
.swagger-ui .btn:hover { background: #2d9a3e !important; transform: translateY(-1px) !important; }
.swagger-ui .btn:focus { box-shadow: 0 0 0 3px rgba(50, 170, 70, 0.2) !important; outline: none !important; }
.swagger-ui .response-col_status { background: #f0fdf4 !important; color: #166534 !important; border: 1px solid #bbf7d0 !important; }
@media (prefers-color-scheme: dark) { body { background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%) !important; color: #f1f5f9 !important; } .swagger-ui .info { background: #1e293b !important; border-color: #334155 !important; } .swagger-ui .opblock .opblock-summary-path-description-wrapper, .swagger-ui .opblock .opblock-summary { background: #1e293b !important; border-color: #334155 !important; } }
"""

# Função OpenAPI
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="IBAMA Location API - Trident Energy",
        version="2.7.0",
        description="API de localização de embarcações e plataformas para o IBAMA/CGMAC",
        routes=app.routes,
    )
    app.openapi_schema = openapi_schema
    return app.openapi_schema

# Função HTML Swagger UI customizada (simplificada, sem logo base64)
def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url="/v1/openapi.json",
        title="IBAMA API — Trident Energy",
        css_url="data:text/css;base64," + base64.b64encode(SWAGGER_CSS.encode()).decode(),
        swagger_js_url="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js",
        swagger_css_url="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css",
        swagger_ui_parameters={
            "syntaxHighlight.theme": "agate",
            "deepLinking": True,
            "showExtensions": True,
            "defaultModelsExpandDepth": 1,
            "filter": True,
            "maxDisplayedTags": 10
        },
        oauth2_redirect_url="/docs/oauth2-redirect.html",
    )

# Inicialização FastAPI com docs_url=None (evita conflito)
app = FastAPI(
    title="IBAMA Location API",
    description="API de localização de embarcações e plataformas para o IBAMA/CGMAC",
    version="2.7.0",
    docs_url=None,
    redoc_url=None,
    openapi_url="/v1/openapi.json",
    openapi_tags=[
        {
            "name": "Vessels",
            "description": "Endpoints para unidades marítimas e posições"
        },
        {
            "name": "Auth",
            "description": "Autenticação OAuth 2.0"
        }
    ]
)

# Rota manual para Swagger UI (sem conflito com docs_url=None)
@app.get("/v1/docs", include_in_schema=False)
async def swagger_docs():
    return custom_swagger_ui_html()

# Rota para OpenAPI JSON
@app.get("/v1/openapi.json", include_in_schema=False)
async def openapi_json():
    return custom_openapi()

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
        "version": "2.7.0",
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
    """
    logger.info(f"[API] GET /v1/unidades - Client: {client_id}")

    try:
        headers = {
            "Apikey": SPINERGIE_API_KEY,
            "Accept": "application/json",
            "Cache-Control": "no-cache"
        }

        url = f"{SPINERGIE_BASE_URL}/sd/api/vessel/sfm-latest-locations"

        response = requests.get(
            url, headers=headers, timeout=5, verify=False
        )

        unidades = []

        if response.status_code == 200:
            vessels_data = response.json()

            if not isinstance(vessels_data, list):
                vessels_data = vessels_data.get("data", [])

            for vessel in vessels_data:
                mmsi = normalizar_mmsi(vessel.get("mmsi", ""))

                if mmsi in ["710001720", "710002450"]:
                    if mmsi in ATIVOS_AUTORIZADOS:
                        dados = ATIVOS_AUTORIZADOS[mmsi]

                        unidades.append(UnidadeMaritima(
                            nome=dados["nome"],
                            imo=dados.get("imo"),
                            mmsi=mmsi,
                            tipoUnidade=dados["tipoUnidade"],
                            licencasAutorizadas=dados.get("licencasAutorizadas", []),
                            validade=dados.get("validade"),
                            observacao=dados.get("observacao"),
                            disponibilidadeInicio=datetime.now(timezone.utc).isoformat() + "Z",
                            disponibilidadeFim=None
                        ))

        # Adicionar Seastar Virtus
        if "SEASTAR_VIRTUS" in ATIVOS_AUTORIZADOS:
            dados = ATIVOS_AUTORIZADOS["SEASTAR_VIRTUS"]
            unidades.append(UnidadeMaritima(
                nome=dados["nome"],
                imo=dados.get("imo"),
                mmsi=dados.get("mmsi"),
                tipoUnidade=dados["tipoUnidade"],
                licencasAutorizadas=dados.get("licencasAutorizadas", []),
                validade=dados.get("validade"),
                observacao=dados.get("observacao"),
                disponibilidadeInicio=datetime.now(timezone.utc).isoformat() + "Z",
                disponibilidadeFim=None
            ))

        # Adicionar Plataformas
        for plataforma_id in ["PPM1", "PCE1", "P65", "P08"]:
            if plataforma_id in ATIVOS_AUTORIZADOS:
                dados = ATIVOS_AUTORIZADOS[plataforma_id]
                unidades.append(UnidadeMaritima(
                    nome=dados["nome"],
                    imo=dados.get("imo"),
                    mmsi=dados.get("mmsi"),
                    tipoUnidade=dados["tipoUnidade"],
                    licencasAutorizadas=dados.get("licencasAutorizadas", []),
                    validade=dados.get("validade"),
                    observacao=dados.get("observacao"),
                    disponibilidadeInicio=datetime.now(timezone.utc).isoformat() + "Z",
                    disponibilidadeFim=None
                ))

        if unidades:
            return unidades

        return _get_unidades_estaticas()

    except Exception as e:
        logger.error(f"[ERROR] Exception in get_unidades: {str(e)}")
        return _get_unidades_estaticas()


def _get_unidades_estaticas() -> List[UnidadeMaritima]:
    """Fallback estático"""
    unidades = []
    
    for ativo_id, dados in ATIVOS_AUTORIZADOS.items():
        unidades.append(UnidadeMaritima(
            nome=dados["nome"],
            imo=dados.get("imo"),
            mmsi=dados.get("mmsi"),
            tipoUnidade=dados["tipoUnidade"],
            licencasAutorizadas=dados.get("licencasAutorizadas", []),
            validade=dados.get("validade"),
            observacao=dados.get("observacao"),
            disponibilidadeInicio=datetime.now(timezone.utc).isoformat() + "Z",
            disponibilidadeFim=None
        ))
    
    return unidades


@app.get("/v1/posicao", response_model=PosicaoAIS, tags=["Vessels"])
async def get_posicao(
    mmsi: Optional[str] = Query(None, description="Número MMSI (9 dígitos) - Opcional"),
    nome: Optional[str] = Query(None, description="Nome da unidade (plataforma ou vessel) - Opcional"),
    client_id: str = Depends(get_current_client_id)
):
    """
    Obtém a posição de uma embarcação ou plataforma.
    """
    logger.info(f"[API] GET /v1/posicao - MMSI: {mmsi}, Nome: {nome} - Client: {client_id}")

    if mmsi:
        mmsi = normalizar_mmsi(mmsi)

    if mmsi and not nome:
        mmsi_autorizado = ["710001720", "710002450"] + MMSI_PLATAFORMAS
        if mmsi not in mmsi_autorizado:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "not_found",
                    "mmsi": mmsi,
                    "message": "MMSI não encontrado ou não autorizado"
                }
            )

        # Busca em estáticos primeiro (rápido)
        for ativo_id, dados in ATIVOS_AUTORIZADOS.items():
            if dados.get("mmsi") == mmsi:
                logger.info(f"[SUCCESS] MMSI {mmsi} em estáticos: {dados['nome']}")
                return PosicaoAIS(
                    mmsi=mmsi,
                    nome=dados["nome"],
                    latitude=float(dados["latitude"]),
                    longitude=float(dados["longitude"]),
                    timestampAquisicao=datetime.now(timezone.utc).isoformat() + "Z"
                )

        # Spinergie só para vessels
        if mmsi not in MMSI_PLATAFORMAS:
            try:
                headers = {
                    "Apikey": SPINERGIE_API_KEY,
                    "Accept": "application/json",
                    "Cache-Control": "no-cache"
                }

                url = f"{SPINERGIE_BASE_URL}/sd/api/vessel/sfm-latest-locations"

                response = requests.get(
                    url, headers=headers, timeout=5, verify=False
                )

                if response.status_code == 200:
                    vessels_data = response.json()

                    if not isinstance(vessels_data, list):
                        vessels_data = vessels_data.get("data", [])

                    for vessel in vessels_data:
                        vessel_mmsi = normalizar_mmsi(vessel.get("mmsi", ""))

                        if vessel_mmsi == mmsi:
                            latitude = vessel.get("latitude")
                            longitude = vessel.get("longitude")
                            datetime_ms = vessel.get("datetime", int(time.time() * 1000))

                            datetime_obj = datetime.fromtimestamp(
                                datetime_ms / 1000, tz=timezone.utc
                            )

                            nome_unidade = None
                            for ativo_id, dados in ATIVOS_AUTORIZADOS.items():
                                if dados.get("mmsi") == mmsi:
                                    nome_unidade = dados["nome"]
                                    break

                            return PosicaoAIS(
                                mmsi=mmsi,
                                nome=nome_unidade,
                                latitude=float(latitude) if latitude else 0.0,
                                longitude=float(longitude) if longitude else 0.0,
                                timestampAquisicao=datetime_obj.isoformat() + "Z"
                            )

            except Exception as e:
                logger.warning(f"[WARNING] Erro Spinergie MMSI {mmsi}: {str(e)}")

        # Fallback final
        for ativo_id, dados in ATIVOS_AUTORIZADOS.items():
            if dados.get("mmsi") == mmsi:
                logger.info(f"[SUCCESS] Fallback MMSI {mmsi}: {dados['nome']}")
                return PosicaoAIS(
                    mmsi=mmsi,
                    nome=dados["nome"],
                    latitude=float(dados["latitude"]),
                    longitude=float(dados["longitude"]),
                    timestampAquisicao=datetime.now(timezone.utc).isoformat() + "Z"
                )

        raise HTTPException(
            status_code=404,
            detail={
                "error": "not_found",
                "mmsi": mmsi,
                "message": "MMSI autorizado mas sem posição disponível"
            }
        )

    elif nome and not mmsi:
        nome_normalizado = nome.strip().lower()

        for ativo_id, dados in ATIVOS_AUTORIZADOS.items():
            if dados["nome"].lower() == nome_normalizado:
                logger.info(f"[SUCCESS] Nome {nome} encontrado")
                return PosicaoAIS(
                    mmsi=dados.get("mmsi"),
                    nome=dados["nome"],
                    latitude=float(dados.get("latitude", 0.0)),
                    longitude=float(dados.get("longitude", 0.0)),
                    timestampAquisicao=datetime.now(timezone.utc).isoformat() + "Z"
                )

        raise HTTPException(
            status_code=404,
            detail={
                "error": "not_found",
                "nome": nome,
                "message": "Unidade não encontrada ou não autorizada"
            }
        )

    elif mmsi and nome:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "bad_request",
                "message": "Forneça apenas MMSI OU nome, não ambos"
            }
        )

    else:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "bad_request",
                "message": "Forneça pelo menos um parâmetro: mmsi ou nome"
            }
        )


if __name__ == "__main__":
    import uvicorn
    logger.info("\n[INFO] ========== INICIANDO API IBAMA 2.7.0 ==========\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)