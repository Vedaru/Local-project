import httpx
from typing import Optional


async def post_json(url: str, payload: dict, timeout: float = 15.0, headers: Optional[dict] = None) -> dict:
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()


async def get_json(url: str, timeout: float = 5.0, headers: Optional[dict] = None) -> dict:
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
