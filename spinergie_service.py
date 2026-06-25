import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import aiohttp
from aiohttp import ClientTimeout

logger = logging.getLogger(__name__)

SPINERGIE_BASE_URL = os.getenv("SPINERGIE_BASE_URL", "https://api.spinergie.com").rstrip("/")
SPINERGIE_API_KEY = os.getenv("SPINERGIE_API_KEY")

CACHE_TTL = timedelta(minutes=5)
_position_cache: Dict[str, Dict[str, Any]] = {}


def _is_cache_valid(mmsi: str) -> bool:
    """Verifica se existe cache válido para o MMSI informado."""
    entry = _position_cache.get(mmsi)
    if not entry:
        return False
    return datetime.now(timezone.utc) - entry["timestamp"] < CACHE_TTL


def _normalize_position(raw: Any, fallback_mmsi: str) -> Optional[Dict[str, Any]]:
    """Converte a resposta da Spinergie para o formato esperado pelo Swagger."""
    if not raw or not isinstance(raw, dict):
        logger.warning(f"Resposta inválida ou vazia da Spinergie para MMSI {fallback_mmsi}")
        return None

    mmsi = str(raw.get("mmsi") or fallback_mmsi)
    nome = raw.get("vesselName") or raw.get("nome") or "DESCONHECIDO"

    latitude = raw.get("latitude")
    longitude = raw.get("longitude")

    try:
        latitude = float(latitude) if latitude is not None else None
        longitude = float(longitude) if longitude is not None else None
    except (TypeError, ValueError) as exc:
        logger.warning(f"Coordenadas inválidas para MMSI {mmsi}: {exc}")
        latitude = None
        longitude = None

    timestamp = raw.get("timestamp") or raw.get("timestampAquisicao") or raw.get("lastReceived")
    if not timestamp:
        timestamp = datetime.now(timezone.utc).isoformat()

    position = {
        "mmsi": mmsi,
        "nome": nome,
        "latitude": latitude,
        "longitude": longitude,
        "timestampAquisicao": timestamp,
    }

    logger.debug(f"Posição normalizada para MMSI {mmsi}: {position}")
    return position


async def fetch_vessel_position_async(mmsi: str) -> Optional[Dict[str, Any]]:
    """
    Busca a posição em tempo real de uma embarcação no Spinergie.

    Utiliza o endpoint GET /sd/api/vessel/sfm-latest-locations com autenticação
    via ApiKey. Mantém cache local de 5 minutos para evitar sobrecarga na API.
    """
    if not SPINERGIE_API_KEY:
        logger.error("Variável de ambiente SPINERGIE_API_KEY não configurada")
        return None

    if not mmsi or not mmsi.strip():
        logger.error("MMSI não informado")
        return None

    mmsi = mmsi.strip()

    if _is_cache_valid(mmsi):
        logger.debug(f"Retornando posição do cache para MMSI {mmsi}")
        return _position_cache[mmsi]["data"]

    url = f"{SPINERGIE_BASE_URL}/sd/api/vessel/sfm-latest-locations"
    headers = {
        "Authorization": f"ApiKey {SPINERGIE_API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    params = {"mmsi": mmsi}
    timeout = ClientTimeout(total=15)

    logger.info(f"Consultando Spinergie para MMSI {mmsi} - URL: {url}")

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers, params=params) as response:
                logger.debug(f"Spinergie respondeu {response.status} para MMSI {mmsi}")

                if response.status == 200:
                    data = await response.json()
                    logger.debug(f"Resposta bruta da Spinergie para MMSI {mmsi}: {data}")

                    if isinstance(data, list):
                        if not data:
                            logger.warning(f"Spinergie retornou lista vazia para MMSI {mmsi}")
                            return None
                        raw = data[0]
                    else:
                        raw = data

                    position = _normalize_position(raw, mmsi)
                    if position:
                        _position_cache[mmsi] = {
                            "data": position,
                            "timestamp": datetime.now(timezone.utc),
                        }
                        logger.info(f"Posição obtida e cacheada para MMSI {mmsi}")
                    return position

                elif response.status == 401:
                    logger.error("Falha de autenticação na API Spinergie (401). Verifique SPINERGIE_API_KEY")
                    return None

                elif response.status == 403:
                    logger.error("Acesso negado à API Spinergie (403)")
                    return None

                elif response.status == 404:
                    logger.warning(f"Embarcação não encontrada no Spinergie (404) para MMSI {mmsi}")
                    return None

                elif response.status >= 500:
                    logger.error(f"Erro no servidor Spinergie ({response.status}) para MMSI {mmsi}")
                    return None

                else:
                    body = await response.text()
                    logger.error(f"Resposta inesperada do Spinergie ({response.status}) para MMSI {mmsi}: {body}")
                    return None

    except asyncio.TimeoutError:
        logger.error(f"Timeout ao consultar Spinergie para MMSI {mmsi}")
        return None

    except aiohttp.ClientConnectionError as exc:
        logger.error(f"Erro de conexão com Spinergie para MMSI {mmsi}: {exc}")
        return None

    except aiohttp.ClientResponseError as exc:
        logger.error(f"Erro na resposta do Spinergie para MMSI {mmsi}: {exc.status} - {exc.message}")
        return None

    except aiohttp.ClientError as exc:
        logger.error(f"Erro do cliente HTTP ao consultar Spinergie para MMSI {mmsi}: {exc}")
        return None

    except Exception as exc:
        logger.exception(f"Erro inesperado ao consultar Spinergie para MMSI {mmsi}: {exc}")
        return None


def get_posicao(mmsi: str) -> Optional[Dict[str, Any]]:
    """
    Função existente mantida para compatibilidade com a API Swagger.

    Retorna a posição atual da embarcação no formato esperado, realizando a
    consulta assíncrona ao Spinergie de forma transparente.
    """
    logger.info(f"get_posicao chamado para MMSI {mmsi}")
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            logger.debug("Loop de eventos em execução; agendando coroutine")
            future = asyncio.run_coroutine_threadsafe(fetch_vessel_position_async(mmsi), loop)
            return future.result(timeout=20)
        return loop.run_until_complete(fetch_vessel_position_async(mmsi))
    except Exception as exc:
        logger.exception(f"Erro ao executar get_posicao para MMSI {mmsi}: {exc}")
        return None


async def get_posicao_async(mmsi: str) -> Optional[Dict[str, Any]]:
    """Versão assíncrona de get_posicao para uso em contextos async."""
    return await fetch_vessel_position_async(mmsi)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    exemplo_mmsi = "710001720"
    resultado = get_posicao(exemplo_mmsi)
    print(resultado)