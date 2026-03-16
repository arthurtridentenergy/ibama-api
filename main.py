# main.py — API IBAMA com FastAPI — VERSÃO FINAL COM POSIÇÃO CORRIGIDA

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
    logger.debug(f"[API] Recebido token (primeiros 50 chars): {token[:50]}...")
    
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
    return {
        "message": "IBAMA Location API",
        "version": "1.0.0",
        "docs": "/v1/docs",
        "environment": ENVIRONMENT
    }


@app.get("/health")
async def health_check():
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
    """Lista todas as unidades marítimas autorizadas"""
    logger.info(f"[API] GET /v1/unidades - Client: {client_id}")
    
    try:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "apiKey": SPINERGIE_API_KEY
        }
        
        # URL correta para atividades detectadas
        url = f"{SPINERGIE_BASE_URL}/osv/api/location/activities"
        
        # Parâmetro obrigatório: activityDatetime (últimos 30 dias em milissegundos)
        now_ms = int(time.time() * 1000)
        thirty_days_ago_ms = now_ms - (30 * 24 * 60 * 60 * 1000)
        
        params = {
            "activityDatetime": f"{thirty_days_ago_ms},{now_ms}"
        }
        
        logger.debug(f"[DEBUG] GET {url} com params: {params}")
        
        response = requests.get(url, headers=headers, params=params, timeout=60, verify=False)
        
        logger.debug(f"[DEBUG] Status: {response.status_code}, Length: {len(response.text)}")
        
        if response.status_code == 200:
            try:
                vessels_data = response.json()
                
                if isinstance(vessels_data, dict):
                    if "activities" in vessels_data:
                        vessels_data = vessels_data["activities"]
                    elif "vessels" in vessels_data:
                        vessels_data = vessels_data["vessels"]
                
                if not isinstance(vessels_data, list):
                    vessels_data = [vessels_data] if vessels_data else []
                
                if vessels_data and len(vessels_data) > 0:
                    unidades = []
                    for vessel in vessels_data:
                        try:
                            tipo = vessel.get("type", vessel.get("tipoUnidade", "EMBARCACAO_APOIO"))
                            unidades.append(UnidadeMaritima(
                                nome=vessel.get("name", vessel.get("nome", "Nome Desconhecido")),
                                imo=str(vessel.get("imo", "")) if vessel.get("imo") else None,
                                mmsi=str(vessel.get("mmsi", "")),
                                tipoUnidade=tipo,
                                licencasAutorizadas=vessel.get("licenses", vessel.get("licencas", [])),
                                disponibilidadeInicio=vessel.get("disponibilidadeInicio", datetime.now(timezone.utc).isoformat() + "Z"),
                                disponibilidadeFim=vessel.get("disponibilidadeFim")
                            ))
                        except Exception as e:
                            logger.warning(f"[WARNING] Erro ao processar vessel: {e}")
                            continue
                    
                    logger.info(f"[API] Retornando {len(unidades)} unidades")
                    return unidades
                else:
                    logger.info("[API] Spinergie retornou vazio, usando dados mock")
                    return get_all_vessels()
            
            except json.JSONDecodeError:
                logger.error("[ERROR] JSON inválido do Spinergie")
                return get_all_vessels()
        
        else:
            logger.error(f"[ERROR] Spinergie Status: {response.status_code}")
            return get_all_vessels()
    
    except Exception as e:
        logger.error(f"[ERROR] Exception: {str(e)}")
        return get_all_vessels()


@app.get("/v1/posicao/{mmsi}", response_model=PosicaoAIS, tags=["Vessels"])
async def get_posicao(mmsi: str, client_id: str = Depends(get_current_client_id)):
    """
    Obtém a posição de um vessel específico pelo MMSI
    
    Estratégia:
    1. Tenta obter do Spinergie usando /osv/api/location/activities
    2. Se não encontrar, tenta dados mock locais
    """
    logger.info(f"[API] GET /v1/posicao/{mmsi} - Client: {client_id}")
    
    try:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "apiKey": SPINERGIE_API_KEY
        }
        
        # Primeiro, tenta obter a lista de vessels para encontrar o vesselId correspondente ao MMSI
        url_activities = f"{SPINERGIE_BASE_URL}/osv/api/location/activities"
        
        now_ms = int(time.time() * 1000)
        thirty_days_ago_ms = now_ms - (30 * 24 * 60 * 60 * 1000)
        
        params = {
            "activityDatetime": f"{thirty_days_ago_ms},{now_ms}"
        }
        
        logger.debug(f"[DEBUG] Procurando MMSI {mmsi} no Spinergie")
        logger.debug(f"[DEBUG] GET {url_activities}")
        
        response = requests.get(url_activities, headers=headers, params=params, timeout=60, verify=False)
        
        logger.debug(f"[DEBUG] Status: {response.status_code}")
        
        if response.status_code == 200:
            try:
                activities_data = response.json()
                
                if not isinstance(activities_data, list):
                    activities_data = activities_data.get("activities", []) if isinstance(activities_data, dict) else []
                
                logger.debug(f"[DEBUG] Total activities: {len(activities_data)}")
                
                # Procura por activities que correspondam ao MMSI ou que contenham latitude/longitude
                for activity in activities_data:
                    activity_mmsi = str(activity.get("mmsi", ""))
                    activity_vessel_id = str(activity.get("vesselId", ""))
                    
                    logger.debug(f"[DEBUG] Verificando activity - MMSI: {activity_mmsi}, vesselId: {activity_vessel_id}")
                    
                    # Se encontrou a latitude/longitude, retorna
                    if activity.get("latitude") and activity.get("longitude"):
                        # Verifica se pertence ao MMSI procurado (se a API retornar esse campo)
                        if activity_mmsi == mmsi or activity_vessel_id == mmsi:
                            logger.info(f"[SUCCESS] Encontrada posição para MMSI {mmsi}")
                            return PosicaoAIS(
                                mmsi=mmsi,
                                latitude=float(activity.get("latitude", 0.0)),
                                longitude=float(activity.get("longitude", 0.0)),
                                timestampAquisicao=datetime.fromtimestamp(
                                    activity.get("dateEnd", int(time.time() * 1000)) / 1000,
                                    tz=timezone.utc
                                ).isoformat() + "Z"
                            )
                
                # Se não encontrou no Spinergie com dados de posição, tenta dados mock
                logger.warning(f"[WARNING] MMSI {mmsi} não encontrado com posição no Spinergie, tentando mock")
                posicao = get_vessel_position(mmsi)
                
                if posicao:
                    logger.info(f"[SUCCESS] Retornando posição mock para MMSI {mmsi}")
                    return posicao
                else:
                    logger.error(f"[ERROR] MMSI {mmsi} não encontrado")
                    raise HTTPException(status_code=404, detail={"error": "not_found", "mmsi": mmsi})
            
            except json.JSONDecodeError as e:
                logger.error(f"[ERROR] JSON inválido: {str(e)}")
                posicao = get_vessel_position(mmsi)
                if posicao:
                    return posicao
                raise HTTPException(status_code=502, detail={"error": "invalid_response"})
        
        else:
            logger.error(f"[ERROR] Spinergie Status {response.status_code}")
            posicao = get_vessel_position(mmsi)
            if posicao:
                return posicao
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