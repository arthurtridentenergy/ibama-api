# models.py
from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_serializer, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class TipoUnidade(str, Enum):
    """
    Tipos de unidade marítima reconhecidos pela API IBAMA.

    Valores exatamente conforme a seção 1.4.3 do Anexo técnico do
    Ofício-Circular nº 4/2025/COEXP/CGMAC/DILIC. Nenhum outro valor é aceito.
    """

    EMBARCACAO_EMERGENCIA = 'EMBARCACAO_EMERGENCIA'
    EMBARCACAO_APOIO = 'EMBARCACAO_APOIO'
    EMBARCACAO_EMERGENCIA_APOIO = 'EMBARCACAO_EMERGENCIA_APOIO'
    UNIDADE_PRODUCAO = 'UNIDADE_PRODUCAO'
    UNIDADE_PERFURACAO = 'UNIDADE_PERFURACAO'
    NAVIO_SISMICO = 'NAVIO_SISMICO'
    NAVIO_ALIVIADOR = 'NAVIO_ALIVIADOR'
    FLOTEL = 'FLOTEL'


class StatusLicenca(str, Enum):
    """Status possíveis para uma licença IBAMA."""

    VIGENTE = 'Vigente'
    RENOVACAO_SOLICITADA = 'Renovação solicitada'
    ANUENCIA = 'Anuência'
    OFICIO = 'Ofício'
    VENCIDA = 'Vencida'
    SUSPENSA = 'Suspensa'
    CANCELADA = 'Cancelada'
    EM_ANALISE = 'Em análise'


# Classificação auxiliar (uso interno, não faz parte do schema do IBAMA).
# UNIDADE_PRODUCAO/UNIDADE_PERFURACAO podem ser fixas OU flutuantes conforme a
# descrição oficial ("fixas ou móveis"), por isso não entram em nenhum dos dois
# grupos abaixo — is_mobile/is_fixed só classificam os tipos que são
# inequivocamente embarcações ou unidades fixas.
_MOBILE_TYPES = {
    TipoUnidade.EMBARCACAO_EMERGENCIA,
    TipoUnidade.EMBARCACAO_APOIO,
    TipoUnidade.EMBARCACAO_EMERGENCIA_APOIO,
    TipoUnidade.NAVIO_SISMICO,
    TipoUnidade.NAVIO_ALIVIADOR,
    TipoUnidade.FLOTEL,
}

_FIXED_TYPES: set = set()

# Padrões de MMSI:
# - Numérico: exatamente 9 dígitos (ex.: 710001720, 538001903)
# - Alfanumérico: identificadores de plataformas fixas sem MMSI numérico
#   (ex.: PPM-1, PCE-1, P-08). Permite letras, dígitos, hífen e underscore,
#   com comprimento entre 2 e 15 caracteres.
_MMSI_NUMERICO_RE = re.compile(r'^\d{9}$')
_MMSI_ALFANUMERICO_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{1,14}$')

# Padrão IMO: 7 dígitos numéricos.
_IMO_RE = re.compile(r'^\d{7}$')

# Padrão de data ISO 8601 (YYYY-MM-DD) para validade de licença.
_DATA_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def _is_numeric_mmsi(value: str) -> bool:
    return bool(_MMSI_NUMERICO_RE.match(value))


def _is_alphanumeric_mmsi(value: str) -> bool:
    return bool(_MMSI_ALFANUMERICO_RE.match(value))


def _validate_mmsi(value: str) -> str:
    """Valida MMSI numérico (9 dígitos) ou alfanumérico (plataformas fixas)."""
    if value is None:
        raise ValueError('MMSI é obrigatório')

    cleaned = str(value).strip()
    if not cleaned:
        raise ValueError('MMSI não pode ser vazio')

    if _is_numeric_mmsi(cleaned) or _is_alphanumeric_mmsi(cleaned):
        return cleaned

    raise ValueError(
        'MMSI deve ser numérico com 9 dígitos (ex.: 710001720) '
        'ou alfanumérico entre 2 e 15 caracteres (ex.: PPM-1, PCE-1)'
    )


def _ensure_iso_z(value: datetime) -> datetime:
    """Garante que o datetime esteja em UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------
class UnidadeMaritima(BaseModel):
    """Representa uma unidade marítima licenciada pelo IBAMA."""

    mmsi: str = Field(
        ...,
        min_length=2,
        max_length=15,
        description=(
            'MMSI numérico de 9 dígitos (embarcações) ou identificador '
            'alfanumérico para plataformas fixas sem MMSI numérico (ex.: PPM-1)'
        ),
        examples=['710001720', 'PPM-1', '538001903'],
    )
    nome: str = Field(
        ...,
        min_length=1,
        description='Nome da unidade marítima',
        examples=['MAERSK VEGA', 'PPM-1', 'P-65'],
    )
    imo: Optional[str] = Field(
        default=None,
        pattern=r'^\d{7}$',
        description='Número IMO de 7 dígitos numéricos, quando aplicável',
        examples=['1234567'],
    )
    tipoUnidade: TipoUnidade = Field(
        ...,
        description='Categoria da unidade (um dos 8 valores oficiais do IBAMA)',
        examples=['EMBARCACAO_EMERGENCIA', 'UNIDADE_PRODUCAO'],
    )
    licencasAutorizadas: List[str] = Field(
        default_factory=list,
        description='Licenças/autorizações vigentes',
        examples=[['LO1234/2025', 'LPS123/2025']],
    )
    disponibilidadeInicio: Optional[datetime] = Field(
        default=None,
        description='Início do período de disponibilidade (ISO 8601 UTC)',
        examples=['2024-01-01T00:00:00Z'],
    )
    disponibilidadeFim: Optional[datetime] = Field(
        default=None,
        description='Fim do período de disponibilidade (ISO 8601 UTC)',
        examples=['2026-12-31T00:00:00Z'],
    )
    # Uso interno/Trident apenas: o schema oficial `UnidadeMaritima` do IBAMA
    # (seção 1.4.1) NÃO inclui latitude/longitude — a posição é servida à parte
    # pelo schema `PosicaoAIS` via GET /v1/posicao/{identificador}. Estes dois
    # campos nunca são expostos na resposta de GET /v1/unidades.
    latitude: Optional[float] = Field(
        default=None,
        ge=-90,
        le=90,
        description='[Uso interno] Latitude estática — não faz parte do schema oficial do IBAMA',
        examples=[-22.9068],
    )
    longitude: Optional[float] = Field(
        default=None,
        ge=-180,
        le=180,
        description='[Uso interno] Longitude estática — não faz parte do schema oficial do IBAMA',
        examples=[-43.1729],
    )

    # Campos de acompanhamento interno da Trident (não fazem parte do schema
    # `UnidadeMaritima` oficial do IBAMA — usados apenas para controle próprio
    # e nunca expostos na resposta de GET /v1/unidades).
    licenca_ibama: Optional[str] = Field(
        default=None,
        description='[Uso interno] Número da licença IBAMA (ex.: LO1572/2020)',
        examples=['LO1572/2020'],
    )
    validade_licenca: Optional[str] = Field(
        default=None,
        description='[Uso interno] Data de validade da licença no formato YYYY-MM-DD',
        examples=['2024-07-11'],
    )
    status_licenca: Optional[StatusLicenca] = Field(
        default=None,
        description='[Uso interno] Status da licença IBAMA',
        examples=['Renovação solicitada', 'Anuência', 'Ofício'],
    )
    observacao_licenca: Optional[str] = Field(
        default=None,
        description='[Uso interno] Observações sobre a licença',
        examples=['Aguardando manifestação do IBAMA'],
    )

    # -----------------------------------------------------------------------
    # Propriedades auxiliares
    # -----------------------------------------------------------------------
    @property
    def is_mobile(self) -> bool:
        """Indica se a unidade é móvel (embarcação ou plataforma móvel)."""
        return self.tipoUnidade in _MOBILE_TYPES

    @property
    def is_fixed(self) -> bool:
        """Indica se a unidade é fixa (plataforma fixa ou unidade de produção)."""
        return self.tipoUnidade in _FIXED_TYPES

    @property
    def has_numeric_mmsi(self) -> bool:
        """Indica se o MMSI é numérico (9 dígitos)."""
        return _is_numeric_mmsi(self.mmsi)

    @property
    def has_alphanumeric_mmsi(self) -> bool:
        """Indica se o MMSI é alfanumérico (identificador de plataforma fixa)."""
        return _is_alphanumeric_mmsi(self.mmsi) and not self.has_numeric_mmsi

    # -----------------------------------------------------------------------
    # Validadores
    # -----------------------------------------------------------------------
    @field_validator('mmsi', mode='before')
    @classmethod
    def _validar_mmsi(cls, value) -> str:
        if value is None:
            raise ValueError('MMSI é obrigatório')
        return _validate_mmsi(str(value))

    @field_validator('imo', mode='before')
    @classmethod
    def _validar_imo(cls, value) -> Optional[str]:
        if value is None or value == '':
            return None
        cleaned = str(value).strip()
        if not _IMO_RE.match(cleaned):
            raise ValueError('IMO deve conter exatamente 7 dígitos numéricos')
        return cleaned

    @field_validator('disponibilidadeInicio', 'disponibilidadeFim', mode='before')
    @classmethod
    def _parse_timestamp(cls, value):
        if value is None or value == '':
            return None
        if isinstance(value, datetime):
            return _ensure_iso_z(value)
        if isinstance(value, str):
            cleaned = value.strip()
            # Normaliza sufixo 'Z' para '+00:00' antes do parse
            if cleaned.endswith('Z'):
                cleaned = cleaned[:-1] + '+00:00'
            try:
                parsed = datetime.fromisoformat(cleaned)
            except ValueError as exc:
                raise ValueError(
                    f'Timestamp inválido (use ISO 8601 com Z): {value}'
                ) from exc
            return _ensure_iso_z(parsed)
        raise ValueError(f'Tipo inválido para timestamp: {type(value)}')

    @field_validator('disponibilidadeInicio', 'disponibilidadeFim', mode='after')
    @classmethod
    def _ensure_timezone(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @field_validator('licencasAutorizadas', mode='before')
    @classmethod
    def _validar_licencas(cls, value) -> List[str]:
        if value is None:
            return []
        if not isinstance(value, (list, tuple)):
            raise ValueError('licencasAutorizadas deve ser uma lista de strings')
        resultado: List[str] = []
        for licenca in value:
            if not isinstance(licenca, str) or not licenca.strip():
                raise ValueError(
                    'Cada licença autorizada deve ser uma string não vazia'
                )
            resultado.append(licenca.strip())
        return resultado

    @field_validator('validade_licenca', mode='before')
    @classmethod
    def _validar_validade_licenca(cls, value) -> Optional[str]:
        if value is None or value == '':
            return None
        cleaned = str(value).strip()
        if not _DATA_RE.match(cleaned):
            raise ValueError(
                'validade_licenca deve estar no formato YYYY-MM-DD'
            )
        return cleaned

    @field_validator('status_licenca', mode='before')
    @classmethod
    def _normalizar_status_licenca(cls, value):
        if value is None or value == '':
            return None
        if isinstance(value, StatusLicenca):
            return value
        cleaned = str(value).strip()
        # Tenta casar com algum valor do enum (case-insensitive em valor)
        for status in StatusLicenca:
            if cleaned == status.value:
                return status
        # Permite strings livres que não constam no enum, convertendo para None
        # apenas se não casar — mas para manter compatibilidade com dados mock,
        # aceitamos o valor como string e tentamos validar.
        try:
            return StatusLicenca(cleaned)
        except ValueError:
            raise ValueError(
                f'status_licenca inválido: {cleaned}. '
                f'Valores aceitos: {[s.value for s in StatusLicenca]}'
            )

    @model_validator(mode='after')
    def _validar_periodo_e_posicao(self) -> 'UnidadeMaritima':
        inicio = self.disponibilidadeInicio
        fim = self.disponibilidadeFim
        if inicio is not None and fim is not None and fim < inicio:
            raise ValueError(
                'disponibilidadeFim deve ser maior ou igual a disponibilidadeInicio'
            )

        if (self.latitude is not None) ^ (self.longitude is not None):
            raise ValueError('Latitude e longitude devem ser informadas juntas')

        return self

    # -----------------------------------------------------------------------
    # Serializadores — garantem timestamps ISO 8601 com sufixo Z
    # -----------------------------------------------------------------------
    @field_serializer('disponibilidadeInicio', 'disponibilidadeFim')
    def _serialize_timestamp_z(self, value: Optional[datetime]) -> Optional[str]:
        if value is None:
            return None
        normalized = _ensure_iso_z(value)
        return normalized.strftime('%Y-%m-%dT%H:%M:%SZ')


class PosicaoAIS(BaseModel):
    """Representa uma posição AIS de uma embarcação ou plataforma."""

    mmsi: str = Field(
        ...,
        min_length=2,
        max_length=15,
        description=(
            'MMSI numérico de 9 dígitos ou identificador alfanumérico '
            'para plataformas fixas'
        ),
        examples=['710001720', 'PPM-1', '538001903'],
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
        description='Data e hora da aquisição da posição (ISO 8601 UTC com Z)',
        examples=['2026-06-25T13:56:11Z'],
    )
    fonte: Optional[str] = Field(
        default=None,
        description=(
            'Origem interna do dado de posição (uso informativo, não faz parte '
            'do schema obrigatório do IBAMA): "spinergie" (tempo real), '
            '"coordenada_fixa" (plataforma hardcoded) ou '
            '"coordenada_fixa_fallback" (embarcação sem retorno da API Spinergie).'
        ),
        examples=['spinergie'],
    )

    @field_validator('mmsi', mode='before')
    @classmethod
    def _validar_mmsi(cls, value) -> str:
        if value is None:
            raise ValueError('MMSI é obrigatório')
        return _validate_mmsi(str(value))

    @field_validator('timestampAquisicao', mode='before')
    @classmethod
    def _normalizar_timestamp(cls, value) -> datetime:
        if isinstance(value, datetime):
            return _ensure_iso_z(value)
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned.endswith('+00:00Z'):
                cleaned = cleaned[:-1]
            if cleaned.endswith('Z'):
                cleaned = cleaned[:-1] + '+00:00'
            try:
                parsed = datetime.fromisoformat(cleaned)
            except ValueError as exc:
                raise ValueError(
                    f'timestampAquisicao inválido (use ISO 8601 com Z): {value}'
                ) from exc
            return _ensure_iso_z(parsed)
        raise ValueError(f'Tipo inválido para timestampAquisicao: {type(value)}')

    @field_validator('timestampAquisicao', mode='after')
    @classmethod
    def _ensure_timezone_aquisicao(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @field_serializer('timestampAquisicao')
    def _serialize_timestamp_aquisicao_z(self, value: datetime) -> str:
        normalized = _ensure_iso_z(value)
        return normalized.strftime('%Y-%m-%dT%H:%M:%SZ')


# ---------------------------------------------------------------------------
# Modelos auxiliares de resposta
#
# Observação: main.py define sua PRÓPRIA cópia de ErroResponse/TokenResponse/
# HealthResponse (é o que a API de fato usa). As classes abaixo não são
# importadas por main.py; mantidas aqui só por compatibilidade e já
# atualizadas para o formato exigido pelo IBAMA (seção 1.6) para não ficarem
# desatualizadas/confusas.
# ---------------------------------------------------------------------------
class ErroResponse(BaseModel):
    """Formato de erro exigido pelo IBAMA (seção 1.6 do Anexo técnico)."""

    error: str = Field(..., description='Código do erro', examples=['not_found'])
    error_description: str = Field(
        ...,
        description='Uma descrição clara do que aconteceu.',
        examples=["A unidade marítima com mmsi 'XXXXXXXXX' não foi encontrada."],
    )


class TokenResponse(BaseModel):
    """Resposta do endpoint de autenticação OAuth 2.0."""

    access_token: str = Field(..., description='Token JWT de acesso')
    token_type: str = Field(default='Bearer', examples=['Bearer'])
    expires_in: int = Field(
        default=3600,
        description='Tempo de expiração do token em segundos',
        examples=[3600],
    )


class HealthResponse(BaseModel):
    """Resposta do endpoint de health check."""

    status: str = Field(default='ok', examples=['ok'])
    timestamp: str = Field(
        ..., description='Timestamp ISO 8601 UTC com Z', examples=['2024-01-15T10:30:00Z']
    )
    version: str = Field(default='1.0.0', examples=['1.0.0'])
    service: str = Field(default='api-ibama', examples=['api-ibama'])