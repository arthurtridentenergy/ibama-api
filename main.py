import os
import sys
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, status
from fastapi.responses import PlainTextResponse

# ---------------------------------------------------------------------------
# Configuração mínima e lazy de logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Lazy logger pesado — carrega recursos custosos apenas na primeira chamada
_lazy_logger = None


def _get_lazy_logger():
    """Inicializa pesadamente (handlers externos, formatos, etc.) sob demanda."""
    global _lazy_logger
    if _lazy_logger is None:
        _lazy_logger = logging.getLogger("heavy_logging")
        # Exemplo: adicionar handler complexo, saneamento, queue handler etc.
        # Tudo que possa travar ou demorar no startup deve ficar aqui.
    return _lazy_logger


# ---------------------------------------------------------------------------
# Validação de variáveis críticas no startup
# ---------------------------------------------------------------------------
def _validate_critical_env() -> None:
    """Garante que variáveis essenciais existam antes de subir o app."""
    missing = []
    for var in ("JWT_SECRET_KEY", "SPINERGIE_API_KEY"):
        if not os.environ.get(var):
            missing.append(var)
    if missing:
        msg = (
            "\n"
            "=" * 70
            + "\n"
            + "CRITICAL CONFIGURATION ERROR\n"
            + "=" * 70
            + "\n"
            + "As seguintes variáveis de ambiente são obrigatórias e não foram definidas:\n"
            + "\n".join(f"  - {var}" for var in missing)
            + "\n"
            + "Defina-as no painel do Render (Environment) e redeploye.\n"
            + "=" * 70
        )
        logger.error(msg)
        raise RuntimeError(msg)


# ---------------------------------------------------------------------------
# Lifespan: otimizado — sem pesado no __init__
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Executa apenas o estritamente necessário antes de receber tráfego."""
    _validate_critical_env()
    logger.info("Startup concluído — variáveis críticas validadas.")
    yield
    logger.info("Shutdown iniciado.")


# ---------------------------------------------------------------------------
# App FastAPI
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Spinergie API",
    description="API otimizada para deploy no Render.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", response_class=PlainTextResponse)
async def health_check():
    """Health check rápido para o Render (<100 ms). Não execute queries lentas."""
    return PlainTextResponse(content="ok", status_code=status.HTTP_200_OK)


@app.get("/ready", response_class=PlainTextResponse)
async def readiness_check():
    """Pronto para receber tráfego após startup."""
    return PlainTextResponse(content="ready", status_code=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Importação lazy de rotas pesadas / lógicas de negócio
# ---------------------------------------------------------------------------
def _load_business_routers():
    """Carrega routers pesados apenas quando necessário."""
    # Exemplo: from app.routers import auth, vessels, spinergie
    # app.include_router(auth.router, prefix="/auth")
    # app.include_router(vessels.router, prefix="/vessels")
    # app.include_router(spinergie.router, prefix="/spinergie")
    _get_lazy_logger().info("Business routers carregados lazy.")


_load_business_routers()


# ---------------------------------------------------------------------------
# Entry point para Render
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")

    logger.info("Iniciando uvicorn em %s:%d", host, port)

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        workers=1,
        timeout_keep_alive=5,
        log_level="info",
    )