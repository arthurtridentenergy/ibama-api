# data.py
# Dados mock (simulados) de unidades marítimas e posições AIS
# Estes dados representam as informações que, em produção, viriam de um banco de dados

from models import UnidadeMaritima, PosicaoAIS, TipoUnidade
from datetime import datetime, timezone

# Atalho para criar datetime com UTC (o padrão Z exigido pelo IBAMA)
def utc(ano, mes, dia, hora=0, minuto=0, segundo=0):
    return datetime(ano, mes, dia, hora, minuto, segundo, tzinfo=timezone.utc)

# ── Unidades Marítimas cadastradas 
unidades: list[UnidadeMaritima] = [
    UnidadeMaritima(
        nome                 = "Navio Emergência Alpha",
        imo                  = "1234567",
        mmsi                 = "123456789",
        tipoUnidade          = TipoUnidade.EMBARCACAO_EMERGENCIA,
        licencasAutorizadas  = ["LO1234/2025", "LPS123/2025"],
        disponibilidadeInicio= utc(2024, 1, 1),
        disponibilidadeFim   = utc(2026, 12, 31)
    ),
    UnidadeMaritima(
        nome                 = "Plataforma Produção Beta",
        imo                  = None,            # Sem número IMO
        mmsi                 = "987654321",
        tipoUnidade          = TipoUnidade.UNIDADE_PRODUCAO,
        licencasAutorizadas  = ["LP5678/2025"],
        disponibilidadeInicio= utc(2023, 6, 1),
        disponibilidadeFim   = None             # Sem prazo de fim
    ),
    UnidadeMaritima(
        nome                 = "Navio Sísmico Gamma",
        imo                  = "7654321",
        mmsi                 = "112233445",
        tipoUnidade          = TipoUnidade.NAVIO_SISMICO,
        licencasAutorizadas  = ["LS9999/2025"],
        disponibilidadeInicio= utc(2024, 3, 15),
        disponibilidadeFim   = utc(2025, 3, 14)
    ),
]

# ── Posições AIS mais recentes de cada unidade ────────────────────────────────
# Dicionário indexado pelo MMSI para busca rápida O(1)
posicoes: dict[str, PosicaoAIS] = {
    "123456789": PosicaoAIS(
        mmsi               = "123456789",
        latitude           = -22.9068,
        longitude          = -43.1729,
        timestampAquisicao = utc(2026, 3, 5, 10, 30, 0)
    ),
    "987654321": PosicaoAIS(
        mmsi               = "987654321",
        latitude           = -23.5505,
        longitude          = -46.6333,
        timestampAquisicao = utc(2026, 3, 5, 11, 0, 0)
    ),
    "112233445": PosicaoAIS(
        mmsi               = "112233445",
        latitude           = -24.0000,
        longitude          = -47.0000,
        timestampAquisicao = utc(2026, 3, 5, 12, 15, 0)
    ),
}