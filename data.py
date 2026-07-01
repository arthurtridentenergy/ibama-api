# data.py — Dados mock para testes locais (API IBAMA)

from datetime import datetime, timezone
from typing import List, Optional

from models import UnidadeMaritima, PosicaoAIS


# ---------------------------------------------------------------------------
# Constantes de MMSI
# ---------------------------------------------------------------------------
P65_MMSI = "538003593"        # P-65 (MMSI numérico real)
P08_MMSI = "538001903"        # P-08 (MMSI numérico real)
PPM1_MMSI = "PPM-1"           # Plataforma fixa (MMSI alfanumérico)
PCE1_MMSI = "PCE-1"           # Plataforma fixa (MMSI alfanumérico)
MAERSK_VENTURA_MMSI = "710002450"
MAERSK_VEGA_MMSI = "710001720"


# ---------------------------------------------------------------------------
# Dados das unidades marítimas — Bacia de Santos (IBAMA)
# ---------------------------------------------------------------------------
_VESSELS: List[UnidadeMaritima] = [
    # --- Plataformas Fixas ---
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
    # --- Embarcações de Apoio ---
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
]


# ---------------------------------------------------------------------------
# Funções de acesso
# ---------------------------------------------------------------------------
def get_all_vessels() -> List[UnidadeMaritima]:
    """Retorna lista de unidades marítimas com dados reais da Bacia de Santos conforme IBAMA."""
    return list(_VESSELS)


def get_vessel_by_mmsi(mmsi: str) -> Optional[UnidadeMaritima]:
    """
    Busca unidade marítima por MMSI.

    Suporta MMSI numérico (ex: 710002450, 538003593) e alfanumérico
    (ex: PPM-1, PCE-1).
    """
    if not mmsi:
        return None
    mmsi_clean = str(mmsi).strip()
    for vessel in _VESSELS:
        if vessel.mmsi == mmsi_clean:
            return vessel
    return None


def get_vessel_by_name(name: str) -> Optional[UnidadeMaritima]:
    """
    Busca unidade marítima por nome (case-insensitive).

    Exemplos: "P-65", "maersk ventura", "PPM-1".
    """
    if not name:
        return None
    name_clean = str(name).strip().upper()
    for vessel in _VESSELS:
        if vessel.nome.strip().upper() == name_clean:
            return vessel
    return None


def get_vessel_position(mmsi: str) -> Optional[PosicaoAIS]:
    """
    Retorna posição mock para um vessel específico, com coordenadas
    realistas da Bacia de Santos.

    Suporta MMSI numérico (ex: 710002450) e alfanumérico (ex: PPM-1).
    """
    if not mmsi:
        return None

    mmsi_clean = str(mmsi).strip()
    now = datetime.now(timezone.utc).isoformat() + "Z"

    positions = {
        "538003593": PosicaoAIS(  # P-65
            mmsi="538003593",
            latitude=-22.701833,
            longitude=-40.677167,
            timestampAquisicao=now,
        ),
        "538001903": PosicaoAIS(  # P-08
            mmsi="538001903",
            latitude=-22.673167,
            longitude=-40.546500,
            timestampAquisicao=now,
        ),
        "PPM-1": PosicaoAIS(
            mmsi="PPM-1",
            latitude=-22.798,
            longitude=-40.7625,
            timestampAquisicao=now,
        ),
        "PCE-1": PosicaoAIS(
            mmsi="PCE-1",
            latitude=-22.708333,
            longitude=-40.693167,
            timestampAquisicao=now,
        ),
        "710002450": PosicaoAIS(  # Maersk Ventura
            mmsi="710002450",
            latitude=-22.9068,
            longitude=-43.1729,
            timestampAquisicao=now,
        ),
        "710001720": PosicaoAIS(  # Maersk Vega
            mmsi="710001720",
            latitude=-23.5505,
            longitude=-46.6333,
            timestampAquisicao=now,
        ),
    }

    return positions.get(mmsi_clean)