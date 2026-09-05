# agent/audit_logger.py
import json
import logging
from typing import Any, Dict, Optional
from agent.db import get_db
from agent.adaptive_sampling import SamplingPolicy

logger = logging.getLogger("PolicyAudit")

async def record_policy_transition(
    island_id: int,
    entropy: float,
    old_policy: SamplingPolicy,
    new_policy: SamplingPolicy,
    details: Optional[Dict[str, Any]] = None
):
    """
    Logs an adaptive parameter shift (temperature, top_p, beam_width).
    Triggered when delta between old and new sampling parameters exceeds threshold.
    """
    payload = {
        "previous_temperature": old_policy.temperature,
        "previous_top_p": old_policy.top_p,
        "previous_beam_width": old_policy.beam_width,
        **(details or {})
    }
    
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO supervisor_policy_audit (
                island_id, event_type, entropy, temperature, top_p, beam_width,
                candidates_generated, candidates_accepted, details
            )
            VALUES (?, 'POLICY_TRANSITION', ?, ?, ?, ?, NULL, NULL, ?)
            """,
            (
                island_id,
                round(entropy, 4),
                new_policy.temperature,
                new_policy.top_p,
                new_policy.beam_width,
                json.dumps(payload)
            )
        )
        await db.commit()

    logger.debug(
        f"Island {island_id} policy transitioned: T={new_policy.temperature} "
        f"top_p={new_policy.top_p} K={new_policy.beam_width} (H={entropy:.3f})"
    )

async def record_beam_evaluation(
    island_id: int,
    entropy: float,
    policy: SamplingPolicy,
    candidates_generated: int,
    candidates_accepted: int,
    details: Optional[Dict[str, Any]] = None
):
    """
    Logs candidate yields and acceptance ratios for a parallel mutation beam.
    """
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO supervisor_policy_audit (
                island_id, event_type, entropy, temperature, top_p, beam_width,
                candidates_generated, candidates_accepted, details
            )
            VALUES (?, 'BEAM_EVALUATION', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                island_id,
                round(entropy, 4),
                policy.temperature,
                policy.top_p,
                policy.beam_width,
                candidates_generated,
                candidates_accepted,
                json.dumps(details or {})
            )
        )
        await db.commit()
