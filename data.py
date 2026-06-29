# data.py — Dados mock para testes locais

from datetime import datetime, timezone
from typing import List, Optional
from models import UnidadeMaritima, PosicaoAIS


# MMSI utilizados para testes locais (prefixo 710 = Brasil)
PM1_MMSI = "PPM-1"  # Plataforma fixa (sem MMSI numérico)
PCE1_MMSI = "PCE-1"  # Plataforma fixa (sem MMSI numérico)
P08_MMSI = "538001903"  # MMSI real da P-08
P65_MMSI = "538003593"  # MMSI real da P-65


def get_all_vessels() -> List[UnidadeMaritima]:
    """Retorna lista de vessels com dados reais da Bacia de Santos conforme IBAMA."""

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
            nome="PPM-1",
            imo=None,
            mmsi="PPM-1",
            tipoUnidade="PLATAFORMA_FIXA",
            licencasAutorizadas=["LO1572/2020"],
            disponibilidadeInicio="2023-01-01T00:00:00Z",
            disponibilidadeFim="2027-12-31T00:00:00Z",
            latitude=-22.798,
            longitude=-40.7625,
            licenca_ibama="LO1572/2020",
            validade_licenca="2024-07-11",
            status_licenca="Renovação solicitada",
            observacao_licenca="Aguardando manifestação do IBAMA",
        ),
        UnidadeMaritima(
            nome="PCE-1",
            imo=None,
            mmsi="PCE-1",
            tipoUnidade="PLATAFORMA_FIXA",
            licencasAutorizadas=["LO1572/2020"],
            disponibilidadeInicio="2022-06-01T00:00:00Z",
            disponibilidadeFim="2027-06-01T00:00:00Z",
            latitude=-22.708333,
            longitude=-40.693167,
            licenca_ibama="LO1572/2020",
            validade_licenca="2024-07-11",
            status_licenca="Renovação solicitada",
            observacao_licenca="Aguardando manifestação do IBAMA",
        ),
        UnidadeMaritima(
            nome="P-08",
            imo=None,
            mmsi="538001903",
            tipoUnidade="PLATAFORMA_FIXA",
            licencasAutorizadas=["LO1572/2020"],
            disponibilidadeInicio="2021-03-15T00:00:00Z",
            disponibilidadeFim="2028-03-15T00:00:00Z",
            latitude=-22.673167,
            longitude=-40.546500,
            licenca_ibama="LO1572/2020",
            validade_licenca="2024-07-11",
            status_licenca="Renovação solicitada",
            observacao_licenca="Aguardando manifestação do IBAMA",
        ),
        UnidadeMaritima(
            nome="P-65",
            imo=None,
            mmsi="538003593",
            tipoUnidade="PLATAFORMA_FIXA",
            licencasAutorizadas=["LO1572/2020"],
            disponibilidadeInicio="2020-09-01T00:00:00Z",
            disponibilidadeFim="2029-09-01T00:00:00Z",
            latitude=-22.701833,
            longitude=-40.677167,
            licenca_ibama="LO1572/2020",
            validade_licenca="2024-07-11",
            status_licenca="Renovação solicitada",
            observacao_licenca="Aguardando manifestação do IBAMA",
        ),
        UnidadeMaritima(
            nome="MAERSK VEGA",
            imo=None,
            mmsi="710001720",
            tipoUnidade="EMBARCACAO_APOIO",
            licencasAutorizadas=["LO1572/2020"],
            disponibilidadeInicio="2024-01-01T00:00:00Z",
            disponibilidadeFim=None,
            licenca_ibama="LO1572/2020",
            validade_licenca=None,
            status_licenca="Ofício",
            observacao_licenca="Ofício nº 163/2024/COPROD/CGMAC/DILIC (SEI 18951971)",
        ),
        UnidadeMaritima(
            nome="MAERSK VENTURA",
            imo=None,
            mmsi="710002450",
            tipoUnidade="EMBARCACAO_APOIO",
            licencasAutorizadas=["LO1572/2020"],
            disponibilidadeInicio="2024-01-01T00:00:00Z",
            disponibilidadeFim=None,
            licenca_ibama="LO1572/2020",
            validade_licenca=None,
            status_licenca="Anuência",
            observacao_licenca="Licenciamento Ambiental nº 23341605/2025-Coprod/CGMac/Dilic (SEI 23341605)",
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
    "710001720": PosicaoAIS(  # Maersk Vega
        mmsi="710001720",
        latitude=-22.9068,
        longitude=-43.1729,
        timestampAquisicao=now,
    ),
    "710002450": PosicaoAIS(  # Maersk Ventura
        mmsi="710002450",
        latitude=-23.5505,
        longitude=-46.6333,
        timestampAquisicao=now,
    ),
    "PPM-1": PosicaoAIS(
        mmsi="PPM-1",
        latitude=-22.798,  # Convertido: 22°47.88S
        longitude=-40.7625,  # Convertido: 40°45.75W
        timestampAquisicao=now,
    ),
    "PCE-1": PosicaoAIS(
        mmsi="PCE-1",
        latitude=-22.708333,  # Convertido: 22°42.50S
        longitude=-40.693167,  # Convertido: 40°41.59W
        timestampAquisicao=now,
    ),
    "538001903": PosicaoAIS(  # P-08
        mmsi="538001903",
        latitude=-22.673167,  # Convertido: 22°40.39S
        longitude=-40.546500,  # Convertido: 40°32.79W
        timestampAquisicao=now,
    ),
    "538003593": PosicaoAIS(  # P-65
        mmsi="538003593",
        latitude=-22.701833,  # Convertido: 22°42.11S
        longitude=-40.677167,  # Convertido: 40°40.63W
        timestampAquisicao=now,
    ),
}

    return positions.get(mmsi)