# main.py — API IBAMA com FastAPI — VERSÃO FINAL COM SPINERGIE CORRETO

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

from fastapi import FastAPI, HTTPException, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import timedelta, datetime, timezone
from typing import List, Optional
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
SPINERGIE_BASE_URL = os.getenv("SPINERGIE_BASE_URL", "https://trident-energy-br.spinergie.com")
SPINERGIE_API_KEY = os.getenv("SPINERGIE_API_KEY", "")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

logger.info(f"[CONFIG] Environment: {ENVIRONMENT}")
logger.info(f"[CONFIG] JWT_SECRET_KEY: {'✅ Carregado' if JWT_SECRET_KEY else '❌ Não carregado'}")
logger.info(f"[CONFIG] CLIENT_ID: {CLIENT_ID}")
logger.info(f"[CONFIG] SPINERGIE_API_KEY: {'✅ Carregado' if SPINERGIE_API_KEY else '❌ Não carregado'}\n")

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


def get_current_client_id(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
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


# ENDPOINTS

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
        raise HTTPException(status_code=400, detail={"error": "unsupported_grant_type"})
    
    if not authenticate_client(client_id, client_secret):
        raise HTTPException(status_code=401, detail={"error": "invalid_client"})
    
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
    Lista todas as unidades marítimas autorizadas
    
    Retorna array de UnidadeMaritima com todos os vessels cadastrados do Spinergie
    """
    logger.info(f"[API] GET /v1/unidades - Client: {client_id}")
    
    try:
        # ✅ HEADERS CORRETOS DO SPINERGIE (case-sensitive!)
        headers = {
            "Apikey": SPINERGIE_API_KEY,
            "Accept": "application/json"
        }
        
        # ✅ ENDPOINT CORRETO: /sd/api/vessel/sfm-latest-locations
        url = f"{SPINERGIE_BASE_URL}/sd/api/vessel/sfm-latest-locations"
        
        logger.debug(f"[DEBUG] Chamando Spinergie: GET {url}")
        logger.debug(f"[DEBUG] Headers: Apikey (***), Accept: application/json")
        
        response = requests.get(url, headers=headers, timeout=60, verify=False)
        
        logger.debug(f"[DEBUG] Status: {response.status_code}, Length: {len(response.text)}")
        
        if response.status_code == 200:
            try:
                vessels_data = response.json()
                
                # Validar que é uma lista
                if not isinstance(vessels_data, list):
                    logger.warning("[WARNING] Resposta não é lista, tentando extrair dados")
                    if isinstance(vessels_data, dict):
                        vessels_data = vessels_data.get("data", [])
                    else:
                        vessels_data = []
                
                logger.info(f"[DEBUG] Total vessels do Spinergie: {len(vessels_data)}")
                
                # Processar cada vessel
                unidades = []
                for vessel in vessels_data:
                    try:
                        # Mapear os campos do Spinergie para o modelo UnidadeMaritima
                        unidades.append(UnidadeMaritima(
                            nome=vessel.get("vesselTitle", "Nome Desconhecido"),
                            imo=str(vessel.get("imo", "")) if vessel.get("imo") else None,
                            mmsi=str(vessel.get("mmsi", "")),
                            tipoUnidade=vessel.get("vesselType", "EMBARCACAO_APOIO"),
                            licencasAutorizadas=[],  # Spinergie não retorna licenças
                            disponibilidadeInicio=datetime.now(timezone.utc).isoformat() + "Z",
                            disponibilidadeFim=None
                        ))
                    except Exception as e:
                        logger.warning(f"[WARNING] Erro ao processar vessel: {e}")
                        continue
                
                logger.info(f"[API] Retornando {len(unidades)} unidades do Spinergie")
                return unidades
            
            except json.JSONDecodeError:
                logger.error("[ERROR] Resposta do Spinergie não é JSON válido")
                logger.info("[INFO] Usando dados mock como fallback")
                return get_all_vessels()
        
        elif response.status_code == 401:
            logger.error("[ERROR] Spinergie 401 - Apikey inválida")
            logger.info("[INFO] Usando dados mock como fallback")
            return get_all_vessels()
        
        else:
            logger.error(f"[ERROR] Spinergie Status {response.status_code}: {response.text[:200]}")
            logger.info("[INFO] Usando dados mock como fallback")
            return get_all_vessels()
    
    except requests.Timeout:
        logger.error("[ERROR] Timeout ao chamar Spinergie")
        logger.info("[INFO] Usando dados mock como fallback")
        return get_all_vessels()
    
    except requests.ConnectionError as e:
        logger.error(f"[ERROR] Connection Error: {e}")
        logger.info("[INFO] Usando dados mock como fallback")
        return get_all_vessels()
    
    except Exception as e:
        logger.error(f"[ERROR] Exception: {str(e)}")
        logger.info("[INFO] Usando dados mock como fallback")
        return get_all_vessels()


@app.get("/v1/posicao/{mmsi}", response_model=PosicaoAIS, tags=["Vessels"])
async def get_posicao(mmsi: str, client_id: str = Depends(get_current_client_id)):
    """
    Obtém a posição de um vessel específico pelo MMSI
    
    Parâmetro: mmsi (9 dígitos)
    Retorna: PosicaoAIS com coordenadas latitude/longitude e timestamp
    """
    logger.info(f"[API] GET /v1/posicao/{mmsi} - Client: {client_id}")
    
    try:
        # ✅ HEADERS CORRETOS DO SPINERGIE
        headers = {
            "Apikey": SPINERGIE_API_KEY,
            "Accept": "application/json"
        }
        
        # ✅ ENDPOINT CORRETO: /sd/api/vessel/sfm-latest-locations
        url = f"{SPINERGIE_BASE_URL}/sd/api/vessel/sfm-latest-locations"
        
        logger.debug(f"[DEBUG] Buscando MMSI {mmsi} no endpoint: {url}")
        
        response = requests.get(url, headers=headers, timeout=60, verify=False)
        
        logger.debug(f"[DEBUG] Spinergie Status Code: {response.status_code}")
        
        if response.status_code == 200:
            try:
                vessels_data = response.json()
                
                # Validar lista
                if not isinstance(vessels_data, list):
                    if isinstance(vessels_data, dict):
                        vessels_data = vessels_data.get("data", [])
                    else:
                        vessels_data = []
                
                logger.debug(f"[DEBUG] Total vessels recebidos: {len(vessels_data)}")
                
                # Procurar o vessel com MMSI específico
                for vessel in vessels_data:
                    vessel_mmsi = str(vessel.get("mmsi", ""))
                    
                    logger.debug(f"[DEBUG] Verificando MMSI: {vessel_mmsi} == {mmsi} ?")
                    
                    if vessel_mmsi == mmsi:
                        # Converter timestamp de milissegundos para segundos
                        datetime_ms = vessel.get("datetime", int(time.time() * 1000))
                        datetime_obj = datetime.fromtimestamp(
                            datetime_ms / 1000,
                            tz=timezone.utc
                        )
                        
                        logger.info(f"[SUCCESS] Encontrada posição para MMSI {mmsi}")
                        return PosicaoAIS(
                            mmsi=mmsi,
                            latitude=float(vessel.get("latitude", 0.0)),
                            longitude=float(vessel.get("longitude", 0.0)),
                            timestampAquisicao=datetime_obj.isoformat() + "Z"
                        )
                
                # Se não encontrou no Spinergie, tenta dados mock
                logger.warning(f"[WARNING] MMSI {mmsi} não encontrado no Spinergie, tentando mock")
                posicao = get_vessel_position(mmsi)
                
                if posicao:
                    logger.info(f"[SUCCESS] Retornando posição mock para MMSI {mmsi}")
                    return posicao
                else:
                    logger.error(f"[ERROR] MMSI {mmsi} não encontrado")
                    raise HTTPException(status_code=404, detail={"error": "not_found", "mmsi": mmsi})
            
            except json.JSONDecodeError as e:
                logger.error(f"[ERROR] JSON inválido: {str(e)}")
                raise HTTPException(status_code=502, detail={"error": "invalid_response"})
        
        elif response.status_code == 401:
            logger.error("[ERROR] Spinergie 401 - Apikey inválida")
            raise HTTPException(status_code=502, detail={"error": "spinergie_auth_error"})
        
        else:
            logger.error(f"[ERROR] Spinergie Status {response.status_code}")
            raise HTTPException(status_code=502, detail={"error": "spinergie_error"})
    
    except requests.Timeout:
        logger.error("[ERROR] Timeout")
        posicao = get_vessel_position(mmsi)
        if posicao:
            return posicao
        raise HTTPException(status_code=504, detail={"error": "timeout"})
    
    except requests.ConnectionError:
        logger.error("[ERROR] Connection Error")
        posicao = get_vessel_position(mmsi)
        if posicao:
            return posicao
        raise HTTPException(status_code=503, detail={"error": "connection_error"})
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"[ERROR] Exception: {str(e)}")
        raise HTTPException(status_code=500, detail={"error": "internal_error"})


if __name__ == "__main__":
    import uvicorn
    logger.info(f"\n[INFO] ========== INICIANDO API IBAMA ==========\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)