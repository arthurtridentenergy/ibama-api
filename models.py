# models.py
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class TipoUnidade(str, Enum):
    EMBARCACAO_EMERGENCIA = 'EMBARCACAO_EMERGENCIA'
    EMBARCACAO_APOIO = 'EMBARCACAO_APOIO'
    EMBARCACAO_MONITORAMENTO = 'EMBARCACAO_MONITORAMENTO'
    UNIDADE_PRODUCAO = 'UNIDADE_PRODUCAO'
    PLATAFORMA_FIXA = 'PLATAFORMA_FIXA'
    PLATAFORMA_MOVEL = 'PLATAFORMA_MOVEL'

_MOBILE_TYPES = {
    TipoUnidade.EMBARCACAO_EMERGENCIA,
    TipoUnidade.EMBARCACAO_APOIO,
    TipoUnidade.EMBARCACAO_MONITORAMENTO,
    TipoUnidade.PLATAFORMA_MOVEL,
}

_FIXED_TYPES = {TipoUnidade.UNIDADE_PRODUCAO, TipoUnidade.PLATAFORMA_FIXA}


class UnidadeMaritima(BaseModel):
    mmsi: str = Field(
        ...,
        min_length=9,
        max_length=9,
        pattern=r'^\\d{9}$',
        description='MMSI de 9 digitos numericos',
        examples=['710001720'],
    )
    nome: str = Field(
        ...,
        min_length=1,
        description='Nome da unidade maritima',
        examples=['MAERSK VEGA'],
    )
    imo: Optional[str] = Field(
        default=None,
        pattern=r'^\\d{7}$',
        description='Numero IMO de 7 digitos numericos, quando aplicavel',
        examples=['1234567'],
    )
    tipoUnidade: TipoUnidade = Field(
        ...,
        description='Tipo da unidade (embarcacao movel ou plataforma fixa)',
        examples=['EMBARCACAO_EMERGENCIA'],
    )
    licencasAutorizadas: List[str] = Field(
        default_factory=list,
        description='Licencas/autorizacoes vigentes',
        examples=[['LO1234/2025', 'LPS123/2025']],
    )
    disponibilidadeInicio: Optional[datetime] = Field(
        default=None,
        description='Inicio do periodo de disponibilidade',
    )
    disponibilidadeFim: Optional[datetime] = Field(
        default=None,
        description='Fim do periodo de disponibilidade',
    )
    latitude: Optional[float] = Field(
        default=None,
        ge=-90,
        le=90,
        description='Latitude estatica para plataformas fixas',
        examples=[-22.9068],
    )
    longitude: Optional[float] = Field(
        default=None,
        ge=-180,
        le=180,
        description='Longitude estatica para plataformas fixas',
        examples=[-43.1729],
    )
    licenca_ibama: Optional[str] = Field(
        default=None,
        description='Número da licença IBAMA (ex: LO1572/2020)',
        examples=['LO1572/2020'],
    )
    validade_licenca: Optional[str] = Field(
        default=None,
        description='Data de validade da licença (YYYY-MM-DD)',
        examples=['2024-07-11'],
    )
    status_licenca: Optional[str] = Field(
        default=None,
        description='Status da licença (Renovação solicitada, Anuência, Ofício, etc)',
        examples=['Renovação solicitada'],
    )
    observacao_licenca: Optional[str] = Field(
        default=None,
        description='Observações sobre a licença',
        examples=['Aguardando manifestação do IBAMA'],
    )

    @property
    def is_mobile(self) -> bool:
        return self.tipoUnidade in _MOBILE_TYPES

    @property
    def is_fixed(self) -> bool:
        return self.tipoUnidade in _FIXED_TYPES

    @field_validator('disponibilidadeInicio', 'disponibilidadeFim', mode='after')
    @classmethod
    def _ensure_timezone(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @field_validator('licencasAutorizadas', mode='before')
    @classmethod
    def _validar_licencas(cls, value: Optional[List[str]]) -> List[str]:
        if value is None:
            return []
        for licenca in value:
            if not isinstance(licenca, str) or not licenca.strip():
                raise ValueError('Cada licenca autorizada deve ser uma string nao vazia')
        return value

    @model_validator(mode='after')
    def _validar_periodo_e_posicao(self):
        inicio = self.disponibilidadeInicio
        fim = self.disponibilidadeFim
        if inicio is not None and fim is not None and fim < inicio:
            raise ValueError('disponibilidadeFim deve ser maior ou igual a disponibilidadeInicio')

        if (self.latitude is not None) ^ (self.longitude is not None):
            raise ValueError('Latitude e longitude devem ser informadas juntas')

        return self


class PosicaoAIS(BaseModel):
    mmsi: str = Field(
        ...,
        min_length=9,
        max_length=9,
        pattern=r'^\\d{9}$',
        description='MMSI da embarcacao',
        examples=['710001720'],
    )
    latitude: float = Field(
        ...,
        ge=-90,
        le=90,
        description='Latitude em graus decimais',
        examples=[-22.9068],
    )
    longitude: float = Field(
        ...,
        ge=-180,
        le=180,
        description='Longitude em graus decimais',
        examples=[-43.1729],
    )
    timestampAquisicao: datetime = Field(
        ...,
        description='Data e hora da aquisicao da posicao (ISO 8601)',
        examples=['2026-06-25T13:56:11+00:00'],
    )

    @field_validator('timestampAquisicao', mode='before')
    @classmethod
    def _normalizar_timestamp(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if value.endswith('+00:00Z'):
                value = value[:-1]
        return value

    @field_validator('timestampAquisicao', mode='after')
    @classmethod
    def _ensure_timezone_aquisicao(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value