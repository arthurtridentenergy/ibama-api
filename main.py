# main.py — API IBAMA com FastAPI — INTEGRAÇÃO DIRETA COM SPINERGIE

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
from pydantic import BaseModel, Field
from enum import Enum
import os
import jwt
import json

from auth import authenticate_client, create_access_token
from dotenv import load_dotenv

load_dotenv()

# 
# CONFIGURAÇÕES
# 

JWT_SECRET = os.getenv("JWT_SECRET") or os.getenv("SECRET_KEY") or "sua-chave-secreta-padrao-nao-use-em-producao"
ALGORITHM = "HS256"

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

SPINERGIE_BASE_URL = os.getenv("SPINERGIE_BASE_URL", "https://trident-energy-br.spinergie.com")
SPINERGIE_API_KEY = os.getenv("SPINERGIE_API_KEY", "")

print(f"\n[CONFIG] ========== CONFIGURAÇÃO INICIAL ==========")
print(f"[CONFIG] JWT_SECRET carregado: {'SIM' if os.getenv('JWT_SECRET') or os.getenv('SECRET_KEY') else 'NÃO'}")
print(f"[CONFIG] CLIENT_ID: {CLIENT_ID if CLIENT_ID else 'NÃO CARREGADO'}")
print(f"[CONFIG] CLIENT_SECRET: {'*' * 20 if CLIENT_SECRET else 'NÃO CARREGADO'}")
print(f"[CONFIG] SPINERGIE_BASE_URL: {SPINERGIE_BASE_URL}")
print(f"[CONFIG] SPINERGIE_API_KEY: {'*' * 20 if SPINERGIE_API_KEY else 'NÃO CARREGADO'}\n")

# 
# ENUMS E MODELOS CONFORME ESPECIFICAÇÃO IBAMA
# 

class TipoUnidade(str, Enum):
    """Tipos de unidade marítima conforme especificação IBAMA."""
    EMBARCACAO_EMERGENCIA = "EMBARCACAO_EMERGENCIA"
    EMBARCACAO_APOIO = "EMBARCACAO_APOIO"
    EMBARCACAO_EMERGENCIA_APOIO = "EMBARCACAO_EMERGENCIA_APOIO"
    UNIDADE_PRODUCAO = "UNIDADE_PRODUCAO"
    UNIDADE_PERFURACAO = "UNIDADE_PERFURACAO"
    NAVIO_SISMICO = "NAVIO_SISMICO"
    NAVIO_ALIVIADOR = "NAVIO_ALIVIADOR"
    FLOTEL = "FLOTEL"
    OTHER = "Other"


class UnidadeMaritima(BaseModel):
    """Modelo de unidade marítima conforme especificação IBAMA."""
    nome: str = Field(..., description="Nome da unidade marítima")
    imo: Optional[str] = Field(None, description="Número IMO")
    mmsi: str = Field(..., description="Número MMSI")
    tipoUnidade: TipoUnidade = Field(..., description="Tipo de unidade")
    licencasAutorizadas: List[str] = Field(..., description="Lista de licenças")
    disponibilidadeInicio: str = Field(..., description="Início da disponibilidade (ISO 8601 UTC)")
    disponibilidadeFim: Optional[str] = Field(None, description="Fim da disponibilidade (ISO 8601 UTC)")

    class Config:
        schema_extra = {
            "example": {
                "nome": "Navio Exemplo",
                "imo": "IMO1234567",
                "mmsi": "123456789",
                "tipoUnidade": "UNIDADE_PRODUCAO",
                "licencasAutorizadas": ["LIC001"],
                "disponibilidadeInicio": "2024-01-01T00:00:00Z",
                "disponibilidadeFim": None
            }
        }


class PosicaoAIS(BaseModel):
    """Modelo de posição geográfica conforme especificação IBAMA."""
    mmsi: str = Field(..., description="Número MMSI")
    latitude: float = Field(..., description="Latitude em graus decimais")
    longitude: float = Field(..., description="Longitude em graus decimais")
    timestampAquisicao: str = Field(..., description="Data/hora da aquisição (ISO 8601 UTC)")

    class Config:
        schema_extra = {
            "example": {
                "mmsi": "123456789",
                "latitude": -23.5505,
                "longitude": -46.6333,
                "timestampAquisicao": "2026-03-12T14:30:00Z"
            }
        }

# 
# INICIALIZAÇÃO DA APP
# 

app = FastAPI(
    title="IBAMA Location API",
    description="API de localização de embarcações para o IBAMA/CGMAC",
    version="1.0.0",
    docs_url="/v1/docs",
    redoc_url=None,
    openapi_url="/v1/openapi.json"
)

# 
# CORS
# 

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 
# SEGURANÇA
# 

security = HTTPBearer()

def get_current_client_id(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """Valida o token JWT do header Authorization: Bearer <token>"""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        client_id: str = payload.get("sub")
        if client_id is None:
            raise HTTPException(
                status_code=401,
                detail={"error": "invalid_token", "error_description": "Token inválido"}
            )
        return client_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail={"error": "token_expired", "error_description": "Token expirado"}
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_token", "error_description": "Token inválido"}
        )

# 
# ENDPOINTS
# 

@app.get("/", tags=["Root"])
async def root():
    """Endpoint raiz da API."""
    return {
        "message": "IBAMA Location API",
        "version": "1.0.0",
        "docs": "/v1/docs",
        "health": "/health"
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """Verifica se a API está operacional."""
    return {
        "status": "ok",
        "message": "API IBAMA está operacional",
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
    }


@app.post("/auth/token", tags=["Authentication"])
async def get_token(
    grant_type: str = Form(...),
    client_id: str = Form(...),
    client_secret: str = Form(...)
):
    """Endpoint de autenticação OAuth 2.0 Client Credentials."""
    
    if grant_type != "client_credentials":
        raise HTTPException(
            status_code=400,
            detail={
                "error": "unsupported_grant_type",
                "error_description": "grant_type deve ser 'client_credentials'"
            }
        )
    
    if not authenticate_client(client_id, client_secret):
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_client",
                "error_description": "client_id ou client_secret inválidos"
            }
        )
    
    access_token = create_access_token(
        data={"sub": client_id},
        expires_delta=timedelta(hours=1)
    )
    
    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": 3600
    }


@app.get("/v1/unidades", 
         response_model=List[UnidadeMaritima],
         tags=["Vessels"],
         summary="Lista todas as unidades marítimas")
async def get_unidades(client_id: str = Depends(get_current_client_id)):
    """Retorna a lista completa de todas as unidades marítimas autorizadas do Spinergie."""
    
    print(f"\n[API] GET /v1/unidades - Client: {client_id}")
    
    try:
        headers = {
            "Authorization": f"Bearer {SPINERGIE_API_KEY}",
            "Content-Type": "application/json"
        }
        
        url = f"{SPINERGIE_BASE_URL}/api/vessels"
        
        print(f"[DEBUG] Chamando Spinergie: GET {url}")
        print(f"[DEBUG] Headers Authorization: Bearer {SPINERGIE_API_KEY[:20]}...")
        
        response = requests.get(
            url,
            headers=headers,
            timeout=60,
            verify=False
        )
        
        print(f"[DEBUG] Spinergie Status Code: {response.status_code}")
        print(f"[DEBUG] Spinergie Response Length: {len(response.text)} caracteres")
        print(f"[DEBUG] Spinergie Content-Type: {response.headers.get('Content-Type')}")
        print(f"[DEBUG] Spinergie Response Text (primeiros 500 chars): '{response.text[:500]}'")
        
        if response.status_code == 200:
            try:
                vessels_data = response.json()
                print(f"[DEBUG] JSON parsed successfully. Type: {type(vessels_data)}")
                
                if isinstance(vessels_data, dict) and "vessels" in vessels_data:
                    vessels_data = vessels_data["vessels"]
                
                if not isinstance(vessels_data, list):
                    vessels_data = [vessels_data] if vessels_data else []
                
                unidades = []
                for vessel in vessels_data:
                    disponibilidade_inicio = vessel.get("disponibilidadeInicio", datetime.now(timezone.utc).isoformat() + "Z")
                    disponibilidade_fim = vessel.get("disponibilidadeFim")
                    
                    unidades.append(UnidadeMaritima(
                        nome=vessel.get("name", "Nome Desconhecido"),
                        imo=str(vessel.get("imo", "")),
                        mmsi=str(vessel.get("mmsi", "")),
                        tipoUnidade=TipoUnidade(vessel.get("type", "OTHER").upper()),
                        licencasAutorizadas=vessel.get("licenses", []),
                        disponibilidadeInicio=disponibilidade_inicio,
                        disponibilidadeFim=disponibilidade_fim
                    ))
                
                print(f"[API] Retornando {len(unidades)} unidades do Spinergie")
                return unidades
            
            except json.JSONDecodeError as e:
                error_description = f"Resposta do Spinergie não é JSON válido: {str(e)}"
                if response.headers.get('Content-Type', '').startswith('text/html'):
                    error_description = "Spinergie retornou HTML em vez de JSON. Verifique o endpoint."
                print(f"[ERROR] {error_description}")
                raise HTTPException(
                    status_code=502,
                    detail={
                        "error": "spinergie_invalid_response",
                        "error_description": error_description
                    }
                )
        
        elif response.status_code == 401:
            print(f"[ERROR] Spinergie retornou 401: Chave de API inválida")
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "spinergie_auth_error",
                    "error_description": "Erro de autenticação com Spinergie"
                }
            )
        
        else:
            print(f"[ERROR] Spinergie Status: {response.status_code}")
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "spinergie_error",
                    "error_description": f"Status {response.status_code}"
                }
            )
    
    except requests.Timeout:
        print(f"[ERROR] Timeout")
        raise HTTPException(status_code=504, detail={"error": "spinergie_timeout"})
    
    except requests.ConnectionError as e:
        print(f"[ERROR] Connection error: {e}")
        raise HTTPException(status_code=503, detail={"error": "spinergie_connection_error"})
    
    except HTTPException:
        raise
    
    except Exception as e:
        print(f"[ERROR] Exception: {str(e)}")
        raise HTTPException(status_code=500, detail={"error": "internal_server_error", "error_description": str(e)})


@app.get("/v1/posicao/{mmsi}", 
         response_model=PosicaoAIS,
         tags=["Vessels"],
         summary="Obtém posição de um vessel")
async def get_posicao(mmsi: str, client_id: str = Depends(get_current_client_id)):
    """Retorna a posição geográfica mais recente de um vessel específico do Spinergie."""
    
    print(f"\n[API] GET /v1/posicao/{mmsi} - Client: {client_id}")
    
    try:
        headers = {
            "Authorization": f"Bearer {SPINERGIE_API_KEY}",
            "Content-Type": "application/json"
        }
        
        url = f"{SPINERGIE_BASE_URL}/api/vessels/{mmsi}/position"
        
        print(f"[DEBUG] Chamando Spinergie: GET {url}")
        print(f"[DEBUG] Headers Authorization: Bearer {SPINERGIE_API_KEY[:20]}...")
        
        response = requests.get(
            url,
            headers=headers,
            timeout=60,
            verify=False
        )
        
        print(f"[DEBUG] Spinergie Status Code: {response.status_code}")
        print(f"[DEBUG] Spinergie Response Length: {len(response.text)} caracteres")
        print(f"[DEBUG] Spinergie Content-Type: {response.headers.get('Content-Type')}")
        print(f"[DEBUG] Spinergie Response Text (primeiros 500 chars): '{response.text[:500]}'")
        
        if response.status_code == 200:
            try:
                data = response.json()
                print(f"[DEBUG] JSON parsed successfully")
                
                return PosicaoAIS(
                    mmsi=mmsi,
                    latitude=data.get("latitude", 0.0),
                    longitude=data.get("longitude", 0.0),
                    timestampAquisicao=data.get("timestamp", datetime.now(timezone.utc).isoformat() + "Z")
                )
            
            except json.JSONDecodeError as e:
                error_description = f"Resposta do Spinergie não é JSON válido: {str(e)}"
                if response.headers.get('Content-Type', '').startswith('text/html'):
                    error_description = "Spinergie retornou HTML em vez de JSON."
                print(f"[ERROR] {error_description}")
                raise HTTPException(
                    status_code=502,
                    detail={"error": "spinergie_invalid_response", "error_description": error_description}
                )
        
        elif response.status_code == 404:
            print(f"[ERROR] MMSI não encontrado")
            raise HTTPException(
                status_code=404,
                detail={"error": "not_found", "error_description": f"MMSI '{mmsi}' não encontrado"}
            )
        
        elif response.status_code == 401:
            print(f"[ERROR] Spinergie retornou 401")
            raise HTTPException(
                status_code=502,
                detail={"error": "spinergie_auth_error", "error_description": "Erro de autenticação"}
            )
        
        else:
            print(f"[ERROR] Spinergie Status: {response.status_code}")
            raise HTTPException(
                status_code=502,
                detail={"error": "spinergie_error", "error_description": f"Status {response.status_code}"}
            )
    
    except requests.Timeout:
        print(f"[ERROR] Timeout")
        raise HTTPException(status_code=504, detail={"error": "spinergie_timeout"})
    
    except requests.ConnectionError as e:
        print(f"[ERROR] Connection error: {e}")
        raise HTTPException(status_code=503, detail={"error": "spinergie_connection_error"})
    
    except HTTPException:
        raise
    
    except Exception as e:
        print(f"[ERROR] Exception: {str(e)}")
        raise HTTPException(status_code=500, detail={"error": "internal_server_error", "error_description": str(e)})


if __name__ == "__main__":
    import uvicorn
    print(f"\n[INFO] ========== INICIANDO API IBAMA ==========")
    print(f"[INFO] Documentação: http://localhost:8000/v1/docs\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)