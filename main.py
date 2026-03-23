# main.py — API IBAMA com FastAPI — VERSÃO FINAL 2.4.0

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

from fastapi import FastAPI, HTTPException, Form, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from datetime import timedelta, datetime, timezone
from typing import List, Optional
import os
import jwt
import traceback
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

# ✅ ATIVOS AUTORIZADOS — Conforme tabela IBAMA + MMSIs para P08 e P65
ATIVOS_AUTORIZADOS = {
    # ===== VESSELS (2) =====
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

    # ===== SEASTAR VIRTUS =====
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
    
    # ===== PLATAFORMAS (4) — COM MMSIs ADICIONADOS PARA P08 E P65 =====
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
        "mmsi": "538003593",  # MMSI ADICIONADO
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
        "mmsi": "538001903",  # MMSI ADICIONADO
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
logger.info(f"[CONFIG] Ativos autorizados: {len(ATIVOS_AUTORIZADOS)} (2 vessels + 1 Seastar + 4 plataformas)\n")

# Inicialização FastAPI
app = FastAPI(
    title="IBAMA Location API",
    description="API de localização de embarcações e plataformas para o IBAMA/CGMAC",
    version="2.4.0",
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


# CSS Customizado para Swagger UI (Trident Energy Design System)
SWAGGER_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {
  --te-green: #32AA46;
  --header-blue: #283C50;
  --header-border: #1f3041;
  --logo-blue: #1e3a5f;
  --logo-green: #4ade80;
  --slate-850: #1e293b;
  --slate-950: #020617;
}

body {
  font-family: 'Inter', sans-serif;
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  color: #1e293b;
}

.swagger-ui .topbar {
  background: var(--header-blue) !important;
  border-bottom: 1px solid var(--header-border) !important;
}

.swagger-ui .topbar-wrapper {
  background: var(--header-blue) !important;
}

.swagger-ui .topbar .topbar-wrapper img {
  filter: brightness(0) invert(1); /* Branco para logo */
}

.swagger-ui .topbar .topbar-wrapper .link {
  color: white !important;
  font-weight: 500;
}

.swagger-ui .topbar .topbar-wrapper .download-url-wrapper {
  display: none; /* Esconde download se não necessário */
}

.swagger-ui .info {
  margin: 50px 0 60px 0;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  padding: 40px;
  font-family: 'Inter', sans-serif;
}

.swagger-ui .info hgroup h4 {
  color: var(--header-blue) !important;
  font-weight: 700;
  font-size: 28px;
  margin-bottom: 8px;
}

.swagger-ui .info hgroup p {
  color: #64748b;
  font-size: 16px;
  line-height: 1.6;
}

.swagger-ui .opblock-tag-section .opblock-tag {
  background: var(--te-green) !important;
  color: white !important;
  font-weight: 600;
  border-radius: 8px;
  padding: 8px 16px;
  font-size: 14px;
}

.swagger-ui .opblock .opblock-summary-path-description-wrapper {
  border-color: #e2e8f0 !important;
  background: white !important;
}

.swagger-ui .opblock .opblock-summary {
  border-color: #e2e8f0 !important;
  background: white !important;
}

.swagger-ui .opblock .opblock-summary .opblock-summary-method {
  background: var(--te-green) !important;
  color: white !important;
  border-radius: 6px;
}

.swagger-ui .opblock .opblock-summary .opblock-summary-path {
  color: var(--header-blue) !important;
  font-weight: 600;
}

.swagger-ui .opblock .opblock-summary .opblock-summary-description {
  color: #64748b !important;
}

.swagger-ui .parameter__name {
  font-weight: 600;
  color: var(--header-blue);
}

.swagger-ui .parameter__type {
  color: var(--te-green);
  font-weight: 500;
}

.swagger-ui .execute-wrapper .execute-wrapper__body {
  background: white !important;
  border: 1px solid #e2e8f0 !important;
  border-radius: 8px;
}

.swagger-ui .btn {
  background: var(--te-green) !important;
  border: none !important;
  color: white !important;
  border-radius: 8px !important;
  font-weight: 500 !important;
  transition: all 0.2s !important;
}

.swagger-ui .btn:hover {
  background: #2d9a3e !important;
  transform: translateY(-1px) !important;
}

.swagger-ui .btn-group .btn {
  border-radius: 6px !important;
  margin-right: 8px !important;
}

.swagger-ui .response-col_status {
  background: #f0fdf4 !important;
  color: #166534 !important;
  border: 1px solid #bbf7d0 !important;
}

.swagger-ui .response-col_description {
  background: white !important;
  border: 1px solid #e2e8f0 !important;
}

/* Dark mode toggle (opcional) */
.swagger-ui .scheme-container {
  background: var(--header-blue) !important;
}

.swagger-ui .expand-operation {
  color: var(--te-green) !important;
}

/* Focus rings Trident style */
.swagger-ui *:focus {
  outline: none !important;
  box-shadow: 0 0 0 3px rgba(50, 170, 70, 0.2) !important;
}
"""

# Função para OpenAPI customizada (não muda)
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="IBAMA Location API",
        version="2.4.0",
        description="API de localização de embarcações e plataformas para o IBAMA/CGMAC",
        routes=app.routes,
    )
    app.openapi_schema = openapi_schema
    return app.openapi_schema


# Função para HTML do Swagger UI customizada
def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url="/v1/openapi.json",
        title="IBAMA API — Trident Energy",
        css_url=SWAGGER_CSS,  # CSS customizado Trident Design System
        swagger_js_url="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js",
        swagger_css_url="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css",
        oauth2_redirect_url="/docs/oauth2-redirect.html",
    )


# Inicialização FastAPI com customizações
app = FastAPI(
    title="IBAMA Location API",
    description="API de localização de embarcações e plataformas para o IBAMA/CGMAC",
    version="2.4.0",
    docs_url="/v1/docs",
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

# Substituir endpoints padrão do Swagger com customizações
app.openapi = custom_openapi
app.get("/v1/docs")(custom_swagger_ui_html)

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
        #logger.error(f"[API] Erro ao validar token: {str(e)}")
        #raise HTTPException(status_code=500, detail={"error": "internal_error"})
        logger.error(f"Erro Spinergie MMSI {mmsi}: {str(e)} | Status: {response.status_code if 'response' in locals() else 'N/A'} | Text: {getattr(response, 'text', 'N/A')[:300]}", exc_info=True)

# ====== ENDPOINTS ======

@app.get("/")
async def root():
    """Endpoint raiz da API"""
    return {
        "message": "IBAMA Location API",
        "version": "2.4.0",
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

                # Verificar se é um dos vessels autorizados (apenas os 2)
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
                validade=dados.get("validade"),
                observacao=dados.get("observacao"),
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
    
    Exemplos:
    - GET /v1/posicao?mmsi=710001720 (MAERSK VEGA)
    - GET /v1/posicao?nome=PPM-1 (Plataforma)
    - GET /v1/posicao?nome=Seastar Virtus (Seastar Virtus)
    - GET /v1/posicao?mmsi=538001903 (P08)
    - GET /v1/posicao?mmsi=538003593 (P65)
    """
    logger.info(f"[API] GET /v1/posicao - MMSI: {mmsi}, Nome: {nome} - Client: {client_id}")

    # Normalizar MMSI se fornecido
    if mmsi:
        mmsi = normalizar_mmsi(mmsi)

        # ===== Busca por MMSI =====
        if mmsi and not nome:
            mmsi = normalizar_mmsi(mmsi)
            logger.info(f"[API] GET /v1/posicao - MMSI: {mmsi}")
            
            # Validar se MMSI autorizado
            if mmsi not in [d.get("mmsi") for d in ATIVOS_AUTORIZADOS.values() if d.get("mmsi")]:
                raise HTTPException(status_code=404, detail=f"MMSI '{mmsi}' não autorizado.")
            
            # P65/P08: retornar estáticos (igual busca por nome)
            mmsi_para_nome = {"538003593": "P65", "538001903": "P08"}
            nome_plataforma = mmsi_para_nome.get(mmsi)
            
            if nome_plataforma:
                # Plataformas: usar dados estáticos (como no antigo)
                for dados in ATIVOS_AUTORIZADOS.values():
                    if dados.get("nome") == nome_plataforma:
                        logger.info(f"[API] P{nome_plataforma[-2:]} estático encontrado")
                        return PosicaoAIS(
                            latitude=dados.get("latitude", 0.0),
                            longitude=dados.get("longitude", 0.0),
                            datetime=datetime.now(timezone.utc).isoformat() + "Z",
                            mmsi=mmsi,
                            nome=nome_plataforma
                        )
                raise HTTPException(status_code=404, detail=f"Plataforma '{nome_plataforma}' não encontrada.")
            
            # Outros MMSI: chamar Spinergie vessel (como antigo)
            headers = {"Apikey": SPINERGIE_API_KEY, "Accept": "application/json"}
            url = f"{SPINERGIE_BASE_URL}/sd/api/vessel/sfm-latest-locations"
            logger.info(f"[Spinergie Vessel] MMSI {mmsi}")
            
            try:
                response = requests.get(url, headers=headers, timeout=10, verify=False)
                
                if response.status_code == 200:
                    vessels_data = response.json()
                    if not isinstance(vessels_data, list):
                        vessels_data = vessels_data.get("data", [])
                    
                    for vessel in vessels_data:
                        if normalizar_mmsi(vessel.get("mmsi", "")) == mmsi:
                            datetime_ms = vessel.get("datetime", int(time.time() * 1000))
                            datetime_obj = datetime.fromtimestamp(datetime_ms / 1000, timezone.utc)
                            
                            # Buscar nome no dicionário
                            nome_unidade = None
                            for ativo_id, dados in ATIVOS_AUTORIZADOS.items():
                                if dados.get("mmsi") == mmsi:
                                    nome_unidade = dados["nome"]
                                    break
                            
                            logger.info(f"[API] Vessel {mmsi} encontrado!")
                            return PosicaoAIS(
                                latitude=vessel.get("latitude", 0.0),
                                longitude=vessel.get("longitude", 0.0),
                                datetime=datetime_obj.isoformat() + "Z",
                                mmsi=mmsi,
                                nome=nome_unidade or f"Vessel {mmsi}"
                            )
                
                raise HTTPException(status_code=404, detail="MMSI autorizado mas sem posição disponível no Spinergie.")
                
            except requests.exceptions.Timeout:
                raise HTTPException(status_code=504, detail="Timeout Spinergie.")
            except requests.exceptions.ConnectionError:
                raise HTTPException(status_code=503, detail="Spinergie indisponível.")
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[Spinergie] Erro MMSI {mmsi}: {e}")
                raise HTTPException(status_code=500, detail="Erro interno consulta Spinergie.")

    # ===== Busca por NOME =====
    elif nome and not mmsi:
        logger.debug(f"[DEBUG] Buscando por Nome: {nome}")

        nome_normalizado = nome.strip().lower()

        # Buscar nos ativos autorizados
        for ativo_id, dados in ATIVOS_AUTORIZADOS.items():
            if dados["nome"].lower() == nome_normalizado:
                logger.info(f"[API] Encontrado: {dados['nome']}")

                # Se tem dados de lat/lon no dicionário, usar
                latitude = dados.get("latitude", 0.0)
                longitude = dados.get("longitude", 0.0)

                logger.info(
                    f"[SUCCESS] Posição encontrada Nome {nome}: "
                    f"lat={latitude}, lon={longitude}"
                )

                return PosicaoAIS(
                    mmsi=dados.get("mmsi"),
                    nome=dados["nome"],
                    latitude=float(latitude),
                    longitude=float(longitude),
                    timestampAquisicao=datetime.now(timezone.utc).isoformat() + "Z"
                )

        logger.warning(f"[WARNING] Nome {nome} não encontrado ou não autorizado")
        raise HTTPException(
            status_code=404,
            detail={
                "error": "not_found",
                "nome": nome,
                "message": "Unidade não encontrada ou não autorizada"
            }
        )

    # ===== Ambos preenchidos =====
    elif mmsi and nome:
        logger.warning(f"[WARNING] Ambos MMSI e Nome fornecidos")
        raise HTTPException(
            status_code=400,
            detail={
                "error": "bad_request",
                "message": "Forneça apenas MMSI OU nome, não ambos"
            }
        )

    # ===== Nenhum preenchido =====
    else:
        logger.warning(f"[WARNING] Nenhum parâmetro válido fornecido")
        raise HTTPException(
            status_code=400,
            detail={
                "error": "bad_request",
                "message": "Forneça pelo menos um parâmetro: mmsi ou nome"
            }
        )


if __name__ == "__main__":
    import uvicorn
    logger.info("\n[INFO] ========== INICIANDO API IBAMA 2.4.0 ==========\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)