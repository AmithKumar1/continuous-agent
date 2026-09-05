import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from croniter import croniter
from agent.nightly_discovery import run_nightly_funsearch_pipeline

from agent.db import get_db
from agent.island_profiler import profile_island, IslandHealth
from agent.funsearch_service import funsearch_service
from agent.metrics import ISLAND_STAGNATION_COUNT, ISLAND_PHENOTYPIC_ENTROPY

logger = logging.getLogger("TaskScheduler")

class AgentTaskScheduler:
    def __init__(self):
        self.cron_expression = "0 2 * * *"  # Default: 02:00 AM UTC
        self.is_running = False
        self.is_executing = False
        self.last_run_utc: Optional[str] = None
        self._loop_task: Optional[asyncio.Task] = None
        self.supervisor_task: Optional[asyncio.Task] = None
        self._reschedule_event = asyncio.Event()

    def get_status(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        next_run_iso = None
        seconds_remaining = None

        if croniter.is_valid(self.cron_expression):
            cron = croniter(self.cron_expression, now)
            next_run_dt = cron.get_next(datetime)
            next_run_iso = next_run_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
            seconds_remaining = max(0, int((next_run_dt - now).total_seconds()))

        return {
            "cron_expression": self.cron_expression,
            "is_running": self.is_running,
            "is_executing": self.is_executing,
            "next_run_utc": next_run_iso,
            "seconds_remaining": seconds_remaining,
            "last_run_utc": self.last_run_utc or "None"
        }

    def update_cron(self, new_cron: str) -> bool:
        if not croniter.is_valid(new_cron):
            return False
        self.cron_expression = new_cron
        self._reschedule_event.set()
        logger.info(f"Cron expression updated to: {new_cron}")
        return True

    async def execute_pipeline(self):
        if self.is_executing:
            return
        self.is_executing = True
        try:
            await run_nightly_funsearch_pipeline()
            self.last_run_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        finally:
            self.is_executing = False

    async def run_supervisory_cycle(
        self,
        window_size: int = 20,
        epsilon: float = 0.0005,
        entropy_threshold: float = 0.6
    ):
        """
        Profiles all evolutionary islands, evaluates entropy and fitness plateaus,
        and triggers autonomous remediation (RING_MIGRATION or CATACLYSMIC_RESTART).
        """
        logger.info("Executing periodic supervisory health inspection...")

        # 1. Query recent heuristic generation history per island
        island_histories: Dict[int, List[Dict[str, Any]]] = {}
        async with get_db() as db:
            cursor = await db.execute(
                """
                SELECT island_id, fitness, phenotype_signature
                FROM heuristics
                WHERE fitness IS NOT NULL
                ORDER BY generation ASC, created_at ASC
                """
            )
            rows = await cursor.fetchall()

        for r in rows:
            i_id = r["island_id"]
            island_histories.setdefault(i_id, []).append({
                "fitness": float(r["fitness"]),
                "phenotype_signature": r["phenotype_signature"] or "default"
            })

        if not island_histories:
            logger.info("No evolutionary history found. Skipping supervisory checks.")
            return

        # 2. Profile each island
        profiles: Dict[int, IslandHealth] = {}
        migration_required = False

        for i_id, history in island_histories.items():
            health = profile_island(
                island_id=i_id,
                history=history,
                window_size=window_size,
                epsilon=epsilon,
                entropy_threshold=entropy_threshold
            )
            profiles[i_id] = health

            # Update Prometheus telemetry
            ISLAND_STAGNATION_COUNT.labels(island_id=str(i_id)).set(health.stagnation_generations)
            ISLAND_PHENOTYPIC_ENTROPY.labels(island_id=str(i_id)).set(health.phenotypic_entropy)

            # 3. Evaluate recommended actions
            if health.suggested_action == "CATACLYSMIC_RESTART":
                logger.warning(
                    f"Island {i_id} requires CATACLYSMIC_RESTART "
                    f"(Stagnation: {health.stagnation_generations} gens, Entropy: {health.phenotypic_entropy:.2f})."
                )
                await funsearch_service.execute_cataclysmic_restart(island_id=i_id)

            elif health.suggested_action == "RING_MIGRATION":
                logger.info(
                    f"Island {i_id} requires RING_MIGRATION "
                    f"(Stagnation: {health.stagnation_generations} gens, Entropy: {health.phenotypic_entropy:.2f})."
                )
                migration_required = True

        # Ring migration is coordinated across islands simultaneously
        if migration_required:
            logger.info("Triggering coordinated ring migration across islands.")
            await funsearch_service.execute_ring_migration(elite_count=2)

    async def _supervisory_worker(self, interval_seconds: int = 120):
        """Background loop executing health checks at scheduled intervals."""
        while self.is_running:
            try:
                await self.run_supervisory_cycle()
            except Exception as e:
                logger.error(f"Error in supervisory health cycle: {e}", exc_info=True)
            await asyncio.sleep(interval_seconds)

    async def _scheduler_loop(self):
        while self.is_running:
            now = datetime.now(timezone.utc)
            if not croniter.is_valid(self.cron_expression):
                await asyncio.sleep(10)
                continue

            cron = croniter(self.cron_expression, now)
            next_run = cron.get_next(datetime)
            delay = max(0.0, (next_run - now).total_seconds())

            try:
                await asyncio.wait_for(self._reschedule_event.wait(), timeout=delay)
                self._reschedule_event.clear()
            except asyncio.TimeoutError:
                if self.is_running:
                    await self.execute_pipeline()

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self._loop_task = asyncio.create_task(self._scheduler_loop())
        self.supervisor_task = asyncio.create_task(self._supervisory_worker(interval_seconds=120))
        logger.info("Dynamic task scheduler and supervisory loop started.")

    def stop(self):
        self.is_running = False
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
        if hasattr(self, "supervisor_task") and self.supervisor_task and not self.supervisor_task.done():
            self.supervisor_task.cancel()
        logger.info("Dynamic task scheduler and supervisory loop stopped.")

TaskScheduler = AgentTaskScheduler
task_scheduler = AgentTaskScheduler()
