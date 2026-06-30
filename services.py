### services.py
"""Service layer: fetch and combine vessel & platform data."""
import asyncio
import logging
import requests
from typing import Any, Dict, List, Optional
from config import (
    EXTERNAL_API_URL,
    EXTERNAL_API_KEY,
    PLATFORMS,
    VESSELS,
)
from models import Platform, Vessel, VesselPlatformItem

logger = logging.getLogger(__name__)

async def _fetch_vessel_external(mmsi: str) -> Optional[Dict[str, Any]]:
    """
    Fetch vessel position from external AIS API.
    Falls back to static coordinates on failure.
    """
    if not EXTERNAL_API_KEY:
        logger.warning("External API key not configured, using static positions")
        return None

    url = f"{EXTERNAL_API_URL}/{mmsi}"
    headers = {
        "Authorization": f"Bearer {EXTERNAL_API_KEY}",
        "Accept": "application/json",
    }
    try:
        response = await asyncio.to_thread(
            requests.get, url, headers=headers, timeout=10
        )
        response.raise_for_status()
        data = response.json()
        lat = data.get("latitude")
        lon = data.get("longitude")
        if lat is not None and lon is not None:
            return {
                "latitude": float(lat),
                "longitude": float(lon),
                "source": "external",
            }
    except Exception as e:
        logger.error(f"Failed to fetch vessel {mmsi}: {e}")
    return None

async def get_platforms() -> List[Platform]:
    """Return list of hardcoded platforms."""
    platforms = []
    for pdata in PLATFORMS:
        platforms.append(Platform(**pdata))
    return platforms

async def get_vessels() -> List[Vessel]:
    """
    Fetch vessels with live coordinates if possible, otherwise fallback to static.
    """
    vessels = []
    for vdata in VESSELS:
        mmsi = vdata["mmsi"]
        live = await _fetch_vessel_external(mmsi)
        if live:
            lat = live["latitude"]
            lon = live["longitude"]
            logger.info(f"Vessel {vdata['name']} live from API: {lat}, {lon}")
        else:
            lat = vdata["static_latitude"]
            lon = vdata["static_longitude"]
            logger.info(f"Vessel {vdata['name']} using static coordinates")
        vessels.append(
            Vessel(
                name=vdata["name"],
                mmsi=vdata["mmsi"],
                license=vdata["license"],
                validity=vdata["validity"],
                observation=vdata["observation"],
                latitude=lat,
                longitude=lon,
            )
        )
    return vessels

async def get_all_vessels_platforms() -> List[VesselPlatformItem]:
    """
    Combine platforms and vessels into a single list of items.
    """
    platforms = await get_platforms()
    vessels = await get_vessels()
    items = []
    for p in platforms:
        items.append(
            VesselPlatformItem(
                type="platform",
                name=p.name,
                mmsi=p.mmsi,
                license=p.license,
                validity=p.validity,
                observation=p.observation,
                latitude=p.latitude,
                longitude=p.longitude,
            )
        )
    for v in vessels:
        items.append(
            VesselPlatformItem(
                type="vessel",
                name=v.name,
                mmsi=v.mmsi,
                license=v.license,
                validity=v.validity,
                observation=v.observation,
                latitude=v.latitude,
                longitude=v.longitude,
            )
        )
    return items