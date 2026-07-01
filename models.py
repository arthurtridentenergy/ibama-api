# models.py
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class TipoUnidade(str, Enum):
    EMBARCACAO_APOIO = "EMBARCACAO_APOIO"
    EMBARCACAO_PRODUCAO = "EMBARCACAO_PRODUCAO"
    PLATAFORMA_FIXA = "PLATAFORMA_FIXA"


class StatusUnidade(str, Enum):
    ATIVA = "ATIVA"
    INATIVA = "INATIVA"
    MANUTENCAO = "MANUTENCAO"


class StatusAIS(str, Enum):
    UNDER_WAY_USING_ENGINE = "UNDER WAY USING ENGINE"
    AT_ANCHOR = "AT ANCHOR"
    MOORED = "MOORED"
    UNDER_WAY_SAILING = "UNDER WAY SAILING"
    NOT_DEFINED = "NOT DEFINED"


# ---------------------------------------------------------------------------
# UnidadeMaritima
# ---------------------------------------------------------------------------
class UnidadeMaritima(BaseModel):
    model_config = ConfigDict(
        use_enum_values=False,
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "nome": "MAERSK VEGA",
                "imo": "1234567",
                "mmsi": "710001720",
                "tipoUnidade": "EMBARCACAO_APOIO",
                "licencasAutorizadas": ["LO1572/2020", "LPS123/2025"],
                "disponibilidadeInicio": "2024-01-01T00:00:00Z",
                "disponibilidadeFim": "2026-12-31T00:00:00Z",
                "status": "ATIVA",
                "observacoes": "Embarcação de apoio licenciada pelo IBAMA para operação na Bacia de Santos",
            }
        },
    )

    nome: str = Field(
        ...,
        min_length=1,
        description="Nome da unidade marítima",
        examples=["MAERSK VEGA", "P-65", "PPM-1"],
    )
    imo: Optional[str] = Field(
        default=None,
        pattern=r"^\d{7}$",
        description="Número IMO de 7 dígitos numéricos, quando aplicável",
        examples=["1234567"],
    )
    mmsi: Optional[str] = Field(
        default=None,
        description="MMSI da embarcação (string numérica de 9 dígitos ou identificador alfanumérico para plataformas fixas sem MMSI)",
        examples=["710001720", "538003593", "PPM-1"],
    )
    tipoUnidade: TipoUnidade = Field(
        ...,
        description="Tipo da unidade marítima conforme classificação IBAMA",
        examples=[TipoUnidade.EMBARCACAO_APOIO],
    )
    licencasAutorizadas: List[str] = Field(
        default_factory=list,
        description="Lista de licenças/autorizações vigentes emitidas pelo IBAMA",
        examples=[["LO1572/2020", "LPS123/2025"]],
    )
    disponibilidadeInicio: Optional[datetime] = Field(
        default=None,
        description="Início do período de disponibilidade da unidade (ISO 8601 UTC)",
        examples=["2024-01-01T00:00:00Z"],
    )
    disponibilidadeFim: Optional[datetime] = Field(
        default=None,
        description="Fim do período de disponibilidade da unidade (ISO 8601 UTC)",
        examples=["2026-12-31T00:00:00Z"],
    )
    status: StatusUnidade = Field(
        default=StatusUnidade.ATIVA,
        description="Status operacional da unidade marítima",
        examples=[StatusUnidade.ATIVA],
    )
    observacoes: Optional[str] = Field(
        default=None,
        description="Observações adicionais sobre a unidade ou licenciamento",
        examples=["Aguardando manifestação do IBAMA quanto à renovação da LO1572/2020"],
    )

    @field_validator("disponibilidadeInicio", "disponibilidadeFim", mode="after")
    @classmethod
    def _ensure_timezone(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @field_validator("licencasAutorizadas", mode="before")
    @classmethod
    def _validar_licencas(cls, value: Optional[List[str]]) -> List[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("licencasAutorizadas deve ser uma lista de strings")
        for licenca in value:
            if not isinstance(licenca, str) or not licenca.strip():
                raise ValueError("Cada licença autorizada deve ser uma string não vazia")
        return value

    @model_validator(mode="after")
    def _validar_periodo(self) -> "UnidadeMaritima":
        inicio = self.disponibilidadeInicio
        fim = self.disponibilidadeFim
        if inicio is not None and fim is not None and fim < inicio:
            raise ValueError(
                "disponibilidadeFim deve ser maior ou igual a disponibilidadeInicio"
            )
        return self


# ---------------------------------------------------------------------------
# PosicaoAIS
# ---------------------------------------------------------------------------
class PosicaoAIS(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "mmsi": "710001720",
                "latitude": -22.9068,
                "longitude": -43.1729,
                "timestampAquisicao": "2025-07-15T13:56:11Z",
                "status": "UNDER WAY USING ENGINE",
            }
        }
    )

    mmsi: str = Field(
        ...,
        min_length=1,
        description="MMSI da embarcação (string)",
        examples=["710001720", "538003593"],
    )
    latitude: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="Latitude em graus decimais",
        examples=[-22.9068],
    )
    longitude: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
        description="Longitude em graus decimais",
        examples=[-43.1729],
    )
    timestampAquisicao: datetime = Field(
        ...,
        description="Data e hora da aquisição da posição no formato ISO 8601 com sufixo Z (UTC)",
        examples=["2025-07-15T13:56:11Z"],
    )
    status: Optional[str] = Field(
        default=None,
        description="Status de navegação AIS da embarcação",
        examples=["UNDER WAY USING ENGINE", "AT ANCHOR", "MOORED"],
    )

    @field_validator("timestampAquisicao", mode="before")
    @classmethod
    def _normalizar_timestamp(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if value.endswith("+00:00Z"):
                value = value[:-1]
        return value

    @field_validator("timestampAquisicao", mode="after")
    @classmethod
    def _ensure_timezone_aquisicao(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


# ---------------------------------------------------------------------------
# Licenca
# ---------------------------------------------------------------------------
class Licenca(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "numero": "LO1572/2020",
                "dataEmissao": "2020-07-11",
                "dataValidade": "2024-07-11",
                "tipo": "Licença de Operação (LO)",
                "unidadeMaritima": {
                    "nome": "P-65",
                    "imo": None,
                    "mmsi": "538003593",
                    "tipoUnidade": "PLATAFORMA_FIXA",
                    "licencasAutorizadas": ["LO1572/2020"],
                    "disponibilidadeInicio": "2020-09-01T00:00:00Z",
                    "disponibilidadeFim": "2029-09-01T00:00:00Z",
                    "status": "ATIVA",
                    "observacoes": "Renovação solicitada - Aguardando manifestação do IBAMA",
                },
            }
        }
    )

    numero: str = Field(
        ...,
        min_length=1,
        description="Número da licença emitida pelo IBAMA",
        examples=["LO1572/2020"],
    )
    dataEmissao: Optional[datetime] = Field(
        default=None,
        description="Data de emissão da licença (ISO 8601)",
        examples=["2020-07-11T00:00:00Z"],
    )
    dataValidade: Optional[datetime] = Field(
        default=None,
        description="Data de validade da licença (ISO 8601)",
        examples=["2024-07-11T00:00:00Z"],
    )
    tipo: str = Field(
        ...,
        min_length=1,
        description="Tipo da licença (LO, LPS, LI, LP, etc.)",
        examples=["Licença de Operação (LO)"],
    )
    unidadeMaritima: Optional[UnidadeMaritima] = Field(
        default=None,
        description="Unidade marítima vinculada à licença",
    )

    @field_validator("dataEmissao", "dataValidade", mode="after")
    @classmethod
    def _ensure_timezone(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @model_validator(mode="after")
    def _validar_datas(self) -> "Licenca":
        if (
            self.dataEmissao is not None
            and self.dataValidade is not None
            and self.dataValidade < self.dataEmissao
        ):
            raise ValueError("dataValidade deve ser maior ou igual a dataEmissao")
        return self


# ---------------------------------------------------------------------------
# TokenResponse
# ---------------------------------------------------------------------------
class TokenResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJpYmFtYS1jbGllbnQiLCJleHAiOjE3MDAwMDAwMDB9.signature",
                "token_type": "Bearer",
                "expires_in": 3600,
            }
        }
    )

    access_token: str = Field(
        ...,
        description="Token JWT de acesso para autenticação nos endpoints protegidos",
        examples=[
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJpYmFtYS1jbGllbnQifQ.signature"
        ],
    )
    token_type: str = Field(
        default="Bearer",
        description="Tipo do token retornado",
        examples=["Bearer"],
    )
    expires_in: int = Field(
        default=3600,
        ge=1,
        description="Tempo de expiração do token em segundos",
        examples=[3600],
    )


# ---------------------------------------------------------------------------
# ErrorResponse
# ---------------------------------------------------------------------------
class ErrorResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status_code": 404,
                "detail": "Embarcação com MMSI 999999999 não encontrada",
                "timestamp": "2025-07-15T13:56:11Z",
            }
        }
    )

    status_code: int = Field(
        ...,
        ge=100,
        le=599,
        description="Código HTTP do erro",
        examples=[404],
    )
    detail: str = Field(
        ...,
        min_length=1,
        description="Mensagem descritiva do erro",
        examples=["Embarcação com MMSI 999999999 não encontrada"],
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Data e hora do erro no formato ISO 8601 com sufixo Z (UTC)",
        examples=["2025-07-15T13:56:11Z"],
    )

    @field_validator("timestamp", mode="before")
    @classmethod
    def _normalizar_timestamp(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if value.endswith("+00:00Z"):
                value = value[:-1]
        return value

    @field_validator("timestamp", mode="after")
    @classmethod
    def _ensure_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value