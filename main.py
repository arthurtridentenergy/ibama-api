import os
import httpx
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from pydantic import BaseModel

# --- Configurações e Constantes ---
SPINERGIE_API_KEY = os.getenv("SPINERGIE_API_KEY", "your_api_key_here")
SPINERGIE_BASE_URL = "https://api.spinergie.com/v1"
AUTH_TOKEN = "maersk-token-2024"  # Token estático para exemplo de validação

# --- Modelos de Dados ---
class PosicaoResponse(BaseModel):
    nome: str
    mmsi: str
    latitude: float
    longitude: float
    timestamp: str
    status: str

class Unidade(BaseModel):
    nome: str
    mmsi: str
    tipo: str

# --- Dados Hardcoded (Plataformas) ---
PLATAFORMAS = [
    {"nome": "P-65", "mmsi": "P65", "lat": -22.7450, "lon": -40.4560, "tipo": "Plataforma"},
    {"nome": "P-08", "mmsi": "P08", "lat": -22.1230, "lon": -40.1230, "tipo": "Plataforma"},
    {"nome": "PPM-1", "mmsi": "PPM1", "lat": -22.5550, "lon": -40.8880, "tipo": "Plataforma"},
    {"nome": "PCE-1", "mmsi": "PCE1", "lat": -22.9990, "lon": -40.2220, "tipo": "Plataforma"},
]

# --- Embarcações Spinergie ---
EMBARCACOES_MAERSK = [
    {"nome": "Maersk Ventura", "mmsi": "710002450", "tipo": "Vessel"},
    {"nome": "Maersk Vega", "mmsi": "710001720", "tipo": "Vessel"},
]

# --- Inicialização do App e Rate Limiting ---
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Maersk Unit Tracking API", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

security = HTTPBearer()

# --- Helpers ---
def get_timestamp_z():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if credentials.credentials != AUTH_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou ausente",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials

async def fetch_spinergie_data(mmsi: str) -> Optional[Dict[str, Any]]:
    """Tenta buscar dados na API Spinergie com fallback."""
    try:
        async with httpx.AsyncClient() as client:
            # Exemplo de chamada hipotética à API Spinergie
            response = await client.get(
                f"{SPINERGIE_BASE_URL}/vessels/{mmsi}/position",
                headers={"Authorization": f"Bearer {SPINERGIE_API_KEY}"},
                timeout=3.0
            )
            if response.status_code == 200:
                data = response.json()
                return {
                    "lat": float(data.get("latitude")),
                    "lon": float(data.get("longitude")),
                    "timestamp": data.get("timestamp", get_timestamp_z())
                }
    except Exception:
        pass
    return None

# --- Endpoints ---

@app.get("/v1/unidades", response_model=List[Unidade])
@limiter.limit("10/minute")
async def list_unidades(request: Request, token: str = Depends(verify_token)):
    """Lista todas as unidades (Plataformas e Embarcações)."""
    unidades = []
    for p in PLATAFORMAS:
        unidades.append({"nome": p["nome"], "mmsi": p["mmsi"], "tipo": p["tipo"]})
    for e in EMBARCACOES_MAERSK:
        unidades.append({"nome": e["nome"], "mmsi": e["mmsi"], "tipo": e["tipo"]})
    return unidades

@app.get("/v1/posicao/{identificador}", response_model=PosicaoResponse)
@limiter.limit("20/minute")
async def get_posicao(request: Request, identificador: str, token: str = Depends(verify_token)):
    """Busca posição por MMSI (numérico/alfanumérico) ou Nome."""
    search_term = identificador.strip().upper()

    # 1. Verificar Plataformas (Hardcoded)
    for p in PLATAFORMAS:
        if search_term in [p["nome"].upper(), p["mmsi"].upper()]:
            return {
                "nome": p["nome"],
                "mmsi": p["mmsi"],
                "latitude": p["lat"],
                "longitude": p["lon"],
                "timestamp": get_timestamp_z(),
                "status": "Fixed"
            }

    # 2. Verificar Embarcações Maersk (Spinergie + Fallback)
    for e in EMBARCACOES_MAERSK:
        if search_term in [e["nome"].upper(), e["mmsi"].upper()]:
            # Tenta Spinergie
            real_time_data = await fetch_spinergie_data(e["mmsi"])
            
            if real_time_data:
                return {
                    "nome": e["nome"],
                    "mmsi": e["mmsi"],
                    "latitude": real_time_data["lat"],
                    "longitude": real_time_data["lon"],
                    "timestamp": real_time_data["timestamp"],
                    "status": "Real-time (Spinergie)"
                }
            else:
                # Fallback se Spinergie falhar ou não retornar dados
                # Coordenadas de fallback baseadas no MMSI
                fallback_coords = {
                    "710002450": {"lat": -23.1234, "lon": -41.5678}, # Ventura
                    "710001720": {"lat": -23.4567, "lon": -41.8901}  # Vega
                }
                coords = fallback_coords.get(e["mmsi"], {"lat": 0.0, "lon": 0.0})
                return {
                    "nome": e["nome"],
                    "mmsi": e["mmsi"],
                    "latitude": coords["lat"],
                    "longitude": coords["lon"],
                    "timestamp": get_timestamp_z(),
                    "status": "Fallback (Offline)"
                }

    raise HTTPException(status_code=404, detail="Unidade não encontrada")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)