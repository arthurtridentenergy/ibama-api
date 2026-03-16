from fastapi import FastAPI, Depends, HTTPException, Header
from pydantic import BaseModel
from typing import Optional, List
import jwt
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

# Config
CLIENT_ID = os.getenv("CLIENT_ID", "ibama_client")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "seu_secret")
JWT_SECRET = os.getenv("JWT_SECRET_KEY", "seu_jwt_secret")

app = FastAPI(
    title="API Unidades Marítimas IBAMA",
    version="1.0.0"
)

# Models
class TokenRequest(BaseModel):
    grant_type: str = "client_credentials"
    client_id: str
    client_secret: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int

class UnidadeMaritima(BaseModel):
    nome: str
    imo: str
    mmsi: str
    tipoUnidade: str
    licencasAutorizadas: List[str]
    disponibilidadeInicio: str
    disponibilidadeFim: Optional[str] = None

class PosicaoAIS(BaseModel):
    mmsi: str
    latitude: float
    longitude: float
    timestampAquisicao: str

# Auth
def criar_token(client_id: str) -> str:
    payload = {
        "sub": client_id,
        "exp": datetime.utcnow() + timedelta(hours=1),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def verificar_token(authorization: Optional[str] = Header(None)) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Token não fornecido")
    
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Inválido")
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload.get("sub")
    except:
        raise HTTPException(status_code=401, detail="Token inválido")

# Endpoints
@app.get("/")
async def root():
    return {"message": "API IBAMA v1.0.0"}

@app.post("/auth/token", response_model=TokenResponse)
async def get_token(request: TokenRequest):
    if request.client_id != CLIENT_ID or request.client_secret != CLIENT_SECRET:
        raise HTTPException(status_code=401, detail="Inválido")
    
    return {
        "access_token": criar_token(request.client_id),
        "token_type": "Bearer",
        "expires_in": 3600
    }

@app.get("/v1/unidades", response_model=List[UnidadeMaritima])
async def listar_unidades(user: str = Depends(verificar_token)):
    return [
        {
            "nome": "Plataforma P-01",
            "imo": "1234567",
            "mmsi": "123456789",
            "tipoUnidade": "UNIDADE_PRODUCAO",
            "licencasAutorizadas": ["LO1234/2025"],
            "disponibilidadeInicio": "2024-01-01T00:00:00Z",
            "disponibilidadeFim": "2026-12-31T23:59:59Z"
        }
    ]

@app.get("/v1/posicao/{mmsi}", response_model=PosicaoAIS)
async def obter_posicao(mmsi: str, user: str = Depends(verificar_token)):
    if mmsi == "123456789":
        return {
            "mmsi": "123456789",
            "latitude": -22.9068,
            "longitude": -42.0281,
            "timestampAquisicao": datetime.utcnow().isoformat() + "Z"
        }
    raise HTTPException(status_code=404, detail="MMSI não encontrado")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)