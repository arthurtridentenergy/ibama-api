from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Classe base declarativa para os modelos SQLAlchemy."""

    pass


class Unidade(Base):
    """Representa uma unidade fiscalizadora/monitorada pelo IBAMA."""

    __tablename__ = "unidade"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    identificador: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    mmsi: Mapped[str | None] = mapped_column(String(9), nullable=True, index=True)
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    tipo: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ativo", index=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    posicoes: Mapped[list["Posicao"]] = relationship(
        back_populates="unidade",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('ativo', 'inativo', 'manutencao', 'offline')",
            name="ck_unidade_status",
        ),
        CheckConstraint(
            "latitude IS NULL OR (latitude >= -90 AND latitude <= 90)",
            name="ck_unidade_latitude",
        ),
        CheckConstraint(
            "longitude IS NULL OR (longitude >= -180 AND longitude <= 180)",
            name="ck_unidade_longitude",
        ),
        UniqueConstraint("identificador", name="uq_unidade_identificador"),
        UniqueConstraint("mmsi", name="uq_unidade_mmsi"),
        Index("ix_unidade_tipo_status", "tipo", "status"),
    )

    def __repr__(self) -> str:
        return f"<Unidade(id={self.id}, identificador={self.identificador!r}, nome={self.nome!r})>"


class Posicao(Base):
    """Representa uma posição histórica reportada por uma unidade."""

    __tablename__ = "posicao"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    unidade_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("unidade.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    origem: Mapped[str] = mapped_column(String(64), nullable=False, default="desconhecida")
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    unidade: Mapped["Unidade"] = relationship(back_populates="posicoes")

    __table_args__ = (
        CheckConstraint(
            "latitude >= -90 AND latitude <= 90", name="ck_posicao_latitude"
        ),
        CheckConstraint(
            "longitude >= -180 AND longitude <= 180", name="ck_posicao_longitude"
        ),
        CheckConstraint(
            "origem IN ('ais', 'radar', 'satelite', 'manual', 'desconhecida')",
            name="ck_posicao_origem",
        ),
        Index("ix_posicao_unidade_timestamp", "unidade_id", "timestamp"),
        Index("ix_posicao_timestamp_origem", "timestamp", "origem"),
    )

    def __repr__(self) -> str:
        return (
            f"<Posicao(id={self.id}, unidade_id={self.unidade_id}, "
            f"timestamp={self.timestamp!r})>"
        )


class AuditLog(Base):
    """Registro de auditoria para ações realizadas na API IBAMA."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    acao: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    usuario: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    recurso: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    __table_args__ = (
        CheckConstraint(
            "acao IN ('create', 'read', 'update', 'delete', 'login', 'logout')",
            name="ck_audit_log_acao",
        ),
        Index("ix_audit_log_usuario_timestamp", "usuario", "timestamp"),
        Index("ix_audit_log_acao_timestamp", "acao", "timestamp"),
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog(id={self.id}, acao={self.acao!r}, "
            f"usuario={self.usuario!r}, timestamp={self.timestamp!r})>"
        )