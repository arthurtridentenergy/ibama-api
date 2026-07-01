# data.py — Dados hardcoded para API IBAMA (Bacia de Santos)
# Contém plataformas fixas, embarcações de apoio e funções de consulta/simulação.

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Union


# ---------------------------------------------------------------------------
# Modelos de dados (flexíveis: aceitam MMSI numérico ou string)
# ---------------------------------------------------------------------------
@dataclass
class UnidadeMaritima:
    nome: str
    mmsi: str
    tipoUnidade: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    licenca_ibama: str = "LO1572/2020"
    validade_licenca: str = "2024-07-11"
    status_licenca: str = "Renovação solicitada"
    observacao_licenca: str = "Aguardando manifestação do IBAMA"
    imo: Optional[str] = None
    licencasAutorizadas: List[str] = field(default_factory=list)


@dataclass
class PosicaoAIS:
    mmsi: str
    nome: str
    latitude: float
    longitude: float
    timestamp: str
    velocidade: Optional[float] = None
    curso: Optional[float] = None
    status: str = "UNDER WAY USING ENGINE"


# ---------------------------------------------------------------------------
# Dados hardcoded — Plataformas fixas
# ---------------------------------------------------------------------------
PLATAFORMAS: List[UnidadeMaritima] = [
    UnidadeMaritima(
        nome="P-65",
        mmsi="P-65",
        tipoUnidade="PLATAFORMA_FIXA",
        latitude=-22.701833,
        longitude=-40.677167,
        licenca_ibama="LO1572/2020",
        validade_licenca="2024-07-11",
        status_licenca="Renovação solicitada",
        observacao_licenca="Aguardando manifestação do IBAMA",
        licencasAutorizadas=["LO1572/2020"],
    ),
    UnidadeMaritima(
        nome="P-08",
        mmsi="P-08",
        tipoUnidade="PLATAFORMA_FIXA",
        latitude=-22.673167,
        longitude=-40.546500,
        licenca_ibama="LO1572/2020",
        validade_licenca="2024-07-11",
        status_licenca="Renovação solicitada",
        observacao_licenca="Aguardando manifestação do IBAMA",
        licencasAutorizadas=["LO1572/2020"],
    ),
    UnidadeMaritima(
        nome="PPM-1",
        mmsi="PPM-1",
        tipoUnidade="PLATAFORMA_FIXA",
        latitude=-22.798,
        longitude=-40.7625,
        licenca_ibama="LO1572/2020",
        validade_licenca="2024-07-11",
        status_licenca="Renovação solicitada",
        observacao_licenca="Aguardando manifestação do IBAMA",
        licencasAutorizadas=["LO1572/2020"],
    ),
    UnidadeMaritima(
        nome="PCE-1",
        mmsi="PCE-1",
        tipoUnidade="PLATAFORMA_FIXA",
        latitude=-22.708333,
        longitude=-40.693167,
        licenca_ibama="LO1572/2020",
        validade_licenca="2024-07-11",
        status_licenca="Renovação solicitada",
        observacao_licenca="Aguardando manifestação do IBAMA",
        licencasAutorizadas=["LO1572/2020"],
    ),
]


# ---------------------------------------------------------------------------
# Dados hardcoded — Embarcações de apoio
# ---------------------------------------------------------------------------
EMBARCACOES: List[UnidadeMaritima] = [
    UnidadeMaritima(
        nome="Maersk Ventura",
        mmsi="710002450",
        tipoUnidade="EMBARCACAO_APOIO",
        licenca_ibama="LO1572/2020",
        validade_licenca="2024-07-11",
        status_licenca="Anuência",
        observacao_licenca="Licenciamento Ambiental nº 23341605/2025-Coprod/CGMac/Dilic (SEI 23341605)",
        licencasAutorizadas=["LO1572/2020"],
    ),
    UnidadeMaritima(
        nome="Maersk Vega",
        mmsi="710001720",
        tipoUnidade="EMBARCACAO_APOIO",
        licenca_ibama="LO1572/2020",
        validade_licenca="2024-07-11",
        status_licenca="Ofício",
        observacao_licenca="Ofício nº 163/2024/COPROD/CGMAC/DILIC (SEI 18951971)",
        licencasAutorizadas=["LO1572/2020"],
    ),
]


# ---------------------------------------------------------------------------
# Parâmetros de simulação de movimento circular das embarcações
# Cada embarcação orbita uma plataforma de referência.
# ---------------------------------------------------------------------------
SIMULACAO_MOVIMENTO = {
    "710002450": {  # Maersk Ventura -> P-65
        "nome": "Maersk Ventura",
        "plataforma": "P-65",
        "raio": 0.008,          # graus de latitude
        "velocidade_angular": 0.0005,  # rad/s
        "fase": 0.0,
    },
    "710001720": {  # Maersk Vega -> P-08
        "nome": "Maersk Vega",
        "plataforma": "P-08",
        "raio": 0.007,
        "velocidade_angular": 0.0007,
        "fase": math.pi,
    },
}


# ---------------------------------------------------------------------------
# Funções utilitárias
# ---------------------------------------------------------------------------
def _iso_timestamp() -> str:
    """Retorna timestamp ISO 8601 UTC com sufixo Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalizar_mmsi(mmsi: Union[str, int, None]) -> str:
    """Normaliza o MMSI para string, aceitando valor numérico ou string."""
    if mmsi is None:
        return ""
    return str(mmsi).strip()


def get_all_vessels() -> List[UnidadeMaritima]:
    """Retorna todas as unidades marítimas (plataformas + embarcações)."""
    return PLATAFORMAS + EMBARCACOES


def get_all_plataformas() -> List[UnidadeMaritima]:
    """Retorna apenas as plataformas fixas."""
    return list(PLATAFORMAS)


def get_all_embarcacoes() -> List[UnidadeMaritima]:
    """Retorna apenas as embarcações de apoio."""
    return list(EMBARCACOES)


# ---------------------------------------------------------------------------
# Busca por MMSI (numérico ou string) ou por nome
# ---------------------------------------------------------------------------
def buscar_por_mmsi(mmsi: Union[str, int, None]) -> Optional[UnidadeMaritima]:
    """
    Busca uma unidade marítima pelo MMSI.
    Aceita MMSI numérico (int) ou string (ex: 'P-65', '710002450').
    """
    alvo = _normalizar_mmsi(mmsi)
    if not alvo:
        return None

    for unidade in get_all_vessels():
        if unidade.mmsi == alvo:
            return unidade
        # Compara também sem zeros à esquerda quando numérico
        if alvo.isdigit() and unidade.mmsi.isdigit() and int(unidade.mmsi) == int(alvo):
            return unidade
    return None


def buscar_por_nome(nome: str) -> Optional[UnidadeMaritima]:
    """
    Busca uma unidade marítima pelo nome (case-insensitive).
    """
    if not nome:
        return None
    alvo = nome.strip().upper()
    for unidade in get_all_vessels():
        if unidade.nome.strip().upper() == alvo:
            return unidade
    return None


def buscar_unidade(
    mmsi: Union[str, int, None] = None, nome: Optional[str] = None
) -> Optional[UnidadeMaritima]:
    """
    Busca unidade marítima por MMSI e/ou nome.
    Prioriza MMSI quando informado; caso contrário, usa o nome.
    """
    if mmsi is not None:
        resultado = buscar_por_mmsi(mmsi)
        if resultado:
            return resultado
    if nome:
        return buscar_por_nome(nome)
    return None


# ---------------------------------------------------------------------------
# Posição hardcoded das plataformas
# ---------------------------------------------------------------------------
def get_plataforma_position(
    identificador: Union[str, int, None]
) -> Optional[PosicaoAIS]:
    """
    Retorna a posição hardcoded de uma plataforma fixa.
    Aceita MMSI (ex: 'P-65') ou nome (ex: 'P-65', 'PPM-1').
    """
    unidade = buscar_unidade(mmsi=identificador, nome=str(identificador) if identificador else None)
    if unidade is None:
        return None
    if unidade.tipoUnidade != "PLATAFORMA_FIXA":
        return None
    if unidade.latitude is None or unidade.longitude is None:
        return None

    return PosicaoAIS(
        mmsi=unidade.mmsi,
        nome=unidade.nome,
        latitude=unidade.latitude,
        longitude=unidade.longitude,
        timestamp=_iso_timestamp(),
        velocidade=0.0,
        curso=0.0,
        status="AT ANCHOR / FIXED",
    )


def get_all_plataformas_positions() -> List[PosicaoAIS]:
    """Retorna as posições hardcoded de todas as plataformas fixas."""
    posicoes: List[PosicaoAIS] = []
    for plataforma in PLATAFORMAS:
        posicao = get_plataforma_position(plataforma.mmsi)
        if posicao:
            posicoes.append(posicao)
    return posicoes


# ---------------------------------------------------------------------------
# Simulação de movimento em tempo real das embarcações (movimento circular)
# ---------------------------------------------------------------------------
def simular_posicao_embarcacao(
    mmsi: Union[str, int, None],
    timestamp: Optional[datetime] = None,
) -> Optional[PosicaoAIS]:
    """
    Simula o movimento circular de uma embarcação ao redor da plataforma
    de referência, retornando a posição em tempo real.
    """
    alvo = _normalizar_mmsi(mmsi)
    if alvo not in SIMULACAO_MOVIMENTO:
        return None

    config = SIMULACAO_MOVIMENTO[alvo]

    # Localiza a plataforma de referência
    plataforma = buscar_por_nome(config["plataforma"])
    if plataforma is None or plataforma.latitude is None or plataforma.longitude is None:
        return None

    lat_center = plataforma.latitude
    lon_center = plataforma.longitude

    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    t = timestamp.timestamp()
    theta = config["fase"] + config["velocidade_angular"] * t
    raio = config["raio"]

    # Deslocamento em latitude (simples) e longitude (ajustado pela latitude)
    dlat = raio * math.cos(theta)
    dlon = raio * math.sin(theta) / math.cos(math.radians(lat_center))

    lat = lat_center + dlat
    lon = lon_center + dlon

    curso = (math.degrees(theta) + 90.0) % 360.0
    velocidade = 10.0 + 2.0 * math.sin(theta * 2.0)

    return PosicaoAIS(
        mmsi=alvo,
        nome=config["nome"],
        latitude=round(lat, 6),
        longitude=round(lon, 6),
        velocidade=round(abs(velocidade), 2),
        curso=round(curso, 2),
        timestamp=timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        status="UNDER WAY USING ENGINE",
    )


def get_all_embarcacoes_positions(
    timestamp: Optional[datetime] = None,
) -> List[PosicaoAIS]:
    """Retorna as posições simuladas de todas as embarcações em tempo real."""
    posicoes: List[PosicaoAIS] = []
    for embarcacao in EMBARCACOES:
        posicao = simular_posicao_embarcacao(embarcacao.mmsi, timestamp)
        if posicao:
            posicoes.append(posicao)
    return posicoes


# ---------------------------------------------------------------------------
# Função unificada de posição (plataforma fixa ou embarcação simulada)
# ---------------------------------------------------------------------------
def get_posicao(
    identificador: Union[str, int, None],
    timestamp: Optional[datetime] = None,
) -> Optional[PosicaoAIS]:
    """
    Retorna a posição de uma unidade marítima:
    - Plataformas fixas: posição hardcoded.
    - Embarcações: posição simulada em movimento circular.
    """
    alvo = _normalizar_mmsi(identificador)

    # Tenta como embarcação (simulação de movimento)
    if alvo in SIMULACAO_MOVIMENTO:
        return simular_posicao_embarcacao(alvo, timestamp)

    # Tenta como plataforma (posição fixa)
    return get_plataforma_position(alvo)


# ---------------------------------------------------------------------------
# Execução para testes rápidos
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Plataformas ===")
    for p in PLATAFORMAS:
        print(f"{p.nome} (MMSI: {p.mmsi}) -> ({p.latitude}, {p.longitude}) | {p.licenca_ibama} vál. {p.validade_licenca}")

    print("\n=== Embarcações ===")
    for e in EMBARCACOES:
        print(f"{e.nome} (MMSI: {e.mmsi}) | {e.licenca_ibama} vál. {e.validade_licenca}")

    print("\n=== Busca por MMSI ===")
    print(buscar_por_mmsi("P-65"))
    print(buscar_por_mmsi(710002450))

    print("\n=== Busca por nome ===")
    print(buscar_por_nome("maersk vega"))

    print("\n=== Posição plataforma (hardcoded) ===")
    print(get_plataforma_position("P-65"))

    print("\n=== Posição embarcação (simulada) ===")
    print(simular_posicao_embarcacao("710002450"))
    print(simular_posicao_embarcacao(710001720))