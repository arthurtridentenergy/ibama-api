# data.py — Dados mock para testes locais

from datetime import datetime, timezone
from typing import List, Optional
from models import UnidadeMaritima, PosicaoAIS


def get_all_vessels() -> List[UnidadeMaritima]:
    """Retorna lista de vessels mock para testes"""
    
    vessels = [
        UnidadeMaritima(
            nome="Navio Emergência Alpha",
            imo="1234567",
            mmsi="123456789",
            tipoUnidade="EMBARCACAO_EMERGENCIA",
            licencasAutorizadas=["LO1234/2025", "LPS123/2025"],
            disponibilidadeInicio="2024-01-01T00:00:00Z",
            disponibilidadeFim="2026-12-31T00:00:00Z"
        ),
        UnidadeMaritima(
            nome="Navio Apoio Beta",
            imo="7654321",
            mmsi="987654321",
            tipoUnidade="EMBARCACAO_APOIO",
            licencasAutorizadas=["LO5678/2025"],
            disponibilidadeInicio="2024-02-01T00:00:00Z",
            disponibilidadeFim=None
        ),
        UnidadeMaritima(
            nome="Plataforma Produção Gamma",
            imo="5555555",
            mmsi="555555555",
            tipoUnidade="UNIDADE_PRODUCAO",
            licencasAutorizadas=["LPS999/2025", "LO9999/2025"],
            disponibilidadeInicio="2024-01-15T00:00:00Z",
            disponibilidadeFim="2027-01-15T00:00:00Z"
        )
    ]
    
    return vessels


def get_vessel_position(mmsi: str) -> Optional[PosicaoAIS]:
    """Retorna posição mock para um vessel específico"""
    
    # Dados mock de posições
    positions = {
        "123456789": PosicaoAIS(
            mmsi="123456789",
            latitude=-22.9068,
            longitude=-43.1729,
            timestampAquisicao=datetime.now(timezone.utc).isoformat() + "Z"
        ),
        "987654321": PosicaoAIS(
            mmsi="987654321",
            latitude=-23.5505,
            longitude=-46.6333,
            timestampAquisicao=datetime.now(timezone.utc).isoformat() + "Z"
        ),
        "555555555": PosicaoAIS(
            mmsi="555555555",
            latitude=-27.1448,
            longitude=-48.5923,
            timestampAquisicao=datetime.now(timezone.utc).isoformat() + "Z"
        )
    }
    
    return positions.get(mmsi)