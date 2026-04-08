"""
Tests for the health check endpoint (/health).
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """GET /health → 200 with required fields."""
    resp = await client.get("/health")
    assert resp.status_code == 200

    data = resp.json()
    assert "status" in data
    assert "version" in data
    assert data["status"] in ("healthy", "degraded")
