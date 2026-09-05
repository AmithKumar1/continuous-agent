import asyncio
import logging
import signal
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from config import config
from agent.db import Database
from agent.core import ContinuousAgent
from agent.scheduler import task_scheduler
from agent.state_persistence import init_evolution_tables
from agent.migrations import backfill_vector_store
from dashboard import app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ContinuousAgentMain")

agent_instance = None
agent_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent_instance, agent_task
    logger.info("Initializing Autonomous Continuous Discovery System...")

    # 1. Initialize SQLite storage layer and schema
    db = Database(db_path=config.DB_PATH)
    await db.init_db()
    await init_evolution_tables()

    # 2. Backfill vector index if chroma directory is empty
    try:
        await backfill_vector_store(db_path=config.DB_PATH)
    except Exception as e:
        logger.warning(f"Initial vector index check skipped: {e}")

    # 3. Instantiate and start the continuous agent heartbeat
    agent_instance = ContinuousAgent(db=db)
    agent_task = asyncio.create_task(agent_instance.run())

    # 4. Start the dynamic task scheduler
    task_scheduler.start()

    logger.info("System fully booted. FastAPI dashboard and continuous heartbeat active.")
    yield

    # Graceful shutdown
    logger.info("Shutdown signal received: cleaning up runtime services...")
    task_scheduler.stop()
    if agent_instance:
        agent_instance.stop()
    if agent_task and not agent_task.done():
        agent_task.cancel()
    logger.info("Shutdown completed.")

app.router.lifespan_context = lifespan

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
