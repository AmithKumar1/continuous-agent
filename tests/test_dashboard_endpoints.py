import pytest
import httpx
from config import config
from main import app

@pytest.mark.asyncio
async def test_auth_fail():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/state")
        assert resp.status_code in (401, 403)

@pytest.mark.asyncio
async def test_state_endpoint():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"Authorization": f"Bearer {config.DASHBOARD_API_KEY}"}
        resp = await client.get("/api/state", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "iteration" in data
        assert "status" in data

@pytest.mark.asyncio
async def test_cegis_verify_custom_endpoint():
    payload = {
        "code": "def priority(item: float, bin_capacity: float) -> float:\n    return 1.0 / (bin_capacity - item)",
        "timeout_ms": 1500
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"Authorization": f"Bearer {config.DASHBOARD_API_KEY}"}
        resp = await client.post("/api/cegis/verify-custom", json=payload, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["verified"] is False
        assert "counterexample" in data

@pytest.mark.asyncio
async def test_pareto_profile_endpoint():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"Authorization": f"Bearer {config.DASHBOARD_API_KEY}"}
        resp = await client.get("/api/evolution/pareto-profile", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_candidates" in data
        assert "pareto_frontier_count" in data
        assert "pareto_points" in data
        assert "all_points" in data
        assert "islands" in data

@pytest.mark.asyncio
async def test_policy_audit_endpoint():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"Authorization": f"Bearer {config.DASHBOARD_API_KEY}"}
        resp = await client.get("/api/evolution/policy-audit", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
