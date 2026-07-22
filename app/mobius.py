import asyncio
from typing import Any
from uuid import uuid4

import httpx

from app.config import Settings
from app.topology import MOBIUS_TOPOLOGY, SUBSCRIPTION_SOURCES


class MobiusError(RuntimeError):
    pass


class MobiusClient:
    """oneM2M HTTP binding for the fixed IOTCOSS AE topology."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url=settings.mobius_base_url.rstrip("/"),
            timeout=settings.mobius_timeout_seconds,
            headers={"Accept": "application/json"},
        )

    def _headers(self, resource_type: int | None = None) -> dict[str, str]:
        headers = {
            "X-M2M-Origin": self.settings.mobius_ae_id or self.settings.mobius_origin,
            "X-M2M-RI": uuid4().hex,
        }
        optional = {
            "X-API-KEY": self.settings.mobius_api_key,
            "X-AUTH-CUSTOM-LECTURE": self.settings.mobius_lecture,
            "X-AUTH-CUSTOM-CREATOR": self.settings.mobius_creator,
        }
        headers.update({key: value for key, value in optional.items() if value})
        if resource_type:
            # IOTCOSS Swagger proxy expects application/json;ty=N.
            headers["Content-Type"] = f"application/json;ty={resource_type}"
        return headers

    async def close(self) -> None:
        await self.client.aclose()

    async def health(self) -> bool:
        try:
            response = await self.client.get("/analyticsServer", headers=self._headers())
            return response.status_code < 500
        except httpx.HTTPError:
            return False

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            return await self.client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise MobiusError(f"Mobius connection failed: {exc}") from exc

    async def ensure_structure(self) -> None:
        await self.ensure_analytics_structure()
        await self.ensure_subscriptions()

    async def ensure_analytics_structure(self) -> None:
        analytics = "analyticsServer"
        await self._ensure_ae(analytics)
        for container in MOBIUS_TOPOLOGY[analytics].containers:
            await self._ensure_container(analytics, container)

    async def ensure_subscriptions(self) -> None:
        if self.settings.mobius_notification_uri:
            for ae_name, container in SUBSCRIPTION_SOURCES:
                await self._require_container(ae_name, container)
                await self._ensure_subscription(ae_name, container)

    async def _ensure_ae(self, ae_name: str) -> None:
        response = await self._request("GET", f"/{ae_name}", headers=self._headers())
        if response.status_code == 404:
            response = await self._request(
                "POST",
                "", headers=self._headers(2),
                json={"m2m:ae": {"rn": ae_name, "api": f"N.IOTCOSS.{ae_name}", "rr": True}},
            )
        self._raise(response, f"AE {ae_name}")

    async def _ensure_container(self, ae_name: str, container: str) -> None:
        path = f"/{ae_name}/{container}"
        response = await self._request("GET", path, headers=self._headers())
        if response.status_code == 404:
            response = await self._request(
                "POST",
                f"/{ae_name}", headers=self._headers(3),
                json={"m2m:cnt": {"rn": container}},
            )
        self._raise(response, f"container {ae_name}/{container}")

    async def _require_container(self, ae_name: str, container: str) -> None:
        response = await self._request(
            "GET", f"/{ae_name}/{container}", headers=self._headers()
        )
        if response.status_code == 404:
            raise MobiusError(
                f"Required device container does not exist: {ae_name}/{container}"
            )
        self._raise(response, f"device container {ae_name}/{container}")

    async def _ensure_subscription(self, ae_name: str, container: str) -> None:
        name = self.settings.mobius_subscription_name
        path = f"/{ae_name}/{container}/{name}"
        response = await self._get_subscription(path)
        if response.status_code == 404:
            response = await self._request(
                "POST",
                f"/{ae_name}/{container}", headers=self._headers(23),
                json={
                    "m2m:sub": {
                        "rn": name,
                        "enc": {"net": [3]},
                        "nu": [self.settings.mobius_notification_uri],
                        "nct": 2,
                    }
                },
            )
        elif response.status_code < 400:
            subscription = response.json().get("m2m:sub", {})
            expected = [self.settings.mobius_notification_uri]
            if subscription.get("nu") != expected:
                response = await self._request(
                    "PUT",
                    path,
                    headers={**self._headers(), "Content-Type": "application/json"},
                    json={"m2m:sub": {"nu": expected}},
                )
        self._raise(response, f"subscription {ae_name}/{container}/{name}")

    async def _get_subscription(self, path: str) -> httpx.Response:
        """Retry the intermittent non-unique-result error from the IOTCOSS proxy."""
        response: httpx.Response | None = None
        for attempt in range(self.settings.mobius_read_retry_attempts):
            response = await self._request("GET", path, headers=self._headers())
            if not (
                response.status_code == 400
                and "Query did not return a unique result" in response.text
            ):
                return response
            if attempt + 1 < self.settings.mobius_read_retry_attempts:
                await asyncio.sleep(
                    self.settings.mobius_read_retry_delay_seconds * (attempt + 1)
                )
        assert response is not None
        return response

    async def list_content_instances(
        self, ae_name: str, container: str
    ) -> list[dict[str, Any]]:
        response = await self._request(
            "GET",
            f"/{ae_name}/{container}?rcn=4",
            headers=self._headers(),
        )
        self._raise(response, f"retrieve {ae_name}/{container}")
        body = response.json()
        parent = body.get("m2m:cnt", body)
        instances = parent.get("m2m:cin", []) if isinstance(parent, dict) else []
        if isinstance(instances, dict):
            instances = [instances]
        return [item for item in instances if isinstance(item, dict)]

    async def create_content_instance(
        self, ae_name: str, container: str, content: Any
    ) -> str | None:
        if ae_name not in MOBIUS_TOPOLOGY:
            raise MobiusError(f"Unknown AE: {ae_name}")
        if container not in MOBIUS_TOPOLOGY[ae_name].containers:
            raise MobiusError(f"Unknown container: {ae_name}/{container}")
        response = await self._request(
            "POST",
            f"/{ae_name}/{container}",
            headers=self._headers(4),
            json={"m2m:cin": {"con": content}},
        )
        self._raise(response, f"content instance {ae_name}/{container}")
        return response.json().get("m2m:cin", {}).get("rn")

    @staticmethod
    def _raise(response: httpx.Response, operation: str) -> None:
        if response.status_code >= 400:
            raise MobiusError(
                f"{operation} failed ({response.status_code}): {response.text[:500]}"
            )
