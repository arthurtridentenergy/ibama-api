# models.py — Modelos Pydantic para a API IBAMA

from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum


class TipoUnidade(str, Enum):
    """Tipos de unidade marítima conforme especificação IBAMA"""
    EMBARCACAO_EMERGENCIA = "EMBARCACAO_EMERGENCIA"
    EMBARCACAO_APOIO = "EMBARCACAO_APOIO"
    EMBARCACAO_EMERGENCIA_APOIO = "EMBARCACAO_EMERGENCIA_APOIO"
    UNIDADE_PRODUCAO = "UNIDADE_PRODUCAO"
    UNIDADE_PERFURACAO = "UNIDADE_PERFURACAO"
    NAVIO_SISMICO = "NAVIO_SISMICO"
    NAVIO_ALIVIADOR = "NAVIO_ALIVIADOR"
    FLOTEL = "FLOTEL"


class UnidadeMaritima(BaseModel):
    """Modelo de unidade marítima conforme especificação IBAMA 1.4.1"""
    nome: str = Field(..., description="Nome comercial ou de operação da unidade")
    imo: Optional[str] = Field(None, description="Número IMO (7 dígitos) ou nulo")
    mmsi: Optional[str] = Field(None, description="Número MMSI (9 dígitos) - Nulo para plataformas")
    tipoUnidade: TipoUnidade = Field(..., description="Categoria da unidade conforme enum")
    licencasAutorizadas: List[str] = Field(default_factory=list, description="Lista de licenças ativas com números, validade e observações")
    disponibilidadeInicio: str = Field(..., description="Data/hora ISO 8601 UTC com Z")
    disponibilidadeFim: Optional[str] = Field(None, description="Data/hora ISO 8601 UTC com Z ou nulo")

    class Config:
        schema_extra = {
            "example": {
                "nome": "MAERSK VEGA",
                "imo": "9294082",
                "mmsi": "710001720",
                "tipoUnidade": "EMBARCACAO_EMERGENCIA_APOIO",
                "licencasAutorizadas": ["Ofício nº 163/2024/COPROD/CGMAC/DILIC (SEI 18951971)"],
                "disponibilidadeInicio": "2024-01-01T00:00:00Z",
                "disponibilidadeFim": None
            }
        }


class PosicaoAIS(BaseModel):
    """Modelo de posição geográfica conforme especificação IBAMA 1.4.2"""
    mmsi: str = Field(..., description="Número MMSI (9 dígitos)")
    latitude: float = Field(..., description="Coordenada de latitude em formato decimal")
    longitude: float = Field(..., description="Coordenada de longitude em formato decimal")
    timestampAquisicao: str = Field(..., description="Data/hora ISO 8601 UTC com Z")

    class Config:
        schema_extra = {
            "example": {
                "mmsi": "710001720",
                "latitude": -23.5505,
                "longitude": -46.6333,
                "timestampAquisicao": "2026-03-12T14:30:00Z"
            }
        }