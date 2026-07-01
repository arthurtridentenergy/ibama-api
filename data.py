import logging
import asyncio
from datetime import datetime
from typing import List, Optional, Sequence

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, select, update, delete, func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker, AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload

# Configuração de Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("data_layer")

# Configuração do Banco de Dados (SQLite Async para exemplo)
DATABASE_URL = "sqlite+aiosqlite:///./ibama_monitor.db"
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# Modelos
class Base(AsyncAttrs, DeclarativeBase):
    pass

class Unidade(Base):
    __tablename__ = "unidades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    tipo: Mapped[str] = mapped_column(String(50), nullable=False)  # Ex: FPSO, SS, Fixed
    status: Mapped[str] = mapped_column(String(20), default="Ativa")
    
    posicoes: Mapped[List["Posicao"]] = relationship("Posicao", back_populates="unidade", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Unidade(id={self.id}, nome='{self.nome}')>"

class Posicao(Base):
    __tablename__ = "posicoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    unidade_id: Mapped[int] = mapped_column(ForeignKey("unidades.id"), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    unidade: Mapped["Unidade"] = relationship("Unidade", back_populates="posicoes")

    def __repr__(self):
        return f"<Posicao(id={self.id}, lat={self.latitude}, lon={self.longitude})>"

# 1) Inicializar Banco de Dados
async def init_db():
    logger.info("Iniciando criação das tabelas...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Tabelas criadas com sucesso.")

# 2) Seed de Dados Iniciais (Plataformas IBAMA)
async def seed_data():
    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Verificar se já existem dados
            result = await session.execute(select(func.count(Unidade.id)))
            count = result.scalar()
            
            if count == 0:
                logger.info("Semeando dados iniciais de plataformas IBAMA...")
                plataformas = [
                    Unidade(nome="P-50", tipo="FPSO", status="Ativa"),
                    Unidade(nome="P-51", tipo="Semi-Submersível", status="Ativa"),
                    Unidade(nome="P-53", tipo="FPSO", status="Manutenção"),
                    Unidade(nome="P-62", tipo="FPSO", status="Ativa"),
                    Unidade(nome="P-70", tipo="FPSO", status="Ativa")
                ]
                session.add_all(plataformas)
                logger.info("Seed concluído.")
            else:
                logger.info("Banco de dados já contém registros. Pulando seed.")

# 3) Funções CRUD para Unidade
async def create_unidade(nome: str, tipo: str, status: str = "Ativa") -> Unidade:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            nova_unidade = Unidade(nome=nome, tipo=tipo, status=status)
            session.add(nova_unidade)
            logger.info(f"Unidade criada: {nome}")
            return nova_unidade

async def get_unidade_by_id(unidade_id: int) -> Optional[Unidade]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Unidade).where(Unidade.id == unidade_id))
        return result.scalar_one_or_none()

async def update_unidade(unidade_id: int, **kwargs) -> bool:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            stmt = update(Unidade).where(Unidade.id == unidade_id).values(**kwargs)
            result = await session.execute(stmt)
            logger.info(f"Unidade {unidade_id} atualizada.")
            return result.rowcount > 0

async def delete_unidade(unidade_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            stmt = delete(Unidade).where(Unidade.id == unidade_id)
            result = await session.execute(stmt)
            logger.info(f"Unidade {unidade_id} removida.")
            return result.rowcount > 0

# CRUD para Posicao
async def add_posicao(unidade_id: int, lat: float, lon: float) -> Posicao:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            pos = Posicao(unidade_id=unidade_id, latitude=lat, longitude=lon)
            session.add(pos)
            logger.info(f"Nova posição registrada para unidade {unidade_id}")
            return pos

# 4) Queries com Filtros e Paginação
async def get_unidades_paginated(
    nome_filter: Optional[str] = None, 
    tipo_filter: Optional[str] = None, 
    page: int = 1, 
    page_size: int = 10
) -> Sequence[Unidade]:
    async with AsyncSessionLocal() as session:
        query = select(Unidade)
        
        if nome_filter:
            query = query.where(Unidade.nome.ilike(f"%{nome_filter}%"))
        if tipo_filter:
            query = query.where(Unidade.tipo == tipo_filter)
            
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)
        
        result = await session.execute(query)
        return result.scalars().all()

async def get_posicoes_history(unidade_id: int, limit: int = 50) -> Sequence[Posicao]:
    async with AsyncSessionLocal() as session:
        query = select(Posicao).where(Posicao.unidade_id == unidade_id).order_by(Posicao.timestamp.desc()).limit(limit)
        result = await session.execute(query)
        return result.scalars().all()

# 5) Transação Assíncrona Complexa (Exemplo)
async def registrar_movimentacao_unidade(unidade_id: int, nova_lat: float, nova_lon: float, novo_status: Optional[str] = None):
    """
    Exemplo de transação atômica: Atualiza status da unidade e insere nova posição.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            try:
                # 1. Atualizar Unidade
                if novo_status:
                    await session.execute(
                        update(Unidade).where(Unidade.id == unidade_id).values(status=novo_status)
                    )
                
                # 2. Inserir Posição
                nova_pos = Posicao(unidade_id=unidade_id, latitude=nova_lat, longitude=nova_lon)
                session.add(nova_pos)
                
                logger.info(f"Transação de movimentação concluída para Unidade {unidade_id}")
            except Exception as e:
                logger.error(f"Erro na transação: {e}")
                await session.rollback()
                raise

# Exemplo de execução principal
async def main():
    await init_db()
    await seed_data()
    
    # Teste de listagem com paginação
    unidades = await get_unidades_paginated(tipo_filter="FPSO", page=1, page_size=2)
    print(f"Unidades encontradas: {[u.nome for u in unidades]}")
    
    # Teste de transação
    if unidades:
        uid = unidades[0].id
        await registrar_movimentacao_unidade(uid, -22.5, -40.3, "Operando")
        
    logger.info("Processamento finalizado.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass