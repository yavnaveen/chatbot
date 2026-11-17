import time
import secrets
from collections import defaultdict, deque
from threading import Lock
from typing import Optional

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from backend.app.config import API_SECRET_KEY, RATE_LIMIT_PER_MINUTE

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_client_ip(request: Request) -> str:
    """Extract real client IP taking Cloudflare Tunnel and proxies into account."""
    # Cloudflare passes the real visitor IP in CF-Connecting-IP
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()

    # Standard proxy forwarded-for
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()

    if request.client and request.client.host:
        return request.client.host

    return "127.0.0.1"


async def verify_api_key(
    request: Request,
    api_key: Optional[str] = Security(api_key_header)
) -> str:
    """Validate X-API-Key header against configured API_SECRET_KEY using constant-time comparison."""
    if not API_SECRET_KEY:
        # If no key configured in environment, allow (or log warning)
        return "unsecured"

    # Also check Authorization Bearer as a fallback
    provided_key = api_key
    if not provided_key:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            provided_key = auth_header[7:].strip()

    if not provided_key or not secrets.compare_digest(provided_key, API_SECRET_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Provide a valid 'X-API-Key' header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return provided_key


class InMemoryRateLimiter:
    """Thread-safe sliding-window rate limiter per client IP."""

    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self.window_seconds = 60.0
        self._clients: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, client_id: str) -> None:
        now = time.time()
        window_start = now - self.window_seconds

        with self._lock:
            timestamps = self._clients[client_id]

            # Evict timestamps outside the sliding window
            while timestamps and timestamps[0] < window_start:
                timestamps.popleft()

            if len(timestamps) >= self.requests_per_minute:
                retry_after = max(1, int(timestamps[0] + self.window_seconds - now) + 1)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded. Please try again later.",
                    headers={"Retry-After": str(retry_after)},
                )

            timestamps.append(now)


rate_limiter = InMemoryRateLimiter(requests_per_minute=RATE_LIMIT_PER_MINUTE)


async def rate_limit_dependency(request: Request) -> None:
    """FastAPI dependency to rate limit requests per client IP."""
    client_ip = get_client_ip(request)
    rate_limiter.check(client_ip)
