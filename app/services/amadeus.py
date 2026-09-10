from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

try:
    import httpx
except ImportError:  # permite o sistema local iniciar antes de instalar a dependencia Amadeus
    httpx = None

from ..config import (
    AMADEUS_CLIENT_ID,
    AMADEUS_CLIENT_SECRET,
    AMADEUS_ENABLED,
    AMADEUS_ENV,
    AMADEUS_TIMEOUT_SECONDS,
)


class AmadeusError(RuntimeError):
    pass


@dataclass
class _TokenState:
    value: str = ""
    expires_at: float = 0.0


class AmadeusClient:
    """Cliente REST mínimo para Amadeus Self-Service.

    Por segurança, esta camada não cria reservas/PNRs. Ela deixa prontos
    autenticação, localizações, Flight Offers Search e Flight Offers Price.
    """

    def __init__(self) -> None:
        self.enabled = AMADEUS_ENABLED
        self.environment = "production" if AMADEUS_ENV in {"production", "prod"} else "test"
        self.base_url = "https://api.amadeus.com" if self.environment == "production" else "https://test.api.amadeus.com"
        self.client_id = AMADEUS_CLIENT_ID
        self.client_secret = AMADEUS_CLIENT_SECRET
        self.timeout = AMADEUS_TIMEOUT_SECONDS
        self._token = _TokenState()
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.client_id and self.client_secret)

    async def _access_token(self) -> str:
        if httpx is None:
            raise AmadeusError("Dependência httpx não instalada. Instale as dependências antes de ativar o Amadeus.")
        if not self.configured:
            raise AmadeusError("Integração Amadeus não configurada.")
        now = time.time()
        if self._token.value and self._token.expires_at > now + 30:
            return self._token.value
        async with self._lock:
            now = time.time()
            if self._token.value and self._token.expires_at > now + 30:
                return self._token.value
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/v1/security/oauth2/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            if response.status_code >= 400:
                raise AmadeusError(self._safe_error(response))
            payload = response.json()
            token = str(payload.get("access_token") or "")
            if not token:
                raise AmadeusError("Amadeus não retornou access_token.")
            expires_in = int(payload.get("expires_in") or 1800)
            self._token = _TokenState(token, time.time() + expires_in)
            return token

    @staticmethod
    def _safe_error(response: "httpx.Response") -> str:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                errors = payload.get("errors")
                if isinstance(errors, list) and errors:
                    item = errors[0] or {}
                    detail = item.get("detail") or item.get("title")
                    if detail:
                        return f"Amadeus HTTP {response.status_code}: {detail}"
                description = payload.get("error_description") or payload.get("error")
                if description:
                    return f"Amadeus HTTP {response.status_code}: {description}"
        except Exception:
            pass
        return f"Amadeus HTTP {response.status_code}"

    async def request(self, method: str, path: str, *, params: dict[str, Any] | None = None, json: Any = None) -> dict[str, Any]:
        token = await self._access_token()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(
                method.upper(),
                f"{self.base_url}{path}",
                params=params,
                json=json,
                headers={"Authorization": f"Bearer {token}"},
            )
        if response.status_code >= 400:
            raise AmadeusError(self._safe_error(response))
        return response.json()

    async def search_locations(self, keyword: str, *, sub_type: str = "AIRPORT,CITY", limit: int = 10) -> dict[str, Any]:
        return await self.request(
            "GET",
            "/v1/reference-data/locations",
            params={"subType": sub_type, "keyword": keyword, "page[limit]": max(1, min(limit, 20))},
        )

    async def search_flights(
        self,
        *,
        origin: str,
        destination: str,
        departure_date: str,
        adults: int = 1,
        return_date: str | None = None,
        children: int = 0,
        infants: int = 0,
        travel_class: str | None = None,
        non_stop: bool | None = None,
        currency: str = "BRL",
        max_results: int = 20,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "originLocationCode": origin.upper(),
            "destinationLocationCode": destination.upper(),
            "departureDate": departure_date,
            "adults": max(1, adults),
            "currencyCode": currency.upper(),
            "max": max(1, min(max_results, 50)),
        }
        if return_date:
            params["returnDate"] = return_date
        if children:
            params["children"] = max(0, children)
        if infants:
            params["infants"] = max(0, infants)
        if travel_class:
            params["travelClass"] = travel_class.upper()
        if non_stop is not None:
            params["nonStop"] = str(bool(non_stop)).lower()
        return await self.request("GET", "/v2/shopping/flight-offers", params=params)

    async def price_flight_offer(self, flight_offer: dict[str, Any], *, include_detailed_fare_rules: bool = False) -> dict[str, Any]:
        params = {"include": "detailed-fare-rules"} if include_detailed_fare_rules else None
        return await self.request(
            "POST",
            "/v1/shopping/flight-offers/pricing",
            params=params,
            json={"data": {"type": "flight-offers-pricing", "flightOffers": [flight_offer]}},
        )


amadeus_client = AmadeusClient()
