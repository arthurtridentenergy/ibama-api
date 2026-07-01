"""Spinergie API service module.

Provides an asynchronous client for the Spinergie API with retry logic,
exponential backoff, timeout/HTTP error handling, MMSI normalization,
ISO 8601 (UTC) timestamps, TTL-based caching and detailed logging.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import aiohttp
from aiohttp import ClientError, ClientResponseError, ClientTimeout

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    """Return current UTC time as ISO 8601 string ending with 'Z'."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond:06d}Z"


@dataclass
class CacheEntry:
    """Internal cache entry storing a value and its expiration time."""

    value: Any
    expires_at: float


@dataclass
class SpinergieResult:
    """Structured result returned by SpinergieClient.

    Attributes:
        mmsi: Vessel MMSI as string.
        data: Raw payload returned by the Spinergie API.
        timestamp: ISO 8601 UTC timestamp ending with 'Z'.
        source: Indicates whether the result came from cache or network.
        metadata: Extra metadata about the request/response.
    """

    mmsi: str
    data: Any
    timestamp: str
    source: str = "network"
    metadata: Dict[str, Any] = field(default_factory=dict)


class SpinergieClient:
    """Asynchronous client for the Spinergie API.

    Args:
        base_url: Base URL for the Spinergie API.
        api_key: API key used for authentication.
        timeout: Request timeout in seconds.
        max_retries: Maximum number of retry attempts.
        backoff_base: Base multiplier (seconds) for exponential backoff.
        backoff_max: Maximum backoff wait time in seconds.
        cache_ttl: Time-to-live for cached responses in seconds.
        session: Optional pre-existing aiohttp.ClientSession.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 30.0,
        max_retries: int = 5,
        backoff_base: float = 1.0,
        backoff_max: float = 60.0,
        cache_ttl: float = 300.0,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url must not be empty")
        if not api_key:
            raise ValueError("api_key must not be empty")
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if cache_ttl < 0:
            raise ValueError("cache_ttl must be >= 0")

        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = ClientTimeout(total=timeout)
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.cache_ttl = cache_ttl
        self._session = session
        self._owns_session = session is None
        self._cache: Dict[str, CacheEntry] = {}

        logger.debug(
            "SpinergieClient initialized (base_url=%s, timeout=%ss, "
            "max_retries=%s, backoff_base=%ss, backoff_max=%ss, cache_ttl=%ss)",
            self.base_url,
            timeout,
            self.max_retries,
            self.backoff_base,
            self.backoff_max,
            self.cache_ttl,
        )

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        """Return the current aiohttp session, creating one if needed."""
        if self._session is None or self._session.closed:
            logger.debug("Creating new aiohttp.ClientSession")
            self._session = aiohttp.ClientSession(timeout=self.timeout)
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        """Close the underlying HTTP session if owned by this client."""
        if self._session is not None and self._owns_session and not self._session.closed:
            logger.debug("Closing owned aiohttp.ClientSession")
            await self._session.close()

    async def __aenter__(self) -> "SpinergieClient":
        await self._get_session()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _cache_key(self, mmsi: str, endpoint: str) -> str:
        return f"{endpoint}:{mmsi}"

    def _get_cached(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if entry is None:
            logger.debug("Cache miss for key=%s", key)
            return None
        if time.monotonic() >= entry.expires_at:
            logger.debug("Cache expired for key=%s", key)
            self._cache.pop(key, None)
            return None
        logger.debug("Cache hit for key=%s", key)
        return entry.value

    def _set_cached(self, key: str, value: Any) -> None:
        expires_at = time.monotonic() + self.cache_ttl
        self._cache[key] = CacheEntry(value=value, expires_at=expires_at)
        logger.debug("Cached key=%s ttl=%ss expires_at=%.3f", key, self.cache_ttl, expires_at)

    def clear_cache(self) -> None:
        """Remove all cached entries."""
        count = len(self._cache)
        self._cache.clear()
        logger.info("Cache cleared (%s entries removed)", count)

    # ------------------------------------------------------------------
    # MMSI helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_mmsi(mmsi: Any) -> str:
        """Convert MMSI (int or str) to a normalized string."""
        if mmsi is None:
            raise ValueError("mmsi must not be None")
        try:
            normalized = str(int(mmsi))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid MMSI value: {mmsi!r}") from exc
        logger.debug("Normalized MMSI %r -> %s", mmsi, normalized)
        return normalized

    # ------------------------------------------------------------------
    # Retry/backoff helpers
    # ------------------------------------------------------------------

    def _backoff_delay(self, attempt: int) -> float:
        """Compute exponential backoff delay for a given attempt (0-based)."""
        delay = min(self.backoff_base * (2 ** attempt), self.backoff_max)
        logger.debug("Backoff delay for attempt=%s: %.3fs", attempt, delay)
        return delay

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Any] = None,
    ) -> Any:
        """Perform an HTTP request with retry and exponential backoff.

        Raises:
            aiohttp.ClientError: If all retries are exhausted.
            asyncio.TimeoutError: If the request times out on every attempt.
        """
        last_exception: Optional[BaseException] = None

        for attempt in range(self.max_retries + 1):
            logger.info(
                "HTTP %s %s attempt=%s/%s params=%s",
                method,
                url,
                attempt + 1,
                self.max_retries + 1,
                params,
            )

            session = await self._get_session()
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            }

            try:
                async with session.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers=headers,
                ) as response:
                    response.raise_for_status()
                    data = await response.json(content_type=None)
                    logger.info(
                        "HTTP %s %s succeeded status=%s attempt=%s",
                        method,
                        url,
                        response.status,
                        attempt + 1,
                    )
                    return data

            except asyncio.TimeoutError as exc:
                last_exception = exc
                logger.warning(
                    "Timeout on %s %s attempt=%s: %s",
                    method,
                    url,
                    attempt + 1,
                    exc,
                )
            except ClientResponseError as exc:
                last_exception = exc
                logger.warning(
                    "HTTP error %s on %s %s attempt=%s: %s",
                    exc.status,
                    method,
                    url,
                    attempt + 1,
                    exc.message,
                )
                # Do not retry on client errors (4xx) except 429.
                if 400 <= exc.status < 500 and exc.status != 429:
                    raise
            except ClientError as exc:
                last_exception = exc
                logger.warning(
                    "Client error on %s %s attempt=%s: %s",
                    method,
                    url,
                    attempt + 1,
                    exc,
                )

            if attempt >= self.max_retries:
                break

            delay = self._backoff_delay(attempt)
            logger.info("Retrying in %.3fs (attempt=%s)", delay, attempt + 1)
            await asyncio.sleep(delay)

        logger.error(
            "All retries exhausted for %s %s (attempts=%s)",
            method,
            url,
            self.max_retries + 1,
        )
        if isinstance(last_exception, Exception):
            raise last_exception
        raise ClientError(f"Request failed for {method} {url}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_vessel_data(
        self,
        mmsi: Any,
        *,
        endpoint: str = "/vessels",
        use_cache: bool = True,
    ) -> SpinergieResult:
        """Fetch vessel data from Spinergie by MMSI.

        Args:
            mmsi: Vessel MMSI (int or str). Will be normalized to string.
            endpoint: API endpoint path (appended to base_url).
            use_cache: Whether to use the TTL cache.

        Returns:
            SpinergieResult containing normalized MMSI, payload, and timestamp.
        """
        mmsi_str = self._normalize_mmsi(mmsi)
        url = f"{self.base_url}{endpoint}"
        params = {"mmsi": mmsi_str}
        cache_key = self._cache_key(mmsi_str, endpoint)

        if use_cache:
            cached = self._get_cached(cache_key)
            if cached is not None:
                return SpinergieResult(
                    mmsi=mmsi_str,
                    data=cached,
                    timestamp=_utc_now_iso(),
                    source="cache",
                    metadata={"endpoint": endpoint, "cached": True},
                )

        logger.info("Fetching Spinergie data for MMSI=%s from %s", mmsi_str, url)
        data = await self._request_with_retry("GET", url, params=params)

        if use_cache:
            self._set_cached(cache_key, data)

        return SpinergieResult(
            mmsi=mmsi_str,
            data=data,
            timestamp=_utc_now_iso(),
            source="network",
            metadata={"endpoint": endpoint, "cached": False},
        )

    async def fetch_raw(
        self,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        method: str = "GET",
        json: Optional[Any] = None,
        use_cache: bool = False,
    ) -> Any:
        """Generic fetch method with retry/backoff and optional caching.

        Args:
            endpoint: API endpoint path (appended to base_url).
            params: Query parameters.
            method: HTTP method.
            json: JSON body for POST/PUT requests.
            use_cache: Whether to use the TTL cache.

        Returns:
            Parsed JSON response from the Spinergie API.
        """
        url = f"{self.base_url}{endpoint}"
        cache_key = self._cache_key(method, endpoint) + ":" + str(params)

        if use_cache:
            cached = self._get_cached(cache_key)
            if cached is not None:
                return cached

        data = await self._request_with_retry(method, url, params=params, json=json)

        if use_cache:
            self._set_cached(cache_key, data)

        return data