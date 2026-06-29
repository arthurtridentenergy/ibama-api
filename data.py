# data.py — Dados mock para testes locais

from datetime import datetime, timezone
from typing import List, Optional
from models import UnidadeMaritima, PosicaoAIS


# MMSI utilizados para testes locais (prefixo 710 = Brasil)
PPM1_MMSI = "710000111"
PCE1_MMSI = "710000222"
P08_MMSI = "710000333"
P65_MMSI = "710000444"


def get_all_vessels() -> List[UnidadeMaritima]:
    """Retorna lista de vessels mock para testes, incluindo unidades reais da Bacia de Santos."""

    vessels = [
        UnidadeMaritima(
            nome="Navio Emergência Alpha",
            imo="1234567",
            mmsi="123456789",
            tipoUnidade="EMBARCACAO_EMERGENCIA",
            licencasAutorizadas=["LO1234/2025", "LPS123/2025"],
            disponibilidadeInicio="2024-01-01T00:00:00Z",
            disponibilidadeFim="2026-12-31T00:00:00Z",
        ),
        UnidadeMaritima(
            nome="Navio Apoio Beta",
            imo="7654321",
            mmsi="987654321",
            tipoUnidade="EMBARCACAO_APOIO",
            licencasAutorizadas=["LO5678/2025"],
            disponibilidadeInicio="2024-02-01T00:00:00Z",
            disponibilidadeFim=None,
        ),
        UnidadeMaritima(
            nome="Plataforma Produção Gamma",
            imo="5555555",
            mmsi="555555555",
            tipoUnidade="UNIDADE_PRODUCAO",
            licencasAutorizadas=["LPS999/2025", "LO9999/2025"],
            disponibilidadeInicio="2024-01-15T00:00:00Z",
            disponibilidadeFim="2027-01-15T00:00:00Z",
        ),
        UnidadeMaritima(
            nome="PPM-1",
            imo="9876543",
            mmsi=PPM1_MMSI,
            tipoUnidade="UNIDADE_PRODUCAO",
            licencasAutorizadas=["LPS-123/2025", "LO-456/2025"],
            disponibilidadeInicio="2023-01-01T00:00:00Z",
            disponibilidadeFim="2027-12-31T00:00:00Z",
        ),
        UnidadeMaritima(
            nome="PCE-1",
            imo="8765432",
            mmsi=PCE1_MMSI,
            tipoUnidade="UNIDADE_PRODUCAO",
            licencasAutorizadas=["LPS-789/2025", "LO-012/2025"],
            disponibilidadeInicio="2022-06-01T00:00:00Z",
            disponibilidadeFim="2027-06-01T00:00:00Z",
        ),
        UnidadeMaritima(
            nome="P-08",
            imo="7654321",
            mmsi=P08_MMSI,
            tipoUnidade="UNIDADE_PRODUCAO",
            licencasAutorizadas=["LPS-345/2025", "LO-678/2025"],
            disponibilidadeInicio="2021-03-15T00:00:00Z",
            disponibilidadeFim="2028-03-15T00:00:00Z",
        ),
        UnidadeMaritima(
            nome="P-65",
            imo="6543210",
            mmsi=P65_MMSI,
            tipoUnidade="UNIDADE_PRODUCAO",
            licencasAutorizadas=["LPS-901/2025", "LO-234/2025"],
            disponibilidadeInicio="2020-09-01T00:00:00Z",
            disponibilidadeFim="2029-09-01T00:00:00Z",
        ),
    ]

    return vessels


def get_vessel_position(mmsi: str) -> Optional[PosicaoAIS]:
    """Retorna posição mock para um vessel específico, com coordenadas realistas da Bacia de Santos."""

    now = datetime.now(timezone.utc).isoformat() + "Z"

    positions = {
        "123456789": PosicaoAIS(
            mmsi="123456789",
            latitude=-22.9068,
            longitude=-43.1729,
            timestampAquisicao=now,
        ),
        "987654321": PosicaoAIS(
            mmsi="987654321",
            latitude=-23.5505,
            longitude=-46.6333,
            timestampAquisicao=now,
        ),
        "555555555": PosicaoAIS(
            mmsi="555555555",
            latitude=-27.1448,
            longitude=-48.5923,
            timestampAquisicao=now,
        ),
        PPM1_MMSI: PosicaoAIS(
            mmsi=PPM1_MMSI,
            latitude=-24.5123,
            longitude=-44.5123,
            timestampAquisicao=now,
        ),
        PCE1_MMSI: PosicaoAIS(
            mmsi=PCE1_MMSI,
            latitude=-25.0123,
            longitude=-43.8234,
            timestampAquisicao=now,
        ),
        P08_MMSI: PosicaoAIS(
            mmsi=P08_MMSI,
            latitude=-26.2345,
            longitude=-45.5678,
            timestampAquisicao=now,
        ),
        P65_MMSI: PosicaoAIS(
            mmsi=P65_MMSI,
            latitude=-25.6789,
            longitude=-44.2345,
            timestampAquisicao=now,
        ),
    }

    return positions.get(mmsi)