# data.py — Dados das unidades marítimas (API IBAMA)
#
# Plataformas fixas (P-65, P-08, PPM-1, PCE-1): coordenadas SEMPRE hardcoded.
# Embarcações rastreadas (Maersk Vega, Maersk Ventura): posição em TEMPO REAL
# via API Spinergie, com fallback para coordenada fixa caso a API falhe.

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from models import UnidadeMaritima, PosicaoAIS
from spinergie_service import fetch_vessel_position_async

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constantes de MMSI
# ---------------------------------------------------------------------------
P65_MMSI = "538003593"        # P-65 (MMSI numérico real)
P08_MMSI = "538001903"        # P-08 (MMSI numérico real)
PPM1_MMSI = "PPM-1"           # Plataforma fixa (MMSI alfanumérico)
PCE1_MMSI = "PCE-1"           # Plataforma fixa (MMSI alfanumérico)
MAERSK_VENTURA_MMSI = "710002450"
MAERSK_VEGA_MMSI = "710001720"

# MMSIs das embarcações que devem ter a posição coletada em TEMPO REAL via
# Spinergie. Qualquer MMSI fora deste conjunto (as 4 plataformas) permanece
# 100% hardcoded, sem nenhuma chamada externa.
LIVE_TRACKED_MMSIS = {MAERSK_VENTURA_MMSI, MAERSK_VEGA_MMSI}


# ---------------------------------------------------------------------------
# Dados das unidades marítimas - Bacia de Santos (IBAMA)
# ---------------------------------------------------------------------------
_VESSELS: List[UnidadeMaritima] = [
    # --- Plataformas Fixas ---
    UnidadeMaritima(
        nome="P-65",
        imo="8755039",
        mmsi="538003593",
        tipoUnidade="UNIDADE_PRODUCAO",
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
        imo="8758017",
        mmsi="538001903",
        tipoUnidade="UNIDADE_PRODUCAO",
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
    # MMSI "PPM-1": exceção alfanumérica expressamente autorizada pelo IBAMA
    # (CGMAC) para unidades sem AIS/MMSI numérico próprio.
    UnidadeMaritima(
        nome="PPM-1",
        imo=None,
        mmsi="PPM-1",
        tipoUnidade="UNIDADE_PRODUCAO",
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
    # MMSI "PCE-1": mesma exceção alfanumérica autorizada pelo IBAMA (ver PPM-1 acima).
    UnidadeMaritima(
        nome="PCE-1",
        imo=None,
        mmsi="PCE-1",
        tipoUnidade="UNIDADE_PRODUCAO",
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
    # IMO 9294094 confirmado via cruzamento de MMSI no VesselFinder (verificar
    # novamente contra Equasis/MarineTraffic antes do envio final ao IBAMA).
    UnidadeMaritima(
        nome="MAERSK VENTURA",
        imo="9294094",
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


def _static_positions() -> Dict[str, PosicaoAIS]:
    """
    Coordenadas hardcoded (fonte unica de verdade para plataformas fixas e
    fallback das embarcacoes rastreadas quando a API Spinergie falhar).
    """
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "") + "Z"

    return {
        "538003593": PosicaoAIS(  # P-65 (plataforma fixa - hardcoded)
            mmsi="538003593",
            latitude=-22.701833,
            longitude=-40.677167,
            timestampAquisicao=now,
            fonte="coordenada_fixa",
        ),
        "538001903": PosicaoAIS(  # P-08 (plataforma fixa - hardcoded)
            mmsi="538001903",
            latitude=-22.673167,
            longitude=-40.546500,
            timestampAquisicao=now,
            fonte="coordenada_fixa",
        ),
        "PPM-1": PosicaoAIS(  # plataforma fixa - hardcoded
            mmsi="PPM-1",
            latitude=-22.798,
            longitude=-40.7625,
            timestampAquisicao=now,
            fonte="coordenada_fixa",
        ),
        "PCE-1": PosicaoAIS(  # plataforma fixa - hardcoded
            mmsi="PCE-1",
            latitude=-22.708333,
            longitude=-40.693167,
            timestampAquisicao=now,
            fonte="coordenada_fixa",
        ),
        "710002450": PosicaoAIS(  # Maersk Ventura - fallback se Spinergie falhar
            mmsi="710002450",
            latitude=-22.9068,
            longitude=-43.1729,
            timestampAquisicao=now,
            fonte="coordenada_fixa_fallback",
        ),
        "710001720": PosicaoAIS(  # Maersk Vega - fallback se Spinergie falhar
            mmsi="710001720",
            latitude=-23.5505,
            longitude=-46.6333,
            timestampAquisicao=now,
            fonte="coordenada_fixa_fallback",
        ),
    }


async def get_vessel_position(mmsi: str) -> Optional[PosicaoAIS]:
    """
    Retorna a posicao de uma unidade maritima.

    - Plataformas (P-65, P-08, PPM-1, PCE-1): SEMPRE coordenada hardcoded,
      nenhuma chamada externa e feita para essas unidades.
    - Embarcacoes rastreadas (Maersk Ventura, Maersk Vega): posicao em TEMPO
      REAL, obtida da API Spinergie a cada chamada. Se a API falhar, expirar
      o tempo limite ou nao retornar coordenadas validas, a funcao cai de
      volta para a coordenada fixa cadastrada (fonte="coordenada_fixa_fallback").

    Suporta MMSI numérico (ex: 710002450) e alfanumérico (ex: PPM-1).
    """
    if not mmsi:
        return None

    mmsi_clean = str(mmsi).strip()

    if mmsi_clean in LIVE_TRACKED_MMSIS:
        live = None
        try:
            live = await fetch_vessel_position_async(mmsi_clean)
        except Exception:
            logger.exception(
                "Erro inesperado ao consultar posição em tempo real (Spinergie) "
                "para MMSI %s",
                mmsi_clean,
            )

        if live and live.get("latitude") is not None and live.get("longitude") is not None:
            return PosicaoAIS(
                mmsi=mmsi_clean,
                latitude=live["latitude"],
                longitude=live["longitude"],
                timestampAquisicao=live.get("timestampAquisicao")
                or datetime.now(timezone.utc),
                fonte="spinergie",
            )

        logger.warning(
            "Posição em tempo real indisponível (Spinergie) para MMSI %s; "
            "retornando coordenada fixa de fallback.",
            mmsi_clean,
        )

    return _static_positions().get(mmsi_clean)