import aiosqlite
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    REGISTRY
)
from agent.db import get_db
from agent.island_profiler import calculate_phenotypic_entropy, profile_island

# ---------------------------------------------------------------------------
# 1. Population & Evolution Metrics
# ---------------------------------------------------------------------------
ISLAND_FITNESS_BEST = Gauge(
    "continuous_agent_island_fitness_best",
    "Highest heuristic fitness recorded on the island",
    ["island_id"]
)
ISLAND_FITNESS_MEAN = Gauge(
    "continuous_agent_island_fitness_mean",
    "Rolling mean heuristic fitness on the island",
    ["island_id"]
)
ISLAND_PHENOTYPIC_ENTROPY = Gauge(
    "continuous_agent_island_phenotypic_entropy",
    "Shannon phenotypic diversity entropy on the island",
    ["island_id"]
)
ISLAND_PARETO_COUNT = Gauge(
    "continuous_agent_island_pareto_count",
    "Active count of Rank-1 non-dominated Pareto heuristics",
    ["island_id"]
)
ISLAND_STAGNATION_COUNT = Gauge(
    "continuous_agent_island_stagnation_generations",
    "Generations elapsed without fitness velocity improvement",
    ["island_id"]
)

# Initialize default labels for island 0 to guarantee presence in Prometheus scrapes
ISLAND_FITNESS_BEST.labels(island_id="0").set(0.0)
ISLAND_FITNESS_MEAN.labels(island_id="0").set(0.0)
ISLAND_PHENOTYPIC_ENTROPY.labels(island_id="0").set(1.0)
ISLAND_PARETO_COUNT.labels(island_id="0").set(0)
ISLAND_STAGNATION_COUNT.labels(island_id="0").set(0)

# ---------------------------------------------------------------------------
# 2. AST Cache & Transpiler Metrics
# ---------------------------------------------------------------------------
AST_CACHE_LOOKUPS = Counter(
    "continuous_agent_ast_cache_lookups_total",
    "Total AST memoization cache lookups",
    ["result"]  # "hit" | "miss"
)
AST_CACHE_HIT_RATIO = Gauge(
    "continuous_agent_ast_cache_hit_ratio",
    "Current effective AST memoization cache hit ratio"
)

# ---------------------------------------------------------------------------
# 3. Formal Verification Metrics
# ---------------------------------------------------------------------------
LEAN_PROOFS_TOTAL = Counter(
    "continuous_agent_lean_proofs_total",
    "Total Lean 4 formal verification theorem generation attempts",
    ["status"]  # "success" | "kernel_error" | "timeout"
)
CEGIS_PROBES_TOTAL = Counter(
    "continuous_agent_cegis_probes_total",
    "Z3 SMT contract invariant probes executed",
    ["result"]  # "verified" | "refuted" | "timeout"
)

# ---------------------------------------------------------------------------
# 4. Resource & Execution Costs
# ---------------------------------------------------------------------------
WASM_FUEL_CONSUMPTION = Histogram(
    "continuous_agent_wasm_fuel_consumed",
    "Distribution of Wasmtime instruction fuel consumed per evaluation",
    buckets=[250, 500, 1000, 2000, 5000, 10000, 25000, 50000]
)

def record_ast_lookup(is_hit: bool):
    """Tracks AST memoization hit/miss events."""
    status = "hit" if is_hit else "miss"
    AST_CACHE_LOOKUPS.labels(result=status).inc()

def record_lean_proof(status: str):
    """Tracks Lean 4 proof outcomes (status: success, kernel_error, timeout)."""
    LEAN_PROOFS_TOTAL.labels(status=status).inc()

def record_cegis_probe(result: str):
    """Tracks Z3 invariant checks (result: verified, refuted, timeout)."""
    CEGIS_PROBES_TOTAL.labels(result=result).inc()

async def sync_island_metrics_from_db():
    """Reads latest heuristics and island states from SQLite to refresh Gauges before scrape."""
    try:
        async with get_db() as db:
            # Update AST cache hit ratio if table exists
            try:
                cursor = await db.execute("SELECT COUNT(*) FROM ast_memo_cache;")
                row = await cursor.fetchone()
                total_cached = row[0] if row else 0
                if total_cached > 0:
                    AST_CACHE_HIT_RATIO.set(min(100.0, float(total_cached)))
            except Exception:
                pass

            # Retrieve per-island populations
            cursor = await db.execute(
                """
                SELECT island_id, fitness, phenotype_signature, pareto_rank, generation
                FROM heuristics
                WHERE fitness IS NOT NULL
                ORDER BY generation DESC
                """
            )
            rows = await cursor.fetchall()
    except Exception:
        rows = []

    if not rows:
        return

    # Aggregate by island
    islands = {}
    for r in rows:
        islands.setdefault(r["island_id"], []).append(r)

    for i_id, pop in islands.items():
        fits = [r["fitness"] for r in pop if r["fitness"] is not None]
        if fits:
            ISLAND_FITNESS_BEST.labels(island_id=str(i_id)).set(max(fits))
            ISLAND_FITNESS_MEAN.labels(island_id=str(i_id)).set(sum(fits) / len(fits))

        # Phenotypic Entropy
        sigs = [r["phenotype_signature"] or "default" for r in pop[-30:]]
        entropy = calculate_phenotypic_entropy(sigs)
        ISLAND_PHENOTYPIC_ENTROPY.labels(island_id=str(i_id)).set(entropy)

        # Active Pareto Count (Rank 1)
        pareto_count = sum(1 for r in pop if r["pareto_rank"] == 1)
        ISLAND_PARETO_COUNT.labels(island_id=str(i_id)).set(pareto_count)

        # Stagnation generations via profile_island
        history = [
            {
                "fitness": r["fitness"],
                "phenotype_signature": r["phenotype_signature"] or "default",
                "generation": r["generation"] if "generation" in r.keys() and r["generation"] is not None else 0
            }
            for r in sorted(pop, key=lambda x: (x["generation"] or 0) if "generation" in x.keys() and x["generation"] is not None else 0)
            if r["fitness"] is not None
        ]
        health = profile_island(i_id, history)
        ISLAND_STAGNATION_COUNT.labels(island_id=str(i_id)).set(health.stagnation_generations)
