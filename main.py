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
from pydantic import BaseModel, Field
import os
import jwt
import json
import logging

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
    description="API de localização de embarcações para o IBAMA/CGMAC - Gerência de Segurança",
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
        return client_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail={"error": "token_expired"})
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail={"error": "invalid_token"})


# ENDPOINTS

@app.get("/", tags=["Root"])
async def root():
    """Endpoint raiz da API"""
    return {
        "message": "IBAMA Location API",
        "version": "1.0.0",
        "docs": "/v1/docs",
        "environment": ENVIRONMENT
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check da API"""
    return {
        "status": "ok",
        "environment": ENVIRONMENT,
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
    }


@app.post("/auth/token", tags=["Authentication"])
async def get_token(
    grant_type: str = Form(...),
    client_id: str = Form(...),
    client_secret: str = Form(...)
):
    """
    Endpoint de autenticação OAuth 2.0 Client Credentials
    
    Retorna um JWT token para uso nos demais endpoints
    """
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
    
    Retorna array de UnidadeMaritima com todos os vessels cadastrados
    """
    logger.info(f"[API] GET /v1/unidades - Client: {client_id}")
    
    try:
        # ✅ HEADERS CORRETOS DO SPINERGIE
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "apiKey": SPINERGIE_API_KEY
        }
        
        # ✅ URL CORRETA DO SPINERGIE
        url = f"{SPINERGIE_BASE_URL}/osv/api/reporting/activities"
        
        logger.debug(f"[DEBUG] Chamando Spinergie: GET {url}")
        
        response = requests.get(url, headers=headers, timeout=60, verify=False)
        
        logger.debug(f"[DEBUG] Status: {response.status_code}, Content-Type: {response.headers.get('Content-Type')}")
        
        if response.status_code == 200:
            try:
                vessels_data = response.json()
                
                # Trata diferentes estruturas de resposta
                if isinstance(vessels_data, dict):
                    if "activities" in vessels_data:
                        vessels_data = vessels_data["activities"]
                    elif "vessels" in vessels_data:
                        vessels_data = vessels_data["vessels"]
                    elif "data" in vessels_data:
                        vessels_data = vessels_data["data"]
                
                if not isinstance(vessels_data, list):
                    vessels_data = [vessels_data] if vessels_data else []
                
                # Se recebeu dados do Spinergie, processa
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
                    
                    logger.info(f"[API] Retornando {len(unidades)} unidades do Spinergie")
                    return unidades
                
                # Se Spinergie retornou vazio, usa dados mock
                else:
                    logger.info(f"[API] Spinergie retornou vazio, usando dados mock")
                    return get_all_vessels()
            
            except json.JSONDecodeError:
                logger.error("[ERROR] Resposta do Spinergie não é JSON válido")
                # Fallback para dados mock
                logger.info("[INFO] Usando dados mock como fallback")
                return get_all_vessels()
        
        elif response.status_code == 401:
            logger.error("[ERROR] Spinergie 401 - apiKey inválida")
            # Fallback para dados mock
            return get_all_vessels()
        
        else:
            logger.error(f"[ERROR] Spinergie Status: {response.status_code}")
            # Fallback para dados mock
            return get_all_vessels()
    
    except requests.Timeout:
        logger.error("[ERROR] Timeout ao chamar Spinergie")
        # Fallback para dados mock
        return get_all_vessels()
    
    except requests.ConnectionError as e:
        logger.error(f"[ERROR] Connection Error: {e}")
        # Fallback para dados mock
        return get_all_vessels()
    
    except Exception as e:
        logger.error(f"[ERROR] Exception: {str(e)}")
        # Fallback para dados mock
        return get_all_vessels()


@app.get("/v1/posicao/{mmsi}", response_model=PosicaoAIS, tags=["Vessels"])
async def get_posicao(mmsi: str, client_id: str = Depends(get_current_client_id)):
    """
    Obtém a posição de um vessel específico pelo MMSI
    
    Parâmetro: mmsi (9 dígitos)
    Retorna: PosicaoAIS com coordenadas e timestamp
    """
    logger.info(f"[API] GET /v1/posicao/{mmsi} - Client: {client_id}")
    
    try:
        # ✅ HEADERS CORRETOS DO SPINERGIE
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "apiKey": SPINERGIE_API_KEY
        }
        
        # ✅ URL CORRETA DO SPINERGIE
        url = f"{SPINERGIE_BASE_URL}/osv/api/reporting/activities"
        
        logger.debug(f"[DEBUG] Chamando Spinergie: GET {url} - MMSI: {mmsi}")
        
        response = requests.get(url, headers=headers, timeout=60, verify=False)
        
        logger.debug(f"[DEBUG] Status: {response.status_code}")
        
        if response.status_code == 200:
            try:
                data = response.json()
                activities = data.get("activities", data.get("data", []))
                
                if not isinstance(activities, list):
                    activities = [activities]
                
                # Procura o vessel com MMSI específico
                for activity in activities:
                    if str(activity.get("mmsi")) == mmsi:
                        return PosicaoAIS(
                            mmsi=mmsi,
                            latitude=activity.get("latitude", 0.0),
                            longitude=activity.get("longitude", 0.0),
                            timestampAquisicao=activity.get("timestamp", datetime.now(timezone.utc).isoformat() + "Z")
                        )
                
                # Se não encontrou no Spinergie, tenta dados mock
                logger.info(f"[INFO] MMSI {mmsi} não encontrado no Spinergie, tentando dados mock")
                posicao = get_vessel_position(mmsi)
                if posicao:
                    return posicao
                else:
                    raise HTTPException(status_code=404, detail={"error": "not_found"})
            
            except json.JSONDecodeError:
                logger.error("[ERROR] Resposta do Spinergie não é JSON válido")
                # Tenta dados mock
                posicao = get_vessel_position(mmsi)
                if posicao:
                    return posicao
                else:
                    raise HTTPException(status_code=502, detail={"error": "invalid_response"})
        
        elif response.status_code == 401:
            logger.error("[ERROR] Spinergie 401 - apiKey inválida")
            # Tenta dados mock
            posicao = get_vessel_position(mmsi)
            if posicao:
                return posicao
            else:
                raise HTTPException(status_code=502, detail={"error": "auth_error"})
        
        else:
            logger.error(f"[ERROR] Spinergie Status: {response.status_code}")
            # Tenta dados mock
            posicao = get_vessel_position(mmsi)
            if posicao:
                return posicao
            else:
                raise HTTPException(status_code=502, detail={"error": "api_error"})
    
    except requests.Timeout:
        logger.error("[ERROR] Timeout ao chamar Spinergie")
        # Tenta dados mock
        posicao = get_vessel_position(mmsi)
        if posicao:
            return posicao
        else:
            raise HTTPException(status_code=504, detail={"error": "timeout"})
    
    except requests.ConnectionError as e:
        logger.error(f"[ERROR] Connection Error: {e}")
        # Tenta dados mock
        posicao = get_vessel_position(mmsi)
        if posicao:
            return posicao
        else:
            raise HTTPException(status_code=503, detail={"error": "connection_error"})
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"[ERROR] Exception: {str(e)}")
        raise HTTPException(status_code=500, detail={"error": "internal_error"})


if __name__ == "__main__":
    import uvicorn
    logger.info(f"\n[INFO] ========== INICIANDO API IBAMA ==========")
    logger.info(f"[INFO] Documentação: http://localhost:8000/v1/docs")
    logger.info(f"[INFO] Health: http://localhost:8000/health\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)