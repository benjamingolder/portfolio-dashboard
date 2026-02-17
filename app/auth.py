"""CloudFlare Access JWT validation middleware."""
from __future__ import annotations

import logging
import time

import httpx
import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class CloudFlareAccessMiddleware(BaseHTTPMiddleware):
    """Validates the Cf-Access-Jwt-Assertion header against CloudFlare's JWKS."""

    def __init__(self, app, team_domain: str, audience: str):
        super().__init__(app)
        self.certs_url = f"https://{team_domain}.cloudflareaccess.com/cdn-cgi/access/certs"
        self.audience = audience
        self.issuer = f"https://{team_domain}.cloudflareaccess.com"
        self._jwks: dict | None = None
        self._jwks_fetched_at: float = 0

    async def _get_jwks(self) -> dict:
        """Fetch and cache JWKS keys (refresh every 10 minutes)."""
        now = time.time()
        if self._jwks and now - self._jwks_fetched_at < 600:
            return self._jwks
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(self.certs_url)
            resp.raise_for_status()
            self._jwks = resp.json()
            self._jwks_fetched_at = now
            logger.info("CloudFlare Access JWKS refreshed")
        return self._jwks

    async def dispatch(self, request: Request, call_next):
        token = request.headers.get("Cf-Access-Jwt-Assertion")
        if not token:
            return JSONResponse(
                {"detail": "Authentication required"},
                status_code=403,
            )

        try:
            jwks = await self._get_jwks()
            # Decode header to find the right key
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")

            # Find matching key
            rsa_key = None
            for key in jwks.get("keys", []):
                if key.get("kid") == kid:
                    rsa_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
                    break

            if not rsa_key:
                # Refresh keys and retry (key rotation)
                self._jwks = None
                jwks = await self._get_jwks()
                for key in jwks.get("keys", []):
                    if key.get("kid") == kid:
                        rsa_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
                        break

            if not rsa_key:
                logger.warning("No matching JWKS key found for kid=%s", kid)
                return JSONResponse(
                    {"detail": "Invalid token: no matching key"},
                    status_code=403,
                )

            payload = jwt.decode(
                token,
                rsa_key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
            )
            # Store the user email in request state for potential future use
            request.state.cf_user_email = payload.get("email", "")

        except jwt.ExpiredSignatureError:
            return JSONResponse({"detail": "Token expired"}, status_code=403)
        except jwt.InvalidTokenError as e:
            logger.warning("Invalid CF Access token: %s", e)
            return JSONResponse({"detail": "Invalid token"}, status_code=403)
        except Exception as e:
            logger.error("Auth error: %s", e)
            return JSONResponse({"detail": "Authentication error"}, status_code=403)

        return await call_next(request)
