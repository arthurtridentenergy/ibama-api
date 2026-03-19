# main.py — API IBAMA com FastAPI — VERSÃO FINAL 2.6.0 (Swagger Fixed + Trident Layout)

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
import base64  # Para logo SVG

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

# MMSIs de plataformas (para pular Spinergie e melhorar tempo)
MMSI_PLATAFORMAS = ["538001903", "538003593"]  # P08 e P65

# ATIVOS_AUTORIZADOS — Com MMSIs para P08 e P65
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

# Inicialização FastAPI SEM docs_url (para evitar conflito)
app = FastAPI(
    title="IBAMA Location API",
    description="API de localização de embarcações e plataformas para o IBAMA/CGMAC",
    version="2.6.0",
    docs_url=None,  # Desabilita docs nativo para custom
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


# CSS Customizado para Swagger UI (Trident Energy Design System - Encurtado para evitar erros)
SWAGGER_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {
  --te-green: #32AA46;
  --header-blue: #283C50;
  --header-border: #1f3041;
}

body { font-family: 'Inter', sans-serif !important; background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%) !important; color: #1e293b !important; }

.swagger-ui .topbar { background: var(--header-blue) !important; border-bottom: 1px solid var(--header-border) !important; height: 60px !important; }

.swagger-ui .topbar-wrapper { background: var(--header-blue) !important; padding: 0 20px !important; }

.swagger-ui .topbar .topbar-wrapper img { filter: brightness(0) invert(1) !important; height: 40px !important; }

.swagger-ui .topbar .topbar-wrapper .link { color: white !important; font-weight: 500 !important; font-family: 'Inter', sans-serif !important; }

.swagger-ui .info { margin: 50px 0 60px 0 !important; background: white !important; border: 1px solid #e2e8f0 !important; border-radius: 12px !important; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1) !important; padding: 40px !important; font-family: 'Inter', sans-serif !important; }

.swagger-ui .info hgroup h4 { color: var(--header-blue) !important; font-weight: 700 !important; font-size: 28px !important; margin-bottom: 8px !important; }

.swagger-ui .info hgroup p { color: #64748b !important; font-size: 16px !important; line-height: 1.6 !important; }

.swagger-ui .opblock-tag-section .opblock-tag { background: var(--te-green) !important; color: white !important; font-weight: 600 !important; border-radius: 8px !important; padding: 8px 16px !important; font-size: 14px !important; font-family: 'Inter', sans-serif !important; }

.swagger-ui .opblock .opblock-summary-path-description-wrapper { border-color: #e2e8f0 !important; background: white !important; }

.swagger-ui .opblock .opblock-summary { border-color: #e2e8f0 !important; background: white !important; }

.swagger-ui .opblock .opblock-summary .opblock-summary-method { background: var(--te-green) !important; color: white !important; border-radius: 6px !important; }

.swagger-ui .opblock .opblock-summary .opblock-summary-path { color: var(--header-blue) !important; font-weight: 600 !important; }

.swagger-ui .parameter__name { font-weight: 600 !important; color: var(--header-blue) !important; }

.swagger-ui .parameter__type { color: var(--te-green) !important; font-weight: 500 !important; }

.swagger-ui .btn { background: var(--te-green) !important; border: none !important; color: white !important; border-radius: 8px !important; font-weight: 500 !important; transition: all 0.2s !important; }

.swagger-ui .btn:hover { background: #2d9a3e !important; transform: translateY(-1px) !important; }

.swagger-ui .btn:focus { box-shadow: 0 0 0 3px rgba(50, 170, 70, 0.2) !important; outline: none !important; }

.swagger-ui .response-col_status { background: #f0fdf4 !important; color: #166534 !important; border: 1px solid #bbf7d0 !important; }

@media (prefers-color-scheme: dark) {
  body { background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%) !important; color: #f1f5f9 !important; }
  .swagger-ui .info { background: #1e293b !important; border-color: #334155 !important; }
  .swagger-ui .opblock .opblock-summary-path-description-wrapper, .swagger-ui .opblock .opblock-summary { background: #1e293b !important; border-color: #334155 !important; }
}
"""

# SVG Logo Trident simplificado (base64 encurtado para evitar erros)
LOGO_SVG = b'''
<svg width="220" height="24" viewBox="0 0 282 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M0 7.82 6.015 0h32.67l-6.196 7.82h-9.192V30h-9.263V7.82H0Z" fill="#32AA46"/>
  <path d="M38.057 7.77 44.19 0h26.803L64.86 7.77H38.057ZM42.67 0h-2.48l-6.134 7.77h2.492L42.67 0Zm2.632 18.15H63.65l5.272-6.76H31.184v6.76h5.002V30H64.86l6.133-7.77H45.301v-4.08Zm41.53 4.29h2.712V9.65h4.852V7.16H81.999v2.49h4.842l-.01 12.79Zm10.395 0h2.692v-5.33h3.361l3.732 5.33h3.192l-4.122-5.79a4.58 4.58 0 0 0 3.641-4.65 4.582 4.582 0 0 0-1.27-3.29 6.145 6.145 0 0 0-4.442-1.55h-6.784v15.28Zm2.692-7.71V9.6h3.912c2.001 0 3.161.9 3.161 2.54 0 1.55-1.22 2.55-3.141 2.55l-3.932.04Zm13.256 7.71h2.681V7.16h-2.681v15.28Zm6.764 0h5.702c4.803 0 8.124-3.34 8.124-7.64v-.05c0-4.3-3.321-7.59-8.124-7.59h-5.702v15.28ZM125.64 9.6a5.003 5.003 0 0 1 5.313 5.2 5.006 5.006 0 0 1-1.498 3.782A4.999 4.999 0 0 1 125.64 20h-3.001V9.6h3.001Zm11.386 12.84h11.446V20h-8.755v-4.07h7.664v-2.4h-7.664v-4h8.645V7.16h-11.336v15.28Zm14.637 0h2.641V11.57l8.435 10.87h2.251V7.16h-2.652v10.56l-8.194-10.56h-2.491l.01 15.28Zm21.01 0h2.712V9.65h4.842V7.16h-12.406v2.49h4.852v12.79Z" fill="#FFFFFF"/>
  <path d="M190.243 22.44h11.165v-1.57h-9.434v-5.35h8.344V14h-8.344V8.73h9.324V7.16h-11.065l.01 15.28Zm14.637 0h1.681V9.91l9.875 12.53h1.37V7.16h-1.68V19.4L206.06 7.16h-1.611v15.28Zm17.249 0h11.165v-1.57h-9.435v-5.35h8.345V14h-8.345V8.73h9.325V7.16h-11.005l-.05 15.28Zm14.637 0h1.741V16.5h4.372l4.432 5.94h2.121l-4.702-6.24c2.411-.44 4.152-1.93 4.152-4.46a4.22 4.22 0 0 0-1.181-3 5.999 5.999 0 0 0-4.342-1.53h-6.573l-.02 15.23Zm1.741-7.44V8.75h4.722c2.461 0 3.912 1.14 3.912 3v.05c0 2-1.641 3.14-3.932 3.14l-4.702.06Zm21.16 7.75a9.257 9.257 0 0 0 6.143-2.34v-6.14h-6.293v1.55h4.652v3.8a7.205 7.205 0 0 1-4.412 1.53c-3.712 0-6.053-2.71-6.053-6.35v-.05a5.998 5.998 0 0 1 3.513-5.725 6.005 6.005 0 0 1 2.3-.535 6.495 6.495 0 0 1 4.652 1.75l1.111-1.31a8.007 8.007 0 0 0-5.693-2 7.682 7.682 0 0 0-5.509 2.327 7.668 7.668 0 0 0-2.165 5.573 7.478 7.478 0 0 0 2.135 5.629 7.485 7.485 0 0 0 5.589 2.241l.03.05Zm14.157-.26h1.701v-6.12l6.353-9.21h-2.001l-5.203 7.64-5.152-7.64H267l6.353 9.23.04 6.1Z" fill="#FFFFFF"/>
</svg>
'''
LOGO_SVG_BASE64 = base64.b64encode(LOGO_SVG).decode('utf-8')

# Função OpenAPI customizada
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="IBAMA Location API - Trident Energy",
        version="2.6.0",
        description="API de localização de embarcações e plataformas para o IBAMA/CGMAC",
        routes=app.routes,
    )
    app.openapi_schema = openapi_schema
    return app.openapi_schema

# Função HTML Swagger UI customizada (sem conflito de rota)
def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url="/v1/openapi.json",
        title="IBAMA API — Trident Energy",
        css_url="data:text/css;base64," + base64.b64encode(SWAGGER_CSS.encode()).decode(),
        swagger_js_url="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js",
        swagger_css_url="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css",
        swagger_ui_parameters={
            "logo": {
                "url": f"data:image/svg+xml;base64,{LOGO_SVG_BASE64}",
                "alt": "Trident Energy Logo",
                "pageTitle": "Trident Energy - IBAMA API"
            },
            "syntaxHighlight.theme": "agate",
            "deepLinking": True,
            "showExtensions": True,
            "defaultModelsExpandDepth": 1,
            "filter": True,
            "maxDisplayedTags": 10
        },
        oauth2_redirect_url="/docs/oauth2-redirect.html",
    )

# Inicialização FastAPI com docs_url=None para evitar conflito
app = FastAPI(
    title="IBAMA Location API",
    description="API de localização de embarcações e plataformas para o IBAMA/CGMAC",
    version="2.6.0",
    docs_url=None,  # Desabilita docs nativo
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

# Rota manual para Swagger UI customizado (sem conflito)
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
        "version": "2.6.0",
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
            "Accept": "application/json",
            "Cache-Control": "no-cache"  # Limpeza de cache
        }

        url = f"{SPINERGIE_BASE_URL}/sd/api/vessel/sfm-latest-locations"

        logger.debug(f"[DEBUG] Chamando Spinergie: GET {url}")

        response = requests.get(
            url, headers=headers, timeout=5, verify=False  # Timeout reduzido
        )

        logger.debug(f"[DEBUG] Status: {response.status_code}")

        unidades = []

        # Processar VESSELS do Spinergie
        if response.status_code == 200:
            vessels_data = response.json()

            if not isinstance(vessels_data, list):
                vessels_data = vessels_data.get("data", [])

            logger.debug(f"[DEBUG] Total vessels Spinergie: {len(vessels_data)}")

            for vessel in vessels_data:
                mmsi = normalizar_mmsi(vessel.get("mmsi", ""))

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
                            validade=dados.get("validade"),
                            observacao=dados.get("observacao"),
                            disponibilidadeInicio=datetime.now(timezone.utc).isoformat() + "Z",
                            disponibilidadeFim=None
                        ))

        # Adicionar Seastar Virtus
        if "SEASTAR_VIRTUS" in ATIVOS_AUTORIZADOS:
            dados = ATIVOS_AUTORIZADOS["SEASTAR_VIRTUS"]
            logger.info(f"[API] Incluindo vessel estático: {dados['nome']}")

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
                logger.info(f"[API] Incluindo plataforma: {dados['nome']}")

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
    
    Parâmetros:
    - mmsi: Número MMSI (para vessels com MMSI)
    - nome: Nome da unidade (para plataformas e Seastar Virtus)
    
    Pelo menos um dos dois parâmetros deve ser fornecido e válido.
    """
    logger.info(f"[API] GET /v1/posicao - MMSI: {mmsi}, Nome: {nome} - Client: {client_id}")

    if mmsi:
        mmsi = normalizar_mmsi(mmsi)

    if mmsi and not nome:
        # Validar MMSI autorizado
        mmsi_autorizado = ["710001720", "710002450"] + MMSI_PLATAFORMAS
        if mmsi not in mmsi_autorizado:
            logger.warning(f"[WARNING] MMSI {mmsi} não autorizado")
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "not_found",
                    "mmsi": mmsi,
                    "message": "MMSI não encontrado ou não autorizado"
                }
            )

        # Fallback rápido: busca em estáticos primeiro (melhora tempo)
        for ativo_id, dados in ATIVOS_AUTORIZADOS.items():
            if dados.get("mmsi") == mmsi:
                logger.info(f"[SUCCESS] MMSI {mmsi} encontrado em estáticos: {dados['nome']}")
                return PosicaoAIS(
                    mmsi=mmsi,
                    nome=dados["nome"],
                    latitude=float(dados["latitude"]),
                    longitude=float(dados["longitude"]),
                    timestampAquisicao=datetime.now(timezone.utc).isoformat() + "Z"
                )

        # Tenta Spinergie só para vessels (não plataformas)
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

                            logger.info(f"[SUCCESS] Posição Spinergie MMSI {mmsi}: lat={latitude}, lon={longitude}")

                            return PosicaoAIS(
                                mmsi=mmsi,
                                nome=nome_unidade,
                                latitude=float(latitude) if latitude else 0.0,
                                longitude=float(longitude) if longitude else 0.0,
                                timestampAquisicao=datetime_obj.isoformat() + "Z"
                            )

                logger.warning(f"[WARNING] MMSI {mmsi} não encontrado em Spinergie")

            except Exception as e:
                logger.warning(f"[WARNING] Erro Spinergie para MMSI {mmsi}: {str(e)}")

        # Fallback final para posição estática
        for ativo_id, dados in ATIVOS_AUTORIZADOS.items():
            if dados.get("mmsi") == mmsi:
                logger.info(f"[SUCCESS] Fallback estático para MMSI {mmsi}: {dados['nome']}")
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
                logger.info(f"[SUCCESS] Nome {nome} encontrado: {dados['nome']}")

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
    logger.info("\n[INFO] ========== INICIANDO API IBAMA 2.6.0 ==========\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)