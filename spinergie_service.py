import asyncio
import logging
import time
import json
from typing import Any, Dict, List, Optional
import httpx

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "service": "spinergie_service", "message": "%(message)s"}'
)
logger = logging.getLogger(__name__)

class SpinergieService:
    """
    Service for interacting with the Spinergie API.
    Features: Async HTTP, Exponential Retry, TTL Caching, and Fallback Data.
    """

    # Fallback data used when API is unreachable and cache is empty
    FALLBACK_VESSELS = [
        {"id": "v-001", "name": "Spinergie Alpha", "status": "active", "lat": 43.2965, "lon": 5.3698, "last_update": "fallback"},
        {"id": "v-002", "name": "Spinergie Beta", "status": "moored", "lat": 51.5074, "lon": -0.1278, "last_update": "fallback"},
        {"id": "v-003", "name": "Spinergie Gamma", "status": "underway", "lat": 40.7128, "lon": -74.0060, "last_update": "fallback"}
    ]

    def __init__(
        self, 
        api_key: str = "YOUR_API_KEY", 
        base_url: str = "https://api.spinergie.com/v1",
        cache_ttl: int = 300,  # 5 minutes in seconds
        max_retries: int = 3
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.cache_ttl = cache_ttl
        self.max_retries = max_retries
        
        # Internal Cache: { "data": List, "expires_at": float }
        self._cache: Dict[str, Any] = {"data": None, "expires_at": 0}
        
        # Async HTTP Client
        self.client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            timeout=httpx.Timeout(10.0, connect=5.0)
        )

    async def _get_cached_data(self) -> Optional[List[Dict]]:
        """Returns data if cache is valid."""
        if self._cache["data"] and time.time() < self._cache["expires_at"]:
            logger.info("Cache hit: returning cached vessel data")
            return self._cache["data"]
        return None

    def _set_cache(self, data: List[Dict]):
        """Updates cache with new data and TTL."""
        self._cache["data"] = data
        self._cache["expires_at"] = time.time() + self.cache_ttl
        logger.debug("Cache updated with fresh API data")

    async def get_vessels(self) -> List[Dict]:
        """
        Fetches real-time vessel data from Spinergie.
        Implements exponential retry and falls back to hardcoded data on failure.
        """
        # 1. Try Cache
        cached_data = await self._get_cached_data()
        if cached_data:
            return cached_data

        # 2. Try API with Exponential Retry
        attempt = 0
        while attempt < self.max_retries:
            try:
                logger.info(f"Requesting vessel data (Attempt {attempt + 1}/{self.max_retries})")
                response = await self.client.get(f"{self.base_url}/vessels/realtime")
                
                # Raise for 4xx/5xx errors
                response.raise_for_status()
                
                data = response.json()
                # Handle potential wrapper in response
                vessels = data.get("data", data) if isinstance(data, dict) else data
                
                self._set_cache(vessels)
                return vessels

            except (httpx.HTTPStatusError, httpx.RequestError, json.JSONDecodeError) as e:
                attempt += 1
                if attempt >= self.max_retries:
                    logger.error(f"API failed after {self.max_retries} attempts: {str(e)}")
                    break
                
                # Exponential backoff: 2s, 4s, 8s...
                wait_time = 2 ** attempt
                logger.warning(f"API error: {str(e)}. Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)

        # 3. Fallback to Hardcoded Data
        logger.warning("Returning fallback vessel data due to API unavailability")
        return self.FALLBACK_VESSELS

    async def close(self):
        """Closes the HTTP client session."""
        await self.client.aclose()
        logger.info("SpinergieService client closed")

# Example usage block
async def example_usage():
    service = SpinergieService(api_key="test_key")
    try:
        vessels = await service.get_vessels()
        print(f"Successfully retrieved {len(vessels)} vessels.")
    finally:
        await service.close()

if __name__ == "__main__":
    asyncio.run(example_usage())