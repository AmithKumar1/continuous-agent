import asyncio
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional
from agent.events import broker

class CegisTelemetryTracker:
    def __init__(self, max_history: int = 50):
        self.history: Deque[Dict[str, Any]] = deque(maxlen=max_history)
        self.total_checks: int = 0
        self.total_verified: int = 0
        self.total_violations: int = 0
        self.active_probes_count: int = 0
        self._lock = asyncio.Lock()

    async def record_event(
        self,
        status: str,
        invariant_name: str,
        island_id: int,
        generation: int,
        counterexample: Optional[Dict[str, Any]] = None,
        injected_sequence: Optional[List[float]] = None,
        total_probes: int = 0,
        solve_time_ms: float = 0.0
    ):
        async with self._lock:
            self.total_checks += 1
            if status == "VERIFIED":
                self.total_verified += 1
            elif status == "VIOLATED":
                self.total_violations += 1

            self.active_probes_count = total_probes

            event_payload = {
                "id": self.total_checks,
                "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                "status": status,
                "invariant_name": invariant_name,
                "island_id": island_id,
                "generation": generation,
                "counterexample": counterexample,
                "injected_sequence": injected_sequence,
                "total_probes": total_probes,
                "solve_time_ms": round(solve_time_ms, 2)
            }
            self.history.appendleft(event_payload)

        await broker.publish("cegis_event", {
            "event": event_payload,
            "metrics": self.get_metrics()
        })

    def get_metrics(self) -> Dict[str, Any]:
        rate = round((self.total_violations / self.total_checks * 100), 1) if self.total_checks > 0 else 0.0
        return {
            "total_checks": self.total_checks,
            "total_verified": self.total_verified,
            "total_violations": self.total_violations,
            "violation_rate_pct": rate,
            "active_probes_count": self.active_probes_count
        }

    def get_recent_events(self) -> List[Dict[str, Any]]:
        return list(self.history)

cegis_tracker = CegisTelemetryTracker()
