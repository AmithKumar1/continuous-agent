import threading
from typing import List, Optional
from dataclasses import dataclass

@dataclass(frozen=True)
class Counterexample:
    invariant_name: str
    item: float
    bin_capacity: float
    detail: Optional[str] = None

class DynamicDiagnosticSuite:
    def __init__(self):
        self._lock = threading.Lock()
        self.static_probes: List[List[float]] = [
            [10.0, 20.0, 30.0, 40.0, 15.0, 25.0, 35.0, 5.0, 45.0, 10.0],
            [50.0, 40.0, 30.0, 20.0, 10.0, 5.0, 15.0, 25.0, 35.0, 45.0],
            [5.0] * 20,
            [30.0, 30.0, 30.0, 10.0, 10.0, 10.0, 50.0, 50.0],
        ]
        self.counterexample_probes: List[List[float]] = []

    def get_probes(self) -> List[List[float]]:
        with self._lock:
            return list(self.static_probes) + list(self.counterexample_probes)

    def register_counterexample(self, ce: Counterexample):
        with self._lock:
            val = round(max(1.0, min(99.0, ce.item)), 1)
            cap = round(max(val, min(100.0, ce.bin_capacity)), 1)
            complement = round(cap - val, 1)

            if complement > 0.0:
                adversarial_seq = [complement, val, val, round(100.0 - val, 1)]
            else:
                adversarial_seq = [val, round(100.0 - val, 1), val]

            if adversarial_seq not in self.counterexample_probes:
                self.counterexample_probes.append(adversarial_seq)
