import pytest
import httpx
from main import app
from agent.metrics import record_ast_lookup, record_lean_proof, record_cegis_probe

@pytest.mark.asyncio
async def test_prometheus_metrics_endpoint():
    # 1. Seed simulated event counters
    record_ast_lookup(is_hit=True)
    record_ast_lookup(is_hit=False)
    record_lean_proof(status="success")
    record_cegis_probe(result="verified")

    # 2. Query ASGI in-memory server
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    body = response.text

    # 3. Verify metric families exist in exposition output
    assert "continuous_agent_ast_cache_lookups_total" in body
    assert 'result="hit"' in body
    assert 'result="miss"' in body
    assert "continuous_agent_lean_proofs_total" in body
    assert 'status="success"' in body
    assert "continuous_agent_cegis_probes_total" in body
    assert 'result="verified"' in body
    assert "continuous_agent_island_fitness_best" in body
    assert "continuous_agent_island_phenotypic_entropy" in body
