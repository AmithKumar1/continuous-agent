# tests/test_scheduler_interventions.py
import pytest
from unittest.mock import AsyncMock, patch
from agent.island_profiler import IslandHealth
from agent.scheduler import TaskScheduler
from agent.nsga2 import NSGA2Individual
from agent.funsearch_service import FunSearchService, FunSearchIsland

@pytest.mark.asyncio
async def test_ring_migration_exchanges_elites():
    service = FunSearchService()
    # Create two islands
    island_0 = FunSearchIsland(island_id=0, max_capacity=10)
    island_1 = FunSearchIsland(island_id=1, max_capacity=10)

    # Populate Island 0 with high-performing candidate
    island_0.individuals.append(
        NSGA2Individual(id="h0_elite", code="return 1.0", packing_ratio=0.98, fuel_consumed=400, phenotype_signature="sig0")
    )
    # Populate Island 1 with baseline candidate
    island_1.individuals.append(
        NSGA2Individual(id="h1_base", code="return 2.0", packing_ratio=0.85, fuel_consumed=900, phenotype_signature="sig1")
    )

    service.islands = {0: island_0, 1: island_1}

    with patch("agent.funsearch_service.get_db") as mock_db:
        mock_conn = AsyncMock()
        mock_db.return_value.__aenter__.return_value = mock_conn

        await service.execute_ring_migration(elite_count=1)

    # Verify Island 1 received migrated elite from Island 0
    island_1_ids = [ind.id for ind in island_1.individuals]
    assert any("h0_elite_migrated" in i_id for i_id in island_1_ids)

    # Verify Island 0 received migrated individual from Island 1
    island_0_ids = [ind.id for ind in island_0.individuals]
    assert any("h1_base_migrated" in i_id for i_id in island_0_ids)


@pytest.mark.asyncio
async def test_cataclysmic_restart_preserves_pareto_and_evicts_stagnant():
    service = FunSearchService()
    island = FunSearchIsland(island_id=0, max_capacity=20)

    # Populate with 1 Pareto elite and 4 dominated individuals
    elite = NSGA2Individual(id="pareto_star", code="return 1.0", packing_ratio=0.99, fuel_consumed=300, phenotype_signature="star", rank=1)
    dominated = [
        NSGA2Individual(id=f"stale_{i}", code="return 0.1", packing_ratio=0.70, fuel_consumed=1500, phenotype_signature="stale", rank=2)
        for i in range(4)
    ]
    island.individuals = [elite] + dominated
    service.islands = {0: island}

    await service.execute_cataclysmic_restart(island_id=0, keep_pareto_elites=1)

    # Only 1 elite should survive
    assert len(island.individuals) == 1
    assert island.individuals[0].id == "pareto_star"
    # Prompt paradigm should shift away from default
    assert hasattr(island, "prompt_paradigm")
    assert island.prompt_paradigm != "STANDARD"


@pytest.mark.asyncio
async def test_scheduler_triggers_actions_from_profile():
    scheduler = TaskScheduler()

    # Mock profile_island returning CATACLYSMIC_RESTART for Island 0 and RING_MIGRATION for Island 1
    mock_health_0 = IslandHealth(
        island_id=0, total_evaluations=50, best_fitness=0.92, mean_fitness=0.92,
        phenotypic_entropy=0.1, is_plateaued=True, stagnation_generations=45,
        suggested_action="CATACLYSMIC_RESTART"
    )
    mock_health_1 = IslandHealth(
        island_id=1, total_evaluations=30, best_fitness=0.88, mean_fitness=0.88,
        phenotypic_entropy=0.4, is_plateaued=True, stagnation_generations=15,
        suggested_action="RING_MIGRATION"
    )

    with patch("agent.scheduler.get_db") as mock_db, \
         patch("agent.scheduler.profile_island", side_effect=[mock_health_0, mock_health_1]), \
         patch("agent.scheduler.funsearch_service.execute_cataclysmic_restart", new_callable=AsyncMock) as mock_restart, \
         patch("agent.scheduler.funsearch_service.execute_ring_migration", new_callable=AsyncMock) as mock_migration:

        # Mock database rows for two islands
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = [
            {"island_id": 0, "fitness": 0.92, "phenotype_signature": "sig0"},
            {"island_id": 1, "fitness": 0.88, "phenotype_signature": "sig1"}
        ]
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = mock_cursor
        mock_db.return_value.__aenter__.return_value = mock_conn

        await scheduler.run_supervisory_cycle()

        # Both interventions must have been dispatched
        mock_restart.assert_called_once_with(island_id=0)
        mock_migration.assert_called_once_with(elite_count=2)
