# models.py — conforme especificação IBAMA/CGMAC
# timestampAquisicao: string ISO 8601 UTC (ex: 2024-01-01T00:00:00Z)

from pydantic import BaseModel
from typing import Optional, List


class UnidadeMaritima(BaseModel):
    nome:                  str
    imo:                   Optional[str]       = None
    mmsi:                  str
    tipoUnidade:           Optional[str]       = "EMBARCACAO_APOIO"
    licencasAutorizadas:   Optional[List[str]] = []
    disponibilidadeInicio: Optional[str]       = None
    disponibilidadeFim:    Optional[str]       = None


class PosicaoAIS(BaseModel):
    mmsi:               str
    latitude:           Optional[float]        = None
    longitude:          Optional[float]        = None
    # ✅ String ISO 8601 conforme exigido pelo IBAMA
    timestampAquisicao: Optional[str]          = None