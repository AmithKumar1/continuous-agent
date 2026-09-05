import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from config import config
from agent.funsearch_service import funsearch_service
from agent.lean_synthesizer import Lean4ProofSynthesizer
from agent.formal_verifier import lean_verifier
from agent.gitops import gitops_publisher

logger = logging.getLogger("NightlyDiscovery")

async def send_telegram_notification(message: str):
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return
    import httpx
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(url, json=payload)
    except Exception as e:
        logger.error(f"Telegram alert error: {e}")

async def run_nightly_funsearch_pipeline():
    logger.info("Starting Nightly Autonomous Discovery Pipeline...")
    await send_telegram_notification("🌙 *Nightly Discovery Pipeline Launched*\nExecuting evolutionary discovery run...")

    # 1. Run FunSearch multi-island search
    await funsearch_service.start(evals_per_island=10)
    await asyncio.sleep(8)
    funsearch_service.stop()

    champ = funsearch_service.champion_program
    fitness = funsearch_service.top_fitness_score
    code = champ.code if champ else "def priority(item, bin_capacity):\n    return 1.0"

    # 2. Synthesize and check Lean 4 proof
    lean_proof = Lean4ProofSynthesizer.synthesize(code)
    is_verified, log = await lean_verifier.verify_code(lean_proof)

    # 3. If verified and fitness is high, submit Pull Request
    pr_result = None
    if fitness >= 0.80 and is_verified:
        pr_result = await gitops_publisher.create_discovery_pr(
            python_code=code,
            lean_proof=lean_proof,
            fitness_score=fitness
        )

    summary = (
        f"🏆 *Nightly Discovery Complete*\n\n"
        f"• Fitness: `{fitness:.4f}`\n"
        f"• Lean 4 Verified: `{is_verified}`\n"
        f"• PR Status: `{pr_result.get('pr_url') if pr_result and pr_result.get('success') else 'None'}`"
    )
    await send_telegram_notification(summary)
    logger.info("Nightly discovery run complete.")
