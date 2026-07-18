from typing import Any
from uuid import uuid4

import httpx

from app.config import Settings


class MobiusError(RuntimeError):
    pass


class MobiusClient:
    """Minimal Mobius/oneM2M HTTP binding for AE, CNT, and CIN resources."""

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
            headers["Content-Type"] = f"application/vnd.onem2m-res+json;ty={resource_type}"
        return headers

    async def close(self) -> None:
        await self.client.aclose()

    async def health(self) -> bool:
        try:
            response = await self.client.get("", headers=self._headers())
            return response.status_code < 500
        except httpx.HTTPError:
            return False

    async def ensure_structure(self) -> None:
        ae_path = f"/{self.settings.mobius_ae_name}"
        ae = await self.client.get(ae_path, headers=self._headers())
        if ae.status_code == 404:
            created = await self.client.post(
                "", headers=self._headers(2),
                json={"m2m:ae": {"rn": self.settings.mobius_ae_name, "api": "N.addhd.app", "rr": True}},
            )
            self._raise(created, "AE registration")
        elif ae.status_code >= 400:
            self._raise(ae, "AE retrieval")

        container_path = f"{ae_path}/{self.settings.mobius_data_container}"
        container = await self.client.get(container_path, headers=self._headers())
        if container.status_code == 404:
            created = await self.client.post(
                ae_path, headers=self._headers(3),
                json={"m2m:cnt": {"rn": self.settings.mobius_data_container}},
            )
            self._raise(created, "container registration")
        elif container.status_code >= 400:
            self._raise(container, "container retrieval")

    async def create_content_instance(self, content: Any) -> str | None:
        path = f"/{self.settings.mobius_ae_name}/{self.settings.mobius_data_container}"
        response = await self.client.post(
            path, headers=self._headers(4), json={"m2m:cin": {"con": content}}
        )
        self._raise(response, "content instance creation")
        body = response.json()
        return body.get("m2m:cin", {}).get("rn")

    @staticmethod
    def _raise(response: httpx.Response, operation: str) -> None:
        if response.status_code >= 400:
            detail = response.text[:500]
            raise MobiusError(f"{operation} failed ({response.status_code}): {detail}")

