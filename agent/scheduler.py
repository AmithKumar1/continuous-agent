import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from croniter import croniter
from agent.nightly_discovery import run_nightly_funsearch_pipeline

logger = logging.getLogger("TaskScheduler")

class AgentTaskScheduler:
    def __init__(self):
        self.cron_expression = "0 2 * * *"  # Default: 02:00 AM UTC
        self.is_running = False
        self.is_executing = False
        self.last_run_utc: Optional[str] = None
        self._loop_task: Optional[asyncio.Task] = None
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
        logger.info("Dynamic task scheduler started.")

    def stop(self):
        self.is_running = False
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
        logger.info("Dynamic task scheduler stopped.")

task_scheduler = AgentTaskScheduler()
